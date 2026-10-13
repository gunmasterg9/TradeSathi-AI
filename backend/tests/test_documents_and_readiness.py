import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.app.db import get_db_path, init_db, set_db_path
from backend.app.main import app
from backend.app.storage import get_storage_dir, set_storage_dir


@pytest.fixture(autouse=True)
def isolated_env(tmp_path):
    """Isolate both SQLite database and storage directory for each test."""
    orig_db = get_db_path()
    orig_storage = get_storage_dir()

    test_db = tmp_path / "test_tradesathi_2c.db"
    test_storage = tmp_path / "storage" / "documents"

    set_db_path(test_db)
    init_db(test_db)
    set_storage_dir(test_storage)

    yield test_db, test_storage

    set_db_path(orig_db)
    set_storage_dir(orig_storage)


@pytest.fixture
def client():
    return TestClient(app)


def test_document_upload_association_with_correct_shipment(client):
    # 1. Create shipment
    resp = client.post("/api/shipments", json={"reference": "SHP-DOC-001"})
    assert resp.status_code == 201
    shp_id = resp.json()["id"]

    # 2. Upload document to shipment
    inv_content = "COMMERCIAL INVOICE #INV-900\nExporter: Alpha Marine\nBuyer: Global Foods\nTotal: USD 5000\nNet Weight: 2000 kg"
    files = [("files", ("invoice_sample.txt", inv_content.encode("utf-8"), "text/plain"))]
    upload_resp = client.post(
        f"/api/shipments/{shp_id}/documents",
        files=files,
        data={"document_type": "commercial_invoice", "notes": "Initial draft invoice"},
    )
    assert upload_resp.status_code == 201
    docs = upload_resp.json()["documents"]
    assert len(docs) == 1
    doc = docs[0]
    assert doc["shipment_id"] == shp_id
    assert doc["original_filename"] == "invoice_sample.txt"
    assert doc["document_type"] == "commercial_invoice"
    assert doc["review_status"] == "uploaded"
    assert doc["notes"] == "Initial draft invoice"
    assert "id" in doc
    doc_id = doc["id"]

    # 3. Retrieve documents list for this shipment
    list_resp = client.get(f"/api/shipments/{shp_id}/documents")
    assert list_resp.status_code == 200
    listed = list_resp.json()
    assert listed["total"] == 1
    assert listed["documents"][0]["id"] == doc_id

    # 4. Check shipment document_count
    shp_get = client.get(f"/api/shipments/{shp_id}").json()
    assert shp_get["document_count"] == 1


def test_invalid_extension_and_oversized_file_rejection(client):
    shp_resp = client.post("/api/shipments", json={"reference": "SHP-DOC-REJECT-01"})
    shp_id = shp_resp.json()["id"]

    # Unsupported extension (e.g. .exe)
    bad_files = [("files", ("malicious.exe", b"binarycontent", "application/octet-stream"))]
    resp_bad_ext = client.post(f"/api/shipments/{shp_id}/documents", files=bad_files)
    assert resp_bad_ext.status_code == 400
    assert "unsupported file type" in resp_bad_ext.json()["detail"].lower()

    # Empty file
    empty_files = [("files", ("empty.txt", b"", "text/plain"))]
    resp_empty = client.post(f"/api/shipments/{shp_id}/documents", files=empty_files)
    assert resp_empty.status_code == 400
    assert "empty" in resp_empty.json()["detail"].lower()

    # Oversized file (> 10MB)
    huge_bytes = b"X" * (11 * 1024 * 1024)
    huge_files = [("files", ("huge.txt", huge_bytes, "text/plain"))]
    resp_huge = client.post(f"/api/shipments/{shp_id}/documents", files=huge_files)
    assert resp_huge.status_code == 413
    assert "exceeds" in resp_huge.json()["detail"].lower()


def test_duplicate_upload_rejection_and_replacement_decision(client):
    shp_resp = client.post("/api/shipments", json={"reference": "SHP-DUP-01"})
    shp_id = shp_resp.json()["id"]

    content = b"COMMERCIAL INVOICE #101\nTotal: 1000 USD\nNet Weight: 500 kg"
    files1 = [("files", ("invoice.txt", content, "text/plain"))]
    up1 = client.post(f"/api/shipments/{shp_id}/documents", files=files1)
    assert up1.status_code == 201
    doc_id1 = up1.json()["documents"][0]["id"]

    # 1. Duplicate upload with same content -> must be rejected with 409
    files_dup = [("files", ("invoice_copy.txt", content, "text/plain"))]
    dup_resp = client.post(f"/api/shipments/{shp_id}/documents", files=files_dup)
    assert dup_resp.status_code == 409
    assert "duplicate document detected" in dup_resp.json()["detail"].lower()

    # 2. Duplicate upload with same filename -> must be rejected with 409
    diff_content = b"COMMERCIAL INVOICE #101 REVISED\nTotal: 1200 USD\nNet Weight: 600 kg"
    files_same_name = [("files", ("invoice.txt", diff_content, "text/plain"))]
    dup_name_resp = client.post(f"/api/shipments/{shp_id}/documents", files=files_same_name)
    assert dup_name_resp.status_code == 409
    assert "already exists for shipment" in dup_name_resp.json()["detail"].lower()

    # 3. Explicit replacement decision (duplicate_action="replace")
    replace_resp = client.post(
        f"/api/shipments/{shp_id}/documents",
        files=[("files", ("invoice.txt", diff_content, "text/plain"))],
        data={"duplicate_action": "replace"},
    )
    assert replace_resp.status_code == 201
    new_doc_id = replace_resp.json()["documents"][0]["id"]
    assert new_doc_id != doc_id1

    # Verify total documents remains 1
    docs_resp = client.get(f"/api/shipments/{shp_id}/documents").json()
    assert docs_resp["total"] == 1


def test_safe_filenames_and_directory_traversal_prevention(client):
    shp_resp = client.post("/api/shipments", json={"reference": "SHP-TRAVERSAL-01"})
    shp_id = shp_resp.json()["id"]

    # File with traversal payload in name
    traversal_name = "../../etc/passwd.txt"
    files = [("files", (traversal_name, b"COMMERCIAL INVOICE payload", "text/plain"))]
    up_resp = client.post(f"/api/shipments/{shp_id}/documents", files=files)
    assert up_resp.status_code == 201
    doc = up_resp.json()["documents"][0]

    # Stored storage_key and clean_filename should NOT contain ../ or path traversal
    assert ".." not in doc["clean_filename"]
    assert ".." not in doc["storage_key"]
    assert not doc["storage_key"].startswith("/")
    assert not doc["storage_key"].startswith("\\")

    # Download via API works cleanly
    dl_resp = client.get(f"/api/shipments/{shp_id}/documents/{doc['id']}/download")
    assert dl_resp.status_code == 200
    assert dl_resp.content == b"COMMERCIAL INVOICE payload"


def test_document_status_persistence_and_user_review_workflow(client):
    shp_resp = client.post("/api/shipments", json={"reference": "SHP-WORKFLOW-01"})
    shp_id = shp_resp.json()["id"]

    files = [("files", ("packing_list.txt", b"PACKING LIST\nTotal Net Weight: 5000 kg", "text/plain"))]
    up_resp = client.post(f"/api/shipments/{shp_id}/documents", files=files)
    doc_id = up_resp.json()["documents"][0]["id"]
    assert up_resp.json()["documents"][0]["review_status"] == "uploaded"

    # Step 1: Change to needs_review with note
    patch1 = client.patch(
        f"/api/shipments/{shp_id}/documents/{doc_id}",
        json={
            "review_status": "needs_review",
            "last_reviewed_by": "Compliance Lead",
            "review_notes": "Carton packaging count differs from standard pallet size",
        },
    )
    assert patch1.status_code == 200
    p1_data = patch1.json()
    assert p1_data["review_status"] == "needs_review"
    assert p1_data["last_reviewed_by"] == "Compliance Lead"
    assert p1_data["review_notes"] == "Carton packaging count differs from standard pallet size"
    assert p1_data["last_reviewed_at"] is not None

    # Step 2: Change to verified_by_user
    patch2 = client.patch(
        f"/api/shipments/{shp_id}/documents/{doc_id}",
        json={
            "review_status": "verified_by_user",
            "last_reviewed_by": "Senior Auditor",
            "review_notes": "Pallet count clarified and verified with warehouse",
        },
    )
    assert patch2.status_code == 200
    p2_data = patch2.json()
    assert p2_data["review_status"] == "verified_by_user"
    assert p2_data["last_reviewed_by"] == "Senior Auditor"


def test_readiness_calculation_missing_vs_uploaded_vs_verified(client):
    # Create shipment with planned date
    shp_resp = client.post(
        "/api/shipments",
        json={"reference": "SHP-READY-01", "planned_shipment_date": "2026-11-20"},
    )
    shp_id = shp_resp.json()["id"]

    # 1. Initial State: No documents -> NOT READY (missing Commercial Invoice & Packing List)
    r1 = client.get(f"/api/shipments/{shp_id}/readiness").json()
    assert r1["is_ready"] is False
    assert r1["status"] == "not_ready"
    assert r1["uploaded_document_count"] == 0
    assert "Commercial Invoice" in r1["missing_documents"]
    assert "Packing List" in r1["missing_documents"]
    assert r1["planned_shipment_date"] == "2026-11-20"

    # 2. Upload documents, but they are in 'uploaded' status (unverified) and no audit run yet
    inv_content = "COMMERCIAL INVOICE #INV-88\nExporter: Apex Export\nBuyer: Apex Import\nTotal Amount: USD 10000\nNet Weight: 3000 kg"
    pl_content = "PACKING LIST for #INV-88\nExporter: Apex Export\nBuyer: Apex Import\nNet Weight: 3000 kg"
    client.post(
        f"/api/shipments/{shp_id}/documents",
        files=[("files", ("invoice.txt", inv_content.encode("utf-8"), "text/plain"))],
        data={"document_type": "commercial_invoice"},
    )
    client.post(
        f"/api/shipments/{shp_id}/documents",
        files=[("files", ("packing_list.txt", pl_content.encode("utf-8"), "text/plain"))],
        data={"document_type": "packing_list"},
    )

    r2 = client.get(f"/api/shipments/{shp_id}/readiness").json()
    assert r2["is_ready"] is False
    assert r2["status"] == "not_ready"
    assert r2["uploaded_document_count"] == 2
    assert len(r2["missing_documents"]) == 0
    assert r2["outstanding_human_reviews"] == 2  # Both are 'uploaded' awaiting verification

    # 3. Reconcile documents
    reconcile_resp = client.post(f"/api/shipments/{shp_id}/reconcile")
    assert reconcile_resp.status_code == 200

    # Still not ready because human reviews are outstanding
    r3 = client.get(f"/api/shipments/{shp_id}/readiness").json()
    assert r3["is_ready"] is False
    assert r3["last_reconciliation_timestamp"] is not None

    # 4. Verify both documents by user
    docs = client.get(f"/api/shipments/{shp_id}/documents").json()["documents"]
    for d in docs:
        client.patch(
            f"/api/shipments/{shp_id}/documents/{d['id']}",
            json={"review_status": "verified_by_user", "last_reviewed_by": "Ops Manager"},
        )

    # 5. Now check readiness: 0 missing, 0 outstanding reviews, 0 critical discrepancies -> READY!
    r4 = client.get(f"/api/shipments/{shp_id}/readiness").json()
    assert r4["is_ready"] is True
    assert r4["status"] == "ready"
    assert r4["unresolved_critical_discrepancies"] == 0
    assert r4["outstanding_human_reviews"] == 0
    assert "disclaimer" in r4


def test_critical_discrepancies_block_readiness(client):
    shp_resp = client.post("/api/shipments", json={"reference": "SHP-DISCREP-BLOCK-01"})
    shp_id = shp_resp.json()["id"]

    # Inconsistent documents: Exporter mismatch or critical currency mismatch
    inv_content = "COMMERCIAL INVOICE #INV-99\nExporter: Company A\nBuyer: Company B\nCurrency: USD\nTotal: 1000\nNet Weight: 500 kg"
    pl_content = "PACKING LIST for #INV-99\nExporter: Company Z\nBuyer: Company B\nCurrency: EUR\nNet Weight: 5000 kg"

    client.post(
        f"/api/shipments/{shp_id}/documents",
        files=[("files", ("invoice.txt", inv_content.encode("utf-8"), "text/plain"))],
        data={"document_type": "commercial_invoice"},
    )
    client.post(
        f"/api/shipments/{shp_id}/documents",
        files=[("files", ("packing_list.txt", pl_content.encode("utf-8"), "text/plain"))],
        data={"document_type": "packing_list"},
    )

    # Verify both documents
    docs = client.get(f"/api/shipments/{shp_id}/documents").json()["documents"]
    for d in docs:
        client.patch(
            f"/api/shipments/{shp_id}/documents/{d['id']}",
            json={"review_status": "verified_by_user"},
        )

    # Run reconciliation audit
    client.post(f"/api/shipments/{shp_id}/reconcile")

    # Readiness should be blocked by critical discrepancies!
    r = client.get(f"/api/shipments/{shp_id}/readiness").json()
    assert r["is_ready"] is False
    assert r["status"] == "not_ready"
    assert r["unresolved_critical_discrepancies"] > 0
    assert any("critical discrepancy" in reason.lower() for reason in r["reasons"])
