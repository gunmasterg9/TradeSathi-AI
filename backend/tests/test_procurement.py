"""TradeSathi AI — ExportMate ERP Phase 2: Procurement & Goods Receipt Automated Tests
Covers Purchase Orders, Partial Goods Receipts, Quality Inspection,
Inventory Ledger Posting, Idempotency, Snapshots, and Referential Integrity.
All tests run 100% isolated via the autouse fixture in conftest.py.
"""

import sqlite3
import pytest
from fastapi.testclient import TestClient

from app.db import get_connection
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def base_entities(client):
    """Sets up an active supplier and two active products for procurement tests."""
    # 1. Supplier
    sup_res = client.post(
        "/api/suppliers",
        json={
            "code": "SUP-OCEAN-01",
            "name": "Ocean Harvest Exporters",
            "country": "IN",
            "currency": "INR",
            "payment_terms": "Net 30",
        },
        headers={"X-User-Role": "procurement"},
    )
    assert sup_res.status_code == 201
    supplier = sup_res.json()

    # 2. Product 1 (Shrimp)
    p1_res = client.post(
        "/api/products",
        json={
            "sku": "SKU-SHRIMP-BLK",
            "name": "Black Tiger Shrimp Headless",
            "category": "Seafood",
            "uom": "KG",
            "default_purchase_cost": 500.0,
            "default_selling_price": 750.0,
            "tax_rate_pct": 5.0,
            "is_active": True,
        },
        headers={"X-User-Role": "procurement"},
    )
    assert p1_res.status_code == 201
    product1 = p1_res.json()

    # 3. Product 2 (Packaging Box)
    p2_res = client.post(
        "/api/products",
        json={
            "sku": "SKU-CARTON-10KG",
            "name": "Master Corrugated Carton 10kg",
            "category": "Packaging",
            "uom": "PCS",
            "default_purchase_cost": 45.0,
            "default_selling_price": 60.0,
            "tax_rate_pct": 18.0,
            "is_active": True,
        },
        headers={"X-User-Role": "procurement"},
    )
    assert p2_res.status_code == 201
    product2 = p2_res.json()

    return {
        "supplier": supplier,
        "product1": product1,
        "product2": product2,
    }


# ===========================================================================
# 1. Purchase Order Creation, Line Validation, and Totals
# ===========================================================================

def test_purchase_order_lifecycle_and_validation(client, base_entities):
    sup = base_entities["supplier"]
    p1 = base_entities["product1"]
    p2 = base_entities["product2"]

    # 1. Validation: negative/zero quantity rejected
    bad_qty = client.post(
        "/api/purchase-orders",
        json={
            "po_number": "PO-2026-TEST-01",
            "supplier_id": sup["id"],
            "order_date": "2026-10-14",
            "items": [{"product_id": p1["id"], "ordered_qty": -5, "unit_price": 500.0}],
        },
        headers={"X-User-Role": "procurement"},
    )
    assert bad_qty.status_code == 422 or bad_qty.status_code == 400

    # 2. Validation: inactive product rejected
    client.patch(f"/api/products/{p1['id']}", json={"is_active": False}, headers={"X-User-Role": "admin"})
    bad_prod = client.post(
        "/api/purchase-orders",
        json={
            "po_number": "PO-2026-TEST-01",
            "supplier_id": sup["id"],
            "order_date": "2026-10-14",
            "items": [{"product_id": p1["id"], "ordered_qty": 10, "unit_price": 500.0}],
        },
        headers={"X-User-Role": "procurement"},
    )
    assert bad_prod.status_code == 400
    assert "inactive" in bad_prod.json()["detail"].lower()
    # Reactivate
    client.patch(f"/api/products/{p1['id']}", json={"is_active": True}, headers={"X-User-Role": "admin"})

    # 3. Create Valid PO with multiple lines
    po_payload = {
        "po_number": "PO-2026-0001",
        "supplier_id": sup["id"],
        "order_date": "2026-10-14",
        "expected_delivery_date": "2026-10-25",
        "currency": "INR",
        "payment_terms": "Net 30",
        "notes": "Export grade frozen batch raw materials",
        "items": [
            {"product_id": p1["id"], "ordered_qty": 100.0, "unit_price": 500.0, "tax_rate_pct": 5.0},
            {"product_id": p2["id"], "ordered_qty": 50.0, "unit_price": 40.0, "tax_rate_pct": 18.0},
        ],
    }
    res = client.post("/api/purchase-orders", json=po_payload, headers={"X-User-Role": "procurement"})
    assert res.status_code == 201
    po = res.json()
    assert po["po_number"] == "PO-2026-0001"
    assert po["status"] == "draft"

    # Line 1: 100 * 500 = 50,000, Tax 5% = 2,500
    # Line 2: 50 * 40 = 2,000, Tax 18% = 360
    # Subtotal: 52,000, Tax: 2,860, Grand Total: 54,860
    assert po["subtotal"] == 52000.0
    assert po["tax_total"] == 2860.0
    assert po["grand_total"] == 54860.0
    po_id = po["id"]

    # 4. Duplicate PO number rejected (Case-insensitive)
    dup_res = client.post(
        "/api/purchase-orders",
        json={**po_payload, "po_number": "po-2026-0001"},
        headers={"X-User-Role": "procurement"},
    )
    assert dup_res.status_code == 409

    # 5. Transition to Submitted -> Approved
    sub_res = client.post(f"/api/purchase-orders/{po_id}/submit", headers={"X-User-Role": "procurement"})
    assert sub_res.status_code == 200
    assert sub_res.json()["status"] == "submitted"

    appr_res = client.post(f"/api/purchase-orders/{po_id}/approve", headers={"X-User-Role": "admin"})
    assert appr_res.status_code == 200
    assert appr_res.json()["status"] == "approved"

    # 6. Once approved, modifying lines is rejected
    edit_res = client.patch(
        f"/api/purchase-orders/{po_id}",
        json={"items": [{"product_id": p1["id"], "ordered_qty": 200, "unit_price": 500.0}]},
        headers={"X-User-Role": "procurement"},
    )
    assert edit_res.status_code == 400


# ===========================================================================
# 2. Server-Side Permissions (RBAC)
# ===========================================================================

def test_procurement_rbac(client, base_entities):
    sup = base_entities["supplier"]
    p1 = base_entities["product1"]

    po_payload = {
        "po_number": "PO-RBAC-01",
        "supplier_id": sup["id"],
        "order_date": "2026-10-14",
        "items": [{"product_id": p1["id"], "ordered_qty": 10.0, "unit_price": 500.0}],
    }

    # 1. Viewer CANNOT create PO
    v_res = client.post("/api/purchase-orders", json=po_payload, headers={"X-User-Role": "viewer"})
    assert v_res.status_code == 403

    # 2. Procurement CAN create PO
    p_res = client.post("/api/purchase-orders", json=po_payload, headers={"X-User-Role": "procurement"})
    assert p_res.status_code == 201
    po_id = p_res.json()["id"]

    # 3. Procurement CANNOT approve PO (Admin only)
    p_appr = client.post(f"/api/purchase-orders/{po_id}/approve", headers={"X-User-Role": "procurement"})
    assert p_appr.status_code == 403

    # 4. Admin CAN approve PO
    a_appr = client.post(f"/api/purchase-orders/{po_id}/approve", headers={"X-User-Role": "admin"})
    assert a_appr.status_code == 200


# ===========================================================================
# 3. Goods Receipts: Partial Delivery, Over-Receipt Prevention & QA
# ===========================================================================

def test_goods_receipts_partial_and_overreceipt_prevention(client, base_entities):
    sup = base_entities["supplier"]
    p1 = base_entities["product1"]

    # Create & Approve PO for 100 units
    po = client.post(
        "/api/purchase-orders",
        json={
            "po_number": "PO-PARTIAL-01",
            "supplier_id": sup["id"],
            "order_date": "2026-10-14",
            "items": [{"product_id": p1["id"], "ordered_qty": 100.0, "unit_price": 500.0, "tax_rate_pct": 5.0}],
        },
        headers={"X-User-Role": "procurement"},
    ).json()
    po_id = po["id"]
    po_item_id = po["items"][0]["id"]
    client.post(f"/api/purchase-orders/{po_id}/approve", headers={"X-User-Role": "admin"})

    # 1. Over-receipt rejection: attempt receiving 150 units against 100
    bad_gr = client.post(
        "/api/goods-receipts",
        json={
            "receipt_number": "GR-FAIL-OVER",
            "idempotency_key": "idemp-over-01",
            "po_id": po_id,
            "receipt_date": "2026-10-15",
            "items": [
                {
                    "po_item_id": po_item_id,
                    "received_qty": 150.0,
                    "accepted_qty": 150.0,
                    "rejected_qty": 0.0,
                    "quarantined_qty": 0.0,
                }
            ],
        },
        headers={"X-User-Role": "warehouse"},
    )
    assert bad_gr.status_code == 409
    assert "over-receipt" in bad_gr.json()["detail"].lower()

    # 2. First Partial Receipt: 40 units (35 accepted, 5 quarantined)
    gr1_res = client.post(
        "/api/goods-receipts",
        json={
            "receipt_number": "GR-2026-0001",
            "idempotency_key": "idemp-gr-0001",
            "po_id": po_id,
            "receipt_date": "2026-10-15",
            "items": [
                {
                    "po_item_id": po_item_id,
                    "received_qty": 40.0,
                    "accepted_qty": 35.0,
                    "rejected_qty": 0.0,
                    "quarantined_qty": 5.0,
                    "inspection_notes": "5kg pack under temperature observation",
                }
            ],
        },
        headers={"X-User-Role": "warehouse"},
    )
    assert gr1_res.status_code == 201
    gr1 = gr1_res.json()
    assert gr1["items"][0]["received_qty"] == 40.0
    assert gr1["items"][0]["accepted_qty"] == 35.0
    assert gr1["items"][0]["quarantined_qty"] == 5.0

    # Verify PO status changed to partially_received
    po_check = client.get(f"/api/purchase-orders/{po_id}").json()
    assert po_check["status"] == "partially_received"
    assert po_check["items"][0]["received_qty"] == 40.0

    # 3. Post first receipt to inventory
    post1 = client.post(
        f"/api/goods-receipts/{gr1['id']}/post?idempotency_key=post-gr-0001",
        headers={"X-User-Role": "admin"},
    )
    assert post1.status_code == 200
    assert post1.json()["status"] == "posted"

    # Check stock balances: 35 available, 5 quarantined
    bal_res = client.get("/api/inventory/balances").json()
    items = bal_res["items"]
    avail = next(b for b in items if b["product_id"] == p1["id"] and b["stock_type"] == "available")
    quar = next(b for b in items if b["product_id"] == p1["id"] and b["stock_type"] == "quarantined")
    assert avail["on_hand_qty"] == 35.0
    assert quar["on_hand_qty"] == 5.0

    # 4. Attempting to cancel PO now must fail because receipts exist!
    cancel_res = client.post(f"/api/purchase-orders/{po_id}/cancel", headers={"X-User-Role": "admin"})
    assert cancel_res.status_code == 409

    # 5. Over-receipt check on second receipt: remaining is 60. Attempting 70 must fail!
    bad_gr2 = client.post(
        "/api/goods-receipts",
        json={
            "receipt_number": "GR-FAIL-OVER-2",
            "idempotency_key": "idemp-over-02",
            "po_id": po_id,
            "receipt_date": "2026-10-16",
            "items": [{"po_item_id": po_item_id, "received_qty": 70.0, "accepted_qty": 70.0}],
        },
        headers={"X-User-Role": "warehouse"},
    )
    assert bad_gr2.status_code == 409

    # 6. Second Receipt: exactly 60 units (50 accepted, 10 rejected due to broken seal)
    gr2_res = client.post(
        "/api/goods-receipts",
        json={
            "receipt_number": "GR-2026-0002",
            "idempotency_key": "idemp-gr-0002",
            "po_id": po_id,
            "receipt_date": "2026-10-16",
            "items": [
                {
                    "po_item_id": po_item_id,
                    "received_qty": 60.0,
                    "accepted_qty": 50.0,
                    "rejected_qty": 10.0,
                    "quarantined_qty": 0.0,
                    "rejection_reason": "Broken vacuum seal on 10 bags",
                }
            ],
        },
        headers={"X-User-Role": "warehouse"},
    )
    assert gr2_res.status_code == 201

    # Verify PO status is now fully_received!
    po_check2 = client.get(f"/api/purchase-orders/{po_id}").json()
    assert po_check2["status"] == "fully_received"
    assert po_check2["items"][0]["received_qty"] == 100.0

    # Post second receipt
    client.post(
        f"/api/goods-receipts/{gr2_res.json()['id']}/post?idempotency_key=post-gr-0002",
        headers={"X-User-Role": "admin"},
    )

    # Check updated balances: available = 35 + 50 = 85, quarantined = 5, rejected = 10
    bal_after = client.get("/api/inventory/balances").json()["items"]
    avail_after = next(b for b in bal_after if b["product_id"] == p1["id"] and b["stock_type"] == "available")
    rej_after = next(b for b in bal_after if b["product_id"] == p1["id"] and b["stock_type"] == "rejected")
    assert avail_after["on_hand_qty"] == 85.0
    assert rej_after["on_hand_qty"] == 10.0


# ===========================================================================
# 4. Exactly-Once Posting & Idempotency
# ===========================================================================

def test_idempotency_and_exactly_once_posting(client, base_entities):
    sup = base_entities["supplier"]
    p2 = base_entities["product2"]

    po = client.post(
        "/api/purchase-orders",
        json={
            "po_number": "PO-IDEMP-01",
            "supplier_id": sup["id"],
            "order_date": "2026-10-14",
            "items": [{"product_id": p2["id"], "ordered_qty": 20.0, "unit_price": 40.0}],
        },
        headers={"X-User-Role": "procurement"},
    ).json()
    client.post(f"/api/purchase-orders/{po['id']}/approve", headers={"X-User-Role": "admin"})

    gr_payload = {
        "receipt_number": "GR-IDEMP-01",
        "idempotency_key": "unique-client-key-9999",
        "po_id": po["id"],
        "receipt_date": "2026-10-15",
        "items": [{"po_item_id": po["items"][0]["id"], "received_qty": 20.0, "accepted_qty": 20.0}],
    }

    # 1. Create Receipt
    gr1 = client.post("/api/goods-receipts", json=gr_payload, headers={"X-User-Role": "warehouse"}).json()
    gr_id = gr1["id"]

    # 2. Retrying identical receipt creation returns same receipt without duplicating lines
    gr2 = client.post("/api/goods-receipts", json=gr_payload, headers={"X-User-Role": "warehouse"}).json()
    assert gr2["id"] == gr_id

    # 3. Post Receipt to inventory
    post_res1 = client.post(
        f"/api/goods-receipts/{gr_id}/post?idempotency_key=post-key-unique",
        headers={"X-User-Role": "admin"},
    )
    assert post_res1.status_code == 200
    assert post_res1.json()["status"] == "posted"

    # 4. Repeated posting returns "already_posted" status and DOES NOT double inventory
    post_res2 = client.post(
        f"/api/goods-receipts/{gr_id}/post?idempotency_key=post-key-unique",
        headers={"X-User-Role": "admin"},
    )
    assert post_res2.status_code == 200
    assert post_res2.json()["status"] == "already_posted"

    # Verify inventory is exactly 20 (not 40!)
    bal = client.get("/api/inventory/balances?stock_type=available").json()["items"]
    p2_bal = next(b for b in bal if b["product_id"] == p2["id"])
    assert p2_bal["on_hand_qty"] == 20.0


# ===========================================================================
# 5. Immutable Snapshots & Referential Integrity
# ===========================================================================

def test_immutable_snapshots_and_deletion_restriction(client, base_entities):
    sup = base_entities["supplier"]
    p1 = base_entities["product1"]

    po = client.post(
        "/api/purchase-orders",
        json={
            "po_number": "PO-SNAPSHOT-01",
            "supplier_id": sup["id"],
            "order_date": "2026-10-14",
            "items": [{"product_id": p1["id"], "ordered_qty": 10.0, "unit_price": 500.0}],
        },
        headers={"X-User-Role": "procurement"},
    ).json()

    # Verify PO line snapshot
    item_before = po["items"][0]
    assert item_before["sku"] == "SKU-SHRIMP-BLK"
    assert item_before["product_name"] == "Black Tiger Shrimp Headless"
    assert item_before["unit_price"] == 500.0

    # 1. Modify the Product Master (change SKU, Name, and Price)
    client.patch(
        f"/api/products/{p1['id']}",
        json={
            "sku": "SKU-SHRIMP-REVISED",
            "name": "Black Tiger Shrimp Premium IQF",
            "default_purchase_cost": 650.0,
        },
        headers={"X-User-Role": "admin"},
    )

    # 2. Inspect PO line: Snapshot MUST remain 100% unchanged!
    po_after = client.get(f"/api/purchase-orders/{po['id']}").json()
    item_after = po_after["items"][0]
    assert item_after["sku"] == "SKU-SHRIMP-BLK"
    assert item_after["product_name"] == "Black Tiger Shrimp Headless"
    assert item_after["unit_price"] == 500.0

    # 3. Master Data Referential Protection:
    # Attempting to DELETE product referenced by PO must fail with HTTP 409!
    del_prod = client.delete(f"/api/products/{p1['id']}", headers={"X-User-Role": "admin"})
    assert del_prod.status_code == 409
    assert "referenced by" in del_prod.json()["detail"].lower()

    # Attempting to DELETE supplier referenced by PO must fail with HTTP 409!
    del_sup = client.delete(f"/api/suppliers/{sup['id']}", headers={"X-User-Role": "admin"})
    assert del_sup.status_code == 409
    assert "referenced by" in del_sup.json()["detail"].lower()

    # 4. Safe deactivation (is_active = False / status = 'inactive') is allowed
    deact_prod = client.patch(f"/api/products/{p1['id']}", json={"is_active": False}, headers={"X-User-Role": "admin"})
    assert deact_prod.status_code == 200
    assert deact_prod.json()["is_active"] is False

    deact_sup = client.patch(f"/api/suppliers/{sup['id']}", json={"status": "inactive"}, headers={"X-User-Role": "admin"})
    assert deact_sup.status_code == 200
    assert deact_sup.json()["status"] == "inactive"


# ===========================================================================
# 6. Database Integrity & Append-Only Trigger Verification
# ===========================================================================

def test_sqlite_integrity_and_ledger_immutability():
    with get_connection() as conn:
        # Check integrity
        integ = conn.execute("PRAGMA integrity_check").fetchone()[0]
        assert integ == "ok"

        # Check foreign keys
        fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        assert len(fk_violations) == 0

        # Insert product first to satisfy foreign key
        conn.execute(
            """
            INSERT INTO products (id, sku, name, created_at, updated_at)
            VALUES ('prod-immut-1', 'SKU-IMMUT-1', 'Immutability Test Product', '2026-10-14', '2026-10-14')
            """
        )

        # Test append-only trigger on inventory_movements
        conn.execute(
            """
            INSERT INTO inventory_movements (
                id, movement_number, idempotency_key, movement_type,
                reference_doc_type, reference_doc_id, product_id, sku,
                quantity, stock_type, unit_cost, total_cost, performed_by, created_at
            ) VALUES ('mov-immut-1', 'MOV-IMMUT-1', 'key-immut-1', 'RECEIPT_POST', 'gr', 'gr-1', 'prod-immut-1', 'SKU-IMMUT-1', 10, 'available', 10, 100, 'Test', '2026-10-14')
            """
        )
        conn.commit()

        # Update must be aborted by trigger
        with pytest.raises(sqlite3.DatabaseError, match="Inventory movements are append-only"):
            conn.execute("UPDATE inventory_movements SET quantity = 99 WHERE id = 'mov-immut-1'")

        # Delete must be aborted by trigger
        with pytest.raises(sqlite3.DatabaseError, match="Inventory movements cannot be deleted"):
            conn.execute("DELETE FROM inventory_movements WHERE id = 'mov-immut-1'")
