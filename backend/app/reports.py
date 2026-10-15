"""
TradeSathi AI — Phase 7: Financial Reports & Executive Dashboard Engine
Provides authoritative business analytics and reporting across Sales, Finance, Procurement,
Inventory, and Export Operations with strict RBAC, multi-currency integrity, and CSV formula-injection safeguards.
"""

import csv
from datetime import datetime, timezone
import io
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from app.auth import AuthenticatedUser, get_current_user
from app.db import (
    get_connection,
    get_receivables_aging_data,
    get_gst_outward_supplies_data,
)
from app.master_data import verify_role_permission, record_erp_audit_log

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reports", tags=["Executive Dashboard & Reports"])

EXPORT_COMPLIANCE_DISCLAIMER = (
    "TradeSathi AI Document Readiness Evaluation is an internal operational check and does not "
    "constitute official customs clearance, single-window approval, or regulatory certification."
)

FINANCE_STATUTORY_DISCLAIMER = (
    "TradeSathi AI Financial Reports & GST Summaries are internal trade management documents. "
    "They do not constitute statutory e-invoicing or official GSTN portal filing acknowledgements."
)

PROCUREMENT_COMMITMENT_DISCLAIMER = (
    "Vendor accounts-payable ledger is not active. Purchase order figures represent commercial "
    "purchasing commitments only and do not reflect finalized accounts-payable balances."
)


def sanitize_csv_cell(value: Any) -> str:
    """
    Sanitizes CSV cell against spreadsheet-formula injection (CSV Injection / Formula Injection).
    Prevents execution of formulas in Excel, LibreOffice Calc, and Google Sheets by checking
    whether the raw or stripped cell begins with formula trigger characters (=, +, -, @, |, \\t, \\r, \\n).
    Legitimate numeric floats and integers (e.g. -125.50 or +100) remain numeric.
    """
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    raw = str(value)
    if not raw:
        return ""
    stripped = raw.lstrip()
    if not stripped:
        return ""
    if stripped[0] in ("=", "+", "-", "@", "|") or raw[0] in ("=", "+", "-", "@", "|", "\t", "\r", "\n"):
        try:
            float(stripped)
            return raw
        except ValueError:
            return "'" + raw
    return raw


# =========================================================================
# 1. Executive Dashboard KPIs Endpoint
# =========================================================================

@router.get("/dashboard-kpis", response_model=dict[str, Any])
def get_dashboard_kpis(
    start_date: str | None = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str | None = Query(None, description="End date (YYYY-MM-DD)"),
    customer_id: str | None = Query(None, description="Filter by customer ID"),
    warehouse_id: str | None = Query(None, description="Filter by warehouse ID"),
    currency: str | None = Query(None, description="Filter by currency"),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Returns consolidated executive dashboard metrics across Sales, Finance, Procurement,
    Inventory, and Export Operations using existing authoritative records.
    """
    verify_role_permission(user.role, "view_dashboard")
    now_iso = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        conn.row_factory = None

        # -------------------------------------------------------------
        # 1. SALES METRICS
        # -------------------------------------------------------------
        so_where = ["1=1"]
        so_params: list[Any] = []
        if start_date:
            so_where.append("order_date >= ?")
            so_params.append(start_date)
        if end_date:
            so_where.append("order_date <= ?")
            so_params.append(end_date)
        if customer_id:
            so_where.append("customer_id = ?")
            so_params.append(customer_id)
        if currency:
            so_where.append("currency = ?")
            so_params.append(currency)

        so_clause = " AND ".join(so_where)

        # Confirmed sales orders by currency
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT currency, COALESCE(SUM(grand_total), 0.0), COUNT(*)
            FROM sales_orders
            WHERE status IN ('confirmed', 'allocated', 'dispatched', 'delivered') AND {so_clause}
            GROUP BY currency
            """,
            so_params,
        )
        confirmed_by_currency = {
            r[0]: {"total_value": round(float(r[1]), 2), "order_count": int(r[2])}
            for r in cur.fetchall()
        }

        # Cancelled sales orders
        cur.execute(
            f"""
            SELECT COUNT(*), COALESCE(SUM(grand_total), 0.0)
            FROM sales_orders
            WHERE status = 'cancelled' AND {so_clause}
            """,
            so_params,
        )
        can_res = cur.fetchone()
        cancelled_orders_count = int(can_res[0]) if can_res else 0
        cancelled_orders_value = round(float(can_res[1]), 2) if can_res else 0.0

        # Ordered, Fulfilled and Outstanding Quantities from lines
        sol_query = f"""
            SELECT
                COALESCE(SUM(sol.ordered_quantity), 0.0),
                COALESCE(SUM(sol.dispatched_quantity), 0.0),
                COALESCE(SUM(MAX(0, sol.ordered_quantity - sol.delivered_quantity)), 0.0)
            FROM sales_order_items sol
            JOIN sales_orders so ON so.id = sol.sales_order_id
            WHERE so.status != 'cancelled' AND {so_clause}
        """
        cur.execute(sol_query, so_params)
        sol_res = cur.fetchone()
        total_ordered_qty = round(float(sol_res[0]), 2) if sol_res else 0.0
        fulfilled_qty = round(float(sol_res[1]), 2) if sol_res else 0.0
        outstanding_qty = round(float(sol_res[2]), 2) if sol_res else 0.0

        sales_kpis = {
            "confirmed_orders_by_currency": confirmed_by_currency,
            "total_ordered_qty": total_ordered_qty,
            "fulfilled_qty": fulfilled_qty,
            "outstanding_qty": outstanding_qty,
            "cancelled_orders_count": cancelled_orders_count,
            "cancelled_orders_value": cancelled_orders_value,
        }

        # -------------------------------------------------------------
        # 2. FINANCE METRICS
        # -------------------------------------------------------------
        can_view_finance = True
        try:
            verify_role_permission(user.role, "view_financial_reports")
        except HTTPException:
            can_view_finance = False

        if can_view_finance:
            inv_where = ["1=1"]
            inv_params: list[Any] = []
            if start_date:
                inv_where.append("invoice_date >= ?")
                inv_params.append(start_date)
            if end_date:
                inv_where.append("invoice_date <= ?")
                inv_params.append(end_date)
            if customer_id:
                inv_where.append("customer_id = ?")
                inv_params.append(customer_id)
            if currency:
                inv_where.append("currency = ?")
                inv_params.append(currency)

            inv_clause = " AND ".join(inv_where)

            # Invoices aggregations
            cur.execute(
                f"""
                SELECT
                    COALESCE(SUM(CASE WHEN status IN ('issued', 'partially_paid', 'overdue') THEN outstanding_balance * exchange_rate ELSE 0 END), 0.0),
                    COALESCE(SUM(CASE WHEN status IN ('issued', 'partially_paid', 'paid', 'credited', 'overdue') THEN base_grand_total ELSE 0 END), 0.0),
                    COALESCE(SUM(CASE WHEN status = 'draft' THEN base_grand_total ELSE 0 END), 0.0),
                    COUNT(CASE WHEN status IN ('issued', 'partially_paid', 'overdue') THEN 1 END)
                FROM customer_invoices
                WHERE {inv_clause}
                """,
                inv_params,
            )
            inv_res = cur.fetchone()
            receivables_inr = round(float(inv_res[0]), 2) if inv_res else 0.0
            invoiced_inr = round(float(inv_res[1]), 2) if inv_res else 0.0
            draft_invoiced_inr = round(float(inv_res[2]), 2) if inv_res else 0.0
            open_invoices_count = int(inv_res[3]) if inv_res else 0

            # Receivables breakdown by transaction currency
            cur.execute(
                f"""
                SELECT currency, COALESCE(SUM(outstanding_balance), 0.0), COUNT(*)
                FROM customer_invoices
                WHERE status IN ('issued', 'partially_paid', 'overdue') AND {inv_clause}
                GROUP BY currency
                """,
                inv_params,
            )
            receivables_by_currency = {
                r[0]: {"balance_due": round(float(r[1]), 2), "open_invoices": int(r[2])}
                for r in cur.fetchall()
            }

            # Payments
            pay_where = ["status = 'posted'"]
            pay_params: list[Any] = []
            if start_date:
                pay_where.append("payment_date >= ?")
                pay_params.append(start_date)
            if end_date:
                pay_where.append("payment_date <= ?")
                pay_params.append(end_date)
            if customer_id:
                pay_where.append("customer_id = ?")
                pay_params.append(customer_id)
            if currency:
                pay_where.append("currency = ?")
                pay_params.append(currency)
            pay_clause = " AND ".join(pay_where)

            cur.execute(
                f"""
                SELECT
                    COALESCE(SUM(amount * exchange_rate), 0.0),
                    COALESCE(SUM(unallocated_amount * exchange_rate), 0.0),
                    COUNT(*)
                FROM customer_payments
                WHERE {pay_clause}
                """,
                pay_params,
            )
            pay_res = cur.fetchone()
            collected_inr = round(float(pay_res[0]), 2) if pay_res else 0.0
            unallocated_credits_inr = round(float(pay_res[1]), 2) if pay_res else 0.0
            payments_count = int(pay_res[2]) if pay_res else 0

            # Credit notes
            crn_where = ["1=1"]
            crn_params: list[Any] = []
            if start_date:
                crn_where.append("credit_note_date >= ?")
                crn_params.append(start_date)
            if end_date:
                crn_where.append("credit_note_date <= ?")
                crn_params.append(end_date)
            if customer_id:
                crn_where.append("customer_id = ?")
                crn_params.append(customer_id)
            crn_clause = " AND ".join(crn_where)

            cur.execute(
                f"""
                SELECT COALESCE(SUM(grand_total * exchange_rate), 0.0), COUNT(*)
                FROM customer_credit_notes
                WHERE {crn_clause}
                """,
                crn_params,
            )
            crn_res = cur.fetchone()
            credit_notes_inr = round(float(crn_res[0]), 2) if crn_res else 0.0
            credit_notes_count = int(crn_res[1]) if crn_res else 0

            # Realized FX Differences
            cur.execute(
                """
                SELECT COALESCE(SUM(realized_gain_loss), 0.0)
                FROM customer_payment_allocations
                """
            )
            fx_res = cur.fetchone()
            realized_fx_inr = round(float(fx_res[0]), 2) if fx_res else 0.0

            # Receivables Aging Summary
            aging_data = get_receivables_aging_data(as_of_date=end_date)
            aging_summary = aging_data.get("buckets", {})

            finance_kpis = {
                "restricted": False,
                "issued_receivables_base_inr": receivables_inr,
                "receivables_by_currency": receivables_by_currency,
                "total_invoiced_base_inr": invoiced_inr,
                "draft_invoiced_base_inr": draft_invoiced_inr,
                "open_invoices_count": open_invoices_count,
                "collected_payments_base_inr": collected_inr,
                "unallocated_credits_base_inr": unallocated_credits_inr,
                "payments_count": payments_count,
                "credit_notes_base_inr": credit_notes_inr,
                "credit_notes_count": credit_notes_count,
                "realized_fx_diff_inr": realized_fx_inr,
                "receivables_aging_buckets": aging_summary,
                "statutory_notice": FINANCE_STATUTORY_DISCLAIMER,
            }
        else:
            finance_kpis = {
                "restricted": True,
                "message": "Financial report access requires Manager or Admin permissions.",
            }

        # -------------------------------------------------------------
        # 3. PROCUREMENT METRICS
        # -------------------------------------------------------------
        po_where = ["status IN ('submitted', 'approved', 'partial_receipt')"]
        po_params: list[Any] = []
        if start_date:
            po_where.append("order_date >= ?")
            po_params.append(start_date)
        if end_date:
            po_where.append("order_date <= ?")
            po_params.append(end_date)
        po_clause = " AND ".join(po_where)

        cur.execute(
            f"""
            SELECT currency, COALESCE(SUM(grand_total), 0.0), COUNT(*)
            FROM purchase_orders
            WHERE {po_clause}
            GROUP BY currency
            """,
            po_params,
        )
        po_commitments_by_currency = {
            r[0]: {"commitment_value": round(float(r[1]), 2), "po_count": int(r[2])}
            for r in cur.fetchall()
        }

        # Pending receipt items
        cur.execute(
            f"""
            SELECT COALESCE(SUM(MAX(0, poi.ordered_qty - poi.received_qty)), 0.0)
            FROM purchase_order_items poi
            JOIN purchase_orders po ON po.id = poi.po_id
            WHERE {po_clause}
            """,
            po_params,
        )
        poi_res = cur.fetchone()
        pending_receipt_qty = round(float(poi_res[0]), 2) if poi_res else 0.0

        procurement_kpis = {
            "active_commitments_by_currency": po_commitments_by_currency,
            "pending_receipt_qty": pending_receipt_qty,
            "supplier_balance_status": "NOT_CONFIGURED",
            "supplier_balance_notice": PROCUREMENT_COMMITMENT_DISCLAIMER,
        }

        # -------------------------------------------------------------
        # 4. INVENTORY METRICS
        # -------------------------------------------------------------
        cur.execute(
            """
            SELECT stock_type, COALESCE(SUM(on_hand_qty), 0.0), COALESCE(SUM(total_value), 0.0)
            FROM inventory_balances
            GROUP BY stock_type
            """
        )
        inv_stock_dict = {
            r[0]: {"quantity": round(float(r[1]), 2), "value": round(float(r[2]), 2)}
            for r in cur.fetchall()
        }

        # Active reservations
        cur.execute(
            """
            SELECT COALESCE(SUM(quantity), 0.0), COUNT(*)
            FROM stock_reservations
            WHERE status = 'active'
            """
        )
        res_res = cur.fetchone()
        reserved_qty = round(float(res_res[0]), 2) if res_res else 0.0
        active_reservations_count = int(res_res[1]) if res_res else 0

        # Low stock products count
        cur.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT p.id, p.reorder_level,
                       COALESCE(SUM(CASE WHEN ib.stock_type = 'available' THEN ib.on_hand_qty ELSE 0 END), 0.0) -
                       COALESCE((SELECT SUM(quantity) FROM stock_reservations WHERE product_id = p.id AND status = 'active'), 0.0) AS net_available
                FROM products p
                LEFT JOIN inventory_balances ib ON ib.product_id = p.id
                WHERE p.is_active = 1 AND p.reorder_level > 0
                GROUP BY p.id, p.reorder_level
                HAVING net_available <= p.reorder_level
            )
            """
        )
        low_res = cur.fetchone()
        low_stock_products_count = int(low_res[0]) if low_res else 0

        inventory_kpis = {
            "available_qty": inv_stock_dict.get("available", {}).get("quantity", 0.0),
            "reserved_qty": reserved_qty,
            "active_reservations_count": active_reservations_count,
            "quarantined_qty": inv_stock_dict.get("quarantined", {}).get("quantity", 0.0),
            "rejected_qty": inv_stock_dict.get("rejected", {}).get("quantity", 0.0),
            "in_transit_qty": inv_stock_dict.get("in_transit", {}).get("quantity", 0.0),
            "low_stock_products_count": low_stock_products_count,
        }

        # -------------------------------------------------------------
        # 5. EXPORT OPERATIONS METRICS
        # -------------------------------------------------------------
        cur.execute(
            """
            SELECT status, COUNT(*)
            FROM shipments
            GROUP BY status
            """
        )
        shipments_by_status = {r[0]: int(r[1]) for r in cur.fetchall()}

        cur.execute(
            """
            SELECT readiness_status, COUNT(*)
            FROM shipments
            GROUP BY readiness_status
            """
        )
        readiness_breakdown = {r[0]: int(r[1]) for r in cur.fetchall()}

        blocked_shipments_count = readiness_breakdown.get("blocked", 0)

        # Document review backlog
        cur.execute(
            """
            SELECT COUNT(*)
            FROM export_shipment_checklist_items
            WHERE status IN ('pending', 'missing', 'under_review', 'needs_confirmation')
            """
        )
        backlog_res = cur.fetchone()
        document_backlog_count = int(backlog_res[0]) if backlog_res else 0

        cur.execute("SELECT COUNT(*) FROM shipments")
        total_shipments_count = int(cur.fetchone()[0])

        export_kpis = {
            "total_shipments_count": total_shipments_count,
            "shipments_by_workflow_status": shipments_by_status,
            "readiness_breakdown": readiness_breakdown,
            "blocked_shipments_count": blocked_shipments_count,
            "document_backlog_count": document_backlog_count,
            "compliance_disclaimer": EXPORT_COMPLIANCE_DISCLAIMER,
        }

    return {
        "metadata": {
            "last_refreshed_at": now_iso,
            "calculation_basis": "Authoritative transactional ledger snapshot using transaction exchange rates",
            "reporting_currency": "INR",
            "applied_filters": {
                "start_date": start_date,
                "end_date": end_date,
                "customer_id": customer_id,
                "warehouse_id": warehouse_id,
                "currency": currency,
            },
        },
        "sales": sales_kpis,
        "finance": finance_kpis,
        "procurement": procurement_kpis,
        "inventory": inventory_kpis,
        "exports": export_kpis,
    }


# =========================================================================
# 2. Detailed Sales Report
# =========================================================================

@router.get("/sales", response_model=dict[str, Any])
def get_sales_report(
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    customer_id: str | None = Query(None),
    product_id: str | None = Query(None),
    status: str | None = Query(None),
    currency: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Detailed paginated sales report with customer and product breakdowns."""
    verify_role_permission(user.role, "view_dashboard")

    where = ["1=1"]
    params: list[Any] = []
    if start_date:
        where.append("so.order_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("so.order_date <= ?")
        params.append(end_date)
    if customer_id:
        where.append("so.customer_id = ?")
        params.append(customer_id)
    if status:
        where.append("so.status = ?")
        params.append(status)
    if currency:
        where.append("so.currency = ?")
        params.append(currency)

    clause = " AND ".join(where)

    with get_connection() as conn:
        conn.row_factory = None
        cur = conn.cursor()

        # Count total matching orders
        cur.execute(f"SELECT COUNT(*) FROM sales_orders so WHERE {clause}", params)
        total_records = cur.fetchone()[0]

        # Paginated orders list
        offset = (page - 1) * page_size
        paginated_params = params + [page_size, offset]
        cur.execute(
            f"""
            SELECT
                so.id, so.order_number, so.customer_name, so.order_date,
                so.currency, so.subtotal, so.tax_total, so.grand_total,
                so.status, so.created_at
            FROM sales_orders so
            WHERE {clause}
            ORDER BY so.order_date DESC, so.created_at DESC
            LIMIT ? OFFSET ?
            """,
            paginated_params,
        )
        orders = [
            {
                "id": r[0],
                "order_number": r[1],
                "customer_name": r[2],
                "order_date": r[3],
                "currency": r[4],
                "subtotal": round(float(r[5]), 2),
                "tax_total": round(float(r[6]), 2),
                "grand_total": round(float(r[7]), 2),
                "status": r[8],
                "created_at": r[9],
            }
            for r in cur.fetchall()
        ]

        # Customer Sales Breakdown
        cur.execute(
            f"""
            SELECT so.customer_name, so.currency, SUM(so.grand_total), COUNT(*)
            FROM sales_orders so
            WHERE so.status != 'cancelled' AND {clause}
            GROUP BY so.customer_name, so.currency
            ORDER BY SUM(so.grand_total) DESC
            LIMIT 10
            """,
            params,
        )
        customer_breakdown = [
            {
                "customer_name": r[0],
                "currency": r[1],
                "total_order_value": round(float(r[2]), 2),
                "order_count": int(r[3]),
            }
            for r in cur.fetchall()
        ]

        # Product Sales Breakdown
        cur.execute(
            f"""
            SELECT sol.product_sku, sol.product_id, SUM(sol.ordered_quantity), SUM(sol.line_total)
            FROM sales_order_items sol
            JOIN sales_orders so ON so.id = sol.sales_order_id
            WHERE so.status != 'cancelled' AND {clause}
            GROUP BY sol.product_sku, sol.product_id
            ORDER BY SUM(sol.ordered_quantity) DESC
            LIMIT 10
            """,
            params,
        )
        product_breakdown = [
            {
                "sku": r[0],
                "product_id": r[1],
                "total_quantity": round(float(r[2]), 2),
                "total_sales_value": round(float(r[3]), 2),
            }
            for r in cur.fetchall()
        ]

    return {
        "page": page,
        "page_size": page_size,
        "total_records": total_records,
        "total_pages": (total_records + page_size - 1) // page_size if total_records else 1,
        "orders": orders,
        "top_customers": customer_breakdown,
        "top_products": product_breakdown,
    }


# =========================================================================
# 3. Detailed Finance & Receivables Report
# =========================================================================

@router.get("/finance", response_model=dict[str, Any])
def get_finance_report(
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    customer_id: str | None = Query(None),
    status: str | None = Query(None),
    currency: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Detailed financial report including invoice register, aging, payments, and GST summaries."""
    verify_role_permission(user.role, "view_financial_reports")

    aging_data = get_receivables_aging_data(as_of_date=end_date)
    gst_data = get_gst_outward_supplies_data(from_date=start_date, to_date=end_date)

    where = ["1=1"]
    params: list[Any] = []
    if start_date:
        where.append("ci.invoice_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("ci.invoice_date <= ?")
        params.append(end_date)
    if customer_id:
        where.append("ci.customer_id = ?")
        params.append(customer_id)
    if status:
        where.append("ci.status = ?")
        params.append(status)
    if currency:
        where.append("ci.currency = ?")
        params.append(currency)

    clause = " AND ".join(where)

    with get_connection() as conn:
        conn.row_factory = None
        cur = conn.cursor()

        cur.execute(f"SELECT COUNT(*) FROM customer_invoices ci WHERE {clause}", params)
        total_invoices = cur.fetchone()[0]

        offset = (page - 1) * page_size
        paginated_params = params + [page_size, offset]
        cur.execute(
            f"""
            SELECT
                ci.id, ci.invoice_number, ci.customer_name, ci.invoice_date,
                ci.due_date, ci.currency, ci.exchange_rate, ci.subtotal,
                ci.tax_total, ci.grand_total, ci.base_grand_total,
                ci.amount_paid, ci.outstanding_balance, ci.status
            FROM customer_invoices ci
            WHERE {clause}
            ORDER BY ci.invoice_date DESC, ci.created_at DESC
            LIMIT ? OFFSET ?
            """,
            paginated_params,
        )
        invoices = [
            {
                "id": r[0],
                "invoice_number": r[1],
                "customer_name": r[2],
                "invoice_date": r[3],
                "due_date": r[4],
                "currency": r[5],
                "exchange_rate": float(r[6]),
                "subtotal": round(float(r[7]), 2),
                "tax_total": round(float(r[8]), 2),
                "grand_total": round(float(r[9]), 2),
                "grand_total_base_inr": round(float(r[10]), 2),
                "amount_paid": round(float(r[11]), 2),
                "balance_due": round(float(r[12]), 2),
                "status": r[13],
            }
            for r in cur.fetchall()
        ]

    return {
        "page": page,
        "page_size": page_size,
        "total_invoices": total_invoices,
        "total_pages": (total_invoices + page_size - 1) // page_size if total_invoices else 1,
        "invoices": invoices,
        "receivables_aging": aging_data,
        "gst_outward_supplies": gst_data,
        "statutory_notice": FINANCE_STATUTORY_DISCLAIMER,
    }


# =========================================================================
# 4. Detailed Inventory Report
# =========================================================================

@router.get("/inventory", response_model=dict[str, Any])
def get_inventory_report(
    warehouse_id: str | None = Query(None),
    low_stock_only: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Detailed inventory status by stock type, warehouse distribution, and low stock monitoring."""
    verify_role_permission(user.role, "view_dashboard")

    with get_connection() as conn:
        conn.row_factory = None
        cur = conn.cursor()

        # Stock by warehouse
        cur.execute(
            """
            SELECT w.id, w.name, w.code,
                   COALESCE(SUM(lib.on_hand_qty), 0.0),
                   COALESCE(SUM(lib.total_value), 0.0)
            FROM warehouses w
            LEFT JOIN location_inventory_balances lib ON lib.warehouse_id = w.id
            WHERE w.is_active = 1
            GROUP BY w.id, w.name, w.code
            ORDER BY w.name ASC
            """
        )
        warehouse_summary = [
            {
                "warehouse_id": r[0],
                "warehouse_name": r[1],
                "warehouse_code": r[2],
                "total_on_hand_qty": round(float(r[3]), 2),
                "total_stock_value": round(float(r[4]), 2),
            }
            for r in cur.fetchall()
        ]

        # Products with stock balances and reorder levels
        prod_where = ["p.is_active = 1"]
        prod_params: list[Any] = []
        if low_stock_only:
            prod_where.append(
                """
                (COALESCE((SELECT SUM(on_hand_qty) FROM inventory_balances WHERE product_id = p.id AND stock_type = 'available'), 0.0) -
                 COALESCE((SELECT SUM(quantity) FROM stock_reservations WHERE product_id = p.id AND status = 'active'), 0.0)) <= p.reorder_level
                AND p.reorder_level > 0
                """
            )

        prod_clause = " AND ".join(prod_where)

        cur.execute(f"SELECT COUNT(*) FROM products p WHERE {prod_clause}", prod_params)
        total_products = cur.fetchone()[0]

        offset = (page - 1) * page_size
        paginated_params = prod_params + [page_size, offset]
        cur.execute(
            f"""
            SELECT
                p.id, p.sku, p.name, p.category, p.uom,
                p.reorder_level, p.reorder_quantity,
                COALESCE((SELECT SUM(on_hand_qty) FROM inventory_balances WHERE product_id = p.id AND stock_type = 'available'), 0.0) as available_qty,
                COALESCE((SELECT SUM(quantity) FROM stock_reservations WHERE product_id = p.id AND status = 'active'), 0.0) as reserved_qty,
                COALESCE((SELECT SUM(on_hand_qty) FROM inventory_balances WHERE product_id = p.id AND stock_type = 'quarantined'), 0.0) as quarantined_qty,
                COALESCE((SELECT SUM(on_hand_qty) FROM inventory_balances WHERE product_id = p.id AND stock_type = 'rejected'), 0.0) as rejected_qty,
                COALESCE((SELECT SUM(on_hand_qty) FROM inventory_balances WHERE product_id = p.id AND stock_type = 'in_transit'), 0.0) as in_transit_qty
            FROM products p
            WHERE {prod_clause}
            ORDER BY p.sku ASC
            LIMIT ? OFFSET ?
            """,
            paginated_params,
        )
        products = []
        for r in cur.fetchall():
            avail = round(float(r[7]), 2)
            resvd = round(float(r[8]), 2)
            net_avail = round(avail - resvd, 2)
            reorder = round(float(r[5] or 0.0), 2)

            if reorder > 0 and net_avail <= 0:
                health = "CRITICAL"
            elif reorder > 0 and net_avail <= reorder:
                health = "LOW_STOCK"
            else:
                health = "HEALTHY"

            products.append({
                "product_id": r[0],
                "sku": r[1],
                "name": r[2],
                "category": r[3],
                "uom": r[4],
                "reorder_level": reorder,
                "reorder_quantity": round(float(r[6] or 0.0), 2),
                "on_hand_available": avail,
                "reserved_qty": resvd,
                "net_available_qty": net_avail,
                "quarantined_qty": round(float(r[9]), 2),
                "rejected_qty": round(float(r[10]), 2),
                "in_transit_qty": round(float(r[11]), 2),
                "stock_health": health,
            })

    return {
        "page": page,
        "page_size": page_size,
        "total_products": total_products,
        "total_pages": (total_products + page_size - 1) // page_size if total_products else 1,
        "warehouse_summary": warehouse_summary,
        "products": products,
    }


# =========================================================================
# 5. Detailed Export Operations Report
# =========================================================================

@router.get("/exports", response_model=dict[str, Any])
def get_exports_report(
    workflow_status: str | None = Query(None),
    readiness_status: str | None = Query(None),
    destination_country: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Detailed export shipments tracking, readiness verification, and document backlog."""
    verify_role_permission(user.role, "view_dashboard")

    where = ["1=1"]
    params: list[Any] = []
    if workflow_status:
        where.append("s.status = ?")
        params.append(workflow_status)
    if readiness_status:
        where.append("s.readiness_status = ?")
        params.append(readiness_status)
    if destination_country:
        where.append("s.destination_country = ?")
        params.append(destination_country)

    clause = " AND ".join(where)

    with get_connection() as conn:
        conn.row_factory = None
        cur = conn.cursor()

        cur.execute(f"SELECT COUNT(*) FROM shipments s WHERE {clause}", params)
        total_shipments = cur.fetchone()[0]

        offset = (page - 1) * page_size
        paginated_params = params + [page_size, offset]
        cur.execute(
            f"""
            SELECT
                s.id, s.reference, COALESCE(s.exporter_name, s.exporter), COALESCE(s.consignee_name, s.buyer),
                s.destination_country, s.transport_mode, s.status,
                s.readiness_status, s.estimated_departure_date, s.estimated_arrival_date,
                s.package_count, s.gross_weight_kg, s.created_at
            FROM shipments s
            WHERE {clause}
            ORDER BY s.created_at DESC
            LIMIT ? OFFSET ?
            """,
            paginated_params,
        )
        shipments = [
            {
                "id": r[0],
                "reference": r[1],
                "exporter_name": r[2],
                "consignee_name": r[3],
                "destination_country": r[4],
                "transport_mode": r[5],
                "workflow_status": r[6],
                "readiness_status": r[7],
                "estimated_departure_date": r[8],
                "estimated_arrival_date": r[9],
                "package_count": r[10] or 0,
                "gross_weight_kg": round(float(r[11] or 0.0), 2),
                "created_at": r[12],
            }
            for r in cur.fetchall()
        ]

        # Blocked shipments list
        cur.execute(
            """
            SELECT s.id, s.reference, s.destination_country, s.status
            FROM shipments s
            WHERE s.readiness_status = 'blocked'
            ORDER BY s.created_at DESC
            LIMIT 10
            """
        )
        blocked_shipments = [
            {
                "id": r[0],
                "reference": r[1],
                "destination_country": r[2],
                "workflow_status": r[3],
            }
            for r in cur.fetchall()
        ]

    return {
        "page": page,
        "page_size": page_size,
        "total_shipments": total_shipments,
        "total_pages": (total_shipments + page_size - 1) // page_size if total_shipments else 1,
        "shipments": shipments,
        "blocked_shipments": blocked_shipments,
        "compliance_disclaimer": EXPORT_COMPLIANCE_DISCLAIMER,
    }


# =========================================================================
# 6. Secure CSV Export Endpoint with Formula Injection Protection
# =========================================================================

@router.get("/export-csv")
def export_report_csv(
    report_type: str = Query(..., description="Report type: invoices, receivables_aging, inventory_balances, export_shipments, sales_orders"),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    customer_id: str | None = Query(None),
    status: str | None = Query(None),
    currency: str | None = Query(None),
    user: AuthenticatedUser = Depends(get_current_user),
) -> Response:
    """
    Generates downloadable CSV data with strict formula-injection sanitization.
    Requires 'export_reports' permission.
    """
    verify_role_permission(user.role, "export_reports")

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    with get_connection() as conn:
        conn.row_factory = None
        cur = conn.cursor()

        if report_type == "invoices":
            writer.writerow([
                "Invoice Number", "Customer Name", "Invoice Date", "Due Date",
                "Currency", "Exchange Rate", "Subtotal", "Tax Total",
                "Grand Total", "Grand Total Base INR", "Amount Paid", "Balance Due", "Status"
            ])
            where = ["1=1"]
            params: list[Any] = []
            if start_date:
                where.append("invoice_date >= ?")
                params.append(start_date)
            if end_date:
                where.append("invoice_date <= ?")
                params.append(end_date)
            if customer_id:
                where.append("customer_id = ?")
                params.append(customer_id)
            if status:
                where.append("status = ?")
                params.append(status)
            if currency:
                where.append("currency = ?")
                params.append(currency)

            cur.execute(
                f"""
                SELECT invoice_number, customer_name, invoice_date, due_date,
                       currency, exchange_rate, subtotal, tax_total,
                       grand_total, base_grand_total, amount_paid, outstanding_balance, status
                FROM customer_invoices
                WHERE {" AND ".join(where)}
                ORDER BY invoice_date DESC
                """,
                params,
            )
            for row in cur.fetchall():
                writer.writerow([sanitize_csv_cell(c) for c in row])

        elif report_type == "receivables_aging":
            writer.writerow([
                "Customer ID", "Customer Name", "Current (INR)", "Days 1-30 (INR)",
                "Days 31-60 (INR)", "Days 61-90 (INR)", "Days 90+ (INR)", "Total Outstanding (INR)", "Invoices Count"
            ])
            aging_data = get_receivables_aging_data(as_of_date=end_date)
            for c in aging_data.get("customers", []):
                writer.writerow([
                    sanitize_csv_cell(c.get("customer_id")),
                    sanitize_csv_cell(c.get("customer_name")),
                    sanitize_csv_cell(c.get("current")),
                    sanitize_csv_cell(c.get("days_1_30")),
                    sanitize_csv_cell(c.get("days_31_60")),
                    sanitize_csv_cell(c.get("days_61_90")),
                    sanitize_csv_cell(c.get("days_90_plus")),
                    sanitize_csv_cell(c.get("total_outstanding_inr")),
                    sanitize_csv_cell(c.get("invoices_count")),
                ])

        elif report_type == "inventory_balances":
            writer.writerow([
                "SKU", "Product Name", "Category", "UOM", "Reorder Level",
                "Available Qty", "Reserved Qty", "Net Available Qty",
                "Quarantined Qty", "Rejected Qty", "In Transit Qty"
            ])
            cur.execute(
                """
                SELECT
                    p.sku, p.name, p.category, p.uom, p.reorder_level,
                    COALESCE((SELECT SUM(on_hand_qty) FROM inventory_balances WHERE product_id = p.id AND stock_type = 'available'), 0.0) as avail,
                    COALESCE((SELECT SUM(quantity) FROM stock_reservations WHERE product_id = p.id AND status = 'active'), 0.0) as resvd,
                    COALESCE((SELECT SUM(on_hand_qty) FROM inventory_balances WHERE product_id = p.id AND stock_type = 'quarantined'), 0.0) as quar,
                    COALESCE((SELECT SUM(on_hand_qty) FROM inventory_balances WHERE product_id = p.id AND stock_type = 'rejected'), 0.0) as rej,
                    COALESCE((SELECT SUM(on_hand_qty) FROM inventory_balances WHERE product_id = p.id AND stock_type = 'in_transit'), 0.0) as transit
                FROM products p
                WHERE p.is_active = 1
                ORDER BY p.sku ASC
                """
            )
            for row in cur.fetchall():
                avail = float(row[5])
                resvd = float(row[6])
                net_avail = round(avail - resvd, 2)
                row_data = [
                    row[0], row[1], row[2], row[3], row[4],
                    avail, resvd, net_avail, row[7], row[8], row[9]
                ]
                writer.writerow([sanitize_csv_cell(c) for c in row_data])

        elif report_type == "export_shipments":
            writer.writerow([
                "Shipment Reference", "Exporter", "Consignee", "Destination Country",
                "Transport Mode", "Workflow Status", "Readiness Status",
                "Departure Date", "Arrival Date", "Package Count", "Gross Weight (KG)"
            ])
            cur.execute(
                """
                SELECT reference, COALESCE(exporter_name, exporter), COALESCE(consignee_name, buyer), destination_country,
                       transport_mode, status, readiness_status,
                       estimated_departure_date, estimated_arrival_date,
                       package_count, gross_weight_kg
                FROM shipments
                ORDER BY created_at DESC
                """
            )
            for row in cur.fetchall():
                writer.writerow([sanitize_csv_cell(c) for c in row])

        elif report_type == "sales_orders":
            writer.writerow([
                "Order Number", "Customer Name", "Order Date", "Currency",
                "Subtotal", "Tax Total", "Grand Total", "Status"
            ])
            cur.execute(
                """
                SELECT order_number, customer_name, order_date, currency,
                       subtotal, tax_total, grand_total, status
                FROM sales_orders
                ORDER BY order_date DESC
                """
            )
            for row in cur.fetchall():
                writer.writerow([sanitize_csv_cell(c) for c in row])

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported report_type '{report_type}'. Valid types: invoices, receivables_aging, inventory_balances, export_shipments, sales_orders."
            )

    # Log export event in audit log
    record_erp_audit_log(
        entity_type="report_export",
        entity_id=report_type,
        action="csv_exported",
        changes={"report_type": report_type, "filters": {"start_date": start_date, "end_date": end_date, "currency": currency}},
        performed_by=f"{user.email} ({user.role})" if user else "System",
    )

    filename = f"tradesathi_{report_type}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
