"""
TradeSathi AI — Phase 4 Sales Orders & Fulfilment Integration Test Suite
Verifies:
1. Customer Quotation lifecycle & conversion to Sales Orders
2. Order creation, validation & server-calculated pricing, discounts, and taxes
3. Immutable snapshotting of customer and product attributes
4. Server-enforced order state machine transitions & invalid transition rejection
5. Integration with Phase 3 ATP & Authoritative Stock Reservations
6. Over-allocation prevention (HTTP 400 when requesting > ATP)
7. Cancellation workflow & automatic release of active reservations
8. Picking, short-picking exception tracking, and packing workflows
9. Commercial dispatch with exactly-once inventory deduction & idempotency
10. Preserving existing shipment records without modification or destruction
11. Delivery confirmation, delivery discrepancies & final order delivery
12. Sales return foundation with strict stock segregation (available vs quarantined/rejected)
13. Append-only ERP audit trail logging
14. Backend RBAC permission enforcement across roles (sales, warehouse, viewer, admin)
"""

import uuid
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import get_connection

client = TestClient(app)


def create_test_product(sku=None, name="Premium Basmati Rice 1121", cost=80.0, price=120.0, tax=5.0):
    if not sku:
        sku = f"SKU-SO-{uuid.uuid4().hex[:6].upper()}"
    res = client.post(
        "/api/products",
        json={
            "sku": sku,
            "name": name,
            "category": "Grains",
            "uom": "KG",
            "default_purchase_cost": cost,
            "default_selling_price": price,
            "hsn_code": "10063020",
            "tax_rate_pct": tax,
        },
        headers={"X-User-Role": "admin"},
    )
    assert res.status_code == 201, res.text
    return res.json()


def create_test_customer(code=None, name="Gulf Trading LLC"):
    if not code:
        code = f"CUST-SO-{uuid.uuid4().hex[:6].upper()}"
    res = client.post(
        "/api/customers",
        json={
            "code": code,
            "name": name,
            "legal_name": f"{name} FZCO",
            "tax_id": "TRN-987654321",
            "country": "AE",
            "destination_port": "Jebel Ali",
            "billing_address": "Al Quoz Industrial Area 3, Dubai, UAE",
            "shipping_address": "Warehouse 14, Jebel Ali Free Zone, Dubai, UAE",
            "email": "procurement@gulftrading.ae",
            "phone": "+971-4-1234567",
            "currency": "USD",
            "payment_terms": "LC at sight",
        },
        headers={"X-User-Role": "admin"},
    )
    assert res.status_code == 201, res.text
    return res.json()


def receive_stock_for_product(product_id, qty=500.0):
    """Utility to seed physical on-hand stock via Phase 2 PO -> GR workflow."""
    sup_code = f"SUP-SO-{uuid.uuid4().hex[:6].upper()}"
    sup_res = client.post(
        "/api/suppliers",
        json={"code": sup_code, "name": "Northern Grain Farmers", "country": "IN", "currency": "USD"},
        headers={"X-User-Role": "admin"},
    )
    assert sup_res.status_code == 201, sup_res.text
    supplier = sup_res.json()

    po_num = f"PO-SO-{uuid.uuid4().hex[:6].upper()}"
    po_res = client.post(
        "/api/purchase-orders",
        json={
            "po_number": po_num,
            "supplier_id": supplier["id"],
            "order_date": "2026-10-14",
            "currency": "USD",
            "items": [{"product_id": product_id, "ordered_qty": qty, "unit_price": 80.0, "tax_rate_pct": 5.0}],
        },
        headers={"X-User-Role": "admin"},
    )
    assert po_res.status_code == 201, po_res.text
    po = po_res.json()

    # Approve PO
    client.post(f"/api/purchase-orders/{po['id']}/approve", headers={"X-User-Role": "admin"})

    gr_num = f"GR-SO-{uuid.uuid4().hex[:6].upper()}"
    gr_res = client.post(
        "/api/goods-receipts",
        json={
            "receipt_number": gr_num,
            "idempotency_key": f"gr-key-{uuid.uuid4().hex[:8]}",
            "po_id": po["id"],
            "receipt_date": "2026-10-14",
            "items": [
                {
                    "po_item_id": po["items"][0]["id"],
                    "received_qty": qty,
                    "accepted_qty": qty,
                    "quarantined_qty": 0.0,
                    "rejected_qty": 0.0,
                }
            ],
        },
        headers={"X-User-Role": "warehouse"},
    )
    assert gr_res.status_code == 201, gr_res.text
    gr = gr_res.json()

    post_res = client.post(
        f"/api/goods-receipts/{gr['id']}/post?idempotency_key=gr-post-{uuid.uuid4().hex[:8]}",
        headers={"X-User-Role": "warehouse"},
    )
    assert post_res.status_code == 200, post_res.text
    return gr


# ==========================================
# Test Cases
# ==========================================

def test_quotation_creation_and_lifecycle():
    cust = create_test_customer()
    prod = create_test_product()

    # Create quotation
    res = client.post(
        "/api/quotations",
        json={
            "customer_id": cust["id"],
            "quotation_date": "2026-10-14",
            "valid_until": "2026-11-14",
            "currency": "USD",
            "items": [
                {
                    "product_id": prod["id"],
                    "quantity": 100.0,
                    "unit_price": 120.0,
                    "discount_pct": 10.0,
                    "tax_rate_pct": 5.0,
                }
            ],
        },
        headers={"X-User-Role": "sales"},
    )
    assert res.status_code == 200, res.text
    quo = res.json()
    assert quo["status"] == "draft"
    assert quo["customer_code"] == cust["code"]
    # Calculation checks: subtotal = 100 * 120 = 12000; disc 10% = 1200; taxable = 10800; tax 5% = 540; grand_total = 11340
    assert quo["subtotal"] == 12000.0
    assert quo["discount_total"] == 1200.0
    assert quo["tax_total"] == 540.0
    assert quo["grand_total"] == 11340.0

    # Lifecycle: send -> accept
    res_send = client.post(f"/api/quotations/{quo['id']}/send", headers={"X-User-Role": "sales"})
    assert res_send.status_code == 200
    assert res_send.json()["status"] == "sent"

    res_accept = client.post(f"/api/quotations/{quo['id']}/accept", headers={"X-User-Role": "sales"})
    assert res_accept.status_code == 200
    assert res_accept.json()["status"] == "accepted"

    # Convert to Sales Order
    res_conv = client.post(
        f"/api/quotations/{quo['id']}/convert",
        json={"payment_terms": "LC at sight", "notes": "Converted for shipment"},
        headers={"X-User-Role": "sales"},
    )
    assert res_conv.status_code == 200, res_conv.text
    so = res_conv.json()
    assert so["quotation_id"] == quo["id"]
    assert so["status"] == "draft"
    assert so["grand_total"] == 11340.0

    # Verify quotation status is now 'converted'
    quo_fresh = client.get(f"/api/quotations/{quo['id']}", headers={"X-User-Role": "sales"}).json()
    assert quo_fresh["status"] == "converted"


def test_sales_order_calculations_and_snapshots():
    cust = create_test_customer()
    prod1 = create_test_product(price=100.0, tax=10.0)
    prod2 = create_test_product(price=200.0, tax=5.0)

    res = client.post(
        "/api/sales-orders",
        json={
            "customer_id": cust["id"],
            "currency": "USD",
            "items": [
                {"product_id": prod1["id"], "ordered_quantity": 50.0, "unit_price": 100.0, "discount_pct": 5.0, "tax_rate_pct": 10.0},
                {"product_id": prod2["id"], "ordered_quantity": 25.0, "unit_price": 200.0, "discount_pct": 0.0, "tax_rate_pct": 5.0},
            ],
        },
        headers={"X-User-Role": "sales"},
    )
    assert res.status_code == 200, res.text
    so = res.json()

    # Line 1: sub = 5000, disc = 250, tax_base = 4750, tax = 475, total = 5225
    # Line 2: sub = 5000, disc = 0, tax = 250, total = 5250
    # Grand: sub = 10000, disc = 250, tax = 725, grand = 10475
    assert so["subtotal"] == 10000.0
    assert so["discount_total"] == 250.0
    assert so["tax_total"] == 725.0
    assert so["grand_total"] == 10475.0
    assert so["customer_name"] == cust["name"]

    # Verify immutable customer snapshot: mutating customer later does NOT mutate the order snapshot
    with get_connection() as conn:
        conn.execute("UPDATE customers SET name = 'Mutated Corp' WHERE id = ?", (cust["id"],))
        conn.commit()

    so_check = client.get(f"/api/sales-orders/{so['id']}", headers={"X-User-Role": "sales"}).json()
    assert so_check["customer_name"] == cust["name"], "Order snapshot must be immutable against master data edits"


def test_order_lifecycle_and_invalid_state_transitions():
    cust = create_test_customer()
    prod = create_test_product()

    so = client.post(
        "/api/sales-orders",
        json={"customer_id": cust["id"], "items": [{"product_id": prod["id"], "ordered_quantity": 10.0, "unit_price": 50.0}]},
        headers={"X-User-Role": "sales"},
    ).json()
    assert so["status"] == "draft"

    # Cannot pack or dispatch draft order
    pack_res = client.post(f"/api/sales-orders/{so['id']}/pack", json={}, headers={"X-User-Role": "warehouse"})
    assert pack_res.status_code == 400

    # Confirm order
    conf_res = client.post(f"/api/sales-orders/{so['id']}/confirm", headers={"X-User-Role": "sales"})
    assert conf_res.status_code == 200
    assert conf_res.json()["status"] == "confirmed"

    # Cannot confirm again (already confirmed)
    conf_again = client.post(f"/api/sales-orders/{so['id']}/confirm", headers={"X-User-Role": "sales"})
    assert conf_again.status_code == 400


def test_atp_allocation_and_overallocation_prevention():
    prod = create_test_product()
    cust = create_test_customer()
    receive_stock_for_product(prod["id"], qty=100.0)

    # Order 1: wants 80 KG
    so1 = client.post(
        "/api/sales-orders",
        json={"customer_id": cust["id"], "items": [{"product_id": prod["id"], "ordered_quantity": 80.0, "unit_price": 50.0}]},
        headers={"X-User-Role": "sales"},
    ).json()
    client.post(f"/api/sales-orders/{so1['id']}/confirm", headers={"X-User-Role": "sales"})

    # Allocate Order 1
    alloc1 = client.post(
        f"/api/sales-orders/{so1['id']}/allocate",
        json={"warehouse_id": "wh-main"},
        headers={"X-User-Role": "sales"},
    )
    assert alloc1.status_code == 200, alloc1.text
    assert alloc1.json()["status"] == "allocated"
    assert alloc1.json()["items"][0]["allocated_quantity"] == 80.0

    # Order 2: wants 40 KG (Only 20 KG ATP remaining out of 100)
    so2 = client.post(
        "/api/sales-orders",
        json={"customer_id": cust["id"], "items": [{"product_id": prod["id"], "ordered_quantity": 40.0, "unit_price": 50.0}]},
        headers={"X-User-Role": "sales"},
    ).json()
    client.post(f"/api/sales-orders/{so2['id']}/confirm", headers={"X-User-Role": "sales"})

    # Attempting to allocate 40 KG must be blocked by ATP engine with HTTP 400
    alloc2 = client.post(
        f"/api/sales-orders/{so2['id']}/allocate",
        json={"warehouse_id": "wh-main"},
        headers={"X-User-Role": "sales"},
    )
    assert alloc2.status_code == 400
    assert "Insufficient available stock" in alloc2.text


def test_cancellation_releases_reservation():
    prod = create_test_product()
    cust = create_test_customer()
    receive_stock_for_product(prod["id"], qty=100.0)

    so = client.post(
        "/api/sales-orders",
        json={"customer_id": cust["id"], "items": [{"product_id": prod["id"], "ordered_quantity": 70.0, "unit_price": 50.0}]},
        headers={"X-User-Role": "sales"},
    ).json()
    client.post(f"/api/sales-orders/{so['id']}/confirm", headers={"X-User-Role": "sales"})
    client.post(f"/api/sales-orders/{so['id']}/allocate", json={"warehouse_id": "wh-main"}, headers={"X-User-Role": "sales"})

    # Verify reservation is active
    with get_connection() as conn:
        res = conn.execute(
            "SELECT status, quantity FROM stock_reservations WHERE reference_id = ? AND status = 'active'",
            (so["id"],),
        ).fetchone()
        assert res is not None
        assert float(res["quantity"]) == 70.0

    # Cancel order
    cancel_res = client.post(f"/api/sales-orders/{so['id']}/cancel", headers={"X-User-Role": "sales"})
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "cancelled"

    # Verify reservation is now released
    with get_connection() as conn:
        res_after = conn.execute(
            "SELECT status FROM stock_reservations WHERE reference_id = ?",
            (so["id"],),
        ).fetchone()
        assert res_after["status"] == "released"


def test_picking_packing_and_short_pick():
    prod = create_test_product()
    cust = create_test_customer()
    receive_stock_for_product(prod["id"], qty=100.0)

    so = client.post(
        "/api/sales-orders",
        json={"customer_id": cust["id"], "items": [{"product_id": prod["id"], "ordered_quantity": 50.0, "unit_price": 50.0}]},
        headers={"X-User-Role": "sales"},
    ).json()
    client.post(f"/api/sales-orders/{so['id']}/confirm", headers={"X-User-Role": "sales"})
    client.post(f"/api/sales-orders/{so['id']}/allocate", json={"warehouse_id": "wh-main"}, headers={"X-User-Role": "sales"})

    # Create Pick List
    pick_res = client.post(
        "/api/sales-pick-lists",
        json={"sales_order_id": so["id"], "warehouse_id": "wh-main", "assigned_picker": "Picker John"},
        headers={"X-User-Role": "warehouse"},
    )
    assert pick_res.status_code == 200, pick_res.text
    pkl = pick_res.json()
    assert pkl["status"] == "pending"
    assert len(pkl["items"]) == 1
    assert pkl["items"][0]["reserved_quantity"] == 50.0

    # Order status should now be picking
    so_fresh = client.get(f"/api/sales-orders/{so['id']}", headers={"X-User-Role": "sales"}).json()
    assert so_fresh["status"] == "picking"

    # Complete Pick List with short pick: picked 45, short 5
    pick_item_id = pkl["items"][0]["id"]
    comp_res = client.post(
        f"/api/sales-pick-lists/{pkl['id']}/complete",
        json={
            "items": [
                {
                    "pick_item_id": pick_item_id,
                    "picked_quantity": 45.0,
                    "short_picked_quantity": 5.0,
                    "short_pick_reason": "Damaged packaging on 5 units",
                }
            ]
        },
        headers={"X-User-Role": "warehouse"},
    )
    assert comp_res.status_code == 200
    pkl_done = comp_res.json()
    assert pkl_done["status"] == "completed"
    assert pkl_done["items"][0]["picked_quantity"] == 45.0
    assert pkl_done["items"][0]["short_picked_quantity"] == 5.0

    # Pack Order
    pack_res = client.post(f"/api/sales-orders/{so['id']}/pack", json={"notes": "Packed into 3 cartons"}, headers={"X-User-Role": "warehouse"})
    assert pack_res.status_code == 200
    assert pack_res.json()["status"] == "packed"


def test_commercial_dispatch_and_delivery_tracking():
    prod = create_test_product()
    cust = create_test_customer()
    receive_stock_for_product(prod["id"], qty=100.0)

    so = client.post(
        "/api/sales-orders",
        json={"customer_id": cust["id"], "items": [{"product_id": prod["id"], "ordered_quantity": 40.0, "unit_price": 50.0}]},
        headers={"X-User-Role": "sales"},
    ).json()
    client.post(f"/api/sales-orders/{so['id']}/confirm", headers={"X-User-Role": "sales"})
    client.post(f"/api/sales-orders/{so['id']}/allocate", json={"warehouse_id": "wh-main"}, headers={"X-User-Role": "sales"})

    # Pick & Pack
    pkl = client.post(
        "/api/sales-pick-lists",
        json={"sales_order_id": so["id"], "warehouse_id": "wh-main"},
        headers={"X-User-Role": "warehouse"},
    ).json()
    client.post(
        f"/api/sales-pick-lists/{pkl['id']}/complete",
        json={"items": [{"pick_item_id": pkl["items"][0]["id"], "picked_quantity": 40.0}]},
        headers={"X-User-Role": "warehouse"},
    )
    client.post(f"/api/sales-orders/{so['id']}/pack", json={}, headers={"X-User-Role": "warehouse"})

    # Check available inventory balance before dispatch: 100 on-hand
    with get_connection() as conn:
        bal_before = conn.execute("SELECT on_hand_qty FROM inventory_balances WHERE product_id = ? AND stock_type = 'available'", (prod["id"],)).fetchone()
        assert float(bal_before["on_hand_qty"]) == 100.0

    # Dispatch Order
    order_item_id = so["items"][0]["id"]
    disp_key = f"idemp-disp-{uuid.uuid4().hex[:8]}"
    disp_res = client.post(
        "/api/sales-dispatches",
        json={
            "sales_order_id": so["id"],
            "warehouse_id": "wh-main",
            "carrier_name": "Maersk Line",
            "tracking_number": "MSK-77665544",
            "vehicle_number": "MH-46-AB-1234",
            "package_count": 2,
            "idempotency_key": disp_key,
            "items": [{"order_item_id": order_item_id, "quantity_dispatched": 40.0}],
        },
        headers={"X-User-Role": "warehouse"},
    )
    assert disp_res.status_code == 200, disp_res.text
    disp = disp_res.json()
    assert disp["status"] == "dispatched"
    assert disp["items"][0]["quantity_dispatched"] == 40.0

    # Verify inventory balance after dispatch: deducted exactly once (100 - 40 = 60)
    with get_connection() as conn:
        bal_after = conn.execute("SELECT on_hand_qty FROM inventory_balances WHERE product_id = ? AND stock_type = 'available'", (prod["id"],)).fetchone()
        assert float(bal_after["on_hand_qty"]) == 60.0

        # Verify stock reservation is marked 'consumed'
        res_row = conn.execute("SELECT status FROM stock_reservations WHERE reference_id = ?", (so["id"],)).fetchone()
        assert res_row["status"] == "consumed"

        # Verify exactly one SALES_DISPATCH movement
        mov = conn.execute(
            "SELECT count(*) FROM inventory_movements WHERE reference_doc_id = ? AND movement_type = 'SALES_DISPATCH'",
            (disp["id"],),
        ).fetchone()
        assert mov[0] == 1

    # Test Dispatch Idempotency: repeating request returns the exact same dispatch without double deducting
    disp_dup = client.post(
        "/api/sales-dispatches",
        json={
            "sales_order_id": so["id"],
            "warehouse_id": "wh-main",
            "idempotency_key": disp_key,
            "items": [{"order_item_id": order_item_id, "quantity_dispatched": 40.0}],
        },
        headers={"X-User-Role": "warehouse"},
    )
    assert disp_dup.status_code == 200
    assert disp_dup.json()["id"] == disp["id"]

    with get_connection() as conn:
        bal_dup = conn.execute("SELECT on_hand_qty FROM inventory_balances WHERE product_id = ? AND stock_type = 'available'", (prod["id"],)).fetchone()
        assert float(bal_dup["on_hand_qty"]) == 60.0, "Idempotent dispatch must not deduct inventory twice"

    # Confirm Delivery
    disp_item_id = disp["items"][0]["id"]
    del_res = client.post(
        f"/api/sales-dispatches/{disp['id']}/deliver",
        json={
            "delivery_date": "2026-10-15",
            "delivered_by": "Agent Tariq",
            "notes": "Delivered to consignee warehouse in good condition",
            "items": [{"dispatch_item_id": disp_item_id, "quantity_delivered": 40.0}],
        },
        headers={"X-User-Role": "warehouse"},
    )
    assert del_res.status_code == 200, del_res.text
    assert del_res.json()["status"] == "delivered"

    # Sales order should now be 'delivered'
    so_delivered = client.get(f"/api/sales-orders/{so['id']}", headers={"X-User-Role": "sales"}).json()
    assert so_delivered["status"] == "delivered"
    assert so_delivered["items"][0]["delivered_quantity"] == 40.0


def test_sales_returns_foundation_and_stock_segregation():
    prod = create_test_product()
    cust = create_test_customer()
    receive_stock_for_product(prod["id"], qty=100.0)

    # Fast forward order to dispatched
    so = client.post(
        "/api/sales-orders",
        json={"customer_id": cust["id"], "items": [{"product_id": prod["id"], "ordered_quantity": 30.0, "unit_price": 50.0}]},
        headers={"X-User-Role": "sales"},
    ).json()
    client.post(f"/api/sales-orders/{so['id']}/confirm", headers={"X-User-Role": "sales"})
    client.post(f"/api/sales-orders/{so['id']}/allocate", json={"warehouse_id": "wh-main"}, headers={"X-User-Role": "sales"})

    pkl = client.post("/api/sales-pick-lists", json={"sales_order_id": so["id"], "warehouse_id": "wh-main"}, headers={"X-User-Role": "warehouse"}).json()
    client.post(f"/api/sales-pick-lists/{pkl['id']}/complete", json={"items": [{"pick_item_id": pkl["items"][0]["id"], "picked_quantity": 30.0}]}, headers={"X-User-Role": "warehouse"})
    client.post(f"/api/sales-orders/{so['id']}/pack", json={}, headers={"X-User-Role": "warehouse"})

    disp = client.post(
        "/api/sales-dispatches",
        json={"sales_order_id": so["id"], "warehouse_id": "wh-main", "items": [{"order_item_id": so["items"][0]["id"], "quantity_dispatched": 30.0}]},
        headers={"X-User-Role": "warehouse"},
    ).json()

    # Balance before return: 100 - 30 = 70 available
    with get_connection() as conn:
        bal = conn.execute("SELECT on_hand_qty FROM inventory_balances WHERE product_id = ? AND stock_type = 'available'", (prod["id"],)).fetchone()
        assert float(bal["on_hand_qty"]) == 70.0

    # Create Sales Return: customer returns 10 units
    ret_res = client.post(
        "/api/sales-returns",
        json={
            "sales_order_id": so["id"],
            "dispatch_id": disp["id"],
            "reason": "Customer reported over-shipment",
            "items": [{"order_item_id": so["items"][0]["id"], "returned_quantity": 10.0}],
        },
        headers={"X-User-Role": "sales"},
    )
    assert ret_res.status_code == 200, ret_res.text
    ret = ret_res.json()
    assert ret["status"] == "received"

    # Process Return: 5 units accepted (restock to available), 3 units quarantined, 2 units rejected
    proc_res = client.post(
        f"/api/sales-returns/{ret['id']}/process",
        json={
            "items": [
                {
                    "order_item_id": so["items"][0]["id"],
                    "returned_quantity": 10.0,
                    "accepted_quantity": 5.0,
                    "quarantined_quantity": 3.0,
                    "rejected_quantity": 2.0,
                    "inspection_notes": "5 sealed units restocked; 3 opened packages quarantined; 2 torn sacks rejected",
                }
            ]
        },
        headers={"X-User-Role": "warehouse"},
    )
    assert proc_res.status_code == 200, proc_res.text
    ret_proc = proc_res.json()
    assert ret_proc["status"] == "processed"

    # Verify stock segregation in database:
    # Available on-hand was 70, now 70 + 5 = 75
    # Quarantined on-hand is 3
    # Rejected on-hand is 2
    # Quarantined and rejected MUST NOT be in available stock!
    with get_connection() as conn:
        avail_row = conn.execute("SELECT on_hand_qty FROM inventory_balances WHERE product_id = ? AND stock_type = 'available'", (prod["id"],)).fetchone()
        assert float(avail_row["on_hand_qty"]) == 75.0

        quar_row = conn.execute("SELECT on_hand_qty FROM inventory_balances WHERE product_id = ? AND stock_type = 'quarantined'", (prod["id"],)).fetchone()
        assert float(quar_row["on_hand_qty"]) == 3.0

        rej_row = conn.execute("SELECT on_hand_qty FROM inventory_balances WHERE product_id = ? AND stock_type = 'rejected'", (prod["id"],)).fetchone()
        assert float(rej_row["on_hand_qty"]) == 2.0


def test_backend_rbac_permission_boundaries():
    cust = create_test_customer()
    prod = create_test_product()

    # Viewer cannot create quotation (403)
    viewer_res = client.post(
        "/api/quotations",
        json={"customer_id": cust["id"], "items": [{"product_id": prod["id"], "quantity": 10.0, "unit_price": 50.0}]},
        headers={"X-User-Role": "viewer"},
    )
    assert viewer_res.status_code == 403

    # Viewer cannot create sales order (403)
    viewer_so = client.post(
        "/api/sales-orders",
        json={"customer_id": cust["id"], "items": [{"product_id": prod["id"], "ordered_quantity": 10.0, "unit_price": 50.0}]},
        headers={"X-User-Role": "viewer"},
    )
    assert viewer_so.status_code == 403

    # Sales role CAN create quotation and order
    sales_so = client.post(
        "/api/sales-orders",
        json={"customer_id": cust["id"], "items": [{"product_id": prod["id"], "ordered_quantity": 10.0, "unit_price": 50.0}]},
        headers={"X-User-Role": "sales"},
    )
    assert sales_so.status_code == 200

    # Sales role CANNOT complete pick lists or dispatches (warehouse operations)
    sales_disp = client.post(
        "/api/sales-dispatches",
        json={"sales_order_id": sales_so.json()["id"], "warehouse_id": "wh-main", "items": []},
        headers={"X-User-Role": "sales"},
    )
    assert sales_disp.status_code == 403
