import os
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.app.db import (
    get_connection,
    get_db_path,
    init_db,
    set_db_path,
)
from backend.app.main import app


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    """Use an isolated SQLite database for each test to prevent test state cross-contamination."""
    original_path = get_db_path()
    test_db = tmp_path / "test_tradesathi.db"
    set_db_path(test_db)
    init_db(test_db)
    yield test_db
    set_db_path(original_path)


@pytest.fixture
def client():
    return TestClient(app)


def test_shipment_creation_and_retrieval(client):
    payload = {
        "reference": "SHP-2026-IN-001",
        "exporter": "Apex Seafoods Pvt Ltd",
        "buyer": "Pacific Cold Storage LLC",
        "product_description": "Frozen Black Tiger Shrimp",
        "destination_country": "USA",
        "destination_port": "Long Beach",
        "planned_shipment_date": "2026-11-15",
        "incoterm": "CIF",
        "named_place": "Long Beach, CA",
        "notes": "Reefer container set at -20C",
    }
    create_resp = client.post("/api/shipments", json=payload)
    assert create_resp.status_code == 201
    created_data = create_resp.json()
    assert created_data["reference"] == "SHP-2026-IN-001"
    assert created_data["exporter"] == "Apex Seafoods Pvt Ltd"
    assert created_data["status"] == "draft"
    assert "id" in created_data
    shipment_id = created_data["id"]

    # Retrieval by ID
    get_resp = client.get(f"/api/shipments/{shipment_id}")
    assert get_resp.status_code == 200
    retrieved = get_resp.json()
    assert retrieved["id"] == shipment_id
    assert retrieved["buyer"] == "Pacific Cold Storage LLC"
    assert retrieved["destination_port"] == "Long Beach"
    assert retrieved["analysis_count"] == 0


def test_listing_and_updating_shipments(client):
    # Create two shipments
    client.post("/api/shipments", json={"reference": "SHP-ALPHA-101", "exporter": "Alpha Corp", "destination_port": "Tokyo"})
    client.post("/api/shipments", json={"reference": "SHP-BETA-202", "exporter": "Beta Corp", "destination_port": "Rotterdam"})

    # List all
    list_resp = client.get("/api/shipments")
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert data["total"] >= 2
    refs = [s["reference"] for s in data["shipments"]]
    assert "SHP-ALPHA-101" in refs
    assert "SHP-BETA-202" in refs

    # Filter with search
    search_resp = client.get("/api/shipments?search=Tokyo")
    assert search_resp.status_code == 200
    search_data = search_resp.json()
    assert search_data["total"] == 1
    assert search_data["shipments"][0]["reference"] == "SHP-ALPHA-101"

    # Update shipment
    alpha_id = search_data["shipments"][0]["id"]
    patch_resp = client.patch(f"/api/shipments/{alpha_id}", json={
        "product_description": "Alaskan King Crab",
        "status": "ready_for_review",
        "notes": "Updated priority dispatch"
    })
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["product_description"] == "Alaskan King Crab"
    assert updated["status"] == "ready_for_review"
    assert updated["notes"] == "Updated priority dispatch"


def test_duplicate_shipment_reference_rejection(client):
    client.post("/api/shipments", json={"reference": "DUP-REF-999"})
    # Attempt duplicate
    dup_resp = client.post("/api/shipments", json={"reference": "DUP-REF-999"})
    assert dup_resp.status_code == 409
    assert "already exists" in dup_resp.json()["detail"]


def test_invalid_or_nonexistent_shipment_ids(client):
    # Nonexistent ID on retrieval
    res_get = client.get("/api/shipments/shp-doesnotexist")
    assert res_get.status_code == 404

    # Nonexistent ID on patch
    res_patch = client.patch("/api/shipments/shp-doesnotexist", json={"notes": "test"})
    assert res_patch.status_code == 404

    # Nonexistent ID on analyses listing
    res_anl = client.get("/api/shipments/shp-doesnotexist/analyses")
    assert res_anl.status_code == 404

    # Nonexistent ID on document reconciliation link
    sample_text = "INVOICE #INV-100\nTotal: USD 1000"
    files = [("files", ("invoice.txt", sample_text.encode("utf-8"), "text/plain"))]
    res_link = client.post("/api/analyze", files=files, data={"shipment_id": "shp-nonexistent-id"})
    assert res_link.status_code == 404
    assert "not found" in res_link.json()["detail"].lower()


def test_linking_analysis_to_shipment_and_listing_audit_history(client):
    # 1. Create shipment
    shp_resp = client.post("/api/shipments", json={"reference": "SHP-LINK-TEST-001"})
    shipment_id = shp_resp.json()["id"]

    # 2. Analyze documents with shipment_id
    inv_text = "COMMERCIAL INVOICE #INV-44\nExporter: Marine Trade Ltd\nBuyer: Global Foods\nTotal Net Weight: 5000 kg"
    pl_text = "PACKING LIST for #INV-44\nExporter: Marine Trade Ltd\nBuyer: Global Foods\nTotal Net Weight: 5000 kg"
    files = [
        ("files", ("invoice.txt", inv_text.encode("utf-8"), "text/plain")),
        ("files", ("packing_list.txt", pl_text.encode("utf-8"), "text/plain")),
    ]
    analyze_resp = client.post("/api/analyze", files=files, data={"shipment_id": shipment_id})
    assert analyze_resp.status_code == 200
    anl_data = analyze_resp.json()
    assert anl_data.get("shipment_id") == shipment_id

    # 3. Retrieve shipment and verify updated count and status
    shp_updated = client.get(f"/api/shipments/{shipment_id}").json()
    assert shp_updated["analysis_count"] == 1
    assert shp_updated["latest_analysis_status"] is not None

    # 4. List shipment audit history
    audit_resp = client.get(f"/api/shipments/{shipment_id}/analyses")
    assert audit_resp.status_code == 200
    audits = audit_resp.json()["analyses"]
    assert len(audits) == 1
    assert audits[0]["id"] == anl_data["id"]
    assert audits[0]["shipment_id"] == shipment_id


def test_persistence_after_database_reconnection(tmp_path):
    # Use explicit database file path
    db_file = tmp_path / "reconnect_test.db"
    set_db_path(db_file)
    init_db(db_file)

    test_client = TestClient(app)
    create_resp = test_client.post("/api/shipments", json={
        "reference": "SHP-PERSIST-909",
        "exporter": "Persist Exporters",
        "buyer": "Persist Buyers",
    })
    assert create_resp.status_code == 201
    shipment_id = create_resp.json()["id"]

    # "Disconnect" and reconnect by reinitializing / reopening connection to the exact same file
    set_db_path(db_file)
    init_db(db_file)

    test_client2 = TestClient(app)
    get_resp = test_client2.get(f"/api/shipments/{shipment_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["reference"] == "SHP-PERSIST-909"
    assert get_resp.json()["exporter"] == "Persist Exporters"
