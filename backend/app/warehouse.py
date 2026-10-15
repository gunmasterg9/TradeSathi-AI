"""
TradeSathi AI — Phase 3: Warehouse & Inventory Management Service
Implements:
1. Warehouses & Storage Locations (Zones, Racks, Shelves, Bins)
2. Stock Transfers (Dispatch, In-Transit, Receive with Discrepancy/Damage Handling)
3. Inventory Adjustments & Physical Stock Counts (with Compensating Movements)
4. Stock Reservations & Available-to-Promise (ATP) Calculations
5. Location-aware Stock Ledger & Materialized Balances
6. Comprehensive Reconciliation & Low-Stock Reports
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
import sqlite3

from app.auth import AuthenticatedUser, get_current_user
from app.db import get_connection
from app.master_data import record_erp_audit_log, verify_role_permission
from app.schemas import (
    InventoryAdjustmentCreateRequest,
    InventoryAdjustmentListResponse,
    InventoryAdjustmentResponse,
    ProductStockBalanceDetail,
    ProductStockBalanceReportResponse,
    ReconciliationItem,
    ReconciliationReportResponse,
    StockReservationCreateRequest,
    StockReservationListResponse,
    StockReservationResponse,
    StockTransferCreateRequest,
    StockTransferListResponse,
    StockTransferReceiveRequest,
    StockTransferResponse,
    WarehouseCreateRequest,
    WarehouseListResponse,
    WarehouseLocationCreateRequest,
    WarehouseLocationListResponse,
    WarehouseLocationResponse,
    WarehouseLocationUpdateRequest,
    WarehouseLocationStockDetail,
    WarehouseResponse,
    WarehouseStockReportResponse,
    WarehouseUpdateRequest,
)

router = APIRouter(tags=["Warehouse & Inventory"])


# ==========================================
# 1. Warehouse Master Data
# ==========================================

def create_warehouse(data: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    code = data.get("code", "").strip().upper()
    name = data.get("name", "").strip()
    if not code or not name:
        raise HTTPException(status_code=400, detail="Warehouse code and name are required.")

    now = datetime.now(timezone.utc).isoformat()
    wh_id = f"wh-{uuid.uuid4().hex[:10]}"

    with get_connection() as conn:
        existing = conn.execute("SELECT id FROM warehouses WHERE code = ?", (code,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail=f"Warehouse with code '{code}' already exists.")

        conn.execute(
            """
            INSERT INTO warehouses (id, code, name, address, city, country, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                wh_id,
                code,
                name,
                data.get("address"),
                data.get("city"),
                data.get("country", "IN"),
                now,
                now,
            ),
        )
        conn.commit()

    record_erp_audit_log("warehouse", wh_id, "create_warehouse", {"code": code, "name": name}, performed_by)
    return get_warehouse_by_id(wh_id)


def get_warehouse_by_id(warehouse_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM warehouses WHERE id = ?", (warehouse_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Warehouse '{warehouse_id}' not found.")
    return {
        "id": row["id"],
        "code": row["code"],
        "name": row["name"],
        "address": row["address"],
        "city": row["city"],
        "country": row["country"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_warehouses(is_active: bool | None = None) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if is_active is not None:
        clauses.append("is_active = ?")
        params.append(1 if is_active else 0)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection() as conn:
        rows = conn.execute(f"SELECT * FROM warehouses {where} ORDER BY code ASC", params).fetchall()

    return [
        {
            "id": r["id"],
            "code": r["code"],
            "name": r["name"],
            "address": r["address"],
            "city": r["city"],
            "country": r["country"],
            "is_active": bool(r["is_active"]),
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


def update_warehouse(warehouse_id: str, data: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    existing = get_warehouse_by_id(warehouse_id)
    now = datetime.now(timezone.utc).isoformat()

    updates = []
    params: list[Any] = []

    if "name" in data and data["name"] is not None:
        updates.append("name = ?")
        params.append(data["name"].strip())
    if "address" in data and data["address"] is not None:
        updates.append("address = ?")
        params.append(data["address"])
    if "city" in data and data["city"] is not None:
        updates.append("city = ?")
        params.append(data["city"])
    if "country" in data and data["country"] is not None:
        updates.append("country = ?")
        params.append(data["country"])

    if "is_active" in data and data["is_active"] is not None:
        new_active = 1 if data["is_active"] else 0
        if new_active == 0 and existing["is_active"]:
            # Safe deactivation rule: check for active stock or active reservations
            with get_connection() as conn:
                stock_row = conn.execute(
                    "SELECT SUM(on_hand_qty) FROM location_inventory_balances WHERE warehouse_id = ?",
                    (warehouse_id,),
                ).fetchone()
                total_stock = stock_row[0] or 0.0

                res_row = conn.execute(
                    "SELECT COUNT(*) FROM stock_reservations WHERE warehouse_id = ? AND status = 'active'",
                    (warehouse_id,),
                ).fetchone()
                active_res = res_row[0] or 0

                if total_stock > 0 or active_res > 0:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Cannot deactivate warehouse '{existing['code']}': it contains {total_stock} units "
                            f"of active stock and {active_res} active reservation(s). Transfer or adjust stock first."
                        ),
                    )
        updates.append("is_active = ?")
        params.append(new_active)

    if not updates:
        return existing

    updates.append("updated_at = ?")
    params.append(now)
    params.append(warehouse_id)

    with get_connection() as conn:
        conn.execute(f"UPDATE warehouses SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()

    record_erp_audit_log("warehouse", warehouse_id, "update_warehouse", data, performed_by)
    return get_warehouse_by_id(warehouse_id)


# ==========================================
# 2. Storage Locations (Zones, Racks, Bins)
# ==========================================

def create_warehouse_location(data: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    warehouse_id = data.get("warehouse_id")
    loc_code = data.get("location_code", "").strip().upper()
    if not warehouse_id or not loc_code:
        raise HTTPException(status_code=400, detail="Warehouse ID and location code are required.")

    # Validate parent warehouse exists and is active
    parent_wh = get_warehouse_by_id(warehouse_id)
    if not parent_wh["is_active"]:
        raise HTTPException(status_code=400, detail=f"Cannot add location to inactive warehouse '{parent_wh['code']}'.")

    now = datetime.now(timezone.utc).isoformat()
    loc_id = f"loc-{uuid.uuid4().hex[:10]}"

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM warehouse_locations WHERE warehouse_id = ? AND location_code = ?",
            (warehouse_id, loc_code),
        ).fetchone()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Location '{loc_code}' already exists in warehouse '{parent_wh['code']}'.",
            )

        conn.execute(
            """
            INSERT INTO warehouse_locations (
                id, warehouse_id, location_code, zone, rack, shelf, bin, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                loc_id,
                warehouse_id,
                loc_code,
                data.get("zone"),
                data.get("rack"),
                data.get("shelf"),
                data.get("bin"),
                now,
                now,
            ),
        )
        conn.commit()

    record_erp_audit_log(
        "warehouse_location",
        loc_id,
        "create_location",
        {"warehouse_code": parent_wh["code"], "location_code": loc_code},
        performed_by,
    )
    return get_warehouse_location_by_id(loc_id)


def get_warehouse_location_by_id(location_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT l.*, w.code as warehouse_code
            FROM warehouse_locations l
            JOIN warehouses w ON l.warehouse_id = w.id
            WHERE l.id = ?
            """,
            (location_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Location '{location_id}' not found.")
    return {
        "id": row["id"],
        "warehouse_id": row["warehouse_id"],
        "warehouse_code": row["warehouse_code"],
        "location_code": row["location_code"],
        "zone": row["zone"],
        "rack": row["rack"],
        "shelf": row["shelf"],
        "bin": row["bin"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_warehouse_locations(warehouse_id: str | None = None, is_active: bool | None = None) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if warehouse_id:
        clauses.append("l.warehouse_id = ?")
        params.append(warehouse_id)
    if is_active is not None:
        clauses.append("l.is_active = ?")
        params.append(1 if is_active else 0)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"""
        SELECT l.*, w.code as warehouse_code
        FROM warehouse_locations l
        JOIN warehouses w ON l.warehouse_id = w.id
        {where}
        ORDER BY w.code ASC, l.location_code ASC
    """
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    return [
        {
            "id": r["id"],
            "warehouse_id": r["warehouse_id"],
            "warehouse_code": r["warehouse_code"],
            "location_code": r["location_code"],
            "zone": r["zone"],
            "rack": r["rack"],
            "shelf": r["shelf"],
            "bin": r["bin"],
            "is_active": bool(r["is_active"]),
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


def update_warehouse_location(location_id: str, data: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    existing = get_warehouse_location_by_id(location_id)
    now = datetime.now(timezone.utc).isoformat()

    updates = []
    params: list[Any] = []

    for f in ["zone", "rack", "shelf", "bin"]:
        if f in data and data[f] is not None:
            updates.append(f"{f} = ?")
            params.append(data[f])

    if "is_active" in data and data["is_active"] is not None:
        new_active = 1 if data["is_active"] else 0
        if new_active == 0 and existing["is_active"]:
            # Check for stock at this location
            with get_connection() as conn:
                stock_row = conn.execute(
                    "SELECT SUM(on_hand_qty) FROM location_inventory_balances WHERE location_id = ?",
                    (location_id,),
                ).fetchone()
                total_stock = stock_row[0] or 0.0
                if total_stock > 0:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Cannot deactivate location '{existing['location_code']}': "
                            f"contains {total_stock} units of active stock. Move stock first."
                        ),
                    )
        updates.append("is_active = ?")
        params.append(new_active)

    if not updates:
        return existing

    updates.append("updated_at = ?")
    params.append(now)
    params.append(location_id)

    with get_connection() as conn:
        conn.execute(f"UPDATE warehouse_locations SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()

    record_erp_audit_log("warehouse_location", location_id, "update_location", data, performed_by)
    return get_warehouse_location_by_id(location_id)


# ==========================================
# 3. Stock Transfers
# ==========================================

def create_stock_transfer(data: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    src_wh_id = data.get("source_warehouse_id")
    dest_wh_id = data.get("dest_warehouse_id")
    src_loc_id = data.get("source_location_id")
    dest_loc_id = data.get("dest_location_id")
    items = data.get("items", [])
    idempotency_key = data.get("idempotency_key")

    if not src_wh_id or not dest_wh_id:
        raise HTTPException(status_code=400, detail="Source and destination warehouses are required.")
    if src_wh_id == dest_wh_id and src_loc_id == dest_loc_id:
        raise HTTPException(status_code=400, detail="Source and destination warehouse and location cannot be identical.")
    if not items:
        raise HTTPException(status_code=400, detail="At least one transfer item is required.")

    # Validate warehouses
    src_wh = get_warehouse_by_id(src_wh_id)
    dest_wh = get_warehouse_by_id(dest_wh_id)
    if not src_wh["is_active"]:
        raise HTTPException(status_code=400, detail=f"Source warehouse '{src_wh['code']}' is inactive.")
    if not dest_wh["is_active"]:
        raise HTTPException(status_code=400, detail=f"Destination warehouse '{dest_wh['code']}' is inactive.")

    with get_connection() as conn:
        if idempotency_key:
            existing = conn.execute("SELECT id FROM stock_transfers WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
            if existing:
                return get_stock_transfer_by_id(existing["id"])

        # Auto-generate transfer number
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        date_str = now.strftime("%Y%m%d")
        count_row = conn.execute(
            "SELECT count(*) FROM stock_transfers WHERE transfer_number LIKE ?",
            (f"TRF-{date_str}-%",),
        ).fetchone()
        seq = (count_row[0] or 0) + 1
        transfer_number = f"TRF-{date_str}-{seq:04d}"

        transfer_id = f"trf-{uuid.uuid4().hex[:10]}"

        conn.execute(
            """
            INSERT INTO stock_transfers (
                id, transfer_number, idempotency_key, source_warehouse_id, source_location_id,
                dest_warehouse_id, dest_location_id, status, created_by, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?)
            """,
            (
                transfer_id,
                transfer_number,
                idempotency_key,
                src_wh_id,
                src_loc_id,
                dest_wh_id,
                dest_loc_id,
                performed_by,
                data.get("notes"),
                now_iso,
                now_iso,
            ),
        )

        for itm in items:
            prod_id = itm["product_id"]
            qty = float(itm["requested_quantity"])
            if qty <= 0:
                raise HTTPException(status_code=400, detail=f"Requested quantity for product '{prod_id}' must be positive.")

            prod = conn.execute("SELECT sku, name, uom, is_active FROM products WHERE id = ?", (prod_id,)).fetchone()
            if not prod:
                raise HTTPException(status_code=400, detail=f"Product '{prod_id}' not found.")
            if not prod["is_active"]:
                raise HTTPException(status_code=400, detail=f"Product '{prod['sku']}' is inactive.")

            itm_id = f"trfi-{uuid.uuid4().hex[:10]}"
            conn.execute(
                """
                INSERT INTO stock_transfer_items (
                    id, transfer_id, product_id, sku, product_name, requested_quantity,
                    uom, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    itm_id,
                    transfer_id,
                    prod_id,
                    prod["sku"],
                    prod["name"],
                    qty,
                    prod["uom"],
                    itm.get("notes"),
                    now_iso,
                    now_iso,
                ),
            )

        conn.commit()

    record_erp_audit_log("stock_transfer", transfer_id, "create_transfer", {"transfer_number": transfer_number}, performed_by)
    return get_stock_transfer_by_id(transfer_id)


def get_stock_transfer_by_id(transfer_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT t.*,
                   sw.code as source_warehouse_code,
                   dw.code as dest_warehouse_code,
                   sl.location_code as source_location_code,
                   dl.location_code as dest_location_code
            FROM stock_transfers t
            JOIN warehouses sw ON t.source_warehouse_id = sw.id
            JOIN warehouses dw ON t.dest_warehouse_id = dw.id
            LEFT JOIN warehouse_locations sl ON t.source_location_id = sl.id
            LEFT JOIN warehouse_locations dl ON t.dest_location_id = dl.id
            WHERE t.id = ?
            """,
            (transfer_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Stock transfer '{transfer_id}' not found.")

        item_rows = conn.execute("SELECT * FROM stock_transfer_items WHERE transfer_id = ? ORDER BY id ASC", (transfer_id,)).fetchall()

    items = [
        {
            "id": r["id"],
            "transfer_id": r["transfer_id"],
            "product_id": r["product_id"],
            "sku": r["sku"],
            "product_name": r["product_name"],
            "requested_quantity": float(r["requested_quantity"]),
            "dispatched_quantity": float(r["dispatched_quantity"]),
            "received_quantity": float(r["received_quantity"]),
            "damaged_quantity": float(r["damaged_quantity"]),
            "shortage_quantity": float(r["shortage_quantity"]),
            "uom": r["uom"],
            "discrepancy_reason": r["discrepancy_reason"],
            "notes": r["notes"],
        }
        for r in item_rows
    ]

    return {
        "id": row["id"],
        "transfer_number": row["transfer_number"],
        "idempotency_key": row["idempotency_key"],
        "source_warehouse_id": row["source_warehouse_id"],
        "source_warehouse_code": row["source_warehouse_code"],
        "source_location_id": row["source_location_id"],
        "source_location_code": row["source_location_code"],
        "dest_warehouse_id": row["dest_warehouse_id"],
        "dest_warehouse_code": row["dest_warehouse_code"],
        "dest_location_id": row["dest_location_id"],
        "dest_location_code": row["dest_location_code"],
        "status": row["status"],
        "created_by": row["created_by"],
        "approved_by": row["approved_by"],
        "dispatched_by": row["dispatched_by"],
        "received_by": row["received_by"],
        "notes": row["notes"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "approved_at": row["approved_at"],
        "dispatched_at": row["dispatched_at"],
        "received_at": row["received_at"],
        "items": items,
    }


def list_stock_transfers(status: str | None = None) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if status:
        clauses.append("t.status = ?")
        params.append(status.strip().lower())

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT t.id
            FROM stock_transfers t
            {where}
            ORDER BY t.created_at DESC
            """,
            params,
        ).fetchall()

    return [get_stock_transfer_by_id(r["id"]) for r in rows]


def approve_stock_transfer(transfer_id: str, performed_by: str = "Local Operator") -> dict[str, Any]:
    transfer = get_stock_transfer_by_id(transfer_id)
    if transfer["status"] != "draft":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve transfer in '{transfer['status']}' status (must be 'draft').",
        )

    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        # Check source warehouse stock availability
        for itm in transfer["items"]:
            bal_row = conn.execute(
                """
                SELECT on_hand_qty FROM inventory_balances
                WHERE product_id = ? AND stock_type = 'available'
                """,
                (itm["product_id"],),
            ).fetchone()
            avail = float(bal_row["on_hand_qty"]) if bal_row else 0.0
            if avail < itm["requested_quantity"]:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Insufficient stock for '{itm['sku']}' at source warehouse. "
                        f"Available: {avail}, Requested: {itm['requested_quantity']}."
                    ),
                )

        conn.execute(
            "UPDATE stock_transfers SET status = 'approved', approved_by = ?, approved_at = ?, updated_at = ? WHERE id = ?",
            (performed_by, now, now, transfer_id),
        )
        conn.commit()

    record_erp_audit_log("stock_transfer", transfer_id, "approve_transfer", {}, performed_by)
    return get_stock_transfer_by_id(transfer_id)


def dispatch_stock_transfer(transfer_id: str, performed_by: str = "Local Operator") -> dict[str, Any]:
    transfer = get_stock_transfer_by_id(transfer_id)
    if transfer["status"] not in ("approved", "draft"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot dispatch transfer in '{transfer['status']}' status (must be approved).",
        )

    now = datetime.now(timezone.utc).isoformat()
    src_wh = transfer["source_warehouse_id"]
    dest_wh = transfer["dest_warehouse_id"]
    src_loc = transfer["source_location_id"]
    dest_loc = transfer["dest_location_id"]

    with get_connection() as conn:
        for itm in transfer["items"]:
            qty = itm["requested_quantity"]
            prod_id = itm["product_id"]
            sku = itm["sku"]

            # Check available stock
            bal = conn.execute(
                "SELECT on_hand_qty FROM inventory_balances WHERE product_id = ? AND stock_type = 'available'",
                (prod_id,),
            ).fetchone()
            avail = float(bal["on_hand_qty"]) if bal else 0.0
            if avail < qty:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot dispatch '{sku}': insufficient available stock. Available: {avail}, Required: {qty}.",
                )

            # 1. Deduct from Source Warehouse (Available)
            src_mov_id = f"mov-{uuid.uuid4().hex[:10]}"
            src_mov_num = f"MOV-{uuid.uuid4().hex[:8].upper()}"
            src_key = f"trf-disp-{transfer_id}-{itm['id']}"

            conn.execute(
                """
                INSERT INTO inventory_movements (
                    id, movement_number, idempotency_key, movement_type, reference_doc_type,
                    reference_doc_id, product_id, sku, quantity, stock_type, warehouse_id, location_id,
                    performed_by, notes, created_at
                ) VALUES (?, ?, ?, 'TRANSFER_DISPATCH', 'stock_transfer', ?, ?, ?, ?, 'available', ?, ?, ?, ?, ?)
                """,
                (
                    src_mov_id,
                    src_mov_num,
                    src_key,
                    transfer_id,
                    prod_id,
                    sku,
                    -qty,
                    src_wh,
                    src_loc,
                    performed_by,
                    f"Dispatched via transfer {transfer['transfer_number']}",
                    now,
                ),
            )

            # Update overall inventory_balances
            new_avail = avail - qty
            conn.execute(
                "UPDATE inventory_balances SET on_hand_qty = ?, updated_at = ? WHERE product_id = ? AND stock_type = 'available'",
                (new_avail, now, prod_id),
            )

            # 2. Add to In-Transit Stock
            transit_mov_id = f"mov-{uuid.uuid4().hex[:10]}"
            transit_mov_num = f"MOV-{uuid.uuid4().hex[:8].upper()}"
            transit_key = f"trf-transit-{transfer_id}-{itm['id']}"

            conn.execute(
                """
                INSERT INTO inventory_movements (
                    id, movement_number, idempotency_key, movement_type, reference_doc_type,
                    reference_doc_id, product_id, sku, quantity, stock_type, warehouse_id, location_id,
                    performed_by, notes, created_at
                ) VALUES (?, ?, ?, 'TRANSFER_IN_TRANSIT', 'stock_transfer', ?, ?, ?, ?, 'in_transit', ?, ?, ?, ?, ?)
                """,
                (
                    transit_mov_id,
                    transit_mov_num,
                    transit_key,
                    transfer_id,
                    prod_id,
                    sku,
                    qty,
                    dest_wh,
                    dest_loc,
                    performed_by,
                    f"In-transit via transfer {transfer['transfer_number']} to {transfer['dest_warehouse_code']}",
                    now,
                ),
            )

            # Update in_transit in inventory_balances
            t_bal = conn.execute(
                "SELECT on_hand_qty FROM inventory_balances WHERE product_id = ? AND stock_type = 'in_transit'",
                (prod_id,),
            ).fetchone()
            if t_bal:
                new_t_qty = float(t_bal["on_hand_qty"]) + qty
                conn.execute(
                    "UPDATE inventory_balances SET on_hand_qty = ?, updated_at = ? WHERE product_id = ? AND stock_type = 'in_transit'",
                    (new_t_qty, now, prod_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO inventory_balances (product_id, stock_type, sku, on_hand_qty, total_value, updated_at)
                    VALUES (?, 'in_transit', ?, ?, 0.0, ?)
                    """,
                    (prod_id, sku, qty, now),
                )

            # Update item dispatched qty
            conn.execute(
                "UPDATE stock_transfer_items SET dispatched_quantity = ?, updated_at = ? WHERE id = ?",
                (qty, now, itm["id"]),
            )

        conn.execute(
            """
            UPDATE stock_transfers
            SET status = 'dispatched', dispatched_by = ?, dispatched_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (performed_by, now, now, transfer_id),
        )
        conn.commit()

    record_erp_audit_log("stock_transfer", transfer_id, "dispatch_transfer", {}, performed_by)
    return get_stock_transfer_by_id(transfer_id)


def receive_stock_transfer(transfer_id: str, data: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    transfer = get_stock_transfer_by_id(transfer_id)
    if transfer["status"] != "dispatched":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot receive transfer in '{transfer['status']}' status (must be 'dispatched').",
        )

    now = datetime.now(timezone.utc).isoformat()
    dest_wh = transfer["dest_warehouse_id"]
    dest_loc = transfer["dest_location_id"]
    receive_items = {itm["item_id"]: itm for itm in data.get("items", [])}

    has_discrepancy = False

    with get_connection() as conn:
        for itm in transfer["items"]:
            rec_info = receive_items.get(itm["id"])
            if not rec_info:
                raise HTTPException(status_code=400, detail=f"Missing receive payload for transfer item '{itm['id']}'.")

            rec_qty = float(rec_info.get("received_quantity", 0.0))
            dmg_qty = float(rec_info.get("damaged_quantity", 0.0))
            reason = rec_info.get("discrepancy_reason")
            dispatched = itm["dispatched_quantity"]

            if rec_qty < 0 or dmg_qty < 0:
                raise HTTPException(status_code=400, detail="Received and damaged quantities cannot be negative.")
            if (rec_qty + dmg_qty) > dispatched:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Sum of received ({rec_qty}) and damaged ({dmg_qty}) exceeds "
                        f"dispatched quantity ({dispatched}) for '{itm['sku']}'."
                    ),
                )

            shortage_qty = dispatched - (rec_qty + dmg_qty)
            if shortage_qty > 0 or dmg_qty > 0:
                has_discrepancy = True

            prod_id = itm["product_id"]
            sku = itm["sku"]

            # 1. Clear In-Transit Stock
            t_clear_id = f"mov-{uuid.uuid4().hex[:10]}"
            t_clear_num = f"MOV-{uuid.uuid4().hex[:8].upper()}"
            t_clear_key = f"trf-clear-{transfer_id}-{itm['id']}"

            conn.execute(
                """
                INSERT INTO inventory_movements (
                    id, movement_number, idempotency_key, movement_type, reference_doc_type,
                    reference_doc_id, product_id, sku, quantity, stock_type, warehouse_id, location_id,
                    performed_by, notes, created_at
                ) VALUES (?, ?, ?, 'TRANSFER_IN_TRANSIT_CLEAR', 'stock_transfer', ?, ?, ?, ?, 'in_transit', ?, ?, ?, ?, ?)
                """,
                (
                    t_clear_id,
                    t_clear_num,
                    t_clear_key,
                    transfer_id,
                    prod_id,
                    sku,
                    -dispatched,
                    dest_wh,
                    dest_loc,
                    performed_by,
                    f"Cleared in-transit for transfer {transfer['transfer_number']}",
                    now,
                ),
            )

            # Deduct from in_transit balance
            t_bal = conn.execute(
                "SELECT on_hand_qty FROM inventory_balances WHERE product_id = ? AND stock_type = 'in_transit'",
                (prod_id,),
            ).fetchone()
            cur_t = float(t_bal["on_hand_qty"]) if t_bal else dispatched
            conn.execute(
                "UPDATE inventory_balances SET on_hand_qty = ?, updated_at = ? WHERE product_id = ? AND stock_type = 'in_transit'",
                (max(0.0, cur_t - dispatched), now, prod_id),
            )

            # 2. Add Accepted Stock to Destination Warehouse (Available)
            if rec_qty > 0:
                rec_mov_id = f"mov-{uuid.uuid4().hex[:10]}"
                rec_mov_num = f"MOV-{uuid.uuid4().hex[:8].upper()}"
                rec_key = f"trf-recv-{transfer_id}-{itm['id']}"

                conn.execute(
                    """
                    INSERT INTO inventory_movements (
                        id, movement_number, idempotency_key, movement_type, reference_doc_type,
                        reference_doc_id, product_id, sku, quantity, stock_type, warehouse_id, location_id,
                        performed_by, notes, created_at
                    ) VALUES (?, ?, ?, 'TRANSFER_RECEIPT', 'stock_transfer', ?, ?, ?, ?, 'available', ?, ?, ?, ?, ?)
                    """,
                    (
                        rec_mov_id,
                        rec_mov_num,
                        rec_key,
                        transfer_id,
                        prod_id,
                        sku,
                        rec_qty,
                        dest_wh,
                        dest_loc,
                        performed_by,
                        f"Received stock via transfer {transfer['transfer_number']}",
                        now,
                    ),
                )

                # Update available balance
                avail_bal = conn.execute(
                    "SELECT on_hand_qty FROM inventory_balances WHERE product_id = ? AND stock_type = 'available'",
                    (prod_id,),
                ).fetchone()
                cur_avail = float(avail_bal["on_hand_qty"]) if avail_bal else 0.0
                conn.execute(
                    "UPDATE inventory_balances SET on_hand_qty = ?, updated_at = ? WHERE product_id = ? AND stock_type = 'available'",
                    (cur_avail + rec_qty, now, prod_id),
                )

            # 3. Add Damaged Stock to Quarantined
            if dmg_qty > 0:
                dmg_mov_id = f"mov-{uuid.uuid4().hex[:10]}"
                dmg_mov_num = f"MOV-{uuid.uuid4().hex[:8].upper()}"
                dmg_key = f"trf-dmg-{transfer_id}-{itm['id']}"

                conn.execute(
                    """
                    INSERT INTO inventory_movements (
                        id, movement_number, idempotency_key, movement_type, reference_doc_type,
                        reference_doc_id, product_id, sku, quantity, stock_type, warehouse_id, location_id,
                        performed_by, notes, created_at
                    ) VALUES (?, ?, ?, 'TRANSFER_RECEIPT_DAMAGED', 'stock_transfer', ?, ?, ?, ?, 'quarantined', ?, ?, ?, ?, ?)
                    """,
                    (
                        dmg_mov_id,
                        dmg_mov_num,
                        dmg_key,
                        transfer_id,
                        prod_id,
                        sku,
                        dmg_qty,
                        dest_wh,
                        dest_loc,
                        performed_by,
                        f"Damaged in transit {transfer['transfer_number']}: {reason or 'Damage'}",
                        now,
                    ),
                )

                q_bal = conn.execute(
                    "SELECT on_hand_qty FROM inventory_balances WHERE product_id = ? AND stock_type = 'quarantined'",
                    (prod_id,),
                ).fetchone()
                if q_bal:
                    conn.execute(
                        "UPDATE inventory_balances SET on_hand_qty = ?, updated_at = ? WHERE product_id = ? AND stock_type = 'quarantined'",
                        (float(q_bal["on_hand_qty"]) + dmg_qty, now, prod_id),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO inventory_balances (product_id, stock_type, sku, on_hand_qty, total_value, updated_at)
                        VALUES (?, 'quarantined', ?, ?, 0.0, ?)
                        """,
                        (prod_id, sku, dmg_qty, now),
                    )

            # 4. Shortage loss audit record (0 qty movement, logged for reconciliation)
            if shortage_qty > 0:
                short_mov_id = f"mov-{uuid.uuid4().hex[:10]}"
                short_mov_num = f"MOV-{uuid.uuid4().hex[:8].upper()}"
                short_key = f"trf-short-{transfer_id}-{itm['id']}"

                conn.execute(
                    """
                    INSERT INTO inventory_movements (
                        id, movement_number, idempotency_key, movement_type, reference_doc_type,
                        reference_doc_id, product_id, sku, quantity, stock_type, warehouse_id, location_id,
                        performed_by, notes, created_at
                    ) VALUES (?, ?, ?, 'TRANSFER_SHORTAGE_LOSS', 'stock_transfer', ?, ?, ?, 0, 'available', ?, ?, ?, ?, ?)
                    """,
                    (
                        short_mov_id,
                        short_mov_num,
                        short_key,
                        transfer_id,
                        prod_id,
                        sku,
                        dest_wh,
                        dest_loc,
                        performed_by,
                        f"Shortage discrepancy: {shortage_qty} units missing from transfer {transfer['transfer_number']}. Reason: {reason or 'Missing'}",
                        now,
                    ),
                )

            # Update line item details
            conn.execute(
                """
                UPDATE stock_transfer_items
                SET received_quantity = ?, damaged_quantity = ?, shortage_quantity = ?,
                    discrepancy_reason = ?, updated_at = ?
                WHERE id = ?
                """,
                (rec_qty, dmg_qty, shortage_qty, reason, now, itm["id"]),
            )

        final_status = "discrepancy" if has_discrepancy else "received"
        conn.execute(
            """
            UPDATE stock_transfers
            SET status = ?, received_by = ?, received_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (final_status, performed_by, now, now, transfer_id),
        )
        conn.commit()

    record_erp_audit_log(
        "stock_transfer",
        transfer_id,
        "receive_transfer",
        {"status": final_status, "has_discrepancy": has_discrepancy},
        performed_by,
    )
    return get_stock_transfer_by_id(transfer_id)


def cancel_stock_transfer(transfer_id: str, reason: str, performed_by: str = "Local Operator") -> dict[str, Any]:
    transfer = get_stock_transfer_by_id(transfer_id)
    if transfer["status"] not in ("draft", "approved"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel transfer in '{transfer['status']}' status (must be draft or approved).",
        )

    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE stock_transfers SET status = 'cancelled', notes = ?, updated_at = ? WHERE id = ?",
            (f"Cancelled: {reason}", now, transfer_id),
        )
        conn.commit()

    record_erp_audit_log("stock_transfer", transfer_id, "cancel_transfer", {"reason": reason}, performed_by)
    return get_stock_transfer_by_id(transfer_id)


# ==========================================
# 4. Inventory Adjustments & Stock Counts
# ==========================================

def create_inventory_adjustment(data: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    prod_id = data.get("product_id")
    wh_id = data.get("warehouse_id")
    loc_id = data.get("location_id")
    stock_type = data.get("stock_type", "available").strip().lower()
    counted_qty = float(data.get("counted_quantity", 0.0))
    reason = data.get("reason_code", "PHYSICAL_COUNT").strip().upper()
    idempotency_key = data.get("idempotency_key")

    if not prod_id or not wh_id:
        raise HTTPException(status_code=400, detail="Product ID and Warehouse ID are required.")
    if counted_qty < 0:
        raise HTTPException(status_code=400, detail="Counted physical quantity cannot be negative.")

    wh = get_warehouse_by_id(wh_id)
    if not wh["is_active"]:
        raise HTTPException(status_code=400, detail=f"Cannot adjust inventory at inactive warehouse '{wh['code']}'.")

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    with get_connection() as conn:
        if idempotency_key:
            existing = conn.execute("SELECT id FROM inventory_adjustments WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
            if existing:
                return get_inventory_adjustment_by_id(existing["id"])

        prod = conn.execute("SELECT sku, name, uom FROM products WHERE id = ?", (prod_id,)).fetchone()
        if not prod:
            raise HTTPException(status_code=400, detail=f"Product '{prod_id}' not found.")

        # Determine current system quantity
        bal = conn.execute(
            "SELECT on_hand_qty FROM inventory_balances WHERE product_id = ? AND stock_type = ?",
            (prod_id, stock_type),
        ).fetchone()
        sys_qty = float(bal["on_hand_qty"]) if bal else 0.0
        diff_qty = round(counted_qty - sys_qty, 3)

        # Generate adjustment number
        date_str = now.strftime("%Y%m%d")
        count_row = conn.execute(
            "SELECT count(*) FROM inventory_adjustments WHERE adjustment_number LIKE ?",
            (f"ADJ-{date_str}-%",),
        ).fetchone()
        seq = (count_row[0] or 0) + 1
        adj_num = f"ADJ-{date_str}-{seq:04d}"
        adj_id = f"adj-{uuid.uuid4().hex[:10]}"

        conn.execute(
            """
            INSERT INTO inventory_adjustments (
                id, adjustment_number, idempotency_key, product_id, sku, warehouse_id, location_id,
                stock_type, system_quantity, counted_quantity, difference_quantity, uom,
                reason_code, notes, status, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                adj_id,
                adj_num,
                idempotency_key,
                prod_id,
                prod["sku"],
                wh_id,
                loc_id,
                stock_type,
                sys_qty,
                counted_qty,
                diff_qty,
                prod["uom"],
                reason,
                data.get("notes"),
                performed_by,
                now_iso,
                now_iso,
            ),
        )
        conn.commit()

    record_erp_audit_log(
        "inventory_adjustment",
        adj_id,
        "create_adjustment",
        {"adjustment_number": adj_num, "difference_quantity": diff_qty},
        performed_by,
    )
    return get_inventory_adjustment_by_id(adj_id)


def get_inventory_adjustment_by_id(adjustment_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT a.*, p.name as product_name, w.code as warehouse_code, l.location_code
            FROM inventory_adjustments a
            JOIN products p ON a.product_id = p.id
            JOIN warehouses w ON a.warehouse_id = w.id
            LEFT JOIN warehouse_locations l ON a.location_id = l.id
            WHERE a.id = ?
            """,
            (adjustment_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Inventory adjustment '{adjustment_id}' not found.")

    return {
        "id": row["id"],
        "adjustment_number": row["adjustment_number"],
        "idempotency_key": row["idempotency_key"],
        "product_id": row["product_id"],
        "sku": row["sku"],
        "product_name": row["product_name"],
        "warehouse_id": row["warehouse_id"],
        "warehouse_code": row["warehouse_code"],
        "location_id": row["location_id"],
        "location_code": row["location_code"],
        "stock_type": row["stock_type"],
        "system_quantity": float(row["system_quantity"]),
        "counted_quantity": float(row["counted_quantity"]),
        "difference_quantity": float(row["difference_quantity"]),
        "uom": row["uom"],
        "reason_code": row["reason_code"],
        "notes": row["notes"],
        "status": row["status"],
        "created_by": row["created_by"],
        "approved_by": row["approved_by"],
        "approved_at": row["approved_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_inventory_adjustments(status: str | None = None) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status.strip().lower())

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection() as conn:
        rows = conn.execute(f"SELECT id FROM inventory_adjustments {where} ORDER BY created_at DESC", params).fetchall()

    return [get_inventory_adjustment_by_id(r["id"]) for r in rows]


def approve_inventory_adjustment(adjustment_id: str, performed_by: str = "Local Operator") -> dict[str, Any]:
    adj = get_inventory_adjustment_by_id(adjustment_id)
    if adj["status"] != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Adjustment '{adj['adjustment_number']}' is already in '{adj['status']}' status.",
        )

    diff_qty = adj["difference_quantity"]
    prod_id = adj["product_id"]
    stock_type = adj["stock_type"]
    wh_id = adj["warehouse_id"]
    loc_id = adj["location_id"]
    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        # Check current balance to prevent negative available inventory
        bal = conn.execute(
            "SELECT on_hand_qty FROM inventory_balances WHERE product_id = ? AND stock_type = ?",
            (prod_id, stock_type),
        ).fetchone()
        cur_on_hand = float(bal["on_hand_qty"]) if bal else 0.0

        if diff_qty < 0 and (cur_on_hand + diff_qty) < 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Adjustment would result in negative {stock_type} inventory. "
                    f"Current: {cur_on_hand}, Difference: {diff_qty}."
                ),
            )

        if diff_qty != 0:
            # Post compensating movement
            mov_id = f"mov-{uuid.uuid4().hex[:10]}"
            mov_num = f"MOV-{uuid.uuid4().hex[:8].upper()}"
            mov_key = f"adj-{adjustment_id}"

            conn.execute(
                """
                INSERT INTO inventory_movements (
                    id, movement_number, idempotency_key, movement_type, reference_doc_type,
                    reference_doc_id, product_id, sku, quantity, stock_type, warehouse_id, location_id,
                    performed_by, notes, created_at
                ) VALUES (?, ?, ?, 'INVENTORY_ADJUSTMENT', 'inventory_adjustment', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mov_id,
                    mov_num,
                    mov_key,
                    adjustment_id,
                    prod_id,
                    adj["sku"],
                    diff_qty,
                    stock_type,
                    wh_id,
                    loc_id,
                    performed_by,
                    f"Adjustment {adj['adjustment_number']} ({adj['reason_code']}): {adj['notes'] or ''}",
                    now,
                ),
            )

            # Update inventory_balances
            new_qty = cur_on_hand + diff_qty
            if bal:
                conn.execute(
                    "UPDATE inventory_balances SET on_hand_qty = ?, updated_at = ? WHERE product_id = ? AND stock_type = ?",
                    (new_qty, now, prod_id, stock_type),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO inventory_balances (product_id, stock_type, sku, on_hand_qty, total_value, updated_at)
                    VALUES (?, ?, ?, ?, 0.0, ?)
                    """,
                    (prod_id, stock_type, adj["sku"], new_qty, now),
                )

        conn.execute(
            """
            UPDATE inventory_adjustments
            SET status = 'approved', approved_by = ?, approved_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (performed_by, now, now, adjustment_id),
        )
        conn.commit()

    record_erp_audit_log(
        "inventory_adjustment",
        adjustment_id,
        "approve_adjustment",
        {"difference_quantity": diff_qty, "stock_type": stock_type},
        performed_by,
    )
    return get_inventory_adjustment_by_id(adjustment_id)


# ==========================================
# 5. Stock Reservations & Available-to-Promise (ATP)
# ==========================================

def get_product_atp(product_id: str, warehouse_id: str | None = None) -> float:
    """
    Available to Promise = Eligible Available On-Hand Stock - Active Reservations
    (Quarantined, rejected, and in-transit stock are excluded).
    """
    with get_connection() as conn:
        bal = conn.execute(
            "SELECT on_hand_qty FROM inventory_balances WHERE product_id = ? AND stock_type = 'available'",
            (product_id,),
        ).fetchone()
        available_on_hand = float(bal["on_hand_qty"]) if bal else 0.0

        res_clauses = ["product_id = ?", "status = 'active'"]
        res_params: list[Any] = [product_id]
        if warehouse_id:
            res_clauses.append("warehouse_id = ?")
            res_params.append(warehouse_id)

        res_row = conn.execute(
            f"SELECT SUM(quantity) FROM stock_reservations WHERE {' AND '.join(res_clauses)}",
            res_params,
        ).fetchone()
        active_reserved = float(res_row[0]) if res_row and res_row[0] else 0.0

    return max(0.0, round(available_on_hand - active_reserved, 3))


def create_stock_reservation(data: dict[str, Any], performed_by: str = "Local Operator") -> dict[str, Any]:
    prod_id = data.get("product_id")
    wh_id = data.get("warehouse_id")
    loc_id = data.get("location_id")
    qty = float(data.get("quantity", 0.0))
    ref_type = data.get("reference_type", "manual")
    ref_id = data.get("reference_id")
    idempotency_key = data.get("idempotency_key")

    if not prod_id or not wh_id:
        raise HTTPException(status_code=400, detail="Product ID and Warehouse ID are required.")
    if qty <= 0:
        raise HTTPException(status_code=400, detail="Reservation quantity must be positive.")

    wh = get_warehouse_by_id(wh_id)
    if not wh["is_active"]:
        raise HTTPException(status_code=400, detail=f"Cannot reserve stock in inactive warehouse '{wh['code']}'.")

    with get_connection() as conn:
        if idempotency_key:
            existing = conn.execute("SELECT id FROM stock_reservations WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
            if existing:
                return get_stock_reservation_by_id(existing["id"])

        prod = conn.execute("SELECT sku, name, uom, is_active FROM products WHERE id = ?", (prod_id,)).fetchone()
        if not prod:
            raise HTTPException(status_code=400, detail=f"Product '{prod_id}' not found.")
        if not prod["is_active"]:
            raise HTTPException(status_code=400, detail=f"Product '{prod['sku']}' is inactive.")

        # Check ATP
        atp = get_product_atp(prod_id, wh_id)
        if qty > atp:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient available stock for reservation. Available to Promise: {atp}, Requested: {qty}.",
            )

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        date_str = now.strftime("%Y%m%d")

        count_row = conn.execute(
            "SELECT count(*) FROM stock_reservations WHERE reservation_number LIKE ?",
            (f"RES-{date_str}-%",),
        ).fetchone()
        seq = (count_row[0] or 0) + 1
        res_num = f"RES-{date_str}-{seq:04d}"
        res_id = f"res-{uuid.uuid4().hex[:10]}"

        conn.execute(
            """
            INSERT INTO stock_reservations (
                id, reservation_number, idempotency_key, product_id, sku, warehouse_id, location_id,
                quantity, uom, reference_type, reference_id, status, notes, reserved_by, expires_at,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)
            """,
            (
                res_id,
                res_num,
                idempotency_key,
                prod_id,
                prod["sku"],
                wh_id,
                loc_id,
                qty,
                prod["uom"],
                ref_type,
                ref_id,
                data.get("notes"),
                performed_by,
                data.get("expires_at"),
                now_iso,
                now_iso,
            ),
        )
        conn.commit()

    record_erp_audit_log(
        "stock_reservation",
        res_id,
        "create_reservation",
        {"reservation_number": res_num, "quantity": qty},
        performed_by,
    )
    return get_stock_reservation_by_id(res_id)


def get_stock_reservation_by_id(reservation_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT r.*, p.name as product_name, w.code as warehouse_code, l.location_code
            FROM stock_reservations r
            JOIN products p ON r.product_id = p.id
            JOIN warehouses w ON r.warehouse_id = w.id
            LEFT JOIN warehouse_locations l ON r.location_id = l.id
            WHERE r.id = ?
            """,
            (reservation_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Stock reservation '{reservation_id}' not found.")

    return {
        "id": row["id"],
        "reservation_number": row["reservation_number"],
        "idempotency_key": row["idempotency_key"],
        "product_id": row["product_id"],
        "sku": row["sku"],
        "product_name": row["product_name"],
        "warehouse_id": row["warehouse_id"],
        "warehouse_code": row["warehouse_code"],
        "location_id": row["location_id"],
        "location_code": row["location_code"],
        "quantity": float(row["quantity"]),
        "uom": row["uom"],
        "reference_type": row["reference_type"],
        "reference_id": row["reference_id"],
        "status": row["status"],
        "notes": row["notes"],
        "reserved_by": row["reserved_by"],
        "released_by": row["released_by"],
        "consumed_by": row["consumed_by"],
        "expires_at": row["expires_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_stock_reservations(status: str | None = None) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status.strip().lower())

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection() as conn:
        rows = conn.execute(f"SELECT id FROM stock_reservations {where} ORDER BY created_at DESC", params).fetchall()

    return [get_stock_reservation_by_id(r["id"]) for r in rows]


def release_stock_reservation(reservation_id: str, performed_by: str = "Local Operator") -> dict[str, Any]:
    res = get_stock_reservation_by_id(reservation_id)
    if res["status"] != "active":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot release reservation in '{res['status']}' status (must be active).",
        )

    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE stock_reservations SET status = 'released', released_by = ?, updated_at = ? WHERE id = ?",
            (performed_by, now, reservation_id),
        )
        conn.commit()

    record_erp_audit_log("stock_reservation", reservation_id, "release_reservation", {}, performed_by)
    return get_stock_reservation_by_id(reservation_id)


def consume_stock_reservation(reservation_id: str, performed_by: str = "Local Operator") -> dict[str, Any]:
    res = get_stock_reservation_by_id(reservation_id)
    if res["status"] != "active":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot consume reservation in '{res['status']}' status (must be active).",
        )

    now = datetime.now(timezone.utc).isoformat()
    qty = res["quantity"]
    prod_id = res["product_id"]

    with get_connection() as conn:
        # Deduct from available on-hand stock via movement
        bal = conn.execute(
            "SELECT on_hand_qty FROM inventory_balances WHERE product_id = ? AND stock_type = 'available'",
            (prod_id,),
        ).fetchone()
        cur_on_hand = float(bal["on_hand_qty"]) if bal else 0.0

        if cur_on_hand < qty:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot consume reservation: physical on-hand stock ({cur_on_hand}) is less than reservation quantity ({qty}).",
            )

        mov_id = f"mov-{uuid.uuid4().hex[:10]}"
        mov_num = f"MOV-{uuid.uuid4().hex[:8].upper()}"
        mov_key = f"res-consume-{reservation_id}"

        conn.execute(
            """
            INSERT INTO inventory_movements (
                id, movement_number, idempotency_key, movement_type, reference_doc_type,
                reference_doc_id, product_id, sku, quantity, stock_type, warehouse_id, location_id,
                performed_by, notes, created_at
            ) VALUES (?, ?, ?, 'RESERVATION_CONSUME', 'stock_reservation', ?, ?, ?, ?, 'available', ?, ?, ?, ?, ?)
            """,
            (
                mov_id,
                mov_num,
                mov_key,
                reservation_id,
                prod_id,
                res["sku"],
                -qty,
                res["warehouse_id"],
                res["location_id"],
                performed_by,
                f"Consumed by reservation {res['reservation_number']}",
                now,
            ),
        )

        conn.execute(
            "UPDATE inventory_balances SET on_hand_qty = ?, updated_at = ? WHERE product_id = ? AND stock_type = 'available'",
            (cur_on_hand - qty, now, prod_id),
        )

        conn.execute(
            "UPDATE stock_reservations SET status = 'consumed', consumed_by = ?, updated_at = ? WHERE id = ?",
            (performed_by, now, reservation_id),
        )
        conn.commit()

    record_erp_audit_log("stock_reservation", reservation_id, "consume_reservation", {"quantity": qty}, performed_by)
    return get_stock_reservation_by_id(reservation_id)


# ==========================================
# 6. Reports & Stock Reconciliation
# ==========================================

def get_product_stock_balances_report(is_low_stock: bool | None = None) -> list[dict[str, Any]]:
    with get_connection() as conn:
        products = conn.execute("SELECT id, sku, name, uom FROM products ORDER BY sku ASC").fetchall()

        results = []
        for p in products:
            p_id = p["id"]

            # Query balances by stock_type
            b_rows = conn.execute(
                "SELECT stock_type, on_hand_qty FROM inventory_balances WHERE product_id = ?",
                (p_id,),
            ).fetchall()
            b_map = {r["stock_type"]: float(r["on_hand_qty"]) for r in b_rows}

            avail = b_map.get("available", 0.0)
            quar = b_map.get("quarantined", 0.0)
            rej = b_map.get("rejected", 0.0)
            in_transit = b_map.get("in_transit", 0.0)

            # Active reservations
            res_row = conn.execute(
                "SELECT SUM(quantity) FROM stock_reservations WHERE product_id = ? AND status = 'active'",
                (p_id,),
            ).fetchone()
            reserved = float(res_row[0]) if res_row and res_row[0] else 0.0

            atp = max(0.0, round(avail - reserved, 3))
            on_hand = round(avail + quar + rej, 3)

            reorder_threshold = 10.0  # default threshold
            low_stock = atp <= reorder_threshold

            if is_low_stock is not None and low_stock != is_low_stock:
                continue

            results.append({
                "product_id": p_id,
                "sku": p["sku"],
                "product_name": p["name"],
                "uom": p["uom"],
                "on_hand_qty": on_hand,
                "available_qty": avail,
                "reserved_qty": reserved,
                "available_to_promise": atp,
                "quarantined_qty": quar,
                "rejected_qty": rej,
                "in_transit_qty": in_transit,
                "reorder_threshold": reorder_threshold,
                "is_low_stock": low_stock,
            })

    return results


def get_warehouse_stock_breakdown(warehouse_id: str | None = None) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if warehouse_id:
        clauses.append("w.id = ?")
        params.append(warehouse_id)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    query = f"""
        SELECT w.id as warehouse_id, w.code as warehouse_code, w.name as warehouse_name,
               l.id as location_id, l.location_code,
               p.id as product_id, p.sku, p.name as product_name, p.uom,
               b.stock_type, b.on_hand_qty
        FROM location_inventory_balances b
        JOIN warehouses w ON b.warehouse_id = w.id
        LEFT JOIN warehouse_locations l ON b.location_id = l.id
        JOIN products p ON b.product_id = p.id
        {where}
        ORDER BY w.code ASC, p.sku ASC
    """
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    return [
        {
            "warehouse_id": r["warehouse_id"],
            "warehouse_code": r["warehouse_code"],
            "warehouse_name": r["warehouse_name"],
            "location_id": r["location_id"],
            "location_code": r["location_code"],
            "product_id": r["product_id"],
            "sku": r["sku"],
            "product_name": r["product_name"],
            "stock_type": r["stock_type"],
            "on_hand_qty": float(r["on_hand_qty"]),
            "uom": r["uom"],
        }
        for r in rows
    ]


def reconcile_inventory_ledger() -> dict[str, Any]:
    """
    Reconciles inventory_balances against sum of inventory_movements for every product and stock_type.
    """
    with get_connection() as conn:
        products = conn.execute("SELECT id, sku FROM products ORDER BY sku ASC").fetchall()
        stock_types = ["available", "quarantined", "rejected", "in_transit"]

        reconciliation_items = []
        discrepancies_found = 0

        for p in products:
            p_id = p["id"]
            sku = p["sku"]

            for st in stock_types:
                # Sum of ledger movements
                mov_row = conn.execute(
                    "SELECT SUM(quantity) FROM inventory_movements WHERE product_id = ? AND stock_type = ?",
                    (p_id, st),
                ).fetchone()
                ledger_sum = round(float(mov_row[0]), 3) if mov_row and mov_row[0] is not None else 0.0

                # Materialized balance
                bal_row = conn.execute(
                    "SELECT on_hand_qty FROM inventory_balances WHERE product_id = ? AND stock_type = ?",
                    (p_id, st),
                ).fetchone()
                bal_qty = round(float(bal_row[0]), 3) if bal_row and bal_row[0] is not None else 0.0

                diff = round(bal_qty - ledger_sum, 3)
                is_reconciled = (diff == 0.0)
                if not is_reconciled:
                    discrepancies_found += 1

                # Only include in report if there is non-zero ledger activity or balance
                if ledger_sum != 0.0 or bal_qty != 0.0 or not is_reconciled:
                    reconciliation_items.append({
                        "product_id": p_id,
                        "sku": sku,
                        "stock_type": st,
                        "balance_on_hand": bal_qty,
                        "ledger_sum_qty": ledger_sum,
                        "discrepancy": diff,
                        "is_reconciled": is_reconciled,
                    })

    return {
        "is_fully_reconciled": (discrepancies_found == 0),
        "total_checked": len(reconciliation_items),
        "discrepancies_found": discrepancies_found,
        "items": reconciliation_items,
    }


# ==========================================
# 7. FastAPI Endpoints
# ==========================================

@router.get("/warehouses", response_model=WarehouseListResponse)
def get_warehouses_endpoint(
    is_active: bool | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    items = list_warehouses(is_active)
    return {"total": len(items), "items": items}


@router.post("/warehouses", response_model=WarehouseResponse, status_code=201)
def create_warehouse_endpoint(
    req: WarehouseCreateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "create_warehouse")
    return create_warehouse(req.model_dump(), current_user.username)


@router.get("/warehouses/{warehouse_id}", response_model=WarehouseResponse)
def get_warehouse_endpoint(
    warehouse_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    return get_warehouse_by_id(warehouse_id)


@router.patch("/warehouses/{warehouse_id}", response_model=WarehouseResponse)
def update_warehouse_endpoint(
    warehouse_id: str,
    req: WarehouseUpdateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "update_warehouse")
    return update_warehouse(warehouse_id, req.model_dump(exclude_unset=True), current_user.username)


@router.get("/warehouse-locations", response_model=WarehouseLocationListResponse)
def get_warehouse_locations_endpoint(
    warehouse_id: str | None = None,
    is_active: bool | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    items = list_warehouse_locations(warehouse_id, is_active)
    return {"total": len(items), "items": items}


@router.post("/warehouse-locations", response_model=WarehouseLocationResponse, status_code=201)
def create_warehouse_location_endpoint(
    req: WarehouseLocationCreateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "create_location")
    return create_warehouse_location(req.model_dump(), current_user.username)


@router.patch("/warehouse-locations/{location_id}", response_model=WarehouseLocationResponse)
def update_warehouse_location_endpoint(
    location_id: str,
    req: WarehouseLocationUpdateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "update_location")
    return update_warehouse_location(location_id, req.model_dump(exclude_unset=True), current_user.username)


# Stock Transfers
@router.get("/inventory/transfers", response_model=StockTransferListResponse)
def list_stock_transfers_endpoint(
    status: str | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    items = list_stock_transfers(status)
    return {"total": len(items), "items": items}


@router.post("/inventory/transfers", response_model=StockTransferResponse, status_code=201)
def create_stock_transfer_endpoint(
    req: StockTransferCreateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "create_transfer")
    return create_stock_transfer(req.model_dump(), current_user.username)


@router.get("/inventory/transfers/{transfer_id}", response_model=StockTransferResponse)
def get_stock_transfer_endpoint(
    transfer_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    return get_stock_transfer_by_id(transfer_id)


@router.post("/inventory/transfers/{transfer_id}/approve", response_model=StockTransferResponse)
def approve_stock_transfer_endpoint(
    transfer_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "approve_transfer")
    return approve_stock_transfer(transfer_id, current_user.username)


@router.post("/inventory/transfers/{transfer_id}/dispatch", response_model=StockTransferResponse)
def dispatch_stock_transfer_endpoint(
    transfer_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "dispatch_transfer")
    return dispatch_stock_transfer(transfer_id, current_user.username)


@router.post("/inventory/transfers/{transfer_id}/receive", response_model=StockTransferResponse)
def receive_stock_transfer_endpoint(
    transfer_id: str,
    req: StockTransferReceiveRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "receive_transfer")
    return receive_stock_transfer(transfer_id, req.model_dump(), current_user.username)


@router.post("/inventory/transfers/{transfer_id}/cancel", response_model=StockTransferResponse)
def cancel_stock_transfer_endpoint(
    transfer_id: str,
    reason: str = Query("Cancelled by user"),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "cancel_transfer")
    return cancel_stock_transfer(transfer_id, reason, current_user.username)


# Inventory Adjustments
@router.get("/inventory/adjustments", response_model=InventoryAdjustmentListResponse)
def list_inventory_adjustments_endpoint(
    status: str | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    items = list_inventory_adjustments(status)
    return {"total": len(items), "items": items}


@router.post("/inventory/adjustments", response_model=InventoryAdjustmentResponse, status_code=201)
def create_inventory_adjustment_endpoint(
    req: InventoryAdjustmentCreateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "create_adjustment")
    return create_inventory_adjustment(req.model_dump(), current_user.username)


@router.get("/inventory/adjustments/{adjustment_id}", response_model=InventoryAdjustmentResponse)
def get_inventory_adjustment_endpoint(
    adjustment_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    return get_inventory_adjustment_by_id(adjustment_id)


@router.post("/inventory/adjustments/{adjustment_id}/approve", response_model=InventoryAdjustmentResponse)
def approve_inventory_adjustment_endpoint(
    adjustment_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "approve_adjustment")
    return approve_inventory_adjustment(adjustment_id, current_user.username)


# Stock Reservations
@router.get("/inventory/reservations", response_model=StockReservationListResponse)
def list_stock_reservations_endpoint(
    status: str | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    items = list_stock_reservations(status)
    return {"total": len(items), "items": items}


@router.post("/inventory/reservations", response_model=StockReservationResponse, status_code=201)
def create_stock_reservation_endpoint(
    req: StockReservationCreateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "create_reservation")
    return create_stock_reservation(req.model_dump(), current_user.username)


@router.get("/inventory/reservations/{reservation_id}", response_model=StockReservationResponse)
def get_stock_reservation_endpoint(
    reservation_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    return get_stock_reservation_by_id(reservation_id)


@router.post("/inventory/reservations/{reservation_id}/release", response_model=StockReservationResponse)
def release_stock_reservation_endpoint(
    reservation_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "release_reservation")
    return release_stock_reservation(reservation_id, current_user.username)


@router.post("/inventory/reservations/{reservation_id}/consume", response_model=StockReservationResponse)
def consume_stock_reservation_endpoint(
    reservation_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "consume_reservation")
    return consume_stock_reservation(reservation_id, current_user.username)


# Reports
@router.get("/inventory/reports/balances", response_model=ProductStockBalanceReportResponse)
def get_product_balances_report_endpoint(
    is_low_stock: bool | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    items = get_product_stock_balances_report(is_low_stock)
    return {"total": len(items), "items": items}


@router.get("/inventory/reports/by-warehouse", response_model=WarehouseStockReportResponse)
def get_warehouse_stock_report_endpoint(
    warehouse_id: str | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    items = get_warehouse_stock_breakdown(warehouse_id)
    return {"total": len(items), "items": items}


@router.get("/inventory/reports/reconciliation", response_model=ReconciliationReportResponse)
def get_reconciliation_report_endpoint(
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    return reconcile_inventory_ledger()
