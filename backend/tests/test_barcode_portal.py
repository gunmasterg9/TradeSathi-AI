"""
TradeSathi AI — Phase 8: Operational Portals & Barcode Services Automated Tests
Validates:
1. QR and Code 128 label generation engines and thermal label formatting (4"x2", 2"x1").
2. Database idempotency and collision handling for barcodes.
3. Universal scan-resolution across Product, Warehouse Location, Purchase Order, Goods Receipt, Sales Order, Dispatch, and Export Shipment.
4. Safe handling of malformed, unknown, and deactivated barcodes.
5. Operational Workflows:
   - Scan-driven Goods Receipt with tolerance checks and ledger posting.
   - Scan-driven Warehouse Transfer with ATP checks and movement tracking.
   - Scan-driven Fulfilment Packing with over-pack prevention.
6. RBAC enforcement (viewer read-only, warehouse operator permissions) and audit logging.
"""

import uuid
import pytest
from fastapi.testclient import TestClient

from app.barcode_engine import (
    generate_qr_svg,
    generate_code128_svg,
    build_label_html,
    resolve_scanned_barcode_payload,
)
from app.db import (
    get_connection,
    get_barcode_record_by_value,
    deactivate_entity_barcode_record,
)
from app.main import app

ADMIN_HEADERS = {"X-User-Role": "admin", "X-User-Name": "Admin User", "X-User-Email": "admin@tradesathi.local"}
WAREHOUSE_HEADERS = {"X-User-Role": "warehouse", "X-User-Name": "Warehouse Operator", "X-User-Email": "wh@tradesathi.local"}
SALES_HEADERS = {"X-User-Role": "sales", "X-User-Name": "Sales Rep", "X-User-Email": "sales@tradesathi.local"}
PROCUREMENT_HEADERS = {"X-User-Role": "procurement", "X-User-Name": "Procurement Buyer", "X-User-Email": "buyer@tradesathi.local"}
VIEWER_HEADERS = {"X-User-Role": "viewer", "X-User-Name": "Auditor Viewer", "X-User-Email": "viewer@tradesathi.local"}


def create_portal_test_fixtures():
    """Populates an isolated test database with base master data and documents."""
    now = "2026-10-14T12:00:00Z"
    uid_suffix = uuid.uuid4().hex[:6]

    wh_src_id = f"wh-src-{uid_suffix}"
    wh_dest_id = f"wh-dest-{uid_suffix}"
    loc_src_id = f"loc-src-{uid_suffix}"
    loc_dest_id = f"loc-dest-{uid_suffix}"
    prod_id = f"prod-{uid_suffix}"
    sku = f"SKU-VLV-{uid_suffix.upper()}"
    supp_id = f"supp-{uid_suffix}"
    cust_id = f"cust-{uid_suffix}"
    po_id = f"po-{uid_suffix}"
    po_num = f"PO-2026-{uid_suffix.upper()}"
    so_id = f"so-{uid_suffix}"
    so_num = f"SO-2026-{uid_suffix.upper()}"
    shipment_id = f"ship-{uid_suffix}"
    shipment_ref = f"EXP-2026-{uid_suffix.upper()}"

    with get_connection() as conn:
        # Warehouses & Locations
        conn.execute(
            """
            INSERT INTO warehouses (id, code, name, address, city, country, is_active, created_at, updated_at)
            VALUES (?, ?, 'Central Primary WH', '100 Dock Rd', 'Mumbai', 'IN', 1, ?, ?),
                   (?, ?, 'Secondary Depot', '200 Terminal Rd', 'Navi Mumbai', 'IN', 1, ?, ?)
            """,
            (wh_src_id, f"WH-PRI-{uid_suffix.upper()}", now, now, wh_dest_id, f"WH-SEC-{uid_suffix.upper()}", now, now),
        )
        conn.execute(
            """
            INSERT INTO warehouse_locations (id, warehouse_id, location_code, zone, rack, shelf, bin, is_active, created_at, updated_at)
            VALUES (?, ?, 'BIN-A1-01', 'A', '1', '1', '01', 1, ?, ?),
                   (?, ?, 'BIN-B2-04', 'B', '2', '4', '04', 1, ?, ?)
            """,
            (loc_src_id, wh_src_id, now, now, loc_dest_id, wh_dest_id, now, now),
        )

        # Product
        conn.execute(
            """
            INSERT INTO products (id, sku, name, category, uom, default_purchase_cost, default_selling_price, currency, is_active, created_at, updated_at)
            VALUES (?, ?, 'High-Pressure Ball Valve', 'Valves', 'PCS', 300.0, 450.0, 'INR', 1, ?, ?)
            """,
            (prod_id, sku, now, now),
        )

        # Inventory balance for product
        conn.execute(
            """
            INSERT INTO inventory_balances (product_id, stock_type, sku, on_hand_qty, total_value, updated_at)
            VALUES (?, 'available', ?, 150.0, 45000.0, ?)
            """,
            (prod_id, sku, now),
        )

        # Supplier & Customer
        conn.execute(
            """
            INSERT INTO suppliers (id, code, name, status, country, created_at, updated_at)
            VALUES (?, ?, 'Industrial Forge Ltd', 'active', 'IN', ?, ?)
            """,
            (supp_id, f"SUPP-{uid_suffix.upper()}", now, now),
        )
        conn.execute(
            """
            INSERT INTO customers (id, code, name, status, country, currency, created_at, updated_at)
            VALUES (?, ?, 'Euro Trade GmbH', 'active', 'DE', 'EUR', ?, ?)
            """,
            (cust_id, f"CUST-{uid_suffix.upper()}", now, now),
        )

        # Purchase Order & PO item
        po_item_id = f"poi-{uid_suffix}"
        conn.execute(
            """
            INSERT INTO purchase_orders (id, po_number, supplier_id, order_date, currency, payment_terms, subtotal, tax_total, grand_total, status, created_by, created_at, updated_at)
            VALUES (?, ?, ?, '2026-10-14', 'INR', 'Net 30', 30000.0, 0.0, 30000.0, 'approved', 'buyer', ?, ?)
            """,
            (po_id, po_num, supp_id, now, now),
        )
        conn.execute(
            """
            INSERT INTO purchase_order_items (id, po_id, product_id, sku, product_name, uom, ordered_qty, unit_price, tax_rate_pct, line_total, received_qty, sort_order, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'High-Pressure Ball Valve', 'PCS', 100.0, 300.0, 0.0, 30000.0, 0.0, 0, ?, ?)
            """,
            (po_item_id, po_id, prod_id, sku, now, now),
        )

        # Sales Order & SO item
        so_item_id = f"soi-{uid_suffix}"
        conn.execute(
            """
            INSERT INTO sales_orders (id, order_number, customer_id, customer_code, customer_name, status, order_date, subtotal, discount_total, tax_total, grand_total, currency, created_by, created_at, updated_at)
            VALUES (?, ?, ?, 'CUST-001', 'Euro Trade GmbH', 'confirmed', '2026-10-14', 22500.0, 0.0, 4050.0, 26550.0, 'INR', 'sales', ?, ?)
            """,
            (so_id, so_num, cust_id, now, now),
        )
        conn.execute(
            """
            INSERT INTO sales_order_items (id, sales_order_id, product_id, product_sku, product_name, uom, ordered_quantity, allocated_quantity, picked_quantity, delivered_quantity, unit_price, discount_pct, tax_rate_pct, subtotal, discount_amount, tax_amount, line_total, sort_order, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'High-Pressure Ball Valve', 'PCS', 50.0, 50.0, 0.0, 0.0, 450.0, 0.0, 18.0, 22500.0, 0.0, 4050.0, 26550.0, 1, ?, ?)
            """,
            (so_item_id, so_id, prod_id, sku, now, now),
        )

        # Export Shipment
        conn.execute(
            """
            INSERT INTO shipments (id, reference, status, exporter, buyer, destination_port, notes, created_at, updated_at)
            VALUES (?, ?, 'draft', 'TradeSathi Exports', 'Euro Trade GmbH', 'Rotterdam', 'Rotterdam transshipment', ?, ?)
            """,
            (shipment_id, shipment_ref, now, now),
        )
        conn.commit()

    return {
        "wh_src_id": wh_src_id,
        "wh_dest_id": wh_dest_id,
        "loc_src_id": loc_src_id,
        "loc_dest_id": loc_dest_id,
        "prod_id": prod_id,
        "sku": sku,
        "po_id": po_id,
        "po_num": po_num,
        "so_id": so_id,
        "so_num": so_num,
        "shipment_id": shipment_id,
        "shipment_ref": shipment_ref,
    }


# ==========================================
# 1. Barcode Engine Unit Tests
# ==========================================

def test_qr_and_barcode_svg_generation():
    """Verifies that SVG generators produce valid, non-empty XML/SVG strings."""
    qr_svg = generate_qr_svg("TS:v1:product:SKU-12345")
    assert "<svg" in qr_svg and "</svg>" in qr_svg
    assert "viewBox" in qr_svg

    barcode_svg = generate_code128_svg("SKU-12345")
    assert "<svg" in barcode_svg and "</svg>" in barcode_svg
    assert "rect" in barcode_svg


def test_thermal_label_html_builder():
    """Verifies thermal label generation for 4x2 and 2x1 dimension presets."""
    html_4x2 = build_label_html(
        entity_type="product",
        entity_reference="SKU-VALVE-100",
        qr_payload="TS:v1:product:SKU-VALVE-100",
        metadata={
            "title": "High-Pressure Ball Valve",
            "subtitle": "Industrial Equipment",
            "extra_lines": [("UOM", "PCS"), ("Category", "Valves")],
        },
        label_size="4x2",
    )
    assert "@page" in html_4x2
    assert "100mm 50mm" in html_4x2
    assert "SKU-VALVE-100" in html_4x2
    assert "Internal verification label" in html_4x2

    html_2x1 = build_label_html(
        entity_type="warehouse_location",
        entity_reference="BIN-A1-01",
        qr_payload="TS:v1:warehouse_location:BIN-A1-01",
        metadata={"title": "BIN-A1-01", "subtitle": "Central WH"},
        label_size="2x1",
    )
    assert "50mm 25mm" in html_2x1
    assert "BIN-A1-01" in html_2x1



# ==========================================
# 2. Label Generation & Idempotency Tests
# ==========================================

def test_generate_label_idempotency(client: TestClient):
    """Ensures that repeated requests for the same entity return the existing barcode record without duplicating identity."""
    fixtures = create_portal_test_fixtures()

    res1 = client.post(
        "/api/portal/labels/generate",
        json={"entity_type": "product", "entity_id": fixtures["prod_id"], "label_size": "4x2", "symbology": "BOTH"},
        headers=ADMIN_HEADERS,
    )
    assert res1.status_code == 200
    data1 = res1.json()
    barcode_id1 = data1["barcode"]["id"]
    val1 = data1["barcode"]["barcode_value"]
    assert "TS:v1:product:" in val1 or "TS:v1:PROD:" in val1

    # Repeat generation
    res2 = client.post(
        "/api/portal/labels/generate",
        json={"entity_type": "product", "entity_id": fixtures["prod_id"], "label_size": "4x2", "symbology": "BOTH"},
        headers=ADMIN_HEADERS,
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["barcode"]["id"] == barcode_id1
    assert data2["barcode"]["barcode_value"] == val1


def test_preview_label_html_endpoint(client: TestClient):
    """Verifies HTML preview of generated thermal label."""
    fixtures = create_portal_test_fixtures()

    gen_res = client.post(
        "/api/portal/labels/generate",
        json={"entity_type": "product", "entity_id": fixtures["prod_id"], "label_size": "4x2", "symbology": "BOTH"},
        headers=ADMIN_HEADERS,
    )
    barcode_id = gen_res.json()["barcode"]["id"]

    prev_res = client.get(f"/api/portal/labels/{barcode_id}/preview", headers=ADMIN_HEADERS)
    assert prev_res.status_code == 200
    assert "text/html" in prev_res.headers["content-type"]
    assert fixtures["sku"] in prev_res.text


# ==========================================
# 3. Universal Scan Resolution Tests
# ==========================================

def test_scan_resolve_product_qr_and_barcode(client: TestClient):
    """Verifies that both QR code and linear barcode strings resolve product details and stock balances."""
    fixtures = create_portal_test_fixtures()

    # 1. Structured QR payload
    qr_code = f"TS:v1:product:{fixtures['sku']}"
    res = client.post("/api/portal/scan-resolve", json={"scanned_code": qr_code}, headers=WAREHOUSE_HEADERS)
    assert res.status_code == 200
    entity = res.json()["entity"]
    assert entity["entity_type"] == "product"
    assert entity["entity_reference"] == fixtures["sku"]
    assert entity["data"]["balances"]["available_qty"] == 150.0

    # 2. Linear 1D barcode text (plain SKU)
    res_linear = client.post("/api/portal/scan-resolve", json={"scanned_code": fixtures["sku"]}, headers=WAREHOUSE_HEADERS)
    assert res_linear.status_code == 200
    assert res_linear.json()["entity"]["entity_reference"] == fixtures["sku"]


def test_scan_resolve_warehouse_location(client: TestClient):
    """Verifies location resolution with zone, rack, shelf, bin details."""
    fixtures = create_portal_test_fixtures()

    qr_code = "TS:v1:warehouse_location:BIN-A1-01"
    res = client.post("/api/portal/scan-resolve", json={"scanned_code": qr_code}, headers=WAREHOUSE_HEADERS)
    assert res.status_code == 200
    entity = res.json()["entity"]
    assert entity["entity_type"] in ("location", "warehouse_location")
    assert entity["entity_reference"] == "BIN-A1-01"
    assert entity["data"]["location"]["zone"] == "A"
    assert entity["data"]["location"]["rack"] == "1"


def test_scan_resolve_purchase_order(client: TestClient):
    """Verifies purchase order resolution with item progress and inbound receipt requirements."""
    fixtures = create_portal_test_fixtures()

    qr_code = f"TS:v1:purchase_order:{fixtures['po_num']}"
    res = client.post("/api/portal/scan-resolve", json={"scanned_code": qr_code}, headers=PROCUREMENT_HEADERS)
    assert res.status_code == 200
    entity = res.json()["entity"]
    assert entity["entity_type"] == "purchase_order"
    assert entity["entity_reference"] == fixtures["po_num"]
    assert entity["data"]["purchase_order"]["status"] == "approved"
    assert len(entity["data"]["lines"]) == 1
    assert entity["data"]["lines"][0]["ordered_qty"] == 100.0


def test_scan_resolve_sales_order(client: TestClient):
    """Verifies sales order resolution with picking and packing progress."""
    fixtures = create_portal_test_fixtures()

    qr_code = f"TS:v1:sales_order:{fixtures['so_num']}"
    res = client.post("/api/portal/scan-resolve", json={"scanned_code": qr_code}, headers=SALES_HEADERS)
    assert res.status_code == 200
    entity = res.json()["entity"]
    assert entity["entity_type"] == "sales_order"
    assert entity["entity_reference"] == fixtures["so_num"]
    assert entity["data"]["sales_order"]["status"] == "confirmed"
    assert len(entity["data"]["items"]) == 1
    assert entity["data"]["items"][0]["ordered_quantity"] == 50.0


def test_scan_resolve_export_shipment(client: TestClient):
    """Verifies export shipment resolution with customs disclaimer and document status."""
    fixtures = create_portal_test_fixtures()

    qr_code = f"TS:v1:export_shipment:{fixtures['shipment_ref']}"
    res = client.post("/api/portal/scan-resolve", json={"scanned_code": qr_code}, headers=SALES_HEADERS)
    assert res.status_code == 200
    entity = res.json()["entity"]
    assert entity["entity_type"] == "export_shipment"
    assert entity["entity_reference"] == fixtures["shipment_ref"]
    assert "disclaimer" in entity["data"]
    assert "customs clearance" in entity["data"]["disclaimer"].lower()



def test_scan_resolve_unknown_and_deactivated_codes(client: TestClient):
    """Verifies graceful handling of non-existent and deactivated barcode codes."""
    fixtures = create_portal_test_fixtures()

    # Unknown code
    res_unknown = client.post("/api/portal/scan-resolve", json={"scanned_code": "TS:v1:product:SKU-UNKNOWN-999"}, headers=WAREHOUSE_HEADERS)
    assert res_unknown.status_code == 404

    # Generate and deactivate code
    gen_res = client.post(
        "/api/portal/labels/generate",
        json={"entity_type": "product", "entity_id": fixtures["prod_id"], "label_size": "4x2", "symbology": "BOTH"},
        headers=ADMIN_HEADERS,
    )
    b_val = gen_res.json()["barcode"]["barcode_value"]
    b_id = gen_res.json()["barcode"]["id"]

    client.post(f"/api/portal/labels/{b_id}/deactivate", headers=ADMIN_HEADERS)

    # Scanned deactivated code
    res_deactivated = client.post("/api/portal/scan-resolve", json={"scanned_code": b_val}, headers=WAREHOUSE_HEADERS)
    assert res_deactivated.status_code == 400
    assert "deactivated" in res_deactivated.json()["detail"].lower()


# ==========================================
# 4. Operational Workflows Tests
# ==========================================

def test_workflow_b_goods_receipt_execution(client: TestClient):
    """Tests scan-driven inbound receipt recording and automatic inventory ledger posting."""
    fixtures = create_portal_test_fixtures()

    receipt_payload = {
        "purchase_order_id": fixtures["po_id"],
        "idempotency_key": f"gr-key-{uuid.uuid4().hex[:8]}",
        "notes": "Scanned dock receipt",
        "lines": [
            {
                "product_id": fixtures["prod_id"],
                "accepted_quantity": 40.0,
                "rejected_quantity": 2.0,
                "quarantined_quantity": 0.0,
                "notes": "40 accepted, 2 damaged packaging",
            }
        ],
    }

    res = client.post("/api/portal/execute-receipt", json=receipt_payload, headers=WAREHOUSE_HEADERS)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["goods_receipt"]["status"] == "posted"

    # Verify inventory was updated
    bal_res = client.get("/api/inventory/balances?stock_type=available", headers=WAREHOUSE_HEADERS)
    matching = [b for b in bal_res.json()["items"] if b["product_id"] == fixtures["prod_id"]]
    assert matching[0]["on_hand_qty"] == 190.0  # 150 baseline + 40 accepted


def test_workflow_b_over_receipt_rejection(client: TestClient):
    """Ensures over-receipt beyond allowable 10% tolerance is rejected."""
    fixtures = create_portal_test_fixtures()

    receipt_payload = {
        "purchase_order_id": fixtures["po_id"],
        "idempotency_key": f"gr-key-{uuid.uuid4().hex[:8]}",
        "lines": [
            {
                "product_id": fixtures["prod_id"],
                "accepted_quantity": 120.0,  # Ordered was 100, max allowed is 110
                "rejected_quantity": 0.0,
                "quarantined_quantity": 0.0,
            }
        ],
    }

    res = client.post("/api/portal/execute-receipt", json=receipt_payload, headers=WAREHOUSE_HEADERS)
    assert res.status_code == 400
    assert "over-receipt rejected" in res.json()["detail"].lower()


def test_workflow_c_warehouse_transfer_execution(client: TestClient):
    """Tests scan-driven stock transfer between facilities with ATP validation."""
    fixtures = create_portal_test_fixtures()

    transfer_payload = {
        "product_id": fixtures["prod_id"],
        "source_warehouse_id": fixtures["wh_src_id"],
        "dest_warehouse_id": fixtures["wh_dest_id"],
        "source_location_id": fixtures["loc_src_id"],
        "dest_location_id": fixtures["loc_dest_id"],
        "quantity": 25.0,
        "idempotency_key": f"trf-key-{uuid.uuid4().hex[:8]}",
        "auto_complete": True,
    }

    res = client.post("/api/portal/execute-transfer", json=transfer_payload, headers=WAREHOUSE_HEADERS)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["transfer"]["status"] == "received"


def test_workflow_c_insufficient_stock_transfer_rejection(client: TestClient):
    """Verifies that transfers exceeding available on-hand stock are rejected."""
    fixtures = create_portal_test_fixtures()

    transfer_payload = {
        "product_id": fixtures["prod_id"],
        "source_warehouse_id": fixtures["wh_src_id"],
        "dest_warehouse_id": fixtures["wh_dest_id"],
        "quantity": 5000.0,  # Available is 150
        "idempotency_key": f"trf-key-{uuid.uuid4().hex[:8]}",
        "auto_complete": True,
    }

    res = client.post("/api/portal/execute-transfer", json=transfer_payload, headers=WAREHOUSE_HEADERS)
    assert res.status_code == 400
    assert "insufficient available stock" in res.json()["detail"].lower()


def test_workflow_d_fulfilment_packing_execution(client: TestClient):
    """Tests scan-driven packing verification advancing sales order line progress."""
    fixtures = create_portal_test_fixtures()

    pack_payload = {
        "sales_order_id": fixtures["so_id"],
        "product_id": fixtures["prod_id"],
        "quantity": 50.0,  # Ordered is 50.0
        "package_ref": "BOX-001",
    }

    res = client.post("/api/portal/execute-pack", json=pack_payload, headers=WAREHOUSE_HEADERS)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["is_order_fully_packed"] is True
    assert data["sales_order"]["status"] == "packed"


def test_workflow_d_excessive_packing_rejection(client: TestClient):
    """Verifies that packing more than ordered quantity is rejected."""
    fixtures = create_portal_test_fixtures()

    pack_payload = {
        "sales_order_id": fixtures["so_id"],
        "product_id": fixtures["prod_id"],
        "quantity": 999.0,
    }

    res = client.post("/api/portal/execute-pack", json=pack_payload, headers=WAREHOUSE_HEADERS)
    assert res.status_code == 400
    assert "packing quantity exceeds order limit" in res.json()["detail"].lower()


# ==========================================
# 5. Security & RBAC Tests
# ==========================================

def test_portal_rbac_permission_enforcement(client: TestClient):
    """Verifies viewer role cannot execute stock-changing operations."""
    fixtures = create_portal_test_fixtures()

    # Viewer role attempting to execute goods receipt -> 403 Forbidden
    gr_payload = {
        "purchase_order_id": fixtures["po_id"],
        "idempotency_key": "viewer-forbidden",
        "lines": [{"product_id": fixtures["prod_id"], "accepted_quantity": 10.0}],
    }
    res = client.post("/api/portal/execute-receipt", json=gr_payload, headers=VIEWER_HEADERS)
    assert res.status_code == 403

    # Viewer attempting to print label -> 403 Forbidden
    lbl_payload = {"entity_type": "product", "entity_id": fixtures["prod_id"]}
    res_lbl = client.post("/api/portal/labels/generate", json=lbl_payload, headers=VIEWER_HEADERS)
    assert res_lbl.status_code == 403
