"""TradeSathi AI — Milestone 2E.4 & Milestone 2F
Human Review, Finding Resolution & Decision Audit Trail
Includes server-side evidence verification, legal transition enforcement,
and distinction between independently grounded evidence and operator assertions.
"""

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from .schemas import ReviewActionRequest, ReviewState

VALID_REVIEW_STATES: set[str] = {
    "pending_review",
    "in_review",
    "acknowledged",
    "resolved",
    "escalated",
    "reopened",
}

LEGAL_TRANSITIONS: dict[str, set[str]] = {
    "pending_review": {"in_review", "acknowledged", "escalated", "resolved"},
    "in_review": {"pending_review", "acknowledged", "escalated", "resolved"},
    "acknowledged": {"in_review", "pending_review", "escalated", "resolved"},
    "escalated": {"in_review", "acknowledged", "pending_review", "resolved"},
    "resolved": {"reopened"},
    "reopened": {"in_review", "acknowledged", "escalated", "resolved"},
}

VALID_WEIGHT_UNITS = {"kg", "kgs", "mt", "metric tons", "lbs", "lb", "g", "grams"}


def validate_review_transition(current_state: str, new_state: str) -> None:
    """Validate whether transitioning from current_state to new_state is allowed."""
    cur = current_state or "pending_review"
    if cur not in VALID_REVIEW_STATES:
        cur = "pending_review"

    if new_state not in VALID_REVIEW_STATES:
        raise ValueError(
            f"Invalid review state '{new_state}'. Allowed states: {', '.join(sorted(VALID_REVIEW_STATES))}."
        )

    allowed = LEGAL_TRANSITIONS.get(cur, set())
    if new_state not in allowed:
        raise ValueError(
            f"Illegal review state transition from '{cur}' to '{new_state}'. "
            f"Allowed transitions from '{cur}': {', '.join(sorted(allowed)) if allowed else 'None'}."
        )


def get_valid_evidence_ids_for_analysis(
    finding: dict[str, Any],
    analysis: dict[str, Any] | None = None,
) -> set[str]:
    """Collect all valid evidence IDs and document references belonging to the given finding and parent analysis."""
    valid_ids: set[str] = set()

    # From finding evidence_ids dictionary
    ev_ids = finding.get("evidence_ids")
    if isinstance(ev_ids, dict):
        for val in ev_ids.values():
            if val and str(val).strip():
                valid_ids.add(str(val).strip())

    # From finding evidence objects
    ev_dict = finding.get("evidence")
    if isinstance(ev_dict, dict):
        for ev in ev_dict.values():
            if isinstance(ev, dict) and ev.get("evidence_id"):
                valid_ids.add(str(ev["evidence_id"]).strip())
            elif hasattr(ev, "evidence_id") and ev.evidence_id:
                valid_ids.add(str(ev.evidence_id).strip())

    # From parent analysis documents and discrepancies
    if analysis and isinstance(analysis, dict):
        for doc in analysis.get("documents", []):
            doc_id = doc.get("id") if isinstance(doc, dict) else getattr(doc, "id", None)
            if doc_id:
                valid_ids.add(str(doc_id).strip())
            doc_name = doc.get("filename") if isinstance(doc, dict) else getattr(doc, "filename", None)
            if doc_name:
                valid_ids.add(str(doc_name).strip())

            fe_map = doc.get("field_evidence") if isinstance(doc, dict) else getattr(doc, "field_evidence", {})
            if isinstance(fe_map, dict):
                for fe in fe_map.values():
                    fe_id = fe.get("evidence_id") if isinstance(fe, dict) else getattr(fe, "evidence_id", None)
                    if fe_id and str(fe_id).strip():
                        valid_ids.add(str(fe_id).strip())

        for d in analysis.get("discrepancies", []):
            if isinstance(d, dict):
                d_ev_ids = d.get("evidence_ids")
                if isinstance(d_ev_ids, dict):
                    for val in d_ev_ids.values():
                        if val and str(val).strip():
                            valid_ids.add(str(val).strip())

    return valid_ids


def validate_finding_resolution(
    finding: dict[str, Any],
    req: ReviewActionRequest,
    analysis: dict[str, Any] | None = None,
) -> None:
    """Validate that resolution meets server-side domain integrity requirements for the specific finding type (Gates C & D)."""
    reason = (req.reason or req.notes or "").strip()
    if not reason or len(reason) < 4:
        raise ValueError("Resolution requires a documented reason or explanation (minimum 4 characters).")

    valid_ids = get_valid_evidence_ids_for_analysis(finding, analysis)

    # Validate supporting evidence IDs against real evidence belonging to this analysis
    grounded_evidence_ids: list[str] = []
    if req.supporting_evidence:
        for item in req.supporting_evidence:
            ev_str = str(item).strip()
            if not ev_str:
                raise ValueError("Supporting evidence items cannot be empty strings.")

            if ev_str.startswith("ev-"):
                # Evidence ID pattern: must exist in this analysis if known
                if valid_ids and ev_str not in valid_ids:
                    raise ValueError(
                        f"Invalid or forged supporting evidence ID '{ev_str}'. "
                        "Evidence ID does not exist in the current analysis or finding."
                    )
                if not valid_ids and analysis is not None:
                    raise ValueError(
                        f"Invalid or forged supporting evidence ID '{ev_str}'. "
                        "No verified evidence IDs found in this analysis."
                    )
                if ev_str in valid_ids:
                    grounded_evidence_ids.append(ev_str)
            else:
                # If an arbitrary string without standard file extension is passed as proof of source evidence:
                has_doc_ext = any(ev_str.lower().endswith(ext) for ext in (".pdf", ".txt", ".docx", ".eml"))
                if not has_doc_ext:
                    if valid_ids or analysis is not None:
                        raise ValueError(
                            f"Invalid supporting evidence reference '{ev_str}'. "
                            "Arbitrary strings cannot serve as source evidence. "
                            "Use verified evidence IDs (e.g. 'ev-...') or valid attached document references."
                        )

    field = (finding.get("field") or "").lower()
    label = (finding.get("label") or "").lower()
    difference = (finding.get("difference") or "").lower()
    finding_reason = (finding.get("reason") or "").lower()

    has_evidence = bool(req.supporting_evidence and len(req.supporting_evidence) > 0)
    has_corrected_value = req.corrected_value is not None and str(req.corrected_value).strip() != ""
    has_corrected_unit = bool(req.corrected_unit and req.corrected_unit.strip())

    # 1. Weight Discrepancies
    is_weight = (
        field in ("net_weight", "gross_weight", "total_net_weight_kg", "total_gross_weight_kg")
        or "weight" in label
        or "weight" in field
    )
    if is_weight:
        if not has_evidence and not (has_corrected_value and has_corrected_unit):
            raise ValueError(
                "Resolution of weight discrepancy requires supporting evidence references "
                "or an explicitly documented corrected weight with a valid compatible unit (e.g. kg, lbs, mt)."
            )
        if has_corrected_unit:
            unit_norm = req.corrected_unit.strip().lower()
            if unit_norm not in VALID_WEIGHT_UNITS:
                raise ValueError(
                    f"Invalid weight unit '{req.corrected_unit}'. Compatible units: {', '.join(sorted(VALID_WEIGHT_UNITS))}."
                )

    # 2. Ambiguous Units
    is_ambiguous_unit = "ambiguous" in difference or "ambiguous" in finding_reason or "unit" in label
    if is_ambiguous_unit and not is_weight:
        if not has_evidence and not has_corrected_unit:
            raise ValueError(
                "Resolution of ambiguous measurement unit requires reliable evidence establishing the unit "
                "or an explicit corrected unit."
            )

    # 3. Missing or Invalid HS Code
    is_hs_code = "hs_code" in field or "hs code" in label or "tariff" in label
    if is_hs_code:
        if not has_evidence and not has_corrected_value:
            raise ValueError(
                "Resolution of missing or invalid HS code requires an actual supplied or verified HS code value "
                "or supporting evidence reference."
            )
        if has_corrected_value:
            hs_str = re.sub(r"[\s\.\-]", "", str(req.corrected_value))
            if not hs_str.isdigit() or len(hs_str) < 4:
                raise ValueError(
                    f"Corrected HS code '{req.corrected_value}' is invalid. HS code must contain at least 4 numeric digits."
                )

    # 4. Currency / Amount Mismatch
    is_currency = "currency" in field or "currency" in label or "amount" in field
    if is_currency:
        if not has_evidence and not has_corrected_value and not ("exchange" in reason.lower() or "conversion" in reason.lower()):
            raise ValueError(
                "Resolution of currency or amount mismatch requires comparable currencies, "
                "a corrected value, or a documented conversion/exchange basis in the reason."
            )


def process_review_action(
    analysis_id: str,
    finding: dict[str, Any],
    req: ReviewActionRequest,
    analysis: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Process a review action against a finding.

    Validates legal state transitions, ensures supporting evidence belongs to this analysis,
    and classifies resolution basis (grounded evidence vs operator assertion).

    Returns:
    (updated_finding, review_event)
    """
    cur_state = finding.get("review_status") or "pending_review"
    new_state = req.action

    # Validate state transition
    validate_review_transition(cur_state, new_state)

    # Validate resolution specifics if resolving
    if new_state == "resolved":
        validate_finding_resolution(finding, req, analysis=analysis)
    elif new_state == "reopened":
        reason = (req.reason or req.notes or "").strip()
        if not reason or len(reason) < 4:
            raise ValueError("Reopening a resolved finding requires a documented explanation of why resolution is invalidated (minimum 4 characters).")

    now = datetime.now(timezone.utc).isoformat()
    reviewer_name = (req.reviewer or "Local Operator").strip()

    # Determine resolution basis & operator assertion status (Gate C)
    valid_ids = get_valid_evidence_ids_for_analysis(finding, analysis)
    grounded_ev = [e for e in (req.supporting_evidence or []) if e in valid_ids and str(e).startswith("ev-")]
    has_grounded = len(grounded_ev) > 0
    has_corrections = bool(
        (req.corrected_value is not None and str(req.corrected_value).strip() != "")
        or (req.corrected_unit and req.corrected_unit.strip())
    )
    has_operator_docs = any(not str(e).startswith("ev-") for e in (req.supporting_evidence or []))

    if has_grounded and not has_corrections and not has_operator_docs:
        resolution_basis = "grounded_evidence"
        is_operator_assertion = False
    elif has_grounded and (has_corrections or has_operator_docs):
        resolution_basis = "hybrid"
        is_operator_assertion = True
    else:
        resolution_basis = "operator_assertion"
        is_operator_assertion = True

    # Create immutable review event
    event = {
        "id": f"rev-{uuid.uuid4().hex[:10]}",
        "analysis_id": analysis_id,
        "finding_id": finding["id"],
        "previous_state": cur_state,
        "new_state": new_state,
        "reviewer": reviewer_name,
        "timestamp": now,
        "notes": req.notes.strip() if req.notes else "",
        "reason": req.reason.strip() if req.reason else "",
        "supporting_evidence": req.supporting_evidence or [],
        "corrected_value": req.corrected_value,
        "corrected_unit": req.corrected_unit.strip() if req.corrected_unit else None,
        "source": req.source.strip() if req.source else None,
        "is_operator_assertion": is_operator_assertion,
        "resolution_basis": resolution_basis,
        "is_authenticated": False,  # Single-user local mode: unauthenticated display label
    }

    # Update finding in-place
    finding["review_status"] = new_state
    if new_state == "resolved":
        finding["resolution"] = {
            "resolved_at": now,
            "resolved_by": reviewer_name,
            "reason": req.reason.strip() if req.reason else req.notes.strip(),
            "supporting_evidence": req.supporting_evidence or [],
            "corrected_value": req.corrected_value,
            "corrected_unit": req.corrected_unit.strip() if req.corrected_unit else None,
            "source": req.source.strip() if req.source else None,
            "is_operator_assertion": is_operator_assertion,
            "resolution_basis": resolution_basis,
            "is_authenticated": False,
        }
    elif new_state == "reopened":
        finding["resolution"] = None

    history = finding.get("review_history", [])
    history.append(event)
    finding["review_history"] = history

    return finding, event
