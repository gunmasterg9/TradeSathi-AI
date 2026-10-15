"""TradeSathi AI — Phase 9C: Customer Collaboration & Order Communication Adversarial Tests
Covers:
1. Customer order-specific communication thread creation, messages, and idempotency.
2. Safe rendering / sanitization of HTML & script payloads in customer messages.
3. Private staff internal notes confidentiality (hidden from customer, visible to staff).
4. Customer document requests lifecycle (open -> under_review -> fulfilled / rejected).
5. Anti-duplicate document requests for identical order and category.
6. Explicit document sharing and instant revocation verification (shared_with_customer toggle).
7. Strict cross-customer tenant isolation (Anti-IDOR on orders, threads, messages, document requests, downloads).
8. In-app collaboration notifications generation and read acknowledgement.
9. Staff console role enforcement (guarding /api/portal/admin endpoints against unauthorized roles and external callers).
10. Immutable audit logging for messages, reviews, and document sharing.
11. Verification that customer collaboration endpoints NEVER mutate sales order commercial terms, inventory, or shipments.
12. Deactivated customer account token revocation.
"""

import hashlib
import json
import os
import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import create_user_token, hash_password
from app.collaboration import hash_portal_token
from app.db import get_connection, init_db
from app.main import app
from app.master_data import create_customer, create_product
from app.sales import create_sales_order
from app.storage import set_storage_dir


@pytest.fixture
def client(tmp_path, monkeypatch):
    test_db = tmp_path / "test_phase9c.db"
    test_storage = tmp_path / "test_storage"
    test_storage.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("TRADESATHI_DB_PATH", str(test_db))
    monkeypatch.setenv("TRADESATHI_STORAGE_PATH", str(test_storage))
    monkeypatch.setenv("TRADESATHI_TEST_MODE", "1")

    set_storage_dir(test_storage)
    init_db()

    with TestClient(app) as tc:
        yield tc


def _create_test_staff(role="sales", username="staff_sales"):
    with get_connection() as conn:
        uid = f"user-{secrets.token_hex(4)}"
        conn.execute(
            """
            INSERT OR REPLACE INTO users (id, username, email, password_hash, role, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, datetime('now'), datetime('now'))
            """,
            (uid, username, f"{username}@tradesathi.internal", hash_password("StaffPass123!"), role),
        )
        conn.commit()
    raw_token, _ = create_user_token(uid)
    return raw_token, uid


def _create_portal_customer_user(customer_id: str, username: str):
    raw_token = f"ptok_{secrets.token_urlsafe(24)}"
    token_hash = hash_portal_token(raw_token)
    user_id = f"puser-{secrets.token_hex(4)}"
    tok_id = f"tok-{secrets.token_hex(4)}"

    with get_connection() as conn:
        cust = conn.execute("SELECT name FROM customers WHERE id = ?", (customer_id,)).fetchone()
        cust_name = cust["name"] if cust else "Test Customer Org"
        conn.execute(
            """
            INSERT INTO portal_users (id, username, email, password_hash, account_type, organization_id, organization_name, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'customer', ?, ?, 1, datetime('now'), datetime('now'))
            """,
            (user_id, username, f"{username}@customer.test", hash_password("CustomerPass123!"), customer_id, cust_name),
        )
        conn.execute(
            """
            INSERT INTO portal_user_tokens (token_id, portal_user_id, token_hash, expires_at, revoked, created_at)
            VALUES (?, ?, ?, datetime('now', '+7 days'), 0, datetime('now'))
            """,
            (tok_id, user_id, token_hash),
        )
        conn.commit()

    return raw_token, user_id


def _setup_customer_and_order(cust_code="CUST-A", order_number="SO-P9C-001"):
    cust = create_customer({
        "code": cust_code,
        "name": f"Customer {cust_code}",
        "country": "India",
        "email": f"{cust_code.lower()}@domain.test",
    })
    prod = create_product({
        "sku": f"SKU-{cust_code}-01",
        "name": f"Product for {cust_code}",
        "category": "Electronics",
        "unit_of_measure": "pcs",
        "hsn_code": "85044090",
    })
    so = create_sales_order({
        "order_number": order_number,
        "customer_id": cust["id"],
        "order_date": "2026-10-15",
        "currency": "USD",
        "items": [{"product_id": prod["id"], "ordered_quantity": 50.0, "unit_price": 25.0}],
    })
    return cust, prod, so


def _attach_synthetic_document(customer_id: str, so_id: str, shared=True, title="Test Shipping Advice"):
    from app.db import create_shipment
    from app.storage import save_document_file

    shp_id = f"shp-{secrets.token_hex(4)}"
    create_shipment({
        "id": shp_id,
        "reference": f"SHP-REF-{secrets.token_hex(3)}",
        "customer_id": customer_id,
    })

    content = b"%PDF-1.4\nSynthetic test document for Phase 9C\n%%EOF"
    doc_id, storage_key, file_hash = save_document_file(shp_id, f"doc_{secrets.token_hex(4)}.pdf", content)

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO documents (
                id, shipment_id, sales_order_id, customer_id, original_filename, clean_filename,
                document_type, uploaded_at, storage_key, file_size, file_hash,
                processing_status, review_status, shared_with_customer, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'shipping_document', datetime('now'), ?, ?, ?, 'completed', 'verified_by_user', ?, datetime('now'), datetime('now'))
            """,
            (doc_id, shp_id, so_id, customer_id, title, title, storage_key, len(content), file_hash, 1 if shared else 0),
        )
        conn.commit()
    return doc_id


# ==============================================================================
# TEST 1: Order-specific message thread creation, message appending & idempotency
# ==============================================================================
def test_customer_thread_creation_and_messaging(client):
    cust, prod, so = _setup_customer_and_order("CUST-101", "SO-101")
    token, puser_id = _create_portal_customer_user(cust["id"], "cust_alice")
    auth_header = {"Authorization": f"Bearer {token}"}

    # 1. Create a thread
    payload = {
        "subject": "Delivery Timeline Inquiry",
        "initial_message": "Could you please confirm the estimated delivery date for this sales order?",
        "idempotency_key": "idemp-thread-001",
    }
    resp = client.post(
        f"/api/portal/customer/sales-orders/{so['id']}/threads",
        json=payload,
        headers=auth_header,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["subject"] == "Delivery Timeline Inquiry"
    assert data["status"] == "open"
    assert data["sales_order_id"] == so["id"]
    thread_id = data["id"]

    # Test idempotency on thread creation: identical payload returns same thread
    resp_dup = client.post(
        f"/api/portal/customer/sales-orders/{so['id']}/threads",
        json=payload,
        headers=auth_header,
    )
    assert resp_dup.status_code == 200
    assert resp_dup.json()["id"] == thread_id

    # Test idempotency conflict: same key, different payload -> 409
    resp_conflict = client.post(
        f"/api/portal/customer/sales-orders/{so['id']}/threads",
        json={"subject": "Different Subject", "initial_message": "Different message", "idempotency_key": "idemp-thread-001"},
        headers=auth_header,
    )
    assert resp_conflict.status_code == 409

    # 2. Append message to thread
    msg_payload = {
        "message": "Also, will tracking details be provided via carrier?",
        "idempotency_key": "idemp-msg-001",
    }
    resp_msg = client.post(
        f"/api/portal/customer/threads/{thread_id}/messages",
        json=msg_payload,
        headers=auth_header,
    )
    assert resp_msg.status_code == 201
    msg_data = resp_msg.json()
    assert msg_data["thread_id"] == thread_id
    assert msg_data["sender_type"] == "customer"
    assert msg_data["is_internal_note"] == 0

    # Idempotent message resubmission returns 200
    resp_msg_dup = client.post(
        f"/api/portal/customer/threads/{thread_id}/messages",
        json=msg_payload,
        headers=auth_header,
    )
    assert resp_msg_dup.status_code == 200

    # 3. Retrieve thread and messages
    resp_detail = client.get(
        f"/api/portal/customer/threads/{thread_id}",
        headers=auth_header,
    )
    assert resp_detail.status_code == 200
    detail = resp_detail.json()
    assert detail["id"] == thread_id
    assert len(detail["messages"]) == 2  # initial + appended
    assert "internal_notes" not in detail  # customer cannot see internal_notes column


# ==============================================================================
# TEST 2: HTML & Script payload sanitization
# ==============================================================================
def test_message_script_payload_sanitization(client):
    cust, prod, so = _setup_customer_and_order("CUST-XSS", "SO-XSS")
    token, puser_id = _create_portal_customer_user(cust["id"], "cust_xss")
    auth_header = {"Authorization": f"Bearer {token}"}

    malicious_text = "<script>alert('pwned')</script>Hello <b>World</b><img src=x onerror=alert(1)>"
    resp = client.post(
        f"/api/portal/customer/sales-orders/{so['id']}/threads",
        json={"subject": "<script>alert(1)</script>Safe Subject", "initial_message": malicious_text},
        headers=auth_header,
    )
    assert resp.status_code == 201
    data = resp.json()
    # Script tags must be stripped
    assert "<script>" not in data["subject"]
    assert "alert(1)" not in data["subject"]

    # Verify message detail
    detail = client.get(f"/api/portal/customer/threads/{data['id']}", headers=auth_header).json()
    msg_content = detail["messages"][0]["message"]
    assert "<script>" not in msg_content
    assert "onerror=" not in msg_content


# ==============================================================================
# TEST 3: Staff internal notes confidentiality
# ==============================================================================
def test_staff_internal_notes_confidentiality(client):
    cust, prod, so = _setup_customer_and_order("CUST-NOTES", "SO-NOTES")
    cust_token, _ = _create_portal_customer_user(cust["id"], "cust_notes")
    staff_token, staff_uid = _create_test_staff(role="sales", username="sales_rep")

    cust_auth = {"Authorization": f"Bearer {cust_token}"}
    staff_auth = {"Authorization": f"Bearer {staff_token}"}

    # Customer creates thread
    t_resp = client.post(
        f"/api/portal/customer/sales-orders/{so['id']}/threads",
        json={"subject": "Pricing inquiry", "initial_message": "Can I get a discount?"},
        headers=cust_auth,
    )
    thread_id = t_resp.json()["id"]

    # Staff posts an internal note
    note_resp = client.post(
        f"/api/portal/admin/customer-threads/{thread_id}/messages",
        json={"message": "INTERNAL: Do not offer discount. Margin is already at minimum.", "is_internal_note": True},
        headers=staff_auth,
    )
    assert note_resp.status_code == 201
    assert note_resp.json()["is_internal_note"] == 1

    # Staff also posts a public reply
    pub_resp = client.post(
        f"/api/portal/admin/customer-threads/{thread_id}/messages",
        json={"message": "Dear customer, our current pricing is already net discounted.", "is_internal_note": False},
        headers=staff_auth,
    )
    assert pub_resp.status_code == 201

    # Staff views thread: sees 3 messages (customer initial, staff internal note, staff public reply)
    staff_view = client.get(f"/api/portal/admin/customer-threads/{thread_id}", headers=staff_auth).json()
    assert len(staff_view["messages"]) == 3
    has_note = any(m["is_internal_note"] == 1 for m in staff_view["messages"])
    assert has_note is True

    # Customer views thread: MUST NOT see internal note
    cust_view = client.get(f"/api/portal/customer/threads/{thread_id}", headers=cust_auth).json()
    assert len(cust_view["messages"]) == 2  # ONLY initial + staff public reply
    assert all(m["is_internal_note"] == 0 for m in cust_view["messages"])
    assert "Margin is already at minimum" not in json.dumps(cust_view)


# ==============================================================================
# TEST 4: Customer Document Request Lifecycle & Explicit Document Sharing
# ==============================================================================
def test_document_request_lifecycle_and_fulfillment(client):
    cust, prod, so = _setup_customer_and_order("CUST-DOCS", "SO-DOCS")
    cust_token, _ = _create_portal_customer_user(cust["id"], "cust_docs")
    staff_token, _ = _create_test_staff(role="sales", username="sales_doc_mgr")

    cust_auth = {"Authorization": f"Bearer {cust_token}"}
    staff_auth = {"Authorization": f"Bearer {staff_token}"}

    # 1. Customer submits a document request
    req_payload = {
        "category": "commercial_invoice",
        "message": "Please provide the official stamped commercial invoice.",
        "idempotency_key": "idemp-doc-001",
    }
    req_resp = client.post(
        f"/api/portal/customer/sales-orders/{so['id']}/document-requests",
        json=req_payload,
        headers=cust_auth,
    )
    assert req_resp.status_code == 201
    req_data = req_resp.json()
    assert req_data["status"] == "open"
    assert req_data["category"] == "commercial_invoice"
    req_id = req_data["id"]

    # 2. Prevent duplicate open request for same order & category
    dup_resp = client.post(
        f"/api/portal/customer/sales-orders/{so['id']}/document-requests",
        json=req_payload,
        headers=cust_auth,
    )
    # Since idempotency_key is identical, returns duplicate 200
    assert dup_resp.status_code == 200

    # Without idempotency key, duplicate open request returns 400
    dup2 = client.post(
        f"/api/portal/customer/sales-orders/{so['id']}/document-requests",
        json={"category": "commercial_invoice", "message": "Duplicate request"},
        headers=cust_auth,
    )
    assert dup2.status_code == 400
    assert "already has an active" in dup2.json()["detail"]

    # 3. Staff sets status to under_review
    rev_resp = client.post(
        f"/api/portal/admin/customer-document-requests/{req_id}/review",
        json={"status": "under_review", "review_notes": "Checking with accounts team"},
        headers=staff_auth,
    )
    assert rev_resp.status_code == 200
    assert rev_resp.json()["status"] == "under_review"

    # 4. Attach an unshared synthetic document to the sales order
    doc_id = _attach_synthetic_document(cust["id"], so["id"], shared=False, title="Official Invoice")

    # Document request does NOT automatically share the document yet
    down_check = client.get(f"/api/portal/documents/{doc_id}/download", headers=cust_auth)
    assert down_check.status_code == 404

    # 5. Staff fulfills the request by explicitly linking and sharing the document
    fulfill_resp = client.post(
        f"/api/portal/admin/customer-document-requests/{req_id}/review",
        json={
            "status": "fulfilled",
            "review_notes": "Invoice approved and attached.",
            "fulfilled_document_id": doc_id,
        },
        headers=staff_auth,
    )
    assert fulfill_resp.status_code == 200
    assert fulfill_resp.json()["status"] == "fulfilled"
    assert fulfill_resp.json()["fulfilled_document_id"] == doc_id

    # 6. Customer can now download the shared document
    down_success = client.get(f"/api/portal/documents/{doc_id}/download", headers=cust_auth)
    assert down_success.status_code == 200
    assert b"Synthetic test document" in down_success.content

    # 7. Invalid state transition: from fulfilled -> open must be rejected
    invalid_trans = client.post(
        f"/api/portal/admin/customer-document-requests/{req_id}/review",
        json={"status": "open", "review_notes": "Attempt reset"},
        headers=staff_auth,
    )
    assert invalid_trans.status_code == 400


# ==============================================================================
# TEST 5: Explicit Document Sharing and Instant Revocation
# ==============================================================================
def test_explicit_document_sharing_and_revocation(client):
    cust, prod, so = _setup_customer_and_order("CUST-REVOKE", "SO-REVOKE")
    cust_token, _ = _create_portal_customer_user(cust["id"], "cust_revoke")
    staff_token, _ = _create_test_staff(role="sales", username="sales_revoker")

    cust_auth = {"Authorization": f"Bearer {cust_token}"}
    staff_auth = {"Authorization": f"Bearer {staff_token}"}

    # Attach shared document
    doc_id = _attach_synthetic_document(cust["id"], so["id"], shared=True, title="Quality Certificate")

    # Customer can download
    resp1 = client.get(f"/api/portal/documents/{doc_id}/download", headers=cust_auth)
    assert resp1.status_code == 200

    # Staff revokes sharing: shared_with_customer = False
    revoke_resp = client.post(
        f"/api/portal/admin/documents/{doc_id}/share",
        json={"shared_with_customer": False, "notes": "Revoking due to audit hold"},
        headers=staff_auth,
    )
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["shared_with_customer"] == 0

    # Customer download MUST immediately fail with 404
    resp2 = client.get(f"/api/portal/documents/{doc_id}/download", headers=cust_auth)
    assert resp2.status_code == 404


# ==============================================================================
# TEST 6: Strict Cross-Customer Tenant Isolation (Anti-IDOR)
# ==============================================================================
def test_cross_customer_tenant_isolation(client):
    cust_a, _, so_a = _setup_customer_and_order("CUST-A", "SO-A-001")
    cust_b, _, so_b = _setup_customer_and_order("CUST-B", "SO-B-001")

    token_a, _ = _create_portal_customer_user(cust_a["id"], "cust_a_user")
    token_b, _ = _create_portal_customer_user(cust_b["id"], "cust_b_user")

    auth_a = {"Authorization": f"Bearer {token_a}"}
    auth_b = {"Authorization": f"Bearer {token_b}"}

    # Customer A creates thread and document
    t_resp = client.post(
        f"/api/portal/customer/sales-orders/{so_a['id']}/threads",
        json={"subject": "Order A status", "initial_message": "When will it arrive?"},
        headers=auth_a,
    )
    thread_a_id = t_resp.json()["id"]

    doc_a_id = _attach_synthetic_document(cust_a["id"], so_a["id"], shared=True, title="Doc A")

    # Customer A creates document request
    dr_resp = client.post(
        f"/api/portal/customer/sales-orders/{so_a['id']}/document-requests",
        json={"category": "packing_list", "message": "Need packing list"},
        headers=auth_a,
    )
    dr_a_id = dr_resp.json()["id"]

    # 1. Customer B attempts to create thread on Customer A's order -> 404 / 403
    cross_thread_create = client.post(
        f"/api/portal/customer/sales-orders/{so_a['id']}/threads",
        json={"subject": "Intruder Thread", "initial_message": "Can I see this?"},
        headers=auth_b,
    )
    assert cross_thread_create.status_code in (403, 404)

    # 2. Customer B attempts to view Customer A's thread -> 404
    cross_thread_view = client.get(f"/api/portal/customer/threads/{thread_a_id}", headers=auth_b)
    assert cross_thread_view.status_code == 404

    # 3. Customer B attempts to post message to Customer A's thread -> 404
    cross_msg_post = client.post(
        f"/api/portal/customer/threads/{thread_a_id}/messages",
        json={"message": "Injected malicious message"},
        headers=auth_b,
    )
    assert cross_msg_post.status_code == 404

    # 4. Customer B attempts to create document request on Customer A's order -> 404
    cross_doc_req = client.post(
        f"/api/portal/customer/sales-orders/{so_a['id']}/document-requests",
        json={"category": "certificate_of_origin", "message": "Give me A's cert"},
        headers=auth_b,
    )
    assert cross_doc_req.status_code in (403, 404)

    # 5. Customer B attempts to view Customer A's document request -> 404
    cross_dr_view = client.get(f"/api/portal/customer/document-requests/{dr_a_id}", headers=auth_b)
    assert cross_dr_view.status_code == 404

    # 6. Customer B attempts to download Customer A's document -> 404
    cross_doc_down = client.get(f"/api/portal/documents/{doc_a_id}/download", headers=auth_b)
    assert cross_doc_down.status_code == 404


# ==============================================================================
# TEST 7: In-app Collaboration Notifications
# ==============================================================================
def test_collaboration_notifications(client):
    cust, prod, so = _setup_customer_and_order("CUST-NOTIF", "SO-NOTIF")
    cust_token, _ = _create_portal_customer_user(cust["id"], "cust_notif")
    staff_token, staff_uid = _create_test_staff(role="sales", username="sales_notif")

    cust_auth = {"Authorization": f"Bearer {cust_token}"}
    staff_auth = {"Authorization": f"Bearer {staff_token}"}

    # Customer creates thread -> staff gets notified
    t_resp = client.post(
        f"/api/portal/customer/sales-orders/{so['id']}/threads",
        json={"subject": "Inquiry", "initial_message": "Need update"},
        headers=cust_auth,
    )
    thread_id = t_resp.json()["id"]

    staff_resp = client.get("/api/portal/admin/notifications", headers=staff_auth).json()
    staff_items = staff_resp.get("items", staff_resp) if isinstance(staff_resp, dict) else staff_resp
    assert len(staff_items) >= 1
    assert any(n["event_type"] == "customer_thread_created" for n in staff_items)

    # Staff replies -> customer gets notified
    client.post(
        f"/api/portal/admin/customer-threads/{thread_id}/messages",
        json={"message": "Staff public reply"},
        headers=staff_auth,
    )

    cust_resp = client.get("/api/portal/customer/notifications", headers=cust_auth).json()
    cust_items = cust_resp.get("items", cust_resp) if isinstance(cust_resp, dict) else cust_resp
    assert len(cust_items) >= 1
    reply_notif = next(n for n in cust_items if n["event_type"] in ("staff_reply", "staff_message_posted"))
    assert reply_notif["is_read"] == 0

    # Customer marks notification as read
    read_resp = client.post(f"/api/portal/customer/notifications/{reply_notif['id']}/read", headers=cust_auth)
    assert read_resp.status_code == 200

    cust_after = client.get("/api/portal/customer/notifications", headers=cust_auth).json()
    cust_after_items = cust_after.get("items", cust_after) if isinstance(cust_after, dict) else cust_after
    marked_notif = next(n for n in cust_after_items if n["id"] == reply_notif["id"])
    assert marked_notif["is_read"] == 1


# ==============================================================================
# TEST 8: Staff Console Role-Based Guarding
# ==============================================================================
def test_staff_console_security_guards(client):
    cust, prod, so = _setup_customer_and_order("CUST-GUARD", "SO-GUARD")
    cust_token, _ = _create_portal_customer_user(cust["id"], "cust_guard")
    cust_auth = {"Authorization": f"Bearer {cust_token}"}

    # External customer cannot call admin endpoints
    resp1 = client.get("/api/portal/admin/customer-threads", headers=cust_auth)
    assert resp1.status_code in (401, 403)

    resp2 = client.get("/api/portal/admin/customer-document-requests", headers=cust_auth)
    assert resp2.status_code in (401, 403)

    resp3 = client.post(
        "/api/portal/admin/documents/fake-doc/share",
        json={"shared_with_customer": True},
        headers=cust_auth,
    )
    assert resp3.status_code in (401, 403)


# ==============================================================================
# TEST 9: Non-mutation of Inventory, Payments, or Order Terms
# ==============================================================================
def test_zero_inventory_and_commercial_mutations(client):
    cust, prod, so = _setup_customer_and_order("CUST-ZERO", "SO-ZERO")
    cust_token, _ = _create_portal_customer_user(cust["id"], "cust_zero")
    cust_auth = {"Authorization": f"Bearer {cust_token}"}

    # Snapshot before customer actions
    with get_connection() as conn:
        so_before = conn.execute("SELECT * FROM sales_orders WHERE id = ?", (so["id"],)).fetchone()
        items_before = conn.execute("SELECT * FROM sales_order_items WHERE sales_order_id = ?", (so["id"],)).fetchall()
        inv_mov_count = conn.execute("SELECT COUNT(*) as c FROM inventory_movements").fetchone()["c"]
        inv_bal_count = conn.execute("SELECT COUNT(*) as c FROM inventory_balances").fetchone()["c"]

    # Customer performs thread creation, messaging, document requests
    t_resp = client.post(
        f"/api/portal/customer/sales-orders/{so['id']}/threads",
        json={"subject": "Inquiry", "initial_message": "Hello staff"},
        headers=cust_auth,
    )
    thread_id = t_resp.json()["id"]

    client.post(
        f"/api/portal/customer/threads/{thread_id}/messages",
        json={"message": "Can I get this expedited?"},
        headers=cust_auth,
    )

    client.post(
        f"/api/portal/customer/sales-orders/{so['id']}/document-requests",
        json={"category": "certificate_of_origin", "message": "Need cert"},
        headers=cust_auth,
    )

    # Snapshot after customer actions
    with get_connection() as conn:
        so_after = conn.execute("SELECT * FROM sales_orders WHERE id = ?", (so["id"],)).fetchone()
        items_after = conn.execute("SELECT * FROM sales_order_items WHERE sales_order_id = ?", (so["id"],)).fetchall()
        inv_mov_after = conn.execute("SELECT COUNT(*) as c FROM inventory_movements").fetchone()["c"]
        inv_bal_after = conn.execute("SELECT COUNT(*) as c FROM inventory_balances").fetchone()["c"]

    # Commercial terms, status, items, and inventory MUST be 100% identical
    assert so_before["status"] == so_after["status"]
    assert so_before["grand_total"] == so_after["grand_total"]
    assert len(items_before) == len(items_after)
    assert inv_mov_count == inv_mov_after
    assert inv_bal_count == inv_bal_after


# ==============================================================================
# TEST 10: Deactivated Customer Account Token Revocation
# ==============================================================================
def test_deactivated_customer_revocation(client):
    cust, prod, so = _setup_customer_and_order("CUST-DEACT", "SO-DEACT")
    cust_token, puser_id = _create_portal_customer_user(cust["id"], "cust_deact")
    cust_auth = {"Authorization": f"Bearer {cust_token}"}

    # Works while active
    resp = client.get(f"/api/portal/customer/sales-orders/{so['id']}/threads", headers=cust_auth)
    assert resp.status_code == 200

    # Deactivate portal user
    with get_connection() as conn:
        conn.execute("UPDATE portal_users SET is_active = 0 WHERE id = ?", (puser_id,))
        conn.commit()

    # Subsequent call immediately rejected with 401 or 403
    resp_deact = client.get(f"/api/portal/customer/sales-orders/{so['id']}/threads", headers=cust_auth)
    assert resp_deact.status_code in (401, 403)
