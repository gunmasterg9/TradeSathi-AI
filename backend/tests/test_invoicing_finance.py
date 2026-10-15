"""
TradeSathi AI — Phase 6: Commercial Invoicing, Payments, Indian GST & Multi-Currency Tests
"""

import os
import tempfile
import uuid
import pytest
from fastapi.testclient import TestClient

import os
import tempfile
import uuid
import pytest
from fastapi.testclient import TestClient

from app.db import (
    get_connection,
    init_db,
    get_customer_invoice_record,
    get_customer_payment_record,
    get_customer_credit_note_record,
)
from app.main import app

ADMIN_HEADERS = {"X-User-Role": "admin", "X-User-Name": "Admin User", "X-User-Email": "admin@tradesathi.local"}
OPERATOR1_HEADERS = {"X-User-Role": "operator", "X-User-Name": "Operator 1", "X-User-Email": "operator1@tradesathi.local"}
OPERATOR2_HEADERS = {"X-User-Role": "operator", "X-User-Name": "Operator 2", "X-User-Email": "operator2@tradesathi.local"}
VIEWER_HEADERS = {"X-User-Role": "viewer", "X-User-Name": "Auditor Viewer", "X-User-Email": "viewer@tradesathi.local"}



def create_mock_customer_and_product(client, state_code="19"):
    cust_id = f"cust-{uuid.uuid4().hex[:6]}"
    cust_code = f"CUST-{uuid.uuid4().hex[:4].upper()}"
    prod_id = f"prod-{uuid.uuid4().hex[:6]}"
    sku = f"SKU-{uuid.uuid4().hex[:4].upper()}"
    now = "2026-10-14T12:00:00Z"

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO customers (id, code, name, legal_name, tax_id, country, billing_address, status, currency, created_at, updated_at)
            VALUES (?, ?, 'Bengal Agro Traders', 'Bengal Agro Traders Pvt Ltd', '19AAACT1111A1Z1', 'IN', 'Strand Road, Kolkata, WB - 700001', 'active', 'INR', ?, ?)
            """,
            (cust_id, cust_code, now, now),
        )
        conn.execute(
            """
            INSERT INTO products (id, sku, name, uom, default_selling_price, currency, hsn_code, tax_rate_pct, is_active, created_at, updated_at)
            VALUES (?, ?, 'Organic Basmati Rice', 'KG', 120.0, 'INR', '10063020', 5.0, 1, ?, ?)
            """,
            (prod_id, sku, now, now),
        )
        conn.commit()

    return {"id": cust_id, "code": cust_code, "name": "Bengal Agro Traders"}, {"id": prod_id, "sku": sku}


# ==========================================
# 1. Indian GST Intra-State (CGST + SGST)
# ==========================================


def test_intra_state_gst_calculation_cgst_sgst(client):
    cust, prod = create_mock_customer_and_product(client)

    payload = {
        "customer_id": cust["id"],
        "place_of_supply": "19-West Bengal",
        "invoice_date": "2026-10-14",
        "due_date": "2026-11-14",
        "currency": "INR",
        "exchange_rate": 1.0,
        "tax_scheme": "GST",
        "items": [
            {
                "product_id": prod["id"],
                "product_sku": prod["sku"],
                "description": "Organic Basmati Rice 100kg",
                "hsn_code": "10063020",
                "uom": "KG",
                "quantity": 100.0,
                "unit_price": 100.0,
                "discount_pct": 10.0,  # Subtotal 9000.0
                "tax_classification": "taxable",
                "gst_rate_pct": 18.0,  # 9% CGST + 9% SGST
            }
        ],
    }

    res = client.post("/api/finance/invoices", json=payload, headers=OPERATOR1_HEADERS)
    assert res.status_code == 200, res.text
    data = res.json()

    assert data["subtotal"] == 9000.0
    assert data["discount_total"] == 1000.0
    assert data["cgst_total"] == 810.0  # 9% of 9000
    assert data["sgst_total"] == 810.0  # 9% of 9000
    assert data["igst_total"] == 0.0    # Strict 0.0 for intra-state
    assert data["tax_total"] == 1620.0
    assert data["grand_total"] == 10620.0
    assert data["outstanding_balance"] == 10620.0

    # Verify line item detail
    line = data["items"][0]
    assert line["cgst_rate_pct"] == 9.0
    assert line["sgst_rate_pct"] == 9.0
    assert line["igst_rate_pct"] == 0.0
    assert line["line_total"] == 10620.0


# ==========================================
# 2. Indian GST Inter-State (IGST)
# ==========================================


def test_inter_state_gst_calculation_igst(client):
    cust, prod = create_mock_customer_and_product(client)

    payload = {
        "customer_id": cust["id"],
        "place_of_supply": "27-Maharashtra",  # Inter-state
        "invoice_date": "2026-10-14",
        "due_date": "2026-11-14",
        "currency": "INR",
        "exchange_rate": 1.0,
        "tax_scheme": "GST",
        "items": [
            {
                "product_id": prod["id"],
                "product_sku": prod["sku"],
                "description": "Spices Consignment Mumbai",
                "hsn_code": "091099",
                "uom": "KG",
                "quantity": 50.0,
                "unit_price": 200.0,
                "discount_pct": 0.0,  # Subtotal 10000.0
                "tax_classification": "taxable",
                "gst_rate_pct": 12.0,  # 12% IGST
            }
        ],
    }

    res = client.post("/api/finance/invoices", json=payload, headers=OPERATOR1_HEADERS)
    assert res.status_code == 200, res.text
    data = res.json()

    assert data["subtotal"] == 10000.0
    assert data["cgst_total"] == 0.0  # Strict 0.0 for inter-state
    assert data["sgst_total"] == 0.0  # Strict 0.0 for inter-state
    assert data["igst_total"] == 1200.0  # 12% of 10000
    assert data["tax_total"] == 1200.0
    assert data["grand_total"] == 11200.0


# ==========================================
# 3. Export Zero-Rated Supplies (LUT & IGST)
# ==========================================


def test_export_zero_rated_under_lut(client):
    cust, prod = create_mock_customer_and_product(client)

    payload = {
        "customer_id": cust["id"],
        "place_of_supply": "97-Other Territory / Export",
        "invoice_date": "2026-10-14",
        "due_date": "2026-11-14",
        "currency": "USD",
        "exchange_rate": 83.50,
        "tax_scheme": "EXPORT_LUT",
        "lut_bond_number": "ARN-AD190324001234F",
        "items": [
            {
                "product_sku": prod["sku"],
                "description": "Export Cargo Dubai",
                "quantity": 100.0,
                "unit_price": 25.0,  # $2500
                "discount_pct": 0.0,
                "tax_classification": "zero_rated_export",
                "gst_rate_pct": 18.0,
            }
        ],
    }

    res = client.post("/api/finance/invoices", json=payload, headers=OPERATOR1_HEADERS)
    assert res.status_code == 200, res.text
    data = res.json()

    # Zero-rated under LUT: tax total must be strictly 0.0
    assert data["subtotal"] == 2500.0
    assert data["cgst_total"] == 0.0
    assert data["sgst_total"] == 0.0
    assert data["igst_total"] == 0.0
    assert data["tax_total"] == 0.0
    assert data["grand_total"] == 2500.0
    assert data["base_grand_total"] == round(2500.0 * 83.50, 2)  # 208750.0 INR


def test_export_with_igst_payment(client):
    cust, prod = create_mock_customer_and_product(client)

    payload = {
        "customer_id": cust["id"],
        "place_of_supply": "97-Export",
        "invoice_date": "2026-10-14",
        "due_date": "2026-11-14",
        "currency": "INR",
        "exchange_rate": 1.0,
        "tax_scheme": "EXPORT_ZERO_RATED",
        "items": [
            {
                "product_sku": prod["sku"],
                "description": "Export Cargo with Tax Payment",
                "quantity": 10.0,
                "unit_price": 1000.0,
                "tax_classification": "taxable",
                "gst_rate_pct": 18.0,
            }
        ],
    }

    res = client.post("/api/finance/invoices", json=payload, headers=OPERATOR1_HEADERS)
    assert res.status_code == 200, res.text
    data = res.json()

    assert data["subtotal"] == 10000.0
    assert data["igst_total"] == 1800.0
    assert data["cgst_total"] == 0.0
    assert data["sgst_total"] == 0.0
    assert data["tax_total"] == 1800.0
    assert data["grand_total"] == 11800.0


# ==========================================
# 4. Cumulative Invoiceable Quantity Guard
# ==========================================


def test_cumulative_invoiceable_quantity_guard(client):
    cust, prod = create_mock_customer_and_product(client)
    now = "2026-10-14T12:00:00Z"
    so_id = f"so-{uuid.uuid4().hex[:6]}"
    so_num = f"SO-{uuid.uuid4().hex[:4].upper()}"
    so_item_id = f"soi-{uuid.uuid4().hex[:6]}"

    # Create Sales Order with ordered_quantity = 10.0
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO sales_orders (id, order_number, customer_id, customer_code, customer_name, order_date, currency, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, '2026-10-14', 'INR', 'confirmed', ?, ?)
            """,
            (so_id, so_num, cust["id"], cust["code"], cust["name"], now, now),
        )
        conn.execute(
            """
            INSERT INTO sales_order_items (id, sales_order_id, product_id, product_sku, product_name, ordered_quantity, unit_price, subtotal, line_total, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'Test Product', 10.0, 500.0, 5000.0, 5000.0, ?, ?)
            """,
            (so_item_id, so_id, prod["id"], prod["sku"], now, now),
        )
        conn.commit()

    # Invoicing Part 1: 6 units (Allowed)
    inv1_payload = {
        "customer_id": cust["id"],
        "sales_order_id": so_id,
        "invoice_date": "2026-10-14",
        "due_date": "2026-11-14",
        "currency": "INR",
        "items": [
            {
                "sales_order_item_id": so_item_id,
                "product_id": prod["id"],
                "product_sku": prod["sku"],
                "description": "Part 1 delivery",
                "quantity": 6.0,
                "unit_price": 500.0,
            }
        ],
    }
    r1 = client.post("/api/finance/invoices", json=inv1_payload, headers=OPERATOR1_HEADERS)
    assert r1.status_code == 200, r1.text

    # Invoicing Part 2: 5 units (Total 6 + 5 = 11 > 10) -> MUST FAIL with HTTP 400
    inv2_over_payload = {
        "customer_id": cust["id"],
        "sales_order_id": so_id,
        "invoice_date": "2026-10-14",
        "due_date": "2026-11-14",
        "currency": "INR",
        "items": [
            {
                "sales_order_item_id": so_item_id,
                "product_id": prod["id"],
                "product_sku": prod["sku"],
                "description": "Over invoicing attempt",
                "quantity": 5.0,
                "unit_price": 500.0,
            }
        ],
    }
    r2 = client.post("/api/finance/invoices", json=inv2_over_payload, headers=OPERATOR1_HEADERS)
    assert r2.status_code == 400
    assert "exceeds ordered quantity" in r2.json()["detail"]

    # Invoicing Part 3: Remaining 4 units (Total 6 + 4 = 10 == 10) -> Allowed
    inv3_exact_payload = {
        "customer_id": cust["id"],
        "sales_order_id": so_id,
        "invoice_date": "2026-10-14",
        "due_date": "2026-11-14",
        "currency": "INR",
        "items": [
            {
                "sales_order_item_id": so_item_id,
                "product_id": prod["id"],
                "product_sku": prod["sku"],
                "description": "Exact remainder",
                "quantity": 4.0,
                "unit_price": 500.0,
            }
        ],
    }
    r3 = client.post("/api/finance/invoices", json=inv3_exact_payload, headers=OPERATOR1_HEADERS)
    assert r3.status_code == 200, r3.text


# ==========================================
# 5. Separation of Duties in Invoice Approval
# ==========================================


def test_separation_of_duties_invoice_approval(client):
    cust, prod = create_mock_customer_and_product(client)

    payload = {
        "customer_id": cust["id"],
        "invoice_date": "2026-10-14",
        "due_date": "2026-11-14",
        "currency": "INR",
        "items": [
            {
                "product_sku": prod["sku"],
                "description": "Segregation test item",
                "quantity": 1.0,
                "unit_price": 500.0,
            }
        ],
    }

    # Created by operator 1
    create_res = client.post("/api/finance/invoices", json=payload, headers=OPERATOR1_HEADERS)
    assert create_res.status_code == 200
    inv_id = create_res.json()["id"]

    # Operator 1 tries to approve/issue own invoice -> REJECTED (Separation of duties)
    self_app = client.post(
        f"/api/finance/invoices/{inv_id}/status",
        json={"status": "issued"},
        headers=OPERATOR1_HEADERS,
    )
    assert self_app.status_code == 403
    assert "Separation-of-duties violation" in self_app.json()["detail"]

    # Operator 2 approves/issues -> ALLOWED
    op2_app = client.post(
        f"/api/finance/invoices/{inv_id}/status",
        json={"status": "issued"},
        headers=OPERATOR2_HEADERS,
    )
    assert op2_app.status_code == 200
    assert op2_app.json()["status"] == "issued"
    assert op2_app.json()["is_posted"] == 1


# ==========================================
# 6. Customer Payment Recording & Allocation
# ==========================================


def test_customer_payment_recording_and_allocation(client):
    cust, prod = create_mock_customer_and_product(client)

    # 1. Create Invoice for 20,000 INR
    inv_res = client.post(
        "/api/finance/invoices",
        json={
            "customer_id": cust["id"],
            "invoice_date": "2026-10-14",
            "due_date": "2026-11-14",
            "currency": "INR",
            "items": [{"product_sku": prod["sku"], "description": "Goods", "quantity": 20.0, "unit_price": 1000.0}],
        },
        headers=OPERATOR1_HEADERS,
    )
    inv_id = inv_res.json()["id"]

    # Issue invoice via Operator 2
    client.post(f"/api/finance/invoices/{inv_id}/status", json={"status": "issued"}, headers=OPERATOR2_HEADERS)

    # 2. Record Customer Payment of 30,000 INR
    pay_res = client.post(
        "/api/finance/payments",
        json={
            "customer_id": cust["id"],
            "payment_date": "2026-10-15",
            "payment_method": "bank_transfer",
            "reference_number": "UTR-SBIN20261015888",
            "currency": "INR",
            "amount": 30000.0,
            "notes": "Advance bank transfer",
        },
        headers=OPERATOR1_HEADERS,
    )
    assert pay_res.status_code == 200
    pay_id = pay_res.json()["id"]
    assert pay_res.json()["unallocated_amount"] == 30000.0

    # 3. Partial allocation: Allocate 12,000 INR to the 20,000 INR invoice
    alloc1 = client.post(
        f"/api/finance/payments/{pay_id}/allocate",
        json={"invoice_id": inv_id, "amount": 12000.0, "notes": "First partial payment"},
        headers=OPERATOR1_HEADERS,
    )
    assert alloc1.status_code == 200
    pay_after1 = alloc1.json()
    assert pay_after1["unallocated_amount"] == 18000.0
    assert pay_after1["allocated_amount"] == 12000.0

    # Verify Invoice status is now 'partially_paid' and outstanding is 8,000
    inv_after1 = client.get(f"/api/finance/invoices/{inv_id}", headers=OPERATOR1_HEADERS).json()
    assert inv_after1["status"] == "partially_paid"
    assert inv_after1["amount_paid"] == 12000.0
    assert inv_after1["outstanding_balance"] == 8000.0

    # 4. Final allocation: Allocate remaining 8,000 INR to fully clear invoice
    alloc2 = client.post(
        f"/api/finance/payments/{pay_id}/allocate",
        json={"invoice_id": inv_id, "amount": 8000.0},
        headers=OPERATOR1_HEADERS,
    )
    assert alloc2.status_code == 200
    assert alloc2.json()["unallocated_amount"] == 10000.0

    inv_after2 = client.get(f"/api/finance/invoices/{inv_id}", headers=OPERATOR1_HEADERS).json()
    assert inv_after2["status"] == "paid"
    assert inv_after2["amount_paid"] == 20000.0
    assert inv_after2["outstanding_balance"] == 0.0


# ==========================================
# 7. Credit Note Creation & Balance Adjustment
# ==========================================


def test_credit_note_creation_and_balance_deduction(client):
    cust, prod = create_mock_customer_and_product(client)

    # Create Invoice of 10,000 INR
    inv_res = client.post(
        "/api/finance/invoices",
        json={
            "customer_id": cust["id"],
            "invoice_date": "2026-10-14",
            "due_date": "2026-11-14",
            "currency": "INR",
            "items": [{"product_sku": prod["sku"], "description": "10 Cartons", "quantity": 10.0, "unit_price": 1000.0}],
        },
        headers=OPERATOR1_HEADERS,
    )
    inv_id = inv_res.json()["id"]
    client.post(f"/api/finance/invoices/{inv_id}/status", json={"status": "issued"}, headers=OPERATOR2_HEADERS)

    # Issue Credit Note for 2 defective cartons (2,000 INR)
    crn_res = client.post(
        "/api/finance/credit-notes",
        json={
            "invoice_id": inv_id,
            "reason": "defective_goods",
            "notes": "2 cartons damaged in transit",
            "items": [
                {
                    "product_sku": prod["sku"],
                    "description": "Defective cartons credit",
                    "quantity": 2.0,
                    "unit_price": 1000.0,
                    "gst_rate_pct": 0.0,
                }
            ],
        },
        headers=OPERATOR1_HEADERS,
    )
    assert crn_res.status_code == 200
    crn_data = crn_res.json()
    assert crn_data["grand_total"] == 2000.0
    assert crn_data["reason"] == "defective_goods"

    # Verify Invoice outstanding balance decreased from 10,000 to 8,000
    inv_updated = client.get(f"/api/finance/invoices/{inv_id}", headers=OPERATOR1_HEADERS).json()
    assert inv_updated["amount_credited"] == 2000.0
    assert inv_updated["outstanding_balance"] == 8000.0
    assert len(inv_updated["credit_notes"]) == 1


# ==========================================
# 8. Receivables Aging & GST Reports
# ==========================================


def test_receivables_aging_and_gst_outward_reports(client):
    aging_res = client.get("/api/finance/reports/receivables-aging", headers=OPERATOR1_HEADERS)
    assert aging_res.status_code == 200
    aging_data = aging_res.json()
    assert "buckets" in aging_data
    assert "current" in aging_data["buckets"]
    assert "days_1_30" in aging_data["buckets"]
    assert "days_31_60" in aging_data["buckets"]
    assert "total_receivables_inr" in aging_data

    gst_res = client.get("/api/finance/reports/gst-outward", headers=OPERATOR1_HEADERS)
    assert gst_res.status_code == 200
    gst_data = gst_res.json()
    assert "b2b_intra_state" in gst_data
    assert "b2b_inter_state" in gst_data
    assert "export_supplies_under_lut" in gst_data
    assert "statutory_notice" in gst_data
    assert "does not constitute statutory gstr-1" in gst_data["statutory_notice"].lower()


# ==========================================
# 9. Role-Based Access Control (RBAC)
# ==========================================


def test_rbac_protection_on_finance_operations(client):
    cust, prod = create_mock_customer_and_product(client)

    # Viewer role CANNOT create invoices (HTTP 403)
    v_inv = client.post(
        "/api/finance/invoices",
        json={
            "customer_id": cust["id"],
            "invoice_date": "2026-10-14",
            "due_date": "2026-11-14",
            "items": [{"product_sku": prod["sku"], "description": "Item", "quantity": 1.0, "unit_price": 100.0}],
        },
        headers=VIEWER_HEADERS,
    )
    assert v_inv.status_code == 403

    # Viewer role CANNOT record payments (HTTP 403)
    v_pay = client.post(
        "/api/finance/payments",
        json={
            "customer_id": cust["id"],
            "payment_date": "2026-10-14",
            "payment_method": "cash",
            "amount": 500.0,
        },
        headers=VIEWER_HEADERS,
    )
    assert v_pay.status_code == 403

    # Viewer CAN read invoices and reports
    v_read = client.get("/api/finance/invoices", headers=VIEWER_HEADERS)
    assert v_read.status_code == 200
