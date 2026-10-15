import json
import logging
import math
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from .auth import AuthenticatedUser, get_current_user
from .analysis import (
    build_response,
    list_ollama_models,
    ollama_extract,
    rules_extract,
)
from .backup import create_backup, get_backup_root, list_backups
from .db import (
    create_document_record,
    create_shipment,
    delete_analysis_by_id,
    delete_document_record,
    get_analysis_by_id,
    get_connection,
    get_document_by_id,
    get_duplicate_document,
    get_finding_reviews,
    get_finding_reviews_for_analysis,
    get_latest_analysis_for_shipment,
    get_shipment_by_id,
    get_shipment_by_reference,
    init_db,
    list_analyses,
    list_analyses_for_shipment,
    list_documents_for_shipment,
    list_shipments,
    record_finding_review,
    save_analysis,
    update_analysis_response_json,
    update_document_record,
    update_shipment,
    delete_shipment,
    create_cargo_calculation,
    get_cargo_calculation_by_id,
    list_cargo_calculations,
    update_cargo_calculation,
    delete_cargo_calculation,
    get_cargo_calculations_for_shipment,
)
from .cbm_engine import (
    CargoLineInput,
    calculate_cargo_aggregate,
    compare_all_containers_for_cargo,
    normalize_dimension_to_meters,
    normalize_weight_to_kg,
)
from .documents import (
    ALLOWED_EXTENSIONS,
    detect_document_type,
    extract_text,
    extract_text_with_metadata,
    read_upload,
    read_upload_with_bytes,
    sanitize_filename,
)
from .master_data import (
    create_customer,
    create_product,
    create_supplier,
    delete_customer,
    delete_product,
    delete_supplier,
    get_customer_by_id,
    get_product_by_id,
    get_supplier_by_id,
    list_customers,
    list_erp_audit_logs,
    list_products,
    list_suppliers,
    update_customer,
    update_product,
    update_supplier,
    verify_role_permission,
)
from .procurement import (
    create_goods_receipt,
    create_purchase_order,
    get_goods_receipt_by_id,
    get_purchase_order_by_id,
    list_goods_receipts,
    list_inventory_balances,
    list_inventory_movements,
    list_purchase_orders,
    post_goods_receipt_to_inventory,
    transition_purchase_order_status,
    update_purchase_order,
)
from .readiness import calculate_shipment_readiness
from .review import process_review_action
from .schemas import (
    AuditListResponse,
    AuditLogListResponse,
    CargoCalculationListResponse,
    CargoCalculationRecord,
    CargoCalculationRequest,
    CargoCalculationResponse,
    CargoLineResponse,
    ContainerEstimateRequest,
    ContainerEstimateResponse,
    CustomerCreate,
    CustomerListResponse,
    CustomerResponse,
    CustomerUpdate,
    DocumentListResponse,
    DocumentResponse,
    DocumentUpdate,
    ProductCreate,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
    ReviewActionRequest,
    ShipmentCreate,
    ShipmentListResponse,
    ShipmentReadinessResponse,
    ShipmentResponse,
    ShipmentUpdate,
    SupplierCreate,
    SupplierListResponse,
    SupplierResponse,
    SupplierUpdate,
    GoodsReceiptCreate,
    GoodsReceiptListResponse,
    GoodsReceiptResponse,
    InventoryBalanceListResponse,
    InventoryBalanceResponse,
    InventoryMovementListResponse,
    InventoryMovementResponse,
    PurchaseOrderCreate,
    PurchaseOrderListResponse,
    PurchaseOrderResponse,
    PurchaseOrderUpdate,
)
from .storage import (
    compute_file_hash,
    delete_document_file,
    get_document_file_path,
    get_storage_dir,
    save_document_file,
)

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent.parent
load_dotenv(APP_DIR.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("tradesathi.api")

MAX_UPLOAD_MB = max(1, int(os.getenv("MAX_UPLOAD_MB", "10")))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
CORS_ORIGINS = [
    value.strip()
    for value in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if value.strip()
]


def validate_production_config() -> list[str]:
    """
    Validate that configuration meets production hardening criteria.
    Returns list of fatal configuration violations (empty if valid).
    """
    env = os.getenv("ENVIRONMENT") or os.getenv("TRADESATHI_ENV") or "development"
    if env.lower() not in ("production", "staging"):
        return []

    errors: list[str] = []

    # 1. Reject test role simulator in production
    if os.getenv("TRADESATHI_TEST_ROLE_SIMULATOR") == "1":
        errors.append("TRADESATHI_TEST_ROLE_SIMULATOR must never be enabled in production.")

    # 2. Reject wildcard CORS in production
    cors_env = os.getenv("CORS_ORIGINS", "")
    if "*" in cors_env:
        errors.append("CORS_ORIGINS cannot contain wildcard '*' in production.")

    # 3. Reject insecure default/dummy secret keys
    secret_key = os.getenv("TRADESATHI_SECRET_KEY") or os.getenv("JWT_SECRET")
    insecure_defaults = {"secret", "changeme", "admin", "password", "123456", "default", "tradesathi"}
    if secret_key:
        if secret_key.strip().lower() in insecure_defaults or len(secret_key.strip()) < 16:
            errors.append("TRADESATHI_SECRET_KEY must be at least 16 characters and not a default value.")

    # 4. Storage directory must be accessible
    try:
        s_dir = get_storage_dir()
        if not s_dir.exists():
            errors.append("Document storage directory does not exist.")
    except Exception as exc:
        errors.append(f"Storage path resolution failed: {type(exc).__name__}")

    return errors


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI startup and shutdown lifecycle management with operational diagnostic checks."""
    logger.info("Initializing TradeSathi AI API v0.2.0...")
    prod_errors = validate_production_config()
    if prod_errors:
        for err in prod_errors:
            logger.error("PRODUCTION CONFIGURATION FATAL ERROR: %s", err)
        raise RuntimeError(f"Startup aborted due to production configuration errors: {'; '.join(prod_errors)}")

    init_db()
    try:
        with get_connection() as conn:
            cursor = conn.execute("PRAGMA integrity_check")
            res = cursor.fetchone()
            logger.info("SQLite startup integrity check: %s", res[0] if res else "ok")
    except Exception as exc:
        logger.error("Database initialization check error: %s", exc)

    storage_p = get_storage_dir()
    logger.info("Document storage verified at %s", storage_p)
    backup_p = get_backup_root()
    logger.info("Backup repository verified at %s", backup_p)
    yield
    logger.info("TradeSathi AI API shutdown complete.")


app = FastAPI(
    title="TradeSathi AI API",
    version="0.2.0",
    description="Local-first export document analysis & reconciliation engine",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "PATCH", "PUT", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests_middleware(request: Request, call_next):
    """Structured request logging middleware tracking latency and status without logging document contents."""
    start_time = time.perf_counter()
    client_ip = request.client.host if request.client else "unknown"
    try:
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.info("%s %s -> %d (%.2f ms) [%s]", request.method, request.url.path, response.status_code, duration_ms, client_ip)
        return response
    except Exception as exc:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.exception("Unhandled error processing %s %s from %s (%.2f ms): %s", request.method, request.url.path, client_ip, duration_ms, exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error. Check server logs for diagnostics."},
        )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Global exception handler preventing leakage of internal tracebacks, paths, or secrets."""
    logger.exception("Unhandled exception on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Check server logs for diagnostics."},
    )


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


@app.get("/health/live")
@app.get("/api/health/live")
async def health_live() -> dict[str, Any]:
    """Process liveness probe indicating ASGI server is alive and receiving HTTP traffic."""
    return {"status": "alive", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/health/ready")
@app.get("/api/health/ready")
async def health_ready(response: Response) -> dict[str, Any]:
    """Application readiness probe confirming DB availability, storage writability, and worker health."""
    db_ok = False
    storage_ok = False
    errors: list[str] = []

    try:
        with get_connection() as conn:
            row = conn.execute("SELECT 1").fetchone()
            if row and row[0] == 1:
                db_ok = True
    except Exception as exc:
        errors.append(f"database_unavailable: {type(exc).__name__}")

    try:
        s_dir = get_storage_dir()
        if s_dir.is_dir() and os.access(str(s_dir), os.W_OK):
            storage_ok = True
        else:
            errors.append("storage_unwritable")
    except Exception as exc:
        errors.append(f"storage_error: {type(exc).__name__}")

    expired_leases = 0
    try:
        with get_connection() as conn:
            now_iso = datetime.now(timezone.utc).isoformat()
            row = conn.execute(
                "SELECT COUNT(*) FROM collaboration_notifications WHERE delivery_status = 'processing' AND lease_expires_at <= ?",
                (now_iso,),
            ).fetchone()
            expired_leases = row[0] if row else 0
    except Exception:
        pass

    is_ready = db_ok and storage_ok
    if not is_ready:
        response.status_code = 503
        return {
            "status": "unhealthy",
            "version": "0.2.0",
            "errors": errors,
            "expired_leases": expired_leases,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    return {
        "status": "ready",
        "version": "0.2.0",
        "database": "connected",
        "storage": "writable",
        "expired_leases": expired_leases,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/health")
async def health() -> dict:
    """Diagnostic health check verifying DB connectivity, storage status, and optional Ollama inference."""
    db_status = "connected"
    try:
        with get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception as exc:
        db_status = f"unhealthy: {type(exc).__name__}"

    storage_status = "writable" if get_storage_dir().is_dir() else "unavailable"

    ollama_status = "unavailable"
    models: list[str] = []
    note = "Rules-based fallback remains available. Start Ollama to enable open-weight AI inference."
    try:
        models = await list_ollama_models(OLLAMA_BASE_URL)
        ollama_status = "connected"
        note = f"Ollama connected with {len(models)} installed model(s)."
    except (httpx.HTTPError, ValueError):
        pass

    is_healthy = db_status == "connected" and storage_status == "writable"

    return {
        "status": "ok" if is_healthy else "degraded",
        "version": "0.2.0",
        "database": db_status,
        "storage": storage_status,
        "ollama": ollama_status,
        "models": models,
        "max_upload_mb": MAX_UPLOAD_MB,
        "note": note,
    }


@app.get("/api/models")
async def models() -> dict:
    try:
        model_list = await list_ollama_models(OLLAMA_BASE_URL)
        return {"available": True, "models": model_list}
    except httpx.HTTPError:
        return {
            "available": False,
            "models": [],
            "message": "Cannot reach Ollama. Start it or check OLLAMA_BASE_URL in backend/.env.",
        }


def find_sample_directory() -> Path | None:
    """Resolve sample-documents folder across common development and root layouts."""
    candidates = [
        PROJECT_ROOT / "sample-documents",
        Path.cwd() / "sample-documents",
        APP_DIR.parent / "sample-documents",
        APP_DIR / "sample-documents",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


@app.get("/api/samples")
async def get_samples() -> dict:
    """Return preloaded sample documents so the user can test the workflow with 1 click."""
    sample_dir = find_sample_directory()
    if not sample_dir:
        raise HTTPException(
            status_code=404,
            detail="Sample documents folder 'sample-documents' not found on the server.",
        )

    samples = []
    target_files = ["commercial_invoice.txt", "packing_list.txt"]
    for filename in target_files:
        file_path = sample_dir / filename
        if file_path.is_file():
            try:
                samples.append({
                    "filename": filename,
                    "content": file_path.read_text(encoding="utf-8"),
                })
            except Exception as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to read sample file '{filename}': {exc}",
                )

    if not samples:
        raise HTTPException(
            status_code=404,
            detail=f"No sample files found in {sample_dir}. Expected: {', '.join(target_files)}.",
        )

    return {"samples": samples}


# ==========================================
# Shipment Management Endpoints (Milestone 2B)
# ==========================================


@app.post("/api/shipments", response_model=ShipmentResponse, status_code=201)
async def create_new_shipment(payload: ShipmentCreate):
    """Create a new shipment record."""
    ref = payload.reference.strip()
    if not ref:
        raise HTTPException(status_code=400, detail="Shipment reference cannot be empty.")

    existing = get_shipment_by_reference(ref)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Shipment reference '{ref}' already exists. Use a unique reference.",
        )

    created = create_shipment(payload.model_dump())
    return created


@app.get("/api/shipments", response_model=ShipmentListResponse)
async def get_all_shipments(
    search: str | None = Query(default=None, description="Search by ref, exporter, buyer, port"),
    status: str | None = Query(default=None, description="Filter by status"),
    limit: int = Query(default=50, ge=1, le=100),
):
    """List shipment records with optional search and status filtering."""
    shipments = list_shipments(search=search, status=status, limit=limit)
    return {"shipments": shipments, "total": len(shipments)}


@app.get("/api/shipments/{shipment_id}", response_model=ShipmentResponse)
async def get_single_shipment(shipment_id: str):
    """Retrieve full details of a specific shipment."""
    shipment = get_shipment_by_id(shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail=f"Shipment '{shipment_id}' not found.")
    return shipment


@app.patch("/api/shipments/{shipment_id}", response_model=ShipmentResponse)
async def update_existing_shipment(shipment_id: str, payload: ShipmentUpdate):
    """Update shipment metadata with uniqueness check if reference is modified."""
    shipment = get_shipment_by_id(shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail=f"Shipment '{shipment_id}' not found.")

    updates = payload.model_dump(exclude_unset=True)
    if "reference" in updates and updates["reference"] is not None:
        new_ref = updates["reference"].strip()
        if not new_ref:
            raise HTTPException(status_code=400, detail="Shipment reference cannot be empty.")
        existing = get_shipment_by_reference(new_ref)
        if existing and existing["id"] != shipment_id:
            raise HTTPException(
                status_code=409,
                detail=f"Shipment reference '{new_ref}' already exists on another shipment.",
            )
        updates["reference"] = new_ref

    updated = update_shipment(shipment_id, updates)
    return updated


@app.get("/api/shipments/{shipment_id}/analyses")
async def get_analyses_for_shipment_endpoint(shipment_id: str):
    """List linked reconciliation audits for this shipment."""
    shipment = get_shipment_by_id(shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail=f"Shipment '{shipment_id}' not found.")
    analyses = list_analyses_for_shipment(shipment_id)
    return {"analyses": analyses, "shipment": shipment}


@app.delete("/api/shipments/{shipment_id}", response_model=ShipmentResponse)
async def delete_shipment_endpoint(shipment_id: str):
    """
    Delete a shipment record.
    Preserves audit history: analyses previously linked to this shipment remain in the system
    with shipment_id unlinked (null), preventing corruption of historical compliance audits.
    Document register files for this shipment are cleaned up safely.
    """
    shipment = get_shipment_by_id(shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail=f"Shipment '{shipment_id}' not found.")

    docs = list_documents_for_shipment(shipment_id)
    for doc in docs:
        storage_key = doc.get("storage_key")
        if storage_key:
            try:
                delete_document_file(storage_key)
            except Exception:
                pass

    deleted = delete_shipment(shipment_id)
    return deleted


# ==========================================
# Document Register Endpoints (Milestone 2C)
# ==========================================


@app.post(
    "/api/shipments/{shipment_id}/documents",
    response_model=DocumentListResponse,
    status_code=201,
)
async def upload_shipment_documents(
    shipment_id: str,
    files: list[UploadFile] = File(...),
    document_type: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    duplicate_action: str = Form(default="reject"),  # "reject" or "replace"
):
    """
    Safely store shipment document files and persist document register records.
    Validates file extensions, size, content, safe naming, and prevents silent overwriting.
    """
    shipment = get_shipment_by_id(shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail=f"Shipment '{shipment_id}' not found.")

    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one document.")
    if len(files) > 8:
        raise HTTPException(status_code=400, detail="Upload no more than 8 documents at once.")

    created_docs = []
    for upload in files:
        raw_name = upload.filename or "upload.txt"
        clean_name = sanitize_filename(raw_name)
        suffix = Path(clean_name).suffix.lower()

        if suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type for {clean_name}. Use PDF, TXT, EML, or DOCX.",
            )

        content = await upload.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
            raise HTTPException(
                status_code=413,
                detail=f"{clean_name} exceeds the {limit_mb} MB upload limit.",
            )
        if not content or not content.strip():
            raise HTTPException(status_code=400, detail=f"{clean_name} is empty.")

        # Ensure text extraction succeeds
        try:
            extracted_text = extract_text(clean_name, content)
        except ValueError as exc:
            msg = str(exc)
            if "Scanned PDFs require OCR" in msg:
                raise HTTPException(status_code=422, detail=msg) from exc
            raise HTTPException(status_code=400, detail=msg) from exc

        file_hash = compute_file_hash(content)

        # Transparent duplicate checking
        dup = get_duplicate_document(shipment_id, file_hash=file_hash, filename=clean_name)
        if dup:
            if duplicate_action == "replace":
                delete_document_record(dup["id"])
                delete_document_file(dup["storage_key"])
            else:
                if dup["file_hash"] == file_hash:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Duplicate document detected: '{clean_name}' has identical content "
                            f"to existing document '{dup['original_filename']}' ({dup['id']}). "
                            f"Duplicate upload rejected."
                        ),
                    )
                else:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Document with filename '{clean_name}' already exists for shipment {shipment_id} ({dup['id']}). "
                            f"To upload a revised version, select 'Replace' or delete the existing document first."
                        ),
                    )

        # Heuristic or explicit document type determination
        assigned_type = document_type.strip() if document_type and document_type.strip() else None
        if not assigned_type or assigned_type == "unknown":
            assigned_type = detect_document_type(clean_name, extracted_text)

        # Persist bytes safely
        uid, storage_key, _ = save_document_file(shipment_id, clean_name, content)

        # Record in database
        doc_record = create_document_record({
            "id": uid,
            "shipment_id": shipment_id,
            "original_filename": raw_name,
            "clean_filename": clean_name,
            "document_type": assigned_type,
            "storage_key": storage_key,
            "file_size": len(content),
            "file_hash": file_hash,
            "processing_status": "completed",
            "review_status": "uploaded",
            "notes": notes.strip() if notes else None,
            "last_reviewed_by": None,
            "last_reviewed_at": None,
            "review_notes": None,
        })
        created_docs.append(doc_record)

    return {"documents": created_docs, "total": len(created_docs)}


@app.get(
    "/api/shipments/{shipment_id}/documents",
    response_model=DocumentListResponse,
)
async def list_shipment_documents_endpoint(shipment_id: str):
    """Retrieve all document records attached to a shipment."""
    shipment = get_shipment_by_id(shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail=f"Shipment '{shipment_id}' not found.")
    docs = list_documents_for_shipment(shipment_id)
    return {"documents": docs, "total": len(docs)}


@app.get(
    "/api/shipments/{shipment_id}/documents/{document_id}",
    response_model=DocumentResponse,
)
async def get_single_document_endpoint(shipment_id: str, document_id: str):
    """Retrieve metadata for a specific shipment document record."""
    doc = get_document_by_id(document_id)
    if not doc or doc["shipment_id"] != shipment_id:
        raise HTTPException(
            status_code=404,
            detail=f"Document '{document_id}' not found on shipment '{shipment_id}'.",
        )
    return doc


@app.patch(
    "/api/shipments/{shipment_id}/documents/{document_id}",
    response_model=DocumentResponse,
)
async def update_document_metadata_and_review_endpoint(
    shipment_id: str,
    document_id: str,
    payload: DocumentUpdate,
):
    """
    Update document review status, document type, or review notes.
    Audit fields (timestamp, reviewer) are automatically recorded.
    """
    doc = get_document_by_id(document_id)
    if not doc or doc["shipment_id"] != shipment_id:
        raise HTTPException(
            status_code=404,
            detail=f"Document '{document_id}' not found on shipment '{shipment_id}'.",
        )

    updates = payload.model_dump(exclude_unset=True)
    if "review_status" in updates and updates["review_status"] is not None:
        now_iso = datetime.now(timezone.utc).isoformat()
        updates["last_reviewed_at"] = now_iso
        if not updates.get("last_reviewed_by"):
            updates["last_reviewed_by"] = "User"

    updated = update_document_record(document_id, updates)
    return updated


@app.delete("/api/shipments/{shipment_id}/documents/{document_id}")
async def delete_document_endpoint(shipment_id: str, document_id: str):
    """Remove a document record and delete its underlying file from disk safely."""
    doc = get_document_by_id(document_id)
    if not doc or doc["shipment_id"] != shipment_id:
        raise HTTPException(
            status_code=404,
            detail=f"Document '{document_id}' not found on shipment '{shipment_id}'.",
        )

    deleted = delete_document_record(document_id)
    if deleted and deleted.get("storage_key"):
        delete_document_file(deleted["storage_key"])
    return {"status": "deleted", "id": document_id}


@app.get("/api/shipments/{shipment_id}/documents/{document_id}/download")
async def download_document_endpoint(shipment_id: str, document_id: str):
    """Download stored document file with path traversal protection."""
    doc = get_document_by_id(document_id)
    if not doc or doc["shipment_id"] != shipment_id:
        raise HTTPException(
            status_code=404,
            detail=f"Document '{document_id}' not found on shipment '{shipment_id}'.",
        )

    file_path = get_document_file_path(doc["storage_key"])
    if not file_path or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Document file not found in local storage.")

    return FileResponse(
        path=file_path,
        filename=doc["original_filename"],
        media_type="application/octet-stream",
    )


@app.get("/api/documents/{document_id}/download")
async def download_document_direct_endpoint(document_id: str):
    """Direct route for downloading stored document file by document record ID."""
    doc = get_document_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document '{document_id}' not found.")

    file_path = get_document_file_path(doc["storage_key"])
    if not file_path or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Document file not found in local storage.")

    return FileResponse(
        path=file_path,
        filename=doc["original_filename"],
        media_type="application/octet-stream",
    )


@app.patch("/api/documents/{document_id}", response_model=DocumentResponse)
async def update_document_direct_endpoint(document_id: str, payload: DocumentUpdate):
    """Direct route for updating human review status and notes on a document."""
    doc = get_document_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document '{document_id}' not found.")

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return doc

    if "review_status" in updates and updates["review_status"]:
        updates["last_reviewed_at"] = datetime.now(timezone.utc).isoformat()

    updated = update_document_record(document_id, updates)
    return updated


@app.delete("/api/documents/{document_id}")
async def delete_document_direct_endpoint(document_id: str):
    """Direct route for removing a document record and deleting its persisted file."""
    doc = get_document_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document '{document_id}' not found.")

    deleted = delete_document_record(document_id)
    if deleted and deleted.get("storage_key"):
        delete_document_file(deleted["storage_key"])
    return {"status": "deleted", "id": document_id}


# ==========================================
# Readiness Dashboard Endpoint (Milestone 2C)
# ==========================================


@app.get(
    "/api/shipments/{shipment_id}/readiness",
    response_model=ShipmentReadinessResponse,
)
async def get_shipment_readiness_endpoint(shipment_id: str):
    """
    Compute explainable shipment readiness status.
    Blocks readiness on missing required documents, unverified reviews, or critical discrepancies.
    """
    shipment = get_shipment_by_id(shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail=f"Shipment '{shipment_id}' not found.")

    docs = list_documents_for_shipment(shipment_id)
    latest_analysis = get_latest_analysis_for_shipment(shipment_id)

    readiness = calculate_shipment_readiness(
        shipment=shipment,
        documents=docs,
        latest_analysis=latest_analysis,
    )
    return readiness


# ==========================================
# Reconcile Attached Documents (Milestone 2C)
# ==========================================


@app.post("/api/shipments/{shipment_id}/reconcile")
async def reconcile_shipment_documents_endpoint(
    shipment_id: str,
    model: str = Form(default=""),
) -> JSONResponse:
    """
    Execute reconciliation audit directly on documents stored in the shipment register.
    """
    shipment = get_shipment_by_id(shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail=f"Shipment '{shipment_id}' not found.")

    docs = list_documents_for_shipment(shipment_id)
    if not docs:
        raise HTTPException(
            status_code=400,
            detail="No documents attached to this shipment. Upload documents to the register first.",
        )

    source_docs: list[tuple[str, str, str, list[dict], str | None]] = []  # (doc_id, filename, text, pages_meta, file_hash)
    for doc in docs:
        path = get_document_file_path(doc["storage_key"])
        if not path or not path.is_file():
            continue
        content = path.read_bytes()
        try:
            text, pages_meta, _ = extract_text_with_metadata(doc["clean_filename"], content)
            source_docs.append((doc["id"], doc["original_filename"], text, pages_meta, doc.get("file_hash")))
        except ValueError:
            continue

    if not source_docs:
        raise HTTPException(
            status_code=400,
            detail="Unable to extract readable text from attached documents for reconciliation.",
        )

    selected_model = model.strip()
    available_models: list[str] = []
    if selected_model:
        try:
            available_models = await list_ollama_models(OLLAMA_BASE_URL)
        except httpx.HTTPError:
            available_models = []
        if selected_model not in available_models:
            raise HTTPException(
                status_code=400,
                detail=f"Selected model '{selected_model}' is not available from Ollama.",
            )

    extracted = []
    mode = "rules_fallback"
    used_model = None

    if selected_model:
        try:
            for doc_id, filename, text, pages_meta, f_hash in source_docs:
                extracted.append(
                    await ollama_extract(
                        OLLAMA_BASE_URL,
                        selected_model,
                        filename,
                        text,
                        doc_id=doc_id,
                        pages_meta=pages_meta,
                        file_hash=f_hash,
                    )
                )
            mode = "ollama"
            used_model = selected_model
        except Exception as exc:
            extracted = [
                rules_extract(filename, text, doc_id=doc_id, pages_meta=pages_meta, file_hash=f_hash)
                for doc_id, filename, text, pages_meta, f_hash in source_docs
            ]
            for doc in extracted:
                doc.extraction_notes.append(
                    f"Ollama inference failed ({type(exc).__name__}); deterministic rules fallback used."
                )
    else:
        extracted = [
            rules_extract(filename, text, doc_id=doc_id, pages_meta=pages_meta, file_hash=f_hash)
            for doc_id, filename, text, pages_meta, f_hash in source_docs
        ]

    analysis_id = f"anl-{uuid.uuid4().hex[:10]}"
    response = build_response(
        extracted,
        mode,
        used_model,
        analysis_id=analysis_id,
        shipment_id=shipment_id,
    )
    response_data = response.model_dump(mode="json")

    # Persist in SQLite
    save_analysis(
        analysis_id=analysis_id,
        mode=mode,
        model=used_model,
        status=response.summary.status,
        headline=response.summary.headline,
        filenames=[doc.filename for doc in response.documents],
        discrepancy_count=len(
            [d for d in response.discrepancies if d.severity in ("critical", "warning")]
        ),
        response_data=response_data,
        shipment_id=shipment_id,
    )

    return JSONResponse(content=response_data)


# ==========================================
# Document Analysis & Reconciliation Endpoints
# ==========================================


@app.post("/api/analyze")
async def analyze(
    files: list[UploadFile] = File(...),
    model: str = Form(default=""),
    shipment_id: str | None = Form(default=None),
) -> JSONResponse:
    if not files:
        return JSONResponse(status_code=400, content={"detail": "Upload at least one document."})
    if len(files) > 8:
        return JSONResponse(
            status_code=400, content={"detail": "Upload no more than 8 documents at once."}
        )

    # Validate linked shipment if provided
    active_shipment_id: str | None = None
    if shipment_id and shipment_id.strip():
        clean_shipment_id = shipment_id.strip()
        shipment = get_shipment_by_id(clean_shipment_id)
        if not shipment:
            return JSONResponse(
                status_code=404,
                content={
                    "detail": f"Shipment '{clean_shipment_id}' not found. Cannot link reconciliation to nonexistent shipment."
                },
            )
        active_shipment_id = clean_shipment_id

    source_payloads: list[tuple[str, str, str, bytes, list[dict], str]] = []
    for upload in files:
        doc_id, filename, text, content = await read_upload_with_bytes(upload, MAX_UPLOAD_BYTES)
        _, pages_meta, _ = extract_text_with_metadata(filename, content)
        file_hash = compute_file_hash(content)
        source_payloads.append((doc_id, filename, text, content, pages_meta, file_hash))

    # If linked to a shipment, persist uploaded files to shipment documents if not already present
    if active_shipment_id:
        for doc_id, filename, text, content, pages_meta, file_hash in source_payloads:
            clean_name = sanitize_filename(filename)
            existing = get_duplicate_document(
                active_shipment_id, file_hash=file_hash, filename=clean_name
            )
            if not existing:
                try:
                    uid, storage_key, _ = save_document_file(
                        active_shipment_id, clean_name, content, doc_id=doc_id
                    )
                    doc_type = detect_document_type(clean_name, text)
                    create_document_record({
                        "id": uid,
                        "shipment_id": active_shipment_id,
                        "original_filename": filename,
                        "clean_filename": clean_name,
                        "document_type": doc_type,
                        "storage_key": storage_key,
                        "file_size": len(content),
                        "file_hash": file_hash,
                        "processing_status": "completed",
                        "review_status": "uploaded",
                    })
                except Exception:
                    # Non-fatal during analyze
                    pass

    selected_model = model.strip()
    available_models: list[str] = []
    if selected_model:
        try:
            available_models = await list_ollama_models(OLLAMA_BASE_URL)
        except httpx.HTTPError:
            available_models = []
        if selected_model not in available_models:
            return JSONResponse(
                status_code=400,
                content={
                    "detail": f"Selected model '{selected_model}' is not available from Ollama. Refresh models and select an installed one."
                },
            )

    extracted = []
    mode = "rules_fallback"
    used_model = None

    if selected_model:
        try:
            for doc_id, filename, text, content, pages_meta, file_hash in source_payloads:
                extracted.append(
                    await ollama_extract(
                        OLLAMA_BASE_URL,
                        selected_model,
                        filename,
                        text,
                        doc_id=doc_id,
                        pages_meta=pages_meta,
                        file_hash=file_hash,
                    )
                )
            mode = "ollama"
            used_model = selected_model
        except Exception as exc:
            extracted = [
                rules_extract(filename, text, doc_id=doc_id, pages_meta=pages_meta, file_hash=file_hash)
                for doc_id, filename, text, content, pages_meta, file_hash in source_payloads
            ]
            for doc in extracted:
                doc.extraction_notes.append(
                    f"Ollama inference failed ({type(exc).__name__}); deterministic rules fallback used."
                )
    else:
        extracted = [
            rules_extract(filename, text, doc_id=doc_id, pages_meta=pages_meta, file_hash=file_hash)
            for doc_id, filename, text, content, pages_meta, file_hash in source_payloads
        ]

    analysis_id = f"anl-{uuid.uuid4().hex[:10]}"
    response = build_response(
        extracted,
        mode,
        used_model,
        analysis_id=analysis_id,
        shipment_id=active_shipment_id,
    )
    response_data = response.model_dump(mode="json")

    # Persist in SQLite
    save_analysis(
        analysis_id=analysis_id,
        mode=mode,
        model=used_model,
        status=response.summary.status,
        headline=response.summary.headline,
        filenames=[doc.filename for doc in response.documents],
        discrepancy_count=len(
            [d for d in response.discrepancies if d.severity in ("critical", "warning")]
        ),
        response_data=response_data,
        shipment_id=active_shipment_id,
    )

    return JSONResponse(content=response_data)


@app.get("/api/analyses", response_model=AuditListResponse)
async def get_analyses(
    search: str | None = Query(
        default=None,
        description="Search by ID, invoice number, exporter, buyer, or shipment reference",
    ),
    status: str | None = Query(
        default=None,
        description="Filter by audit status (needs_attention, ready_for_review, etc.)",
    ),
    date_from: str | None = Query(
        default=None,
        description="Filter audits created on or after date (YYYY-MM-DD)",
    ),
    date_to: str | None = Query(
        default=None,
        description="Filter audits created on or before date (YYYY-MM-DD)",
    ),
    audit_type: str | None = Query(
        default=None,
        description="Filter linked or standalone audits ('linked', 'standalone', 'all')",
    ),
    sort_order: str = Query(
        default="desc",
        description="Sort order: 'desc' / 'newest' or 'asc' / 'oldest'",
    ),
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    limit: int | None = Query(default=None, ge=1, le=100, description="Legacy limit override"),
) -> dict:
    """Return filtered, paginated list of saved reconciliation audits from SQLite."""
    import math

    clean_sort = sort_order.strip().lower()
    if clean_sort not in ("asc", "desc", "newest", "oldest"):
        raise HTTPException(
            status_code=400,
            detail="Invalid sort_order. Allowed: desc, asc, newest, oldest.",
        )

    if audit_type:
        clean_type = audit_type.strip().lower()
        if clean_type not in ("all", "linked", "standalone"):
            raise HTTPException(
                status_code=400,
                detail="Invalid audit_type. Allowed: all, linked, standalone.",
            )

    eff_page_size = (
        limit
        if (
            limit is not None
            and search is None
            and status is None
            and date_from is None
            and date_to is None
            and audit_type is None
        )
        else page_size
    )

    results, total = list_analyses(
        limit=limit,
        search=search,
        status=status,
        date_from=date_from,
        date_to=date_to,
        audit_type=audit_type,
        sort_order=clean_sort,
        page=page,
        page_size=eff_page_size,
        return_meta=True,
    )

    total_pages = math.ceil(total / eff_page_size) if total > 0 else 1

    return {
        "analyses": results,
        "total": total,
        "page": page,
        "page_size": eff_page_size,
        "total_pages": total_pages,
    }


@app.get("/api/analyses/{analysis_id}")
async def get_analysis(analysis_id: str) -> dict:
    """Fetch full analysis details by id. Returns recoverable 422 error if historical payload is corrupted."""
    clean_id = analysis_id.strip()
    data = get_analysis_by_id(clean_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Analysis '{clean_id}' not found.")
    if data.get("error") == "malformed_payload":
        raise HTTPException(
            status_code=422,
            detail=f"Historical analysis '{clean_id}' payload is malformed or corrupted. {data.get('message', '')}",
        )
    return data


@app.delete("/api/analyses/{analysis_id}")
async def delete_analysis(analysis_id: str) -> dict:
    """Delete an analysis record from SQLite."""
    deleted = delete_analysis_by_id(analysis_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return {"status": "deleted", "id": analysis_id}


# ==========================================
# Finding Review & Resolution Endpoints (Milestone 2E.4)
# ==========================================


@app.post("/api/analyses/{analysis_id}/findings/{finding_id}/review")
async def review_finding_endpoint(
    analysis_id: str,
    finding_id: str,
    payload: ReviewActionRequest,
) -> dict:
    """Record a review action (in_review, acknowledged, escalated, resolved, reopened)
    against a reconciliation finding in an analysis.
    Validates legal state transitions and finding-specific resolution evidence.
    """
    clean_anl_id = analysis_id.strip()
    clean_fnd_id = finding_id.strip()

    analysis = get_analysis_by_id(clean_anl_id)
    if not analysis:
        raise HTTPException(status_code=404, detail=f"Analysis '{clean_anl_id}' not found.")

    discrepancies = analysis.get("discrepancies", [])
    target = None
    for d in discrepancies:
        if d.get("id") == clean_fnd_id:
            target = d
            break
    if not target:
        for d in discrepancies:
            if d.get("field") == clean_fnd_id:
                target = d
                break

    if not target:
        raise HTTPException(
            status_code=404,
            detail=f"Finding '{clean_fnd_id}' not found in analysis '{clean_anl_id}'.",
        )

    try:
        updated_finding, event = process_review_action(clean_anl_id, target, payload, analysis=analysis)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))

    # Persist the immutable review event
    record_finding_review(event)

    # Persist updated response data
    update_analysis_response_json(clean_anl_id, analysis)

    # If linked to a shipment, update shipment readiness/status
    shipment_id = analysis.get("shipment_id")
    if shipment_id:
        shipment = get_shipment_by_id(shipment_id)
        if shipment:
            docs = list_documents_for_shipment(shipment_id)
            readiness = calculate_shipment_readiness(
                shipment=shipment,
                documents=docs,
                latest_analysis=analysis,
            )
            new_shipment_status = "ready" if readiness.get("is_ready") else "needs_attention"
            update_shipment(shipment_id, {"status": new_shipment_status})

    return {
        "status": "success",
        "analysis_id": clean_anl_id,
        "finding_id": target["id"],
        "finding": updated_finding,
        "event": event,
    }


@app.get("/api/analyses/{analysis_id}/findings/{finding_id}/reviews")
async def get_finding_reviews_endpoint(analysis_id: str, finding_id: str) -> dict:
    """Retrieve full append-only review audit trail for a specific finding."""
    clean_anl_id = analysis_id.strip()
    clean_fnd_id = finding_id.strip()

    analysis = get_analysis_by_id(clean_anl_id)
    if not analysis:
        raise HTTPException(status_code=404, detail=f"Analysis '{clean_anl_id}' not found.")

    reviews = get_finding_reviews(clean_anl_id, clean_fnd_id)
    return {
        "analysis_id": clean_anl_id,
        "finding_id": clean_fnd_id,
        "reviews": reviews,
    }


@app.get("/api/analyses/{analysis_id}/reviews")
async def get_all_analysis_reviews_endpoint(analysis_id: str) -> dict:
    """Retrieve all review events across all findings for an analysis."""
    clean_anl_id = analysis_id.strip()
    analysis = get_analysis_by_id(clean_anl_id)
    if not analysis:
        raise HTTPException(status_code=404, detail=f"Analysis '{clean_anl_id}' not found.")

    reviews = get_finding_reviews_for_analysis(clean_anl_id)
    return {
        "analysis_id": clean_anl_id,
        "reviews": reviews,
    }


# ==========================================
# Backup & Disaster Recovery Endpoints (Milestone 2F)
# ==========================================


@app.get("/api/backups")
async def list_backups_endpoint(current_user: AuthenticatedUser = Depends(get_current_user)) -> dict:
    """List verified backup snapshots in the managed backup directory.
    Administrative endpoint — requires authenticated administrative access.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only administrators can view backup archives.")
    backups = list_backups()
    return {"backups": backups, "total": len(backups)}


@app.post("/api/backups", status_code=201)
async def trigger_backup_endpoint(current_user: AuthenticatedUser = Depends(get_current_user)) -> dict:
    """Create a verified snapshot backup of SQLite database and uploaded documents.
    Enforces retention policy and SHA-256 manifest integrity verification.
    Administrative endpoint — requires authenticated administrative access.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only administrators can trigger backup creation.")
    try:
        manifest = create_backup()
        return {"status": "created", "backup": manifest}
    except Exception as exc:
        logger.error("Administrative backup creation failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Backup creation failed: {exc}")


# ==========================================
# CBM Calculator & Cargo Logistics Endpoints (Milestone 2F)
# ==========================================


@app.post("/api/logistics/cbm/calculate", response_model=CargoCalculationResponse)
async def calculate_cbm_endpoint(payload: CargoCalculationRequest):
    """Stateless calculation of CBM, volumetric weight, and chargeable weight."""
    try:
        inputs = [
            CargoLineInput(
                description=it.description,
                length=it.length,
                width=it.width,
                height=it.height,
                dimension_unit=it.dimension_unit,
                gross_weight_per_pkg=it.gross_weight_per_pkg,
                weight_unit=it.weight_unit,
                quantity=it.quantity,
                sku=it.sku,
                package_type=it.package_type,
                notes=it.notes,
            )
            for it in payload.items
        ]
        agg = calculate_cargo_aggregate(
            inputs,
            freight_mode=payload.freight_mode,
            dimensional_divisor=payload.dimensional_divisor,
            per_package_chargeable_rounding=payload.per_package_chargeable_rounding,
        )
        return agg
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/logistics/cbm/container-estimate", response_model=list[ContainerEstimateResponse])
async def estimate_container_endpoint(payload: ContainerEstimateRequest):
    """Estimate container capacity across standard container types."""
    try:
        pkg_l_m = normalize_dimension_to_meters(payload.package_length, payload.dimension_unit)
        pkg_w_m = normalize_dimension_to_meters(payload.package_width, payload.dimension_unit)
        pkg_h_m = normalize_dimension_to_meters(payload.package_height, payload.dimension_unit)
        pkg_wt_kg = normalize_weight_to_kg(payload.package_weight, payload.weight_unit)

        custom_payloads = {}
        if payload.custom_payload_capacity_kg is not None:
            for k in ("20_standard", "40_standard", "40_high_cube"):
                custom_payloads[k] = payload.custom_payload_capacity_kg

        results = compare_all_containers_for_cargo(
            package_length_m=pkg_l_m,
            package_width_m=pkg_w_m,
            package_height_m=pkg_h_m,
            package_weight_kg=pkg_wt_kg,
            usable_ratio=payload.usable_volume_ratio,
            custom_payload_map=custom_payloads if custom_payloads else None,
        )
        return results
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/logistics/cbm/calculations", response_model=CargoCalculationListResponse)
async def list_cargo_calculations_endpoint(
    shipment_id: str | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """Retrieve paginated cargo calculations with optional search or shipment filter."""
    records, total = list_cargo_calculations(
        shipment_id=shipment_id,
        search=search,
        page=page,
        page_size=page_size,
    )
    total_pages = math.ceil(total / page_size) if total > 0 else 1
    return {
        "calculations": records,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@app.get("/api/logistics/cbm/calculations/{calculation_id}", response_model=CargoCalculationRecord)
async def get_cargo_calculation_endpoint(calculation_id: str):
    """Retrieve full details of a saved cargo calculation."""
    record = get_cargo_calculation_by_id(calculation_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Cargo calculation '{calculation_id}' not found.")
    return record


@app.post("/api/logistics/cbm/calculations", response_model=CargoCalculationRecord, status_code=201)
async def save_cargo_calculation_endpoint(payload: CargoCalculationRequest):
    """Persist a new cargo calculation with authoritative server recalculation."""
    try:
        inputs = [
            CargoLineInput(
                description=it.description,
                length=it.length,
                width=it.width,
                height=it.height,
                dimension_unit=it.dimension_unit,
                gross_weight_per_pkg=it.gross_weight_per_pkg,
                weight_unit=it.weight_unit,
                quantity=it.quantity,
                sku=it.sku,
                package_type=it.package_type,
                notes=it.notes,
            )
            for it in payload.items
        ]
        agg = calculate_cargo_aggregate(
            inputs,
            freight_mode=payload.freight_mode,
            dimensional_divisor=payload.dimensional_divisor,
            per_package_chargeable_rounding=payload.per_package_chargeable_rounding,
        )

        header_data = {
            "title": payload.title or "Cargo Calculation",
            "shipment_id": payload.shipment_id,
            "freight_mode": payload.freight_mode,
            "dimensional_divisor": payload.dimensional_divisor,
            "volumetric_rounding": "per_package" if payload.per_package_chargeable_rounding else "standard",
            "total_packages": agg.total_packages,
            "total_cbm": agg.total_cbm,
            "total_cuft": agg.total_cuft,
            "total_gross_weight_kg": agg.total_gross_weight_kg,
            "total_gross_weight_lb": agg.total_gross_weight_lb,
            "total_volumetric_weight_kg": agg.total_volumetric_weight_kg,
            "chargeable_weight_kg": agg.chargeable_weight_kg,
            "notes": payload.notes,
        }
        lines_data = [
            {
                "sku": l.sku,
                "description": l.description,
                "package_type": l.package_type,
                "length_orig": l.length_orig,
                "width_orig": l.width_orig,
                "height_orig": l.height_orig,
                "dimension_unit": l.dimension_unit,
                "gross_weight_orig": l.gross_weight_orig,
                "weight_unit": l.weight_unit,
                "quantity": l.quantity,
                "length_m": l.length_m,
                "width_m": l.width_m,
                "height_m": l.height_m,
                "weight_kg": l.weight_kg,
                "cbm_per_pkg": l.cbm_per_pkg,
                "total_cbm": l.total_cbm,
                "total_cuft": l.total_cuft,
                "total_weight_kg": l.total_gross_weight_kg,
                "total_weight_lb": l.total_gross_weight_lb,
                "volumetric_weight_kg": l.volumetric_weight_kg,
                "notes": l.notes,
            }
            for l in agg.lines
        ]

        created = create_cargo_calculation(header_data, lines_data)
        return created
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.put("/api/logistics/cbm/calculations/{calculation_id}", response_model=CargoCalculationRecord)
async def update_cargo_calculation_endpoint(calculation_id: str, payload: CargoCalculationRequest):
    """Update existing draft cargo calculation with authoritative recalculation."""
    existing = get_cargo_calculation_by_id(calculation_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Cargo calculation '{calculation_id}' not found.")

    try:
        inputs = [
            CargoLineInput(
                description=it.description,
                length=it.length,
                width=it.width,
                height=it.height,
                dimension_unit=it.dimension_unit,
                gross_weight_per_pkg=it.gross_weight_per_pkg,
                weight_unit=it.weight_unit,
                quantity=it.quantity,
                sku=it.sku,
                package_type=it.package_type,
                notes=it.notes,
            )
            for it in payload.items
        ]
        agg = calculate_cargo_aggregate(
            inputs,
            freight_mode=payload.freight_mode,
            dimensional_divisor=payload.dimensional_divisor,
            per_package_chargeable_rounding=payload.per_package_chargeable_rounding,
        )

        header_data = {
            "title": payload.title or existing.get("title", "Cargo Calculation"),
            "shipment_id": payload.shipment_id if payload.shipment_id is not None else existing.get("shipment_id"),
            "freight_mode": payload.freight_mode,
            "dimensional_divisor": payload.dimensional_divisor,
            "volumetric_rounding": "per_package" if payload.per_package_chargeable_rounding else "standard",
            "total_packages": agg.total_packages,
            "total_cbm": agg.total_cbm,
            "total_cuft": agg.total_cuft,
            "total_gross_weight_kg": agg.total_gross_weight_kg,
            "total_gross_weight_lb": agg.total_gross_weight_lb,
            "total_volumetric_weight_kg": agg.total_volumetric_weight_kg,
            "chargeable_weight_kg": agg.chargeable_weight_kg,
            "notes": payload.notes if payload.notes is not None else existing.get("notes"),
        }
        lines_data = [
            {
                "sku": l.sku,
                "description": l.description,
                "package_type": l.package_type,
                "length_orig": l.length_orig,
                "width_orig": l.width_orig,
                "height_orig": l.height_orig,
                "dimension_unit": l.dimension_unit,
                "gross_weight_orig": l.gross_weight_orig,
                "weight_unit": l.weight_unit,
                "quantity": l.quantity,
                "length_m": l.length_m,
                "width_m": l.width_m,
                "height_m": l.height_m,
                "weight_kg": l.weight_kg,
                "cbm_per_pkg": l.cbm_per_pkg,
                "total_cbm": l.total_cbm,
                "total_cuft": l.total_cuft,
                "total_weight_kg": l.total_gross_weight_kg,
                "total_weight_lb": l.total_gross_weight_lb,
                "volumetric_weight_kg": l.volumetric_weight_kg,
                "notes": l.notes,
            }
            for l in agg.lines
        ]

        updated = update_cargo_calculation(calculation_id, header_data, lines_data)
        return updated
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.delete("/api/logistics/cbm/calculations/{calculation_id}")
async def delete_cargo_calculation_endpoint(calculation_id: str):
    """Delete a saved draft calculation."""
    deleted = delete_cargo_calculation(calculation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Cargo calculation '{calculation_id}' not found.")
    return {"deleted": True, "id": calculation_id}


@app.get("/api/shipments/{shipment_id}/cargo-measurements")
async def get_shipment_cargo_measurements(shipment_id: str):
    """List linked cargo measurements and calculations for a shipment with discrepancy analysis."""
    shipment = get_shipment_by_id(shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail=f"Shipment '{shipment_id}' not found.")

    calcs = get_cargo_calculations_for_shipment(shipment_id)

    # Discrepancy comparison against latest analysis or documents if available
    latest_anl = get_latest_analysis_for_shipment(shipment_id)
    discrepancy_info = None

    if calcs and latest_anl:
        active_calc = calcs[0]
        anl_data = latest_anl.get("response_json") or {}
        if isinstance(anl_data, str):
            try:
                anl_data = json.loads(anl_data)
            except Exception:
                anl_data = {}

        # Look for declared gross weight in analysis
        docs = anl_data.get("documents", [])
        declared_weights = []
        for d in docs:
            gw = d.get("total_gross_weight_kg")
            if gw is not None and gw > 0:
                declared_weights.append((d.get("filename", "Document"), gw))

        if declared_weights:
            calc_wt = active_calc["total_gross_weight_kg"]
            discrepancies = []
            for doc_name, doc_wt in declared_weights:
                diff = abs(calc_wt - doc_wt)
                if diff > 1.0:  # more than 1 kg difference
                    discrepancies.append({
                        "document": doc_name,
                        "declared_weight_kg": doc_wt,
                        "calculated_cargo_weight_kg": calc_wt,
                        "difference_kg": round(diff, 2),
                        "status": "warning",
                        "message": f"Calculated cargo weight ({calc_wt:.1f} kg) differs from declared weight in {doc_name} ({doc_wt:.1f} kg) by {diff:.1f} kg.",
                    })
            if discrepancies:
                discrepancy_info = discrepancies

    has_calcs = len(calcs) > 0
    first_calc = calcs[0] if has_calcs else {}
    disc_alert = discrepancy_info[0]["message"] if discrepancy_info else None

    return {
        "shipment_id": shipment_id,
        "shipment_reference": shipment.get("reference"),
        "has_cargo_measurements": has_calcs,
        "total_cbm": first_calc.get("total_cbm", 0.0),
        "total_gross_weight_kg": first_calc.get("total_gross_weight_kg", 0.0),
        "chargeable_weight_kg": first_calc.get("chargeable_weight_kg", 0.0),
        "total_packages": first_calc.get("total_packages", 0),
        "freight_mode": first_calc.get("freight_mode", "general"),
        "discrepancy_alert": disc_alert,
        "calculations": calcs,
        "discrepancies": discrepancy_info,
    }


# ===========================================================================
# Milestone Phase 1: Core Master Data Endpoints
# ===========================================================================

# --- Products Master API ---

@app.post("/api/products", response_model=ProductResponse, status_code=201)
async def create_product_endpoint(
    payload: ProductCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Create a new product in the Product Master catalog."""
    verify_role_permission(current_user.role, "create_product")
    return create_product(payload.model_dump(), performed_by=current_user.username)


@app.get("/api/products", response_model=ProductListResponse)
async def list_products_endpoint(
    search: str | None = Query(None, description="Search by SKU, name, description, HSN, barcode"),
    category: str | None = Query(None, description="Filter by product category"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Retrieve catalog of products with search, category filtering, and pagination."""
    return list_products(search=search, category=category, is_active=is_active, limit=limit, offset=offset)


@app.get("/api/products/{product_id}", response_model=ProductResponse)
async def get_product_endpoint(product_id: str):
    """Retrieve a single product by its unique product ID."""
    prod = get_product_by_id(product_id)
    if not prod:
        raise HTTPException(status_code=404, detail=f"Product with ID '{product_id}' not found.")
    return prod


@app.patch("/api/products/{product_id}", response_model=ProductResponse)
async def update_product_endpoint(
    product_id: str,
    payload: ProductUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Update fields on an existing product with duplicate protection and audit logging."""
    verify_role_permission(current_user.role, "update_product")
    return update_product(product_id, payload.model_dump(exclude_unset=True), performed_by=current_user.username)


@app.delete("/api/products/{product_id}")
async def delete_product_endpoint(
    product_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Delete a product from the master catalog."""
    verify_role_permission(current_user.role, "delete")
    delete_product(product_id, performed_by=current_user.username)
    return {"detail": "Product deleted successfully.", "id": product_id}


# --- Supplier Master API ---

@app.post("/api/suppliers", response_model=SupplierResponse, status_code=201)
async def create_supplier_endpoint(
    payload: SupplierCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Create a new supplier in the Supplier Master registry."""
    verify_role_permission(current_user.role, "create_supplier")
    return create_supplier(payload.model_dump(), performed_by=current_user.username)


@app.get("/api/suppliers", response_model=SupplierListResponse)
async def list_suppliers_endpoint(
    search: str | None = Query(None, description="Search by code, name, tax ID, email, contact"),
    status: str | None = Query(None, description="Filter by status (active, inactive, blocked)"),
    country: str | None = Query(None, description="Filter by country code"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Retrieve suppliers with search, status filtering, and pagination."""
    return list_suppliers(search=search, status=status, country=country, limit=limit, offset=offset)


@app.get("/api/suppliers/{supplier_id}", response_model=SupplierResponse)
async def get_supplier_endpoint(supplier_id: str):
    """Retrieve a single supplier by its unique supplier ID."""
    sup = get_supplier_by_id(supplier_id)
    if not sup:
        raise HTTPException(status_code=404, detail=f"Supplier with ID '{supplier_id}' not found.")
    return sup


@app.patch("/api/suppliers/{supplier_id}", response_model=SupplierResponse)
async def update_supplier_endpoint(
    supplier_id: str,
    payload: SupplierUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Update supplier information with audit logging."""
    verify_role_permission(current_user.role, "update_supplier")
    return update_supplier(supplier_id, payload.model_dump(exclude_unset=True), performed_by=current_user.username)


@app.delete("/api/suppliers/{supplier_id}")
async def delete_supplier_endpoint(
    supplier_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Delete a supplier from the registry."""
    verify_role_permission(current_user.role, "delete")
    delete_supplier(supplier_id, performed_by=current_user.username)
    return {"detail": "Supplier deleted successfully.", "id": supplier_id}


# --- Customer Master API ---

@app.post("/api/customers", response_model=CustomerResponse, status_code=201)
async def create_customer_endpoint(
    payload: CustomerCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Create a new customer in the Customer Master / CRM registry."""
    verify_role_permission(current_user.role, "create_customer")
    return create_customer(payload.model_dump(), performed_by=current_user.username)


@app.get("/api/customers", response_model=CustomerListResponse)
async def list_customers_endpoint(
    search: str | None = Query(None, description="Search by code, name, tax ID, email, contact, port"),
    status: str | None = Query(None, description="Filter by status (active, inactive, blocked)"),
    country: str | None = Query(None, description="Filter by destination country"),
    customer_type: str | None = Query(None, description="Filter by type (domestic, international)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Retrieve customers with search, country, status filtering, and pagination."""
    return list_customers(
        search=search, status=status, country=country, customer_type=customer_type, limit=limit, offset=offset
    )


@app.get("/api/customers/{customer_id}", response_model=CustomerResponse)
async def get_customer_endpoint(customer_id: str):
    """Retrieve a single customer by its unique customer ID."""
    cus = get_customer_by_id(customer_id)
    if not cus:
        raise HTTPException(status_code=404, detail=f"Customer with ID '{customer_id}' not found.")
    return cus


@app.patch("/api/customers/{customer_id}", response_model=CustomerResponse)
async def update_customer_endpoint(
    customer_id: str,
    payload: CustomerUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Update customer information with audit logging."""
    verify_role_permission(current_user.role, "update_customer")
    return update_customer(customer_id, payload.model_dump(exclude_unset=True), performed_by=current_user.username)


@app.delete("/api/customers/{customer_id}")
async def delete_customer_endpoint(
    customer_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Delete a customer from the CRM registry."""
    verify_role_permission(current_user.role, "delete")
    delete_customer(customer_id, performed_by=current_user.username)
    return {"detail": "Customer deleted successfully.", "id": customer_id}


# --- ERP Master Data Audit Logs API ---

@app.get("/api/master-data/audit-logs", response_model=AuditLogListResponse)
async def get_master_data_audit_logs(
    entity_type: str | None = Query(None, description="Filter by entity type (product, supplier, customer)"),
    entity_id: str | None = Query(None, description="Filter by specific entity ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Retrieve immutable audit logs of master data creations, modifications, and deletions."""
    return list_erp_audit_logs(entity_type=entity_type, entity_id=entity_id, limit=limit, offset=offset)


# ===========================================================================
# Milestone Phase 2: Procurement & Goods Receipt Endpoints
# ===========================================================================

# --- Purchase Orders API ---

@app.post("/api/purchase-orders", response_model=PurchaseOrderResponse, status_code=201)
async def create_purchase_order_endpoint(
    payload: PurchaseOrderCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Create a new Purchase Order in draft state."""
    verify_role_permission(current_user.role, "create_po")
    return create_purchase_order(payload.model_dump(), performed_by=current_user.username)


@app.get("/api/purchase-orders", response_model=PurchaseOrderListResponse)
async def list_purchase_orders_endpoint(
    search: str | None = Query(None, description="Search by PO number or notes"),
    status: str | None = Query(None, description="Filter by status (draft, submitted, approved, partially_received, fully_received, cancelled)"),
    supplier_id: str | None = Query(None, description="Filter by supplier ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Retrieve purchase orders with search, status filtering, and pagination."""
    return list_purchase_orders(search=search, status=status, supplier_id=supplier_id, limit=limit, offset=offset)


@app.get("/api/purchase-orders/{po_id}", response_model=PurchaseOrderResponse)
async def get_purchase_order_endpoint(po_id: str):
    """Retrieve a single purchase order by its ID."""
    po = get_purchase_order_by_id(po_id)
    if not po:
        raise HTTPException(status_code=404, detail=f"Purchase order '{po_id}' not found.")
    return po


@app.patch("/api/purchase-orders/{po_id}", response_model=PurchaseOrderResponse)
async def update_purchase_order_endpoint(
    po_id: str,
    payload: PurchaseOrderUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Update fields on a draft or submitted purchase order."""
    verify_role_permission(current_user.role, "update_po")
    return update_purchase_order(po_id, payload.model_dump(exclude_unset=True), performed_by=current_user.username)


@app.post("/api/purchase-orders/{po_id}/submit", response_model=PurchaseOrderResponse)
async def submit_purchase_order_endpoint(
    po_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Submit a draft purchase order for review/approval."""
    verify_role_permission(current_user.role, "submit_po")
    return transition_purchase_order_status(po_id, "submitted", performed_by=current_user.username)


@app.post("/api/purchase-orders/{po_id}/approve", response_model=PurchaseOrderResponse)
async def approve_purchase_order_endpoint(
    po_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Approve a submitted purchase order (Authorizes goods receipt)."""
    verify_role_permission(current_user.role, "approve_po")
    return transition_purchase_order_status(po_id, "approved", performed_by=current_user.username)


@app.post("/api/purchase-orders/{po_id}/cancel", response_model=PurchaseOrderResponse)
async def cancel_purchase_order_endpoint(
    po_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Cancel a purchase order if no receipts have been recorded."""
    verify_role_permission(current_user.role, "cancel_po")
    return transition_purchase_order_status(po_id, "cancelled", performed_by=current_user.username)


# --- Goods Receipts API ---

@app.post("/api/goods-receipts", response_model=GoodsReceiptResponse, status_code=201)
async def create_goods_receipt_endpoint(
    payload: GoodsReceiptCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Create a new goods receipt against an approved purchase order."""
    verify_role_permission(current_user.role, "create_gr")
    return create_goods_receipt(payload.model_dump(), performed_by=current_user.username)


@app.get("/api/goods-receipts", response_model=GoodsReceiptListResponse)
async def list_goods_receipts_endpoint(
    search: str | None = Query(None, description="Search by receipt number or notes"),
    status: str | None = Query(None, description="Filter by status (draft, inspected, posted, cancelled)"),
    po_id: str | None = Query(None, description="Filter by PO ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Retrieve goods receipts with search, status filtering, and pagination."""
    return list_goods_receipts(search=search, status=status, po_id=po_id, limit=limit, offset=offset)


@app.get("/api/goods-receipts/{receipt_id}", response_model=GoodsReceiptResponse)
async def get_goods_receipt_endpoint(receipt_id: str):
    """Retrieve a single goods receipt by its ID."""
    receipt = get_goods_receipt_by_id(receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail=f"Goods receipt '{receipt_id}' not found.")
    return receipt


@app.post("/api/goods-receipts/{receipt_id}/post")
async def post_goods_receipt_endpoint(
    receipt_id: str,
    idempotency_key: str = Query(..., description="Unique client posting key for exactly-once execution"),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Post accepted goods receipt stock to available inventory ledger."""
    verify_role_permission(current_user.role, "post_gr")
    return post_goods_receipt_to_inventory(receipt_id, idempotency_key=idempotency_key, performed_by=current_user.username)


# --- Inventory Ledger API ---

@app.get("/api/inventory/balances", response_model=InventoryBalanceListResponse)
async def get_inventory_balances_endpoint(
    stock_type: str | None = Query(None, description="Filter by stock type (available, quarantined, rejected)"),
):
    """Retrieve current stock on-hand balances across products."""
    balances = list_inventory_balances(stock_type=stock_type)
    return {"total": len(balances), "items": balances}


@app.get("/api/inventory/movements", response_model=InventoryMovementListResponse)
async def list_inventory_movements_endpoint(
    product_id: str | None = Query(None, description="Filter by product ID"),
    movement_type: str | None = Query(None, description="Filter by movement type (RECEIPT_POST, COMPENSATING_RETURN)"),
    stock_type: str | None = Query(None, description="Filter by stock type (available, quarantined, rejected)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Retrieve chronological audit trail of stock movements."""
    return list_inventory_movements(
        product_id=product_id,
        movement_type=movement_type,
        stock_type=stock_type,
        limit=limit,
        offset=offset,
    )


# --- Phase 3: Warehouse & Inventory Management API ---
from .warehouse import router as warehouse_router
app.include_router(warehouse_router, prefix="/api")

# --- Phase 4: Sales Orders & Fulfilment API ---
from .sales import router as sales_router
app.include_router(sales_router, prefix="/api")

# --- Authentication & User Identity API (SEC-01) ---
from .auth import auth_router
app.include_router(auth_router)

# --- Phase 5: Export Operations & Documentation API ---
from .export_operations import router as export_router
app.include_router(export_router, prefix="/api")

# --- Phase 6: Commercial Invoicing, Payments, Indian GST & Multi-Currency API ---
from .invoicing import router as finance_router
app.include_router(finance_router)

# --- Phase 7: Financial Reports & Executive Dashboard API ---
from .reports import router as reports_router
app.include_router(reports_router)

# --- Phase 8: Operational Portals & Barcode Services API ---
from .portal import router as portal_router
app.include_router(portal_router)

# --- Phase 9: Secure Supplier & Customer Collaboration Portals API ---
from .collaboration import router as collaboration_router
app.include_router(collaboration_router)



