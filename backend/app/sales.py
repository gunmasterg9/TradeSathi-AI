"""
TradeSathi AI — Phase 4: Sales Orders, Quotations & Fulfilment Service
Implements:
1. Customer Quotations (draft, sent, accepted, rejected, converted to sales order)
2. Sales Orders (draft, confirmed, allocated, picking, packed, dispatched, delivered, cancelled)
3. Inventory Allocation via authoritative Phase 3 ATP & Reservation Engine
4. Picking and Packing Workflows with Short-Pick Auditing
5. Commercial Dispatch & Delivery Integration (Exactly-once ledger posting, shipment linking)
6. Controlled Sales Returns Foundation (Available restock vs Quarantined/Rejected segregation)
7. Full Append-Only Audit Trail & Role-Based Permissions
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
import sqlite3

from app.auth import AuthenticatedUser, get_current_user
from app.db import get_connection
from app.master_data import record_erp_audit_log, verify_role_permission
from app.warehouse import (
    create_stock_reservation,
    get_product_atp,
    get_stock_reservation_by_id,
    release_stock_reservation,
)
from app.schemas import (
    QuotationConvertRequest,
    QuotationCreateRequest,
    QuotationListResponse,
    QuotationResponse,
    QuotationUpdateRequest,
    SalesDispatchCreateRequest,
    SalesDispatchDeliveryRequest,
    SalesDispatchListResponse,
    SalesDispatchResponse,
    SalesOrderAllocateRequest,
    SalesOrderCreateRequest,
    SalesOrderListResponse,
    SalesOrderPackRequest,
    SalesOrderResponse,
    SalesOrderUpdateRequest,
    SalesPickListCompleteRequest,
    SalesPickListCreateRequest,
    SalesPickListListResponse,
    SalesPickListResponse,
    SalesReturnCreateRequest,
    SalesReturnListResponse,
    SalesReturnProcessRequest,
    SalesReturnResponse,
)

router = APIRouter(tags=["Sales & Fulfilment"])


def _calculate_line_amounts(qty: float, price: float, discount_pct: float, tax_rate_pct: float) -> tuple[float, float, float, float]:
    subtotal = round(qty * price, 2)
    discount_amount = round(subtotal * (discount_pct / 100.0), 2)
    tax_base = subtotal - discount_amount
    tax_amount = round(tax_base * (tax_rate_pct / 100.0), 2)
    line_total = round(tax_base + tax_amount, 2)
    return subtotal, discount_amount, tax_amount, line_total


def _update_inventory_balance(conn, product_id: str, sku: str, stock_type: str, delta: float, now_iso: str) -> None:
    bal = conn.execute(
        "SELECT on_hand_qty FROM inventory_balances WHERE product_id = ? AND stock_type = ?",
        (product_id, stock_type),
    ).fetchone()
    if bal:
        conn.execute(
            "UPDATE inventory_balances SET on_hand_qty = on_hand_qty + ?, updated_at = ? WHERE product_id = ? AND stock_type = ?",
            (delta, now_iso, product_id, stock_type),
        )
    else:
        conn.execute(
            "INSERT INTO inventory_balances (product_id, stock_type, sku, on_hand_qty, total_value, updated_at) VALUES (?, ?, ?, ?, 0.0, ?)",
            (product_id, stock_type, sku, delta, now_iso),
        )


# ==========================================
# 1. Customer Quotations
# ==========================================

def create_customer_quotation(data: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    customer_id = data.get("customer_id")
    if not customer_id:
        raise HTTPException(status_code=400, detail="Customer ID is required.")

    items_data = data.get("items", [])
    if not items_data:
        raise HTTPException(status_code=400, detail="At least one quotation line item is required.")

    with get_connection() as conn:
        customer = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
        if not customer:
            raise HTTPException(status_code=400, detail=f"Customer '{customer_id}' not found.")
        if customer["status"] != "active":
            raise HTTPException(status_code=400, detail=f"Customer '{customer['code']}' is not active.")

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        date_str = now.strftime("%Y%m%d")

        count_row = conn.execute("SELECT count(*) FROM customer_quotations WHERE quotation_number LIKE ?", (f"QUO-{date_str}-%",)).fetchone()
        seq = (count_row[0] or 0) + 1
        quotation_number = f"QUO-{date_str}-{seq:04d}"
        quotation_id = f"quo-{uuid.uuid4().hex[:10]}"

        subtotal_sum = 0.0
        discount_sum = 0.0
        tax_sum = 0.0
        grand_total_sum = 0.0

        item_records = []
        for idx, item in enumerate(items_data):
            prod_id = item.get("product_id")
            qty = float(item.get("quantity", 0.0))
            price = float(item.get("unit_price", 0.0))
            disc_pct = float(item.get("discount_pct", 0.0))
            tax_pct = float(item.get("tax_rate_pct", 0.0))

            if not prod_id:
                raise HTTPException(status_code=400, detail="Product ID is required for each line item.")
            if qty <= 0:
                raise HTTPException(status_code=400, detail=f"Line {idx+1}: Quantity must be greater than zero.")
            if price < 0:
                raise HTTPException(status_code=400, detail=f"Line {idx+1}: Unit price cannot be negative.")
            if disc_pct < 0 or disc_pct > 100:
                raise HTTPException(status_code=400, detail=f"Line {idx+1}: Discount percentage must be between 0 and 100.")
            if tax_pct < 0:
                raise HTTPException(status_code=400, detail=f"Line {idx+1}: Tax rate percentage cannot be negative.")

            prod = conn.execute("SELECT sku, name, uom, is_active FROM products WHERE id = ?", (prod_id,)).fetchone()
            if not prod:
                raise HTTPException(status_code=400, detail=f"Line {idx+1}: Product '{prod_id}' not found.")
            if not prod["is_active"]:
                raise HTTPException(status_code=400, detail=f"Line {idx+1}: Product '{prod['sku']}' is inactive.")

            line_sub, line_disc, line_tax, line_tot = _calculate_line_amounts(qty, price, disc_pct, tax_pct)
            subtotal_sum += line_sub
            discount_sum += line_disc
            tax_sum += line_tax
            grand_total_sum += line_tot

            item_records.append({
                "id": f"qti-{uuid.uuid4().hex[:10]}",
                "quotation_id": quotation_id,
                "product_id": prod_id,
                "product_sku": prod["sku"],
                "product_name": prod["name"],
                "uom": prod["uom"] or "PCS",
                "quantity": qty,
                "unit_price": price,
                "discount_pct": disc_pct,
                "tax_rate_pct": tax_pct,
                "subtotal": line_sub,
                "discount_amount": line_disc,
                "tax_amount": line_tax,
                "line_total": line_tot,
                "sort_order": idx,
                "created_at": now_iso,
            })

        quotation_date = data.get("quotation_date") or now_iso[:10]
        valid_until = data.get("valid_until")
        currency = (data.get("currency") or customer["currency"] or "USD").upper()

        conn.execute(
            """
            INSERT INTO customer_quotations (
                id, quotation_number, customer_id, customer_code, customer_name,
                quotation_date, valid_until, currency, payment_terms, incoterm, destination_port,
                subtotal, discount_total, tax_total, grand_total, status, notes, created_by,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?)
            """,
            (
                quotation_id,
                quotation_number,
                customer_id,
                customer["code"],
                customer["name"],
                quotation_date,
                valid_until,
                currency,
                customer["payment_terms"] or "LC at sight",
                customer["incoterm_preference"] or "FOB",
                customer["destination_port"],
                round(subtotal_sum, 2),
                round(discount_sum, 2),
                round(tax_sum, 2),
                round(grand_total_sum, 2),
                data.get("notes"),
                performed_by,
                now_iso,
                now_iso,
            ),
        )

        for it in item_records:
            conn.execute(
                """
                INSERT INTO customer_quotation_items (
                    id, quotation_id, product_id, product_sku, product_name, uom,
                    quantity, unit_price, discount_pct, tax_rate_pct, subtotal,
                    discount_amount, tax_amount, line_total, sort_order, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    it["id"], it["quotation_id"], it["product_id"], it["product_sku"],
                    it["product_name"], it["uom"], it["quantity"], it["unit_price"],
                    it["discount_pct"], it["tax_rate_pct"], it["subtotal"],
                    it["discount_amount"], it["tax_amount"], it["line_total"],
                    it["sort_order"], it["created_at"],
                ),
            )
        conn.commit()

    record_erp_audit_log("customer_quotation", quotation_id, "create_quotation", {"quotation_number": quotation_number, "grand_total": grand_total_sum}, performed_by)
    return get_customer_quotation_by_id(quotation_id)


def get_customer_quotation_by_id(quotation_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        q = conn.execute("SELECT * FROM customer_quotations WHERE id = ?", (quotation_id,)).fetchone()
        if not q:
            raise HTTPException(status_code=404, detail=f"Quotation '{quotation_id}' not found.")

        c = conn.execute("SELECT * FROM customers WHERE id = ?", (q["customer_id"],)).fetchone()

        items = conn.execute("SELECT * FROM customer_quotation_items WHERE quotation_id = ? ORDER BY sort_order ASC", (quotation_id,)).fetchall()

    return {
        "id": q["id"],
        "quotation_number": q["quotation_number"],
        "quotation_version": 1,
        "customer_id": q["customer_id"],
        "customer_code": q["customer_code"],
        "customer_name": q["customer_name"],
        "billing_address": c["billing_address"] if c else None,
        "shipping_address": c["shipping_address"] if c else None,
        "contact_email": c["email"] if c else None,
        "tax_id": c["tax_id"] if c else None,
        "quotation_date": q["quotation_date"],
        "valid_until": q["valid_until"],
        "currency": q["currency"],
        "subtotal": float(q["subtotal"]),
        "discount_total": float(q["discount_total"]),
        "tax_total": float(q["tax_total"]),
        "grand_total": float(q["grand_total"]),
        "status": q["status"],
        "notes": q["notes"],
        "created_by": q["created_by"],
        "updated_by": q["created_by"],
        "created_at": q["created_at"],
        "updated_at": q["updated_at"],
        "items": [
            {
                "id": it["id"],
                "quotation_id": it["quotation_id"],
                "product_id": it["product_id"],
                "sku": it["product_sku"],
                "product_name": it["product_name"],
                "uom": it["uom"],
                "quantity": float(it["quantity"]),
                "unit_price": float(it["unit_price"]),
                "discount_pct": float(it["discount_pct"]),
                "tax_rate_pct": float(it["tax_rate_pct"]),
                "line_subtotal": float(it["subtotal"]),
                "line_discount": float(it["discount_amount"]),
                "line_tax": float(it["tax_amount"]),
                "line_total": float(it["line_total"]),
            }
            for it in items
        ],
    }


def list_customer_quotations(customer_id: str | None = None, status: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    clauses = []
    params: list[Any] = []
    if customer_id:
        clauses.append("customer_id = ?")
        params.append(customer_id)
    if status:
        clauses.append("status = ?")
        params.append(status.strip().lower())

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection() as conn:
        count_row = conn.execute(f"SELECT count(*) FROM customer_quotations {where}", params).fetchone()
        total = count_row[0] if count_row else 0

        rows = conn.execute(
            f"SELECT id FROM customer_quotations {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

    return {
        "total": total,
        "items": [get_customer_quotation_by_id(r["id"]) for r in rows],
    }


def send_customer_quotation(quotation_id: str, performed_by: str = "Local Operator") -> dict[str, Any]:
    quo = get_customer_quotation_by_id(quotation_id)
    if quo["status"] != "draft":
        raise HTTPException(status_code=400, detail=f"Cannot send quotation in '{quo['status']}' status (must be draft).")

    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute("UPDATE customer_quotations SET status = 'sent', updated_at = ? WHERE id = ?", (now_iso, quotation_id))
        conn.commit()

    record_erp_audit_log("customer_quotation", quotation_id, "send_quotation", {"status": "sent"}, performed_by)
    return get_customer_quotation_by_id(quotation_id)


def accept_customer_quotation(quotation_id: str, performed_by: str = "Local Operator") -> dict[str, Any]:
    quo = get_customer_quotation_by_id(quotation_id)
    if quo["status"] not in ("draft", "sent"):
        raise HTTPException(status_code=400, detail=f"Cannot accept quotation in '{quo['status']}' status.")

    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute("UPDATE customer_quotations SET status = 'accepted', updated_at = ? WHERE id = ?", (now_iso, quotation_id))
        conn.commit()

    record_erp_audit_log("customer_quotation", quotation_id, "accept_quotation", {"status": "accepted"}, performed_by)
    return get_customer_quotation_by_id(quotation_id)


def reject_customer_quotation(quotation_id: str, performed_by: str = "Local Operator") -> dict[str, Any]:
    quo = get_customer_quotation_by_id(quotation_id)
    if quo["status"] not in ("draft", "sent"):
        raise HTTPException(status_code=400, detail=f"Cannot reject quotation in '{quo['status']}' status.")

    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute("UPDATE customer_quotations SET status = 'rejected', updated_at = ? WHERE id = ?", (now_iso, quotation_id))
        conn.commit()

    record_erp_audit_log("customer_quotation", quotation_id, "reject_quotation", {"status": "rejected"}, performed_by)
    return get_customer_quotation_by_id(quotation_id)


# ==========================================
# 2. Sales Orders
# ==========================================

def create_sales_order(data: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    customer_id = data.get("customer_id")
    if not customer_id:
        raise HTTPException(status_code=400, detail="Customer ID is required.")

    items_data = data.get("items", [])
    if not items_data:
        raise HTTPException(status_code=400, detail="At least one sales order item is required.")

    shipment_id = data.get("shipment_id")

    with get_connection() as conn:
        customer = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
        if not customer:
            raise HTTPException(status_code=400, detail=f"Customer '{customer_id}' not found.")
        if customer["status"] != "active":
            raise HTTPException(status_code=400, detail=f"Customer '{customer['code']}' is not active.")

        if shipment_id:
            sh = conn.execute("SELECT id FROM shipments WHERE id = ?", (shipment_id,)).fetchone()
            if not sh:
                raise HTTPException(status_code=400, detail=f"Shipment '{shipment_id}' not found.")

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        date_str = now.strftime("%Y%m%d")

        count_row = conn.execute("SELECT count(*) FROM sales_orders WHERE order_number LIKE ?", (f"SO-{date_str}-%",)).fetchone()
        seq = (count_row[0] or 0) + 1
        order_number = f"SO-{date_str}-{seq:04d}"
        order_id = f"so-{uuid.uuid4().hex[:10]}"

        subtotal_sum = 0.0
        discount_sum = 0.0
        tax_sum = 0.0
        grand_total_sum = 0.0

        item_records = []
        for idx, item in enumerate(items_data):
            prod_id = item.get("product_id")
            qty = float(item.get("ordered_quantity", 0.0))
            price = float(item.get("unit_price", 0.0))
            disc_pct = float(item.get("discount_pct", 0.0))
            tax_pct = float(item.get("tax_rate_pct", 0.0))

            if not prod_id:
                raise HTTPException(status_code=400, detail="Product ID is required for each order line item.")
            if qty <= 0:
                raise HTTPException(status_code=400, detail=f"Line {idx+1}: Ordered quantity must be greater than zero.")
            if price < 0:
                raise HTTPException(status_code=400, detail=f"Line {idx+1}: Unit price cannot be negative.")
            if disc_pct < 0 or disc_pct > 100:
                raise HTTPException(status_code=400, detail=f"Line {idx+1}: Discount percentage must be between 0 and 100.")
            if tax_pct < 0:
                raise HTTPException(status_code=400, detail=f"Line {idx+1}: Tax rate percentage cannot be negative.")

            prod = conn.execute("SELECT sku, name, uom, is_active FROM products WHERE id = ?", (prod_id,)).fetchone()
            if not prod:
                raise HTTPException(status_code=400, detail=f"Line {idx+1}: Product '{prod_id}' not found.")
            if not prod["is_active"]:
                raise HTTPException(status_code=400, detail=f"Line {idx+1}: Product '{prod['sku']}' is inactive.")

            line_sub, line_disc, line_tax, line_tot = _calculate_line_amounts(qty, price, disc_pct, tax_pct)
            subtotal_sum += line_sub
            discount_sum += line_disc
            tax_sum += line_tax
            grand_total_sum += line_tot

            item_records.append({
                "id": f"soi-{uuid.uuid4().hex[:10]}",
                "sales_order_id": order_id,
                "product_id": prod_id,
                "product_sku": prod["sku"],
                "product_name": prod["name"],
                "uom": prod["uom"] or "PCS",
                "ordered_quantity": qty,
                "allocated_quantity": 0.0,
                "picked_quantity": 0.0,
                "dispatched_quantity": 0.0,
                "delivered_quantity": 0.0,
                "unit_price": price,
                "discount_pct": disc_pct,
                "tax_rate_pct": tax_pct,
                "subtotal": line_sub,
                "discount_amount": line_disc,
                "tax_amount": line_tax,
                "line_total": line_tot,
                "sort_order": idx,
                "created_at": now_iso,
                "updated_at": now_iso,
            })

        order_date = data.get("order_date") or now_iso[:10]
        req_del_date = data.get("requested_delivery_date")
        currency = (data.get("currency") or customer["currency"] or "USD").upper()
        quotation_id = data.get("quotation_id")

        conn.execute(
            """
            INSERT INTO sales_orders (
                id, order_number, quotation_id, customer_id, customer_code, customer_name,
                billing_address, shipping_address, contact_email, contact_phone, tax_id,
                order_date, requested_delivery_date, currency, payment_terms, incoterm,
                destination_port, subtotal, discount_total, tax_total, grand_total,
                status, shipment_id, notes, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                order_number,
                quotation_id,
                customer_id,
                customer["code"],
                customer["name"],
                customer["billing_address"],
                customer["shipping_address"],
                customer["email"],
                customer["phone"],
                customer["tax_id"],
                order_date,
                req_del_date,
                currency,
                data.get("payment_terms") or customer["payment_terms"] or "Net 30",
                customer["incoterm_preference"] or "FOB",
                customer["destination_port"],
                round(subtotal_sum, 2),
                round(discount_sum, 2),
                round(tax_sum, 2),
                round(grand_total_sum, 2),
                shipment_id,
                data.get("notes"),
                performed_by,
                now_iso,
                now_iso,
            ),
        )

        for it in item_records:
            conn.execute(
                """
                INSERT INTO sales_order_items (
                    id, sales_order_id, product_id, product_sku, product_name, uom,
                    ordered_quantity, allocated_quantity, picked_quantity, dispatched_quantity,
                    delivered_quantity, unit_price, discount_pct, tax_rate_pct, subtotal,
                    discount_amount, tax_amount, line_total, sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0.0, 0.0, 0.0, 0.0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    it["id"], it["sales_order_id"], it["product_id"], it["product_sku"],
                    it["product_name"], it["uom"], it["ordered_quantity"], it["unit_price"],
                    it["discount_pct"], it["tax_rate_pct"], it["subtotal"],
                    it["discount_amount"], it["tax_amount"], it["line_total"],
                    it["sort_order"], it["created_at"], it["updated_at"],
                ),
            )
        conn.commit()

    record_erp_audit_log("sales_order", order_id, "create_order", {"order_number": order_number, "grand_total": grand_total_sum}, performed_by)
    return get_sales_order_by_id(order_id)


def get_sales_order_by_id(order_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        o = conn.execute("SELECT * FROM sales_orders WHERE id = ?", (order_id,)).fetchone()
        if not o:
            raise HTTPException(status_code=404, detail=f"Sales order '{order_id}' not found.")

        items = conn.execute("SELECT * FROM sales_order_items WHERE sales_order_id = ? ORDER BY sort_order ASC", (order_id,)).fetchall()

    return {
        "id": o["id"],
        "order_number": o["order_number"],
        "quotation_id": o["quotation_id"],
        "customer_id": o["customer_id"],
        "customer_code": o["customer_code"],
        "customer_name": o["customer_name"],
        "billing_address": o["billing_address"],
        "shipping_address": o["shipping_address"],
        "contact_email": o["contact_email"],
        "tax_id": o["tax_id"],
        "order_date": o["order_date"],
        "requested_delivery_date": o["requested_delivery_date"],
        "currency": o["currency"],
        "payment_terms": o["payment_terms"],
        "delivery_address": o["shipping_address"],
        "status": o["status"],
        "subtotal": float(o["subtotal"]),
        "discount_total": float(o["discount_total"]),
        "tax_total": float(o["tax_total"]),
        "grand_total": float(o["grand_total"]),
        "notes": o["notes"],
        "shipment_id": o["shipment_id"],
        "created_by": o["created_by"],
        "updated_by": o["confirmed_by"] or o["created_by"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "items": [
            {
                "id": it["id"],
                "sales_order_id": it["sales_order_id"],
                "product_id": it["product_id"],
                "sku": it["product_sku"],
                "product_name": it["product_name"],
                "uom": it["uom"],
                "ordered_quantity": float(it["ordered_quantity"]),
                "allocated_quantity": float(it["allocated_quantity"]),
                "picked_quantity": float(it["picked_quantity"]),
                "packed_quantity": float(it["picked_quantity"]),  # mapped to packed state
                "dispatched_quantity": float(it["dispatched_quantity"]),
                "delivered_quantity": float(it["delivered_quantity"]),
                "unit_price": float(it["unit_price"]),
                "discount_pct": float(it["discount_pct"]),
                "tax_rate_pct": float(it["tax_rate_pct"]),
                "line_subtotal": float(it["subtotal"]),
                "line_discount": float(it["discount_amount"]),
                "line_tax": float(it["tax_amount"]),
                "line_total": float(it["line_total"]),
            }
            for it in items
        ],
    }


def list_sales_orders(customer_id: str | None = None, status: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    clauses = []
    params: list[Any] = []
    if customer_id:
        clauses.append("customer_id = ?")
        params.append(customer_id)
    if status:
        clauses.append("status = ?")
        params.append(status.strip().lower())

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection() as conn:
        count_row = conn.execute(f"SELECT count(*) FROM sales_orders {where}", params).fetchone()
        total = count_row[0] if count_row else 0

        rows = conn.execute(
            f"SELECT id FROM sales_orders {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

    return {
        "total": total,
        "items": [get_sales_order_by_id(r["id"]) for r in rows],
    }


def convert_quotation_to_sales_order(quotation_id: str, data: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    quo = get_customer_quotation_by_id(quotation_id)
    if quo["status"] not in ("accepted", "sent", "draft"):
        raise HTTPException(status_code=400, detail=f"Quotation in '{quo['status']}' status cannot be converted to a sales order.")

    order_payload = {
        "customer_id": quo["customer_id"],
        "quotation_id": quotation_id,
        "order_date": datetime.now(timezone.utc).isoformat()[:10],
        "requested_delivery_date": data.get("requested_delivery_date") or quo.get("valid_until"),
        "currency": quo["currency"],
        "payment_terms": data.get("payment_terms") or "Net 30",
        "notes": data.get("notes") or f"Converted from quotation {quo['quotation_number']}",
        "items": [
            {
                "product_id": it["product_id"],
                "ordered_quantity": it["quantity"],
                "unit_price": it["unit_price"],
                "discount_pct": it["discount_pct"],
                "tax_rate_pct": it["tax_rate_pct"],
            }
            for it in quo["items"]
        ],
    }

    order = create_sales_order(order_payload, performed_by=performed_by)

    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute("UPDATE customer_quotations SET status = 'converted', converted_order_id = ?, updated_at = ? WHERE id = ?", (order["id"], now_iso, quotation_id))
        conn.commit()

    record_erp_audit_log("customer_quotation", quotation_id, "convert_quotation", {"converted_order_id": order["id"]}, performed_by)
    return order


def confirm_sales_order(order_id: str, performed_by: str = "Local Operator") -> dict[str, Any]:
    order = get_sales_order_by_id(order_id)
    if order["status"] != "draft":
        raise HTTPException(status_code=400, detail=f"Cannot confirm sales order in '{order['status']}' status (must be draft).")

    with get_connection() as conn:
        cust = conn.execute("SELECT status FROM customers WHERE id = ?", (order["customer_id"],)).fetchone()
        if not cust or cust["status"] != "active":
            raise HTTPException(status_code=400, detail="Cannot confirm order: Customer is inactive.")

        for item in order["items"]:
            p = conn.execute("SELECT is_active, sku FROM products WHERE id = ?", (item["product_id"],)).fetchone()
            if not p or not p["is_active"]:
                raise HTTPException(status_code=400, detail=f"Cannot confirm order: Product '{p['sku'] if p else item['product_id']}' is inactive.")

        now_iso = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE sales_orders SET status = 'confirmed', confirmed_by = ?, confirmed_at = ?, updated_at = ? WHERE id = ?",
            (performed_by, now_iso, now_iso, order_id),
        )
        conn.commit()

    record_erp_audit_log("sales_order", order_id, "confirm_order", {"status": "confirmed"}, performed_by)
    return get_sales_order_by_id(order_id)


def allocate_sales_order(order_id: str, data: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    """
    Authoritative stock reservation via Phase 3 warehouse ATP engine.
    Ensures that active reservations prevent concurrent orders from reserving the same stock.
    """
    order = get_sales_order_by_id(order_id)
    if order["status"] not in ("confirmed", "allocated", "picking"):
        raise HTTPException(status_code=400, detail=f"Cannot allocate stock for sales order in '{order['status']}' status.")

    warehouse_id = data.get("warehouse_id")
    if not warehouse_id:
        raise HTTPException(status_code=400, detail="Warehouse ID is required for allocation.")

    with get_connection() as conn:
        wh = conn.execute("SELECT id, code, is_active FROM warehouses WHERE id = ?", (warehouse_id,)).fetchone()
        if not wh:
            raise HTTPException(status_code=400, detail=f"Warehouse '{warehouse_id}' not found.")
        if not wh["is_active"]:
            raise HTTPException(status_code=400, detail=f"Warehouse '{wh['code']}' is inactive.")

    # Allocate line items
    all_allocated = True
    any_allocated = False

    for item in order["items"]:
        needed = item["ordered_quantity"] - item["allocated_quantity"]
        if needed <= 0:
            continue

        atp = get_product_atp(item["product_id"], warehouse_id)
        if atp < needed:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient available stock for reservation. Available to Promise: {atp}, Requested: {needed} for SKU '{item['sku']}'.",
            )

        res_data = {
            "product_id": item["product_id"],
            "warehouse_id": warehouse_id,
            "quantity": needed,
            "reference_type": "sales_order",
            "reference_id": order_id,
            "notes": f"Allocation for {order['order_number']}",
        }
        res = create_stock_reservation(res_data, performed_by=performed_by)

        now_iso = datetime.now(timezone.utc).isoformat()
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE sales_order_items
                SET allocated_quantity = allocated_quantity + ?, reservation_id = ?, warehouse_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (needed, res["id"], warehouse_id, now_iso, item["id"]),
            )
            conn.commit()
        any_allocated = True

    # Re-fetch order items to determine if fully or partially allocated
    fresh_order = get_sales_order_by_id(order_id)
    is_complete = all(it["allocated_quantity"] >= it["ordered_quantity"] for it in fresh_order["items"])

    new_status = "allocated" if is_complete else order["status"]
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute("UPDATE sales_orders SET status = ?, updated_at = ? WHERE id = ?", (new_status, now_iso, order_id))
        conn.commit()

    record_erp_audit_log("sales_order", order_id, "allocate_order", {"status": new_status, "warehouse_id": warehouse_id}, performed_by)
    return get_sales_order_by_id(order_id)


def cancel_sales_order(order_id: str, performed_by: str = "Local Operator", reason: str | None = None) -> dict[str, Any]:
    order = get_sales_order_by_id(order_id)
    if order["status"] in ("dispatched", "delivered", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel order in '{order['status']}' status.")

    any_dispatched = any(it["dispatched_quantity"] > 0 for it in order["items"])
    if any_dispatched:
        raise HTTPException(status_code=400, detail="Cannot cancel sales order with already dispatched items. Use sales return.")

    # Release all active stock reservations associated with this sales order
    with get_connection() as conn:
        res_rows = conn.execute(
            "SELECT id FROM stock_reservations WHERE reference_type = 'sales_order' AND reference_id = ? AND status = 'active'",
            (order_id,),
        ).fetchall()

    for r in res_rows:
        release_stock_reservation(r["id"], performed_by=performed_by)

    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE sales_orders
            SET status = 'cancelled', cancelled_by = ?, cancelled_at = ?, cancellation_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (performed_by, now_iso, reason or "Cancelled by user", now_iso, order_id),
        )
        conn.execute("UPDATE sales_order_items SET allocated_quantity = 0.0, updated_at = ? WHERE sales_order_id = ?", (now_iso, order_id))
        conn.commit()

    record_erp_audit_log("sales_order", order_id, "cancel_order", {"reason": reason}, performed_by)
    return get_sales_order_by_id(order_id)


# ==========================================
# 3. Picking & Packing Workflows
# ==========================================

def create_sales_pick_list(data: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    order_id = data.get("sales_order_id")
    warehouse_id = data.get("warehouse_id")

    if not order_id or not warehouse_id:
        raise HTTPException(status_code=400, detail="Sales order ID and Warehouse ID are required.")

    order = get_sales_order_by_id(order_id)
    if order["status"] not in ("confirmed", "allocated", "picking"):
        raise HTTPException(status_code=400, detail=f"Cannot create pick list for sales order in '{order['status']}' status.")

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    date_str = now.strftime("%Y%m%d")

    with get_connection() as conn:
        count_row = conn.execute("SELECT count(*) FROM sales_pick_lists WHERE pick_list_number LIKE ?", (f"PICK-{date_str}-%",)).fetchone()
        seq = (count_row[0] or 0) + 1
        pick_number = f"PICK-{date_str}-{seq:04d}"
        pick_id = f"pkl-{uuid.uuid4().hex[:10]}"

        conn.execute(
            """
            INSERT INTO sales_pick_lists (
                id, pick_list_number, sales_order_id, warehouse_id, status, assigned_to,
                notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            """,
            (
                pick_id,
                pick_number,
                order_id,
                warehouse_id,
                data.get("assigned_picker"),
                data.get("notes"),
                now_iso,
                now_iso,
            ),
        )

        for item in order["items"]:
            # Only pick remaining unpicked
            remaining_to_pick = max(0.0, item["allocated_quantity"] - item["picked_quantity"])
            if remaining_to_pick <= 0:
                continue

            item_id = f"pki-{uuid.uuid4().hex[:10]}"
            conn.execute(
                """
                INSERT INTO sales_pick_items (
                    id, pick_list_id, sales_order_item_id, product_id, sku, product_name,
                    warehouse_id, location_id, required_quantity, picked_quantity, short_quantity,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, 0.0, 0.0, ?, ?)
                """,
                (
                    item_id,
                    pick_id,
                    item["id"],
                    item["product_id"],
                    item["sku"],
                    item["product_name"],
                    warehouse_id,
                    remaining_to_pick,
                    now_iso,
                    now_iso,
                ),
            )

        # Update order status to 'picking'
        conn.execute("UPDATE sales_orders SET status = 'picking', updated_at = ? WHERE id = ?", (now_iso, order_id))
        conn.commit()

    record_erp_audit_log("sales_pick_list", pick_id, "create_pick_list", {"pick_list_number": pick_number, "order_id": order_id}, performed_by)
    return get_sales_pick_list_by_id(pick_id)


def get_sales_pick_list_by_id(pick_list_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        p = conn.execute(
            """
            SELECT p.*, o.order_number, w.code as warehouse_code
            FROM sales_pick_lists p
            JOIN sales_orders o ON p.sales_order_id = o.id
            JOIN warehouses w ON p.warehouse_id = w.id
            WHERE p.id = ?
            """,
            (pick_list_id,),
        ).fetchone()
        if not p:
            raise HTTPException(status_code=404, detail=f"Pick list '{pick_list_id}' not found.")

        items = conn.execute("SELECT * FROM sales_pick_items WHERE pick_list_id = ?", (pick_list_id,)).fetchall()

    return {
        "id": p["id"],
        "pick_list_number": p["pick_list_number"],
        "sales_order_id": p["sales_order_id"],
        "order_number": p["order_number"],
        "warehouse_id": p["warehouse_id"],
        "warehouse_code": p["warehouse_code"],
        "status": p["status"],
        "assigned_picker": p["assigned_to"],
        "started_at": p["created_at"],
        "completed_at": p["packed_at"],
        "notes": p["notes"],
        "created_by": p["assigned_to"] or "Local Operator",
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "items": [
            {
                "id": it["id"],
                "pick_list_id": it["pick_list_id"],
                "order_item_id": it["sales_order_item_id"],
                "product_id": it["product_id"],
                "sku": it["sku"],
                "product_name": it["product_name"],
                "location_id": it["location_id"],
                "location_code": None,
                "reserved_quantity": float(it["required_quantity"]),
                "picked_quantity": float(it["picked_quantity"]),
                "short_picked_quantity": float(it["short_quantity"]),
                "short_pick_reason": it["discrepancy_reason"],
                "is_short_picked": float(it["short_quantity"]) > 0,
                "picked_at": it["picked_at"],
            }
            for it in items
        ],
    }


def list_sales_pick_lists(sales_order_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if sales_order_id:
        clauses.append("sales_order_id = ?")
        params.append(sales_order_id)
    if status:
        clauses.append("status = ?")
        params.append(status.strip().lower())

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection() as conn:
        rows = conn.execute(f"SELECT id FROM sales_pick_lists {where} ORDER BY created_at DESC", params).fetchall()

    return [get_sales_pick_list_by_id(r["id"]) for r in rows]


def complete_sales_pick_list(pick_list_id: str, data: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    pkl = get_sales_pick_list_by_id(pick_list_id)
    if pkl["status"] not in ("pending", "in_progress"):
        raise HTTPException(status_code=400, detail=f"Cannot complete pick list in '{pkl['status']}' status.")

    items_input = {it.get("pick_item_id"): it for it in data.get("items", [])}
    now_iso = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        for it in pkl["items"]:
            inp = items_input.get(it["id"], {})
            picked_qty = float(inp.get("picked_quantity", it["reserved_quantity"]))
            short_qty = float(inp.get("short_picked_quantity", 0.0))
            reason = inp.get("short_pick_reason")

            if picked_qty < 0:
                raise HTTPException(status_code=400, detail=f"Picked quantity cannot be negative for SKU '{it['sku']}'.")
            if picked_qty > it["reserved_quantity"]:
                raise HTTPException(status_code=400, detail=f"Cannot pick {picked_qty} > reserved quantity {it['reserved_quantity']}.")

            conn.execute(
                """
                UPDATE sales_pick_items
                SET picked_quantity = ?, short_quantity = ?, discrepancy_reason = ?, picked_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (picked_qty, short_qty, reason, now_iso, now_iso, it["id"]),
            )

            # Update sales_order_items picked_quantity
            conn.execute(
                """
                UPDATE sales_order_items
                SET picked_quantity = picked_quantity + ?, updated_at = ?
                WHERE id = ?
                """,
                (picked_qty, now_iso, it["order_item_id"]),
            )

        conn.execute(
            "UPDATE sales_pick_lists SET status = 'completed', picked_by = ?, updated_at = ? WHERE id = ?",
            (performed_by, now_iso, pick_list_id),
        )
        conn.commit()

    record_erp_audit_log("sales_pick_list", pick_list_id, "complete_pick_list", {"status": "completed"}, performed_by)
    return get_sales_pick_list_by_id(pick_list_id)


def pack_sales_order(order_id: str, data: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    order = get_sales_order_by_id(order_id)
    if order["status"] not in ("picking", "allocated"):
        raise HTTPException(status_code=400, detail=f"Cannot pack sales order in '{order['status']}' status.")

    any_picked = any(it["picked_quantity"] > 0 for it in order["items"])
    if not any_picked:
        raise HTTPException(status_code=400, detail="Cannot pack sales order: No picked items found.")

    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute("UPDATE sales_orders SET status = 'packed', updated_at = ? WHERE id = ?", (now_iso, order_id))
        conn.commit()

    record_erp_audit_log("sales_order", order_id, "pack_order", {"status": "packed", "notes": data.get("notes")}, performed_by)
    return get_sales_order_by_id(order_id)


# ==========================================
# 4. Commercial Dispatches & Delivery Tracking
# ==========================================

def calculate_dispatch_payload_hash(data: dict[str, Any]) -> str:
    """
    Deterministic SHA-256 hash of the canonical dispatch request payload.
    Binds idempotency key strictly to the order, warehouse, and sorted line items.
    """
    order_id = str(data.get("sales_order_id") or "").strip()
    warehouse_id = str(data.get("warehouse_id") or "").strip()
    raw_items = data.get("items", [])
    normalized_items = []
    for it in raw_items:
        normalized_items.append({
            "order_item_id": str(it.get("order_item_id") or "").strip(),
            "quantity_dispatched": round(float(it.get("quantity_dispatched", 0.0)), 4),
        })
    normalized_items.sort(key=lambda x: x["order_item_id"])
    canonical = {
        "sales_order_id": order_id,
        "warehouse_id": warehouse_id,
        "items": normalized_items,
    }
    canonical_json = json.dumps(canonical, sort_keys=True)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def create_sales_dispatch(data: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    """
    Commercial Dispatch:
    - Atomically consumes corresponding active reservations
    - Posts SALES_DISPATCH negative movement exactly once
    - Updates warehouse available on-hand balances
    - Supports partial dispatches without duplicating fulfilled quantities
    - Non-destructively links to shipments(id) when provided
    - Binds idempotency key strictly to payload hash (ARC-01)
    - Concurrency conflict handling with atomic rollback (ARC-02)
    """
    idempotency_key = data.get("idempotency_key")
    payload_hash = calculate_dispatch_payload_hash(data) if idempotency_key else None

    if idempotency_key:
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT id, payload_hash, sales_order_id, warehouse_id FROM sales_dispatches WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                if existing["payload_hash"]:
                    if existing["payload_hash"] != payload_hash:
                        raise HTTPException(
                            status_code=409,
                            detail="Idempotency key has already been used with a different request payload.",
                        )
                else:
                    # Legacy record with NULL payload_hash:
                    # Verify order and warehouse match
                    if existing["sales_order_id"] != data.get("sales_order_id") or existing["warehouse_id"] != data.get("warehouse_id"):
                        raise HTTPException(
                            status_code=409,
                            detail="Idempotency key has already been used for a different sales order or warehouse.",
                        )
                    # Verify line items against actual database dispatch items
                    disp_items = conn.execute(
                        "SELECT sales_order_item_id, dispatched_quantity FROM sales_dispatch_items WHERE dispatch_id = ?",
                        (existing["id"],),
                    ).fetchall()
                    if not disp_items:
                        # Cannot safely verify original payload
                        raise HTTPException(
                            status_code=409,
                            detail="Idempotency key refers to an unverifiable historical dispatch record without line item data.",
                        )
                    reconstructed_hash = calculate_dispatch_payload_hash({
                        "sales_order_id": existing["sales_order_id"],
                        "warehouse_id": existing["warehouse_id"],
                        "items": [
                            {"order_item_id": r["sales_order_item_id"], "quantity_dispatched": r["dispatched_quantity"]}
                            for r in disp_items
                        ],
                    })
                    if payload_hash != reconstructed_hash:
                        raise HTTPException(
                            status_code=409,
                            detail="Idempotency key has already been used with a different request payload.",
                        )
                    # Payload safely and reliably verified against database; backfill hash for future fast lookup
                    conn.execute("UPDATE sales_dispatches SET payload_hash = ? WHERE id = ?", (payload_hash, existing["id"]))
                    conn.commit()
                return get_sales_dispatch_by_id(existing["id"])

    order_id = data.get("sales_order_id")
    warehouse_id = data.get("warehouse_id")
    if not order_id or not warehouse_id:
        raise HTTPException(status_code=400, detail="Sales order ID and Warehouse ID are required.")

    order = get_sales_order_by_id(order_id)
    if order["status"] not in ("packed", "picking", "allocated", "dispatched"):
        raise HTTPException(status_code=400, detail=f"Cannot dispatch sales order in '{order['status']}' status.")

    items_data = data.get("items", [])
    if not items_data:
        raise HTTPException(status_code=400, detail="At least one dispatch item is required.")

    shipment_id = data.get("shipment_id") or order.get("shipment_id")
    with get_connection() as conn:
        if shipment_id:
            sh = conn.execute("SELECT id FROM shipments WHERE id = ?", (shipment_id,)).fetchone()
            if not sh:
                raise HTTPException(status_code=400, detail=f"Shipment '{shipment_id}' not found.")

        wh = conn.execute("SELECT id, code, is_active FROM warehouses WHERE id = ?", (warehouse_id,)).fetchone()
        if not wh or not wh["is_active"]:
            raise HTTPException(status_code=400, detail="Active warehouse required for dispatch.")

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    date_str = now.strftime("%Y%m%d")

    try:
        with get_connection() as conn:
            count_row = conn.execute("SELECT count(*) FROM sales_dispatches WHERE dispatch_number LIKE ?", (f"DISP-{date_str}-%",)).fetchone()
            seq = (count_row[0] or 0) + 1
            dispatch_num = f"DISP-{date_str}-{seq:04d}"
            dispatch_id = f"dsp-{uuid.uuid4().hex[:10]}"

            conn.execute(
                """
                INSERT INTO sales_dispatches (
                    id, dispatch_number, sales_order_id, warehouse_id, shipment_id, idempotency_key,
                    payload_hash, dispatch_date, carrier, tracking_reference, vehicle_no, packages_count,
                    status, dispatched_by, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'dispatched', ?, ?, ?, ?)
                """,
                (
                    dispatch_id,
                    dispatch_num,
                    order_id,
                    warehouse_id,
                    shipment_id,
                    idempotency_key,
                    payload_hash,
                    data.get("dispatch_date") or now_iso[:10],
                    data.get("carrier_name"),
                    data.get("tracking_number"),
                    data.get("vehicle_number"),
                    data.get("package_count") or 1,
                    performed_by,
                    data.get("notes"),
                    now_iso,
                    now_iso,
                ),
            )

            dispatch_items = []
            for it in items_data:
                order_item_id = it.get("order_item_id")
                qty_dispatch = float(it.get("quantity_dispatched", 0.0))

                if qty_dispatch <= 0:
                    raise HTTPException(status_code=400, detail="Quantity dispatched must be greater than zero.")

                # Validate against order line
                line = conn.execute("SELECT * FROM sales_order_items WHERE id = ? AND sales_order_id = ?", (order_item_id, order_id)).fetchone()
                if not line:
                    raise HTTPException(status_code=400, detail=f"Order line '{order_item_id}' not found.")

                remaining = float(line["ordered_quantity"]) - float(line["dispatched_quantity"])
                if qty_dispatch > remaining:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot dispatch {qty_dispatch} > remaining ordered quantity {remaining} for SKU '{line['product_sku']}'.",
                    )

                # Check physical on-hand available balance
                bal = conn.execute(
                    "SELECT on_hand_qty FROM inventory_balances WHERE product_id = ? AND stock_type = 'available'",
                    (line["product_id"],),
                ).fetchone()
                cur_on_hand = float(bal["on_hand_qty"]) if bal else 0.0
                if cur_on_hand < qty_dispatch:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Insufficient physical available stock ({cur_on_hand}) to dispatch {qty_dispatch} of SKU '{line['product_sku']}'.",
                    )

                # Record inventory movement (Deduction from available stock)
                mov_id = f"mov-{uuid.uuid4().hex[:10]}"
                mov_num = f"MOV-{uuid.uuid4().hex[:8].upper()}"
                mov_key = f"disp-{dispatch_id}-{line['product_id']}"

                conn.execute(
                    """
                    INSERT INTO inventory_movements (
                        id, movement_number, idempotency_key, movement_type, reference_doc_type,
                        reference_doc_id, product_id, sku, quantity, stock_type, warehouse_id,
                        location_id, uom, performed_by, notes, created_at
                    ) VALUES (?, ?, ?, 'SALES_DISPATCH', 'sales_dispatch', ?, ?, ?, ?, 'available', ?, NULL, ?, ?, ?, ?)
                    """,
                    (
                        mov_id,
                        mov_num,
                        mov_key,
                        dispatch_id,
                        line["product_id"],
                        line["product_sku"],
                        -qty_dispatch,
                        warehouse_id,
                        line["uom"] or "PCS",
                        performed_by,
                        f"Sales dispatch {dispatch_num} for order {order['order_number']}",
                        now_iso,
                    ),
                )

                # Deduct balance
                conn.execute(
                    "UPDATE inventory_balances SET on_hand_qty = ?, updated_at = ? WHERE product_id = ? AND stock_type = 'available'",
                    (cur_on_hand - qty_dispatch, now_iso, line["product_id"]),
                )

                # Consume active reservation for this order and product
                res_row = conn.execute(
                    """
                    SELECT id, quantity FROM stock_reservations
                    WHERE reference_type = 'sales_order' AND reference_id = ? AND product_id = ? AND status = 'active'
                    ORDER BY created_at ASC LIMIT 1
                    """,
                    (order_id, line["product_id"]),
                ).fetchone()

                if res_row:
                    res_id = res_row["id"]
                    res_qty = float(res_row["quantity"])
                    if res_qty <= qty_dispatch:
                        conn.execute(
                            "UPDATE stock_reservations SET status = 'consumed', consumed_by = ?, updated_at = ? WHERE id = ?",
                            (performed_by, now_iso, res_id),
                        )
                    else:
                        # Partial consumption: decrease remaining active reservation
                        conn.execute(
                            "UPDATE stock_reservations SET quantity = ?, updated_at = ? WHERE id = ?",
                            (res_qty - qty_dispatch, now_iso, res_id),
                        )

                # Update order line dispatched quantity
                conn.execute(
                    "UPDATE sales_order_items SET dispatched_quantity = dispatched_quantity + ?, updated_at = ? WHERE id = ?",
                    (qty_dispatch, now_iso, order_item_id),
                )

                disp_item_id = f"dsi-{uuid.uuid4().hex[:10]}"
                conn.execute(
                    """
                    INSERT INTO sales_dispatch_items (
                        id, dispatch_id, sales_order_item_id, product_id, sku, product_name,
                        dispatched_quantity, delivered_quantity, discrepancy_quantity, uom, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0.0, 0.0, ?, ?)
                    """,
                    (
                        disp_item_id,
                        dispatch_id,
                        order_item_id,
                        line["product_id"],
                        line["product_sku"],
                        line["product_name"],
                        qty_dispatch,
                        line["uom"] or "PCS",
                        now_iso,
                    ),
                )

            # Check if all items in order are fully dispatched
            fresh_items = conn.execute("SELECT ordered_quantity, dispatched_quantity FROM sales_order_items WHERE sales_order_id = ?", (order_id,)).fetchall()
            all_dispatched = all(float(it["dispatched_quantity"]) >= float(it["ordered_quantity"]) for it in fresh_items)
            if all_dispatched:
                conn.execute("UPDATE sales_orders SET status = 'dispatched', updated_at = ? WHERE id = ?", (now_iso, order_id))

            conn.commit()
    except sqlite3.IntegrityError as e:
        err_msg = str(e)
        if idempotency_key and ("sales_dispatches.idempotency_key" in err_msg or "UNIQUE constraint failed" in err_msg):
            with get_connection() as conn:
                winner = conn.execute(
                    "SELECT id, payload_hash, sales_order_id, warehouse_id FROM sales_dispatches WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if winner:
                    if winner["payload_hash"]:
                        if winner["payload_hash"] != payload_hash:
                            raise HTTPException(
                                status_code=409,
                                detail="Idempotency key has already been used with a different request payload.",
                            )
                    else:
                        disp_items = conn.execute(
                            "SELECT sales_order_item_id, dispatched_quantity FROM sales_dispatch_items WHERE dispatch_id = ?",
                            (winner["id"],),
                        ).fetchall()
                        if not disp_items:
                            raise HTTPException(
                                status_code=409,
                                detail="Idempotency key refers to an unverifiable historical dispatch record.",
                            )
                        reconstructed_hash = calculate_dispatch_payload_hash({
                            "sales_order_id": winner["sales_order_id"],
                            "warehouse_id": winner["warehouse_id"],
                            "items": [
                                {"order_item_id": r["sales_order_item_id"], "quantity_dispatched": r["dispatched_quantity"]}
                                for r in disp_items
                            ],
                        })
                        if payload_hash != reconstructed_hash:
                            raise HTTPException(
                                status_code=409,
                                detail="Idempotency key has already been used with a different request payload.",
                            )
                    return get_sales_dispatch_by_id(winner["id"])
        raise HTTPException(status_code=400, detail=f"Database constraint violation: {err_msg}")

    record_erp_audit_log("sales_dispatch", dispatch_id, "create_dispatch", {"dispatch_number": dispatch_num, "order_id": order_id}, performed_by)
    return get_sales_dispatch_by_id(dispatch_id)


def get_sales_dispatch_by_id(dispatch_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        d = conn.execute(
            """
            SELECT d.*, o.order_number, w.code as warehouse_code
            FROM sales_dispatches d
            JOIN sales_orders o ON d.sales_order_id = o.id
            JOIN warehouses w ON d.warehouse_id = w.id
            WHERE d.id = ?
            """,
            (dispatch_id,),
        ).fetchone()
        if not d:
            raise HTTPException(status_code=404, detail=f"Sales dispatch '{dispatch_id}' not found.")

        items = conn.execute("SELECT * FROM sales_dispatch_items WHERE dispatch_id = ?", (dispatch_id,)).fetchall()

    return {
        "id": d["id"],
        "dispatch_number": d["dispatch_number"],
        "idempotency_key": d["idempotency_key"],
        "payload_hash": dict(d).get("payload_hash"),
        "sales_order_id": d["sales_order_id"],
        "order_number": d["order_number"],
        "warehouse_id": d["warehouse_id"],
        "warehouse_code": d["warehouse_code"],
        "carrier_name": d["carrier"],
        "tracking_number": d["tracking_reference"],
        "vehicle_number": d["vehicle_no"],
        "package_count": d["packages_count"],
        "total_weight_kg": None,
        "dispatch_date": d["dispatch_date"],
        "status": d["status"],
        "dispatched_by": d["dispatched_by"],
        "delivery_date": d["delivered_at"],
        "delivered_by": d["delivered_by"],
        "shipment_id": d["shipment_id"],
        "notes": d["notes"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "items": [
            {
                "id": it["id"],
                "dispatch_id": it["dispatch_id"],
                "order_item_id": it["sales_order_item_id"],
                "product_id": it["product_id"],
                "sku": it["sku"],
                "quantity_dispatched": float(it["dispatched_quantity"]),
                "quantity_delivered": float(it["delivered_quantity"]),
                "quantity_damaged": 0.0,
                "quantity_rejected": float(it["discrepancy_quantity"]),
                "discrepancy_notes": it["notes"],
            }
            for it in items
        ],
    }


def list_sales_dispatches(sales_order_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if sales_order_id:
        clauses.append("sales_order_id = ?")
        params.append(sales_order_id)
    if status:
        clauses.append("status = ?")
        params.append(status.strip().lower())

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection() as conn:
        rows = conn.execute(f"SELECT id FROM sales_dispatches {where} ORDER BY created_at DESC", params).fetchall()

    return [get_sales_dispatch_by_id(r["id"]) for r in rows]


def deliver_sales_dispatch(dispatch_id: str, data: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    dsp = get_sales_dispatch_by_id(dispatch_id)
    if dsp["status"] not in ("dispatched", "in_transit"):
        raise HTTPException(status_code=400, detail=f"Cannot deliver dispatch in '{dsp['status']}' status.")

    now_iso = datetime.now(timezone.utc).isoformat()
    del_date = data.get("delivery_date") or now_iso[:10]
    delivered_by = data.get("delivered_by") or performed_by
    del_notes = data.get("notes")

    items_input = {it.get("dispatch_item_id"): it for it in data.get("items", [])}

    with get_connection() as conn:
        for it in dsp["items"]:
            inp = items_input.get(it["id"], {})
            qty_del = float(inp.get("quantity_delivered", it["quantity_dispatched"]))
            qty_rej = float(inp.get("quantity_rejected", 0.0))
            disc_notes = inp.get("discrepancy_notes")

            conn.execute(
                """
                UPDATE sales_dispatch_items
                SET delivered_quantity = ?, discrepancy_quantity = ?, notes = ?
                WHERE id = ?
                """,
                (qty_del, qty_rej, disc_notes, it["id"]),
            )

            # Update sales_order_items delivered_quantity
            conn.execute(
                """
                UPDATE sales_order_items
                SET delivered_quantity = delivered_quantity + ?, updated_at = ?
                WHERE id = ?
                """,
                (qty_del, now_iso, it["order_item_id"]),
            )

        conn.execute(
            """
            UPDATE sales_dispatches
            SET status = 'delivered', delivered_at = ?, delivered_by = ?, delivery_notes = ?, updated_at = ?
            WHERE id = ?
            """,
            (del_date, delivered_by, del_notes, now_iso, dispatch_id),
        )

        # Check if all items in the sales order are delivered
        order_id = dsp["sales_order_id"]
        fresh_lines = conn.execute("SELECT ordered_quantity, delivered_quantity FROM sales_order_items WHERE sales_order_id = ?", (order_id,)).fetchall()
        all_delivered = all(float(l["delivered_quantity"]) >= float(l["ordered_quantity"]) for l in fresh_lines)
        if all_delivered:
            conn.execute("UPDATE sales_orders SET status = 'delivered', updated_at = ? WHERE id = ?", (now_iso, order_id))

        conn.commit()

    record_erp_audit_log("sales_dispatch", dispatch_id, "deliver_dispatch", {"status": "delivered", "delivered_at": del_date}, performed_by)
    return get_sales_dispatch_by_id(dispatch_id)


# ==========================================
# 5. Sales Returns Foundation
# ==========================================

def create_sales_return(data: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    order_id = data.get("sales_order_id")
    reason = data.get("reason", "").strip()
    if not order_id or not reason:
        raise HTTPException(status_code=400, detail="Sales order ID and return reason are required.")

    order = get_sales_order_by_id(order_id)
    dispatch_id = data.get("dispatch_id")

    items_data = data.get("items", [])
    if not items_data:
        raise HTTPException(status_code=400, detail="At least one return item is required.")

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    date_str = now.strftime("%Y%m%d")

    with get_connection() as conn:
        count_row = conn.execute("SELECT count(*) FROM sales_returns WHERE return_number LIKE ?", (f"RET-{date_str}-%",)).fetchone()
        seq = (count_row[0] or 0) + 1
        return_num = f"RET-{date_str}-{seq:04d}"
        return_id = f"ret-{uuid.uuid4().hex[:10]}"

        conn.execute(
            """
            INSERT INTO sales_returns (
                id, return_number, sales_order_id, dispatch_id, customer_id, return_date,
                status, reason, notes, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'received', ?, ?, ?, ?, ?)
            """,
            (
                return_id,
                return_num,
                order_id,
                dispatch_id,
                order["customer_id"],
                now_iso[:10],
                reason,
                data.get("notes"),
                performed_by,
                now_iso,
                now_iso,
            ),
        )

        for it in items_data:
            order_item_id = it.get("order_item_id")
            ret_qty = float(it.get("returned_quantity", 0.0))
            if ret_qty <= 0:
                raise HTTPException(status_code=400, detail="Returned quantity must be greater than zero.")

            line = conn.execute("SELECT * FROM sales_order_items WHERE id = ? AND sales_order_id = ?", (order_item_id, order_id)).fetchone()
            if not line:
                raise HTTPException(status_code=400, detail=f"Order line '{order_item_id}' not found.")

            ret_item_id = f"rti-{uuid.uuid4().hex[:10]}"
            conn.execute(
                """
                INSERT INTO sales_return_items (
                    id, return_id, sales_order_item_id, product_id, sku, product_name,
                    returned_quantity, accepted_quantity, quarantined_quantity, rejected_quantity,
                    condition_notes, uom, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0.0, 0.0, 0.0, ?, ?, ?)
                """,
                (
                    ret_item_id,
                    return_id,
                    order_item_id,
                    line["product_id"],
                    line["product_sku"],
                    line["product_name"],
                    ret_qty,
                    it.get("inspection_notes"),
                    line["uom"] or "PCS",
                    now_iso,
                ),
            )
        conn.commit()

    record_erp_audit_log("sales_return", return_id, "create_return", {"return_number": return_num, "order_id": order_id}, performed_by)
    return get_sales_return_by_id(return_id)


def get_sales_return_by_id(return_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        r = conn.execute(
            """
            SELECT ret.*, o.order_number, c.name as customer_name
            FROM sales_returns ret
            JOIN sales_orders o ON ret.sales_order_id = o.id
            JOIN customers c ON ret.customer_id = c.id
            WHERE ret.id = ?
            """,
            (return_id,),
        ).fetchone()
        if not r:
            raise HTTPException(status_code=404, detail=f"Sales return '{return_id}' not found.")

        items = conn.execute("SELECT * FROM sales_return_items WHERE return_id = ?", (return_id,)).fetchall()

    return {
        "id": r["id"],
        "return_number": r["return_number"],
        "sales_order_id": r["sales_order_id"],
        "order_number": r["order_number"],
        "dispatch_id": r["dispatch_id"],
        "customer_id": r["customer_id"],
        "customer_name": r["customer_name"],
        "return_date": r["return_date"],
        "reason": r["reason"],
        "status": r["status"],
        "received_by": r["created_by"],
        "inspected_by": None,
        "notes": r["notes"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "items": [
            {
                "id": it["id"],
                "return_id": it["return_id"],
                "order_item_id": it["sales_order_item_id"],
                "product_id": it["product_id"],
                "sku": it["sku"],
                "returned_quantity": float(it["returned_quantity"]),
                "accepted_quantity": float(it["accepted_quantity"]),
                "quarantined_quantity": float(it["quarantined_quantity"]),
                "rejected_quantity": float(it["rejected_quantity"]),
                "warehouse_id": None,
                "location_id": None,
                "inspection_notes": it["condition_notes"],
            }
            for it in items
        ],
    }


def list_sales_returns(sales_order_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if sales_order_id:
        clauses.append("sales_order_id = ?")
        params.append(sales_order_id)
    if status:
        clauses.append("status = ?")
        params.append(status.strip().lower())

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection() as conn:
        rows = conn.execute(f"SELECT id FROM sales_returns {where} ORDER BY created_at DESC", params).fetchall()

    return [get_sales_return_by_id(r["id"]) for r in rows]


def process_sales_return(return_id: str, data: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    """
    Processes a sales return following strict inventory segregation rules:
    - Accepted stock is returned to available inventory (RETURN_RESTOCK)
    - Quarantined stock is posted to quarantined balances (RETURN_QUARANTINE) and NEVER available
    - Rejected stock is posted to rejected balances (RETURN_REJECT) and NEVER available
    """
    ret = get_sales_return_by_id(return_id)
    if ret["status"] not in ("received", "inspected"):
        raise HTTPException(status_code=400, detail=f"Cannot process sales return in '{ret['status']}' status.")

    items_input = {it.get("order_item_id"): it for it in data.get("items", [])}
    now_iso = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        # Default central warehouse
        wh = conn.execute("SELECT id FROM warehouses WHERE is_active = 1 LIMIT 1").fetchone()
        wh_id = wh["id"] if wh else "wh-main"

        for it in ret["items"]:
            inp = items_input.get(it["order_item_id"], {})
            acc_qty = float(inp.get("accepted_quantity", 0.0))
            quar_qty = float(inp.get("quarantined_quantity", 0.0))
            rej_qty = float(inp.get("rejected_quantity", 0.0))
            insp_notes = inp.get("inspection_notes") or it["inspection_notes"]

            total_inspected = acc_qty + quar_qty + rej_qty
            if total_inspected > it["returned_quantity"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Total processed {total_inspected} exceeds returned quantity {it['returned_quantity']} for SKU '{it['sku']}'.",
                )

            conn.execute(
                """
                UPDATE sales_return_items
                SET accepted_quantity = ?, quarantined_quantity = ?, rejected_quantity = ?, condition_notes = ?
                WHERE id = ?
                """,
                (acc_qty, quar_qty, rej_qty, insp_notes, it["id"]),
            )

            # Post Accepted stock (available)
            if acc_qty > 0:
                mov_id = f"mov-{uuid.uuid4().hex[:10]}"
                mov_num = f"MOV-{uuid.uuid4().hex[:8].upper()}"
                conn.execute(
                    """
                    INSERT INTO inventory_movements (
                        id, movement_number, idempotency_key, movement_type, reference_doc_type,
                        reference_doc_id, product_id, sku, quantity, stock_type, warehouse_id,
                        uom, performed_by, notes, created_at
                    ) VALUES (?, ?, ?, 'RETURN_RESTOCK', 'sales_return', ?, ?, ?, ?, 'available', ?, 'PCS', ?, ?, ?)
                    """,
                    (mov_id, mov_num, f"ret-acc-{ret['id']}-{it['product_id']}", ret["id"], it["product_id"], it["sku"], acc_qty, wh_id, performed_by, f"Accepted return {ret['return_number']}", now_iso),
                )
                _update_inventory_balance(conn, it["product_id"], it["sku"], "available", acc_qty, now_iso)

            # Post Quarantined stock (segregated)
            if quar_qty > 0:
                mov_id = f"mov-{uuid.uuid4().hex[:10]}"
                mov_num = f"MOV-{uuid.uuid4().hex[:8].upper()}"
                conn.execute(
                    """
                    INSERT INTO inventory_movements (
                        id, movement_number, idempotency_key, movement_type, reference_doc_type,
                        reference_doc_id, product_id, sku, quantity, stock_type, warehouse_id,
                        uom, performed_by, notes, created_at
                    ) VALUES (?, ?, ?, 'RETURN_QUARANTINE', 'sales_return', ?, ?, ?, ?, 'quarantined', ?, 'PCS', ?, ?, ?)
                    """,
                    (mov_id, mov_num, f"ret-quar-{ret['id']}-{it['product_id']}", ret["id"], it["product_id"], it["sku"], quar_qty, wh_id, performed_by, f"Quarantined return {ret['return_number']}", now_iso),
                )
                _update_inventory_balance(conn, it["product_id"], it["sku"], "quarantined", quar_qty, now_iso)

            # Post Rejected stock (segregated)
            if rej_qty > 0:
                mov_id = f"mov-{uuid.uuid4().hex[:10]}"
                mov_num = f"MOV-{uuid.uuid4().hex[:8].upper()}"
                conn.execute(
                    """
                    INSERT INTO inventory_movements (
                        id, movement_number, idempotency_key, movement_type, reference_doc_type,
                        reference_doc_id, product_id, sku, quantity, stock_type, warehouse_id,
                        uom, performed_by, notes, created_at
                    ) VALUES (?, ?, ?, 'RETURN_REJECT', 'sales_return', ?, ?, ?, ?, 'rejected', ?, 'PCS', ?, ?, ?)
                    """,
                    (mov_id, mov_num, f"ret-rej-{ret['id']}-{it['product_id']}", ret["id"], it["product_id"], it["sku"], rej_qty, wh_id, performed_by, f"Rejected return {ret['return_number']}", now_iso),
                )
                _update_inventory_balance(conn, it["product_id"], it["sku"], "rejected", rej_qty, now_iso)

        conn.execute("UPDATE sales_returns SET status = 'processed', updated_at = ? WHERE id = ?", (now_iso, return_id))
        conn.commit()

    record_erp_audit_log("sales_return", return_id, "process_return", {"status": "processed"}, performed_by)
    return get_sales_return_by_id(return_id)


# ==========================================
# 6. FastAPI Router Endpoints with RBAC
# ==========================================

# Quotations
@router.post("/quotations", response_model=QuotationResponse)
def api_create_quotation(
    req: QuotationCreateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "create_quotation")
    return create_customer_quotation(req.model_dump(), performed_by=current_user.username)


@router.get("/quotations", response_model=QuotationListResponse)
def api_list_quotations(
    customer_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    return list_customer_quotations(customer_id=customer_id, status=status, limit=limit, offset=offset)


@router.get("/quotations/{quotation_id}", response_model=QuotationResponse)
def api_get_quotation(
    quotation_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    return get_customer_quotation_by_id(quotation_id)


@router.post("/quotations/{quotation_id}/send", response_model=QuotationResponse)
def api_send_quotation(
    quotation_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "send_quotation")
    return send_customer_quotation(quotation_id, performed_by=current_user.username)


@router.post("/quotations/{quotation_id}/accept", response_model=QuotationResponse)
def api_accept_quotation(
    quotation_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "accept_quotation")
    return accept_customer_quotation(quotation_id, performed_by=current_user.username)


@router.post("/quotations/{quotation_id}/reject", response_model=QuotationResponse)
def api_reject_quotation(
    quotation_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "reject_quotation")
    return reject_customer_quotation(quotation_id, performed_by=current_user.username)


@router.post("/quotations/{quotation_id}/convert", response_model=SalesOrderResponse)
def api_convert_quotation(
    quotation_id: str,
    req: QuotationConvertRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "convert_quotation")
    return convert_quotation_to_sales_order(quotation_id, req.model_dump(), performed_by=current_user.username)


# Sales Orders
@router.post("/sales-orders", response_model=SalesOrderResponse)
def api_create_sales_order(
    req: SalesOrderCreateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "create_order")
    return create_sales_order(req.model_dump(), performed_by=current_user.username)


@router.get("/sales-orders", response_model=SalesOrderListResponse)
def api_list_sales_orders(
    customer_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    return list_sales_orders(customer_id=customer_id, status=status, limit=limit, offset=offset)


@router.get("/sales-orders/{order_id}", response_model=SalesOrderResponse)
def api_get_sales_order(
    order_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    return get_sales_order_by_id(order_id)


@router.post("/sales-orders/{order_id}/confirm", response_model=SalesOrderResponse)
def api_confirm_sales_order(
    order_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "confirm_order")
    return confirm_sales_order(order_id, performed_by=current_user.username)


@router.post("/sales-orders/{order_id}/allocate", response_model=SalesOrderResponse)
def api_allocate_sales_order(
    order_id: str,
    req: SalesOrderAllocateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "allocate_order")
    return allocate_sales_order(order_id, req.model_dump(), performed_by=current_user.username)


@router.post("/sales-orders/{order_id}/cancel", response_model=SalesOrderResponse)
def api_cancel_sales_order(
    order_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "cancel_order")
    return cancel_sales_order(order_id, performed_by=current_user.username)


@router.post("/sales-orders/{order_id}/pack", response_model=SalesOrderResponse)
def api_pack_sales_order(
    order_id: str,
    req: SalesOrderPackRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "pack_order")
    return pack_sales_order(order_id, req.model_dump(), performed_by=current_user.username)


# Picking
@router.post("/sales-pick-lists", response_model=SalesPickListResponse)
def api_create_pick_list(
    req: SalesPickListCreateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "create_pick_list")
    return create_sales_pick_list(req.model_dump(), performed_by=current_user.username)


@router.get("/sales-pick-lists", response_model=list[SalesPickListResponse])
def api_list_pick_lists(
    sales_order_id: str | None = Query(None),
    status: str | None = Query(None),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    return list_sales_pick_lists(sales_order_id=sales_order_id, status=status)


@router.get("/sales-pick-lists/{pick_list_id}", response_model=SalesPickListResponse)
def api_get_pick_list(
    pick_list_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    return get_sales_pick_list_by_id(pick_list_id)


@router.post("/sales-pick-lists/{pick_list_id}/complete", response_model=SalesPickListResponse)
def api_complete_pick_list(
    pick_list_id: str,
    req: SalesPickListCompleteRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "complete_pick_list")
    return complete_sales_pick_list(pick_list_id, req.model_dump(), performed_by=current_user.username)


# Commercial Dispatches
@router.post("/sales-dispatches", response_model=SalesDispatchResponse)
def api_create_dispatch(
    req: SalesDispatchCreateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "create_dispatch")
    return create_sales_dispatch(req.model_dump(), performed_by=current_user.username)


@router.get("/sales-dispatches", response_model=list[SalesDispatchResponse])
def api_list_dispatches(
    sales_order_id: str | None = Query(None),
    status: str | None = Query(None),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    return list_sales_dispatches(sales_order_id=sales_order_id, status=status)


@router.get("/sales-dispatches/{dispatch_id}", response_model=SalesDispatchResponse)
def api_get_dispatch(
    dispatch_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    return get_sales_dispatch_by_id(dispatch_id)


@router.post("/sales-dispatches/{dispatch_id}/deliver", response_model=SalesDispatchResponse)
def api_deliver_dispatch(
    dispatch_id: str,
    req: SalesDispatchDeliveryRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "deliver_dispatch")
    return deliver_sales_dispatch(dispatch_id, req.model_dump(), performed_by=current_user.username)


# Sales Returns
@router.post("/sales-returns", response_model=SalesReturnResponse)
def api_create_return(
    req: SalesReturnCreateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "create_return")
    return create_sales_return(req.model_dump(), performed_by=current_user.username)


@router.get("/sales-returns", response_model=list[SalesReturnResponse])
def api_list_returns(
    sales_order_id: str | None = Query(None),
    status: str | None = Query(None),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    return list_sales_returns(sales_order_id=sales_order_id, status=status)


@router.get("/sales-returns/{return_id}", response_model=SalesReturnResponse)
def api_get_return(
    return_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    return get_sales_return_by_id(return_id)


@router.post("/sales-returns/{return_id}/process", response_model=SalesReturnResponse)
def api_process_return(
    return_id: str,
    req: SalesReturnProcessRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "process_return")
    return process_sales_return(return_id, req.model_dump(), performed_by=current_user.username)
