import io
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.app.db import (
    get_db_path,
    init_db,
    set_db_path,
)
from backend.app.main import app, find_sample_directory
from backend.app.storage import set_storage_dir


@pytest.fixture(autouse=True)
def isolated_env(tmp_path):
    """Isolate both SQLite database and storage directory for test safety."""
    original_db = get_db_path()
    test_db = tmp_path / "test_audit.db"
    set_db_path(test_db)
    init_db(test_db)

    test_storage = tmp_path / "test_docs_storage"
    test_storage.mkdir(parents=True, exist_ok=True)
    set_storage_dir(test_storage)

    yield tmp_path

    set_db_path(original_db)


@pytest.fixture
def client():
    return TestClient(app)


def test_sample_documents_resolution_and_content(client):
    """Verify /api/samples returns commercial_invoice.txt and packing_list.txt."""
    resp = client.get("/api/samples")
    assert resp.status_code == 200, f"Expected 200 OK, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "samples" in data
    samples = data["samples"]
    assert len(samples) == 2, f"Expected 2 sample files, got {len(samples)}"

    filenames = [s["filename"] for s in samples]
    assert "commercial_invoice.txt" in filenames
    assert "packing_list.txt" in filenames

    invoice = next(s for s in samples if s["filename"] == "commercial_invoice.txt")
    packing = next(s for s in samples if s["filename"] == "packing_list.txt")

    assert "18000" in invoice["content"] or "18,000" in invoice["content"]
    assert "18100" in packing["content"] or "18,100" in packing["content"]


def test_sample_endpoint_missing_directory_raises_404(client, monkeypatch):
    """When sample directory is missing or empty, verify clear 404 response."""
    monkeypatch.setattr("backend.app.main.find_sample_directory", lambda: None)
    resp = client.get("/api/samples")
    assert resp.status_code == 404
    assert "Sample documents folder" in resp.json()["detail"]


def test_synthetic_sample_reconciliation_workflow(client):
    """Verify the full sample-document reconciliation workflow detects the 100 kg weight discrepancy."""
    samples_resp = client.get("/api/samples")
    assert samples_resp.status_code == 200
    samples = samples_resp.json()["samples"]

    # Post both sample files to /api/analyze
    files = [
        ("files", (s["filename"], io.BytesIO(s["content"].encode("utf-8")), "text/plain"))
        for s in samples
    ]
    analyze_resp = client.post("/api/analyze", files=files)
    assert analyze_resp.status_code == 200
    res = analyze_resp.json()

    assert len(res["discrepancies"]) >= 1

    # Specifically check for the 100 kg net weight discrepancy
    disc_fields = [d["field"] for d in res["discrepancies"]]
    assert "total_net_weight_kg" in disc_fields

    weight_disc = next(d for d in res["discrepancies"] if d["field"] == "total_net_weight_kg")
    assert "100" in weight_disc["difference"]
    assert weight_disc["severity"] in ("warning", "critical")

    # Verify checklist exists and is populated
    checklist = res["summary"]["checklist"]
    assert len(checklist) >= 4
    chk_ids = [c["id"] for c in checklist]
    assert "chk-weights" in chk_ids


def test_shipment_deletion_preserves_audit_history(client):
    """Verify deleting a shipment removes the shipment record but unlinks rather than destroys linked audit analyses."""
    # 1. Create a shipment
    shp_resp = client.post(
        "/api/shipments",
        json={"reference": "SHP-AUDIT-DEL-01", "exporter": "Test Exporter", "status": "draft"},
    )
    assert shp_resp.status_code == 201
    shp_id = shp_resp.json()["id"]

    # 2. Upload sample documents to /api/analyze with shipment_id
    samples_resp = client.get("/api/samples")
    samples = samples_resp.json()["samples"]
    files = [
        ("files", (s["filename"], io.BytesIO(s["content"].encode("utf-8")), "text/plain"))
        for s in samples
    ]
    analyze_resp = client.post(
        "/api/analyze",
        data={"shipment_id": shp_id},
        files=files,
    )
    assert analyze_resp.status_code == 200
    analysis_id = analyze_resp.json()["id"]

    # 3. Upload a document to shipment document register
    upload_resp = client.post(
        f"/api/shipments/{shp_id}/documents",
        files=[("files", ("invoice.txt", io.BytesIO(b"dummy invoice content"), "text/plain"))],
    )
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["documents"][0]["id"]

    # 4. Delete the shipment
    del_resp = client.delete(f"/api/shipments/{shp_id}")
    assert del_resp.status_code == 200

    # 5. Verify shipment is gone
    assert client.get(f"/api/shipments/{shp_id}").status_code == 404

    # 6. Verify audit history is preserved: analysis is still retrievable!
    anl_resp = client.get(f"/api/analyses/{analysis_id}")
    assert anl_resp.status_code == 200
    saved_analysis = anl_resp.json()
    assert saved_analysis["id"] == analysis_id
    # shipment_id is unlinked to avoid stale references
    assert saved_analysis.get("shipment_id") is None

    # 7. Verify document was cleaned up
    assert client.get(f"/api/documents/{doc_id}/download").status_code == 404


def test_cors_preflight_and_origin_regex(client):
    """Verify local development origins (e.g. port 5174, 3000, 8001) are accepted."""
    test_origins = [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:3000",
        "http://127.0.0.1:8001",
    ]
    for origin in test_origins:
        resp = client.options(
            "/api/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200, f"Failed for origin {origin}"
        assert resp.headers.get("access-control-allow-origin") == origin


def test_analyze_validation_errors_return_clean_json_details(client):
    """Verify endpoint validation errors return JSON with detail attribute, never blank or malformed."""
    # 1. No files submitted
    resp = client.post("/api/analyze")
    assert resp.status_code == 422 or resp.status_code == 400
    data = resp.json()
    assert "detail" in data

    # 2. More than 8 files
    excess_files = [
        ("files", (f"doc_{i}.txt", io.BytesIO(b"sample text"), "text/plain"))
        for i in range(9)
    ]
    resp_excess = client.post("/api/analyze", files=excess_files)
    assert resp_excess.status_code == 400
    assert "Upload no more than 8 documents" in resp_excess.json()["detail"]


def test_reconciliation_returns_valid_persisted_audit_id(client):
    """Verify /api/analyze creates exactly one unique audit record with persisted results."""
    from backend.app.db import list_analyses

    initial_count = len(list_analyses())

    samples_resp = client.get("/api/samples")
    samples = samples_resp.json()["samples"]
    files = [
        ("files", (s["filename"], io.BytesIO(s["content"].encode("utf-8")), "text/plain"))
        for s in samples
    ]

    resp = client.post("/api/analyze", files=files)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    result = resp.json()

    assert "id" in result
    audit_id = result["id"]
    assert audit_id.startswith("anl-")

    # Verify exactly 1 audit added to database (no duplicate records)
    after_count = len(list_analyses())
    assert after_count == initial_count + 1

    # Verify audit retrievable by ID
    get_resp = client.get(f"/api/analyses/{audit_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == audit_id


def test_favicon_endpoint_returns_clean_response(client):
    """Verify GET /favicon.ico does not return 404."""
    resp = client.get("/favicon.ico")
    assert resp.status_code in (200, 204)


def test_direct_document_routes_download_review_delete(client):
    """Verify document download, review updates, and deletion via direct document URLs."""
    # Create shipment
    shp_resp = client.post(
        "/api/shipments",
        json={"reference": "SHP-DOC-DIRECT-01", "status": "draft"},
    )
    shp_id = shp_resp.json()["id"]

    # Upload document
    test_content = b"Commercial Invoice direct test bytes"
    up_resp = client.post(
        f"/api/shipments/{shp_id}/documents",
        files=[("files", ("invoice_direct.txt", io.BytesIO(test_content), "text/plain"))],
    )
    assert up_resp.status_code == 201
    doc_id = up_resp.json()["documents"][0]["id"]

    # Direct download
    dl_resp = client.get(f"/api/documents/{doc_id}/download")
    assert dl_resp.status_code == 200
    assert dl_resp.content == test_content

    # Direct review status update
    patch_resp = client.patch(
        f"/api/documents/{doc_id}",
        json={"review_status": "verified_by_user", "review_notes": "All checks verified"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["review_status"] == "verified_by_user"

    # Direct delete
    del_resp = client.delete(f"/api/documents/{doc_id}")
    assert del_resp.status_code == 200
    assert client.get(f"/api/documents/{doc_id}/download").status_code == 404
