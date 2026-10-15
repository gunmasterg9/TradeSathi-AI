"""TradeSathi AI — ExportMate ERP Phase 2: Procurement & Goods Receipt Module
Manages Purchase Orders, Goods Receipts, QA Inspections, Inventory Posting, and Stock Ledger.
Guarantees transaction-level integrity, immutable snapshots, over-receipt prevention,
and exactly-once posting idempotency.
"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from .db import get_connection
from .master_data import record_erp_audit_log, verify_role_permission


# ===========================================================================
# Helper Formatting Functions
# ===========================================================================

def _row_to_po_dict(po_row: Any, item_rows: list[Any], supplier_name: str | None = None) -> dict[str, Any]:
    items = []
    for r in item_rows:
        items.append({
            "id": r["id"],
            "po_id": r["po_id"],
            "product_id": r["product_id"],
            "sku": r["sku"],
            "product_name": r["product_name"],
            "uom": r["uom"],
            "ordered_qty": float(r["ordered_qty"]),
            "unit_price": float(r["unit_price"]),
            "tax_rate_pct": float(r["tax_rate_pct"]),
            "line_total": float(r["line_total"]),
            "received_qty": float(r["received_qty"]),
            "sort_order": int(r["sort_order"]),
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        })

    return {
        "id": po_row["id"],
        "po_number": po_row["po_number"],
        "supplier_id": po_row["supplier_id"],
        "supplier_name": supplier_name,
        "order_date": po_row["order_date"],
        "expected_delivery_date": po_row["expected_delivery_date"],
        "currency": po_row["currency"],
        "payment_terms": po_row["payment_terms"],
        "subtotal": float(po_row["subtotal"]),
        "tax_total": float(po_row["tax_total"]),
        "grand_total": float(po_row["grand_total"]),
        "status": po_row["status"],
        "notes": po_row["notes"],
        "created_by": po_row["created_by"],
        "created_at": po_row["created_at"],
        "updated_at": po_row["updated_at"],
        "supplier_ack_status": po_row["supplier_ack_status"] if "supplier_ack_status" in po_row.keys() else "unacknowledged",
        "supplier_ack_at": po_row["supplier_ack_at"] if "supplier_ack_at" in po_row.keys() else None,
        "supplier_ack_by": po_row["supplier_ack_by"] if "supplier_ack_by" in po_row.keys() else None,
        "supplier_ack_notes": po_row["supplier_ack_notes"] if "supplier_ack_notes" in po_row.keys() else None,
        "supplier_proposed_delivery_date": po_row["supplier_proposed_delivery_date"] if "supplier_proposed_delivery_date" in po_row.keys() else None,
        "items": items,
    }


def _row_to_gr_dict(
    gr_row: Any,
    item_rows: list[Any],
    po_number: str | None = None,
    supplier_name: str | None = None,
) -> dict[str, Any]:
    items = []
    for r in item_rows:
        items.append({
            "id": r["id"],
            "receipt_id": r["receipt_id"],
            "po_item_id": r["po_item_id"],
            "product_id": r["product_id"],
            "sku": r["sku"],
            "product_name": r["product_name"],
            "uom": r["uom"],
            "unit_cost": float(r["unit_cost"]),
            "received_qty": float(r["received_qty"]),
            "accepted_qty": float(r["accepted_qty"]),
            "rejected_qty": float(r["rejected_qty"]),
            "quarantined_qty": float(r["quarantined_qty"]),
            "inspection_notes": r["inspection_notes"],
            "rejection_reason": r["rejection_reason"],
            "inspection_status": r["inspection_status"],
            "inspected_by": r["inspected_by"],
            "inspected_at": r["inspected_at"],
            "created_at": r["created_at"],
        })

    return {
        "id": gr_row["id"],
        "receipt_number": gr_row["receipt_number"],
        "idempotency_key": gr_row["idempotency_key"],
        "po_id": gr_row["po_id"],
        "po_number": po_number,
        "supplier_id": gr_row["supplier_id"],
        "supplier_name": supplier_name,
        "receipt_date": gr_row["receipt_date"],
        "received_by": gr_row["received_by"],
        "status": gr_row["status"],
        "notes": gr_row["notes"],
        "created_at": gr_row["created_at"],
        "updated_at": gr_row["updated_at"],
        "items": items,
    }


# ===========================================================================
# 1. Purchase Orders Service
# ===========================================================================

def create_purchase_order(data: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    po_number = (data.get("po_number") or "").strip().upper()
    if not po_number:
        raise HTTPException(status_code=400, detail="Purchase order number cannot be empty.")

    supplier_id = (data.get("supplier_id") or "").strip()
    if not supplier_id:
        raise HTTPException(status_code=400, detail="Supplier ID is required.")

    order_date = (data.get("order_date") or "").strip()
    if not order_date:
        raise HTTPException(status_code=400, detail="Order date is required.")

    items_data = data.get("items") or []
    if not items_data:
        raise HTTPException(status_code=400, detail="A purchase order must contain at least one line item.")

    now = datetime.now(timezone.utc).isoformat()
    po_id = f"po-{uuid.uuid4().hex[:10]}"

    with get_connection() as conn:
        # 1. Verify supplier existence & active status
        sup = conn.execute("SELECT id, name, status FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
        if not sup:
            raise HTTPException(status_code=400, detail=f"Supplier '{supplier_id}' not found.")
        if sup["status"] == "blocked":
            raise HTTPException(status_code=400, detail=f"Cannot create order: supplier '{sup['name']}' is blocked.")

        # 2. Check duplicate PO number
        existing_po = conn.execute(
            "SELECT id FROM purchase_orders WHERE LOWER(po_number) = LOWER(?)",
            (po_number,),
        ).fetchone()
        if existing_po:
            raise HTTPException(status_code=409, detail=f"Purchase order with number '{po_number}' already exists.")

        # 3. Process lines with immutable snapshots
        processed_lines = []
        subtotal = 0.0
        tax_total = 0.0

        for idx, item in enumerate(items_data):
            prod_id = (item.get("product_id") or "").strip()
            ordered_qty = float(item.get("ordered_qty") or 0.0)
            unit_price = float(item.get("unit_price") if item.get("unit_price") is not None else 0.0)
            tax_rate_pct = float(item.get("tax_rate_pct") if item.get("tax_rate_pct") is not None else 0.0)

            if ordered_qty <= 0:
                raise HTTPException(status_code=400, detail=f"Line {idx + 1}: ordered quantity must be greater than zero.")
            if unit_price < 0:
                raise HTTPException(status_code=400, detail=f"Line {idx + 1}: unit price cannot be negative.")
            if tax_rate_pct < 0 or tax_rate_pct > 100:
                raise HTTPException(status_code=400, detail=f"Line {idx + 1}: tax rate must be between 0 and 100%.")

            prod = conn.execute("SELECT id, sku, name, uom, is_active FROM products WHERE id = ?", (prod_id,)).fetchone()
            if not prod:
                raise HTTPException(status_code=400, detail=f"Line {idx + 1}: product '{prod_id}' not found.")
            if not prod["is_active"]:
                raise HTTPException(status_code=400, detail=f"Line {idx + 1}: cannot order inactive product '{prod['sku']}'.")

            line_total = round(ordered_qty * unit_price, 2)
            line_tax = round(line_total * (tax_rate_pct / 100.0), 2)
            subtotal += line_total
            tax_total += line_tax

            processed_lines.append({
                "id": f"poi-{uuid.uuid4().hex[:10]}",
                "po_id": po_id,
                "product_id": prod["id"],
                "sku": prod["sku"],
                "product_name": prod["name"],
                "uom": prod["uom"] or "PCS",
                "ordered_qty": ordered_qty,
                "unit_price": unit_price,
                "tax_rate_pct": tax_rate_pct,
                "line_total": line_total,
                "sort_order": idx,
                "created_at": now,
                "updated_at": now,
            })

        grand_total = round(subtotal + tax_total, 2)

        # 4. Insert PO header
        conn.execute(
            """
            INSERT INTO purchase_orders (
                id, po_number, supplier_id, order_date, expected_delivery_date,
                currency, payment_terms, subtotal, tax_total, grand_total,
                status, notes, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                po_id,
                po_number,
                supplier_id,
                order_date,
                data.get("expected_delivery_date"),
                (data.get("currency") or "INR").strip().upper(),
                data.get("payment_terms") or "Net 30",
                subtotal,
                tax_total,
                grand_total,
                "draft",
                data.get("notes"),
                performed_by,
                now,
                now,
            ),
        )

        # 5. Insert PO lines
        for pl in processed_lines:
            conn.execute(
                """
                INSERT INTO purchase_order_items (
                    id, po_id, product_id, sku, product_name, uom,
                    ordered_qty, unit_price, tax_rate_pct, line_total,
                    received_qty, sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, ?, ?, ?)
                """,
                (
                    pl["id"],
                    pl["po_id"],
                    pl["product_id"],
                    pl["sku"],
                    pl["product_name"],
                    pl["uom"],
                    pl["ordered_qty"],
                    pl["unit_price"],
                    pl["tax_rate_pct"],
                    pl["line_total"],
                    pl["sort_order"],
                    pl["created_at"],
                    pl["updated_at"],
                ),
            )

        conn.commit()

    record_erp_audit_log(
        "purchase_order",
        po_id,
        "create",
        {"po_number": po_number, "supplier_id": supplier_id, "grand_total": grand_total},
        performed_by,
    )

    created = get_purchase_order_by_id(po_id)
    assert created is not None
    return created


def get_purchase_order_by_id(po_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        po_row = conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
        if not po_row:
            return None

        sup_row = conn.execute("SELECT name FROM suppliers WHERE id = ?", (po_row["supplier_id"],)).fetchone()
        supplier_name = sup_row["name"] if sup_row else None

        item_rows = conn.execute(
            "SELECT * FROM purchase_order_items WHERE po_id = ? ORDER BY sort_order ASC",
            (po_id,),
        ).fetchall()

    return _row_to_po_dict(po_row, item_rows, supplier_name)


def list_purchase_orders(
    search: str | None = None,
    status: str | None = None,
    supplier_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    clauses = []
    params: list[Any] = []

    if search:
        s = f"%{search.strip().lower()}%"
        clauses.append("(LOWER(po_number) LIKE ? OR LOWER(COALESCE(notes, '')) LIKE ?)")
        params.extend([s, s])
    if status:
        clauses.append("status = ?")
        params.append(status.strip().lower())
    if supplier_id:
        clauses.append("supplier_id = ?")
        params.append(supplier_id)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with get_connection() as conn:
        count_row = conn.execute(f"SELECT count(*) FROM purchase_orders {where}", params).fetchone()
        total = count_row[0]

        query = f"""
            SELECT po.*, s.name as supplier_name
            FROM purchase_orders po
            LEFT JOIN suppliers s ON po.supplier_id = s.id
            {where}
            ORDER BY po.created_at DESC
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(query, params + [limit, offset]).fetchall()

        items = []
        for r in rows:
            line_items = conn.execute(
                "SELECT * FROM purchase_order_items WHERE po_id = ? ORDER BY sort_order ASC",
                (r["id"],),
            ).fetchall()
            items.append(_row_to_po_dict(r, line_items, r["supplier_name"]))

    return {"total": total, "items": items, "limit": limit, "offset": offset}


def update_purchase_order(po_id: str, updates: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    existing = get_purchase_order_by_id(po_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Purchase order '{po_id}' not found.")

    if existing["status"] not in ("draft", "submitted"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot edit purchase order in '{existing['status']}' status. Only draft or submitted orders can be edited.",
        )

    now = datetime.now(timezone.utc).isoformat()
    changes: dict[str, Any] = {}

    with get_connection() as conn:
        set_clauses = ["updated_at = ?"]
        params: list[Any] = [now]

        if "expected_delivery_date" in updates:
            set_clauses.append("expected_delivery_date = ?")
            params.append(updates["expected_delivery_date"])
            changes["expected_delivery_date"] = {
                "old": existing["expected_delivery_date"],
                "new": updates["expected_delivery_date"],
            }

        if "payment_terms" in updates and updates["payment_terms"]:
            set_clauses.append("payment_terms = ?")
            params.append(updates["payment_terms"])
            changes["payment_terms"] = {"old": existing["payment_terms"], "new": updates["payment_terms"]}

        if "notes" in updates:
            set_clauses.append("notes = ?")
            params.append(updates["notes"])
            changes["notes"] = {"old": existing["notes"], "new": updates["notes"]}

        # If items are updated
        if "items" in updates and updates["items"] is not None:
            new_items_data = updates["items"]
            if not new_items_data:
                raise HTTPException(status_code=400, detail="A purchase order must contain at least one line item.")

            # Recalculate lines
            processed_lines = []
            subtotal = 0.0
            tax_total = 0.0

            for idx, item in enumerate(new_items_data):
                prod_id = (item.get("product_id") or "").strip()
                ordered_qty = float(item.get("ordered_qty") or 0.0)
                unit_price = float(item.get("unit_price") if item.get("unit_price") is not None else 0.0)
                tax_rate_pct = float(item.get("tax_rate_pct") if item.get("tax_rate_pct") is not None else 0.0)

                if ordered_qty <= 0:
                    raise HTTPException(status_code=400, detail=f"Line {idx + 1}: quantity must be > 0.")
                if unit_price < 0:
                    raise HTTPException(status_code=400, detail=f"Line {idx + 1}: price cannot be negative.")

                prod = conn.execute("SELECT id, sku, name, uom, is_active FROM products WHERE id = ?", (prod_id,)).fetchone()
                if not prod or not prod["is_active"]:
                    raise HTTPException(status_code=400, detail=f"Line {idx + 1}: product not found or inactive.")

                line_total = round(ordered_qty * unit_price, 2)
                line_tax = round(line_total * (tax_rate_pct / 100.0), 2)
                subtotal += line_total
                tax_total += line_tax

                processed_lines.append({
                    "id": f"poi-{uuid.uuid4().hex[:10]}",
                    "po_id": po_id,
                    "product_id": prod["id"],
                    "sku": prod["sku"],
                    "product_name": prod["name"],
                    "uom": prod["uom"] or "PCS",
                    "ordered_qty": ordered_qty,
                    "unit_price": unit_price,
                    "tax_rate_pct": tax_rate_pct,
                    "line_total": line_total,
                    "sort_order": idx,
                    "created_at": now,
                    "updated_at": now,
                })

            grand_total = round(subtotal + tax_total, 2)

            set_clauses.extend(["subtotal = ?", "tax_total = ?", "grand_total = ?"])
            params.extend([subtotal, tax_total, grand_total])
            changes["totals"] = {"subtotal": subtotal, "grand_total": grand_total}

            # Delete old lines and re-insert
            conn.execute("DELETE FROM purchase_order_items WHERE po_id = ?", (po_id,))
            for pl in processed_lines:
                conn.execute(
                    """
                    INSERT INTO purchase_order_items (
                        id, po_id, product_id, sku, product_name, uom,
                        ordered_qty, unit_price, tax_rate_pct, line_total,
                        received_qty, sort_order, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, ?, ?, ?)
                    """,
                    (
                        pl["id"],
                        pl["po_id"],
                        pl["product_id"],
                        pl["sku"],
                        pl["product_name"],
                        pl["uom"],
                        pl["ordered_qty"],
                        pl["unit_price"],
                        pl["tax_rate_pct"],
                        pl["line_total"],
                        pl["sort_order"],
                        pl["created_at"],
                        pl["updated_at"],
                    ),
                )

        params.append(po_id)
        conn.execute(f"UPDATE purchase_orders SET {', '.join(set_clauses)} WHERE id = ?", params)
        conn.commit()

    record_erp_audit_log("purchase_order", po_id, "update", changes, performed_by)
    updated = get_purchase_order_by_id(po_id)
    assert updated is not None
    return updated


def transition_purchase_order_status(po_id: str, new_status: str, performed_by: str = "Local Operator") -> dict[str, Any]:
    existing = get_purchase_order_by_id(po_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Purchase order '{po_id}' not found.")

    current = existing["status"]
    target = new_status.strip().lower()
    now = datetime.now(timezone.utc).isoformat()

    # If attempting to cancel, verify no goods receipts exist first (returns 409 Conflict)
    if target == "cancelled":
        with get_connection() as conn:
            gr_count = conn.execute("SELECT count(*) FROM goods_receipts WHERE po_id = ?", (po_id,)).fetchone()[0]
            if gr_count > 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot cancel Purchase Order '{existing['po_number']}': {gr_count} goods receipt(s) already exist. Cancelling received orders is blocked.",
                )

    # Explicit state transition rules
    valid_transitions = {
        "draft": {"submitted", "approved", "cancelled"},
        "submitted": {"approved", "cancelled", "draft"},
        "approved": {"cancelled", "partially_received", "fully_received"},
        "partially_received": {"fully_received"},
        "fully_received": set(),
        "cancelled": set(),
    }

    if target not in valid_transitions.get(current, set()):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid PO status transition from '{current}' to '{target}'.",
        )

    with get_connection() as conn:
        conn.execute("UPDATE purchase_orders SET status = ?, updated_at = ? WHERE id = ?", (target, now, po_id))
        conn.commit()

    record_erp_audit_log(
        "purchase_order",
        po_id,
        f"status_{target}",
        {"old_status": current, "new_status": target},
        performed_by,
    )

    updated = get_purchase_order_by_id(po_id)
    assert updated is not None
    return updated


# ===========================================================================
# 2. Goods Receipts Service
# ===========================================================================

def create_goods_receipt(data: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    receipt_number = (data.get("receipt_number") or "").strip().upper()
    if not receipt_number:
        raise HTTPException(status_code=400, detail="Receipt number cannot be empty.")

    idempotency_key = (data.get("idempotency_key") or "").strip()
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency key is required.")

    po_id = (data.get("po_id") or "").strip()
    if not po_id:
        raise HTTPException(status_code=400, detail="Target purchase order ID is required.")

    receipt_date = (data.get("receipt_date") or "").strip()
    if not receipt_date:
        raise HTTPException(status_code=400, detail="Receipt date is required.")

    items_data = data.get("items") or []
    if not items_data:
        raise HTTPException(status_code=400, detail="Goods receipt must have at least one line item.")

    now = datetime.now(timezone.utc).isoformat()
    receipt_id = f"gr-{uuid.uuid4().hex[:10]}"

    with get_connection() as conn:
        # Check idempotency key: return existing receipt if already created
        existing_key = conn.execute(
            "SELECT id FROM goods_receipts WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing_key:
            existing_receipt = get_goods_receipt_by_id(existing_key["id"])
            assert existing_receipt is not None
            if existing_receipt["po_id"] != po_id:
                raise HTTPException(
                    status_code=409,
                    detail=f"Idempotency key '{idempotency_key}' was previously used for PO '{existing_receipt['po_id']}'. Cannot reuse key with different target PO '{po_id}'.",
                )
            return existing_receipt

        # Check receipt number collision
        dup_num = conn.execute(
            "SELECT id FROM goods_receipts WHERE LOWER(receipt_number) = LOWER(?)",
            (receipt_number,),
        ).fetchone()
        if dup_num:
            raise HTTPException(status_code=409, detail=f"Goods receipt with number '{receipt_number}' already exists.")

        # Check purchase order eligibility
        po = conn.execute("SELECT id, po_number, supplier_id, status FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
        if not po:
            raise HTTPException(status_code=404, detail=f"Purchase order '{po_id}' not found.")

        if po["status"] not in ("approved", "partially_received"):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot receive goods for PO '{po['po_number']}' with status '{po['status']}'. PO must be 'approved' or 'partially_received'.",
            )

        supplier_id = po["supplier_id"]

        # Validate line items and prevent over-receipt
        receipt_lines = []
        for idx, itm in enumerate(items_data):
            po_item_id = (itm.get("po_item_id") or "").strip()
            received_qty = float(itm.get("received_qty") or 0.0)
            accepted_qty = float(itm.get("accepted_qty") or 0.0)
            rejected_qty = float(itm.get("rejected_qty") or 0.0)
            quarantined_qty = float(itm.get("quarantined_qty") or 0.0)

            if received_qty <= 0:
                raise HTTPException(status_code=400, detail=f"Line {idx + 1}: received quantity must be > 0.")
            if accepted_qty < 0 or rejected_qty < 0 or quarantined_qty < 0:
                raise HTTPException(status_code=400, detail=f"Line {idx + 1}: quantities cannot be negative.")

            # Validation: sum of QA split must equal received_qty
            if round(accepted_qty + rejected_qty + quarantined_qty, 4) != round(received_qty, 4):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Line {idx + 1}: sum of accepted ({accepted_qty}), rejected ({rejected_qty}), "
                        f"and quarantined ({quarantined_qty}) must equal received quantity ({received_qty})."
                    ),
                )

            poi = conn.execute(
                "SELECT id, po_id, product_id, sku, product_name, uom, ordered_qty, unit_price, received_qty "
                "FROM purchase_order_items WHERE id = ? AND po_id = ?",
                (po_item_id, po_id),
            ).fetchone()
            if not poi:
                raise HTTPException(status_code=400, detail=f"Line {idx + 1}: PO item '{po_item_id}' not found on PO '{po_id}'.")

            # Over-receipt check
            ordered = float(poi["ordered_qty"])
            already_received = float(poi["received_qty"])
            remaining = round(ordered - already_received, 4)

            if received_qty > remaining:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Over-receipt rejected: Product '{poi['sku']}' ordered {ordered}, "
                        f"already received {already_received}, remaining is {remaining}. "
                        f"Requested delivery of {received_qty} exceeds remaining balance."
                    ),
                )

            insp_status = itm.get("inspection_status") or "pending"
            if accepted_qty == received_qty:
                insp_status = "passed"
            elif rejected_qty == received_qty:
                insp_status = "rejected"
            elif quarantined_qty > 0:
                insp_status = "quarantine"

            receipt_lines.append({
                "id": f"gri-{uuid.uuid4().hex[:10]}",
                "receipt_id": receipt_id,
                "po_item_id": poi["id"],
                "product_id": poi["product_id"],
                "sku": poi["sku"],
                "product_name": poi["product_name"],
                "uom": poi["uom"],
                "unit_cost": float(poi["unit_price"]),
                "received_qty": received_qty,
                "accepted_qty": accepted_qty,
                "rejected_qty": rejected_qty,
                "quarantined_qty": quarantined_qty,
                "inspection_notes": itm.get("inspection_notes"),
                "rejection_reason": itm.get("rejection_reason"),
                "inspection_status": insp_status,
                "inspected_by": performed_by,
                "inspected_at": now,
                "created_at": now,
            })

        # Insert receipt header
        conn.execute(
            """
            INSERT INTO goods_receipts (
                id, receipt_number, idempotency_key, po_id, supplier_id,
                receipt_date, received_by, status, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)
            """,
            (
                receipt_id,
                receipt_number,
                idempotency_key,
                po_id,
                supplier_id,
                receipt_date,
                performed_by,
                data.get("notes"),
                now,
                now,
            ),
        )

        # Insert receipt lines
        for rl in receipt_lines:
            conn.execute(
                """
                INSERT INTO goods_receipt_items (
                    id, receipt_id, po_item_id, product_id, sku, product_name,
                    uom, unit_cost, received_qty, accepted_qty, rejected_qty,
                    quarantined_qty, inspection_notes, rejection_reason,
                    inspection_status, inspected_by, inspected_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rl["id"],
                    rl["receipt_id"],
                    rl["po_item_id"],
                    rl["product_id"],
                    rl["sku"],
                    rl["product_name"],
                    rl["uom"],
                    rl["unit_cost"],
                    rl["received_qty"],
                    rl["accepted_qty"],
                    rl["rejected_qty"],
                    rl["quarantined_qty"],
                    rl["inspection_notes"],
                    rl["rejection_reason"],
                    rl["inspection_status"],
                    rl["inspected_by"],
                    rl["inspected_at"],
                    rl["created_at"],
                ),
            )

            # Update PO line cumulative received quantity
            conn.execute(
                "UPDATE purchase_order_items SET received_qty = received_qty + ?, updated_at = ? WHERE id = ?",
                (rl["received_qty"], now, rl["po_item_id"]),
            )

        # Recalculate and update PO overall receipt status
        all_poi = conn.execute(
            "SELECT ordered_qty, received_qty FROM purchase_order_items WHERE po_id = ?",
            (po_id,),
        ).fetchall()

        all_fully_received = all(float(r["received_qty"]) >= float(r["ordered_qty"]) for r in all_poi)
        any_received = any(float(r["received_qty"]) > 0 for r in all_poi)

        new_po_status = "fully_received" if all_fully_received else ("partially_received" if any_received else "approved")
        conn.execute("UPDATE purchase_orders SET status = ?, updated_at = ? WHERE id = ?", (new_po_status, now, po_id))

        conn.commit()

    record_erp_audit_log(
        "goods_receipt",
        receipt_id,
        "create",
        {"receipt_number": receipt_number, "po_id": po_id, "lines_count": len(receipt_lines)},
        performed_by,
    )

    created = get_goods_receipt_by_id(receipt_id)
    assert created is not None
    return created


def get_goods_receipt_by_id(receipt_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        gr_row = conn.execute("SELECT * FROM goods_receipts WHERE id = ?", (receipt_id,)).fetchone()
        if not gr_row:
            return None

        po_row = conn.execute("SELECT po_number FROM purchase_orders WHERE id = ?", (gr_row["po_id"],)).fetchone()
        po_number = po_row["po_number"] if po_row else None

        sup_row = conn.execute("SELECT name FROM suppliers WHERE id = ?", (gr_row["supplier_id"],)).fetchone()
        supplier_name = sup_row["name"] if sup_row else None

        item_rows = conn.execute("SELECT * FROM goods_receipt_items WHERE receipt_id = ?", (receipt_id,)).fetchall()

    return _row_to_gr_dict(gr_row, item_rows, po_number, supplier_name)


def list_goods_receipts(
    search: str | None = None,
    status: str | None = None,
    po_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    clauses = []
    params: list[Any] = []

    if search:
        s = f"%{search.strip().lower()}%"
        clauses.append("(LOWER(gr.receipt_number) LIKE ? OR LOWER(COALESCE(gr.notes, '')) LIKE ?)")
        params.extend([s, s])
    if status:
        clauses.append("gr.status = ?")
        params.append(status.strip().lower())
    if po_id:
        clauses.append("gr.po_id = ?")
        params.append(po_id)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with get_connection() as conn:
        count_row = conn.execute(f"SELECT count(*) FROM goods_receipts gr {where}", params).fetchone()
        total = count_row[0]

        query = f"""
            SELECT gr.*, po.po_number, s.name as supplier_name
            FROM goods_receipts gr
            LEFT JOIN purchase_orders po ON gr.po_id = po.id
            LEFT JOIN suppliers s ON gr.supplier_id = s.id
            {where}
            ORDER BY gr.created_at DESC
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(query, params + [limit, offset]).fetchall()

        items = []
        for r in rows:
            line_items = conn.execute(
                "SELECT * FROM goods_receipt_items WHERE receipt_id = ?",
                (r["id"],),
            ).fetchall()
            items.append(_row_to_gr_dict(r, line_items, r["po_number"], r["supplier_name"]))

    return {"total": total, "items": items, "limit": limit, "offset": offset}


# ===========================================================================
# 3. Inventory Posting & Ledger Service
# ===========================================================================

def post_goods_receipt_to_inventory(
    receipt_id: str,
    idempotency_key: str,
    performed_by: str = "Local Operator",
) -> dict[str, Any]:
    """Posts accepted goods receipt quantities to available stock, and tracks rejected/quarantined goods.
    Enforces atomic transaction and exactly-once execution.
    """
    receipt = get_goods_receipt_by_id(receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail=f"Goods receipt '{receipt_id}' not found.")

    # Idempotent return if already posted
    if receipt["status"] == "posted":
        return {
            "status": "already_posted",
            "receipt": receipt,
            "message": f"Goods receipt '{receipt['receipt_number']}' is already posted to inventory.",
        }

    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        # Check idempotency key collision on inventory movements
        existing_mov = conn.execute(
            "SELECT id FROM inventory_movements WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing_mov:
            return {
                "status": "already_posted",
                "receipt": get_goods_receipt_by_id(receipt_id),
                "message": "Transaction already posted with this idempotency key.",
            }

        items = conn.execute(
            "SELECT * FROM goods_receipt_items WHERE receipt_id = ?",
            (receipt_id,),
        ).fetchall()

        movements_created = []

        for itm in items:
            product_id = itm["product_id"]
            sku = itm["sku"]
            unit_cost = float(itm["unit_cost"])
            accepted_qty = float(itm["accepted_qty"])
            quarantined_qty = float(itm["quarantined_qty"])
            rejected_qty = float(itm["rejected_qty"])

            # 1. Post Accepted Qty -> Available stock
            if accepted_qty > 0:
                mov_num = f"MOV-{uuid.uuid4().hex[:8].upper()}"
                mov_id = f"mov-{uuid.uuid4().hex[:10]}"
                mov_key = f"{idempotency_key}-avail-{itm['id']}"

                conn.execute(
                    """
                    INSERT INTO inventory_movements (
                        id, movement_number, idempotency_key, movement_type,
                        reference_doc_type, reference_doc_id, product_id, sku,
                        quantity, stock_type, unit_cost, total_cost, warehouse_id, location_id,
                        performed_by, notes, created_at
                    ) VALUES (?, ?, ?, 'RECEIPT_POST', 'goods_receipt', ?, ?, ?, ?, 'available', ?, ?, 'wh-main', 'loc-main-gen', ?, ?, ?)
                    """,
                    (
                        mov_id,
                        mov_num,
                        mov_key,
                        receipt_id,
                        product_id,
                        sku,
                        accepted_qty,
                        unit_cost,
                        round(accepted_qty * unit_cost, 2),
                        performed_by,
                        f"Receipt posting: {receipt['receipt_number']}",
                        now,
                    ),
                )
                movements_created.append(mov_num)

                # Update or insert into inventory_balances
                bal = conn.execute(
                    "SELECT on_hand_qty, total_value FROM inventory_balances WHERE product_id = ? AND stock_type = 'available'",
                    (product_id,),
                ).fetchone()

                if bal:
                    new_qty = float(bal["on_hand_qty"]) + accepted_qty
                    new_val = float(bal["total_value"]) + (accepted_qty * unit_cost)
                    conn.execute(
                        "UPDATE inventory_balances SET on_hand_qty = ?, total_value = ?, updated_at = ? WHERE product_id = ? AND stock_type = 'available'",
                        (new_qty, round(new_val, 2), now, product_id),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO inventory_balances (product_id, stock_type, sku, on_hand_qty, total_value, updated_at)
                        VALUES (?, 'available', ?, ?, ?, ?)
                        """,
                        (product_id, sku, accepted_qty, round(accepted_qty * unit_cost, 2), now),
                    )

                # Update location_inventory_balances
                conn.execute(
                    """
                    INSERT INTO location_inventory_balances (product_id, warehouse_id, location_id, stock_type, sku, on_hand_qty, total_value, updated_at)
                    VALUES (?, 'wh-main', 'loc-main-gen', 'available', ?, ?, ?, ?)
                    ON CONFLICT(product_id, warehouse_id, location_id, stock_type)
                    DO UPDATE SET on_hand_qty = on_hand_qty + excluded.on_hand_qty,
                                  total_value = total_value + excluded.total_value,
                                  updated_at = excluded.updated_at
                    """,
                    (product_id, sku, accepted_qty, round(accepted_qty * unit_cost, 2), now),
                )

            # 2. Post Quarantined Qty -> Quarantined stock (segregated from available)
            if quarantined_qty > 0:
                mov_num = f"MOV-{uuid.uuid4().hex[:8].upper()}"
                mov_id = f"mov-{uuid.uuid4().hex[:10]}"
                mov_key = f"{idempotency_key}-quar-{itm['id']}"

                conn.execute(
                    """
                    INSERT INTO inventory_movements (
                        id, movement_number, idempotency_key, movement_type,
                        reference_doc_type, reference_doc_id, product_id, sku,
                        quantity, stock_type, unit_cost, total_cost, warehouse_id, location_id,
                        performed_by, notes, created_at
                    ) VALUES (?, ?, ?, 'RECEIPT_POST', 'goods_receipt', ?, ?, ?, ?, 'quarantined', ?, ?, 'wh-main', 'loc-main-gen', ?, ?, ?)
                    """,
                    (
                        mov_id,
                        mov_num,
                        mov_key,
                        receipt_id,
                        product_id,
                        sku,
                        quarantined_qty,
                        unit_cost,
                        round(quarantined_qty * unit_cost, 2),
                        performed_by,
                        f"Quarantined stock from receipt {receipt['receipt_number']}",
                        now,
                    ),
                )
                movements_created.append(mov_num)

                bal = conn.execute(
                    "SELECT on_hand_qty, total_value FROM inventory_balances WHERE product_id = ? AND stock_type = 'quarantined'",
                    (product_id,),
                ).fetchone()

                if bal:
                    new_qty = float(bal["on_hand_qty"]) + quarantined_qty
                    new_val = float(bal["total_value"]) + (quarantined_qty * unit_cost)
                    conn.execute(
                        "UPDATE inventory_balances SET on_hand_qty = ?, total_value = ?, updated_at = ? WHERE product_id = ? AND stock_type = 'quarantined'",
                        (new_qty, round(new_val, 2), now, product_id),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO inventory_balances (product_id, stock_type, sku, on_hand_qty, total_value, updated_at)
                        VALUES (?, 'quarantined', ?, ?, ?, ?)
                        """,
                        (product_id, sku, quarantined_qty, round(quarantined_qty * unit_cost, 2), now),
                    )

                conn.execute(
                    """
                    INSERT INTO location_inventory_balances (product_id, warehouse_id, location_id, stock_type, sku, on_hand_qty, total_value, updated_at)
                    VALUES (?, 'wh-main', 'loc-main-gen', 'quarantined', ?, ?, ?, ?)
                    ON CONFLICT(product_id, warehouse_id, location_id, stock_type)
                    DO UPDATE SET on_hand_qty = on_hand_qty + excluded.on_hand_qty,
                                  total_value = total_value + excluded.total_value,
                                  updated_at = excluded.updated_at
                    """,
                    (product_id, sku, quarantined_qty, round(quarantined_qty * unit_cost, 2), now),
                )

            # 3. Post Rejected Qty -> Rejected stock (audited return/disposal staging)
            if rejected_qty > 0:
                mov_num = f"MOV-{uuid.uuid4().hex[:8].upper()}"
                mov_id = f"mov-{uuid.uuid4().hex[:10]}"
                mov_key = f"{idempotency_key}-rej-{itm['id']}"

                conn.execute(
                    """
                    INSERT INTO inventory_movements (
                        id, movement_number, idempotency_key, movement_type,
                        reference_doc_type, reference_doc_id, product_id, sku,
                        quantity, stock_type, unit_cost, total_cost, warehouse_id, location_id,
                        performed_by, notes, created_at
                    ) VALUES (?, ?, ?, 'RECEIPT_POST', 'goods_receipt', ?, ?, ?, ?, 'rejected', ?, ?, 'wh-main', 'loc-main-gen', ?, ?, ?)
                    """,
                    (
                        mov_id,
                        mov_num,
                        mov_key,
                        receipt_id,
                        product_id,
                        sku,
                        rejected_qty,
                        unit_cost,
                        round(rejected_qty * unit_cost, 2),
                        performed_by,
                        f"Rejected stock from receipt {receipt['receipt_number']}: {itm['rejection_reason'] or 'QA failure'}",
                        now,
                    ),
                )
                movements_created.append(mov_num)

                bal = conn.execute(
                    "SELECT on_hand_qty, total_value FROM inventory_balances WHERE product_id = ? AND stock_type = 'rejected'",
                    (product_id,),
                ).fetchone()

                if bal:
                    new_qty = float(bal["on_hand_qty"]) + rejected_qty
                    new_val = float(bal["total_value"]) + (rejected_qty * unit_cost)
                    conn.execute(
                        "UPDATE inventory_balances SET on_hand_qty = ?, total_value = ?, updated_at = ? WHERE product_id = ? AND stock_type = 'rejected'",
                        (new_qty, round(new_val, 2), now, product_id),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO inventory_balances (product_id, stock_type, sku, on_hand_qty, total_value, updated_at)
                        VALUES (?, 'rejected', ?, ?, ?, ?)
                        """,
                        (product_id, sku, rejected_qty, round(rejected_qty * unit_cost, 2), now),
                    )

                conn.execute(
                    """
                    INSERT INTO location_inventory_balances (product_id, warehouse_id, location_id, stock_type, sku, on_hand_qty, total_value, updated_at)
                    VALUES (?, 'wh-main', 'loc-main-gen', 'rejected', ?, ?, ?, ?)
                    ON CONFLICT(product_id, warehouse_id, location_id, stock_type)
                    DO UPDATE SET on_hand_qty = on_hand_qty + excluded.on_hand_qty,
                                  total_value = total_value + excluded.total_value,
                                  updated_at = excluded.updated_at
                    """,
                    (product_id, sku, rejected_qty, round(rejected_qty * unit_cost, 2), now),
                )

        # Set goods receipt status to 'posted'
        conn.execute(
            "UPDATE goods_receipts SET status = 'posted', updated_at = ? WHERE id = ?",
            (now, receipt_id),
        )
        conn.commit()

    record_erp_audit_log(
        "goods_receipt",
        receipt_id,
        "post_inventory",
        {"movements_created": len(movements_created), "idempotency_key": idempotency_key},
        performed_by,
    )

    posted_receipt = get_goods_receipt_by_id(receipt_id)
    return {
        "status": "posted",
        "receipt": posted_receipt,
        "movements_created": movements_created,
        "message": f"Goods receipt '{receipt['receipt_number']}' successfully posted {len(movements_created)} stock movements.",
    }


def list_inventory_balances(stock_type: str | None = None) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if stock_type:
        clauses.append("b.stock_type = ?")
        params.append(stock_type.strip().lower())

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with get_connection() as conn:
        query = f"""
            SELECT b.*, p.name as product_name
            FROM inventory_balances b
            LEFT JOIN products p ON b.product_id = p.id
            {where}
            ORDER BY b.sku ASC, b.stock_type ASC
        """
        rows = conn.execute(query, params).fetchall()

    return [
        {
            "product_id": r["product_id"],
            "sku": r["sku"],
            "product_name": r["product_name"],
            "stock_type": r["stock_type"],
            "on_hand_qty": float(r["on_hand_qty"]),
            "total_value": float(r["total_value"]),
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


def list_inventory_movements(
    product_id: str | None = None,
    movement_type: str | None = None,
    stock_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    clauses = []
    params: list[Any] = []

    if product_id:
        clauses.append("m.product_id = ?")
        params.append(product_id)
    if movement_type:
        clauses.append("m.movement_type = ?")
        params.append(movement_type)
    if stock_type:
        clauses.append("m.stock_type = ?")
        params.append(stock_type)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with get_connection() as conn:
        count_row = conn.execute(f"SELECT count(*) FROM inventory_movements m {where}", params).fetchone()
        total = count_row[0]

        query = f"""
            SELECT m.*, p.name as product_name
            FROM inventory_movements m
            LEFT JOIN products p ON m.product_id = p.id
            {where}
            ORDER BY m.created_at DESC
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(query, params + [limit, offset]).fetchall()

    items = [
        {
            "id": r["id"],
            "movement_number": r["movement_number"],
            "idempotency_key": r["idempotency_key"],
            "movement_type": r["movement_type"],
            "reference_doc_type": r["reference_doc_type"],
            "reference_doc_id": r["reference_doc_id"],
            "product_id": r["product_id"],
            "sku": r["sku"],
            "product_name": r["product_name"],
            "quantity": float(r["quantity"]),
            "stock_type": r["stock_type"],
            "unit_cost": float(r["unit_cost"]),
            "total_cost": float(r["total_cost"]),
            "performed_by": r["performed_by"],
            "notes": r["notes"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]

    return {"total": total, "items": items, "limit": limit, "offset": offset}
