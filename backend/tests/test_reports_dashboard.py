"""
TradeSathi AI — Phase 7: Financial Reports & Executive Dashboard Automated Tests
Tests dashboard KPIs, domain reporting, multi-currency integrity, RBAC, and CSV formula-injection defense.
"""

import uuid
import pytest
from fastapi.testclient import TestClient

from app.db import get_connection
from app.main import app

ADMIN_HEADERS = {"X-User-Role": "admin", "X-User-Name": "Admin User", "X-User-Email": "admin@tradesathi.local"}
MANAGER_HEADERS = {"X-User-Role": "manager", "X-User-Name": "Finance Manager", "X-User-Email": "manager@tradesathi.local"}
SALES_HEADERS = {"X-User-Role": "sales", "X-User-Name": "Sales Rep", "X-User-Email": "sales@tradesathi.local"}
WAREHOUSE_HEADERS = {"X-User-Role": "warehouse", "X-User-Name": "Warehouse Ops", "X-User-Email": "wh@tradesathi.local"}
VIEWER_HEADERS = {"X-User-Role": "viewer", "X-User-Name": "Auditor Viewer", "X-User-Email": "viewer@tradesathi.local"}


def create_base_entities():
    cust_id = f"cust-{uuid.uuid4().hex[:6]}"
    cust_code = f"CUST-{uuid.uuid4().hex[:4].upper()}"
    prod_id = f"prod-{uuid.uuid4().hex[:6]}"
    sku = f"SKU-{uuid.uuid4().hex[:4].upper()}"
    wh_id = f"wh-{uuid.uuid4().hex[:6]}"
    wh_code = f"WH-{uuid.uuid4().hex[:4].upper()}"
    now = "2026-10-14T12:00:00Z"

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO customers (id, code, name, legal_name, tax_id, country, billing_address, status, currency, created_at, updated_at)
            VALUES (?, ?, 'Global Exports Inc', 'Global Exports Inc LLC', 'US123456789', 'US', '100 Broadway, New York, NY', 'active', 'USD', ?, ?)
            """,
            (cust_id, cust_code, now, now),
        )
        conn.execute(
            """
            INSERT INTO products (id, sku, name, category, uom, default_selling_price, currency, reorder_level, reorder_quantity, is_active, created_at, updated_at)
            VALUES (?, ?, 'Engineered Valves', 'Machinery', 'PCS', 500.0, 'INR', 20.0, 50.0, 1, ?, ?)
            """,
            (prod_id, sku, now, now),
        )
        conn.execute(
            """
            INSERT INTO warehouses (id, code, name, city, country, is_active, created_at, updated_at)
            VALUES (?, ?, 'Central Logistics Hub', 'Kolkata', 'IN', 1, ?, ?)
            """,
            (wh_id, wh_code, now, now),
        )
        conn.commit()

    return {"cust_id": cust_id, "prod_id": prod_id, "sku": sku, "wh_id": wh_id}


def test_empty_dashboard_kpis_and_metadata():
    """Verify empty database returns structured zeroes without crashing."""
    client = TestClient(app)
    res = client.get("/api/reports/dashboard-kpis", headers=ADMIN_HEADERS)
    assert res.status_code == 200
    data = res.json()

    assert "metadata" in data
    assert data["metadata"]["reporting_currency"] == "INR"
    assert "sales" in data
    assert data["sales"]["total_ordered_qty"] == 0.0
    assert data["sales"]["cancelled_orders_count"] == 0
    assert "finance" in data
    assert data["finance"]["issued_receivables_base_inr"] == 0.0
    assert "procurement" in data
    assert data["procurement"]["pending_receipt_qty"] == 0.0
    assert data["procurement"]["supplier_balance_status"] == "NOT_CONFIGURED"
    assert "inventory" in data
    assert data["inventory"]["available_qty"] == 0.0
    assert "exports" in data
    assert data["exports"]["total_shipments_count"] == 0
    assert "compliance_disclaimer" in data["exports"]


def test_sales_kpis_and_breakdown():
    """Verify confirmed orders, line quantities, cancelled order separation, and sales report."""
    base = create_base_entities()
    now = "2026-10-14T12:00:00Z"
    so_id1 = f"so-{uuid.uuid4().hex[:6]}"
    so_id2 = f"so-{uuid.uuid4().hex[:6]}"
    sol_id1 = f"sol-{uuid.uuid4().hex[:6]}"

    with get_connection() as conn:
        # Confirmed sales order (USD 2,000)
        conn.execute(
            """
            INSERT INTO sales_orders (id, order_number, customer_id, customer_code, customer_name, order_date, currency, subtotal, grand_total, status, created_at, updated_at)
            VALUES (?, 'SO-101', ?, 'CUST-01', 'Global Exports Inc', '2026-10-10', 'USD', 2000.0, 2000.0, 'confirmed', ?, ?)
            """,
            (so_id1, base["cust_id"], now, now),
        )
        # Order line: ordered 10, dispatched 4, delivered 4
        conn.execute(
            """
            INSERT INTO sales_order_items (id, sales_order_id, product_id, product_sku, product_name, ordered_quantity, unit_price, subtotal, line_total, allocated_quantity, dispatched_quantity, delivered_quantity, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'Engineered Valves', 10.0, 200.0, 2000.0, 2000.0, 4.0, 4.0, 4.0, ?, ?)
            """,
            (sol_id1, so_id1, base["prod_id"], base["sku"], now, now),
        )
        # Cancelled sales order (USD 500)
        conn.execute(
            """
            INSERT INTO sales_orders (id, order_number, customer_id, customer_code, customer_name, order_date, currency, subtotal, grand_total, status, created_at, updated_at)
            VALUES (?, 'SO-102', ?, 'CUST-01', 'Global Exports Inc', '2026-10-11', 'USD', 500.0, 500.0, 'cancelled', ?, ?)
            """,
            (so_id2, base["cust_id"], now, now),
        )
        conn.commit()

    client = TestClient(app)
    res = client.get("/api/reports/dashboard-kpis", headers=ADMIN_HEADERS)
    assert res.status_code == 200
    sales = res.json()["sales"]

    assert "USD" in sales["confirmed_orders_by_currency"]
    assert sales["confirmed_orders_by_currency"]["USD"]["total_value"] == 2000.0
    assert sales["total_ordered_qty"] == 10.0
    assert sales["fulfilled_qty"] == 4.0
    assert sales["outstanding_qty"] == 6.0
    assert sales["cancelled_orders_count"] == 1
    assert sales["cancelled_orders_value"] == 500.0

    # Test detailed sales report endpoint
    rep_res = client.get("/api/reports/sales", headers=ADMIN_HEADERS)
    assert rep_res.status_code == 200
    rep_data = rep_res.json()
    assert rep_data["total_records"] >= 2
    assert len(rep_data["top_customers"]) >= 1
    assert len(rep_data["top_products"]) >= 1


def test_finance_kpis_and_receivables_aging():
    """Verify issued receivables, collections, credit notes, FX diffs, and draft invoice exclusion."""
    base = create_base_entities()
    now = "2026-10-14T12:00:00Z"
    inv_id1 = f"inv-{uuid.uuid4().hex[:6]}"
    inv_id_draft = f"inv-{uuid.uuid4().hex[:6]}"
    pay_id1 = f"pay-{uuid.uuid4().hex[:6]}"
    crn_id1 = f"crn-{uuid.uuid4().hex[:6]}"
    alloc_id = f"alloc-{uuid.uuid4().hex[:6]}"

    with get_connection() as conn:
        # Issued Invoice: INR 10,000, paid 2,000, balance 8,000
        conn.execute(
            """
            INSERT INTO customer_invoices (
                id, invoice_number, customer_id, customer_code, customer_name, billing_address, status,
                invoice_date, due_date, currency, exchange_rate, place_of_supply,
                subtotal, grand_total, base_grand_total, amount_paid, outstanding_balance,
                created_by, created_at, updated_at
            ) VALUES (?, 'INV-FIN-01', ?, 'CUST-01', 'Global Exports Inc', '100 Broadway, NY', 'issued',
                      '2026-10-01', '2026-10-15', 'INR', 1.0, '19-West Bengal',
                      10000.0, 10000.0, 10000.0, 2000.0, 8000.0,
                      'usr-op1', ?, ?)
            """,
            (inv_id1, base["cust_id"], now, now),
        )
        # Draft Invoice: INR 5,000 (must be excluded from receivables!)
        conn.execute(
            """
            INSERT INTO customer_invoices (
                id, invoice_number, customer_id, customer_code, customer_name, billing_address, status,
                invoice_date, due_date, currency, exchange_rate, place_of_supply,
                subtotal, grand_total, base_grand_total, amount_paid, outstanding_balance,
                created_by, created_at, updated_at
            ) VALUES (?, 'INV-DRAFT-01', ?, 'CUST-01', 'Global Exports Inc', '100 Broadway, NY', 'draft',
                      '2026-10-02', '2026-10-16', 'INR', 1.0, '19-West Bengal',
                      5000.0, 5000.0, 5000.0, 0.0, 5000.0,
                      'usr-op1', ?, ?)
            """,
            (inv_id_draft, base["cust_id"], now, now),
        )
        # Customer Payment: INR 15,000 (10,000 allocated, 5,000 unallocated)
        conn.execute(
            """
            INSERT INTO customer_payments (id, payment_number, customer_id, customer_name, payment_date, payment_method, currency, exchange_rate, amount, allocated_amount, unallocated_amount, status, created_at, updated_at)
            VALUES (?, 'PAY-FIN-01', ?, 'Global Exports Inc', '2026-10-05', 'bank_transfer', 'INR', 1.0, 15000.0, 10000.0, 5000.0, 'posted', ?, ?)
            """,
            (pay_id1, base["cust_id"], now, now),
        )
        # Payment Allocation with Realized FX Gain (+350.0 INR)
        conn.execute(
            """
            INSERT INTO customer_payment_allocations (id, payment_id, invoice_id, allocated_amount, realized_gain_loss, allocated_at, allocated_by)
            VALUES (?, ?, ?, 2000.0, 350.0, ?, 'usr-op1')
            """,
            (alloc_id, pay_id1, inv_id1, now),
        )
        # Customer Credit Note: INR 1,200
        conn.execute(
            """
            INSERT INTO customer_credit_notes (id, credit_note_number, invoice_id, customer_id, customer_name, credit_note_date, reason, currency, exchange_rate, subtotal, grand_total, created_at, updated_at)
            VALUES (?, 'CRN-FIN-01', ?, ?, 'Global Exports Inc', '2026-10-08', 'pricing_error', 'INR', 1.0, 1200.0, 1200.0, ?, ?)
            """,
            (crn_id1, inv_id1, base["cust_id"], now, now),
        )
        conn.commit()

    client = TestClient(app)
    res = client.get("/api/reports/dashboard-kpis", headers=ADMIN_HEADERS)
    assert res.status_code == 200
    finance = res.json()["finance"]

    assert finance["issued_receivables_base_inr"] == 8000.0  # Draft invoice 5,000 excluded!
    assert finance["draft_invoiced_base_inr"] == 5000.0
    assert finance["collected_payments_base_inr"] == 15000.0
    assert finance["unallocated_credits_base_inr"] == 5000.0
    assert finance["credit_notes_base_inr"] == 1200.0
    assert finance["realized_fx_diff_inr"] == 350.0


def test_finance_report_rbac():
    """Verify financial reports require Manager or Admin permissions and restrict unauthorized roles."""
    client = TestClient(app)

    # Admin and Manager must succeed
    res_admin = client.get("/api/reports/finance", headers=ADMIN_HEADERS)
    assert res_admin.status_code == 200
    res_mgr = client.get("/api/reports/finance", headers=MANAGER_HEADERS)
    assert res_mgr.status_code == 200

    # Sales, Warehouse, Viewer must be 403 Forbidden
    res_sales = client.get("/api/reports/finance", headers=SALES_HEADERS)
    assert res_sales.status_code == 403
    res_wh = client.get("/api/reports/finance", headers=WAREHOUSE_HEADERS)
    assert res_wh.status_code == 403
    res_viewer = client.get("/api/reports/finance", headers=VIEWER_HEADERS)
    assert res_viewer.status_code == 403


def test_procurement_kpis_and_commitment_disclaimer():
    """Verify active PO commitments, pending receipt quantities, and supplier balance notice."""
    base = create_base_entities()
    now = "2026-10-14T12:00:00Z"
    supp_id = f"supp-{uuid.uuid4().hex[:6]}"
    po_id = f"po-{uuid.uuid4().hex[:6]}"
    poi_id = f"poi-{uuid.uuid4().hex[:6]}"

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO suppliers (id, code, name, country, currency, status, created_at, updated_at)
            VALUES (?, 'SUPP-01', 'Premier Foundry Ltd', 'IN', 'INR', 'active', ?, ?)
            """,
            (supp_id, now, now),
        )
        conn.execute(
            """
            INSERT INTO purchase_orders (id, po_number, supplier_id, order_date, currency, subtotal, grand_total, status, created_at, updated_at)
            VALUES (?, 'PO-201', ?, '2026-10-01', 'INR', 50000.0, 50000.0, 'approved', ?, ?)
            """,
            (po_id, supp_id, now, now),
        )
        conn.execute(
            """
            INSERT INTO purchase_order_items (id, po_id, product_id, sku, product_name, ordered_qty, received_qty, unit_price, line_total, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'Engineered Valves', 100.0, 30.0, 500.0, 50000.0, ?, ?)
            """,
            (poi_id, po_id, base["prod_id"], base["sku"], now, now),
        )
        conn.commit()

    client = TestClient(app)
    res = client.get("/api/reports/dashboard-kpis", headers=ADMIN_HEADERS)
    assert res.status_code == 200
    proc = res.json()["procurement"]

    assert "INR" in proc["active_commitments_by_currency"]
    assert proc["active_commitments_by_currency"]["INR"]["commitment_value"] == 50000.0
    assert proc["pending_receipt_qty"] == 70.0  # 100 ordered - 30 received
    assert proc["supplier_balance_status"] == "NOT_CONFIGURED"
    assert "Vendor accounts-payable ledger is not active" in proc["supplier_balance_notice"]


def test_inventory_kpis_and_health_monitoring():
    """Verify stock types, active reservations, net available stock, and low stock categorization."""
    base = create_base_entities()
    now = "2026-10-14T12:00:00Z"
    res_id = f"res-{uuid.uuid4().hex[:6]}"

    with get_connection() as conn:
        # Available on hand: 15 PCS
        conn.execute(
            """
            INSERT OR REPLACE INTO inventory_balances (product_id, stock_type, sku, on_hand_qty, total_value, updated_at)
            VALUES (?, 'available', ?, 15.0, 7500.0, ?)
            """,
            (base["prod_id"], base["sku"], now),
        )
        # Quarantined: 5 PCS
        conn.execute(
            """
            INSERT OR REPLACE INTO inventory_balances (product_id, stock_type, sku, on_hand_qty, total_value, updated_at)
            VALUES (?, 'quarantined', ?, 5.0, 2500.0, ?)
            """,
            (base["prod_id"], base["sku"], now),
        )
        # Active Reservation: 3 PCS
        conn.execute(
            """
            INSERT INTO stock_reservations (id, reservation_number, product_id, sku, warehouse_id, quantity, status, created_at, updated_at)
            VALUES (?, 'RES-301', ?, ?, ?, 3.0, 'active', ?, ?)
            """,
            (res_id, base["prod_id"], base["sku"], base["wh_id"], now, now),
        )
        conn.commit()

    client = TestClient(app)
    res = client.get("/api/reports/dashboard-kpis", headers=ADMIN_HEADERS)
    assert res.status_code == 200
    inv = res.json()["inventory"]

    assert inv["available_qty"] >= 15.0
    assert inv["quarantined_qty"] >= 5.0
    assert inv["reserved_qty"] >= 3.0
    assert inv["low_stock_products_count"] >= 1  # 15 - 3 = 12 net available <= 20 reorder level

    # Test inventory detailed report
    rep_res = client.get("/api/reports/inventory?low_stock_only=true", headers=ADMIN_HEADERS)
    assert rep_res.status_code == 200
    rep_data = rep_res.json()
    assert rep_data["total_products"] >= 1
    found = next((p for p in rep_data["products"] if p["sku"] == base["sku"]), None)
    assert found is not None
    assert found["stock_health"] == "LOW_STOCK"
    assert found["net_available_qty"] == 12.0


def test_export_operations_kpis_and_blockers():
    """Verify shipments counts, readiness status, blocked shipments, and non-clearance legal notice."""
    base = create_base_entities()
    now = "2026-10-14T12:00:00Z"
    shp_id1 = f"shp-{uuid.uuid4().hex[:6]}"
    chk_id = f"chk-{uuid.uuid4().hex[:6]}"

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO shipments (id, reference, exporter_name, consignee_name, destination_country, transport_mode, status, readiness_status, created_at, updated_at)
            VALUES (?, 'EXP-401', 'Bharat Forgings', 'Global Exports Inc', 'US', 'sea', 'document_prep', 'blocked', ?, ?)
            """,
            (shp_id1, now, now),
        )
        conn.execute(
            """
            INSERT INTO export_shipment_checklist_items (id, shipment_id, document_type, requirement_level, status, created_at, updated_at)
            VALUES (?, ?, 'commercial_invoice', 'mandatory', 'pending', ?, ?)
            """,
            (chk_id, shp_id1, now, now),
        )
        conn.commit()

    client = TestClient(app)
    res = client.get("/api/reports/dashboard-kpis", headers=ADMIN_HEADERS)
    assert res.status_code == 200
    exp = res.json()["exports"]

    assert exp["total_shipments_count"] >= 1
    assert exp["blocked_shipments_count"] >= 1
    assert exp["document_backlog_count"] >= 1
    assert "does not constitute official customs clearance" in exp["compliance_disclaimer"]

    # Test detailed exports report endpoint
    exp_rep = client.get("/api/reports/exports", headers=ADMIN_HEADERS)
    assert exp_rep.status_code == 200
    exp_data = exp_rep.json()
    assert exp_data["total_shipments"] >= 1
    assert len(exp_data["blocked_shipments"]) >= 1


def test_csv_export_reports_and_formula_injection_defense():
    """Verify CSV generation across all report types and formula injection sanitization."""
    base = create_base_entities()
    now = "2026-10-14T12:00:00Z"
    so_id = f"so-{uuid.uuid4().hex[:6]}"

    # Insert malicious formula injection payload into customer_name
    malicious_name = "=cmd|' /C calc'!A0"
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO sales_orders (id, order_number, customer_id, customer_code, customer_name, order_date, currency, subtotal, grand_total, status, created_at, updated_at)
            VALUES (?, 'SO-INJECT-01', ?, 'CUST-BAD', ?, '2026-10-14', 'INR', 100.0, 100.0, 'confirmed', ?, ?)
            """,
            (so_id, base["cust_id"], malicious_name, now, now),
        )
        conn.commit()

    client = TestClient(app)

    # 1. Sales orders CSV
    res_so = client.get("/api/reports/export-csv?report_type=sales_orders", headers=ADMIN_HEADERS)
    assert res_so.status_code == 200
    assert res_so.headers["content-type"].startswith("text/csv")
    csv_text = res_so.text
    # Verify malicious prefix was neutralized with a single quote: '=cmd...
    assert "'=cmd|' /C calc'!A0" in csv_text

    # 2. Invoices CSV
    res_inv = client.get("/api/reports/export-csv?report_type=invoices", headers=ADMIN_HEADERS)
    assert res_inv.status_code == 200
    assert "Invoice Number" in res_inv.text

    # 3. Receivables Aging CSV
    res_aging = client.get("/api/reports/export-csv?report_type=receivables_aging", headers=ADMIN_HEADERS)
    assert res_aging.status_code == 200
    assert "Total Outstanding (INR)" in res_aging.text

    # 4. Inventory Balances CSV
    res_bal = client.get("/api/reports/export-csv?report_type=inventory_balances", headers=ADMIN_HEADERS)
    assert res_bal.status_code == 200
    assert "Net Available Qty" in res_bal.text

    # 5. Export Shipments CSV
    res_exp = client.get("/api/reports/export-csv?report_type=export_shipments", headers=ADMIN_HEADERS)
    assert res_exp.status_code == 200
    assert "Readiness Status" in res_exp.text


def test_csv_export_rbac():
    """Verify CSV export is restricted to authorized roles and denies viewers."""
    client = TestClient(app)

    # Admin and Manager can export
    res_admin = client.get("/api/reports/export-csv?report_type=sales_orders", headers=ADMIN_HEADERS)
    assert res_admin.status_code == 200
    res_mgr = client.get("/api/reports/export-csv?report_type=sales_orders", headers=MANAGER_HEADERS)
    assert res_mgr.status_code == 200

    # Viewer cannot export CSV
    res_viewer = client.get("/api/reports/export-csv?report_type=sales_orders", headers=VIEWER_HEADERS)
    assert res_viewer.status_code == 403


def test_dashboard_filtering_by_date_customer_currency():
    """Verify date, customer, and currency filters accurately bound calculated metrics."""
    base = create_base_entities()
    now = "2026-10-14T12:00:00Z"
    so_id = f"so-{uuid.uuid4().hex[:6]}"

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO sales_orders (id, order_number, customer_id, customer_code, customer_name, order_date, currency, subtotal, grand_total, status, created_at, updated_at)
            VALUES (?, 'SO-FILTER-01', ?, 'CUST-01', 'Global Exports Inc', '2026-05-01', 'EUR', 4500.0, 4500.0, 'confirmed', ?, ?)
            """,
            (so_id, base["cust_id"], now, now),
        )
        conn.commit()

    client = TestClient(app)

    # Filter with date range covering 2026-05-01 -> should find EUR 4,500
    res1 = client.get(
        f"/api/reports/dashboard-kpis?start_date=2026-04-01&end_date=2026-05-31&currency=EUR",
        headers=ADMIN_HEADERS,
    )
    assert res1.status_code == 200
    data1 = res1.json()["sales"]
    assert "EUR" in data1["confirmed_orders_by_currency"]
    assert data1["confirmed_orders_by_currency"]["EUR"]["total_value"] == 4500.0

    # Filter outside date range (2026-06-01 to 2026-07-01) -> should be 0
    res2 = client.get(
        f"/api/reports/dashboard-kpis?start_date=2026-06-01&end_date=2026-07-01&currency=EUR",
        headers=ADMIN_HEADERS,
    )
    assert res2.status_code == 200
    data2 = res2.json()["sales"]
    assert "EUR" not in data2["confirmed_orders_by_currency"]
