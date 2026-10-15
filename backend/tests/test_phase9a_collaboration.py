"""TradeSathi AI — Phase 9A: Secure Collaboration Adversarial Test Suite
Comprehensive security, tenant-isolation, IDOR, and lifecycle verification.
"""

import json
import sqlite3
import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from app.collaboration import hash_portal_token
from app.db import get_connection, get_db_path, init_db
from app.main import app
from app.master_data import create_customer, create_product, create_supplier
from app.procurement import create_purchase_order, transition_purchase_order_status
from app.sales import create_sales_order
from app.storage import get_storage_dir, save_document_file


@pytest.fixture
def auth_client():
    return TestClient(app)


def seed_synthetic_collaboration_data():
    """Seed synthetic Supplier A/B, Customer A/B, and test products."""
    now = datetime.now(timezone.utc).isoformat()
    # 1. Products
    p1 = create_product({
        "sku": "SKU-COLLAB-01",
        "name": "Darjeeling Special Tea Grade 1",
        "category": "Tea",
        "default_purchase_cost": 450.0,
        "default_selling_price": 750.0,
        "uom": "KGS",
    })

    # 2. Synthetic Suppliers
    sup_a = create_supplier({
        "code": "SUP-SYNTH-A",
        "name": "Alpha Himalayan Tea Estate",
        "email": "alpha@supplier-a.com",
        "currency": "INR",
        "country": "IN",
    })
    sup_b = create_supplier({
        "code": "SUP-SYNTH-B",
        "name": "Beta Valley Plantations",
        "email": "beta@supplier-b.com",
        "currency": "INR",
        "country": "IN",
    })

    # 3. Synthetic Customers
    cust_a = create_customer({
        "code": "CUST-SYNTH-A",
        "name": "Global Beverages London",
        "email": "procurement@globalbeverages.co.uk",
        "country": "GB",
        "currency": "USD",
    })
    cust_b = create_customer({
        "code": "CUST-SYNTH-B",
        "name": "Nippon Tea Importers Tokyo",
        "email": "orders@nippontea.co.jp",
        "country": "JP",
        "currency": "USD",
    })

    # 4. Purchase Orders for Supplier A and Supplier B
    po_a = create_purchase_order({
        "po_number": "PO-SYNTH-A-001",
        "supplier_id": sup_a["id"],
        "order_date": "2026-10-15",
        "currency": "INR",
        "items": [{"product_id": p1["id"], "ordered_qty": 100.0, "unit_price": 450.0}],
    })
    # Submit PO A so it is eligible for acknowledgement
    transition_purchase_order_status(po_a["id"], "submitted")

    po_b = create_purchase_order({
        "po_number": "PO-SYNTH-B-001",
        "supplier_id": sup_b["id"],
        "order_date": "2026-10-15",
        "currency": "INR",
        "items": [{"product_id": p1["id"], "ordered_qty": 200.0, "unit_price": 450.0}],
    })
    transition_purchase_order_status(po_b["id"], "submitted")

    # 5. Sales Orders for Customer A and Customer B
    so_a = create_sales_order({
        "order_number": "SO-SYNTH-A-001",
        "customer_id": cust_a["id"],
        "order_date": "2026-10-15",
        "currency": "USD",
        "items": [{"product_id": p1["id"], "ordered_quantity": 50.0, "unit_price": 10.0}],
    })

    so_b = create_sales_order({
        "order_number": "SO-SYNTH-B-001",
        "customer_id": cust_b["id"],
        "order_date": "2026-10-15",
        "currency": "USD",
        "items": [{"product_id": p1["id"], "ordered_quantity": 80.0, "unit_price": 10.0}],
    })

    return {
        "product": p1,
        "sup_a": sup_a,
        "sup_b": sup_b,
        "cust_a": cust_a,
        "cust_b": cust_b,
        "po_a": po_a,
        "po_b": po_b,
        "so_a": so_a,
        "so_b": so_b,
    }


def helper_create_and_activate_portal_user(client: TestClient, account_type: str, org_id: str, username: str, email: str, role="admin"):
    """Helper to generate an invitation and activate a portal user."""
    # 1. Staff generates invitation
    inv_resp = client.post(
        "/api/portal/admin/invitations",
        json={"account_type": account_type, "organization_id": org_id, "email": email},
        headers={"X-User-Role": role, "X-User-Name": "Staff Admin"},
    )
    assert inv_resp.status_code == 201
    inv_data = inv_resp.json()
    raw_token = inv_data["invitation_token"]

    # 2. External partner activates account
    act_resp = client.post(
        "/api/portal/invitations/accept",
        json={"invitation_token": raw_token, "username": username, "password": "SecurePassword123!"},
    )
    assert act_resp.status_code == 200
    act_data = act_resp.json()
    bearer = act_data["access_token"]
    user_id = act_data["user"]["id"]

    return {
        "invitation_id": inv_data["id"],
        "raw_invitation_token": raw_token,
        "bearer_token": bearer,
        "user_id": user_id,
        "username": username,
    }


# ==========================================
# GATE B: External Identity, Invitation Lifecycle & Revocation
# ==========================================

def test_invitation_lifecycle_and_single_use(auth_client):
    """Test full invitation lifecycle: creation, verification, acceptance, and replay rejection."""
    data = seed_synthetic_collaboration_data()

    # Staff creates invitation for Supplier A
    resp = auth_client.post(
        "/api/portal/admin/invitations",
        json={"account_type": "supplier", "organization_id": data["sup_a"]["id"], "email": "contact@alpha.com"},
        headers={"X-User-Role": "procurement", "X-User-Name": "Procurement Officer"},
    )
    assert resp.status_code == 201
    inv = resp.json()
    raw_token = inv["invitation_token"]
    assert raw_token is not None

    # Verify invitation endpoint returns non-sensitive details
    v_resp = auth_client.post("/api/portal/invitations/verify", json={"invitation_token": raw_token})
    assert v_resp.status_code == 200
    v_data = v_resp.json()
    assert v_data["valid"] is True
    assert v_data["organization_id"] == data["sup_a"]["id"]
    assert v_data["account_type"] == "supplier"

    # Accept invitation
    acc_resp = auth_client.post(
        "/api/portal/invitations/accept",
        json={"invitation_token": raw_token, "username": "supplier_alpha_user", "password": "StrongPassword99!"},
    )
    assert acc_resp.status_code == 200
    acc_data = acc_resp.json()
    assert "access_token" in acc_data
    assert acc_data["user"]["organization_id"] == data["sup_a"]["id"]

    # REPLAY ATTACK: Re-submitting same invitation token must fail with 400
    replay_resp = auth_client.post(
        "/api/portal/invitations/accept",
        json={"invitation_token": raw_token, "username": "supplier_alpha_user_2", "password": "StrongPassword99!"},
    )
    assert replay_resp.status_code == 400
    assert "expired" in replay_resp.json()["detail"].lower() or "invalid" in replay_resp.json()["detail"].lower()


def test_invitation_role_authorization_guards(auth_client):
    """Unauthorized staff roles cannot issue invitations."""
    data = seed_synthetic_collaboration_data()

    # Viewer role cannot invite
    resp_viewer = auth_client.post(
        "/api/portal/admin/invitations",
        json={"account_type": "supplier", "organization_id": data["sup_a"]["id"], "email": "test@alpha.com"},
        headers={"X-User-Role": "viewer", "X-User-Name": "Viewer Staff"},
    )
    assert resp_viewer.status_code == 403

    # Procurement role cannot invite customers
    resp_proc_cust = auth_client.post(
        "/api/portal/admin/invitations",
        json={"account_type": "customer", "organization_id": data["cust_a"]["id"], "email": "test@cust.com"},
        headers={"X-User-Role": "procurement", "X-User-Name": "Procurement Staff"},
    )
    assert resp_proc_cust.status_code == 403

    # Sales role cannot invite suppliers
    resp_sales_sup = auth_client.post(
        "/api/portal/admin/invitations",
        json={"account_type": "supplier", "organization_id": data["sup_a"]["id"], "email": "test@sup.com"},
        headers={"X-User-Role": "sales", "X-User-Name": "Sales Staff"},
    )
    assert resp_sales_sup.status_code == 403


def test_invitation_revocation_blocks_activation(auth_client):
    """Revoking an invitation immediately invalidates it."""
    data = seed_synthetic_collaboration_data()
    inv_resp = auth_client.post(
        "/api/portal/admin/invitations",
        json={"account_type": "supplier", "organization_id": data["sup_a"]["id"], "email": "temp@alpha.com"},
        headers={"X-User-Role": "admin", "X-User-Name": "Admin"},
    )
    inv = inv_resp.json()
    raw_token = inv["invitation_token"]

    # Staff revokes invitation
    rev_resp = auth_client.post(
        f"/api/portal/admin/invitations/{inv['id']}/revoke",
        headers={"X-User-Role": "admin", "X-User-Name": "Admin"},
    )
    assert rev_resp.status_code == 200

    # Verification and acceptance fail
    v_resp = auth_client.post("/api/portal/invitations/verify", json={"invitation_token": raw_token})
    assert v_resp.status_code == 400

    acc_resp = auth_client.post(
        "/api/portal/invitations/accept",
        json={"invitation_token": raw_token, "username": "temp_user", "password": "Password123!"},
    )
    assert acc_resp.status_code == 400


def test_user_deactivation_instantly_revokes_tokens(auth_client):
    """Deactivating an external user account immediately revokes all active tokens."""
    data = seed_synthetic_collaboration_data()
    user = helper_create_and_activate_portal_user(
        auth_client, "supplier", data["sup_a"]["id"], "sup_user_deact", "sup_deact@alpha.com"
    )

    # User can access their purchase orders with active token
    auth_headers = {"Authorization": f"Bearer {user['bearer_token']}"}
    ok_resp = auth_client.get("/api/portal/supplier/purchase-orders", headers=auth_headers)
    assert ok_resp.status_code == 200

    # Staff deactivates account
    deact_resp = auth_client.post(
        f"/api/portal/admin/users/{user['user_id']}/deactivate",
        headers={"X-User-Role": "admin", "X-User-Name": "Admin"},
    )
    assert deact_resp.status_code == 200

    # Subsequent request using previous token must fail with 401
    fail_resp = auth_client.get("/api/portal/supplier/purchase-orders", headers=auth_headers)
    assert fail_resp.status_code in (401, 403)


# ==========================================
# GATE C: Strict Supplier / Customer Tenant Isolation (Anti-IDOR)
# ==========================================

def test_supplier_tenant_isolation_and_anti_idor(auth_client):
    """
    Supplier A CANNOT see or access Supplier B's purchase orders.
    Supplier A CANNOT acknowledge Supplier B's purchase orders.
    """
    data = seed_synthetic_collaboration_data()
    sup_a_user = helper_create_and_activate_portal_user(
        auth_client, "supplier", data["sup_a"]["id"], "user_sup_a", "usera@alpha.com"
    )
    sup_b_user = helper_create_and_activate_portal_user(
        auth_client, "supplier", data["sup_b"]["id"], "user_sup_b", "userb@beta.com"
    )

    headers_a = {"Authorization": f"Bearer {sup_a_user['bearer_token']}"}
    headers_b = {"Authorization": f"Bearer {sup_b_user['bearer_token']}"}

    # 1. Supplier A list only contains PO A
    list_a = auth_client.get("/api/portal/supplier/purchase-orders", headers=headers_a).json()
    po_ids_a = [item["id"] for item in list_a["items"]]
    assert data["po_a"]["id"] in po_ids_a
    assert data["po_b"]["id"] not in po_ids_a

    # 2. Supplier B list only contains PO B
    list_b = auth_client.get("/api/portal/supplier/purchase-orders", headers=headers_b).json()
    po_ids_b = [item["id"] for item in list_b["items"]]
    assert data["po_b"]["id"] in po_ids_b
    assert data["po_a"]["id"] not in po_ids_b

    # 3. IDOR: Supplier A attempts to GET Supplier B's PO directly -> 404 Not Found
    idor_get = auth_client.get(f"/api/portal/supplier/purchase-orders/{data['po_b']['id']}", headers=headers_a)
    assert idor_get.status_code == 404

    # 4. IDOR: Supplier A attempts to acknowledge Supplier B's PO -> 404 Not Found
    idor_ack = auth_client.post(
        f"/api/portal/supplier/purchase-orders/{data['po_b']['id']}/acknowledge",
        headers=headers_a,
        json={"action": "accept", "supplier_comments": "Illegally acknowledging B's order"},
    )
    assert idor_ack.status_code == 404


def test_customer_tenant_isolation_and_anti_idor(auth_client):
    """
    Customer A CANNOT see or access Customer B's sales orders, invoices, or dispatches.
    """
    data = seed_synthetic_collaboration_data()
    cust_a_user = helper_create_and_activate_portal_user(
        auth_client, "customer", data["cust_a"]["id"], "user_cust_a", "cust_a@global.co.uk"
    )
    cust_b_user = helper_create_and_activate_portal_user(
        auth_client, "customer", data["cust_b"]["id"], "user_cust_b", "cust_b@nippon.co.jp"
    )

    headers_a = {"Authorization": f"Bearer {cust_a_user['bearer_token']}"}
    headers_b = {"Authorization": f"Bearer {cust_b_user['bearer_token']}"}

    # 1. Customer A list only contains SO A
    list_a = auth_client.get("/api/portal/customer/sales-orders", headers=headers_a).json()
    so_ids_a = [item["id"] for item in list_a["items"]]
    assert data["so_a"]["id"] in so_ids_a
    assert data["so_b"]["id"] not in so_ids_a

    # 2. IDOR: Customer A attempts to GET Customer B's SO directly -> 404 Not Found
    idor_get = auth_client.get(f"/api/portal/customer/sales-orders/{data['so_b']['id']}", headers=headers_a)
    assert idor_get.status_code == 404


def test_cross_portal_role_segregation(auth_client):
    """
    Supplier account calling Customer endpoint -> 403 Forbidden.
    Customer account calling Supplier endpoint -> 403 Forbidden.
    External account calling internal admin/staff endpoints -> 401 Unauthorized.
    """
    data = seed_synthetic_collaboration_data()
    sup_user = helper_create_and_activate_portal_user(
        auth_client, "supplier", data["sup_a"]["id"], "seg_sup", "seg_sup@alpha.com"
    )
    cust_user = helper_create_and_activate_portal_user(
        auth_client, "customer", data["cust_a"]["id"], "seg_cust", "seg_cust@global.com"
    )

    sup_headers = {"Authorization": f"Bearer {sup_user['bearer_token']}"}
    cust_headers = {"Authorization": f"Bearer {cust_user['bearer_token']}"}

    # Supplier calls customer sales orders endpoint
    resp1 = auth_client.get("/api/portal/customer/sales-orders", headers=sup_headers)
    assert resp1.status_code == 403

    # Customer calls supplier purchase orders endpoint
    resp2 = auth_client.get("/api/portal/supplier/purchase-orders", headers=cust_headers)
    assert resp2.status_code == 403

    # External account calls internal staff invitation admin endpoint
    resp3 = auth_client.post(
        "/api/portal/admin/invitations",
        json={"account_type": "supplier", "organization_id": data["sup_a"]["id"], "email": "test@test.com"},
        headers=sup_headers,
    )
    assert resp3.status_code == 401


# ==========================================
# GATE D: Secure Document Access & Authorization
# ==========================================

def test_document_sharing_authorization_and_cross_tenant_isolation(auth_client):
    """
    Document access requires explicit sharing (shared_with_customer = 1) AND authoritative tenancy ownership.
    Unshared documents and cross-tenant downloads are strictly denied (404).
    """
    data = seed_synthetic_collaboration_data()
    cust_a_user = helper_create_and_activate_portal_user(
        auth_client, "customer", data["cust_a"]["id"], "doc_cust_a", "doc_cust_a@global.com"
    )
    cust_b_user = helper_create_and_activate_portal_user(
        auth_client, "customer", data["cust_b"]["id"], "doc_cust_b", "doc_cust_b@nippon.com"
    )

    # Create shipment record to satisfy foreign key constraint on documents
    from app.db import create_shipment
    create_shipment({
        "id": "shp-collab-01",
        "reference": "SHP-COLLAB-001",
        "customer_id": data["cust_a"]["id"],
    })

    # Create a physical document file linked to Customer A's sales order
    doc_bytes = b"CONFIDENTIAL COMMERCIAL INVOICE FOR CUSTOMER A - DO NOT LEAK"
    uid, storage_key, file_hash = save_document_file("shp-collab-01", "Customer_A_Invoice.pdf", doc_bytes)

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO documents (
                id, shipment_id, sales_order_id, original_filename, clean_filename,
                document_type, uploaded_at, storage_key, file_size, file_hash,
                processing_status, review_status, shared_with_customer, created_at, updated_at
            ) VALUES (?, 'shp-collab-01', ?, 'Customer_A_Invoice.pdf', 'Customer_A_Invoice.pdf',
                      'commercial_invoice', '2026-10-15T12:00:00Z', ?, ?, ?, 'completed', 'verified_by_user', 0,
                      '2026-10-15T12:00:00Z', '2026-10-15T12:00:00Z')
            """,
            (uid, data["so_a"]["id"], storage_key, len(doc_bytes), file_hash),
        )
        conn.commit()

    headers_a = {"Authorization": f"Bearer {cust_a_user['bearer_token']}"}
    headers_b = {"Authorization": f"Bearer {cust_b_user['bearer_token']}"}

    # 1. Unshared document: Customer A attempts download before staff sharing -> 404 Not Found
    unshared_resp = auth_client.get(f"/api/portal/documents/{uid}/download", headers=headers_a)
    assert unshared_resp.status_code == 404

    # 2. Staff explicitly shares document with customer
    share_resp = auth_client.post(
        f"/api/portal/admin/documents/{uid}/share",
        json={"shared_with_customer": True, "sharing_notes": "Approved for customer download"},
        headers={"X-User-Role": "sales", "X-User-Name": "Sales Rep"},
    )
    assert share_resp.status_code == 200

    # 3. Customer A can now download their shared document
    dl_a = auth_client.get(f"/api/portal/documents/{uid}/download", headers=headers_a)
    assert dl_a.status_code == 200
    assert dl_a.content == doc_bytes

    # 4. CROSS-TENANT DEFENSE: Customer B attempts to download Customer A's shared document -> 404 Not Found
    dl_b = auth_client.get(f"/api/portal/documents/{uid}/download", headers=headers_b)
    assert dl_b.status_code == 404


# ==========================================
# GATE E: Purchase Order Acknowledgement Workflow & Idempotency
# ==========================================

def test_po_acknowledgement_lifecycle_and_idempotency(auth_client):
    """
    Supplier acknowledges PO with accept, reject, clarification.
    Validates comments length, proposed delivery date, idempotency, and non-mutation of inventory.
    """
    data = seed_synthetic_collaboration_data()
    sup_user = helper_create_and_activate_portal_user(
        auth_client, "supplier", data["sup_a"]["id"], "ack_sup", "ack_sup@alpha.com"
    )
    headers = {"Authorization": f"Bearer {sup_user['bearer_token']}"}

    # 1. Reject invalid action
    inv_act = auth_client.post(
        f"/api/portal/supplier/purchase-orders/{data['po_a']['id']}/acknowledge",
        headers=headers,
        json={"action": "invalid_action"},
    )
    assert inv_act.status_code == 422

    # 2. Reject excessive comments (>1000 chars)
    long_comment = "A" * 1001
    toolong_resp = auth_client.post(
        f"/api/portal/supplier/purchase-orders/{data['po_a']['id']}/acknowledge",
        headers=headers,
        json={"action": "request_clarification", "supplier_comments": long_comment},
    )
    assert toolong_resp.status_code in (400, 422)

    # 3. Successful acknowledgement with proposed delivery date and idempotency key
    idem_key = "IDEM-ACK-SYNTH-001"
    ack_resp = auth_client.post(
        f"/api/portal/supplier/purchase-orders/{data['po_a']['id']}/acknowledge",
        headers=headers,
        json={
            "action": "accept",
            "supplier_comments": "Accepted. Production scheduled.",
            "proposed_delivery_date": "2026-10-25",
            "idempotency_key": idem_key,
        },
    )
    assert ack_resp.status_code == 200
    ack_data = ack_resp.json()
    assert ack_data["status"] == "success"
    assert ack_data["action"] == "accept"

    # 4. Verify purchase order has updated ack fields, but internal status is STILL 'submitted'
    with get_connection() as conn:
        po_row = conn.execute("SELECT status, supplier_ack_status, supplier_ack_by FROM purchase_orders WHERE id = ?", (data["po_a"]["id"],)).fetchone()
        assert po_row["status"] == "submitted"  # Did NOT mutate internal approval
        assert po_row["supplier_ack_status"] == "accept"
        assert po_row["supplier_ack_by"] == sup_user["username"]

        # Ensure NO goods receipts or inventory movements were generated
        gr_count = conn.execute("SELECT count(*) FROM goods_receipts WHERE po_id = ?", (data["po_a"]["id"],)).fetchone()[0]
        assert gr_count == 0
        mov_count = conn.execute("SELECT count(*) FROM inventory_movements WHERE reference_doc_id = ?", (data["po_a"]["id"],)).fetchone()[0]
        assert mov_count == 0

    # 5. IDEMPOTENT RE-SUBMISSION: Re-submitting with identical key returns idempotent duplicate
    dup_resp = auth_client.post(
        f"/api/portal/supplier/purchase-orders/{data['po_a']['id']}/acknowledge",
        headers=headers,
        json={
            "action": "accept",
            "supplier_comments": "Accepted. Production scheduled.",
            "proposed_delivery_date": "2026-10-25",
            "idempotency_key": idem_key,
        },
    )
    assert dup_resp.status_code == 200
    assert dup_resp.json()["status"] == "idempotent_duplicate"

    # 6. Immutable trigger guard: po_acknowledgements records CANNOT be updated or deleted
    with get_connection() as conn:
        ack_id = ack_data["acknowledgement_id"]
        with pytest.raises(sqlite3.IntegrityError, match="Audit integrity violation"):
            conn.execute("UPDATE po_acknowledgements SET action = 'reject' WHERE id = ?", (ack_id,))

        with pytest.raises(sqlite3.IntegrityError, match="Audit integrity violation"):
            conn.execute("DELETE FROM po_acknowledgements WHERE id = ?", (ack_id,))


# ==========================================
# GATE F: Secret-Safe Audit Logging
# ==========================================

def test_collaboration_audit_logs_contain_no_secrets(auth_client):
    """
    Ensure all collaboration audit logs record actor and organization,
    while zero passwords, tokens, or hashes are recorded in changes_json.
    """
    data = seed_synthetic_collaboration_data()
    user = helper_create_and_activate_portal_user(
        auth_client, "supplier", data["sup_a"]["id"], "audit_sup", "audit_sup@alpha.com"
    )

    with get_connection() as conn:
        logs = conn.execute(
            "SELECT * FROM erp_audit_logs WHERE performed_by LIKE '%audit_sup%' OR changes_json LIKE '%audit_sup%'",
        ).fetchall()

        assert len(logs) > 0
        for log in logs:
            payload = log["changes_json"]
            assert "SecurePassword123!" not in payload
            assert "password_hash" not in payload
            assert "scrypt" not in payload
            assert user["bearer_token"] not in payload
            assert user["raw_invitation_token"] not in payload


# ==========================================
# GATE H: Two-Pass Migration Idempotency & Database Integrity
# ==========================================

def test_migration_2pass_idempotency_and_integrity(isolated_test_environment):
    """Run init_db() twice on isolated clone and verify PRAGMA integrity."""
    db_path = isolated_test_environment["db_path"]

    # First pass already ran in fixture, run second pass
    init_db(db_path)

    with get_connection(db_path) as conn:
        cur = conn.cursor()
        integrity = cur.execute("PRAGMA integrity_check").fetchone()[0]
        assert integrity == "ok"

        fk_issues = cur.execute("PRAGMA foreign_key_check").fetchall()
        assert len(fk_issues) == 0
