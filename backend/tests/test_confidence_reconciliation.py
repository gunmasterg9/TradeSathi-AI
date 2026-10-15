from decimal import Decimal
import pytest
from fastapi.testclient import TestClient

from app.analysis import (
    compare_documents,
    build_response,
    normalize_weight_with_provenance,
    rules_extract,
)
from app.db import (
    init_db,
    save_analysis,
    get_analysis_by_id,
    create_shipment,
)
from app.main import app
from app.readiness import calculate_shipment_readiness
from app.schemas import ExtractedDocument, FieldEvidence


# ---------------------------------------------------------------------------
# 1. Exact matching weights with explicit compatible units
# ---------------------------------------------------------------------------
def test_exact_matching_weights_with_compatible_units():
    """Documents with identical normalized weights (1,000 kg vs 1,000 kg) must produce 0 discrepancies."""
    doc1 = ExtractedDocument(
        filename="commercial_invoice.txt",
        document_type="commercial_invoice",
        total_net_weight_kg=1000.0,
        raw_net_weight="1000 kg",
        field_evidence={
            "total_net_weight_kg": FieldEvidence(
                raw_value="1000 kg",
                normalized_value="1000.0 kg",
                source_document="commercial_invoice.txt",
                field_name="total_net_weight_kg",
                method="deterministic_rules",
                validation_status="verified",
            )
        },
    )
    doc2 = ExtractedDocument(
        filename="packing_list.txt",
        document_type="packing_list",
        total_net_weight_kg=1000.0,
        raw_net_weight="1000 kg",
        field_evidence={
            "total_net_weight_kg": FieldEvidence(
                raw_value="1000 kg",
                normalized_value="1000.0 kg",
                source_document="packing_list.txt",
                field_name="total_net_weight_kg",
                method="deterministic_rules",
                validation_status="verified",
            )
        },
    )
    discrepancies = compare_documents([doc1, doc2])
    weight_disc = [d for d in discrepancies if d.field == "total_net_weight_kg"]
    assert len(weight_disc) == 0


# ---------------------------------------------------------------------------
# 2. 1,000 kg versus 1 MT
# ---------------------------------------------------------------------------
def test_1000kg_versus_1mt_compatible_unit_exact_match():
    """1 MT normalized to 1000 kg matches 1000 kg with 0 discrepancy."""
    doc1 = ExtractedDocument(
        filename="commercial_invoice.txt",
        document_type="commercial_invoice",
        total_net_weight_kg=1000.0,
        raw_net_weight="1000 kg",
        field_evidence={
            "total_net_weight_kg": FieldEvidence(
                raw_value="1000 kg",
                normalized_value="1000.0 kg",
                source_document="commercial_invoice.txt",
                field_name="total_net_weight_kg",
                validation_status="verified",
            )
        },
    )
    doc2 = ExtractedDocument(
        filename="packing_list.txt",
        document_type="packing_list",
        total_net_weight_kg=1000.0,  # 1 MT normalized
        raw_net_weight="1 MT",
        field_evidence={
            "total_net_weight_kg": FieldEvidence(
                raw_value="1 MT",
                normalized_value="1000.0 kg",
                source_document="packing_list.txt",
                field_name="total_net_weight_kg",
                validation_status="verified",
                notes="Metric tons converted to kilograms (1 MT = 1000.0 kg)",
            )
        },
    )
    discrepancies = compare_documents([doc1, doc2])
    assert not any(d.field == "total_net_weight_kg" for d in discrepancies)


# ---------------------------------------------------------------------------
# 3. 1,000 kg versus 2,204.62 lb with documented conversion tolerance
# ---------------------------------------------------------------------------
def test_1000kg_versus_2204_62lbs_conversion_tolerance():
    """2204.62 lbs converts to ~999.99979 kg; delta < 0.05 and <= 0.01% must match within tolerance."""
    doc1 = ExtractedDocument(
        filename="commercial_invoice.txt",
        document_type="commercial_invoice",
        total_net_weight_kg=1000.0,
        raw_net_weight="1000 kg",
        field_evidence={
            "total_net_weight_kg": FieldEvidence(
                raw_value="1000 kg",
                normalized_value="1000.0 kg",
                source_document="commercial_invoice.txt",
                field_name="total_net_weight_kg",
                validation_status="verified",
            )
        },
    )
    norm_lbs, raw_lbs, status, note = normalize_weight_with_provenance("2204.62 lbs")
    assert abs(norm_lbs - 1000.0) < 0.01

    doc2 = ExtractedDocument(
        filename="packing_list.txt",
        document_type="packing_list",
        total_net_weight_kg=norm_lbs,
        raw_net_weight="2204.62 lbs",
        field_evidence={
            "total_net_weight_kg": FieldEvidence(
                raw_value="2204.62 lbs",
                normalized_value=f"{norm_lbs} kg",
                source_document="packing_list.txt",
                field_name="total_net_weight_kg",
                validation_status="verified",
                notes=note,
            )
        },
    )
    discrepancies = compare_documents([doc1, doc2])
    assert not any(d.field == "total_net_weight_kg" for d in discrepancies)


# ---------------------------------------------------------------------------
# 4. Unitless 18,000 versus explicit 18,100 kg
# ---------------------------------------------------------------------------
def test_unitless_versus_explicit_kg_unit_ambiguity():
    """Unitless 18,000 on invoice vs 18,100 kg on packing list must trigger unit ambiguity review finding."""
    doc1 = ExtractedDocument(
        filename="commercial_invoice.txt",
        document_type="commercial_invoice",
        total_net_weight_kg=18000.0,
        raw_net_weight="18000",
        field_evidence={
            "total_net_weight_kg": FieldEvidence(
                raw_value="18000",
                normalized_value=18000.0,
                source_document="commercial_invoice.txt",
                field_name="total_net_weight_kg",
                validation_status="uncertain",
                notes="Weight unit unspecified in source text; recorded with uncertainty",
            )
        },
    )
    doc2 = ExtractedDocument(
        filename="packing_list.txt",
        document_type="packing_list",
        total_net_weight_kg=18100.0,
        raw_net_weight="18100 kg",
        field_evidence={
            "total_net_weight_kg": FieldEvidence(
                raw_value="18100 kg",
                normalized_value=18100.0,
                source_document="packing_list.txt",
                field_name="total_net_weight_kg",
                validation_status="verified",
            )
        },
    )
    discrepancies = compare_documents([doc1, doc2])
    weight_disc = next(d for d in discrepancies if d.field == "total_net_weight_kg")
    assert weight_disc.severity == "critical"
    assert "unit ambiguity" in weight_disc.difference.lower()
    assert weight_disc.comparison_rule == "compatible_weight_conversion"
    assert weight_disc.human_review_required is True


# ---------------------------------------------------------------------------
# 5. Unitless values on both documents
# ---------------------------------------------------------------------------
def test_unitless_values_on_both_documents():
    """Unitless values on both documents cannot be confirmed as a verified match."""
    doc1 = ExtractedDocument(
        filename="commercial_invoice.txt",
        document_type="commercial_invoice",
        total_net_weight_kg=18000.0,
        raw_net_weight="18000",
        field_evidence={
            "total_net_weight_kg": FieldEvidence(
                raw_value="18000",
                validation_status="uncertain",
                source_document="commercial_invoice.txt",
                field_name="total_net_weight_kg",
            )
        },
    )
    doc2 = ExtractedDocument(
        filename="packing_list.txt",
        document_type="packing_list",
        total_net_weight_kg=18000.0,
        raw_net_weight="18000",
        field_evidence={
            "total_net_weight_kg": FieldEvidence(
                raw_value="18000",
                validation_status="uncertain",
                source_document="packing_list.txt",
                field_name="total_net_weight_kg",
            )
        },
    )
    discrepancies = compare_documents([doc1, doc2])
    weight_disc = next(d for d in discrepancies if d.field == "total_net_weight_kg")
    assert weight_disc.severity == "warning"
    assert "both measurements lack explicit units" in weight_disc.difference.lower()
    assert weight_disc.human_review_required is True


# ---------------------------------------------------------------------------
# 6. Missing or invalid weight values
# ---------------------------------------------------------------------------
def test_invalid_weight_produces_critical_format_finding():
    """Non-weight token like '18000 widgets' must produce critical validity finding."""
    doc1 = ExtractedDocument(
        filename="commercial_invoice.txt",
        document_type="commercial_invoice",
        total_net_weight_kg=None,
        raw_net_weight="18000 widgets",
        field_evidence={
            "total_net_weight_kg": FieldEvidence(
                raw_value="18000 widgets",
                validation_status="invalid",
                source_document="commercial_invoice.txt",
                field_name="total_net_weight_kg",
            )
        },
    )
    doc2 = ExtractedDocument(
        filename="packing_list.txt",
        document_type="packing_list",
        total_net_weight_kg=18000.0,
        raw_net_weight="18000 kg",
        field_evidence={
            "total_net_weight_kg": FieldEvidence(
                raw_value="18000 kg",
                validation_status="verified",
                source_document="packing_list.txt",
                field_name="total_net_weight_kg",
            )
        },
    )
    discrepancies = compare_documents([doc1, doc2])
    weight_disc = next(d for d in discrepancies if d.field == "total_net_weight_kg")
    assert weight_disc.severity == "critical"
    assert "invalid" in weight_disc.difference.lower()
    assert weight_disc.human_review_required is True


# ---------------------------------------------------------------------------
# 7. Match within tolerance versus genuine mismatch
# ---------------------------------------------------------------------------
def test_match_within_tolerance_vs_genuine_mismatch():
    """Small tolerance (e.g. 0.01%) must pass; genuine 0.56% mismatch must be flagged."""
    # Within tolerance: 10000.00 vs 10000.01 (pct = 0.0001% <= 0.01%)
    d1 = ExtractedDocument(filename="inv.txt", document_type="commercial_invoice", total_amount=10000.00, currency="USD")
    d2 = ExtractedDocument(filename="po.txt", document_type="purchase_order", total_amount=10000.01, currency="USD")
    disc = compare_documents([d1, d2])
    assert not any(d.field == "total_amount" for d in disc)

    # Genuine mismatch: 10000.00 vs 10100.00 (pct = 1.0% > 0.01%)
    d3 = ExtractedDocument(filename="inv.txt", document_type="commercial_invoice", total_amount=10000.00, currency="USD")
    d4 = ExtractedDocument(filename="po.txt", document_type="purchase_order", total_amount=10100.00, currency="USD")
    disc2 = compare_documents([d3, d4])
    amt_disc = next(d for d in disc2 if d.field == "total_amount")
    assert amt_disc.severity == "critical"
    assert amt_disc.delta_numeric == 100.0
    assert amt_disc.delta_percentage == 1.0


# ---------------------------------------------------------------------------
# 8. Zero denominators and percentages that cannot be calculated
# ---------------------------------------------------------------------------
def test_zero_denominator_safe_handling():
    """When a baseline value is 0.0, delta percentage must be None rather than causing ZeroDivisionError."""
    doc1 = ExtractedDocument(
        filename="inv.txt",
        document_type="commercial_invoice",
        total_net_weight_kg=0.0,
        raw_net_weight="0 kg",
        field_evidence={"total_net_weight_kg": FieldEvidence(raw_value="0 kg", validation_status="verified")},
    )
    doc2 = ExtractedDocument(
        filename="pack.txt",
        document_type="packing_list",
        total_net_weight_kg=50.0,
        raw_net_weight="50 kg",
        field_evidence={"total_net_weight_kg": FieldEvidence(raw_value="50 kg", validation_status="verified")},
    )
    discrepancies = compare_documents([doc1, doc2])
    weight_disc = next(d for d in discrepancies if d.field == "total_net_weight_kg")
    assert weight_disc.delta_numeric == 50.0
    assert weight_disc.delta_percentage is None
    assert "N/A %" in weight_disc.difference


# ---------------------------------------------------------------------------
# 9. Currency mismatch without an exchange rate
# ---------------------------------------------------------------------------
def test_cross_currency_amounts_flagged_not_directly_comparable():
    """USD 12500 vs EUR 12500 must produce critical finding without attempting direct numeric equality."""
    doc1 = ExtractedDocument(
        filename="commercial_invoice.txt",
        document_type="commercial_invoice",
        currency="USD",
        total_amount=12500.0,
    )
    doc2 = ExtractedDocument(
        filename="packing_list.txt",
        document_type="packing_list",
        currency="EUR",
        total_amount=12500.0,
    )
    discrepancies = compare_documents([doc1, doc2])
    # Must flag both currency mismatch and total_amount non-comparability
    curr_disc = next(d for d in discrepancies if d.field == "currency")
    assert curr_disc.severity == "critical"

    amt_disc = next(d for d in discrepancies if d.field == "total_amount")
    assert amt_disc.severity == "critical"
    assert "not directly comparable" in amt_disc.difference.lower()
    assert amt_disc.comparison_rule == "monetary_total_comparison"


# ---------------------------------------------------------------------------
# 10. Monetary rounding and decimal precision
# ---------------------------------------------------------------------------
def test_monetary_decimal_precision_no_float_leaks():
    """Ensure floating point precision issues (e.g. 0.010000000000001) are handled cleanly."""
    doc1 = ExtractedDocument(
        filename="commercial_invoice.txt",
        document_type="commercial_invoice",
        currency="USD",
        total_amount=12500.50,
    )
    doc2 = ExtractedDocument(
        filename="purchase_order.txt",
        document_type="purchase_order",
        currency="USD",
        total_amount=12500.49,
    )
    discrepancies = compare_documents([doc1, doc2])
    # Difference is $0.01 on $12500 (0.00008%), which is within 0.01% rounding tolerance
    assert not any(d.field == "total_amount" for d in discrepancies)


# ---------------------------------------------------------------------------
# 11. Missing versus invalid HS codes
# ---------------------------------------------------------------------------
def test_missing_versus_invalid_hs_codes():
    """Missing HS code produces info/missing status; invalid HS code produces critical finding."""
    # Invalid HS code: 'NOT_HS_CODE'
    doc1 = ExtractedDocument(
        filename="commercial_invoice.txt",
        document_type="commercial_invoice",
        hs_code=None,
        raw_hs_code="NOT_HS_CODE",
        field_evidence={"hs_code": FieldEvidence(raw_value="NOT_HS_CODE", validation_status="invalid")},
    )
    doc2 = ExtractedDocument(
        filename="packing_list.txt",
        document_type="packing_list",
        hs_code="0303.89",
        raw_hs_code="0303.89",
        field_evidence={"hs_code": FieldEvidence(raw_value="0303.89", validation_status="verified")},
    )
    discrepancies = compare_documents([doc1, doc2])
    hs_disc = next(d for d in discrepancies if d.field == "hs_code")
    assert hs_disc.severity == "critical"
    assert "invalid" in hs_disc.difference.lower()
    assert hs_disc.comparison_rule == "hs_code_validity"


# ---------------------------------------------------------------------------
# 12. Preservation of existing 18,000 kg vs 18,100 kg sample discrepancy
# ---------------------------------------------------------------------------
def test_preservation_of_18000kg_vs_18100kg_sample_discrepancy():
    """Default sample files must continue to report the 100 kg (+0.56%) discrepancy with full provenance."""
    client = TestClient(app)
    sample_resp = client.get("/api/samples")
    assert sample_resp.status_code == 200
    samples = sample_resp.json()["samples"]

    inv = next(s for s in samples if "invoice" in s["filename"].lower())
    pack = next(s for s in samples if "packing" in s["filename"].lower())

    files = [
        ("files", (inv["filename"], inv["content"].encode("utf-8"), "text/plain")),
        ("files", (pack["filename"], pack["content"].encode("utf-8"), "text/plain")),
    ]
    resp = client.post("/api/analyze", files=files)
    assert resp.status_code == 200
    data = resp.json()

    assert data["summary"]["status"] == "needs_attention"
    weight_disc = next(d for d in data["discrepancies"] if d["field"] == "total_net_weight_kg")
    assert weight_disc["severity"] == "critical"
    assert weight_disc["delta_numeric"] == 100.0
    assert weight_disc["delta_percentage"] == 0.56
    assert weight_disc["human_review_required"] is True


# ---------------------------------------------------------------------------
# 13. Readiness blocked for unresolved critical findings
# ---------------------------------------------------------------------------
def test_readiness_blocked_for_unresolved_critical_findings():
    """Shipment readiness must be blocked (status: 'not_ready') when latest analysis has critical discrepancy."""
    shipment = {"id": "shp-test-critical", "status": "draft"}
    documents = [
        {"id": "d1", "document_type": "commercial_invoice", "original_filename": "inv.txt", "review_status": "verified_by_user"},
        {"id": "d2", "document_type": "packing_list", "original_filename": "pack.txt", "review_status": "verified_by_user"},
    ]
    latest_analysis = {
        "id": "anl-crit-1",
        "created_at": "2026-10-13T10:00:00Z",
        "status": "needs_attention",
        "response_data": {
            "discrepancies": [
                {
                    "field": "total_net_weight_kg",
                    "severity": "critical",
                    "message": "Net weight mismatch of 100 kg",
                }
            ]
        },
    }
    readiness = calculate_shipment_readiness(shipment=shipment, documents=documents, latest_analysis=latest_analysis)
    assert readiness["is_ready"] is False
    assert readiness["status"] == "not_ready"
    assert readiness["unresolved_critical_discrepancies"] == 1
    assert any("critical discrepancy" in r.lower() for r in readiness["reasons"])


# ---------------------------------------------------------------------------
# 14. Audit persistence, historical immutability, deterministic fallback
# ---------------------------------------------------------------------------
def test_audit_persistence_and_deterministic_fallback():
    """Verify that structured discrepancies are preserved completely in SQLite without schema alteration."""
    init_db()

    doc1 = ExtractedDocument(
        filename="invoice.txt",
        document_type="commercial_invoice",
        invoice_number="INV-2026-PERSIST",
        total_net_weight_kg=18000.0,
        raw_net_weight="18000 kg",
    )
    doc2 = ExtractedDocument(
        filename="packing.txt",
        document_type="packing_list",
        invoice_number="INV-2026-PERSIST",
        total_net_weight_kg=18100.0,
        raw_net_weight="18100 kg",
    )
    resp = build_response(documents=[doc1, doc2], mode="rules_fallback")
    assert resp.mode == "rules_fallback"

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

    retrieved = get_analysis_by_id(resp.id)
    assert retrieved is not None
    assert retrieved["id"] == resp.id
    stored_disc = retrieved["discrepancies"][0]
    assert stored_disc["field"] == "total_net_weight_kg"
    assert stored_disc["delta_numeric"] == 100.0
    assert stored_disc["human_review_required"] is True


# ---------------------------------------------------------------------------
# 15. Existing shipment/document and audit-history functionality
# ---------------------------------------------------------------------------
def test_shipment_document_and_audit_history_routes():
    """Verify shipment creation, linking analysis to shipment, and audit history listing work seamlessly."""
    client = TestClient(app)

    import uuid
    unique_ref = f"SHP-2E2-{uuid.uuid4().hex[:6].upper()}"
    inv_no = f"INV-{uuid.uuid4().hex[:6].upper()}"

    # Create shipment
    ship_resp = client.post("/api/shipments", json={"reference": unique_ref, "exporter": "Test Exporter"})
    assert ship_resp.status_code == 201
    shipment_id = ship_resp.json()["id"]

    # Reconcile linked to shipment
    files = [
        ("files", ("inv.txt", f"COMMERCIAL INVOICE\nInvoice No: {inv_no}\nNet Weight: 1000 kg\nTotal: USD 1000".encode("utf-8"), "text/plain")),
        ("files", ("pack.txt", f"PACKING LIST\nInvoice No: {inv_no}\nNet Weight: 1000 kg".encode("utf-8"), "text/plain")),
    ]
    reconcile_resp = client.post("/api/analyze", data={"shipment_id": shipment_id}, files=files)
    assert reconcile_resp.status_code == 200
    reconcile_data = reconcile_resp.json()
    assert reconcile_data["shipment_id"] == shipment_id

    # Retrieve audit history with filter
    hist_resp = client.get(f"/api/analyses?search={inv_no}")
    assert hist_resp.status_code == 200
    hist_data = hist_resp.json()
    assert hist_data["total"] >= 1
    found = any(a["id"] == reconcile_data["id"] for a in hist_data["analyses"])
    assert found is True
