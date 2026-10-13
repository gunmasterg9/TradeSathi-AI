from typing import Any


DEFAULT_REQUIRED_DOCUMENTS = [
    {
        "type": "commercial_invoice",
        "title": "Commercial Invoice",
        "required": True,
        "description": "Proposed default: Commercial Invoice for value, currency, terms, and line item verification.",
    },
    {
        "type": "packing_list",
        "title": "Packing List",
        "required": True,
        "description": "Proposed default: Packing List for cargo weight, package count, and packaging specifications.",
    },
]


def calculate_shipment_readiness(
    shipment: dict[str, Any],
    documents: list[dict[str, Any]],
    latest_analysis: dict[str, Any] | None = None,
    required_specs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Compute shipment export readiness from explicit, explainable operational rules.

    Readiness requires:
    1. All proposed default required export documents attached.
    2. Zero missing required documents.
    3. At least one cross-document reconciliation audit executed.
    4. Zero unresolved critical discrepancies in the latest audit.
    5. All attached documents reviewed and verified by human operator (or marked N/A).

    Note: Readiness indicates local operational and paperwork reconciliation completeness.
    It NEVER certifies customs compliance, statutory export clearance, or legal authenticity.
    """
    specs = required_specs if required_specs is not None else DEFAULT_REQUIRED_DOCUMENTS
    shipment_id = shipment.get("id", "")
    planned_date = shipment.get("planned_shipment_date")

    # Map attached documents by document_type
    docs_by_type: dict[str, list[dict[str, Any]]] = {}
    for doc in documents:
        dtype = doc.get("document_type", "unknown")
        docs_by_type.setdefault(dtype, []).append(doc)

    checklist: list[dict[str, Any]] = []
    missing_docs: list[str] = []

    # Evaluate required document checklist items
    for spec in specs:
        spec_type = spec["type"]
        spec_title = spec["title"]
        is_required = spec.get("required", True)
        matching_docs = docs_by_type.get(spec_type, [])

        if not matching_docs:
            if is_required:
                missing_docs.append(spec_title)
            checklist.append({
                "id": f"chk-{spec_type}",
                "title": spec_title,
                "document_type": spec_type,
                "required": is_required,
                "status": "missing",
                "attached_document_id": None,
                "attached_filename": None,
                "detail": f"{spec_title} is missing. Required for export dispatch review.",
            })
        else:
            # Determine aggregate status for this required document type
            # Preference: verified_by_user > needs_review > not_applicable > uploaded
            primary_doc = matching_docs[0]
            statuses = [d.get("review_status", "uploaded") for d in matching_docs]

            if any(s == "needs_review" for s in statuses):
                eff_status = "needs_review"
                flagged_doc = next(d for d in matching_docs if d.get("review_status") == "needs_review")
                detail = f"Requires human review: {flagged_doc.get('original_filename')} (note: {flagged_doc.get('review_notes') or 'Unspecified review reason'})."
            elif any(s == "verified_by_user" for s in statuses):
                eff_status = "verified_by_user"
                v_doc = next(d for d in matching_docs if d.get("review_status") == "verified_by_user")
                detail = f"Verified by {v_doc.get('last_reviewed_by') or 'user'} on {v_doc.get('last_reviewed_at') or 'record'}."
            elif all(s == "not_applicable" for s in statuses):
                eff_status = "not_applicable"
                detail = "Marked not applicable by user."
            else:
                eff_status = "uploaded"
                detail = f"Uploaded as {primary_doc.get('original_filename')}. Awaiting human verification."

            checklist.append({
                "id": f"chk-{spec_type}",
                "title": spec_title,
                "document_type": spec_type,
                "required": is_required,
                "status": eff_status,
                "attached_document_id": primary_doc.get("id"),
                "attached_filename": primary_doc.get("original_filename"),
                "detail": detail,
            })

    # Evaluate other attached documents not in standard checklist specs
    spec_types = {s["type"] for s in specs}
    for doc in documents:
        dtype = doc.get("document_type", "unknown")
        if dtype not in spec_types:
            r_status = doc.get("review_status", "uploaded")
            checklist.append({
                "id": f"chk-extra-{doc.get('id')}",
                "title": doc.get("original_filename", "Attached Document"),
                "document_type": dtype,
                "required": False,
                "status": r_status,
                "attached_document_id": doc.get("id"),
                "attached_filename": doc.get("original_filename"),
                "detail": f"Supplementary document ({dtype.replace('_', ' ')}). Review status: {r_status.replace('_', ' ')}.",
            })

    # Outstanding human reviews: documents with status 'uploaded' or 'needs_review'
    outstanding_human_reviews = sum(
        1 for d in documents if d.get("review_status") in ("uploaded", "needs_review")
    )

    # Discrepancies and reconciliation status from latest analysis
    last_reconciliation_timestamp = None
    last_reconciliation_id = None
    last_reconciliation_status = None
    unresolved_critical_discrepancies = 0
    unresolved_warning_discrepancies = 0

    if latest_analysis:
        last_reconciliation_id = latest_analysis.get("id")
        last_reconciliation_timestamp = latest_analysis.get("created_at")
        last_reconciliation_status = latest_analysis.get("status")

        # Extract discrepancies if response_data available
        response_json = latest_analysis.get("response_data") or latest_analysis.get("response_json")
        discrepancies: list[dict[str, Any]] = []
        if isinstance(response_json, dict):
            discrepancies = response_json.get("discrepancies", [])
        elif isinstance(response_json, str):
            import json
            try:
                parsed = json.loads(response_json)
                discrepancies = parsed.get("discrepancies", [])
            except Exception:
                discrepancies = []

        unresolved_critical_discrepancies = sum(
            1 for d in discrepancies if d.get("severity") == "critical"
        )
        unresolved_warning_discrepancies = sum(
            1 for d in discrepancies if d.get("severity") == "warning"
        )

    # Explainable rules evaluation
    blocking_reasons: list[str] = []
    advisory_notes: list[str] = []

    if missing_docs:
        blocking_reasons.append(
            f"Missing {len(missing_docs)} required document(s): {', '.join(missing_docs)}."
        )

    if not latest_analysis:
        blocking_reasons.append(
            "No cross-document reconciliation audit has been executed for this shipment."
        )
    elif unresolved_critical_discrepancies > 0:
        blocking_reasons.append(
            f"{unresolved_critical_discrepancies} unresolved critical discrepancy(ies) detected in reconciliation audit."
        )

    if outstanding_human_reviews > 0:
        blocking_reasons.append(
            f"{outstanding_human_reviews} attached document(s) have pending human reviews or require verification."
        )

    if unresolved_warning_discrepancies > 0:
        advisory_notes.append(
            f"{unresolved_warning_discrepancies} non-critical advisory warning(s) present in reconciliation."
        )

    # Determine readiness state
    if blocking_reasons:
        status = "not_ready"
        is_ready = False
        reasons = blocking_reasons + advisory_notes
    elif unresolved_warning_discrepancies > 0:
        status = "ready_with_warnings"
        is_ready = True
        reasons = [
            "All required export documents are attached and verified.",
            "Zero critical discrepancies found in document reconciliation.",
        ] + advisory_notes
    else:
        status = "ready"
        is_ready = True
        reasons = [
            "All required export documents are attached and verified by user.",
            "Zero critical discrepancies found across trade documentation.",
            "Operational documentation criteria satisfied.",
        ]

    return {
        "shipment_id": shipment_id,
        "status": status,
        "is_ready": is_ready,
        "uploaded_document_count": len(documents),
        "missing_documents": missing_docs,
        "unresolved_critical_discrepancies": unresolved_critical_discrepancies,
        "unresolved_warning_discrepancies": unresolved_warning_discrepancies,
        "outstanding_human_reviews": outstanding_human_reviews,
        "planned_shipment_date": planned_date,
        "last_reconciliation_timestamp": last_reconciliation_timestamp,
        "last_reconciliation_id": last_reconciliation_id,
        "last_reconciliation_status": last_reconciliation_status,
        "checklist": checklist,
        "reasons": reasons,
        "disclaimer": (
            "Proposed checklist defaults and operational readiness rules for local verification. "
            "This assessment does NOT constitute customs compliance, statutory export clearance, or legal certification."
        ),
    }
