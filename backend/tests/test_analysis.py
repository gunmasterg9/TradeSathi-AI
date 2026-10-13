import io
import pytest
from fastapi.testclient import TestClient

from app.analysis import (
    build_response,
    compare_documents,
    normalize_weight_to_kg,
    rules_extract,
)
from app.db import (
    delete_analysis_by_id,
    get_analysis_by_id,
    init_db,
    list_analyses,
    save_analysis,
)
from app.documents import extract_text, sanitize_filename
from app.main import app
from app.schemas import ExtractedDocument


def test_rules_extract_invoice_fields():
    text = """COMMERCIAL INVOICE
Exporter: Kamakshi Seafood Exports
Buyer: Ocean Foods LLC
Invoice No: INV-2026-104
Purchase Order No: PO-8891
Invoice Date: 2026-10-12
Currency: USD
Product: Frozen Indian Mackerel, IQF
HS Code: 0303.89
Country of Origin: India
Port of Loading: JNPT, Mumbai
Port of Discharge: Port of Singapore
Total Amount: 12500.00
Net Weight: 18000 kg
Gross Weight: 19500 kg
Packages: 1000 cartons"""

    result = rules_extract("commercial_invoice.txt", text)
    assert result.document_type == "commercial_invoice"
    assert result.exporter == "Kamakshi Seafood Exports"
    assert result.buyer == "Ocean Foods LLC"
    assert result.invoice_number == "INV-2026-104"
    assert result.purchase_order_number == "PO-8891"
    assert result.currency == "USD"
    assert result.total_amount == 12500.0
    assert result.total_net_weight_kg == 18000.0
    assert result.total_gross_weight_kg == 19500.0
    assert result.packages == 1000
    assert result.hs_code == "0303.89"
    assert "India" in (result.country_of_origin or "")
    assert "JNPT" in (result.port_of_loading or "")
    assert "Singapore" in (result.port_of_discharge or "")
    assert len(result.evidence) > 0
    assert "invoice_number" in result.evidence


def test_compare_documents_detects_net_weight_mismatch():
    invoice = ExtractedDocument(
        filename="commercial_invoice.txt",
        document_type="commercial_invoice",
        buyer="Ocean Foods LLC",
        exporter="Kamakshi Seafood Exports",
        invoice_number="INV-2026-104",
        total_amount=12500.0,
        total_net_weight_kg=18000.0,
        total_gross_weight_kg=19500.0,
        packages=1000,
    )
    packing = ExtractedDocument(
        filename="packing_list.txt",
        document_type="packing_list",
        buyer="Ocean Foods LLC",
        exporter="Kamakshi Seafood Exports",
        invoice_number="INV-2026-104",
        total_amount=12500.0,
        total_net_weight_kg=18100.0,  # 100 kg mismatch
        total_gross_weight_kg=19500.0,
        packages=1000,
    )
    discrepancies = compare_documents([invoice, packing])
    weight_disc = next((d for d in discrepancies if d.field == "total_net_weight_kg"), None)
    assert weight_disc is not None
    assert weight_disc.severity in ("critical", "warning")
    assert "100" in (weight_disc.difference or "")
    assert "re-weigh cargo" in weight_disc.recommended_action.lower() or "reconcile" in weight_disc.recommended_action.lower()


def test_unit_normalization():
    # Pounds to kilograms
    kg, raw = normalize_weight_to_kg("2204.62 lbs")
    assert kg is not None
    assert round(kg) == 1000
    assert "lbs" in (raw or "")

    # Metric tons to kilograms
    kg, raw = normalize_weight_to_kg("18 MT")
    assert kg == 18000.0
    assert "MT" in (raw or "")

    # Grams to kilograms
    kg, raw = normalize_weight_to_kg("5000 g")
    assert kg == 5.0


def test_build_response_structure_and_checklist():
    doc1 = ExtractedDocument(
        filename="commercial_invoice.txt",
        document_type="commercial_invoice",
        exporter="Kamakshi Seafood Exports",
        buyer="Ocean Foods LLC",
        invoice_number="INV-1",
        currency="USD",
        total_amount=5000.0,
        total_net_weight_kg=1000.0,
        total_gross_weight_kg=1100.0,
        packages=100,
        hs_code="0303.89",
        port_of_loading="JNPT",
        port_of_discharge="Singapore",
    )
    doc2 = ExtractedDocument(
        filename="packing_list.txt",
        document_type="packing_list",
        exporter="Kamakshi Seafood Exports",
        buyer="Ocean Foods LLC",
        invoice_number="INV-1",
        currency="USD",
        total_amount=5000.0,
        total_net_weight_kg=1000.0,
        total_gross_weight_kg=1100.0,
        packages=100,
        hs_code="0303.89",
        port_of_loading="JNPT",
        port_of_discharge="Singapore",
    )
    result = build_response([doc1, doc2], "rules_fallback")
    assert result.summary.status == "ready_for_review"
    assert len(result.summary.checklist) == 5
    assert all(item.status == "passed" for item in result.summary.checklist)
    assert any(cv["field"] == "Invoice No" and cv["value"] == "INV-1" for cv in result.summary.confirmed_values)


def test_missing_field_detection():
    # Documents without invoice number
    doc = ExtractedDocument(filename="doc.txt", document_type="unknown")
    discrepancies = compare_documents([doc, doc])
    assert any(d.field == "missing_invoice_number" for d in discrepancies)
    assert any(d.field == "missing_buyer" for d in discrepancies)


def test_extract_text_from_txt():
    result = extract_text("sample.txt", b"Buyer: Example Ltd\nTotal Amount: 99.00")
    assert "Buyer: Example Ltd" in result


def test_extract_text_empty_and_unsupported():
    with pytest.raises(ValueError, match="empty"):
        extract_text("empty.txt", b"   ")

    with pytest.raises(ValueError, match="Unsupported file type"):
        extract_text("image.png", b"not an image")


def test_sanitize_filename():
    assert sanitize_filename("../../../etc/passwd") == "passwd"
    assert sanitize_filename("..\\..\\secret.pdf") == "secret.pdf"
    assert sanitize_filename('test"file*.txt') == "testfile.txt"


def test_api_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "ollama" in data
    assert "max_upload_mb" in data


def test_api_models_endpoint():
    with TestClient(app) as client:
        response = client.get("/api/models")
    assert response.status_code == 200
    data = response.json()
    assert "available" in data
    assert "models" in data


def test_api_samples_endpoint():
    with TestClient(app) as client:
        response = client.get("/api/samples")
    assert response.status_code == 200
    samples = response.json()["samples"]
    assert len(samples) >= 2
    filenames = [s["filename"] for s in samples]
    assert "commercial_invoice.txt" in filenames
    assert "packing_list.txt" in filenames


def test_api_analyze_and_persistence_flow():
    with TestClient(app) as client:
        invoice_content = b"""COMMERCIAL INVOICE
Exporter: Marine Foods Ltd
Buyer: Global Seafoods Inc
Invoice No: INV-772
Currency: USD
Total Amount: 45000.00
Net Weight: 20000 kg
Gross Weight: 21500 kg
Packages: 1000 cartons"""

        packing_content = b"""PACKING LIST
Exporter: Marine Foods Ltd
Buyer: Global Seafoods Inc
Invoice No: INV-772
Net Weight: 20200 kg
Gross Weight: 21500 kg
Packages: 1000 cartons"""

        response = client.post(
            "/api/analyze",
            files=[
                ("files", ("invoice.txt", invoice_content, "text/plain")),
                ("files", ("packing.txt", packing_content, "text/plain")),
            ],
        )
        assert response.status_code == 200
        data = response.json()
        assert data["mode"] == "rules_fallback"
        assert "id" in data
        analysis_id = data["id"]

        # Check net weight discrepancy detected
        weight_disc = next(
            (d for d in data["discrepancies"] if d["field"] == "total_net_weight_kg"), None
        )
        assert weight_disc is not None
        assert "200 kg" in weight_disc["difference"]

        # Check SQLite persistence
        saved = get_analysis_by_id(analysis_id)
        assert saved is not None
        assert saved["id"] == analysis_id

        # Check list analyses
        hist_resp = client.get("/api/analyses")
        assert hist_resp.status_code == 200
        analyses_list = hist_resp.json()["analyses"]
        assert any(item["id"] == analysis_id for item in analyses_list)

        # Check delete
        del_resp = client.delete(f"/api/analyses/{analysis_id}")
        assert del_resp.status_code == 200
        assert get_analysis_by_id(analysis_id) is None


def test_file_size_limit_rejection():
    with TestClient(app) as client:
        # 11 MB payload exceeding MAX_UPLOAD_MB (10 MB)
        big_content = b"0" * (11 * 1024 * 1024)
        response = client.post(
            "/api/analyze",
            files=[("files", ("big.txt", big_content, "text/plain"))],
        )
        assert response.status_code == 413
        assert "upload limit" in response.json()["detail"].lower()


def test_extract_docx_and_eml():
    from docx import Document
    import io

    # Test DOCX extraction
    doc = Document()
    doc.add_paragraph("Commercial Invoice No: INV-DOCX-99")
    doc.add_paragraph("Exporter: Coastal Marine Exports")
    table = doc.add_table(rows=1, cols=2)
    row = table.rows[0]
    row.cells[0].text = "Net Weight"
    row.cells[1].text = "5000 kg"
    bio = io.BytesIO()
    doc.save(bio)
    docx_bytes = bio.getvalue()

    extracted_docx = extract_text("invoice.docx", docx_bytes)
    assert "INV-DOCX-99" in extracted_docx
    assert "Coastal Marine Exports" in extracted_docx
    assert "5000 kg" in extracted_docx

    # Test EML extraction
    eml_bytes = b"""Subject: Export Shipping Instructions
From: logistics@shipper.com
To: operations@oceanfreight.com
Content-Type: text/plain; charset="utf-8"

Commercial Invoice: INV-EML-77
Buyer: Tokyo Seafood Trading Ltd
Net Weight: 12000 kg
"""
    extracted_eml = extract_text("instructions.eml", eml_bytes)
    assert "Export Shipping Instructions" in extracted_eml
    assert "INV-EML-77" in extracted_eml
    assert "Tokyo Seafood Trading" in extracted_eml


def test_incoterms_and_field_evidence_extraction():
    text = """COMMERCIAL INVOICE
Exporter: Supreme Seafoods
Buyer: Global Catch Co
Invoice No: INV-4401
Incoterms: FOB
Currency: USD
Total Amount: 10000.00
Net Weight: 5000 kg
Packages: 250"""

    result = rules_extract("invoice.txt", text)
    assert result.incoterms == "FOB"
    assert "incoterms" in result.field_evidence
    assert result.field_evidence["incoterms"].source_snippet is not None
    assert "FOB" in result.field_evidence["incoterms"].source_snippet


def test_rounding_tolerance_threshold():
    # 0.005% difference (10,000.00 vs 10,000.50) within rounding threshold (<= 0.01% and < 0.05)
    doc1 = ExtractedDocument(filename="inv.txt", document_type="commercial_invoice", total_amount=10000.00)
    doc2 = ExtractedDocument(filename="pack.txt", document_type="packing_list", total_amount=10000.01)
    discrepancies = compare_documents([doc1, doc2])
    # Should NOT have total_amount discrepancy because difference is within 0.01%
    assert not any(d.field == "total_amount" for d in discrepancies)


def test_uninstalled_model_validation():
    with TestClient(app) as client:
        payload = b"Invoice No: INV-1"
        response = client.post(
            "/api/analyze",
            data={"model": "non_existent_model_123"},
            files=[("files", ("invoice.txt", payload, "text/plain"))],
        )
        assert response.status_code == 400
        assert "not available from ollama" in response.json()["detail"].lower()


def test_missing_customs_routing_is_needs_review():
    doc1 = ExtractedDocument(
        filename="inv.txt",
        document_type="commercial_invoice",
        exporter="Exp",
        buyer="Buy",
        invoice_number="INV-1",
        currency="USD",
        total_amount=100.0,
        total_net_weight_kg=50.0,
    )
    doc2 = ExtractedDocument(
        filename="pack.txt",
        document_type="packing_list",
        exporter="Exp",
        buyer="Buy",
        invoice_number="INV-1",
        currency="USD",
        total_amount=100.0,
        total_net_weight_kg=50.0,
    )
    result = build_response([doc1, doc2], "rules_fallback")
    customs_chk = next(c for c in result.summary.checklist if c.id == "chk-customs")
    assert customs_chk.status == "needs_review"
    assert "missing" in customs_chk.detail.lower()


def test_complete_routing_is_passed():
    doc1 = ExtractedDocument(
        filename="inv.txt",
        document_type="commercial_invoice",
        exporter="Exp",
        buyer="Buy",
        invoice_number="INV-1",
        currency="USD",
        total_amount=100.0,
        total_net_weight_kg=50.0,
        hs_code="0303.89",
        port_of_loading="POL",
        port_of_discharge="POD",
    )
    doc2 = ExtractedDocument(
        filename="pack.txt",
        document_type="packing_list",
        exporter="Exp",
        buyer="Buy",
        invoice_number="INV-1",
        currency="USD",
        total_amount=100.0,
        total_net_weight_kg=50.0,
        hs_code="0303.89",
        port_of_loading="POL",
        port_of_discharge="POD",
    )
    result = build_response([doc1, doc2], "rules_fallback")
    customs_chk = next(c for c in result.summary.checklist if c.id == "chk-customs")
    assert customs_chk.status == "passed"


def test_confirmed_net_weight_mismatch_is_failed():
    doc1 = ExtractedDocument(
        filename="inv.txt",
        document_type="commercial_invoice",
        exporter="Exp",
        buyer="Buy",
        invoice_number="INV-1",
        currency="USD",
        total_amount=100.0,
        total_net_weight_kg=18000.0,
    )
    doc2 = ExtractedDocument(
        filename="pack.txt",
        document_type="packing_list",
        exporter="Exp",
        buyer="Buy",
        invoice_number="INV-1",
        currency="USD",
        total_amount=100.0,
        total_net_weight_kg=18100.0,
    )
    result = build_response([doc1, doc2], "rules_fallback")
    weights_chk = next(c for c in result.summary.checklist if c.id == "chk-weights")
    assert weights_chk.status == "failed"
    assert "mismatch" in weights_chk.detail.lower() or "differs" in weights_chk.detail.lower()


def test_missing_weight_is_needs_review_not_failed():
    doc1 = ExtractedDocument(
        filename="inv.txt",
        document_type="commercial_invoice",
        exporter="Exp",
        buyer="Buy",
        invoice_number="INV-1",
        currency="USD",
        total_amount=100.0,
    )
    doc2 = ExtractedDocument(
        filename="pack.txt",
        document_type="packing_list",
        exporter="Exp",
        buyer="Buy",
        invoice_number="INV-1",
        currency="USD",
        total_amount=100.0,
    )
    result = build_response([doc1, doc2], "rules_fallback")
    weights_chk = next(c for c in result.summary.checklist if c.id == "chk-weights")
    assert weights_chk.status == "needs_review"
    assert weights_chk.status != "failed"


def test_missing_fields_reported_separately_from_conflicts():
    doc1 = ExtractedDocument(
        filename="inv.txt",
        document_type="commercial_invoice",
        exporter="Exp",
        buyer="Buy",
        invoice_number="INV-1",
        total_net_weight_kg=18000.0,
    )
    doc2 = ExtractedDocument(
        filename="pack.txt",
        document_type="packing_list",
        exporter="Exp",
        buyer="Buy",
        invoice_number="INV-1",
        total_net_weight_kg=18100.0,
    )
    result = build_response([doc1, doc2], "rules_fallback")
    assert any("Weight" in item for item in result.summary.conflicting_items)
    assert "HS Code" in result.summary.missing_items
    assert "HS Code" not in result.summary.conflicting_items


def test_overall_status_not_ready_when_critical_discrepancies_remain():
    doc1 = ExtractedDocument(
        filename="inv.txt",
        document_type="commercial_invoice",
        exporter="Exp",
        buyer="Buy",
        invoice_number="INV-1",
        currency="USD",
        total_amount=100.0,
        total_net_weight_kg=18000.0,
        hs_code="0303.89",
        port_of_loading="POL",
        port_of_discharge="POD",
    )
    doc2 = ExtractedDocument(
        filename="pack.txt",
        document_type="packing_list",
        exporter="Exp",
        buyer="Buy",
        invoice_number="INV-1",
        currency="USD",
        total_amount=100.0,
        total_net_weight_kg=18100.0,
        hs_code="0303.89",
        port_of_loading="POL",
        port_of_discharge="POD",
    )
    result = build_response([doc1, doc2], "rules_fallback")
    assert result.summary.status != "ready_for_review"
    assert result.summary.status == "needs_attention"


def test_exported_json_contains_checklist_statuses():
    with TestClient(app) as client:
        f1 = io.BytesIO(
            b"COMMERCIAL INVOICE\nExporter: Marine\nBuyer: Ocean\nInvoice No: INV-10\nNet Weight: 18000 kg"
        )
        f2 = io.BytesIO(
            b"PACKING LIST\nExporter: Marine\nBuyer: Ocean\nInvoice No: INV-10\nNet Weight: 18100 kg"
        )
        resp = client.post(
            "/api/analyze",
            files=[
                ("files", ("inv.txt", f1.getvalue(), "text/plain")),
                ("files", ("pack.txt", f2.getvalue(), "text/plain")),
            ],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data
        assert "checklist" in data["summary"]
        chk_weights = next(c for c in data["summary"]["checklist"] if c["id"] == "chk-weights")
        assert chk_weights["status"] == "failed"
        chk_customs = next(c for c in data["summary"]["checklist"] if c["id"] == "chk-customs")
        assert chk_customs["status"] == "needs_review"


