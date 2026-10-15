"""
TradeSathi AI — Phase 8: Operational Portals & Barcode Services API
Provides high-performance, authenticated endpoints for:
1. Unified Barcode & QR Code Resolution (Product, Location, PO, GR, SO, Dispatch, Export Shipment)
2. Thermal Label Generation & Preview (4"x2", 2"x1" ISO/IEC compliant Code 128 & QR Code)
3. Scan-driven Inbound Goods Receipt (Authoritative Procurement & QA Integration)
4. Scan-driven Warehouse Location Transfer (Authoritative Inventory Ledger & Movements)
5. Scan-driven Fulfilment Packing (Authoritative Sales Allocation & Pick/Pack)
"""

from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.auth import AuthenticatedUser, get_current_user
from app.barcode_engine import (
    generate_entity_label,
    resolve_scanned_barcode_payload,
    build_label_html,
    generate_qr_svg,
    generate_code128_svg,
)
from app.db import (
    get_connection,
    get_barcode_record_by_id,
    list_entity_barcodes_record,
    deactivate_entity_barcode_record,
)
from app.master_data import record_erp_audit_log, verify_role_permission
from app.procurement import (
    create_goods_receipt,
    get_purchase_order_by_id,
    post_goods_receipt_to_inventory,
)
from app.sales import get_sales_order_by_id
from app.storage import get_storage_dir
from app.warehouse import (
    approve_stock_transfer,
    create_stock_transfer,
    dispatch_stock_transfer,
    get_stock_transfer_by_id,
    get_warehouse_by_id,
    get_warehouse_location_by_id,
    receive_stock_transfer,
)

logger = logging.getLogger("tradesathi.portal")

router = APIRouter(prefix="/api/portal", tags=["Operational Portal & Barcode Engine"])


# ==========================================
# Request / Response Schemas
# ==========================================

class ScanResolveRequest(BaseModel):
    scanned_code: str = Field(..., min_length=1, max_length=500, description="Raw scanned QR or linear barcode string")


class GenerateLabelRequest(BaseModel):
    entity_type: str = Field(..., description="One of: product, warehouse_location, purchase_order, goods_receipt, sales_order, dispatch, export_shipment")
    entity_id: str = Field(..., min_length=1, description="Primary ID or reference of target entity")
    label_size: str = Field(default="4x2", description="Thermal label dimension: '4x2' or '2x1'")
    symbology: str = Field(default="BOTH", description="Symbology to embed: 'QR', 'CODE128', or 'BOTH'")


class ScanReceiptLine(BaseModel):
    product_id: str
    accepted_quantity: float = Field(ge=0.0)
    rejected_quantity: float = Field(default=0.0, ge=0.0)
    quarantined_quantity: float = Field(default=0.0, ge=0.0)
    notes: Optional[str] = None


class ExecuteReceiptRequest(BaseModel):
    purchase_order_id: str
    idempotency_key: str = Field(..., min_length=1, max_length=100)
    receipt_number: Optional[str] = None
    notes: Optional[str] = None
    lines: list[ScanReceiptLine] = Field(..., min_length=1)


class ExecuteTransferRequest(BaseModel):
    product_id: str
    source_warehouse_id: str
    dest_warehouse_id: str
    source_location_id: Optional[str] = None
    dest_location_id: Optional[str] = None
    quantity: float = Field(..., gt=0.0)
    idempotency_key: str = Field(..., min_length=1, max_length=100)
    notes: Optional[str] = None
    auto_complete: bool = Field(default=True, description="Immediately complete dispatch and receipt with zero discrepancy")


class ExecutePackRequest(BaseModel):
    sales_order_id: str
    product_id: str
    quantity: float = Field(..., gt=0.0)
    package_ref: Optional[str] = None
    notes: Optional[str] = None


# ==========================================
# 1. Barcode & QR Resolution Endpoints
# ==========================================

@router.post("/scan-resolve")
def scan_and_resolve_entity(
    payload: ScanResolveRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Unified operational scan endpoint:
    Resolves structured TradeSathi QR payloads (TS:v1:<TYPE>:<REF>) and 1D linear barcodes.
    Returns complete authoritative entity context, real-time stock balances, and permitted workflow actions.
    Mere scanning NEVER alters stock balances or executes lifecycle changes.
    """
    verify_role_permission(current_user.role, "scan_portal")

    code = payload.scanned_code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="Empty barcode or QR code payload.")

    resolved = resolve_scanned_barcode_payload(
        scanned_text=code,
        user_role=current_user.role,
        user_id=current_user.id,
    )

    logger.info("Scan resolution success for '%s' by user %s (role: %s)", code, current_user.username, current_user.role)
    return {
        "status": "resolved",
        "entity": resolved,
        "scanned_raw": code,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }


# ==========================================
# 2. Label Generation & Thermal Printing
# ==========================================

@router.post("/labels/generate")
def create_or_get_label(
    payload: GenerateLabelRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Generates or retrieves a print-ready thermal label for an authoritative entity.
    Supports standard 4"x2" and compact 2"x1" label layouts.
    Stores generated HTML/SVG strictly in the application storage directory.
    Enforces idempotency: does not duplicate barcode identifiers for the same entity and symbology.
    """
    verify_role_permission(current_user.role, "print_labels")

    label_size = payload.label_size.strip().lower()
    if label_size not in ("4x2", "2x1"):
        raise HTTPException(status_code=400, detail="Invalid label_size. Must be '4x2' or '2x1'.")

    symbology = payload.symbology.strip().upper()
    if symbology not in ("QR", "CODE128", "BOTH"):
        raise HTTPException(status_code=400, detail="Invalid symbology. Must be 'QR', 'CODE128', or 'BOTH'.")

    result = generate_entity_label(
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        label_size=label_size,
        symbology=symbology,
        created_by=current_user.username,
    )

    record_erp_audit_log(
        entity_type="barcode_label",
        entity_id=result["barcode"]["id"],
        action="generate_label",
        changes={
            "target_entity_type": payload.entity_type,
            "target_entity_id": payload.entity_id,
            "symbology": symbology,
            "label_size": label_size,
        },
        performed_by=current_user.username,
    )

    return {
        "status": "success",
        "barcode": result["barcode"],
        "entity_metadata": result["entity_metadata"],
        "preview_url": f"/api/portal/labels/{result['barcode']['id']}/preview",
    }


@router.get("/labels/{barcode_id}/preview")
def preview_label_html(
    barcode_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> HTMLResponse:
    """
    Serves the standalone, printable HTML document for thermal label printing.
    Protects against path traversal by resolving strictly within get_storage_dir() / 'labels'.
    Rebuilds on the fly if file is missing.
    """
    verify_role_permission(current_user.role, "scan_portal")

    record = get_barcode_record_by_id(barcode_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Barcode record '{barcode_id}' not found.")

    labels_dir = get_storage_dir() / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)

    file_path_str = record.get("file_path")
    if file_path_str:
        raw_path = Path(file_path_str)
        file_path = raw_path.resolve() if raw_path.is_absolute() else (get_storage_dir() / raw_path).resolve()
        # Path traversal guard: must be strictly inside labels_dir
        if labels_dir.resolve() in file_path.parents and file_path.is_file():
            html_content = file_path.read_text(encoding="utf-8")
            return HTMLResponse(content=html_content)

    # Fallback re-generation if file was cleaned up
    regen = generate_entity_label(
        entity_type=record["entity_type"],
        entity_id=record["entity_id"],
        label_size=record["label_size"],
        symbology=record["symbology"],
        created_by=current_user.username,
    )
    return HTMLResponse(content=regen["html_content"])


@router.get("/labels")
def list_labels(
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    entity_id: Optional[str] = Query(None, description="Filter by entity ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Lists registered barcodes with metadata, symbology, and reprint URLs."""
    verify_role_permission(current_user.role, "scan_portal")

    records = list_entity_barcodes_record(
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
        offset=offset,
    )
    return {
        "total": len(records),
        "items": records,
        "limit": limit,
        "offset": offset,
    }


@router.post("/labels/{barcode_id}/deactivate")
def deactivate_label(
    barcode_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Deactivates a barcode so it will no longer resolve in operational scanning."""
    verify_role_permission(current_user.role, "print_labels")

    record = get_barcode_record_by_id(barcode_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Barcode record '{barcode_id}' not found.")

    deactivate_entity_barcode_record(barcode_id, deactivated_by=current_user.username)
    record_erp_audit_log(
        entity_type="barcode_label",
        entity_id=barcode_id,
        action="deactivate_label",
        changes={"barcode_value": record["barcode_value"]},
        performed_by=current_user.username,
    )
    return {"status": "deactivated", "barcode_id": barcode_id}


# ==========================================
# 3. Operational Inbound Goods Receipt Workflow
# ==========================================

@router.post("/execute-receipt")
def scan_execute_goods_receipt(
    payload: ExecuteReceiptRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Executes a verified goods receipt against an approved Purchase Order identified via scan.
    - Validates order lines, received quantities, and tolerance limits.
    - Atomically updates PO line fulfilled quantities and posts accepted stock to the authoritative inventory ledger.
    - Rejects over-receipt beyond tolerance and prevents duplicate submissions.
    """
    verify_role_permission(current_user.role, "execute_scan_operations")
    verify_role_permission(current_user.role, "create_gr")
    verify_role_permission(current_user.role, "post_gr")

    po = get_purchase_order_by_id(payload.purchase_order_id)
    if not po:
        raise HTTPException(status_code=404, detail=f"Purchase order '{payload.purchase_order_id}' not found.")
    if po["status"] not in ("approved", "partially_received"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot receive goods for PO in status '{po['status']}'. Must be 'approved' or 'partially_received'.",
        )

    # Validate receipt lines against PO lines
    po_item_map = {item["product_id"]: item for item in po["items"]}
    gr_items_payload = []

    for line in payload.lines:
        if line.product_id not in po_item_map:
            raise HTTPException(
                status_code=400,
                detail=f"Product '{line.product_id}' is not an expected item on PO '{po['po_number']}'.",
            )
        po_item = po_item_map[line.product_id]
        total_inbound = line.accepted_quantity + line.rejected_quantity + line.quarantined_quantity
        if total_inbound <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Total inbound quantity for '{po_item['sku']}' must be greater than zero.",
            )

        # Tolerance check: 10% standard over-receipt tolerance
        ordered_val = float(po_item.get("ordered_qty") or po_item.get("quantity") or 0.0)
        already_received = float(po_item.get("received_qty") or po_item.get("received_quantity") or 0.0)
        max_allowed = ordered_val * 1.10
        if (already_received + total_inbound) > max_allowed:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Over-receipt rejected for SKU '{po_item['sku']}': ordered {ordered_val}, "
                    f"already received {already_received}, attempting to receive {total_inbound}. "
                    f"Exceeds 10% maximum allowable tolerance."
                ),
            )

        gr_items_payload.append({
            "po_item_id": po_item["id"],
            "product_id": line.product_id,
            "sku": po_item["sku"],
            "received_qty": total_inbound,
            "accepted_qty": line.accepted_quantity,
            "rejected_qty": line.rejected_quantity,
            "quarantined_qty": line.quarantined_quantity,
            "notes": line.notes or "Received via scanner portal",
        })

    # Create Goods Receipt via established procurement service
    now_dt = datetime.now(timezone.utc)
    rec_num = (payload.receipt_number or "").strip() or f"GR-{now_dt.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    gr_create_payload = {
        "po_id": payload.purchase_order_id,
        "receipt_number": rec_num,
        "receipt_date": now_dt.strftime("%Y-%m-%d"),
        "idempotency_key": payload.idempotency_key,
        "notes": payload.notes or f"Scanned receipt for PO {po['po_number']}",
        "items": gr_items_payload,
    }

    created_gr = create_goods_receipt(gr_create_payload, performed_by=current_user.username)

    # Post accepted inventory to authoritative ledger
    posted_gr = post_goods_receipt_to_inventory(
        receipt_id=created_gr["id"],
        idempotency_key=payload.idempotency_key,
        performed_by=current_user.username,
    )

    receipt_dict = posted_gr.get("receipt", posted_gr) if isinstance(posted_gr, dict) else posted_gr
    rec_num_actual = receipt_dict.get("receipt_number", rec_num) if isinstance(receipt_dict, dict) else rec_num

    record_erp_audit_log(
        entity_type="goods_receipt",
        entity_id=created_gr["id"],
        action="scan_execute_goods_receipt",
        changes={
            "po_id": payload.purchase_order_id,
            "po_number": po["po_number"],
            "receipt_number": rec_num_actual,
            "idempotency_key": payload.idempotency_key,
            "items_count": len(gr_items_payload),
        },
        performed_by=current_user.username,
    )

    return {
        "status": "success",
        "message": f"Successfully received and posted {len(gr_items_payload)} items for PO {po['po_number']}.",
        "goods_receipt": receipt_dict,
    }


# ==========================================
# 4. Operational Warehouse Transfer Workflow
# ==========================================

@router.post("/execute-transfer")
def scan_execute_stock_transfer(
    payload: ExecuteTransferRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Executes a scan-driven stock transfer between warehouse locations or facilities.
    - Validates source and destination identifiers.
    - Checks source location ATP (Available-to-Promise) unreserved stock.
    - Executes via authoritative stock transfer lifecycle and records double-entry inventory ledger movements.
    """
    verify_role_permission(current_user.role, "execute_scan_operations")

    if payload.source_warehouse_id == payload.dest_warehouse_id:
        if payload.source_location_id and payload.dest_location_id and payload.source_location_id == payload.dest_location_id:
            raise HTTPException(status_code=400, detail="Source and destination storage locations cannot be identical.")

    # Validate warehouses
    src_wh = get_warehouse_by_id(payload.source_warehouse_id)
    dest_wh = get_warehouse_by_id(payload.dest_warehouse_id)
    if not src_wh["is_active"]:
        raise HTTPException(status_code=400, detail=f"Source warehouse '{src_wh['code']}' is inactive.")
    if not dest_wh["is_active"]:
        raise HTTPException(status_code=400, detail=f"Destination warehouse '{dest_wh['code']}' is inactive.")

    # Validate product exists
    with get_connection() as conn:
        prod = conn.execute("SELECT id, sku, name, is_active FROM products WHERE id = ?", (payload.product_id,)).fetchone()
        if not prod:
            raise HTTPException(status_code=404, detail=f"Product '{payload.product_id}' not found.")
        if not prod["is_active"]:
            raise HTTPException(status_code=400, detail=f"Product '{prod['sku']}' is inactive.")

        # Check source warehouse/location available stock and active reservations (ATP)
        avail = 0.0
        if payload.source_location_id:
            loc_bal = conn.execute(
                """
                SELECT on_hand_qty FROM location_inventory_balances
                WHERE product_id = ? AND warehouse_id = ? AND location_id = ? AND stock_type = 'available'
                """,
                (payload.product_id, payload.source_warehouse_id, payload.source_location_id),
            ).fetchone()
            if loc_bal:
                avail = float(loc_bal["on_hand_qty"])
            else:
                wh_bal = conn.execute(
                    """
                    SELECT COALESCE(SUM(on_hand_qty), 0.0) as on_hand_qty
                    FROM location_inventory_balances
                    WHERE product_id = ? AND warehouse_id = ? AND stock_type = 'available'
                    """,
                    (payload.product_id, payload.source_warehouse_id),
                ).fetchone()
                if wh_bal and float(wh_bal["on_hand_qty"]) > 0:
                    avail = float(wh_bal["on_hand_qty"])
                else:
                    bal = conn.execute(
                        "SELECT on_hand_qty FROM inventory_balances WHERE product_id = ? AND stock_type = 'available'",
                        (payload.product_id,),
                    ).fetchone()
                    avail = float(bal["on_hand_qty"]) if bal else 0.0
        else:
            wh_bal = conn.execute(
                """
                SELECT COALESCE(SUM(on_hand_qty), 0.0) as on_hand_qty
                FROM location_inventory_balances
                WHERE product_id = ? AND warehouse_id = ? AND stock_type = 'available'
                """,
                (payload.product_id, payload.source_warehouse_id),
            ).fetchone()
            if wh_bal and float(wh_bal["on_hand_qty"]) > 0:
                avail = float(wh_bal["on_hand_qty"])
            else:
                bal = conn.execute(
                    "SELECT on_hand_qty FROM inventory_balances WHERE product_id = ? AND stock_type = 'available'",
                    (payload.product_id,),
                ).fetchone()
                avail = float(bal["on_hand_qty"]) if bal else 0.0

        res_row = conn.execute(
            """
            SELECT COALESCE(SUM(quantity), 0.0) as reserved_qty
            FROM stock_reservations
            WHERE product_id = ? AND warehouse_id = ? AND status = 'active'
            """,
            (payload.product_id, payload.source_warehouse_id),
        ).fetchone()
        reserved = float(res_row["reserved_qty"]) if res_row else 0.0
        net_atp = max(0.0, avail - reserved)

        if net_atp < payload.quantity:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Insufficient available stock (unreserved ATP) for '{prod['sku']}' at source warehouse. "
                    f"On-hand available: {avail}, Active reservations: {reserved}, "
                    f"Net ATP: {net_atp}, Requested: {payload.quantity}."
                ),
            )

    transfer_data = {
        "source_warehouse_id": payload.source_warehouse_id,
        "source_location_id": payload.source_location_id,
        "dest_warehouse_id": payload.dest_warehouse_id,
        "dest_location_id": payload.dest_location_id,
        "idempotency_key": payload.idempotency_key,
        "notes": payload.notes or "Scan portal location transfer",
        "items": [
            {
                "product_id": payload.product_id,
                "requested_quantity": payload.quantity,
                "notes": "Scanned relocation",
            }
        ],
    }

    created = create_stock_transfer(transfer_data, performed_by=current_user.username)
    transfer_id = created["id"]

    if payload.auto_complete:
        approved = approve_stock_transfer(transfer_id, performed_by=current_user.username)
        dispatched = dispatch_stock_transfer(transfer_id, performed_by=current_user.username)

        item_id = dispatched["items"][0]["id"]
        receive_payload = {
            "items": [
                {
                    "item_id": item_id,
                    "received_quantity": payload.quantity,
                    "damaged_quantity": 0.0,
                    "discrepancy_reason": None,
                }
            ]
        }
        completed = receive_stock_transfer(transfer_id, receive_payload, performed_by=current_user.username)
        final_transfer = completed
    else:
        final_transfer = created

    record_erp_audit_log(
        entity_type="stock_transfer",
        entity_id=transfer_id,
        action="scan_execute_transfer",
        changes={
            "transfer_number": final_transfer["transfer_number"],
            "product_id": payload.product_id,
            "sku": prod["sku"],
            "quantity": payload.quantity,
            "source_warehouse": src_wh["code"],
            "dest_warehouse": dest_wh["code"],
            "auto_completed": payload.auto_complete,
        },
        performed_by=current_user.username,
    )

    return {
        "status": "success",
        "message": f"Transferred {payload.quantity} units of {prod['sku']} from {src_wh['code']} to {dest_wh['code']}.",
        "transfer": final_transfer,
    }


# ==========================================
# 5. Operational Fulfilment & Packing Workflow
# ==========================================

@router.post("/execute-pack")
def scan_execute_packing_verification(
    payload: ExecutePackRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Verifies and records product packing progress for an existing Sales Order.
    - Validates order state (confirmed, allocated, or picking).
    - Checks that packed quantity does not exceed ordered/allocated line quantity.
    - Increments verified packed count and advances order state when all items are packed.
    - Does NOT dispatch inventory solely because a barcode is scanned.
    """
    verify_role_permission(current_user.role, "execute_scan_operations")

    so = get_sales_order_by_id(payload.sales_order_id)
    if not so:
        raise HTTPException(status_code=404, detail=f"Sales order '{payload.sales_order_id}' not found.")
    if so["status"] not in ("confirmed", "allocated", "picking"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot pack items for sales order in status '{so['status']}'. Must be confirmed, allocated, or picking.",
        )

    # Find item line on sales order
    matched_item = None
    for item in so["items"]:
        if item["product_id"] == payload.product_id:
            matched_item = item
            break

    if not matched_item:
        raise HTTPException(
            status_code=400,
            detail=f"Product '{payload.product_id}' is not an ordered line on Sales Order '{so['order_number']}'.",
        )

    current_picked = float(matched_item["picked_quantity"])
    ordered_qty = float(matched_item["ordered_quantity"])
    allocated_qty = float(matched_item.get("allocated_quantity") or 0.0)
    # Strictly enforce allocated limit if order is allocated/picking
    max_packable = allocated_qty if (allocated_qty > 0 and so["status"] in ("allocated", "picking")) else ordered_qty
    new_picked = current_picked + payload.quantity

    if new_picked > max_packable:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Packing quantity exceeds order limit / allocated limit for SKU '{matched_item['sku']}': "
                f"allocated {max_packable} (ordered {ordered_qty}), already packed {current_picked}, "
                f"attempting to add {payload.quantity}."
            ),
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE sales_order_items
            SET picked_quantity = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_picked, now_iso, matched_item["id"]),
        )

        # Check if all items on the order are now fully packed
        all_items = conn.execute(
            "SELECT ordered_quantity, picked_quantity FROM sales_order_items WHERE sales_order_id = ?",
            (payload.sales_order_id,),
        ).fetchall()

        all_packed = all(float(r["picked_quantity"]) >= float(r["ordered_quantity"]) for r in all_items)
        new_status = "packed" if all_packed else "picking"

        conn.execute(
            "UPDATE sales_orders SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, now_iso, payload.sales_order_id),
        )
        conn.commit()

    record_erp_audit_log(
        entity_type="sales_order",
        entity_id=payload.sales_order_id,
        action="scan_execute_pack",
        changes={
            "order_number": so["order_number"],
            "product_id": payload.product_id,
            "sku": matched_item["sku"],
            "packed_quantity": payload.quantity,
            "total_packed_for_item": new_picked,
            "package_ref": payload.package_ref,
            "new_order_status": new_status,
        },
        performed_by=current_user.username,
    )

    refreshed_so = get_sales_order_by_id(payload.sales_order_id)
    return {
        "status": "success",
        "message": f"Packed {payload.quantity} units of {matched_item['sku']} ({new_picked}/{ordered_qty} packed). Status: {new_status}.",
        "sales_order": refreshed_so,
        "is_order_fully_packed": all_packed,
    }
