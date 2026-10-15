import json
import sqlite3
import pytest
from fastapi.testclient import TestClient

from backend.app.db import (
    create_shipment,
    delete_shipment,
    get_analysis_by_id,
    get_connection,
    get_db_path,
    init_db,
    list_analyses,
    save_analysis,
    set_db_path,
)
from backend.app.main import app


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    """Use an isolated SQLite database for each test."""
    original_path = get_db_path()
    test_db = tmp_path / "test_tradesathi_history.db"
    set_db_path(test_db)
    init_db(test_db)
    yield test_db
    set_db_path(original_path)


@pytest.fixture
def client():
    return TestClient(app)


def _seed_sample_audits():
    """Helper to seed sample audits: both standalone and shipment-linked."""
    # Create a shipment
    shipment = create_shipment({
        "reference": "SHP-2026-EXPORT-99",
        "exporter": "Kamakshi Seafoods Ltd",
        "buyer": "Ocean Foods Corp",
        "destination_country": "USA",
    })
    shipment_id = shipment["id"]

    # Standalone audit 1
    save_analysis(
        analysis_id="anl-standalone-01",
        mode="rules_fallback",
        model=None,
        status="needs_attention",
        headline="Reconciliation detected net weight mismatch",
        filenames=["commercial_invoice.txt", "packing_list.txt"],
        discrepancy_count=1,
        response_data={
            "id": "anl-standalone-01",
            "created_at": "2026-10-01T10:00:00+00:00",
            "mode": "rules_fallback",
            "documents": [
                {
                    "id": "doc-1",
                    "filename": "commercial_invoice.txt",
                    "invoice_number": "INV-2026-901",
                    "exporter": "Kamakshi Seafoods Ltd",
                    "buyer": "Global Imports Inc",
                    "total_amount": 45000.0,
                    "total_net_weight_kg": 18000.0,
                },
                {
                    "id": "doc-2",
                    "filename": "packing_list.txt",
                    "invoice_number": "INV-2026-901",
                    "exporter": "Kamakshi Seafoods Ltd",
                    "buyer": "Global Imports Inc",
                    "total_net_weight_kg": 18150.0,
                },
            ],
            "discrepancies": [
                {
                    "field": "total_net_weight_kg",
                    "label": "Net Weight",
                    "severity": "critical",
                    "difference": "+150 kg",
                    "reason": "Weight mismatch between invoice and packing list",
                    "recommended_action": "Perform physical tare weight calibration",
                    "message": "commercial_invoice: 18000 kg vs packing_list: 18150 kg",
                }
            ],
            "summary": {
                "status": "needs_attention",
                "headline": "Reconciliation detected net weight mismatch",
                "documents_received": ["commercial_invoice.txt", "packing_list.txt"],
                "summary_text": "Net weight conflict requires physical verification.",
                "checklist": [
                    {
                        "id": "chk-weights",
                        "title": "Weights & Cargo Tally",
                        "status": "failed",
                        "detail": "150 kg weight mismatch",
                    }
                ],
            },
        },
        shipment_id=None,
    )

    # Standalone audit 2 (Ready status)
    save_analysis(
        analysis_id="anl-standalone-02",
        mode="ollama",
        model="llama3",
        status="ready_for_review",
        headline="Export reconciliation passed all integrity checks",
        filenames=["commercial_invoice_clean.txt", "packing_list_clean.txt"],
        discrepancy_count=0,
        response_data={
            "id": "anl-standalone-02",
            "created_at": "2026-10-05T12:00:00+00:00",
            "mode": "ollama",
            "model": "llama3",
            "documents": [
                {
                    "id": "doc-3",
                    "filename": "commercial_invoice_clean.txt",
                    "invoice_number": "INV-2026-888",
                    "exporter": "Kerala Spices Trading",
                    "buyer": "Spice Route GmbH",
                    "total_amount": 12000.0,
                }
            ],
            "discrepancies": [],
            "summary": {
                "status": "ready_for_review",
                "headline": "Export reconciliation passed all integrity checks",
                "documents_received": ["commercial_invoice_clean.txt"],
                "summary_text": "Zero discrepancies detected.",
                "checklist": [
                    {
                        "id": "chk-entities",
                        "title": "Parties & Entities",
                        "status": "passed",
                        "detail": "Consistent exporter and buyer across all documents",
                    }
                ],
            },
        },
        shipment_id=None,
    )

    # Shipment-linked audit
    save_analysis(
        analysis_id="anl-linked-03",
        mode="rules_fallback",
        model=None,
        status="needs_attention",
        headline="Shipment SHP-2026-EXPORT-99 reconciliation completed",
        filenames=["shipping_instructions.txt", "commercial_invoice.txt"],
        discrepancy_count=1,
        response_data={
            "id": "anl-linked-03",
            "created_at": "2026-10-10T15:30:00+00:00",
            "mode": "rules_fallback",
            "documents": [
                {
                    "id": "doc-4",
                    "filename": "commercial_invoice.txt",
                    "invoice_number": "INV-2026-999",
                    "exporter": "Kamakshi Seafoods Ltd",
                    "buyer": "Ocean Foods Corp",
                    "shipment_reference": "SHP-2026-EXPORT-99",
                }
            ],
            "discrepancies": [
                {
                    "field": "hs_code",
                    "label": "HS Code",
                    "severity": "warning",
                    "difference": "6-digit vs 8-digit tariff code",
                    "reason": "Tariff classification precision required",
                    "recommended_action": "Verify with customs broker",
                    "message": "HS code truncated in commercial invoice",
                }
            ],
            "summary": {
                "status": "needs_attention",
                "headline": "Shipment SHP-2026-EXPORT-99 reconciliation completed",
                "documents_received": ["shipping_instructions.txt", "commercial_invoice.txt"],
                "summary_text": "Warning found on HS code classification.",
                "checklist": [],
            },
        },
        shipment_id=shipment_id,
    )

    return shipment_id


def test_audit_search_by_id_and_business_fields(client):
    """Test 1: Audit search by ID, invoice number, exporter, buyer, and shipment reference."""
    _seed_sample_audits()

    # Search by Audit ID
    res = client.get("/api/analyses?search=anl-standalone-01")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["analyses"][0]["id"] == "anl-standalone-01"

    # Search by Invoice Number
    res_inv = client.get("/api/analyses?search=INV-2026-901")
    assert res_inv.status_code == 200
    data_inv = res_inv.json()
    assert data_inv["total"] == 1
    assert data_inv["analyses"][0]["id"] == "anl-standalone-01"
    assert "INV-2026-901" in data_inv["analyses"][0]["invoice_numbers"]

    # Search by Exporter
    res_exp = client.get("/api/analyses?search=Kerala Spices")
    assert res_exp.status_code == 200
    data_exp = res_exp.json()
    assert data_exp["total"] == 1
    assert data_exp["analyses"][0]["id"] == "anl-standalone-02"

    # Search by Buyer
    res_buy = client.get("/api/analyses?search=Spice Route GmbH")
    assert res_buy.status_code == 200
    data_buy = res_buy.json()
    assert data_buy["total"] == 1
    assert data_buy["analyses"][0]["id"] == "anl-standalone-02"

    # Search by Shipment Reference
    res_shp = client.get("/api/analyses?search=SHP-2026-EXPORT-99")
    assert res_shp.status_code == 200
    data_shp = res_shp.json()
    assert data_shp["total"] == 1
    assert data_shp["analyses"][0]["id"] == "anl-linked-03"
    assert data_shp["analyses"][0]["shipment_reference"] == "SHP-2026-EXPORT-99"


def test_status_date_and_shipment_filters(client):
    """Test 2: Status, date range, and linked vs standalone filters."""
    _seed_sample_audits()

    # Filter by Status: ready_for_review
    res_ready = client.get("/api/analyses?status=ready_for_review")
    assert res_ready.status_code == 200
    assert res_ready.json()["total"] == 1
    assert res_ready.json()["analyses"][0]["status"] == "ready_for_review"

    # Filter by Status: needs_attention
    res_att = client.get("/api/analyses?status=needs_attention")
    assert res_att.status_code == 200
    assert res_att.json()["total"] == 2

    # Filter by Audit Type: linked
    res_linked = client.get("/api/analyses?audit_type=linked")
    assert res_linked.status_code == 200
    data_linked = res_linked.json()
    assert data_linked["total"] == 1
    assert data_linked["analyses"][0]["id"] == "anl-linked-03"
    assert data_linked["analyses"][0]["is_linked"] is True

    # Filter by Audit Type: standalone
    res_stand = client.get("/api/analyses?audit_type=standalone")
    assert res_stand.status_code == 200
    data_stand = res_stand.json()
    assert data_stand["total"] == 2
    for item in data_stand["analyses"]:
        assert item["is_linked"] is False

    # Filter by Date range
    # Seeded dates: 2026-10-01, 2026-10-05, 2026-10-10 (note save_analysis uses datetime.now(timezone.utc) in created_at)
    # Let's query date range matching today's date
    from datetime import datetime, timezone
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    res_today = client.get(f"/api/analyses?date_from={today_str}&date_to={today_str}")
    assert res_today.status_code == 200
    assert res_today.json()["total"] == 3


def test_pagination_and_sorting(client):
    """Test 3: Pagination and sorting."""
    _seed_sample_audits()

    # Page size 1, Page 1
    res_p1 = client.get("/api/analyses?page=1&page_size=1")
    assert res_p1.status_code == 200
    data_p1 = res_p1.json()
    assert data_p1["total"] == 3
    assert len(data_p1["analyses"]) == 1
    assert data_p1["page"] == 1
    assert data_p1["page_size"] == 1
    assert data_p1["total_pages"] == 3

    # Page size 1, Page 2
    res_p2 = client.get("/api/analyses?page=2&page_size=1")
    assert res_p2.status_code == 200
    data_p2 = res_p2.json()
    assert len(data_p2["analyses"]) == 1
    assert data_p2["analyses"][0]["id"] != data_p1["analyses"][0]["id"]

    # Sorting newest (desc) vs oldest (asc)
    res_desc = client.get("/api/analyses?sort_order=desc")
    res_asc = client.get("/api/analyses?sort_order=asc")
    assert res_desc.status_code == 200
    assert res_asc.status_code == 200
    assert res_desc.json()["analyses"][0]["id"] == res_asc.json()["analyses"][-1]["id"]


def test_retrieving_older_audit_after_database_reconnection(client):
    """Test 4: Retrieving an older audit from disk/db without re-running analysis."""
    _seed_sample_audits()
    original_db = get_db_path()

    # Reconnect / re-instantiate connection to simulate server restart
    with get_connection(original_db) as conn:
        cursor = conn.execute("SELECT id FROM analyses WHERE id = 'anl-standalone-01'")
        assert cursor.fetchone() is not None

    # Reopening saved result directly from backend endpoint
    res = client.get("/api/analyses/anl-standalone-01")
    assert res.status_code == 200
    audit = res.json()
    assert audit["id"] == "anl-standalone-01"
    assert audit["mode"] == "rules_fallback"
    assert len(audit["documents"]) == 2
    assert audit["documents"][0]["invoice_number"] == "INV-2026-901"
    assert len(audit["discrepancies"]) == 1
    assert audit["discrepancies"][0]["severity"] == "critical"
    assert audit["summary"]["checklist"][0]["status"] == "failed"


def test_correct_selection_of_historical_audit_for_json_export(client):
    """Test 5: Verify selecting a historical audit yields exact, uncorrupted JSON export payload."""
    _seed_sample_audits()

    res = client.get("/api/analyses/anl-standalone-02")
    assert res.status_code == 200
    audit = res.json()

    # Verify JSON export integrity
    json_bytes = json.dumps(audit).encode("utf-8")
    parsed_back = json.loads(json_bytes.decode("utf-8"))
    assert parsed_back["id"] == "anl-standalone-02"
    assert parsed_back["mode"] == "ollama"
    assert parsed_back["model"] == "llama3"
    assert parsed_back["summary"]["status"] == "ready_for_review"
    assert len(parsed_back["summary"]["checklist"]) == 1
    assert parsed_back["summary"]["checklist"][0]["id"] == "chk-entities"


def test_standalone_and_shipment_linked_audit_records(client):
    """Test 7: Standalone and shipment-linked audit designations."""
    shipment_id = _seed_sample_audits()

    # Standalone audit has shipment_id=None
    standalone = get_analysis_by_id("anl-standalone-01")
    assert standalone["shipment_id"] is None
    assert "shipment_reference" not in standalone or standalone.get("shipment_reference") is None

    # Linked audit has valid shipment_id and resolved reference
    linked = get_analysis_by_id("anl-linked-03")
    assert linked["shipment_id"] == shipment_id
    assert linked["shipment_reference"] == "SHP-2026-EXPORT-99"


def test_preserved_history_after_shipment_deletion(client):
    """Test 8: Preserved history after shipment deletion (analyses unlinked, never destroyed)."""
    shipment_id = _seed_sample_audits()

    # Verify linked before deletion
    linked_before = get_analysis_by_id("anl-linked-03")
    assert linked_before["shipment_id"] == shipment_id

    # Delete the shipment
    del_res = client.delete(f"/api/shipments/{shipment_id}")
    assert del_res.status_code == 200

    # The analysis record must STILL EXIST, with shipment_id unlinked (null)
    linked_after = get_analysis_by_id("anl-linked-03")
    assert linked_after is not None
    assert linked_after["id"] == "anl-linked-03"
    assert linked_after["shipment_id"] is None

    # Historical endpoint still serves it cleanly
    res = client.get("/api/analyses/anl-linked-03")
    assert res.status_code == 200
    assert res.json()["id"] == "anl-linked-03"


def test_empty_history_and_malformed_historical_payloads(client):
    """Test 9: Empty history and malformed historical payload handling."""
    # Empty history
    res_empty = client.get("/api/analyses")
    assert res_empty.status_code == 200
    assert res_empty.json()["total"] == 0
    assert res_empty.json()["analyses"] == []

    # Nonexistent audit ID
    res_notfound = client.get("/api/analyses/anl-does-not-exist")
    assert res_notfound.status_code == 404

    # Malformed historical payload in SQLite
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO analyses (
                id, created_at, mode, model, status, headline,
                document_count, filenames_json, discrepancy_count, response_json, shipment_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "anl-corrupted-99",
                "2026-10-12T00:00:00+00:00",
                "rules_fallback",
                None,
                "needs_attention",
                "Corrupted headline",
                1,
                "['bad_json']",
                0,
                "{invalid_json_bytes_corrupted: true",
                None,
            ),
        )
        conn.commit()

    # Fetching corrupted audit returns recoverable 422 HTTP exception
    res_corrupt = client.get("/api/analyses/anl-corrupted-99")
    assert res_corrupt.status_code == 422
    assert "malformed or corrupted" in res_corrupt.json()["detail"]


def test_input_validation_on_filter_parameters(client):
    """Test 10: Validation of query and filter parameters."""
    _seed_sample_audits()

    # Invalid sort order
    res_bad_sort = client.get("/api/analyses?sort_order=invalid_sort")
    assert res_bad_sort.status_code == 400
    assert "Invalid sort_order" in res_bad_sort.json()["detail"]

    # Invalid audit type
    res_bad_type = client.get("/api/analyses?audit_type=unsupported_type")
    assert res_bad_type.status_code == 400
    assert "Invalid audit_type" in res_bad_type.json()["detail"]

    # Invalid page number (< 1)
    res_bad_page = client.get("/api/analyses?page=0")
    assert res_bad_page.status_code == 422  # Pydantic Query(ge=1) validation
