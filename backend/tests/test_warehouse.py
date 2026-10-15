import uuid
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def create_test_product(sku=None, name="Test Seafood Grade A", cost=500.0, price=800.0):
    if not sku:
        sku = f"SKU-WH-{uuid.uuid4().hex[:6].upper()}"
    res = client.post(
        "/api/products",
        json={
            "sku": sku,
            "name": name,
            "category": "Seafood",
            "uom": "KG",
            "default_purchase_cost": cost,
            "default_selling_price": price,
            "hsn_code": "03061790",
            "tax_rate_pct": 5.0,
        },
        headers={"X-User-Role": "admin"},
    )
    assert res.status_code == 201, res.text
    return res.json()


def create_test_supplier(code=None, name="Coastal Catchers Ltd"):
    if not code:
        code = f"SUP-WH-{uuid.uuid4().hex[:6].upper()}"
    res = client.post(
        "/api/suppliers",
        json={
            "code": code,
            "name": name,
            "country": "IN",
            "currency": "INR",
            "payment_terms": "Net 30",
        },
        headers={"X-User-Role": "admin"},
    )
    assert res.status_code == 201, res.text
    return res.json()


def create_test_po_and_post_gr(product_id, qty=100.0, accepted_qty=100.0, quarantined_qty=0.0):
    supplier = create_test_supplier()
    po_num = f"PO-WH-{uuid.uuid4().hex[:6].upper()}"
    po_res = client.post(
        "/api/purchase-orders",
        json={
            "po_number": po_num,
            "supplier_id": supplier["id"],
            "order_date": "2026-10-14",
            "currency": "INR",
            "items": [
                {
                    "product_id": product_id,
                    "ordered_qty": qty,
                    "unit_price": 500.0,
                    "tax_rate_pct": 5.0,
                }
            ],
        },
        headers={"X-User-Role": "admin"},
    )
    assert po_res.status_code == 201, po_res.text
    po = po_res.json()

    # Approve PO
    app_res = client.post(
        f"/api/purchase-orders/{po['id']}/approve",
        headers={"X-User-Role": "admin"},
    )
    assert app_res.status_code == 200, app_res.text

    # Create GR
    gr_num = f"GR-WH-{uuid.uuid4().hex[:6].upper()}"
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
                    "accepted_qty": accepted_qty,
                    "quarantined_qty": quarantined_qty,
                    "rejected_qty": 0.0,
                }
            ],
        },
        headers={"X-User-Role": "warehouse"},
    )
    assert gr_res.status_code == 201, gr_res.text
    gr = gr_res.json()

    # Post GR to inventory
    post_res = client.post(
        f"/api/goods-receipts/{gr['id']}/post?idempotency_key=gr-post-{uuid.uuid4().hex[:8]}",
        headers={"X-User-Role": "warehouse"},
    )
    assert post_res.status_code == 200, post_res.text
    return gr


def test_warehouse_and_location_lifecycle_and_validation():
    # 1. Create Warehouse
    wh_code = f"WH-SOUTH-{uuid.uuid4().hex[:4].upper()}"
    res = client.post(
        "/api/warehouses",
        json={
            "code": wh_code,
            "name": "Kochi Marine Terminal Warehouse",
            "address": "Willingdon Island",
            "city": "Kochi",
            "country": "IN",
        },
        headers={"X-User-Role": "warehouse"},
    )
    assert res.status_code == 201, res.text
    wh = res.json()
    assert wh["code"] == wh_code
    assert wh["is_active"] is True

    # 2. Duplicate code rejected (409)
    res_dup = client.post(
        "/api/warehouses",
        json={"code": wh_code.lower(), "name": "Duplicate"},
        headers={"X-User-Role": "warehouse"},
    )
    assert res_dup.status_code == 409

    # 3. Create Storage Location within Warehouse
    loc_res = client.post(
        "/api/warehouse-locations",
        json={
            "warehouse_id": wh["id"],
            "location_code": "COLD-01",
            "zone": "Cold Storage (-20C)",
            "rack": "R1",
            "shelf": "S1",
            "bin": "B1",
        },
        headers={"X-User-Role": "warehouse"},
    )
    assert loc_res.status_code == 201, loc_res.text
    loc = loc_res.json()
    assert loc["location_code"] == "COLD-01"
    assert loc["zone"] == "Cold Storage (-20C)"

    # 4. Duplicate location in same warehouse rejected (409)
    dup_loc = client.post(
        "/api/warehouse-locations",
        json={"warehouse_id": wh["id"], "location_code": "COLD-01"},
        headers={"X-User-Role": "warehouse"},
    )
    assert dup_loc.status_code == 409

    # 5. List locations filtered by warehouse
    list_res = client.get(f"/api/warehouse-locations?warehouse_id={wh['id']}")
    assert list_res.status_code == 200
    locs = list_res.json()["items"]
    assert len(locs) == 1
    assert locs[0]["location_code"] == "COLD-01"


def test_safe_deactivation_rules():
    # Create warehouse, location, product, and stock
    wh_code = f"WH-ACT-{uuid.uuid4().hex[:4].upper()}"
    wh = client.post(
        "/api/warehouses",
        json={"code": wh_code, "name": "Active Hub"},
        headers={"X-User-Role": "admin"},
    ).json()

    prod = create_test_product()
    create_test_po_and_post_gr(prod["id"], qty=50.0, accepted_qty=50.0)

    # Create an active reservation for this warehouse
    res_res = client.post(
        "/api/inventory/reservations",
        json={
            "product_id": prod["id"],
            "warehouse_id": wh["id"],
            "quantity": 10.0,
            "reference_type": "export_order",
            "notes": "Pre-shipment reservation",
        },
        headers={"X-User-Role": "sales"},
    )
    assert res_res.status_code == 201, res_res.text

    # Attempt to deactivate warehouse with active reservation -> blocked with 409 Conflict
    deact_res = client.patch(
        f"/api/warehouses/{wh['id']}",
        json={"is_active": False},
        headers={"X-User-Role": "admin"},
    )
    assert deact_res.status_code == 409
    assert "Cannot deactivate warehouse" in deact_res.json()["detail"]


def test_stock_transfer_lifecycle_and_reconciliation():
    # Create source & destination warehouses
    wh1 = client.post(
        "/api/warehouses",
        json={"code": f"WH-SRC-{uuid.uuid4().hex[:4].upper()}", "name": "Source WH"},
        headers={"X-User-Role": "admin"},
    ).json()
    wh2 = client.post(
        "/api/warehouses",
        json={"code": f"WH-DST-{uuid.uuid4().hex[:4].upper()}", "name": "Dest WH"},
        headers={"X-User-Role": "admin"},
    ).json()

    prod = create_test_product()
    create_test_po_and_post_gr(prod["id"], qty=100.0, accepted_qty=100.0)

    # 1. Create Stock Transfer (draft)
    trf_key = f"trf-key-{uuid.uuid4().hex[:8]}"
    trf_res = client.post(
        "/api/inventory/transfers",
        json={
            "source_warehouse_id": wh1["id"],
            "dest_warehouse_id": wh2["id"],
            "notes": "Inter-hub transfer to Kochi",
            "idempotency_key": trf_key,
            "items": [
                {"product_id": prod["id"], "requested_quantity": 40.0}
            ],
        },
        headers={"X-User-Role": "warehouse"},
    )
    assert trf_res.status_code == 201, trf_res.text
    trf = trf_res.json()
    assert trf["status"] == "draft"
    assert trf["items"][0]["requested_quantity"] == 40.0

    # Test idempotency: sending same request returns same transfer
    dup_res = client.post(
        "/api/inventory/transfers",
        json={
            "source_warehouse_id": wh1["id"],
            "dest_warehouse_id": wh2["id"],
            "idempotency_key": trf_key,
            "items": [{"product_id": prod["id"], "requested_quantity": 40.0}],
        },
        headers={"X-User-Role": "warehouse"},
    )
    assert dup_res.status_code == 201
    assert dup_res.json()["id"] == trf["id"]

    # 2. Approve Transfer
    app_res = client.post(f"/api/inventory/transfers/{trf['id']}/approve", headers={"X-User-Role": "warehouse"})
    assert app_res.status_code == 200, app_res.text
    assert app_res.json()["status"] == "approved"

    # 3. Dispatch Transfer
    disp_res = client.post(f"/api/inventory/transfers/{trf['id']}/dispatch", headers={"X-User-Role": "warehouse"})
    assert disp_res.status_code == 200, disp_res.text
    assert disp_res.json()["status"] == "dispatched"

    # Check that in-transit stock was created (40.0 units)
    report_res = client.get("/api/inventory/reports/balances")
    assert report_res.status_code == 200
    p_report = next(i for i in report_res.json()["items"] if i["product_id"] == prod["id"])
    assert p_report["in_transit_qty"] == 40.0
    assert p_report["available_qty"] == 60.0  # 100 - 40 = 60

    # 4. Receive Transfer with Discrepancy (35 accepted, 3 damaged, 2 shortage)
    item_id = trf["items"][0]["id"]
    recv_res = client.post(
        f"/api/inventory/transfers/{trf['id']}/receive",
        json={
            "items": [
                {
                    "item_id": item_id,
                    "received_quantity": 35.0,
                    "damaged_quantity": 3.0,
                    "discrepancy_reason": "Carton crushed in transit",
                }
            ],
            "notes": "Shortage of 2 units reported upon unloading",
        },
        headers={"X-User-Role": "warehouse"},
    )
    assert recv_res.status_code == 200, recv_res.text
    rec = recv_res.json()
    assert rec["status"] == "discrepancy"
    rec_item = rec["items"][0]
    assert rec_item["received_quantity"] == 35.0
    assert rec_item["damaged_quantity"] == 3.0
    assert rec_item["shortage_quantity"] == 2.0

    # In-transit should now be 0, damaged in quarantined stock (3.0), available (60 + 35 = 95.0)
    report_res2 = client.get("/api/inventory/reports/balances")
    p_report2 = next(i for i in report_res2.json()["items"] if i["product_id"] == prod["id"])
    assert p_report2["in_transit_qty"] == 0.0
    assert p_report2["available_qty"] == 95.0
    assert p_report2["quarantined_qty"] == 3.0

    # Total physical stock = 95 available + 3 quarantined = 98 (2 lost to shortage)
    assert p_report2["on_hand_qty"] == 98.0


def test_inventory_adjustments_and_compensating_movements():
    wh = client.post(
        "/api/warehouses",
        json={"code": f"WH-ADJ-{uuid.uuid4().hex[:4].upper()}", "name": "Adjustment Depot"},
        headers={"X-User-Role": "admin"},
    ).json()

    prod = create_test_product()
    create_test_po_and_post_gr(prod["id"], qty=50.0, accepted_qty=50.0)

    # 1. Create Stock Count Adjustment (Physical count finds 48 units instead of 50 -> -2 diff)
    adj_res = client.post(
        "/api/inventory/adjustments",
        json={
            "product_id": prod["id"],
            "warehouse_id": wh["id"],
            "system_quantity": 50.0,
            "counted_quantity": 48.0,
            "reason_code": "PHYSICAL_COUNT",
            "notes": "Annual cycle count discrepancy",
        },
        headers={"X-User-Role": "warehouse"},
    )
    assert adj_res.status_code == 201, adj_res.text
    adj = adj_res.json()
    assert adj["difference_quantity"] == -2.0
    assert adj["status"] == "pending"

    # 2. Approve Adjustment
    app_res = client.post(f"/api/inventory/adjustments/{adj['id']}/approve", headers={"X-User-Role": "admin"})
    assert app_res.status_code == 200, app_res.text
    assert app_res.json()["status"] == "approved"

    # Check updated stock
    bal_res = client.get("/api/inventory/reports/balances")
    p_bal = next(i for i in bal_res.json()["items"] if i["product_id"] == prod["id"])
    assert p_bal["available_qty"] == 48.0

    # 3. Test negative stock prevention: cannot adjust below 0
    neg_res = client.post(
        "/api/inventory/adjustments",
        json={
            "product_id": prod["id"],
            "warehouse_id": wh["id"],
            "system_quantity": 48.0,
            "counted_quantity": 0.0,
            "reason_code": "DAMAGE_WRITE_OFF",
        },
        headers={"X-User-Role": "warehouse"},
    ).json()

    # If system quantity was 48, counted 0 difference is -48 (allowed to bring to 0)
    # But if counted was somehow negative:
    invalid_neg = client.post(
        "/api/inventory/adjustments",
        json={
            "product_id": prod["id"],
            "warehouse_id": wh["id"],
            "system_quantity": 48.0,
            "counted_quantity": -5.0,
            "reason_code": "DAMAGE_WRITE_OFF",
        },
        headers={"X-User-Role": "warehouse"},
    )
    assert invalid_neg.status_code == 400


def test_stock_reservations_and_available_to_promise():
    wh = client.post(
        "/api/warehouses",
        json={"code": f"WH-RES-{uuid.uuid4().hex[:4].upper()}", "name": "Reservation Hub"},
        headers={"X-User-Role": "admin"},
    ).json()

    prod = create_test_product()
    create_test_po_and_post_gr(prod["id"], qty=80.0, accepted_qty=80.0)

    # Available = 80.0, Reserved = 0, ATP = 80.0
    report1 = client.get("/api/inventory/reports/balances").json()
    p1 = next(i for i in report1["items"] if i["product_id"] == prod["id"])
    assert p1["available_to_promise"] == 80.0

    # 1. Create Reservation of 30 units
    res1 = client.post(
        "/api/inventory/reservations",
        json={
            "product_id": prod["id"],
            "warehouse_id": wh["id"],
            "quantity": 30.0,
            "reference_type": "sales_order",
            "reference_id": "SO-2026-001",
        },
        headers={"X-User-Role": "sales"},
    ).json()
    assert res1["status"] == "active"

    # ATP should now be 80 - 30 = 50.0
    report2 = client.get("/api/inventory/reports/balances").json()
    p2 = next(i for i in report2["items"] if i["product_id"] == prod["id"])
    assert p2["reserved_qty"] == 30.0
    assert p2["available_to_promise"] == 50.0

    # 2. Attempt to reserve more than ATP (try 55 units -> rejected with 400)
    over_res = client.post(
        "/api/inventory/reservations",
        json={
            "product_id": prod["id"],
            "warehouse_id": wh["id"],
            "quantity": 55.0,
        },
        headers={"X-User-Role": "sales"},
    )
    assert over_res.status_code == 400
    assert "Insufficient available stock" in over_res.json()["detail"]

    # 3. Release Reservation -> ATP restored
    rel_res = client.post(f"/api/inventory/reservations/{res1['id']}/release", headers={"X-User-Role": "sales"})
    assert rel_res.status_code == 200
    assert rel_res.json()["status"] == "released"

    report3 = client.get("/api/inventory/reports/balances").json()
    p3 = next(i for i in report3["items"] if i["product_id"] == prod["id"])
    assert p3["reserved_qty"] == 0.0
    assert p3["available_to_promise"] == 80.0

    # 4. Create and Consume Reservation (fulfilment)
    res2 = client.post(
        "/api/inventory/reservations",
        json={"product_id": prod["id"], "warehouse_id": wh["id"], "quantity": 25.0},
        headers={"X-User-Role": "sales"},
    ).json()

    consume_res = client.post(f"/api/inventory/reservations/{res2['id']}/consume", headers={"X-User-Role": "warehouse"})
    assert consume_res.status_code == 200
    assert consume_res.json()["status"] == "consumed"

    # Stock on hand decreased by 25: 80 - 25 = 55.0
    report4 = client.get("/api/inventory/reports/balances").json()
    p4 = next(i for i in report4["items"] if i["product_id"] == prod["id"])
    assert p4["available_qty"] == 55.0
    assert p4["available_to_promise"] == 55.0


def test_inventory_ledger_reconciliation_report():
    prod = create_test_product()
    create_test_po_and_post_gr(prod["id"], qty=60.0, accepted_qty=50.0, quarantined_qty=10.0)

    # Run Reconciliation Report
    rec_res = client.get("/api/inventory/reports/reconciliation", headers={"X-User-Role": "admin"})
    assert rec_res.status_code == 200, rec_res.text
    rec = rec_res.json()
    assert rec["is_fully_reconciled"] is True
    assert rec["discrepancies_found"] == 0

    # Ensure our product's available and quarantined movements perfectly match balance
    prod_items = [i for i in rec["items"] if i["product_id"] == prod["id"]]
    avail_item = next(i for i in prod_items if i["stock_type"] == "available")
    assert avail_item["balance_on_hand"] == 50.0
    assert avail_item["ledger_sum_qty"] == 50.0
    assert avail_item["discrepancy"] == 0.0
    assert avail_item["is_reconciled"] is True


def test_phase3_role_permissions():
    # Viewer cannot create warehouses, transfers, adjustments, or reservations (403)
    wh_data = {"code": "WH-VIEW", "name": "Viewer Test WH"}
    assert client.post("/api/warehouses", json=wh_data, headers={"X-User-Role": "viewer"}).status_code == 403

    trf_data = {
        "source_warehouse_id": "wh-main",
        "dest_warehouse_id": "wh-main",
        "items": [{"product_id": "p1", "requested_quantity": 10.0}],
    }
    assert client.post("/api/inventory/transfers", json=trf_data, headers={"X-User-Role": "viewer"}).status_code == 403

    adj_data = {
        "product_id": "p1",
        "warehouse_id": "wh1",
        "system_quantity": 10.0,
        "counted_quantity": 10.0,
        "reason_code": "PHYSICAL_COUNT",
    }
    assert client.post("/api/inventory/adjustments", json=adj_data, headers={"X-User-Role": "viewer"}).status_code == 403

    res_data = {"product_id": "p1", "warehouse_id": "wh1", "quantity": 5.0}
    assert client.post("/api/inventory/reservations", json=res_data, headers={"X-User-Role": "viewer"}).status_code == 403
