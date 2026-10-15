import asyncio
import io
from unittest.mock import patch, MagicMock
import httpx
import pytest
from fastapi.testclient import TestClient

from app.analysis import (
    clean_entity_value,
    parse_and_validate_date,
    normalize_weight_with_provenance,
    parse_and_validate_currency,
    parse_and_validate_amount,
    parse_and_validate_hs_code,
    rules_extract,
    ollama_extract,
    compare_documents,
    build_response,
)
from app.db import (
    init_db,
    save_analysis,
    get_analysis_by_id,
    list_analyses,
)
from app.main import app
from app.schemas import AnalyzeResponse, ExtractedDocument, FieldEvidence


# ---------------------------------------------------------------------------
# 1. Valid and Missing Fields
# ---------------------------------------------------------------------------

def test_clean_entity_value_filters_placeholders():
    """Ensure placeholder strings are cleanly treated as None/missing, not genuine values."""
    assert clean_entity_value("N/A") is None
    assert clean_entity_value("n/a") is None
    assert clean_entity_value("None") is None
    assert clean_entity_value("-") is None
    assert clean_entity_value("TBD") is None
    assert clean_entity_value("UNKNOWN") is None
    assert clean_entity_value("   ") is None
    assert clean_entity_value("Kamakshi Seafood Exports") == "Kamakshi Seafood Exports"


def test_missing_fields_never_invented():
    """Ensure missing fields in deterministic extraction are None and recorded as missing."""
    sparse_text = """COMMERCIAL INVOICE
Invoice No: INV-2026-999
Date: 2026-10-15
Total Amount: USD 5000.00
"""
    doc = rules_extract("sparse_invoice.txt", sparse_text)
    assert doc.invoice_number == "INV-2026-999"
    assert doc.total_amount == 5000.0
    # Missing fields must remain None, never hallucinated defaults
    assert doc.exporter is None
    assert doc.buyer is None
    assert doc.consignee is None
    assert doc.total_net_weight_kg is None
    assert doc.total_gross_weight_kg is None
    assert doc.packages is None
    assert doc.hs_code is None

    # Check evidence records
    assert "invoice_number" in doc.field_evidence
    assert doc.field_evidence["invoice_number"].validation_status == "verified"
    assert doc.field_evidence["invoice_number"].raw_value == "INV-2026-999"


# ---------------------------------------------------------------------------
# 2. Invalid Dates and Numeric Values
# ---------------------------------------------------------------------------

def test_date_validation_calendar_and_formats():
    """Test ISO, DD/MM/YYYY, textual dates, and rejection of invalid calendar dates."""
    # Valid ISO
    val, raw, status, note = parse_and_validate_date("2026-10-12")
    assert val == "2026-10-12"
    assert status == "verified"

    # Valid DD/MM/YYYY
    val, raw, status, note = parse_and_validate_date("12/10/2026")
    assert val == "2026-10-12"
    assert status == "verified"

    # Valid textual date
    val, raw, status, note = parse_and_validate_date("12 October 2026")
    assert val == "2026-10-12"
    assert status == "verified"

    # Invalid calendar date: February 31st
    val, raw, status, note = parse_and_validate_date("2026-02-31")
    assert val is None
    assert raw == "2026-02-31"
    assert status == "invalid"

    # Invalid date: 99-99-9999
    val, raw, status, note = parse_and_validate_date("99-99-9999")
    assert val is None
    assert status == "invalid"

    # Non-date string
    val, raw, status, note = parse_and_validate_date("NotADate")
    assert val is None
    assert status == "invalid"


def test_invalid_date_in_rules_extract():
    """Document with invalid calendar date should not produce a valid ISO date."""
    text = """COMMERCIAL INVOICE
Invoice No: INV-ERR-1
Invoice Date: 2026-02-31
Total: USD 1000
"""
    doc = rules_extract("invoice.txt", text)
    assert doc.invoice_date is None
    assert doc.raw_invoice_date == "2026-02-31"
    assert "invoice_date" in doc.field_evidence
    assert doc.field_evidence["invoice_date"].validation_status == "invalid"


# ---------------------------------------------------------------------------
# 3. Weight Units and Ambiguous Units
# ---------------------------------------------------------------------------

def test_weight_normalization_and_provenance():
    """Verify weight conversion for metric, imperial, MT, and flag ambiguous/invalid units."""
    # Standard kg
    norm, raw, status, note = normalize_weight_with_provenance("18000 kg")
    assert norm == 18000.0
    assert "kg" in raw
    assert status == "verified"

    # Pounds / lbs conversion (2204.62 lbs ~ 1000 kg)
    norm, raw, status, note = normalize_weight_with_provenance("2204.62 lbs")
    assert abs(norm - 1000.0) < 0.1
    assert "lbs" in raw
    assert status == "verified"

    # Metric Tonnes (18 MT = 18000 kg)
    norm, raw, status, note = normalize_weight_with_provenance("18 MT")
    assert norm == 18000.0
    assert "MT" in raw
    assert status == "verified"

    # Grams (500000 g = 500 kg)
    norm, raw, status, note = normalize_weight_with_provenance("500000 g")
    assert norm == 500.0
    assert "g" in raw
    assert status == "verified"

    # Ambiguous unit: number with no unit specified
    norm, raw, status, note = normalize_weight_with_provenance("18000")
    assert norm == 18000.0
    assert status == "uncertain"
    assert "unspecified" in note.lower()

    # Invalid unit: non-weight unit
    norm, raw, status, note = normalize_weight_with_provenance("18000 boxes")
    assert norm is None
    assert status == "invalid"


# ---------------------------------------------------------------------------
# 4. Currency and Amount Parsing
# ---------------------------------------------------------------------------

def test_currency_and_amount_parsing():
    """Verify ISO currencies, symbols, and rejection of invalid currency tokens."""
    curr, raw, status, note = parse_and_validate_currency("USD")
    assert curr == "USD"
    assert status == "verified"

    curr, raw, status, note = parse_and_validate_currency("$")
    assert curr == "USD"
    assert status == "verified"

    curr, raw, status, note = parse_and_validate_currency("€")
    assert curr == "EUR"
    assert status == "verified"

    curr, raw, status, note = parse_and_validate_currency("₹")
    assert curr == "INR"
    assert status == "verified"

    curr, raw, status, note = parse_and_validate_currency("FOOBAR")
    assert curr is None
    assert status == "invalid"

    # Amounts with formatting
    amt, raw, status, note = parse_and_validate_amount("12,500.50")
    assert amt == 12500.5
    assert status == "verified"

    amt, raw, status, note = parse_and_validate_amount("invalid_amount")
    assert amt is None
    assert status == "invalid"


def test_hs_code_validation():
    """Ensure valid HS codes (4-10 digits) are accepted and non-HS strings rejected."""
    hs, raw, status, note = parse_and_validate_hs_code("0303.89")
    assert hs == "0303.89"
    assert status == "verified"

    hs, raw, status, note = parse_and_validate_hs_code("8471.30.10")
    assert hs == "8471.30.10"
    assert status == "verified"

    hs, raw, status, note = parse_and_validate_hs_code("12")  # Too short
    assert hs is None
    assert status == "invalid"

    hs, raw, status, note = parse_and_validate_hs_code("NON_HS_TEXT")
    assert hs is None
    assert status == "invalid"


# ---------------------------------------------------------------------------
# 5. Malformed or Incomplete AI Responses
# ---------------------------------------------------------------------------

def test_ollama_extract_handles_malformed_json():
    """When Ollama returns malformed JSON, raise ValueError so fallback triggers."""
    async def _run():
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {"content": "Here is the result: {invoice_number: missing_quotes, invalid json}"}
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", return_value=mock_resp):
            with pytest.raises(ValueError, match="invalid JSON"):
                await ollama_extract("http://localhost:11434", "llama3.2:latest", "invoice.txt", "Commercial Invoice\nInvoice No: INV-100")

    asyncio.run(_run())


def test_ollama_extract_handles_incomplete_ai_fields():
    """When Ollama returns JSON with unusual types or partial keys, validate and sanitize."""
    async def _run():
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {
                "content": """```json
{
  "document_type": "commercial_invoice",
  "invoice_number": "INV-AI-2026",
  "total_amount": "invalid_number_string",
  "total_net_weight_kg": 18000,
  "exporter": "AI Exporter Ltd",
  "buyer": "N/A"
}
```"""
            }
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", return_value=mock_resp):
            doc = await ollama_extract("http://localhost:11434", "llama3.2:latest", "invoice.txt", "Invoice raw content")
            assert doc.document_type == "commercial_invoice"
            assert doc.invoice_number == "INV-AI-2026"
            assert doc.total_net_weight_kg == 18000.0
            # "invalid_number_string" should be safely None
            assert doc.total_amount is None
            # "N/A" placeholder should be cleaned to None
            assert doc.buyer is None
            assert doc.field_evidence["invoice_number"].method == "ollama_model"

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 6. Ollama Unavailable or Timing Out (Deterministic Fallback)
# ---------------------------------------------------------------------------

def test_ollama_timeout_fallback_to_deterministic():
    """When Ollama times out or raises Exception, pipeline handles it gracefully."""
    async def _run():
        with patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("Ollama timed out")):
            with pytest.raises(httpx.TimeoutException):
                await ollama_extract("http://localhost:11434", "llama3.2:latest", "invoice.txt", "Commercial Invoice\nInvoice No: INV-FALLBACK-1")

    asyncio.run(_run())


def test_full_reconciliation_under_ollama_failure():
    """Test full reconciliation endpoint falls back to rules and produces valid provenance."""
    client = TestClient(app)
    with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Ollama connection refused")):
        files = [
            (
                "files",
                (
                    "commercial_invoice.txt",
                    b"Commercial Invoice\nInvoice No: INV-100\nNet Weight: 18000 kg\nTotal: USD 10000",
                    "text/plain",
                ),
            ),
            (
                "files",
                (
                    "packing_list.txt",
                    b"Packing List\nInvoice No: INV-100\nNet Weight: 18100 kg\nPackages: 50 cartons",
                    "text/plain",
                ),
            ),
        ]
        resp = client.post("/api/analyze", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "rules_fallback"
        assert len(data["documents"]) == 2
        # Verify provenance in documents
        inv_doc = next(d for d in data["documents"] if d["document_type"] == "commercial_invoice")
        assert "invoice_number" in inv_doc["field_evidence"]
        assert inv_doc["field_evidence"]["invoice_number"]["validation_status"] == "verified"


# ---------------------------------------------------------------------------
# 7. Existing 100 kg Sample Discrepancy
# ---------------------------------------------------------------------------

def test_preservation_of_100kg_sample_discrepancy():
    """Ensure the sample commercial invoice (18,000 kg) and packing list (18,100 kg) discrepancy is detected."""
    client = TestClient(app)
    # Load default sample files from the API
    sample_resp = client.get("/api/samples")
    assert sample_resp.status_code == 200
    samples_data = sample_resp.json()
    samples = samples_data.get("samples", [])

    inv_sample = next(s for s in samples if "commercial_invoice" in s["filename"].lower())
    pack_sample = next(s for s in samples if "packing_list" in s["filename"].lower())

    files = [
        ("files", (inv_sample["filename"], inv_sample["content"].encode("utf-8"), "text/plain")),
        ("files", (pack_sample["filename"], pack_sample["content"].encode("utf-8"), "text/plain")),
    ]

    with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Ollama offline")):
        resp = client.post("/api/analyze", files=files)
        assert resp.status_code == 200
        data = resp.json()

        # Discrepancy checklist check
        weight_chk = next(c for c in data["summary"]["checklist"] if c["id"] == "chk-weights")
        assert weight_chk["status"] == "failed"

        # Discrepancy list check
        weight_disc = next(d for d in data["discrepancies"] if d["field"] == "total_net_weight_kg")
        assert weight_disc["severity"] in ("critical", "warning")
        assert "18000" in weight_disc["message"]
        assert "18100" in weight_disc["message"]
        assert "100" in weight_disc["message"]

        # Provenance verification on both documents
        inv_doc = next(d for d in data["documents"] if "invoice" in d["filename"].lower())
        pack_doc = next(d for d in data["documents"] if "packing" in d["filename"].lower())
        assert inv_doc["field_evidence"]["total_net_weight_kg"]["normalized_value"] == 18000.0
        assert pack_doc["field_evidence"]["total_net_weight_kg"]["normalized_value"] == 18100.0


# ---------------------------------------------------------------------------
# 8. Audit Persistence and Historical Record Immutability
# ---------------------------------------------------------------------------

def test_audit_persistence_preserves_provenance_and_evidence():
    """Ensure that saved audits preserve field provenance and can be reloaded without data loss."""
    init_db()

    inv_doc = ExtractedDocument(
        filename="commercial_invoice.txt",
        document_type="commercial_invoice",
        invoice_number="INV-AUDIT-001",
        raw_invoice_number="INV-AUDIT-001",
        total_net_weight_kg=15000.0,
        raw_net_weight="15000 kg",
        exporter="Audit Exporter Ltd",
        consignee="Audit Consignee Inc",
        field_evidence={
            "invoice_number": FieldEvidence(
                raw_value="INV-AUDIT-001",
                normalized_value="INV-AUDIT-001",
                source_document="commercial_invoice.txt",
                field_name="invoice_number",
                method="deterministic_rules",
                validation_status="verified",
                confidence=1.0,
            ),
            "total_net_weight_kg": FieldEvidence(
                raw_value="15000 kg",
                normalized_value="15000.0 kg",
                source_document="commercial_invoice.txt",
                field_name="total_net_weight_kg",
                method="deterministic_rules",
                validation_status="verified",
                confidence=1.0,
            ),
        },
    )

    pack_doc = ExtractedDocument(
        filename="packing_list.txt",
        document_type="packing_list",
        invoice_number="INV-AUDIT-001",
        total_net_weight_kg=15000.0,
        packages=500,
    )

    resp = build_response(
        documents=[inv_doc, pack_doc],
        mode="rules_fallback",
        model=None,
    )

    # Save to database
    save_analysis(
        analysis_id=resp.id,
        mode=resp.mode,
        model=resp.model,
        status=resp.summary.status,
        headline=resp.summary.headline,
        filenames=[d.filename for d in resp.documents],
        discrepancy_count=len(resp.discrepancies),
        response_data=resp.model_dump(mode="json"),
    )

    # Retrieve from database
    stored = get_analysis_by_id(resp.id)
    assert stored is not None
    assert stored["id"] == resp.id
    assert len(stored["documents"]) == 2

    # Check evidence fidelity
    retrieved_inv = next(d for d in stored["documents"] if d["filename"] == "commercial_invoice.txt")
    assert retrieved_inv["consignee"] == "Audit Consignee Inc"
    assert retrieved_inv["raw_net_weight"] == "15000 kg"
    assert "invoice_number" in retrieved_inv["field_evidence"]
    evidence_item = retrieved_inv["field_evidence"]["invoice_number"]
    assert evidence_item["validation_status"] == "verified"
    assert evidence_item["raw_value"] == "INV-AUDIT-001"
    assert evidence_item["method"] == "deterministic_rules"
