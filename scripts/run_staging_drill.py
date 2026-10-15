"""TradeSathi AI — Phase 10.2 Controlled Isolated Staging Deployment Runner.
Executes end-to-end smoke verification across all platform functional modules,
security enforcement gates, and disaster recovery drills without touching live assets.
"""
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Set staging environment variables BEFORE importing application modules
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "backend"))
sys.path.insert(0, str(repo_root))

staging_dir = (repo_root / "staging_data").resolve()
staging_db = (staging_dir / "tradesathi_staging.db").resolve()
staging_storage = (staging_dir / "storage" / "documents").resolve()
staging_backups = (staging_dir / "backups").resolve()
staging_recovery = (staging_dir / "recovery_target").resolve()

# Enforce staging environment
os.environ["ENVIRONMENT"] = "staging"
os.environ["TRADESATHI_ENV"] = "staging"
os.environ["TRADESATHI_DB_PATH"] = str(staging_db)
os.environ["TRADESATHI_STORAGE_PATH"] = str(staging_storage)
os.environ["TRADESATHI_BACKUP_ROOT"] = str(staging_backups)
os.environ["TRADESATHI_SECRET_KEY"] = "stg_9f8e7d6c5b4a3a2b1c0d9e8f7a6b5c4d3e2f1a0b_tradesathi"
os.environ["CORS_ORIGINS"] = "http://127.0.0.1:5173,http://127.0.0.1:8001"
os.environ["TRADESATHI_TEST_ROLE_SIMULATOR"] = "0"
os.environ["EMAIL_DELIVERY_ENABLED"] = "false"

# Import application components
from fastapi.testclient import TestClient
from app.main import app, validate_production_config
from app.db import (
    init_db,
    get_connection,
    get_applied_migrations,
    create_shipment,
    get_shipment_by_id,
    create_cargo_calculation,
)
from app.auth import (
    provision_initial_admin,
    create_user_record,
    create_user_token,
    revoke_token_by_raw,
    get_user_by_id,
    hash_token,
)
from app.master_data import (
    create_supplier,
    create_customer,
    create_product,
    list_suppliers,
    list_customers,
    list_products,
)
from app.warehouse import (
    create_warehouse,
    create_warehouse_location,
    create_stock_reservation,
    get_product_atp,
)
from app.procurement import (
    create_purchase_order,
    transition_purchase_order_status,
    create_goods_receipt,
    post_goods_receipt_to_inventory,
)
from app.sales import (
    create_sales_order,
    confirm_sales_order,
    allocate_sales_order,
    create_sales_pick_list,
    complete_sales_pick_list,
    pack_sales_order,
    create_sales_dispatch,
    deliver_sales_dispatch,
    create_sales_return,
)
from app.barcode_engine import (
    generate_entity_label,
    generate_qr_svg,
)
from app.collaboration import hash_portal_token
from app.notifications import (
    reclaim_expired_leases,
    process_notification_deliveries,
)
from app.backup import (
    create_backup,
    verify_backup,
    restore_backup,
    verify_restoration_integrity,
)


def run_staging_deployment() -> dict:
    results = {"gates": {}, "workflows": {}, "metrics": {}}

    print("=" * 80)
    print("TRADESATHI AI — PHASE 10.2 CONTROLLED ISOLATED STAGING DEPLOYMENT")
    print("=" * 80)

    # -------------------------------------------------------------------------
    # Gate A: Staging Isolation & Preflight Verification
    # -------------------------------------------------------------------------
    live_db = (repo_root / "backend" / "tradesathi.db").resolve()
    live_storage = (repo_root / "backend" / "storage" / "documents").resolve()

    live_hash_pre = hashlib.sha256(live_db.read_bytes()).hexdigest()
    live_size_pre = live_db.stat().st_size
    live_docs_pre = len([f for f in live_storage.rglob("*") if f.is_file()])

    print("\n--- Gate A: Isolation Invariants ---")
    print(f"Live DB Checksum:          {live_hash_pre}")
    print(f"Live DB Size:              {live_size_pre} bytes")
    print(f"Live Storage Files:        {live_docs_pre}")
    print(f"Staging DB Target:         {staging_db}")
    print(f"Staging Storage Target:    {staging_storage}")

    assert staging_db != live_db, "Isolation Failure: Staging DB matches live DB!"
    assert staging_storage != live_storage, "Isolation Failure: Staging storage matches live storage!"
    print("Gate A Result: PASSED (Non-aliasing and zero-shared paths verified)")
    results["gates"]["Gate_A_Isolation"] = "PASSED"

    # -------------------------------------------------------------------------
    # Gate B: Application Startup & Health Probes
    # -------------------------------------------------------------------------
    print("\n--- Gate B: Application Startup & Diagnostics ---")
    config_errors = validate_production_config()
    assert config_errors == [], f"Staging configuration validation failed: {config_errors}"
    print("Production config validation gate: CLEAN PASS (0 errors)")

    # Clean previous staging database run if present
    if staging_db.exists():
        staging_db.unlink()
    if staging_storage.exists():
        shutil.rmtree(staging_storage, ignore_errors=True)
    staging_storage.mkdir(parents=True, exist_ok=True)

    # Initialize staging database
    init_db(staging_db)
    migrations = get_applied_migrations(staging_db)
    print(f"Staging Database Migrations Tracked: {len(migrations)}")
    assert len(migrations) == 10, f"Expected 10 migrations, got {len(migrations)}"

    client = TestClient(app)

    # Liveness probe
    resp_live = client.get("/health/live")
    assert resp_live.status_code == 200
    assert resp_live.json()["status"] == "alive"
    print(f"GET /health/live -> 200 OK: {resp_live.json()}")

    # Readiness probe
    resp_ready = client.get("/health/ready")
    assert resp_ready.status_code == 200
    assert resp_ready.json()["status"] == "ready"
    assert resp_ready.json()["database"] == "connected"
    assert resp_ready.json()["storage"] == "writable"
    print(f"GET /health/ready -> 200 OK: {resp_ready.json()}")

    # High-level diagnostic probe
    resp_diag = client.get("/api/health")
    assert resp_diag.status_code == 200
    assert resp_diag.json()["status"] == "ok"
    print(f"GET /api/health -> 200 OK: {resp_diag.json()}")

    results["gates"]["Gate_B_Startup"] = "PASSED"

    # -------------------------------------------------------------------------
    # Gate C: Authentication, Staff RBAC & Portal Isolation
    # -------------------------------------------------------------------------
    print("\n--- Gate C: Authentication & Role Enforcement ---")

    # 1. Anonymous protection
    resp_anon = client.get("/api/portal/admin/health/summary")
    assert resp_anon.status_code == 401, f"Expected 401 on unauthenticated call, got {resp_anon.status_code}"
    print("Anonymous call to staff admin endpoint: 401 Unauthorized (PROTECTED)")

    # 2. Simulator bypass rejection in staging
    resp_sim = client.get("/api/portal/admin/health/summary", headers={"X-User-Role": "admin"})
    assert resp_sim.status_code == 401, f"Simulator bypass succeeded in staging! Code: {resp_sim.status_code}"
    print("Header-based test simulator injection: 401 Unauthorized (BLOCKED)")

    # 3. Provision Admin
    admin_user = provision_initial_admin("stg_admin", "StagingPassword2026!", "stg_admin@tradesathi.local")
    admin_token, admin_expiry = create_user_token(admin_user["id"])
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    print(f"Provisioned Staging Administrator: {admin_user['username']} ({admin_user['id']})")

    # Verify admin authenticated call
    resp_admin = client.get("/api/portal/admin/health/summary", headers=admin_headers)
    assert resp_admin.status_code == 200
    assert resp_admin.json()["status"] in ("healthy", "degraded")
    print(f"Staff Admin call to /api/portal/admin/health/summary -> 200 OK: database={resp_admin.json()['database']['status']}")

    # 4. Role Segregation (Sales & Warehouse)
    sales_user = create_user_record({"username": "stg_sales", "password": "SalesPassword2026!", "role": "sales"})
    sales_token, _ = create_user_token(sales_user["id"])
    sales_headers = {"Authorization": f"Bearer {sales_token}"}

    wh_user = create_user_record({"username": "stg_wh", "password": "WarehousePassword2026!", "role": "warehouse"})
    wh_token, _ = create_user_token(wh_user["id"])
    wh_headers = {"Authorization": f"Bearer {wh_token}"}

    # 5. Account Deactivation & Instant Revocation
    deact_user = create_user_record({"username": "stg_deact", "password": "DeactPassword2026!", "role": "viewer"})
    deact_token, _ = create_user_token(deact_user["id"])
    deact_headers = {"Authorization": f"Bearer {deact_token}"}

    # Deactivate user
    with get_connection() as conn:
        conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (deact_user["id"],))
        conn.commit()

    resp_deact = client.get("/api/portal/admin/health/summary", headers=deact_headers)
    assert resp_deact.status_code in (401, 403), f"Expected 401/403 for deactivated user, got {resp_deact.status_code}"
    print("Deactivated account session: 401/403 (INSTANTLY REVOKED)")

    results["gates"]["Gate_C_Authentication"] = "PASSED"

    # -------------------------------------------------------------------------
    # Gate D: Core Workflow Smoke Tests (Synthetic Data Only)
    # -------------------------------------------------------------------------
    print("\n--- Gate D: Core Workflow Smoke Tests ---")

    # Workflow 1: Master Data
    supp = create_supplier({
        "code": "SUPP-STG-01",
        "name": "Staging Precision Valves Ltd",
        "contact_email": "valves@supplier-staging.test",
        "city": "Ahmedabad",
        "country": "IN",
    })
    cust = create_customer({
        "code": "CUST-STG-01",
        "name": "Staging Gulf Engineering LLC",
        "contact_email": "procurement@gulf-staging.test",
        "city": "Dubai",
        "country": "AE",
    })
    wh = create_warehouse({
        "code": "WH-STG-MAIN",
        "name": "Staging Central Hub",
        "address": "Nhava Sheva SEZ, Sector 4",
        "city": "Navi Mumbai",
        "country": "IN",
    })
    loc = create_warehouse_location({
        "warehouse_id": wh["id"],
        "location_code": "LOC-STG-A1",
        "zone": "A",
        "rack": "1",
        "shelf": "1",
        "bin": "1",
    })
    prod = create_product({
        "sku": "SKU-STG-VALVE-50",
        "name": "Industrial Gate Valve 50mm",
        "uom": "PCS",
        "purchase_price": 120.0,
        "selling_price": 180.0,
        "currency": "USD",
        "hsn_code": "84818030",
        "reorder_level": 50,
    })
    print(f"Master Data: Supplier={supp['code']}, Customer={cust['code']}, Warehouse={wh['code']}, Product={prod['sku']}")
    results["workflows"]["Master_Data"] = "PASSED"

    # Workflow 2: Procurement, Inspection & Inventory Receipt
    po = create_purchase_order({
        "po_number": "PO-STG-2026-001",
        "supplier_id": supp["id"],
        "warehouse_id": wh["id"],
        "currency": "USD",
        "order_date": "2026-10-15",
        "items": [{
            "product_id": prod["id"],
            "sku": prod["sku"],
            "description": prod["name"],
            "ordered_qty": 100,
            "unit_price": 120.0,
            "uom": "PCS",
        }],
    })
    # Transition PO to approved
    po_app = transition_purchase_order_status(po["id"], "approved", performed_by=admin_user["username"])
    assert po_app["status"] == "approved"

    # Create Goods Receipt
    gr = create_goods_receipt({
        "receipt_number": "GR-STG-2026-001",
        "idempotency_key": "idemp-gr-stg-001",
        "po_id": po["id"],
        "receipt_date": "2026-10-15",
        "warehouse_id": wh["id"],
        "delivery_note_ref": "DN-SUPP-99112",
        "carrier": "Staging Logistics Express",
        "items": [{
            "po_item_id": po["items"][0]["id"],
            "location_id": loc["id"],
            "received_qty": 100,
            "accepted_qty": 95,
            "rejected_qty": 5,
            "quarantined_qty": 0,
            "rejection_reason": "Damaged threading on 5 units during transit",
        }],
    }, performed_by=wh_user["username"])
    # Post Goods Receipt to inventory
    gr_posted = post_goods_receipt_to_inventory(
        receipt_id=gr["id"],
        idempotency_key="idemp-post-gr-stg-001",
        performed_by=wh_user["username"],
    )
    assert gr_posted["receipt"]["status"] == "posted"
    print(f"Procurement: PO={po['po_number']} Approved -> GR={gr['receipt_number']} Posted (95 Accepted, 5 Rejected)")
    results["workflows"]["Procurement_and_GR"] = "PASSED"

    # Workflow 3: Stock Reservation & ATP
    res = create_stock_reservation({
        "reservation_number": "RES-STG-001",
        "product_id": prod["id"],
        "sku": prod["sku"],
        "warehouse_id": wh["id"],
        "location_id": loc["id"],
        "quantity": 25,
        "uom": "PCS",
        "reserved_by": sales_user["username"],
        "notes": "Allocation for urgent customer dispatch",
    })
    atp = get_product_atp(prod["id"], wh["id"])
    print(f"Inventory: Stock Reserved={res['quantity']} PCS -> ATP Available={atp} PCS")
    assert atp == 70.0  # 95 on hand - 25 reserved = 70
    results["workflows"]["Inventory_and_ATP"] = "PASSED"

    # Workflow 4: Sales Order, Picking, Packing & Dispatch
    so = create_sales_order({
        "order_number": "SO-STG-2026-001",
        "customer_id": cust["id"],
        "warehouse_id": wh["id"],
        "order_date": "2026-10-15",
        "currency": "USD",
        "payment_terms": "LC at sight",
        "incoterm": "FOB",
        "destination_port": "Jebel Ali",
        "items": [{
            "product_id": prod["id"],
            "sku": prod["sku"],
            "description": prod["name"],
            "ordered_quantity": 25,
            "unit_price": 180.0,
            "discount_pct": 0.0,
            "tax_rate_pct": 0.0,
        }],
    }, performed_by=sales_user["username"])
    so_conf = confirm_sales_order(so["id"], performed_by=sales_user["username"])
    assert so_conf["status"] == "confirmed"

    # Allocate sales order
    so_alloc = allocate_sales_order(so["id"], {"warehouse_id": wh["id"]}, performed_by=sales_user["username"])
    assert so_alloc["status"] == "allocated"

    # Pick list
    pl = create_sales_pick_list({
        "sales_order_id": so["id"],
        "warehouse_id": wh["id"],
        "assigned_picker": wh_user["username"],
    }, performed_by=wh_user["username"])
    pl_done = complete_sales_pick_list(pl["id"], {"items": []}, performed_by=wh_user["username"])
    assert pl_done["status"] == "completed"

    # Pack order
    so_pack = pack_sales_order(so["id"], {"notes": "Packed in certified export cartons"}, performed_by=wh_user["username"])
    assert so_pack["status"] == "packed"

    # Dispatch
    dsp = create_sales_dispatch({
        "sales_order_id": so["id"],
        "warehouse_id": wh["id"],
        "carrier": "Gulf Ocean Freight",
        "packages_count": 5,
        "items": [{
            "order_item_id": so["items"][0]["id"],
            "quantity_dispatched": 25,
        }],
    }, performed_by=wh_user["username"])
    assert dsp["status"] == "dispatched"

    # Deliver dispatch
    dsp_del = deliver_sales_dispatch(dsp["id"], {"delivery_date": "2026-10-15"}, performed_by=wh_user["username"])
    assert dsp_del["status"] == "delivered"

    print(f"Sales & Fulfilment: SO={so['order_number']} -> Allocated -> Picked={pl['pick_list_number']} -> Packed -> Dispatched={dsp['dispatch_number']} -> Delivered")
    results["workflows"]["Sales_and_Fulfilment"] = "PASSED"

    # Workflow 5: Invoicing, GST & Receivables Aging
    inv_payload = {
        "customer_id": cust["id"],
        "sales_order_id": so["id"],
        "dispatch_id": dsp["id"],
        "place_of_supply": "97-Other Territory / Export",
        "invoice_date": "2026-10-15",
        "due_date": "2026-11-15",
        "currency": "USD",
        "exchange_rate": 83.50,
        "tax_scheme": "EXPORT_LUT",
        "lut_bond_number": "ARN-STG-2026-00123",
        "items": [{
            "product_id": prod["id"],
            "product_sku": prod["sku"],
            "description": prod["name"],
            "hsn_code": "84818030",
            "quantity": 25.0,
            "unit_price": 180.0,
            "discount_pct": 0.0,
            "tax_classification": "zero_rated_export",
            "gst_rate_pct": 0.0,
        }],
    }
    res_inv = client.post("/api/finance/invoices", json=inv_payload, headers=admin_headers)
    assert res_inv.status_code == 200, res_inv.text
    inv_data = res_inv.json()
    assert inv_data["grand_total"] == 4500.0
    assert inv_data["tax_total"] == 0.0  # Zero-rated export under LUT

    # Post / Issue invoice
    res_post = client.post(
        f"/api/finance/invoices/{inv_data['id']}/status",
        json={"status": "issued", "reason": "Approved and issued for export shipment"},
        headers=admin_headers,
    )
    assert res_post.status_code == 200, res_post.text

    # Record customer payment
    pay_payload = {
        "customer_id": cust["id"],
        "payment_date": "2026-10-15",
        "amount": 2000.0,
        "currency": "USD",
        "exchange_rate": 83.50,
        "payment_method": "wire_swift",
        "reference_number": "WIRE-GULF-77331",
        "notes": "Advance wire payment against INV-STG-2026-001",
    }
    res_pay = client.post("/api/finance/payments", json=pay_payload, headers=admin_headers)
    assert res_pay.status_code == 200
    pay_data = res_pay.json()

    # Allocate payment to invoice
    alloc_payload = {
        "invoice_id": inv_data["id"],
        "amount": 2000.0,
        "notes": "Allocate USD 2,000 to invoice",
    }
    res_alloc = client.post(f"/api/finance/payments/{pay_data['id']}/allocate", json=alloc_payload, headers=admin_headers)
    assert res_alloc.status_code == 200

    # Aging report & GST summary via Finance API
    res_aging = client.get("/api/finance/reports/receivables-aging", headers=admin_headers)
    assert res_aging.status_code == 200, res_aging.text
    res_gst = client.get("/api/finance/reports/gst-outward", headers=admin_headers)
    assert res_gst.status_code == 200, res_gst.text

    # Executive Dashboard KPIs & Financial Reports via Reports API
    res_kpis = client.get("/api/reports/dashboard-kpis", headers=admin_headers)
    assert res_kpis.status_code == 200, res_kpis.text
    res_fin = client.get("/api/reports/finance", headers=admin_headers)
    assert res_fin.status_code == 200, res_fin.text

    # CSV Export with formula injection defense
    res_csv = client.get("/api/reports/export-csv?report_type=invoices", headers=admin_headers)
    assert res_csv.status_code == 200, res_csv.text
    assert "text/csv" in res_csv.headers.get("content-type", "")

    print(f"Invoicing & Finance: Invoice={inv_data['invoice_number']} -> Issued -> Paid USD 2,000 Allocated -> Aging & GST Reports OK")
    results["workflows"]["Invoicing_and_Finance"] = "PASSED"

    # Workflow 6: Barcode & QR Generation & Scan Lookup
    label_res = generate_entity_label("product", prod["sku"], label_size="4x2", created_by="stg_admin")
    assert label_res["barcode"]["barcode_value"] != ""
    assert "<svg" in label_res["html_content"]

    # Verify scan lookup endpoint via HTTP /api/portal/scan-resolve
    scan_payload = {"scanned_code": label_res["barcode"]["barcode_value"]}
    resp_scan = client.post("/api/portal/scan-resolve", json=scan_payload, headers=admin_headers)
    assert resp_scan.status_code == 200, resp_scan.text
    scan_data = resp_scan.json()
    assert scan_data["status"] == "resolved"
    assert scan_data["entity"]["data"]["product"]["sku"] == prod["sku"]
    print(f"Barcode & QR: Generated Label for SKU={prod['sku']} -> Resolved via POST /api/portal/scan-resolve -> 200 OK")
    results["workflows"]["Barcodes_and_Scanning"] = "PASSED"

    # Workflow 7: Supplier & Customer Portals & Collaboration Notifications
    # Create a dedicated PO for supplier portal interaction
    po2 = create_purchase_order({
        "po_number": "PO-STG-2026-002",
        "supplier_id": supp["id"],
        "warehouse_id": wh["id"],
        "order_date": "2026-10-15",
        "currency": "INR",
        "items": [{
            "product_id": prod["id"],
            "sku": prod["sku"],
            "description": prod["name"],
            "ordered_qty": 50,
            "unit_price": 120.0,
            "uom": "PCS",
        }],
    })
    transition_purchase_order_status(po2["id"], "approved", performed_by=admin_user["username"])

    # Internal Admin invites supplier
    resp_inv_supp = client.post("/api/portal/admin/invitations", json={
        "account_type": "supplier",
        "organization_id": supp["id"],
        "email": "valves-rep@supplier-staging.test",
        "expires_in_days": 7,
    }, headers=admin_headers)
    assert resp_inv_supp.status_code == 201, resp_inv_supp.text
    inv_supp_token = resp_inv_supp.json()["invitation_token"]

    # Portal Supplier accepts invitation & sets credentials
    resp_acc_supp = client.post("/api/portal/invitations/accept", json={
        "invitation_token": inv_supp_token,
        "username": "vikram_valves",
        "password": "PortalPassword2026!",
    })
    assert resp_acc_supp.status_code == 200, resp_acc_supp.text

    # Supplier logs in
    resp_supp_login = client.post("/api/portal/auth/login", json={
        "username": "vikram_valves",
        "password": "PortalPassword2026!",
    })
    assert resp_supp_login.status_code == 200, resp_supp_login.text
    supp_token = resp_supp_login.json()["access_token"]
    supp_headers = {"Authorization": f"Bearer {supp_token}"}

    # Supplier submits delivery commitment
    cmt_payload = {
        "proposed_delivery_date": "2026-10-30",
        "supplier_dispatch_ref": "STG-DISP-001",
        "carrier_name": "Container Rail Express",
        "supplier_comments": "First batch ready for packaging",
        "lines": [{
            "po_item_id": po2["items"][0]["id"],
            "committed_qty": 50,
        }],
    }
    resp_cmt = client.post(f"/api/portal/supplier/purchase-orders/{po2['id']}/commitments", json=cmt_payload, headers=supp_headers)
    assert resp_cmt.status_code == 200, resp_cmt.text

    # Supplier submits ASN
    asn_payload = {
        "po_id": po2["id"],
        "dispatch_reference": "ASN-STG-VALVE-001",
        "dispatch_date": "2026-10-15",
        "expected_arrival_date": "2026-10-31",
        "package_count": 2,
        "carrier_name": "Container Rail Express",
        "items": [{
            "po_item_id": po2["items"][0]["id"],
            "shipped_qty": 50,
            "package_label": "BOX-01",
        }],
    }
    resp_asn = client.post("/api/portal/supplier/asns", json=asn_payload, headers=supp_headers)
    assert resp_asn.status_code in (200, 201), resp_asn.text

    # Internal Admin invites customer
    resp_inv_cust = client.post("/api/portal/admin/invitations", json={
        "account_type": "customer",
        "organization_id": cust["id"],
        "email": "buyer@gulf-distribution.test",
        "expires_in_days": 7,
    }, headers=admin_headers)
    assert resp_inv_cust.status_code == 201, resp_inv_cust.text
    inv_cust_token = resp_inv_cust.json()["invitation_token"]

    # Customer accepts invitation & sets credentials
    resp_acc_cust = client.post("/api/portal/invitations/accept", json={
        "invitation_token": inv_cust_token,
        "username": "tariq_gulf",
        "password": "PortalPassword2026!",
    })
    assert resp_acc_cust.status_code == 200, resp_acc_cust.text

    # Customer logs in
    resp_cust_login = client.post("/api/portal/auth/login", json={
        "username": "tariq_gulf",
        "password": "PortalPassword2026!",
    })
    assert resp_cust_login.status_code == 200, resp_cust_login.text
    cust_token = resp_cust_login.json()["access_token"]
    cust_headers = {"Authorization": f"Bearer {cust_token}"}

    # Customer creates order thread
    thread_payload = {
        "subject": "Shipping Schedule & BL Inquiry",
        "initial_message": "Please confirm the expected vessel arrival date and bill of lading copy.",
    }
    resp_thread = client.post(f"/api/portal/customer/sales-orders/{so['id']}/threads", json=thread_payload, headers=cust_headers)
    assert resp_thread.status_code == 201, resp_thread.text

    # Cross-portal Anti-IDOR Authorization Enforcements:
    # 1. Supplier cannot access staff health endpoint
    resp_cross1 = client.get("/api/portal/admin/health/summary", headers=supp_headers)
    assert resp_cross1.status_code in (401, 403), f"Security breach: Supplier accessed admin! {resp_cross1.status_code}"

    # 2. Customer cannot access supplier purchase orders
    resp_cross2 = client.get("/api/portal/supplier/purchase-orders", headers=cust_headers)
    assert resp_cross2.status_code in (401, 403), f"Security breach: Customer accessed supplier POs! {resp_cross2.status_code}"

    # 3. Supplier cannot access customer sales orders
    resp_cross3 = client.get("/api/portal/customer/sales-orders", headers=supp_headers)
    assert resp_cross3.status_code in (401, 403), f"Security breach: Supplier accessed customer SOs! {resp_cross3.status_code}"

    print(f"Portals: Supplier & Customer Onboarded -> Commitment -> ASN -> Thread -> Anti-IDOR Isolation Enforced")
    results["workflows"]["Collaboration_and_Portals"] = "PASSED"

    results["gates"]["Gate_D_Workflows"] = "PASSED"

    # -------------------------------------------------------------------------
    # Gate E: Disaster Recovery & Operational Drills
    # -------------------------------------------------------------------------
    print("\n--- Gate E: Disaster Recovery & Operational Checks ---")

    # 1. Create Staging Snapshot
    manifest = create_backup(
        source_db_path=staging_db,
        source_storage_dir=staging_storage,
        backup_root=staging_backups,
    )
    backup_id = manifest["backup_id"]
    backup_folder = staging_backups / backup_id
    print(f"Staging Backup Created: {backup_id} in {backup_folder}")

    # 2. Verify Staging Backup Snapshot
    v_res = verify_backup(backup_folder)
    assert v_res["verified"] is True
    print(f"Staging Backup Verified: db_sha256={v_res['database_sha256']}")

    # 3. Restore to Isolated Target
    target_restored_db = staging_recovery / "tradesathi_restored.db"
    target_restored_storage = staging_recovery / "documents"
    if target_restored_db.exists():
        target_restored_db.unlink()
    if target_restored_storage.exists():
        shutil.rmtree(target_restored_storage, ignore_errors=True)

    r_res = restore_backup(backup_folder, target_restored_db, target_restored_storage)
    assert r_res["status"] == "success"

    # 4. Deep Restoration Integrity Check
    r_int = verify_restoration_integrity(target_restored_db, target_restored_storage)
    assert r_int["status"] == "verified"
    print(f"Restored Database Deep Check: {r_int['status']}, Shipments={r_int['shipments_count']}, Reviews={r_int['reviews_count']}")

    # 5. Worker Lease Reclamation
    reclaimed = reclaim_expired_leases()
    print(f"Notification Worker Lease Reclamation: {reclaimed} expired leases reclaimed safely")

    # 6. Offline Delivery Processing
    delivery_stats = process_notification_deliveries(batch_size=10, worker_id="stg-worker-1")
    print(f"Offline Notification Delivery Queue Processing: {delivery_stats}")

    results["gates"]["Gate_E_Recovery"] = "PASSED"

    # -------------------------------------------------------------------------
    # Final Post-Staging Live Baseline Verification
    # -------------------------------------------------------------------------
    print("\n--- Post-Staging Live Asset Verification ---")
    live_hash_post = hashlib.sha256(live_db.read_bytes()).hexdigest()
    live_size_post = live_db.stat().st_size
    live_docs_post = len([f for f in live_storage.rglob("*") if f.is_file()])

    print(f"Live DB Post-Check:        {live_hash_post} (Size: {live_size_post} bytes)")
    print(f"Live Storage Post-Check:   {live_docs_post} files")

    assert live_hash_pre == live_hash_post, "FATAL: LIVE DATABASE HASH MUTATED!"
    assert live_size_pre == live_size_post, "FATAL: LIVE DATABASE SIZE MUTATED!"
    assert live_docs_pre == live_docs_post, "FATAL: LIVE STORAGE FILE COUNT MUTATED!"
    print("Zero Live Asset Mutation Invariant: 100% BIT-FOR-BIT IDENTICAL")

    print("\n" + "=" * 80)
    print("CONTROLLED ISOLATED STAGING DEPLOYMENT DRILL: COMPLETE & ALL GATES PASSED")
    print("=" * 80)

    results["decision"] = "STAGING VERIFIED"
    return results


if __name__ == "__main__":
    run_staging_deployment()
