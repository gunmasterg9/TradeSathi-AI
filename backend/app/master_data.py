"""TradeSathi AI — ExportMate ERP Module Phase 1: Core Master Data
Manages Product Master, Supplier Master, Customer Master, and ERP Audit Log.
Includes strict uniqueness, normalization, status transitions, and role-based access control.
"""

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from .db import get_connection


# Role permissions configuration
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {
        "read", "create", "update", "delete", "all",
        "create_product", "update_product",
        "create_supplier", "update_supplier",
        "create_customer", "update_customer",
        "create_po", "update_po", "submit_po", "approve_po", "cancel_po",
        "create_gr", "update_gr", "inspect_gr", "post_gr",
        "create_warehouse", "update_warehouse", "delete_warehouse",
        "create_location", "update_location", "delete_location",
        "create_transfer", "approve_transfer", "dispatch_transfer", "receive_transfer", "cancel_transfer",
        "create_adjustment", "approve_adjustment",
        "create_reservation", "release_reservation", "consume_reservation",
        "create_quotation", "update_quotation", "send_quotation", "accept_quotation", "reject_quotation", "convert_quotation",
        "create_order", "update_order", "confirm_order", "cancel_order", "allocate_order",
        "create_pick_list", "update_pick_list", "complete_pick_list", "pack_order",
        "create_dispatch", "deliver_dispatch",
        "create_return", "inspect_return", "process_return",
        "create_export_shipment", "update_export_shipment", "transition_export_shipment",
        "link_export_dispatch", "unlink_export_dispatch", "create_checklist_rule",
        "review_checklist_item", "generate_export_document", "review_export_document",
    },
    "manager": {
        "read", "create", "update", "delete",
        "create_product", "update_product",
        "create_supplier", "update_supplier",
        "create_customer", "update_customer",
        "create_po", "update_po", "submit_po", "approve_po", "cancel_po",
        "create_gr", "update_gr", "inspect_gr", "post_gr",
        "create_warehouse", "update_warehouse",
        "create_location", "update_location",
        "create_transfer", "approve_transfer", "dispatch_transfer", "receive_transfer", "cancel_transfer",
        "create_adjustment", "approve_adjustment",
        "create_reservation", "release_reservation", "consume_reservation",
        "create_quotation", "update_quotation", "send_quotation", "accept_quotation", "reject_quotation", "convert_quotation",
        "create_order", "update_order", "confirm_order", "cancel_order", "allocate_order",
        "create_pick_list", "update_pick_list", "complete_pick_list", "pack_order",
        "create_dispatch", "deliver_dispatch",
        "create_return", "inspect_return", "process_return",
        "create_export_shipment", "update_export_shipment", "transition_export_shipment",
        "link_export_dispatch", "unlink_export_dispatch", "create_checklist_rule",
        "review_checklist_item", "generate_export_document", "review_export_document",
        "create_invoice", "update_invoice", "record_payment", "create_credit_note",
        "view_dashboard", "view_financial_reports", "export_reports",
        "scan_portal", "print_labels", "execute_scan_operations",
    },
    "procurement": {
        "read", "create_product", "update_product",
        "create_supplier", "update_supplier",
        "create_po", "update_po", "submit_po",
        "create_gr", "update_gr",
        "create_transfer",
        "create_reservation", "release_reservation",
        "view_dashboard",
        "scan_portal", "print_labels",
    },
    "sales": {
        "read", "create_product", "update_product",
        "create_customer", "update_customer",
        "create_reservation", "release_reservation",
        "create_quotation", "update_quotation", "send_quotation", "accept_quotation", "reject_quotation", "convert_quotation",
        "create_order", "update_order", "confirm_order", "cancel_order", "allocate_order",
        "create_return",
        "create_export_shipment", "update_export_shipment", "transition_export_shipment",
        "link_export_dispatch", "unlink_export_dispatch", "generate_export_document",
        "create_invoice", "update_invoice",
        "view_dashboard",
        "scan_portal", "print_labels",
    },
    "warehouse": {
        "read", "create_gr", "update_gr", "inspect_gr", "post_gr",
        "create_warehouse", "update_warehouse",
        "create_location", "update_location",
        "create_transfer", "approve_transfer", "dispatch_transfer", "receive_transfer", "cancel_transfer",
        "create_adjustment", "approve_adjustment",
        "create_reservation", "consume_reservation",
        "allocate_order", "create_pick_list", "update_pick_list", "complete_pick_list", "pack_order",
        "create_dispatch", "deliver_dispatch",
        "inspect_return", "process_return",
        "link_export_dispatch", "unlink_export_dispatch", "generate_export_document",
        "view_dashboard",
        "scan_portal", "print_labels", "execute_scan_operations",
    },
    "operator": {
        "read",
        "create_export_shipment", "update_export_shipment", "transition_export_shipment",
        "link_export_dispatch", "unlink_export_dispatch", "generate_export_document",
        "review_checklist_item",
        "create_invoice", "update_invoice", "record_payment", "create_credit_note",
        "view_dashboard",
        "scan_portal", "execute_scan_operations",
    },
    "viewer": {"read", "view_dashboard", "scan_portal"},
}


def verify_role_permission(role: str, action: str) -> None:
    """Enforce role-based access control. Raises HTTP 403 if unauthorized."""
    normalized_role = (role or "viewer").strip().lower()
    allowed_actions = ROLE_PERMISSIONS.get(normalized_role, {"read"})
    if action not in allowed_actions and "all" not in allowed_actions:
        # Check general action category
        if "update" in action and "update" in allowed_actions:
            return
        if "create" in action and "create" in allowed_actions:
            return
        raise HTTPException(
            status_code=403,
            detail=f"Permission denied: role '{normalized_role}' is not authorized to perform '{action}'.",
        )


def record_erp_audit_log(
    entity_type: str,
    entity_id: str,
    action: str,
    changes: dict[str, Any],
    performed_by: str = "Local Operator",
) -> None:
    """Append-only audit trail for master data changes."""
    log_id = f"aud-{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc).isoformat()
    changes_json = json.dumps(changes, default=str)

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO erp_audit_logs (
                id, entity_type, entity_id, action, performed_by, changes_json, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (log_id, entity_type, entity_id, action, performed_by, changes_json, now),
        )
        conn.commit()


def list_erp_audit_logs(
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    clauses = []
    params: list[Any] = []
    if entity_type:
        clauses.append("entity_type = ?")
        params.append(entity_type)
    if entity_id:
        clauses.append("entity_id = ?")
        params.append(entity_id)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with get_connection() as conn:
        count_cur = conn.execute(f"SELECT count(*) FROM erp_audit_logs {where}", params)
        total = count_cur.fetchone()[0]

        query = f"""
            SELECT id, entity_type, entity_id, action, performed_by, changes_json, timestamp
            FROM erp_audit_logs
            {where}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(query, params + [limit, offset]).fetchall()

    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "entity_type": r["entity_type"],
            "entity_id": r["entity_id"],
            "action": r["action"],
            "performed_by": r["performed_by"],
            "changes": json.loads(r["changes_json"]) if r["changes_json"] else {},
            "timestamp": r["timestamp"],
        })

    return {"total": total, "items": items, "limit": limit, "offset": offset}


# ===========================================================================
# Product Master Operations
# ===========================================================================

def _row_to_product_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "sku": row["sku"],
        "name": row["name"],
        "description": row["description"],
        "category": row["category"],
        "uom": row["uom"],
        "purchase_uom": row["purchase_uom"],
        "conversion_factor": row["conversion_factor"],
        "default_purchase_cost": row["default_purchase_cost"],
        "default_selling_price": row["default_selling_price"],
        "currency": row["currency"],
        "hsn_code": row["hsn_code"],
        "tax_rate_pct": row["tax_rate_pct"],
        "country_of_origin": row["country_of_origin"],
        "net_weight_kg": row["net_weight_kg"],
        "gross_weight_kg": row["gross_weight_kg"],
        "barcode": row["barcode"],
        "batch_tracking": bool(row["batch_tracking"]),
        "is_active": bool(row["is_active"]),
        "notes": row["notes"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_product(data: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    sku = data["sku"].strip().upper()
    if not sku:
        raise HTTPException(status_code=400, detail="Product SKU cannot be empty.")
    name = data["name"].strip()
    if not name:
        raise HTTPException(status_code=400, detail="Product name cannot be empty.")

    # Check duplicate SKU
    with get_connection() as conn:
        existing = conn.execute("SELECT id FROM products WHERE LOWER(sku) = LOWER(?)", (sku,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail=f"Product with SKU '{sku}' already exists.")

        barcode = data.get("barcode")
        if barcode:
            barcode = barcode.strip()
            existing_bc = conn.execute("SELECT id FROM products WHERE barcode = ?", (barcode,)).fetchone()
            if existing_bc:
                raise HTTPException(status_code=409, detail=f"Product with barcode '{barcode}' already exists.")

        product_id = data.get("id") or f"prd-{uuid.uuid4().hex[:10]}"
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """
            INSERT INTO products (
                id, sku, name, description, category, uom, purchase_uom,
                conversion_factor, default_purchase_cost, default_selling_price,
                currency, hsn_code, tax_rate_pct, country_of_origin,
                net_weight_kg, gross_weight_kg, barcode, batch_tracking,
                is_active, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product_id,
                sku,
                name,
                data.get("description"),
                data.get("category") or "General",
                (data.get("uom") or "PCS").strip().upper(),
                (data.get("purchase_uom") or "").strip().upper() or None,
                float(data.get("conversion_factor") if data.get("conversion_factor") is not None else 1.0),
                float(data.get("default_purchase_cost") if data.get("default_purchase_cost") is not None else 0.0),
                float(data.get("default_selling_price") if data.get("default_selling_price") is not None else 0.0),
                (data.get("currency") or "INR").strip().upper(),
                data.get("hsn_code"),
                float(data.get("tax_rate_pct") if data.get("tax_rate_pct") is not None else 0.0),
                (data.get("country_of_origin") or "IN").strip().upper(),
                float(data.get("net_weight_kg") if data.get("net_weight_kg") is not None else 0.0),
                float(data.get("gross_weight_kg") if data.get("gross_weight_kg") is not None else 0.0),
                barcode or None,
                1 if data.get("batch_tracking") else 0,
                1 if data.get("is_active", True) else 0,
                data.get("notes"),
                now,
                now,
            ),
        )
        conn.commit()

    created = get_product_by_id(product_id)
    assert created is not None
    record_erp_audit_log("product", product_id, "create", {"sku": sku, "name": name}, performed_by)
    return created


def get_product_by_id(product_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    return _row_to_product_dict(row) if row else None


def get_product_by_sku(sku: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM products WHERE LOWER(TRIM(sku)) = LOWER(TRIM(?))", (sku,)).fetchone()
    return _row_to_product_dict(row) if row else None


def list_products(
    search: str | None = None,
    category: str | None = None,
    is_active: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    clauses = []
    params: list[Any] = []

    if search:
        s = f"%{search.strip().lower()}%"
        clauses.append("(LOWER(sku) LIKE ? OR LOWER(name) LIKE ? OR LOWER(COALESCE(description, '')) LIKE ? OR LOWER(COALESCE(hsn_code, '')) LIKE ? OR barcode LIKE ?)")
        params.extend([s, s, s, s, s])
    if category:
        clauses.append("LOWER(category) = LOWER(?)")
        params.append(category.strip())
    if is_active is not None:
        clauses.append("is_active = ?")
        params.append(1 if is_active else 0)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with get_connection() as conn:
        count_row = conn.execute(f"SELECT count(*) FROM products {where}", params).fetchone()
        total = count_row[0]

        query = f"""
            SELECT * FROM products
            {where}
            ORDER BY sku ASC
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(query, params + [limit, offset]).fetchall()

    items = [_row_to_product_dict(r) for r in rows]
    return {"total": total, "items": items, "limit": limit, "offset": offset}


def update_product(product_id: str, updates: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    existing = get_product_by_id(product_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Product with ID '{product_id}' not found.")

    allowed_fields = {
        "sku", "name", "description", "category", "uom", "purchase_uom",
        "conversion_factor", "default_purchase_cost", "default_selling_price",
        "currency", "hsn_code", "tax_rate_pct", "country_of_origin",
        "net_weight_kg", "gross_weight_kg", "barcode", "batch_tracking",
        "is_active", "notes"
    }

    set_clauses = []
    params: list[Any] = []
    changes = {}

    with get_connection() as conn:
        for field, value in updates.items():
            if field in allowed_fields and value is not None:
                if field == "sku":
                    sku = str(value).strip().upper()
                    # Check uniqueness if changed
                    if sku != existing["sku"]:
                        chk = conn.execute("SELECT id FROM products WHERE LOWER(sku) = LOWER(?) AND id != ?", (sku, product_id)).fetchone()
                        if chk:
                            raise HTTPException(status_code=409, detail=f"Product with SKU '{sku}' already exists.")
                    set_clauses.append("sku = ?")
                    params.append(sku)
                    changes["sku"] = {"old": existing["sku"], "new": sku}
                elif field == "barcode":
                    bc = str(value).strip() if value else None
                    if bc and bc != existing.get("barcode"):
                        chk = conn.execute("SELECT id FROM products WHERE barcode = ? AND id != ?", (bc, product_id)).fetchone()
                        if chk:
                            raise HTTPException(status_code=409, detail=f"Product with barcode '{bc}' already exists.")
                    set_clauses.append("barcode = ?")
                    params.append(bc)
                    changes["barcode"] = {"old": existing.get("barcode"), "new": bc}
                elif field in ("batch_tracking", "is_active"):
                    int_val = 1 if value else 0
                    set_clauses.append(f"{field} = ?")
                    params.append(int_val)
                    changes[field] = {"old": existing.get(field), "new": bool(int_val)}
                else:
                    set_clauses.append(f"{field} = ?")
                    params.append(value)
                    changes[field] = {"old": existing.get(field), "new": value}

        if not set_clauses:
            return existing

        now = datetime.now(timezone.utc).isoformat()
        set_clauses.append("updated_at = ?")
        params.append(now)
        params.append(product_id)

        conn.execute(f"UPDATE products SET {', '.join(set_clauses)} WHERE id = ?", params)
        conn.commit()

    record_erp_audit_log("product", product_id, "update", changes, performed_by)
    updated = get_product_by_id(product_id)
    assert updated is not None
    return updated


def delete_product(product_id: str, performed_by: str = "Local Operator") -> bool:
    existing = get_product_by_id(product_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Product with ID '{product_id}' not found.")

    with get_connection() as conn:
        # Referential integrity check: check purchase_order_items, goods_receipt_items, inventory_movements
        try:
            ref_poi = conn.execute("SELECT count(*) FROM purchase_order_items WHERE product_id = ?", (product_id,)).fetchone()[0]
            if ref_poi > 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot delete product '{existing['sku']}': referenced by {ref_poi} purchase order line(s). Please deactivate the product instead."
                )
            ref_gri = conn.execute("SELECT count(*) FROM goods_receipt_items WHERE product_id = ?", (product_id,)).fetchone()[0]
            if ref_gri > 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot delete product '{existing['sku']}': referenced by {ref_gri} goods receipt line(s). Please deactivate the product instead."
                )
            ref_mov = conn.execute("SELECT count(*) FROM inventory_movements WHERE product_id = ?", (product_id,)).fetchone()[0]
            if ref_mov > 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot delete product '{existing['sku']}': referenced by {ref_mov} inventory movement(s). Please deactivate the product instead."
                )
        except sqlite3.OperationalError:
            pass  # Tables might not exist in early tests

        try:
            conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
            conn.commit()
        except sqlite3.IntegrityError as e:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot delete product '{existing['sku']}': referenced by existing transactions ({e}). Please deactivate instead."
            )

    record_erp_audit_log("product", product_id, "delete", {"sku": existing["sku"], "name": existing["name"]}, performed_by)
    return True


# ===========================================================================
# Supplier Master Operations
# ===========================================================================

def _row_to_supplier_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "code": row["code"],
        "name": row["name"],
        "legal_name": row["legal_name"],
        "tax_id": row["tax_id"],
        "country": row["country"],
        "state": row["state"],
        "address": row["address"],
        "contact_person": row["contact_person"],
        "email": row["email"],
        "phone": row["phone"],
        "currency": row["currency"],
        "payment_terms": row["payment_terms"],
        "payment_terms_days": row["payment_terms_days"],
        "bank_name": row["bank_name"],
        "bank_account_no": row["bank_account_no"],
        "bank_ifsc_swift": row["bank_ifsc_swift"],
        "status": row["status"],
        "notes": row["notes"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_supplier(data: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    code = data["code"].strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Supplier code cannot be empty.")
    name = data["name"].strip()
    if not name:
        raise HTTPException(status_code=400, detail="Supplier name cannot be empty.")

    with get_connection() as conn:
        existing = conn.execute("SELECT id FROM suppliers WHERE LOWER(code) = LOWER(?)", (code,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail=f"Supplier with code '{code}' already exists.")

        supplier_id = data.get("id") or f"sup-{uuid.uuid4().hex[:10]}"
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """
            INSERT INTO suppliers (
                id, code, name, legal_name, tax_id, country, state, address,
                contact_person, email, phone, currency, payment_terms,
                payment_terms_days, bank_name, bank_account_no, bank_ifsc_swift,
                status, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                supplier_id,
                code,
                name,
                data.get("legal_name"),
                data.get("tax_id"),
                (data.get("country") or "IN").strip().upper(),
                data.get("state"),
                data.get("address"),
                data.get("contact_person"),
                data.get("email"),
                data.get("phone"),
                (data.get("currency") or "INR").strip().upper(),
                (data.get("payment_terms") or "Net 30").strip(),
                int(data.get("payment_terms_days") if data.get("payment_terms_days") is not None else 30),
                data.get("bank_name"),
                data.get("bank_account_no"),
                data.get("bank_ifsc_swift"),
                (data.get("status") or "active").strip().lower(),
                data.get("notes"),
                now,
                now,
            ),
        )
        conn.commit()

    created = get_supplier_by_id(supplier_id)
    assert created is not None
    record_erp_audit_log("supplier", supplier_id, "create", {"code": code, "name": name}, performed_by)
    return created


def get_supplier_by_id(supplier_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
    return _row_to_supplier_dict(row) if row else None


def get_supplier_by_code(code: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM suppliers WHERE LOWER(TRIM(code)) = LOWER(TRIM(?))", (code,)).fetchone()
    return _row_to_supplier_dict(row) if row else None


def list_suppliers(
    search: str | None = None,
    status: str | None = None,
    country: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    clauses = []
    params: list[Any] = []

    if search:
        s = f"%{search.strip().lower()}%"
        clauses.append("(LOWER(code) LIKE ? OR LOWER(name) LIKE ? OR LOWER(COALESCE(tax_id, '')) LIKE ? OR LOWER(COALESCE(contact_person, '')) LIKE ? OR LOWER(COALESCE(email, '')) LIKE ?)")
        params.extend([s, s, s, s, s])
    if status:
        clauses.append("LOWER(status) = LOWER(?)")
        params.append(status.strip())
    if country:
        clauses.append("LOWER(country) = LOWER(?)")
        params.append(country.strip())

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with get_connection() as conn:
        count_row = conn.execute(f"SELECT count(*) FROM suppliers {where}", params).fetchone()
        total = count_row[0]

        query = f"""
            SELECT * FROM suppliers
            {where}
            ORDER BY code ASC
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(query, params + [limit, offset]).fetchall()

    items = [_row_to_supplier_dict(r) for r in rows]
    return {"total": total, "items": items, "limit": limit, "offset": offset}


def update_supplier(supplier_id: str, updates: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    existing = get_supplier_by_id(supplier_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Supplier with ID '{supplier_id}' not found.")

    allowed_fields = {
        "code", "name", "legal_name", "tax_id", "country", "state", "address",
        "contact_person", "email", "phone", "currency", "payment_terms",
        "payment_terms_days", "bank_name", "bank_account_no", "bank_ifsc_swift",
        "status", "notes"
    }

    set_clauses = []
    params: list[Any] = []
    changes = {}

    with get_connection() as conn:
        for field, value in updates.items():
            if field in allowed_fields and value is not None:
                if field == "code":
                    code = str(value).strip().upper()
                    if code != existing["code"]:
                        chk = conn.execute("SELECT id FROM suppliers WHERE LOWER(code) = LOWER(?) AND id != ?", (code, supplier_id)).fetchone()
                        if chk:
                            raise HTTPException(status_code=409, detail=f"Supplier with code '{code}' already exists.")
                    set_clauses.append("code = ?")
                    params.append(code)
                    changes["code"] = {"old": existing["code"], "new": code}
                else:
                    set_clauses.append(f"{field} = ?")
                    params.append(value)
                    changes[field] = {"old": existing.get(field), "new": value}

        if not set_clauses:
            return existing

        now = datetime.now(timezone.utc).isoformat()
        set_clauses.append("updated_at = ?")
        params.append(now)
        params.append(supplier_id)

        conn.execute(f"UPDATE suppliers SET {', '.join(set_clauses)} WHERE id = ?", params)
        conn.commit()

    record_erp_audit_log("supplier", supplier_id, "update", changes, performed_by)
    updated = get_supplier_by_id(supplier_id)
    assert updated is not None
    return updated


def delete_supplier(supplier_id: str, performed_by: str = "Local Operator") -> bool:
    existing = get_supplier_by_id(supplier_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Supplier with ID '{supplier_id}' not found.")

    with get_connection() as conn:
        try:
            ref_po = conn.execute("SELECT count(*) FROM purchase_orders WHERE supplier_id = ?", (supplier_id,)).fetchone()[0]
            if ref_po > 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot delete supplier '{existing['code']}': referenced by {ref_po} purchase order(s). Please deactivate the supplier instead."
                )
            ref_gr = conn.execute("SELECT count(*) FROM goods_receipts WHERE supplier_id = ?", (supplier_id,)).fetchone()[0]
            if ref_gr > 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot delete supplier '{existing['code']}': referenced by {ref_gr} goods receipt(s). Please deactivate the supplier instead."
                )
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute("DELETE FROM suppliers WHERE id = ?", (supplier_id,))
            conn.commit()
        except sqlite3.IntegrityError as e:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot delete supplier '{existing['code']}': referenced by existing transactions ({e}). Please deactivate instead."
            )

    record_erp_audit_log("supplier", supplier_id, "delete", {"code": existing["code"], "name": existing["name"]}, performed_by)
    return True


# ===========================================================================
# Customer Master Operations
# ===========================================================================

def _row_to_customer_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "code": row["code"],
        "name": row["name"],
        "legal_name": row["legal_name"],
        "tax_id": row["tax_id"],
        "customer_type": row["customer_type"],
        "country": row["country"],
        "destination_port": row["destination_port"],
        "billing_address": row["billing_address"],
        "shipping_address": row["shipping_address"],
        "contact_person": row["contact_person"],
        "email": row["email"],
        "phone": row["phone"],
        "currency": row["currency"],
        "payment_terms": row["payment_terms"],
        "payment_terms_days": row["payment_terms_days"],
        "credit_limit": row["credit_limit"],
        "incoterm_preference": row["incoterm_preference"],
        "status": row["status"],
        "notes": row["notes"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_customer(data: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    code = data["code"].strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Customer code cannot be empty.")
    name = data["name"].strip()
    if not name:
        raise HTTPException(status_code=400, detail="Customer name cannot be empty.")
    country = data.get("country", "").strip().upper()
    if not country:
        raise HTTPException(status_code=400, detail="Customer country is required.")

    with get_connection() as conn:
        existing = conn.execute("SELECT id FROM customers WHERE LOWER(code) = LOWER(?)", (code,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail=f"Customer with code '{code}' already exists.")

        customer_id = data.get("id") or f"cus-{uuid.uuid4().hex[:10]}"
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """
            INSERT INTO customers (
                id, code, name, legal_name, tax_id, customer_type, country,
                destination_port, billing_address, shipping_address, contact_person,
                email, phone, currency, payment_terms, payment_terms_days,
                credit_limit, incoterm_preference, status, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                customer_id,
                code,
                name,
                data.get("legal_name"),
                data.get("tax_id"),
                (data.get("customer_type") or "international").strip().lower(),
                country,
                data.get("destination_port"),
                data.get("billing_address"),
                data.get("shipping_address"),
                data.get("contact_person"),
                data.get("email"),
                data.get("phone"),
                (data.get("currency") or "USD").strip().upper(),
                (data.get("payment_terms") or "LC at sight").strip(),
                int(data.get("payment_terms_days") if data.get("payment_terms_days") is not None else 30),
                float(data.get("credit_limit") if data.get("credit_limit") is not None else 0.0),
                (data.get("incoterm_preference") or "FOB").strip().upper(),
                (data.get("status") or "active").strip().lower(),
                data.get("notes"),
                now,
                now,
            ),
        )
        conn.commit()

    created = get_customer_by_id(customer_id)
    assert created is not None
    record_erp_audit_log("customer", customer_id, "create", {"code": code, "name": name}, performed_by)
    return created


def get_customer_by_id(customer_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    return _row_to_customer_dict(row) if row else None


def get_customer_by_code(code: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM customers WHERE LOWER(TRIM(code)) = LOWER(TRIM(?))", (code,)).fetchone()
    return _row_to_customer_dict(row) if row else None


def list_customers(
    search: str | None = None,
    status: str | None = None,
    country: str | None = None,
    customer_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    clauses = []
    params: list[Any] = []

    if search:
        s = f"%{search.strip().lower()}%"
        clauses.append("(LOWER(code) LIKE ? OR LOWER(name) LIKE ? OR LOWER(COALESCE(tax_id, '')) LIKE ? OR LOWER(COALESCE(destination_port, '')) LIKE ? OR LOWER(COALESCE(contact_person, '')) LIKE ? OR LOWER(COALESCE(email, '')) LIKE ?)")
        params.extend([s, s, s, s, s, s])
    if status:
        clauses.append("LOWER(status) = LOWER(?)")
        params.append(status.strip())
    if country:
        clauses.append("LOWER(country) = LOWER(?)")
        params.append(country.strip())
    if customer_type:
        clauses.append("LOWER(customer_type) = LOWER(?)")
        params.append(customer_type.strip())

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with get_connection() as conn:
        count_row = conn.execute(f"SELECT count(*) FROM customers {where}", params).fetchone()
        total = count_row[0]

        query = f"""
            SELECT * FROM customers
            {where}
            ORDER BY code ASC
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(query, params + [limit, offset]).fetchall()

    items = [_row_to_customer_dict(r) for r in rows]
    return {"total": total, "items": items, "limit": limit, "offset": offset}


def update_customer(customer_id: str, updates: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    existing = get_customer_by_id(customer_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Customer with ID '{customer_id}' not found.")

    allowed_fields = {
        "code", "name", "legal_name", "tax_id", "customer_type", "country",
        "destination_port", "billing_address", "shipping_address", "contact_person",
        "email", "phone", "currency", "payment_terms", "payment_terms_days",
        "credit_limit", "incoterm_preference", "status", "notes"
    }

    set_clauses = []
    params: list[Any] = []
    changes = {}

    with get_connection() as conn:
        for field, value in updates.items():
            if field in allowed_fields and value is not None:
                if field == "code":
                    code = str(value).strip().upper()
                    if code != existing["code"]:
                        chk = conn.execute("SELECT id FROM customers WHERE LOWER(code) = LOWER(?) AND id != ?", (code, customer_id)).fetchone()
                        if chk:
                            raise HTTPException(status_code=409, detail=f"Customer with code '{code}' already exists.")
                    set_clauses.append("code = ?")
                    params.append(code)
                    changes["code"] = {"old": existing["code"], "new": code}
                else:
                    set_clauses.append(f"{field} = ?")
                    params.append(value)
                    changes[field] = {"old": existing.get(field), "new": value}

        if not set_clauses:
            return existing

        now = datetime.now(timezone.utc).isoformat()
        set_clauses.append("updated_at = ?")
        params.append(now)
        params.append(customer_id)

        conn.execute(f"UPDATE customers SET {', '.join(set_clauses)} WHERE id = ?", params)
        conn.commit()

    record_erp_audit_log("customer", customer_id, "update", changes, performed_by)
    updated = get_customer_by_id(customer_id)
    assert updated is not None
    return updated


def delete_customer(customer_id: str, performed_by: str = "Local Operator") -> bool:
    existing = get_customer_by_id(customer_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Customer with ID '{customer_id}' not found.")

    with get_connection() as conn:
        conn.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
        conn.commit()

    record_erp_audit_log("customer", customer_id, "delete", {"code": existing["code"], "name": existing["name"]}, performed_by)
    return True
