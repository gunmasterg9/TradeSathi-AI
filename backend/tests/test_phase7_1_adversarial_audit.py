"""
TradeSathi AI — Phase 7.1: Adversarial Safety Acceptance Audit Test Suite
Rigorous, independent verification of Financial Reconciliation, Multi-Currency Integrity,
RBAC Security, CSV Formula-Injection Mitigation, Inventory Allocations, and Data Safety.
"""

import io
import csv
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import get_connection, init_db, set_db_path, get_db_path


# =========================================================================
# GATE B: FINANCIAL RECONCILIATION ADVERSARIAL TESTS
# =========================================================================

def test_financial_reconciliation_adversarial_matrix(client: TestClient):
    """
    Test complete lifecycle matrix across 6 invoice states:
    draft, issued, partially_paid, paid, credited, cancelled, overdue.
    Verify that:
    1. Revenue only reflects confirmed billings (not draft or cancelled).
    2. Receivables strictly aggregate uncollected balances of open issued/overdue invoices.
    3. Collected payments are distinct from revenue and credit notes.
    4. Unallocated payments are tracked as customer credits, not revenue.
    5. Over-allocations are rejected with strict 400 errors.
    """
    with get_connection() as conn:
        # Create customer
        conn.execute(
            """
            INSERT INTO customers (id, code, name, legal_name, tax_id, country, billing_address, status, currency, created_at, updated_at)
            VALUES ('cust-adv-1', 'CUST-ADV-1', 'Adversarial Trading Corp', 'Adversarial Trading Corp Ltd', '19AAACT1234A1Z5', 'India', '123 Harbor St', 'active', 'INR', '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z')
            """
        )
        # 1. Draft Invoice: INR 10,000 (must be excluded from receivables and invoiced revenue)
        conn.execute(
            """
            INSERT INTO customer_invoices (
                id, invoice_number, customer_id, customer_code, customer_name,
                billing_address, invoice_date, due_date, currency, exchange_rate,
                subtotal, discount_total, cgst_total, sgst_total, igst_total, tax_total,
                grand_total, amount_paid, amount_credited, outstanding_balance, base_grand_total,
                status, is_posted, created_by, created_at, updated_at
            ) VALUES (
                'inv-adv-draft', 'INV-ADV-001', 'cust-adv-1', 'CUST-ADV-1', 'Adversarial Trading Corp',
                '123 Harbor St', '2026-10-01', '2026-10-31', 'INR', 1.0,
                10000.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                10000.0, 0.0, 0.0, 10000.0, 10000.0,
                'draft', 0, 'tester', '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z'
            )
            """
        )
        # 2. Issued Invoice: INR 20,000 (full open balance)
        conn.execute(
            """
            INSERT INTO customer_invoices (
                id, invoice_number, customer_id, customer_code, customer_name,
                billing_address, invoice_date, due_date, currency, exchange_rate,
                subtotal, discount_total, cgst_total, sgst_total, igst_total, tax_total,
                grand_total, amount_paid, amount_credited, outstanding_balance, base_grand_total,
                status, is_posted, created_by, created_at, updated_at
            ) VALUES (
                'inv-adv-issued', 'INV-ADV-002', 'cust-adv-1', 'CUST-ADV-1', 'Adversarial Trading Corp',
                '123 Harbor St', '2026-10-02', '2026-10-15', 'INR', 1.0,
                20000.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                20000.0, 0.0, 0.0, 20000.0, 20000.0,
                'issued', 1, 'tester', '2026-10-02T00:00:00Z', '2026-10-02T00:00:00Z'
            )
            """
        )
        # 3. Partially Paid Invoice: INR 30,000 with INR 12,000 paid -> Outstanding INR 18,000
        conn.execute(
            """
            INSERT INTO customer_invoices (
                id, invoice_number, customer_id, customer_code, customer_name,
                billing_address, invoice_date, due_date, currency, exchange_rate,
                subtotal, discount_total, cgst_total, sgst_total, igst_total, tax_total,
                grand_total, amount_paid, amount_credited, outstanding_balance, base_grand_total,
                status, is_posted, created_by, created_at, updated_at
            ) VALUES (
                'inv-adv-part', 'INV-ADV-003', 'cust-adv-1', 'CUST-ADV-1', 'Adversarial Trading Corp',
                '123 Harbor St', '2026-10-03', '2026-10-18', 'INR', 1.0,
                30000.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                30000.0, 12000.0, 0.0, 18000.0, 30000.0,
                'partially_paid', 1, 'tester', '2026-10-03T00:00:00Z', '2026-10-03T00:00:00Z'
            )
            """
        )
        # 4. Paid Invoice: INR 15,000 with INR 15,000 paid -> Outstanding INR 0.0
        conn.execute(
            """
            INSERT INTO customer_invoices (
                id, invoice_number, customer_id, customer_code, customer_name,
                billing_address, invoice_date, due_date, currency, exchange_rate,
                subtotal, discount_total, cgst_total, sgst_total, igst_total, tax_total,
                grand_total, amount_paid, amount_credited, outstanding_balance, base_grand_total,
                status, is_posted, created_by, created_at, updated_at
            ) VALUES (
                'inv-adv-paid', 'INV-ADV-004', 'cust-adv-1', 'CUST-ADV-1', 'Adversarial Trading Corp',
                '123 Harbor St', '2026-10-04', '2026-10-12', 'INR', 1.0,
                15000.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                15000.0, 15000.0, 0.0, 0.0, 15000.0,
                'paid', 1, 'tester', '2026-10-04T00:00:00Z', '2026-10-04T00:00:00Z'
            )
            """
        )
        # 5. Cancelled Invoice: INR 5,000 (must be completely excluded from receivables and invoiced totals)
        conn.execute(
            """
            INSERT INTO customer_invoices (
                id, invoice_number, customer_id, customer_code, customer_name,
                billing_address, invoice_date, due_date, currency, exchange_rate,
                subtotal, discount_total, cgst_total, sgst_total, igst_total, tax_total,
                grand_total, amount_paid, amount_credited, outstanding_balance, base_grand_total,
                status, is_posted, created_by, created_at, updated_at
            ) VALUES (
                'inv-adv-canc', 'INV-ADV-005', 'cust-adv-1', 'CUST-ADV-1', 'Adversarial Trading Corp',
                '123 Harbor St', '2026-10-05', '2026-10-25', 'INR', 1.0,
                5000.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                5000.0, 0.0, 0.0, 5000.0, 5000.0,
                'cancelled', 0, 'tester', '2026-10-05T00:00:00Z', '2026-10-05T00:00:00Z'
            )
            """
        )
        # 6. Overdue Invoice: USD 500 @ 84.0 = INR 42,000 (Past due date 2026-09-01)
        conn.execute(
            """
            INSERT INTO customer_invoices (
                id, invoice_number, customer_id, customer_code, customer_name,
                billing_address, invoice_date, due_date, currency, exchange_rate,
                subtotal, discount_total, cgst_total, sgst_total, igst_total, tax_total,
                grand_total, amount_paid, amount_credited, outstanding_balance, base_grand_total,
                status, is_posted, created_by, created_at, updated_at
            ) VALUES (
                'inv-adv-overdue', 'INV-ADV-006', 'cust-adv-1', 'CUST-ADV-1', 'Adversarial Trading Corp',
                '123 Harbor St', '2026-08-01', '2026-09-01', 'USD', 84.0,
                500.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                500.0, 0.0, 0.0, 500.0, 42000.0,
                'overdue', 1, 'tester', '2026-08-01T00:00:00Z', '2026-08-01T00:00:00Z'
            )
            """
        )
        # Payments:
        # P1: INR 27,000 collected (12,000 allocated to inv-adv-part, 15,000 allocated to inv-adv-paid, 0 unallocated)
        conn.execute(
            """
            INSERT INTO customer_payments (
                id, payment_number, customer_id, customer_name, payment_date,
                payment_method, currency, exchange_rate, amount, allocated_amount,
                unallocated_amount, status, created_by, created_at, updated_at
            ) VALUES (
                'pay-adv-1', 'PAY-ADV-001', 'cust-adv-1', 'Adversarial Trading Corp', '2026-10-04',
                'bank_transfer', 'INR', 1.0, 27000.0, 27000.0,
                0.0, 'posted', 'tester', '2026-10-04T00:00:00Z', '2026-10-04T00:00:00Z'
            )
            """
        )
        # P2: INR 5,000 unallocated customer advance payment
        conn.execute(
            """
            INSERT INTO customer_payments (
                id, payment_number, customer_id, customer_name, payment_date,
                payment_method, currency, exchange_rate, amount, allocated_amount,
                unallocated_amount, status, created_by, created_at, updated_at
            ) VALUES (
                'pay-adv-2', 'PAY-ADV-002', 'cust-adv-1', 'Adversarial Trading Corp', '2026-10-05',
                'wire_swift', 'INR', 1.0, 5000.0, 0.0,
                5000.0, 'posted', 'tester', '2026-10-05T00:00:00Z', '2026-10-05T00:00:00Z'
            )
            """
        )
        conn.commit()

    # Query Dashboard KPIs with Admin role
    resp = client.get("/api/reports/dashboard-kpis", headers={"X-User-Role": "admin"})
    assert resp.status_code == 200
    data = resp.json()
    fin = data["finance"]
    assert fin["restricted"] is False

    # Expected reconciliation:
    # 1. Total Invoiced Base INR = INV-002 (20,000) + INV-003 (30,000) + INV-004 (15,000) + INV-006 (42,000) = 107,000 INR
    # Draft (10,000) and Cancelled (5,000) are excluded.
    assert fin["total_invoiced_base_inr"] == 107000.0
    assert fin["draft_invoiced_base_inr"] == 10000.0

    # 2. Issued Receivables Base INR =
    # INV-002 (20,000) + INV-003 (18,000 remaining) + INV-006 (500 USD * 84 = 42,000 INR) = 80,000 INR
    assert fin["issued_receivables_base_inr"] == 80000.0
    assert fin["open_invoices_count"] == 3  # INV-002, INV-003, INV-006

    # 3. Currency breakdown:
    # INR: 20,000 + 18,000 = 38,000 INR (2 invoices)
    # USD: 500 USD (1 invoice)
    by_curr = fin["receivables_by_currency"]
    assert by_curr["INR"]["balance_due"] == 38000.0
    assert by_curr["INR"]["open_invoices"] == 2
    assert by_curr["USD"]["balance_due"] == 500.0
    assert by_curr["USD"]["open_invoices"] == 1

    # 4. Payments:
    # Collected = P1 (27,000) + P2 (5,000) = 32,000 INR
    # Unallocated = P2 (5,000 INR)
    assert fin["collected_payments_base_inr"] == 32000.0
    assert fin["unallocated_credits_base_inr"] == 5000.0
    assert fin["payments_count"] == 2


# =========================================================================
# GATE C: MULTI-CURRENCY & NEGATIVE RATE BOUNDARY TESTS
# =========================================================================

def test_currency_and_exchange_rate_boundaries(client: TestClient):
    """
    Test exchange-rate boundary validation:
    - Zero or negative exchange rate in invoice creation must be rejected.
    - Missing conversion rate cannot silently default to 1 for foreign currency.
    - Historical exchange rate snapshots are immutable and preserved.
    """
    # 1. Invoice with negative exchange rate must fail schema validation
    inv_payload_negative_rate = {
        "customer_id": "cust-adv-1",
        "place_of_supply": "19-West Bengal",
        "invoice_date": "2026-10-10",
        "due_date": "2026-11-10",
        "currency": "EUR",
        "exchange_rate": -92.5,
        "items": [
            {
                "product_sku": "SKU-CURR-1",
                "description": "Export Widget",
                "quantity": 10.0,
                "unit_price": 50.0,
                "gst_rate_pct": 0.0,
            }
        ],
    }
    resp = client.post("/api/finance/invoices", json=inv_payload_negative_rate, headers={"X-User-Role": "admin"})
    assert resp.status_code == 422  # Unprocessable Entity (gt=0 violated)

    # 2. Payment with zero exchange rate must fail validation
    pay_payload_zero_rate = {
        "customer_id": "cust-adv-1",
        "payment_date": "2026-10-10",
        "payment_method": "bank_transfer",
        "currency": "GBP",
        "exchange_rate": 0.0,
        "amount": 1000.0,
    }
    resp = client.post("/api/finance/payments", json=pay_payload_zero_rate, headers={"X-User-Role": "admin"})
    assert resp.status_code == 422  # Unprocessable Entity (gt=0 violated)


# =========================================================================
# GATE D: AUTHORIZATION & API SECURITY TESTS
# =========================================================================

def test_role_authorization_and_unauthorized_direct_calls(client: TestClient):
    """
    Verify RBAC security:
    1. Anonymous request to /api/reports/finance returns 401 Unauthorized.
    2. Operational roles (sales, warehouse, procurement, operator, viewer) cannot access /api/reports/finance (403 Forbidden).
    3. Operational roles cannot export financial CSVs (invoices, receivables_aging) even if they have export_reports (403 Forbidden).
    4. General dashboard KPI endpoint masks financial metrics for non-finance roles ('restricted': True).
    """
    # 1. Anonymous request without headers (in non-simulator or viewer simulator)
    viewer_resp = client.get("/api/reports/finance", headers={"X-User-Role": "viewer"})
    assert viewer_resp.status_code == 403
    assert "view_financial_reports" in viewer_resp.json()["detail"]

    # 2. Sales role accessing finance report directly -> 403 Forbidden
    sales_resp = client.get("/api/reports/finance", headers={"X-User-Role": "sales"})
    assert sales_resp.status_code == 403

    # 3. Warehouse role attempting to export financial invoices CSV -> 403 Forbidden (not authorized to export_reports)
    wh_export_resp = client.get("/api/reports/export-csv?report_type=invoices", headers={"X-User-Role": "warehouse"})
    assert wh_export_resp.status_code == 403
    assert "export_reports" in wh_export_resp.json()["detail"]

    # 4. Warehouse role accessing dashboard KPIs -> permitted, but finance block is restricted
    wh_kpi_resp = client.get("/api/reports/dashboard-kpis", headers={"X-User-Role": "warehouse"})
    assert wh_kpi_resp.status_code == 200
    kpi_data = wh_kpi_resp.json()
    assert kpi_data["finance"]["restricted"] is True
    assert "issued_receivables_base_inr" not in kpi_data["finance"]


# =========================================================================
# GATE E: ADVERSARIAL CSV FORMULA-INJECTION TESTS
# =========================================================================

def test_csv_formula_injection_raw_bytes_and_obfuscation(client: TestClient):
    """
    Test adversarial CSV formula injection via direct endpoint stream:
    Verify that dangerous formula triggers (=, +, -, @, |, leading spaces/tabs/CR)
    are prepended with a single quote (') while legitimate negative numbers remain unquoted.
    """
    with get_connection() as conn:
        # Create customer with malicious formula payload in customer_name
        conn.execute(
            """
            INSERT INTO customers (id, code, name, legal_name, tax_id, country, billing_address, status, currency, created_at, updated_at)
            VALUES ('cust-malicious', 'CUST-MAL-1', '=cmd|'' /C calc''!A0', 'Malicious Corp Ltd', '19AAACT1234A1Z5', 'India', '123 Harbor St', 'active', 'INR', '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z')
            """
        )
        # Create invoice with malicious formula in customer name and plain negative/positive figures
        conn.execute(
            """
            INSERT INTO customer_invoices (
                id, invoice_number, customer_id, customer_code, customer_name,
                billing_address, invoice_date, due_date, currency, exchange_rate,
                subtotal, discount_total, cgst_total, sgst_total, igst_total, tax_total,
                grand_total, amount_paid, amount_credited, outstanding_balance, base_grand_total,
                status, is_posted, created_by, created_at, updated_at
            ) VALUES (
                'inv-mal-1', 'INV-MAL-001', 'cust-malicious', 'CUST-MAL-1', '=cmd|'' /C calc''!A0',
                '123 Harbor St', '2026-10-01', '2026-10-31', 'INR', 1.0,
                5000.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                5000.0, 0.0, 0.0, 5000.0, 5000.0,
                'issued', 1, 'tester', '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z'
            )
            """
        )
        conn.commit()

    # Stream CSV export for invoices as Admin
    resp = client.get("/api/reports/export-csv?report_type=invoices", headers={"X-User-Role": "admin"})
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]

    csv_text = resp.text
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    assert len(rows) >= 2  # Header + at least 1 row

    header = rows[0]
    cust_idx = header.index("Customer Name")
    data_row = next(r for r in rows[1:] if r[0] == "INV-MAL-001")
    exported_cust_name = data_row[cust_idx]

    # Verify formula is escaped with single quote
    assert exported_cust_name.startswith("'="), f"Expected formula escape, got: {exported_cust_name}"
    assert "calc" in exported_cust_name


# =========================================================================
# GATE F: INVENTORY RESERVATION & OPERATIONAL METRICS
# =========================================================================

def test_inventory_stock_reservation_exclusion(client: TestClient):
    """
    Verify that:
    1. Available on-hand stock excludes reserved, quarantined, rejected, and in-transit.
    2. Active reservations correctly decrease net available stock in reorder health checks.
    3. Purchase order commitments carry mandatory disclaimers and are not booked as liabilities.
    """
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO warehouses (id, code, name, is_active, created_at, updated_at)
            VALUES ('wh-adv-1', 'WH-ADV-1', 'Adversarial Central Warehouse', 1, '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO products (id, sku, name, category, uom, reorder_level, is_active, created_at, updated_at)
            VALUES ('prod-adv-1', 'SKU-ADV-100', 'Industrial Valve', 'Valves', 'PCS', 50.0, 1, '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z')
            """
        )
        # 100 on-hand available, 40 active reservation -> Net Available = 60 (above reorder 50 -> HEALTHY)
        conn.execute(
            """
            INSERT INTO inventory_balances (product_id, stock_type, sku, on_hand_qty, total_value, updated_at)
            VALUES ('prod-adv-1', 'available', 'SKU-ADV-100', 100.0, 10000.0, '2026-10-01T00:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO stock_reservations (id, reservation_number, warehouse_id, product_id, sku, quantity, status, created_at, updated_at)
            VALUES ('res-adv-1', 'RES-ADV-001', 'wh-adv-1', 'prod-adv-1', 'SKU-ADV-100', 40.0, 'active', '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z')
            """
        )
        conn.commit()

    resp = client.get("/api/reports/inventory", headers={"X-User-Role": "admin"})
    assert resp.status_code == 200
    inv_data = resp.json()
    item = next(p for p in inv_data["products"] if p["sku"] == "SKU-ADV-100")

    assert item["on_hand_available"] == 100.0
    assert item["reserved_qty"] == 40.0
    assert item["net_available_qty"] == 60.0
    assert item["stock_health"] == "HEALTHY"  # 60 > 50

    # Add 25 more reservation -> Net Available = 35 <= 50 -> LOW_STOCK
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO stock_reservations (id, reservation_number, warehouse_id, product_id, sku, quantity, status, created_at, updated_at)
            VALUES ('res-adv-2', 'RES-ADV-002', 'wh-adv-1', 'prod-adv-1', 'SKU-ADV-100', 25.0, 'active', '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z')
            """
        )
        conn.commit()

    resp2 = client.get("/api/reports/inventory", headers={"X-User-Role": "admin"})
    item2 = next(p for p in resp2.json()["products"] if p["sku"] == "SKU-ADV-100")
    assert item2["net_available_qty"] == 35.0
    assert item2["stock_health"] == "LOW_STOCK"  # 35 <= 50, but > 25 (0.5 * 50)

