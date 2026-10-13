import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .analysis import (
    build_response,
    list_ollama_models,
    ollama_extract,
    rules_extract,
)
from .db import (
    create_document_record,
    create_shipment,
    delete_analysis_by_id,
    delete_document_record,
    get_analysis_by_id,
    get_document_by_id,
    get_duplicate_document,
    get_latest_analysis_for_shipment,
    get_shipment_by_id,
    get_shipment_by_reference,
    init_db,
    list_analyses,
    list_analyses_for_shipment,
    list_documents_for_shipment,
    list_shipments,
    save_analysis,
    update_document_record,
    update_shipment,
)
from .documents import (
    ALLOWED_EXTENSIONS,
    detect_document_type,
    extract_text,
    read_upload,
    read_upload_with_bytes,
    sanitize_filename,
)
from .readiness import calculate_shipment_readiness
from .schemas import (
    DocumentListResponse,
    DocumentResponse,
    DocumentUpdate,
    ShipmentCreate,
    ShipmentListResponse,
    ShipmentReadinessResponse,
    ShipmentResponse,
    ShipmentUpdate,
)
from .storage import (
    compute_file_hash,
    delete_document_file,
    get_document_file_path,
    save_document_file,
)

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent.parent
load_dotenv(APP_DIR.parent / ".env")

MAX_UPLOAD_MB = max(1, int(os.getenv("MAX_UPLOAD_MB", "10")))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
CORS_ORIGINS = [
    value.strip()
    for value in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if value.strip()
]

# Initialize SQLite database schema and migrations
init_db()

app = FastAPI(
    title="TradeSathi AI API",
    version="0.2.0",
    description="Local-first export document analysis & reconciliation engine",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "PATCH", "PUT", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    ollama_status = "unavailable"
    models: list[str] = []
    note = "Rules-based fallback remains available. Start Ollama to enable open-weight AI inference."
    try:
        models = await list_ollama_models(OLLAMA_BASE_URL)
        ollama_status = "connected"
        note = f"Ollama connected with {len(models)} installed model(s)."
    except (httpx.HTTPError, ValueError):
        pass

    return {
        "status": "ok",
        "version": "0.2.0",
        "ollama": ollama_status,
        "ollama_base_url": OLLAMA_BASE_URL,
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


@app.get("/api/samples")
async def get_samples() -> dict:
    """Return preloaded sample documents so the user can test the workflow with 1 click."""
    sample_dir = PROJECT_ROOT / "sample-documents"
    samples = []
    if sample_dir.is_dir():
        for filename in ["commercial_invoice.txt", "packing_list.txt"]:
            file_path = sample_dir / filename
            if file_path.is_file():
                samples.append({
                    "filename": filename,
                    "content": file_path.read_text(encoding="utf-8"),
                })
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

    source_docs: list[tuple[str, str, str]] = []  # (doc_id, filename, text)
    for doc in docs:
        path = get_document_file_path(doc["storage_key"])
        if not path or not path.is_file():
            continue
        content = path.read_bytes()
        try:
            text = extract_text(doc["clean_filename"], content)
            source_docs.append((doc["id"], doc["original_filename"], text))
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
            for doc_id, filename, text in source_docs:
                extracted.append(
                    await ollama_extract(
                        OLLAMA_BASE_URL, selected_model, filename, text, doc_id=doc_id
                    )
                )
            mode = "ollama"
            used_model = selected_model
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            extracted = [
                rules_extract(filename, text, doc_id=doc_id)
                for doc_id, filename, text in source_docs
            ]
            for doc in extracted:
                doc.extraction_notes.append(
                    f"Ollama inference failed ({type(exc).__name__}); deterministic rules fallback used."
                )
    else:
        extracted = [
            rules_extract(filename, text, doc_id=doc_id)
            for doc_id, filename, text in source_docs
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

    source_docs: list[tuple[str, str, str]] = []  # (doc_id, filename, text)
    source_payloads: list[tuple[str, str, str, bytes]] = []
    for upload in files:
        doc_id, filename, text, content = await read_upload_with_bytes(upload, MAX_UPLOAD_BYTES)
        source_docs.append((doc_id, filename, text))
        source_payloads.append((doc_id, filename, text, content))

    # If linked to a shipment, persist uploaded files to shipment documents if not already present
    if active_shipment_id:
        for doc_id, filename, text, content in source_payloads:
            file_hash = compute_file_hash(content)
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
            for doc_id, filename, text in source_docs:
                extracted.append(
                    await ollama_extract(
                        OLLAMA_BASE_URL, selected_model, filename, text, doc_id=doc_id
                    )
                )
            mode = "ollama"
            used_model = selected_model
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            extracted = [
                rules_extract(filename, text, doc_id=doc_id)
                for doc_id, filename, text in source_docs
            ]
            for doc in extracted:
                doc.extraction_notes.append(
                    f"Ollama inference failed ({type(exc).__name__}); deterministic rules fallback used."
                )
    else:
        extracted = [
            rules_extract(filename, text, doc_id=doc_id)
            for doc_id, filename, text in source_docs
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


@app.get("/api/analyses")
async def get_analyses() -> dict:
    """Return list of recent saved analyses from SQLite."""
    return {"analyses": list_analyses(limit=20)}


@app.get("/api/analyses/{analysis_id}")
async def get_analysis(analysis_id: str) -> dict:
    """Fetch full analysis details by id."""
    data = get_analysis_by_id(analysis_id)
    if not data:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return data


@app.delete("/api/analyses/{analysis_id}")
async def delete_analysis(analysis_id: str) -> dict:
    """Delete an analysis record from SQLite."""
    deleted = delete_analysis_by_id(analysis_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return {"status": "deleted", "id": analysis_id}
