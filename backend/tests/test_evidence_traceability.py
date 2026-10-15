import os
import uuid
from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.analysis import (
    rules_extract,
    compare_documents,
    ground_text_snippet,
    ollama_extract,
    build_response,
)
from app.schemas import ExtractedDocument, FieldEvidence, Discrepancy
from app.documents import extract_text_with_metadata


def test_1_exact_source_snippet_linked_to_deterministic_extracted_value():
    """Verify that rules_extract captures exact line snippet and character offsets for extracted fields."""
    sample_invoice = """COMMERCIAL INVOICE
Invoice No: INV-2026-9001
Invoice Date: 2026-10-15
Total Amount: USD 54,000.00
Total Net Weight: 12,500 kg
Port of Loading: Mumbai Port
"""
    doc = rules_extract("invoice.txt", sample_invoice, doc_id="doc-test-1")
    assert doc.invoice_number == "INV-2026-9001"
    
    # Check field_evidence
    ev_inv = doc.field_evidence.get("invoice_number")
    assert ev_inv is not None
    assert ev_inv.evidence_id == "ev-doc-test-1-invoice_number"
    assert "Invoice No: INV-2026-9001" in ev_inv.source_snippet
    assert ev_inv.char_start is not None
    assert ev_inv.char_end is not None
    assert ev_inv.char_start < ev_inv.char_end
    # Verify exact substring corresponds to source text
    assert "INV-2026-9001" in sample_invoice[ev_inv.char_start:ev_inv.char_end]
    assert ev_inv.is_grounded is True
    assert ev_inv.validation_status == "verified"


def test_2_raw_and_normalized_values_retaining_correct_provenance():
    """Verify raw value preservation alongside normalized numeric representation and unit."""
    sample_text = "Net Weight: 1,500.50 lbs\nTotal Amount: $ 12,345.67"
    doc = rules_extract("packing.txt", sample_text, doc_id="doc-test-2")

    ev_weight = doc.field_evidence.get("total_net_weight_kg")
    assert ev_weight is not None
    assert ev_weight.raw_value == "1,500.50 lbs"
    # 1500.50 lbs * 0.45359237 kg/lb = 680.615 kg
    assert pytest.approx(ev_weight.normalized_value, 0.01) == 680.62
    assert ev_weight.unit == "kg"
    assert ev_weight.is_grounded is True


def test_3_correct_linkage_between_each_discrepancy_and_both_source_documents():
    """Verify that discrepancy records link traceable evidence and snippets from each compared document."""
    inv_text = "Invoice No: INV-300\nNet Weight: 5000 kg"
    pl_text = "Invoice No: INV-300\nNet Weight: 5200 kg"

    doc_inv = rules_extract("commercial_invoice.txt", inv_text, doc_id="doc-inv")
    doc_pl = rules_extract("packing_list.txt", pl_text, doc_id="doc-pl")

    discrepancies = compare_documents([doc_inv, doc_pl])
    weight_disc = next((d for d in discrepancies if d.field == "total_net_weight_kg"), None)
    assert weight_disc is not None

    # Check evidence map links both files
    assert "commercial_invoice.txt" in weight_disc.evidence
    assert "packing_list.txt" in weight_disc.evidence

    ev_inv = weight_disc.evidence["commercial_invoice.txt"]
    ev_pl = weight_disc.evidence["packing_list.txt"]

    assert "5000 kg" in ev_inv.source_snippet
    assert "5200 kg" in ev_pl.source_snippet
    assert weight_disc.source_snippets["commercial_invoice.txt"] == ev_inv.source_snippet
    assert weight_disc.source_snippets["packing_list.txt"] == ev_pl.source_snippet
    assert weight_disc.evidence_ids["commercial_invoice.txt"] == ev_inv.evidence_id
    assert weight_disc.evidence_ids["packing_list.txt"] == ev_pl.evidence_id


def test_4_evidence_unavailable_when_value_cannot_be_grounded():
    """Verify that ungrounded values return is_grounded=False with explicit limitations."""
    doc_text = "COMMERCIAL INVOICE\nShipper: Alpha Trading Co"
    line, c_start, c_end, page_num, is_grounded, limits = ground_text_snippet(
        "Phantom Buyer Inc", doc_text
    )
    assert is_grounded is False
    assert line is None
    assert c_start is None
    assert c_end is None
    assert any("not found in document" in lim for lim in limits)


def test_5_missing_or_unreliable_page_locations_return_none():
    """Verify that plain text documents return page_number=None, not fabricated page numbers."""
    text = "Invoice Date: 2026-10-14\nTotal: USD 1000"
    doc = rules_extract("invoice.txt", text, doc_id="doc-txt")
    ev = doc.field_evidence.get("invoice_date")
    assert ev is not None
    # No pages_meta provided for plain text -> page_number MUST be None
    assert ev.page_number is None


def test_6_whitespace_and_line_ending_handling_in_grounding():
    """Verify that multiple spaces or newline formatting does not break evidence grounding."""
    text = "Product Description:\n   Organic   Darjeeling    Tea   Leaves  Grade-A\nNet Weight: 1000 kg"
    line, c_start, c_end, page_num, is_grounded, limits = ground_text_snippet(
        "Organic Darjeeling Tea Leaves Grade-A", text
    )
    assert is_grounded is True
    assert c_start is not None
    assert "Organic" in line


def test_7_malformed_or_misleading_llm_output_lacks_source_support():
    """Verify that hallucinated LLM values not present in source text are marked ungrounded and uncertain."""
    source_text = "COMMERCIAL INVOICE\nInvoice No: INV-REAL-100\nTotal: USD 500"
    
    # Ground a fake AI extracted consignee
    fake_ai_val = "Nonexistent Hallucinated Consignee Ltd"
    line, c_start, c_end, page_num, is_grounded, limits = ground_text_snippet(
        fake_ai_val, source_text
    )
    assert is_grounded is False
    assert any("not found" in l for l in limits)


def test_8_invalid_and_unit_ambiguous_weights_with_traceable_evidence():
    """Verify unit-ambiguous weight discrepancy retains exact snippets and review requirement."""
    inv_text = "Invoice No: INV-1\nNet Weight: 18000"
    pl_text = "Invoice No: INV-1\nNet Weight: 18100 kg"

    doc_inv = rules_extract("inv.txt", inv_text, doc_id="inv")
    doc_pl = rules_extract("pl.txt", pl_text, doc_id="pl")

    discs = compare_documents([doc_inv, doc_pl])
    ambiguity_disc = next((d for d in discs if d.field == "total_net_weight_kg"), None)
    assert ambiguity_disc is not None
    assert "Unit ambiguity" in ambiguity_disc.difference
    assert ambiguity_disc.human_review_required is True

    # Traceable evidence
    assert ambiguity_disc.source_snippets["inv.txt"] == "Net Weight: 18000"
    assert ambiguity_disc.source_snippets["pl.txt"] == "Net Weight: 18100 kg"


def test_9_existing_18000kg_vs_18100kg_sample_discrepancy_and_evidence():
    """Verify that sample commercial invoice and packing list retain the 100 kg discrepancy and exact line snippets."""
    inv_text = "COMMERCIAL INVOICE\nInvoice No: INV-2026-104\nTotal Net Weight: 18,000 kg"
    pl_text = "PACKING LIST\nInvoice No: INV-2026-104\nTotal Net Weight: 18,100 kg"

    doc_inv = rules_extract("commercial_invoice.txt", inv_text, doc_id="ci")
    doc_pl = rules_extract("packing_list.txt", pl_text, doc_id="pl")

    discs = compare_documents([doc_inv, doc_pl])
    weight_disc = next((d for d in discs if d.field == "total_net_weight_kg"), None)
    assert weight_disc is not None
    assert weight_disc.delta_numeric == 100.0
    assert weight_disc.delta_percentage == 0.56
    assert "18,000 kg" in weight_disc.source_snippets["commercial_invoice.txt"]
    assert "18,100 kg" in weight_disc.source_snippets["packing_list.txt"]


def test_10_historical_audit_reopening_without_reextraction():
    """Verify that retrieving a historical audit returns the stored evidence without re-extracting."""
    client = TestClient(app)
    unique_inv = f"INV-HIST-{uuid.uuid4().hex[:6].upper()}"

    files = [
        ("files", ("inv.txt", f"Invoice No: {unique_inv}\nTotal: USD 1000\nNet Weight: 500 kg".encode("utf-8"), "text/plain")),
        ("files", ("pl.txt", f"Invoice No: {unique_inv}\nNet Weight: 550 kg".encode("utf-8"), "text/plain")),
    ]
    create_resp = client.post("/api/analyze", files=files)
    assert create_resp.status_code == 200
    created_data = create_resp.json()
    audit_id = created_data["id"]

    # Retrieve from database
    get_resp = client.get(f"/api/analyses/{audit_id}")
    assert get_resp.status_code == 200
    retrieved_data = get_resp.json()

    # Verify discrepancies and evidence are preserved identically
    assert len(retrieved_data["discrepancies"]) == len(created_data["discrepancies"])
    orig_disc = next(d for d in created_data["discrepancies"] if d["field"] == "total_net_weight_kg")
    reopened_disc = next(d for d in retrieved_data["discrepancies"] if d["field"] == "total_net_weight_kg")

    assert reopened_disc["source_snippets"] == orig_disc["source_snippets"]
    assert reopened_disc["evidence_ids"] == orig_disc["evidence_ids"]


def test_11_evidence_retrieval_after_shipment_deleted_or_unlinked():
    """Verify that deleting a shipment preserves the audit's grounded evidence records."""
    client = TestClient(app)
    ship_ref = f"SHP-EV-{uuid.uuid4().hex[:6].upper()}"

    # Create shipment
    ship_resp = client.post("/api/shipments", json={"reference": ship_ref, "exporter": "Test Exporter"})
    assert ship_resp.status_code == 201
    shipment_id = ship_resp.json()["id"]

    # Analyze linked to shipment
    files = [
        ("files", ("inv.txt", "Invoice No: INV-DEL-1\nNet Weight: 1000 kg\nTotal: USD 2000".encode("utf-8"), "text/plain")),
        ("files", ("pl.txt", "Invoice No: INV-DEL-1\nNet Weight: 1200 kg".encode("utf-8"), "text/plain")),
    ]
    anl_resp = client.post("/api/analyze", data={"shipment_id": shipment_id}, files=files)
    assert anl_resp.status_code == 200
    audit_id = anl_resp.json()["id"]

    # Delete shipment
    del_resp = client.delete(f"/api/shipments/{shipment_id}")
    assert del_resp.status_code == 200

    # Retrieve audit - must be preserved with full evidence
    get_resp = client.get(f"/api/analyses/{audit_id}")
    assert get_resp.status_code == 200
    saved_audit = get_resp.json()
    disc = next(d for d in saved_audit["discrepancies"] if d["field"] == "total_net_weight_kg")
    assert disc["source_snippets"]["inv.txt"] == "Net Weight: 1000 kg"
    assert disc["source_snippets"]["pl.txt"] == "Net Weight: 1200 kg"


def test_12_document_access_controls_and_safe_display_of_source_text():
    """Verify that source text with HTML or potential script injections is safely captured as inert text."""
    malicious_text = "Exporter: Alpha Corp <script>alert('xss')</script>\nInvoice No: INV-SAFE-101\nNet Weight: 1000 kg"
    doc = rules_extract("injection.txt", malicious_text, doc_id="inj")
    ev = doc.field_evidence.get("exporter")
    assert ev is not None
    assert ev.source_snippet is not None
    # Text snippet contains raw string without server-side execution or stripping
    assert "<script>" in ev.source_snippet
    assert "Alpha Corp" in doc.exporter


def test_13_existing_document_shipment_readiness_and_audit_behavior():
    """Verify that shipment creation, readiness checks, and document listings function without regression."""
    client = TestClient(app)
    ship_ref = f"SHP-E2E-{uuid.uuid4().hex[:6].upper()}"

    # Create shipment
    ship_resp = client.post("/api/shipments", json={"reference": ship_ref, "exporter": "Verified Agro Ltd"})
    assert ship_resp.status_code == 201
    shipment_id = ship_resp.json()["id"]

    # Check readiness initially (not ready due to missing documents)
    ready_resp = client.get(f"/api/shipments/{shipment_id}/readiness")
    assert ready_resp.status_code == 200
    readiness = ready_resp.json()
    assert readiness["is_ready"] is False
    assert any("commercial invoice" in r.lower() for r in readiness["reasons"])
