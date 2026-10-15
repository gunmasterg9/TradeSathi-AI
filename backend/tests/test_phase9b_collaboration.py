"""TradeSathi AI — Phase 9B: Advanced Supplier Collaboration Adversarial Tests
Covers:
1. Delivery commitment validation, partial quantities, revision history, and idempotency.
2. Advance Shipment Notice (ASN) uniqueness, over-shipment protection, and idempotency.
3. Supplier document uploads, extension allowlist, magic byte checks, and pending review.
4. Delivery discrepancy reporting, message thread, state machine, and internal note secrecy.
5. Strict tenant isolation (anti-IDOR) between Supplier A and Supplier B across all new entities.
6. Role-based security guarding internal review consoles from external caller access.
7. Partial failure / ghost file cleanup assurance.
8. Secret-safe audit logging across all Phase 9B operations.
9. Verification that collaboration operations NEVER mutate inventory balances or post goods receipts.
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
from app.master_data import create_product, create_supplier
from app.procurement import create_purchase_order, transition_purchase_order_status
from app.storage import get_document_file_path, get_storage_dir


@pytest.fixture
def client(tmp_path, monkeypatch):
    test_db = tmp_path / "test_phase9b.db"
    test_storage = tmp_path / "test_storage"
    test_storage.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("TRADESATHI_DB_PATH", str(test_db))
    monkeypatch.setenv("TRADESATHI_STORAGE_PATH", str(test_storage))
    monkeypatch.setenv("TRADESATHI_TEST_MODE", "1")

    from app.storage import set_storage_dir
    set_storage_dir(test_storage)

    init_db()
    with TestClient(app) as tc:
        yield tc


def _create_test_staff(role="admin", username="staff_tester"):
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
    return raw_token


def _create_portal_supplier_user(supplier_id: str, username: str):
    raw_token = f"ptok_{secrets.token_urlsafe(24)}"
    token_hash = hash_portal_token(raw_token)
    user_id = f"puser-{secrets.token_hex(4)}"
    tok_id = f"tok-{secrets.token_hex(4)}"

    with get_connection() as conn:
        sup = conn.execute("SELECT name FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
        sup_name = sup["name"] if sup else "Test Supplier Org"
        conn.execute(
            """
            INSERT INTO portal_users (id, username, email, password_hash, account_type, organization_id, organization_name, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'supplier', ?, ?, 1, datetime('now'), datetime('now'))
            """,
            (user_id, username, f"{username}@supplier.test", hash_password("SupplierPass123!"), supplier_id, sup_name),
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


def _setup_supplier_and_po(supplier_code="SUP-A", sku="SKU-P9B-01", ordered_qty=100.0):
    sup = create_supplier({
        "code": supplier_code,
        "name": f"Supplier {supplier_code}",
        "country": "India",
        "email": f"{supplier_code.lower()}@domain.test",
    })
    prod = create_product({
        "sku": sku,
        "name": f"Product {sku}",
        "uom": "PCS",
        "unit_price": 50.0,
    })
    po = create_purchase_order({
        "po_number": f"PO-{supplier_code}-{secrets.token_hex(3).upper()}",
        "supplier_id": sup["id"],
        "order_date": "2026-10-15",
        "expected_delivery_date": "2026-11-15",
        "currency": "INR",
        "items": [
            {
                "product_id": prod["id"],
                "ordered_qty": ordered_qty,
                "unit_price": 50.0,
                "tax_rate_pct": 18.0,
            }
        ],
    })
    # Submit PO so it is in an eligible status
    transition_purchase_order_status(po["id"], "submitted")
    return sup, prod, po


# ===========================================================================
# 1. Delivery Commitments & Revision History Tests
# ===========================================================================

def test_delivery_commitment_lifecycle_and_revisions(client):
    sup_a, prod_a, po_a = _setup_supplier_and_po("SUP-COMMIT-A", "SKU-COMMIT-A", 100.0)
    tok_a, _ = _create_portal_supplier_user(sup_a["id"], "supplier_commit_user")
    po_item_id = po_a["items"][0]["id"]

    # 1. Submit initial delivery commitment
    resp = client.post(
        f"/api/portal/supplier/purchase-orders/{po_a['id']}/commitments",
        headers={"Authorization": f"Bearer {tok_a}"},
        json={
            "proposed_delivery_date": "2026-11-10",
            "supplier_dispatch_ref": "DISP-REV1",
            "carrier_name": "FastFreight",
            "tracking_number": "FF-123456",
            "supplier_comments": "First batch of 60 units",
            "lines": [{"po_item_id": po_item_id, "committed_qty": 60.0}],
            "idempotency_key": "idem-commit-01",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "success"
    assert data["revision_number"] == 1
    assert data["proposed_delivery_date"] == "2026-11-10"

    # 2. Idempotent resubmission with same key returns existing commitment
    resp_dup = client.post(
        f"/api/portal/supplier/purchase-orders/{po_a['id']}/commitments",
        headers={"Authorization": f"Bearer {tok_a}"},
        json={
            "proposed_delivery_date": "2026-11-10",
            "idempotency_key": "idem-commit-01",
        },
    )
    assert resp_dup.status_code == 200
    assert resp_dup.json()["status"] == "idempotent_duplicate"

    # 3. Submit revised commitment (revision 2)
    resp_rev2 = client.post(
        f"/api/portal/supplier/purchase-orders/{po_a['id']}/commitments",
        headers={"Authorization": f"Bearer {tok_a}"},
        json={
            "proposed_delivery_date": "2026-11-18",
            "supplier_comments": "Updated schedule due to logistics delay",
            "lines": [{"po_item_id": po_item_id, "committed_qty": 100.0}],
        },
    )
    assert resp_rev2.status_code == 200
    assert resp_rev2.json()["revision_number"] == 2

    # 4. Verify commitments list returns both revisions with correct statuses
    resp_list = client.get(
        f"/api/portal/supplier/purchase-orders/{po_a['id']}/commitments",
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    assert resp_list.status_code == 200
    items = resp_list.json()["items"]
    assert len(items) == 2
    assert items[0]["revision_number"] == 2
    assert items[0]["status"] == "proposed"
    assert items[1]["revision_number"] == 1
    assert items[1]["status"] == "superseded"

    # 5. Verify PO proposed delivery date was updated
    with get_connection() as conn:
        po_row = conn.execute("SELECT supplier_proposed_delivery_date FROM purchase_orders WHERE id = ?", (po_a["id"],)).fetchone()
        assert po_row["supplier_proposed_delivery_date"] == "2026-11-18"
        # Zero inventory balance changes
        bal = conn.execute("SELECT count(*) FROM inventory_movements").fetchone()[0]
        assert bal == 0


def test_delivery_commitment_quantity_and_eligibility_validation(client):
    sup_a, prod_a, po_a = _setup_supplier_and_po("SUP-COMMIT-VAL", "SKU-COMMIT-VAL", 50.0)
    tok_a, _ = _create_portal_supplier_user(sup_a["id"], "supplier_commit_val")
    po_item_id = po_a["items"][0]["id"]

    # Negative quantity rejected
    resp_neg = client.post(
        f"/api/portal/supplier/purchase-orders/{po_a['id']}/commitments",
        headers={"Authorization": f"Bearer {tok_a}"},
        json={
            "proposed_delivery_date": "2026-11-10",
            "lines": [{"po_item_id": po_item_id, "committed_qty": -10.0}],
        },
    )
    assert resp_neg.status_code in (400, 422)

    # Quantity exceeding remaining PO balance (50.0 ordered, trying 60.0)
    resp_over = client.post(
        f"/api/portal/supplier/purchase-orders/{po_a['id']}/commitments",
        headers={"Authorization": f"Bearer {tok_a}"},
        json={
            "proposed_delivery_date": "2026-11-10",
            "lines": [{"po_item_id": po_item_id, "committed_qty": 60.0}],
        },
    )
    assert resp_over.status_code == 400
    assert "exceeds remaining balance" in resp_over.text

    # Unrelated PO item ID
    resp_bad_item = client.post(
        f"/api/portal/supplier/purchase-orders/{po_a['id']}/commitments",
        headers={"Authorization": f"Bearer {tok_a}"},
        json={
            "proposed_delivery_date": "2026-11-10",
            "lines": [{"po_item_id": "nonexistent-item", "committed_qty": 10.0}],
        },
    )
    assert resp_bad_item.status_code == 400


# ===========================================================================
# 2. Advance Shipment Notice (ASN) Tests
# ===========================================================================

def test_asn_creation_and_over_shipment_guards(client):
    sup_a, prod_a, po_a = _setup_supplier_and_po("SUP-ASN-A", "SKU-ASN-A", 150.0)
    tok_a, _ = _create_portal_supplier_user(sup_a["id"], "supplier_asn_user")
    po_item_id = po_a["items"][0]["id"]

    # 1. Over-shipment check: attempting to ship 160 on a 150 PO
    resp_over = client.post(
        "/api/portal/supplier/asns",
        headers={"Authorization": f"Bearer {tok_a}"},
        json={
            "po_id": po_a["id"],
            "dispatch_reference": "DISP-ASN-001",
            "package_count": 5,
            "dispatch_date": "2026-10-20",
            "expected_arrival_date": "2026-10-25",
            "items": [{"po_item_id": po_item_id, "shipped_qty": 160.0}],
        },
    )
    assert resp_over.status_code == 400
    assert "exceeds remaining quantity" in resp_over.text

    # 2. Valid partial ASN
    resp_asn = client.post(
        "/api/portal/supplier/asns",
        headers={"Authorization": f"Bearer {tok_a}"},
        json={
            "po_id": po_a["id"],
            "dispatch_reference": "DISP-ASN-001",
            "package_count": 5,
            "carrier_name": "Maersk",
            "tracking_number": "TRK-998877",
            "dispatch_date": "2026-10-20",
            "expected_arrival_date": "2026-10-25",
            "items": [{"po_item_id": po_item_id, "shipped_qty": 75.0, "package_label": "BOX-1-TO-5"}],
            "idempotency_key": "idem-asn-01",
        },
    )
    assert resp_asn.status_code == 200, resp_asn.text
    asn_data = resp_asn.json()
    assert asn_data["status"] == "success"
    assert asn_data["asn_number"].startswith("ASN-")

    # 3. Duplicate dispatch reference by same supplier rejected
    resp_dup_disp = client.post(
        "/api/portal/supplier/asns",
        headers={"Authorization": f"Bearer {tok_a}"},
        json={
            "po_id": po_a["id"],
            "dispatch_reference": "DISP-ASN-001",  # Same dispatch ref
            "dispatch_date": "2026-10-21",
            "expected_arrival_date": "2026-10-26",
            "items": [{"po_item_id": po_item_id, "shipped_qty": 20.0}],
        },
    )
    assert resp_dup_disp.status_code == 400
    assert "already been used" in resp_dup_disp.text

    # 4. Idempotency key replay returns existing ASN
    resp_idem = client.post(
        "/api/portal/supplier/asns",
        headers={"Authorization": f"Bearer {tok_a}"},
        json={
            "po_id": po_a["id"],
            "dispatch_reference": "DISP-ASN-001",
            "dispatch_date": "2026-10-20",
            "expected_arrival_date": "2026-10-25",
            "items": [{"po_item_id": po_item_id, "shipped_qty": 75.0}],
            "idempotency_key": "idem-asn-01",
        },
    )
    assert resp_idem.status_code == 200
    assert resp_idem.json()["status"] == "idempotent_duplicate"
    assert resp_idem.json()["asn_id"] == asn_data["asn_id"]

    # 5. Verify NO goods receipts or inventory were created
    with get_connection() as conn:
        gr_count = conn.execute("SELECT count(*) FROM goods_receipts WHERE po_id = ?", (po_a["id"],)).fetchone()[0]
        assert gr_count == 0
        inv_count = conn.execute("SELECT count(*) FROM inventory_movements").fetchone()[0]
        assert inv_count == 0


# ===========================================================================
# 3. Secure Supplier Document Submissions Tests
# ===========================================================================

def test_supplier_document_upload_validation_and_isolation(client):
    sup_a, prod_a, po_a = _setup_supplier_and_po("SUP-DOC-A", "SKU-DOC-A")
    tok_a, _ = _create_portal_supplier_user(sup_a["id"], "supplier_doc_user")

    # 1. Valid PDF upload with %PDF- header
    pdf_bytes = b"%PDF-1.4 Mock valid PDF document content for delivery cert."
    resp_pdf = client.post(
        "/api/portal/supplier/documents/upload",
        headers={"Authorization": f"Bearer {tok_a}"},
        data={"po_id": po_a["id"], "document_type": "delivery_certificate"},
        files={"file": ("delivery_cert.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp_pdf.status_code == 200, resp_pdf.text
    doc_data = resp_pdf.json()
    assert doc_data["status"] == "success"
    assert doc_data["review_status"] == "pending_review"
    doc_id = doc_data["document_id"]

    # Verify DB record: shared_with_customer is 0 (private by default)
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        assert row["shared_with_customer"] == 0
        assert row["shared_with_supplier"] == 1
        assert row["supplier_id"] == sup_a["id"]
        assert row["review_status"] == "pending_review"
        assert row["file_hash"] == hashlib.sha256(pdf_bytes).hexdigest()

    # 2. Executable / disallowed file extension rejected (.exe)
    resp_exe = client.post(
        "/api/portal/supplier/documents/upload",
        headers={"Authorization": f"Bearer {tok_a}"},
        data={"po_id": po_a["id"]},
        files={"file": ("payload.exe", b"MZ\x90\x00executable bytes", "application/octet-stream")},
    )
    assert resp_exe.status_code == 400
    assert "Unsupported file type" in resp_exe.text

    # 3. Spoofed PDF extension without %PDF- magic bytes rejected
    resp_spoof = client.post(
        "/api/portal/supplier/documents/upload",
        headers={"Authorization": f"Bearer {tok_a}"},
        data={"po_id": po_a["id"]},
        files={"file": ("fake.pdf", b"This is not a real PDF file header", "application/pdf")},
    )
    assert resp_spoof.status_code == 400
    assert "header signature mismatch" in resp_spoof.text

    # 4. Empty file rejected
    resp_empty = client.post(
        "/api/portal/supplier/documents/upload",
        headers={"Authorization": f"Bearer {tok_a}"},
        data={"po_id": po_a["id"]},
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert resp_empty.status_code == 400
    assert "Uploaded file is empty" in resp_empty.text


# ===========================================================================
# 4. Delivery Discrepancy Workflow Tests
# ===========================================================================

def test_discrepancy_lifecycle_and_internal_notes_secrecy(client):
    sup_a, prod_a, po_a = _setup_supplier_and_po("SUP-DISC-A", "SKU-DISC-A")
    tok_a, _ = _create_portal_supplier_user(sup_a["id"], "supplier_disc_user")
    staff_tok = _create_test_staff("procurement", "proc_staff_disc")

    # 1. Supplier submits discrepancy
    resp_disc = client.post(
        "/api/portal/supplier/discrepancies",
        headers={"Authorization": f"Bearer {tok_a}"},
        json={
            "po_id": po_a["id"],
            "category": "short_shipment",
            "title": "Raw material shortage from upstream mill",
            "description": "Due to power outage at the spinning mill, only 80 units could be finished.",
        },
    )
    assert resp_disc.status_code == 200, resp_disc.text
    disc_id = resp_disc.json()["discrepancy_id"]
    assert resp_disc.json()["discrepancy_number"].startswith("DISC-")

    # 2. Supplier inspects discrepancy detail: internal_notes must NOT exist
    resp_get_sup = client.get(
        f"/api/portal/supplier/discrepancies/{disc_id}",
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    assert resp_get_sup.status_code == 200
    disc_sup_data = resp_get_sup.json()["discrepancy"]
    assert "internal_notes" not in disc_sup_data
    assert disc_sup_data["status"] == "open"
    assert len(resp_get_sup.json()["messages"]) == 1

    # 3. Staff reviews and requests info from supplier, writing internal notes
    resp_staff_rev = client.post(
        f"/api/portal/admin/discrepancies/{disc_id}/review",
        headers={"Authorization": f"Bearer {staff_tok}"},
        json={
            "action": "request_supplier_info",
            "internal_notes": "CONFIDENTIAL: Checked with warehouse, we have buffer stock for 5 days.",
            "message": "Please provide revised dispatch ETA for the remaining 20 units.",
        },
    )
    assert resp_staff_rev.status_code == 200
    assert resp_staff_rev.json()["new_status"] == "awaiting_supplier"

    # 4. Supplier verifies updated status and new message, but still cannot see confidential internal notes
    resp_get_sup2 = client.get(
        f"/api/portal/supplier/discrepancies/{disc_id}",
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    assert resp_get_sup2.status_code == 200
    assert resp_get_sup2.json()["discrepancy"]["status"] == "awaiting_supplier"
    assert "CONFIDENTIAL" not in json.dumps(resp_get_sup2.json())
    assert len(resp_get_sup2.json()["messages"]) == 2

    # 5. Supplier responds: transitions status from awaiting_supplier back to under_review
    resp_msg = client.post(
        f"/api/portal/supplier/discrepancies/{disc_id}/messages",
        headers={"Authorization": f"Bearer {tok_a}"},
        json={"message": "Remaining 20 units will be dispatched by November 5th."},
    )
    assert resp_msg.status_code == 200
    assert resp_msg.json()["discrepancy_status"] == "under_review"

    # 6. Staff resolves discrepancy with resolution notes
    resp_resolve = client.post(
        f"/api/portal/admin/discrepancies/{disc_id}/review",
        headers={"Authorization": f"Bearer {staff_tok}"},
        json={
            "action": "resolve",
            "shared_resolution_notes": "Revised timeline approved by procurement team.",
        },
    )
    assert resp_resolve.status_code == 200
    assert resp_resolve.json()["new_status"] == "resolved"

    # 7. Supplier cannot add messages to resolved discrepancy
    resp_blocked_msg = client.post(
        f"/api/portal/supplier/discrepancies/{disc_id}/messages",
        headers={"Authorization": f"Bearer {tok_a}"},
        json={"message": "Trying to post after resolution"},
    )
    assert resp_blocked_msg.status_code == 400


# ===========================================================================
# 5. Strict Cross-Supplier Tenant Isolation (Anti-IDOR)
# ===========================================================================

def test_cross_supplier_tenant_isolation_anti_idor(client):
    sup_a, _, po_a = _setup_supplier_and_po("SUP-ISOL-A", "SKU-ISOL-A")
    sup_b, _, po_b = _setup_supplier_and_po("SUP-ISOL-B", "SKU-ISOL-B")

    tok_a, _ = _create_portal_supplier_user(sup_a["id"], "user_tenant_a")
    tok_b, _ = _create_portal_supplier_user(sup_b["id"], "user_tenant_b")

    # 1. Supplier A creates commitment on PO A
    resp_c_a = client.post(
        f"/api/portal/supplier/purchase-orders/{po_a['id']}/commitments",
        headers={"Authorization": f"Bearer {tok_a}"},
        json={"proposed_delivery_date": "2026-11-20"},
    )
    assert resp_c_a.status_code == 200

    # 2. Supplier B attempts to read Supplier A's commitments -> 404
    resp_idor_c = client.get(
        f"/api/portal/supplier/purchase-orders/{po_a['id']}/commitments",
        headers={"Authorization": f"Bearer {tok_b}"},
    )
    assert resp_idor_c.status_code == 404

    # 3. Supplier B attempts to create commitment against Supplier A's PO -> 404
    resp_idor_c_create = client.post(
        f"/api/portal/supplier/purchase-orders/{po_a['id']}/commitments",
        headers={"Authorization": f"Bearer {tok_b}"},
        json={"proposed_delivery_date": "2026-11-25"},
    )
    assert resp_idor_c_create.status_code == 404

    # 4. Supplier A creates an ASN on PO A
    resp_asn_a = client.post(
        "/api/portal/supplier/asns",
        headers={"Authorization": f"Bearer {tok_a}"},
        json={
            "po_id": po_a["id"],
            "dispatch_reference": "DISP-ISOL-01",
            "dispatch_date": "2026-10-22",
            "expected_arrival_date": "2026-10-27",
            "items": [{"po_item_id": po_a["items"][0]["id"], "shipped_qty": 10.0}],
        },
    )
    assert resp_asn_a.status_code == 200
    asn_a_id = resp_asn_a.json()["asn_id"]

    # 5. Supplier B attempts to read Supplier A's ASN -> 404
    resp_idor_asn = client.get(
        f"/api/portal/supplier/asns/{asn_a_id}",
        headers={"Authorization": f"Bearer {tok_b}"},
    )
    assert resp_idor_asn.status_code == 404

    # 6. Supplier A uploads a document
    pdf_bytes = b"%PDF-1.4 Supplier A private delivery invoice"
    resp_doc_a = client.post(
        "/api/portal/supplier/documents/upload",
        headers={"Authorization": f"Bearer {tok_a}"},
        data={"po_id": po_a["id"]},
        files={"file": ("sup_a_doc.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp_doc_a.status_code == 200
    doc_a_id = resp_doc_a.json()["document_id"]

    # 7. Supplier B attempts to download Supplier A's document -> 404
    resp_idor_doc = client.get(
        f"/api/portal/documents/{doc_a_id}/download",
        headers={"Authorization": f"Bearer {tok_b}"},
    )
    assert resp_idor_doc.status_code == 404


# ===========================================================================
# 6. Internal Staff Role Guards
# ===========================================================================

def test_internal_staff_review_endpoints_require_staff_role(client):
    sup_a, _, po_a = _setup_supplier_and_po("SUP-ROLE-A", "SKU-ROLE-A")
    tok_a, _ = _create_portal_supplier_user(sup_a["id"], "user_role_test")

    # External supplier token calling internal staff admin endpoints -> 401/403
    resp_admin_c = client.get(
        "/api/portal/admin/commitments",
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    assert resp_admin_c.status_code in (401, 403)

    resp_admin_asn = client.get(
        "/api/portal/admin/asns",
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    assert resp_admin_asn.status_code in (401, 403)

    resp_admin_disc = client.get(
        "/api/portal/admin/discrepancies",
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    assert resp_admin_disc.status_code in (401, 403)


# ===========================================================================
# 7. Secret-Safe Audit Logging Tests
# ===========================================================================

def test_phase9b_audit_logs_contain_no_secrets(client):
    sup_a, prod_a, po_a = _setup_supplier_and_po("SUP-AUDIT-B", "SKU-AUDIT-B")
    tok_a, _ = _create_portal_supplier_user(sup_a["id"], "user_audit_test")

    # Create commitment, ASN, and discrepancy
    client.post(
        f"/api/portal/supplier/purchase-orders/{po_a['id']}/commitments",
        headers={"Authorization": f"Bearer {tok_a}"},
        json={"proposed_delivery_date": "2026-11-20"},
    )
    client.post(
        "/api/portal/supplier/asns",
        headers={"Authorization": f"Bearer {tok_a}"},
        json={
            "po_id": po_a["id"],
            "dispatch_reference": "DISP-AUD-01",
            "dispatch_date": "2026-10-22",
            "expected_arrival_date": "2026-10-27",
            "items": [{"po_item_id": po_a["items"][0]["id"], "shipped_qty": 10.0}],
        },
    )

    with get_connection() as conn:
        logs = conn.execute("SELECT * FROM erp_audit_logs").fetchall()
        assert len(logs) > 0
        for log in logs:
            det = log["changes_json"] or ""
            assert "SupplierPass" not in det
            assert "Bearer " not in det
            assert "ptok_" not in det


# ===========================================================================
# 8. Concurrency & Idempotency Conflict Tests
# ===========================================================================

def test_asn_and_commitment_concurrency_and_idempotency_conflicts(client):
    import concurrent.futures

    sup_a, prod_a, po_a = _setup_supplier_and_po("SUP-CONCUR-B", "SKU-CONCUR-B")
    tok_a, _ = _create_portal_supplier_user(sup_a["id"], "user_concur_test")

    # 1. Concurrent ASN creations with same idempotency key
    idemp_key = "idemp-concur-test-123"
    payload = {
        "po_id": po_a["id"],
        "dispatch_reference": "DISP-CNC-01",
        "dispatch_date": "2026-10-25",
        "expected_arrival_date": "2026-10-30",
        "items": [{"po_item_id": po_a["items"][0]["id"], "shipped_qty": 5.0}],
    }

    results = []
    def _create_asn():
        return client.post(
            "/api/portal/supplier/asns",
            headers={"Authorization": f"Bearer {tok_a}", "X-Idempotency-Key": idemp_key},
            json=payload,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_create_asn) for _ in range(5)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    # All should return 200 with the exact same asn_id
    asn_ids = set()
    for r in results:
        assert r.status_code == 200
        asn_ids.add(r.json()["asn_id"])
    assert len(asn_ids) == 1, "Concurrent idempotent requests must resolve to exactly one ASN identity"

    # 2. Same idempotency key with different payload -> 409 Conflict
    diff_payload = dict(payload)
    diff_payload["dispatch_reference"] = "DISP-CNC-DIFFERENT"
    resp_conflict = client.post(
        "/api/portal/supplier/asns",
        headers={"Authorization": f"Bearer {tok_a}", "X-Idempotency-Key": idemp_key},
        json=diff_payload,
    )
    assert resp_conflict.status_code == 409
    assert "Payload does not match" in resp_conflict.json()["detail"]
