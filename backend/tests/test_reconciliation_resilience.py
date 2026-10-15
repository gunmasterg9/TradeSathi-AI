import io
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.db import (
    get_connection,
    get_analysis_by_id,
    list_analyses,
    create_shipment,
    list_documents_for_shipment,
)

client = TestClient(app)

SAMPLE_INVOICE = b"""COMMERCIAL INVOICE
Exporter: Kamakshi Seafood Exports
Buyer: Ocean Foods LLC
Invoice No: INV-2026-104
Total Amount: 12500.00
Net Weight: 18000 kg
Gross Weight: 19500 kg
Packages: 1000 cartons
"""

SAMPLE_PACKING_LIST = b"""PACKING LIST
Exporter: Kamakshi Seafood Exports
Buyer: Ocean Foods LLC
Invoice No: INV-2026-104
Total Net Weight: 18100 kg
Total Gross Weight: 19600 kg
Total Packages: 1000 cartons
"""


def test_ollama_unexpected_exception_falls_back_to_deterministic_rules():
    """Verify that any unexpected exception during Ollama extraction seamlessly falls back to rules engine."""
    with patch("app.main.list_ollama_models", new=AsyncMock(return_value=["mock-model"])):
        with patch("app.main.ollama_extract", new=AsyncMock(side_effect=RuntimeError("Unexpected connection drop"))):
            response = client.post(
                "/api/analyze",
                data={"model": "mock-model"},
                files=[
                    ("files", ("invoice.txt", SAMPLE_INVOICE, "text/plain")),
                    ("files", ("packing_list.txt", SAMPLE_PACKING_LIST, "text/plain")),
                ],
            )

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "rules_fallback"
    assert data["model"] is None
    # Verify extraction notes mention the fallback
    assert any("Ollama inference failed" in note for doc in data["documents"] for note in doc.get("extraction_notes", []))
    assert len(data["discrepancies"]) >= 1


def test_failed_reconciliation_creates_no_audit_record_and_retry_is_clean():
    """Ensure a failed reconciliation request does not create orphaned audit records, and manual retry creates exactly 1."""
    # Count analyses before
    with get_connection() as conn:
        before_count = conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]

    # Step 1: Send invalid request (empty file) which fails with 400
    failed_resp = client.post(
        "/api/analyze",
        files=[
            ("files", ("empty.txt", b"", "text/plain")),
        ],
    )
    assert failed_resp.status_code == 400

    # Verify no audit record was created
    with get_connection() as conn:
        after_failed_count = conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
    assert after_failed_count == before_count

    # Step 2: Manual retry with valid documents
    retry_resp = client.post(
        "/api/analyze",
        files=[
            ("files", ("invoice.txt", SAMPLE_INVOICE, "text/plain")),
            ("files", ("packing_list.txt", SAMPLE_PACKING_LIST, "text/plain")),
        ],
    )
    assert retry_resp.status_code == 200
    retry_data = retry_resp.json()
    analysis_id = retry_data["id"]

    # Verify exactly 1 new record was created in total
    with get_connection() as conn:
        after_retry_count = conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
    assert after_retry_count == before_count + 1

    # Cleanup the newly created test analysis to keep db pristine
    with get_connection() as conn:
        conn.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,))
        conn.commit()


def test_shipment_retry_does_not_duplicate_documents():
    """Verify that manual retries for a shipment do not create duplicate documents in register."""
    import uuid
    ref = f"REF-RETRY-{uuid.uuid4().hex[:6].upper()}"
    shipment = create_shipment({
        "reference": ref,
        "exporter": "Test Exporter",
        "buyer": "Test Buyer",
    })
    shipment_id = shipment["id"]

    try:
        # First call succeeds
        resp1 = client.post(
            "/api/analyze",
            data={"shipment_id": shipment_id},
            files=[
                ("files", ("invoice.txt", SAMPLE_INVOICE, "text/plain")),
                ("files", ("packing_list.txt", SAMPLE_PACKING_LIST, "text/plain")),
            ],
        )
        assert resp1.status_code == 200
        anl_id_1 = resp1.json()["id"]

        docs_1 = list_documents_for_shipment(shipment_id)
        assert len(docs_1) == 2

        # Second call (e.g. user retrying or re-running analysis on same files)
        resp2 = client.post(
            "/api/analyze",
            data={"shipment_id": shipment_id},
            files=[
                ("files", ("invoice.txt", SAMPLE_INVOICE, "text/plain")),
                ("files", ("packing_list.txt", SAMPLE_PACKING_LIST, "text/plain")),
            ],
        )
        assert resp2.status_code == 200
        anl_id_2 = resp2.json()["id"]

        # Document count on shipment must still be exactly 2 (no duplicate document records)
        docs_2 = list_documents_for_shipment(shipment_id)
        assert len(docs_2) == 2

        # Cleanup test analyses
        with get_connection() as conn:
            conn.execute("DELETE FROM analyses WHERE id IN (?, ?)", (anl_id_1, anl_id_2))
            conn.commit()
    finally:
        with get_connection() as conn:
            conn.execute("DELETE FROM documents WHERE shipment_id = ?", (shipment_id,))
            conn.execute("DELETE FROM shipments WHERE id = ?", (shipment_id,))
            conn.commit()
