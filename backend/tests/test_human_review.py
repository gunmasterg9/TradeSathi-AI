"""TradeSathi AI — Milestone 2E.4
Human Review, Finding Resolution & Decision Audit Trail Test Suite
"""

import json
import pytest
from fastapi.testclient import TestClient

from backend.app.db import (
    create_shipment,
    get_analysis_by_id,
    get_connection,
    init_db,
    save_analysis,
    set_db_path,
)
from backend.app.main import app
from backend.app.readiness import calculate_shipment_readiness
from backend.app.review import (
    process_review_action,
    validate_finding_resolution,
    validate_review_transition,
)
from backend.app.schemas import ReviewActionRequest

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_isolated_test_db(tmp_path):
    """Use an isolated SQLite test database for every test."""
    test_db = tmp_path / "test_review.db"
    set_db_path(test_db)
    init_db(test_db)
    yield
    # Cleanup


def create_sample_audit_payload(analysis_id: str, shipment_id: str | None = None) -> dict:
    return {
        "id": analysis_id,
        "created_at": "2026-10-13T10:00:00Z",
        "mode": "rules_fallback",
        "model": None,
        "shipment_id": shipment_id,
        "documents": [
            {
                "id": "doc-1",
                "filename": "invoice.txt",
                "document_type": "commercial_invoice",
                "invoice_number": "INV-2026-100",
                "total_net_weight_kg": 18000.0,
                "total_amount": 12500.0,
                "field_evidence": {
                    "total_net_weight_kg": {
                        "evidence_id": "ev-weight-inv",
                        "field_name": "total_net_weight_kg",
                        "document_id": "doc-1",
                        "display_filename": "invoice.txt",
                        "source_snippet": "Net Weight: 18000 kg",
                        "char_start": 10,
                        "char_end": 30,
                        "page_number": None,
                        "raw_value": "18000 kg",
                        "normalized_value": "18000",
                        "unit": "kg",
                        "extraction_method": "rules_deterministic",
                        "provenance_status": "verified",
                        "is_grounded": True,
                    }
                },
            },
            {
                "id": "doc-2",
                "filename": "packing.txt",
                "document_type": "packing_list",
                "invoice_number": "INV-2026-100",
                "total_net_weight_kg": 18100.0,
                "total_amount": 12500.0,
                "field_evidence": {
                    "total_net_weight_kg": {
                        "evidence_id": "ev-weight-pkg",
                        "field_name": "total_net_weight_kg",
                        "document_id": "doc-2",
                        "display_filename": "packing.txt",
                        "source_snippet": "Net Weight: 18100 kg",
                        "char_start": 15,
                        "char_end": 35,
                        "page_number": None,
                        "raw_value": "18100 kg",
                        "normalized_value": "18100",
                        "unit": "kg",
                        "extraction_method": "rules_deterministic",
                        "provenance_status": "verified",
                        "is_grounded": True,
                    }
                },
            },
        ],
        "discrepancies": [
            {
                "id": "fnd-net_weight-1",
                "field": "net_weight",
                "label": "Net Weight",
                "severity": "critical",
                "doc_values": {"invoice.txt": "18000 kg", "packing.txt": "18100 kg"},
                "difference": "Delta: +100 kg (+0.56%)",
                "reason": "Net Weight mismatch (invoice.txt: 18000 kg; packing.txt: 18100 kg)",
                "recommended_action": "Reconcile weights between invoice and packing list",
                "message": "Weight mismatch detected",
                "comparison_rule": "Compatible Weight Conversion",
                "raw_values": {"invoice.txt": "18000.0 kg", "packing.txt": "18100.0 kg"},
                "normalized_values": {"invoice.txt": "18000", "packing.txt": "18100"},
                "units": {"invoice.txt": "kg", "packing.txt": "kg"},
                "provenance_statuses": {"invoice.txt": "verified", "packing.txt": "verified"},
                "source_documents": ["invoice.txt", "packing.txt"],
                "source_snippets": {
                    "invoice.txt": "Net Weight: 18000 kg",
                    "packing.txt": "Net Weight: 18100 kg",
                },
                "evidence_ids": {
                    "invoice.txt": "ev-weight-inv",
                    "packing.txt": "ev-weight-pkg",
                },
                "delta_numeric": 100.0,
                "delta_percentage": 0.56,
                "human_review_required": True,
                "review_status": "pending_review",
            },
            {
                "id": "fnd-hs_code-2",
                "field": "hs_code",
                "label": "HS Code",
                "severity": "warning",
                "doc_values": {"invoice.txt": "0303.89"},
                "difference": "Missing HS Code in packing list",
                "reason": "HS code not declared on packing list",
                "recommended_action": "Verify tariff code",
                "message": "HS code missing in packing list",
                "comparison_rule": "mandatory_field_presence",
                "review_status": "pending_review",
            },
        ],
        "summary": {
            "status": "needs_attention",
            "headline": "Action Required: 1 critical issue(s) detected",
            "summary_text": "Audit completed with 1 critical discrepancy.",
            "checklist": [],
        },
    }


# ===========================================================================
# 1. Legal Review State Transitions & Gate B Rules
# ===========================================================================


def test_legal_state_transitions():
    """Verify legal state transitions succeed and illegal transitions raise ValueError."""
    # Legal transitions
    validate_review_transition("pending_review", "in_review")
    validate_review_transition("pending_review", "acknowledged")
    validate_review_transition("pending_review", "escalated")
    validate_review_transition("in_review", "acknowledged")
    validate_review_transition("acknowledged", "resolved")
    validate_review_transition("resolved", "reopened")
    validate_review_transition("reopened", "in_review")
    validate_review_transition("reopened", "resolved")

    # Illegal transitions
    with pytest.raises(ValueError, match="Illegal review state transition"):
        validate_review_transition("resolved", "acknowledged")

    with pytest.raises(ValueError, match="Illegal review state transition"):
        validate_review_transition("resolved", "in_review")

    with pytest.raises(ValueError, match="Illegal review state transition"):
        validate_review_transition("pending_review", "reopened")

    with pytest.raises(ValueError, match="Invalid review state"):
        validate_review_transition("pending_review", "non_existent_state")


# ===========================================================================
# 2. Gate D Resolution Validation Rules
# ===========================================================================


def test_weight_discrepancy_resolution_requires_evidence_or_unit():
    """Merely clicking resolve with no evidence or unit must be rejected."""
    finding = {
        "id": "fnd-net_weight-1",
        "field": "net_weight",
        "label": "Net Weight",
        "difference": "Delta: +100 kg",
        "reason": "Weight mismatch",
    }

    # Rejection: note alone with no evidence or unit
    req_invalid = ReviewActionRequest(
        action="resolved",
        notes="I think this is fine",
        reason="Looks ok",
    )
    with pytest.raises(ValueError, match="requires supporting evidence references or an explicitly documented corrected weight"):
        validate_finding_resolution(finding, req_invalid)

    # Rejection: invalid weight unit
    req_bad_unit = ReviewActionRequest(
        action="resolved",
        reason="Weighed at gate",
        corrected_value=18000,
        corrected_unit="bananas",
    )
    with pytest.raises(ValueError, match="Invalid weight unit"):
        validate_finding_resolution(finding, req_bad_unit)

    # Success: with supporting evidence reference
    req_valid_ev = ReviewActionRequest(
        action="resolved",
        reason="Certified weighbridge slip confirms 18,000 kg",
        supporting_evidence=["ev-weight-inv", "weighbridge_slip_#402.pdf"],
    )
    validate_finding_resolution(finding, req_valid_ev)

    # Success: with valid corrected value and unit
    req_valid_val = ReviewActionRequest(
        action="resolved",
        reason="Corrected to manifest scale tally",
        corrected_value=18050.0,
        corrected_unit="kg",
    )
    validate_finding_resolution(finding, req_valid_val)


def test_ambiguous_unit_resolution_validation():
    """Ambiguous measurement unit requires establishing the unit."""
    finding = {
        "id": "fnd-ambig-1",
        "field": "cargo_volume",
        "label": "Cargo Volume",
        "difference": "Ambiguous measurement unit detected",
        "reason": "ambiguous unit on invoice",
    }
    req_invalid = ReviewActionRequest(
        action="resolved",
        reason="Resolving this issue",
    )
    with pytest.raises(ValueError, match="requires reliable evidence establishing the unit or an explicit corrected unit"):
        validate_finding_resolution(finding, req_invalid)

    req_valid = ReviewActionRequest(
        action="resolved",
        reason="Standard cubic meters established by carrier bill of lading",
        corrected_unit="cbm",
        supporting_evidence=["cbm_confirmation.pdf"],
    )
    validate_finding_resolution(finding, req_valid)


def test_missing_hs_code_resolution_validation():
    """Resolving missing HS code requires a valid numeric HS code (min 4 digits)."""
    finding = {
        "id": "fnd-hs_code-2",
        "field": "hs_code",
        "label": "HS Code",
        "difference": "Missing HS Code",
        "reason": "HS code not declared",
    }
    # Reject: no code or evidence
    with pytest.raises(ValueError, match="requires an actual supplied or verified HS code"):
        validate_finding_resolution(finding, ReviewActionRequest(action="resolved", reason="Fixed it"))

    # Reject: invalid alphabetic or short code
    with pytest.raises(ValueError, match="HS code must contain at least 4 numeric digits"):
        validate_finding_resolution(
            finding,
            ReviewActionRequest(action="resolved", reason="Added code", corrected_value="12"),
        )

    # Success: valid HS tariff code
    validate_finding_resolution(
        finding,
        ReviewActionRequest(
            action="resolved",
            reason="Tariff schedule 0303.89 verified from exporter catalogue",
            corrected_value="0303.89",
        ),
    )


# ===========================================================================
# 3. Full API Lifecycle & Append-Only Audit Trail
# ===========================================================================


def test_full_review_lifecycle_via_api():
    """Test start review -> acknowledge -> escalate -> resolve -> reopen via HTTP API."""
    analysis_id = "anl-test-rev-001"
    payload = create_sample_audit_payload(analysis_id)
    save_analysis(
        analysis_id=analysis_id,
        mode="rules_fallback",
        model=None,
        status="needs_attention",
        headline="Action Required",
        filenames=["invoice.txt", "packing.txt"],
        discrepancy_count=1,
        response_data=payload,
    )

    finding_id = "fnd-net_weight-1"

    # Step 1: Start review (in_review)
    res1 = client.post(
        f"/api/analyses/{analysis_id}/findings/{finding_id}/review",
        json={"action": "in_review", "reviewer": "Operator Gautam", "notes": "Beginning physical tally review"},
    )
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["finding"]["review_status"] == "in_review"
    assert data1["event"]["previous_state"] == "pending_review"
    assert data1["event"]["new_state"] == "in_review"
    assert data1["event"]["reviewer"] == "Operator Gautam"

    # Step 2: Acknowledge (acknowledged != resolved)
    res2 = client.post(
        f"/api/analyses/{analysis_id}/findings/{finding_id}/review",
        json={"action": "acknowledged", "reviewer": "Operator Gautam", "notes": "Acknowledged 100 kg delta"},
    )
    assert res2.status_code == 200
    assert res2.json()["finding"]["review_status"] == "acknowledged"

    # Step 3: Escalate (escalated != resolved)
    res3 = client.post(
        f"/api/analyses/{analysis_id}/findings/{finding_id}/review",
        json={"action": "escalated", "reviewer": "Operator Gautam", "reason": "Requires port scale calibration check"},
    )
    assert res3.status_code == 200
    assert res3.json()["finding"]["review_status"] == "escalated"

    # Step 4: Resolve with valid evidence and reason
    res4 = client.post(
        f"/api/analyses/{analysis_id}/findings/{finding_id}/review",
        json={
            "action": "resolved",
            "reviewer": "Supervisor Rahul",
            "reason": "Warehouse calibrated weighbridge certificate #9901 confirms 18,000 kg net weight",
            "supporting_evidence": ["ev-weight-inv", "weighbridge_cert_9901.pdf"],
            "corrected_value": 18000.0,
            "corrected_unit": "kg",
        },
    )
    assert res4.status_code == 200
    data4 = res4.json()
    assert data4["finding"]["review_status"] == "resolved"
    assert data4["finding"]["resolution"] is not None
    assert data4["finding"]["resolution"]["resolved_by"] == "Supervisor Rahul"
    assert data4["finding"]["resolution"]["corrected_unit"] == "kg"

    # Machine original finding preserved completely
    assert data4["finding"]["raw_values"] == {"invoice.txt": "18000.0 kg", "packing.txt": "18100.0 kg"}
    assert data4["finding"]["doc_values"] == {"invoice.txt": "18000 kg", "packing.txt": "18100 kg"}
    assert data4["finding"]["comparison_rule"] == "Compatible Weight Conversion"

    # Step 5: Verify append-only history has all 4 events in order
    res_history = client.get(f"/api/analyses/{analysis_id}/findings/{finding_id}/reviews")
    assert res_history.status_code == 200
    reviews = res_history.json()["reviews"]
    assert len(reviews) == 4
    assert [r["new_state"] for r in reviews] == ["in_review", "acknowledged", "escalated", "resolved"]

    # Step 6: Reopen when new evidence contradicts resolution
    res6 = client.post(
        f"/api/analyses/{analysis_id}/findings/{finding_id}/review",
        json={
            "action": "reopened",
            "reviewer": "Inspector Roy",
            "reason": "Discharge port container tare weight inspection shows discrepancies with certificate #9901",
        },
    )
    assert res6.status_code == 200
    data6 = res6.json()
    assert data6["finding"]["review_status"] == "reopened"
    assert data6["finding"]["resolution"] is None

    # Verify event #5 added to history
    res_history_after = client.get(f"/api/analyses/{analysis_id}/findings/{finding_id}/reviews")
    assert len(res_history_after.json()["reviews"]) == 5


# ===========================================================================
# 4. Gate E Readiness Integration & Safety Controls
# ===========================================================================


def test_acknowledgement_and_escalation_do_not_clear_critical_discrepancy():
    """Acknowledged or escalated findings remain unresolved and continue to block readiness."""
    shipment = {"id": "shp-ready-test-1", "reference": "EXP-MUM-2026", "planned_shipment_date": "2026-10-20"}
    docs = [
        {"id": "d1", "document_type": "commercial_invoice", "review_status": "verified_by_user", "original_filename": "inv.txt"},
        {"id": "d2", "document_type": "packing_list", "review_status": "verified_by_user", "original_filename": "pkg.txt"},
    ]

    # Analysis with pending critical discrepancy
    analysis_pending = {
        "id": "anl-ready-1",
        "created_at": "2026-10-13T10:00:00Z",
        "status": "needs_attention",
        "discrepancies": [{"id": "fnd-1", "severity": "critical", "review_status": "pending_review"}],
    }
    readiness1 = calculate_shipment_readiness(shipment, docs, latest_analysis=analysis_pending)
    assert readiness1["is_ready"] is False
    assert readiness1["unresolved_critical_discrepancies"] == 1

    # Analysis with acknowledged critical discrepancy -> STILL BLOCKS READINESS
    analysis_ack = {
        "id": "anl-ready-1",
        "created_at": "2026-10-13T10:00:00Z",
        "status": "needs_attention",
        "discrepancies": [{"id": "fnd-1", "severity": "critical", "review_status": "acknowledged"}],
    }
    readiness2 = calculate_shipment_readiness(shipment, docs, latest_analysis=analysis_ack)
    assert readiness2["is_ready"] is False
    assert readiness2["unresolved_critical_discrepancies"] == 1

    # Analysis with escalated critical discrepancy -> STILL BLOCKS READINESS
    analysis_esc = {
        "id": "anl-ready-1",
        "created_at": "2026-10-13T10:00:00Z",
        "status": "needs_attention",
        "discrepancies": [{"id": "fnd-1", "severity": "critical", "review_status": "escalated"}],
    }
    readiness3 = calculate_shipment_readiness(shipment, docs, latest_analysis=analysis_esc)
    assert readiness3["is_ready"] is False
    assert readiness3["unresolved_critical_discrepancies"] == 1

    # Analysis with resolved critical discrepancy -> UNBLOCKS DISCREPANCY BLOCKER
    analysis_res = {
        "id": "anl-ready-1",
        "created_at": "2026-10-13T10:00:00Z",
        "status": "needs_attention",
        "discrepancies": [{"id": "fnd-1", "severity": "critical", "review_status": "resolved"}],
    }
    readiness4 = calculate_shipment_readiness(shipment, docs, latest_analysis=analysis_res)
    assert readiness4["unresolved_critical_discrepancies"] == 0
    assert readiness4["is_ready"] is True

    # Reopened finding -> RESTORES BLOCKER
    analysis_reopened = {
        "id": "anl-ready-1",
        "created_at": "2026-10-13T10:00:00Z",
        "status": "needs_attention",
        "discrepancies": [{"id": "fnd-1", "severity": "critical", "review_status": "reopened"}],
    }
    readiness5 = calculate_shipment_readiness(shipment, docs, latest_analysis=analysis_reopened)
    assert readiness5["unresolved_critical_discrepancies"] == 1
    assert readiness5["is_ready"] is False


# ===========================================================================
# 5. Historical Audit Reopening with Preserved Review History
# ===========================================================================


def test_historical_audit_reopening_preserves_review_history():
    """Ensure get_analysis_by_id loads the persistent review history without data loss."""
    analysis_id = "anl-hist-rev-099"
    payload = create_sample_audit_payload(analysis_id)
    save_analysis(
        analysis_id=analysis_id,
        mode="rules_fallback",
        model=None,
        status="needs_attention",
        headline="Action Required",
        filenames=["invoice.txt", "packing.txt"],
        discrepancy_count=1,
        response_data=payload,
    )

    finding_id = "fnd-net_weight-1"

    # Add resolution review event
    client.post(
        f"/api/analyses/{analysis_id}/findings/{finding_id}/review",
        json={
            "action": "resolved",
            "reviewer": "Lead Auditor Anita",
            "reason": "Weight reconciliation validated with manufacturer weight slip",
            "supporting_evidence": ["slip.pdf"],
            "corrected_value": 18000,
            "corrected_unit": "kg",
        },
    )

    # Reopen historical audit through API
    reopened = client.get(f"/api/analyses/{analysis_id}").json()
    assert reopened["id"] == analysis_id

    disc = next(d for d in reopened["discrepancies"] if d["id"] == finding_id)
    assert disc["review_status"] == "resolved"
    assert disc["resolution"]["resolved_by"] == "Lead Auditor Anita"
    assert len(disc["review_history"]) == 1
    assert disc["review_history"][0]["new_state"] == "resolved"


def test_unknown_finding_or_analysis_returns_404():
    """Verify clean 404 error responses for invalid analysis or finding identifiers."""
    res_bad_anl = client.post(
        "/api/analyses/non-existent-anl/findings/fnd-1/review",
        json={"action": "in_review"},
    )
    assert res_bad_anl.status_code == 404

    analysis_id = "anl-404-test"
    save_analysis(
        analysis_id=analysis_id,
        mode="rules_fallback",
        model=None,
        status="ready",
        headline="Ready",
        filenames=["a.txt"],
        discrepancy_count=0,
        response_data={"id": analysis_id, "discrepancies": []},
    )

    res_bad_fnd = client.post(
        f"/api/analyses/{analysis_id}/findings/non-existent-finding/review",
        json={"action": "in_review"},
    )
    assert res_bad_fnd.status_code == 404
