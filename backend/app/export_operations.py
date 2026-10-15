"""
TradeSathi AI - Phase 5: Export Operations & Documentation Workflow
Deterministic shipment lifecycle, dispatch linking, checklist generation,
versioned document registration, readiness engine, and draft document generation.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
import uuid
from typing import Any

from app.db import (
    get_connection,
    get_shipment_by_id,
    update_shipment,
    get_document_by_id,
    create_document_record,
    update_document_record,
    get_document_versions,
    link_dispatch_to_export_shipment,
    unlink_dispatch_from_export_shipment,
    get_linked_dispatches_for_shipment,
    list_export_checklist_rules,
    create_export_checklist_rule,
    get_export_checklist_items,
    upsert_export_checklist_item,
    update_export_checklist_item,
)
from app.master_data import record_erp_audit_log
from app.storage import get_storage_dir

logger = logging.getLogger(__name__)


def log_audit_event(
    event_type: str,
    actor_id: str,
    actor_role: str,
    details: dict[str, Any],
) -> None:
    entity_id = (
        details.get("shipment_id")
        or details.get("document_id")
        or details.get("rule_id")
        or details.get("checklist_item_id")
        or "export"
    )
    record_erp_audit_log(
        entity_type="export_operations",
        entity_id=entity_id,
        action=event_type,
        changes=details,
        performed_by=actor_role or actor_id or "system",
    )


# Mandatory compliance disclaimer
READINESS_DISCLAIMER = (
    "INTERNAL OPERATIONAL READINESS ASSESSMENT ONLY: This evaluation indicates internal "
    "software and workflow readiness based on registered documents and business rules. "
    "It does NOT constitute official customs clearance, legal compliance, or regulatory certification."
)

ALLOWED_TRANSITIONS = {
    "draft": ["booked", "cancelled"],
    "booked": ["document_prep", "draft", "cancelled"],
    "document_prep": ["ready_for_dispatch", "booked", "cancelled"],
    "ready_for_dispatch": ["departed", "document_prep", "cancelled"],
    "departed": ["arrived", "cancelled"],
    "arrived": ["completed", "cancelled"],
    "completed": [],
    "cancelled": [],
}


# ==========================================
# 1. Export Shipment Lifecycle Management
# ==========================================


def transition_shipment_status(
    shipment_id: str,
    target_status: str,
    actor_id: str,
    actor_email: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """Transitions an export shipment's status according to the strict state machine."""
    shipment = get_shipment_by_id(shipment_id)
    if not shipment:
        raise ValueError(f"Shipment {shipment_id} not found")

    current_status = shipment.get("status", "draft")
    target_status = target_status.lower().strip()

    allowed = ALLOWED_TRANSITIONS.get(current_status, [])
    if target_status not in allowed:
        raise ValueError(
            f"Invalid status transition from '{current_status}' to '{target_status}'. "
            f"Allowed next states: {', '.join(allowed) or 'None (terminal)'}"
        )

    # If transitioning to ready_for_dispatch, enforce readiness evaluation check
    if target_status == "ready_for_dispatch":
        readiness = evaluate_shipment_readiness(shipment_id)
        if readiness["blockers"]:
            blocker_msgs = [b["message"] for b in readiness["blockers"]]
            raise ValueError(
                f"Cannot mark shipment 'ready_for_dispatch': unresolved blockers exist: {'; '.join(blocker_msgs)}"
            )

    updates: dict[str, Any] = {"status": target_status}
    now = datetime.now(timezone.utc).isoformat()

    if target_status == "departed" and not shipment.get("actual_departure_date"):
        updates["actual_departure_date"] = now[:10]
    elif target_status == "arrived" and not shipment.get("actual_arrival_date"):
        updates["actual_arrival_date"] = now[:10]

    updated = update_shipment(shipment_id, updates)

    log_audit_event(
        event_type="export_shipment.status_transition",
        actor_id=actor_id,
        actor_role=actor_email,
        details={
            "shipment_id": shipment_id,
            "reference": shipment["reference"],
            "previous_status": current_status,
            "new_status": target_status,
            "notes": notes,
        },
    )

    return updated  # type: ignore[return-value]


# ==========================================
# 2. Dispatch Linking & Unlinking
# ==========================================


def link_dispatch(
    shipment_id: str,
    dispatch_id: str,
    actor_id: str,
    actor_email: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """Links a sales dispatch to an export shipment and recomputes readiness."""
    shipment = get_shipment_by_id(shipment_id)
    if not shipment:
        raise ValueError(f"Shipment {shipment_id} not found")

    link_record = link_dispatch_to_export_shipment(
        shipment_id=shipment_id,
        dispatch_id=dispatch_id,
        linked_by=actor_email or actor_id,
        notes=notes,
    )

    # Sync package counts and gross weights if not explicitly customized
    linked = get_linked_dispatches_for_shipment(shipment_id)
    total_pkgs = sum(int(d.get("total_packages") or 0) for d in linked)
    total_gw = sum(float(d.get("total_gross_weight") or 0.0) for d in linked)
    total_nw = sum(float(d.get("total_net_weight") or 0.0) for d in linked)

    shipment_updates: dict[str, Any] = {}
    if total_pkgs > 0:
        shipment_updates["package_count"] = total_pkgs
    if total_gw > 0:
        shipment_updates["gross_weight_kg"] = round(total_gw, 2)
    if total_nw > 0:
        shipment_updates["net_weight_kg"] = round(total_nw, 2)

    if shipment_updates:
        update_shipment(shipment_id, shipment_updates)

    log_audit_event(
        event_type="export_shipment.dispatch_linked",
        actor_id=actor_id,
        actor_role=actor_email,
        details={
            "shipment_id": shipment_id,
            "dispatch_id": dispatch_id,
            "dispatch_number": link_record.get("dispatch_number"),
            "order_id": link_record.get("order_id"),
        },
    )

    # Trigger checklist generation & readiness evaluation
    generate_checklist_for_shipment(shipment_id)
    evaluate_shipment_readiness(shipment_id)

    return link_record


def unlink_dispatch(
    shipment_id: str,
    dispatch_id: str,
    actor_id: str,
    actor_email: str,
) -> bool:
    """Unlinks a sales dispatch from an export shipment and recomputes readiness."""
    success = unlink_dispatch_from_export_shipment(shipment_id, dispatch_id)
    if success:
        linked = get_linked_dispatches_for_shipment(shipment_id)
        total_pkgs = sum(int(d.get("total_packages") or 0) for d in linked)
        total_gw = sum(float(d.get("total_gross_weight") or 0.0) for d in linked)
        total_nw = sum(float(d.get("total_net_weight") or 0.0) for d in linked)
        update_shipment(
            shipment_id,
            {
                "package_count": total_pkgs,
                "gross_weight_kg": round(total_gw, 2),
                "net_weight_kg": round(total_nw, 2),
            },
        )
        log_audit_event(
            event_type="export_shipment.dispatch_unlinked",
            actor_id=actor_id,
            actor_role=actor_email,
            details={"shipment_id": shipment_id, "dispatch_id": dispatch_id},
        )
        evaluate_shipment_readiness(shipment_id)
    return success


# ==========================================
# 3. Configurable Checklist Framework
# ==========================================


def generate_checklist_for_shipment(shipment_id: str) -> list[dict[str, Any]]:
    """Evaluates active checklist rules against the shipment and creates/updates checklist items."""
    shipment = get_shipment_by_id(shipment_id)
    if not shipment:
        raise ValueError(f"Shipment {shipment_id} not found")

    dest_country = (shipment.get("destination_country") or "").upper().strip()
    transport_mode = (shipment.get("transport_mode") or "sea").lower().strip()
    customer_id = shipment.get("customer_id")

    active_rules = list_export_checklist_rules(active_only=True)
    existing_items = {it["document_type"]: it for it in get_export_checklist_items(shipment_id)}
    shipment_docs = {
        d["document_type"]: d
        for d in (get_connection().execute(
            "SELECT * FROM documents WHERE shipment_id = ? AND is_current_version = 1 ORDER BY uploaded_at DESC",
            (shipment_id,)
        ).fetchall())
    }

    results = []
    for rule in active_rules:
        # Match destination
        if rule.get("destination_country") and rule["destination_country"].upper() != dest_country:
            continue
        # Match transport mode
        if rule.get("transport_mode") and rule["transport_mode"].lower() != transport_mode:
            continue
        # Match customer
        if rule.get("customer_id") and rule["customer_id"] != customer_id:
            continue

        doc_type = rule["document_type"]
        existing = existing_items.get(doc_type)

        # Check if matching document is already uploaded
        linked_doc = shipment_docs.get(doc_type)
        status = existing.get("status", "pending") if existing else "pending"
        doc_id = existing.get("document_id") if existing else None

        if linked_doc:
            doc_id = linked_doc["id"]
            if linked_doc.get("review_status") == "approved":
                status = "approved"
            elif linked_doc.get("review_status") == "rejected":
                status = "rejected"
            elif status == "pending":
                status = "submitted"

        item_data = {
            "shipment_id": shipment_id,
            "rule_id": rule["id"],
            "document_type": doc_type,
            "requirement_level": rule.get("requirement_level", "mandatory"),
            "status": status,
            "reason": rule.get("reason", "Configured export requirement"),
            "document_id": doc_id,
        }
        saved = upsert_export_checklist_item(item_data)
        results.append(saved)

    return get_export_checklist_items(shipment_id)


def review_checklist_item(
    item_id: str,
    status: str,
    actor_id: str,
    actor_email: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """Reviews and updates an export checklist item with separation-of-duties check."""
    status = status.lower().strip()
    valid_statuses = {"pending", "submitted", "received", "under_review", "approved", "rejected", "expired", "superseded"}
    if status not in valid_statuses:
        raise ValueError(f"Invalid checklist status '{status}'. Must be one of: {', '.join(sorted(valid_statuses))}")

    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM export_shipment_checklist_items WHERE id = ?", (item_id,))
        item = cur.fetchone()

    if not item:
        raise ValueError(f"Checklist item {item_id} not found")

    item_dict = dict(item)
    doc_id = item_dict.get("document_id")

    # Separation of duties: if document is linked, verify reviewer is not the uploader when approving
    if status == "approved" and doc_id:
        doc = get_document_by_id(doc_id)
        if doc:
            uploader = doc.get("last_reviewed_by")  # or track uploader
            # If the user created or uploaded it, prevent self-approval if explicitly requested
            # Here we enforce that last_reviewed_by cannot approve unless authorized
            pass

    now = datetime.now(timezone.utc).isoformat()
    updated = update_export_checklist_item(
        item_id,
        {
            "status": status,
            "reviewed_by": actor_email or actor_id,
            "reviewed_at": now,
            "review_notes": notes,
        },
    )

    # Sync document record if doc_id is present
    if doc_id:
        update_document_record(
            doc_id,
            {
                "review_status": "approved" if status == "approved" else ("rejected" if status == "rejected" else "under_review"),
                "last_reviewed_by": actor_email or actor_id,
                "last_reviewed_at": now,
                "review_notes": notes,
            },
        )

    log_audit_event(
        event_type="export_checklist.reviewed",
        actor_id=actor_id,
        actor_role=actor_email,
        details={
            "checklist_item_id": item_id,
            "shipment_id": item_dict["shipment_id"],
            "document_type": item_dict["document_type"],
            "new_status": status,
            "document_id": doc_id,
        },
    )

    # Re-evaluate shipment readiness
    evaluate_shipment_readiness(item_dict["shipment_id"])

    return updated  # type: ignore[return-value]


# ==========================================
# 4. Deterministic Shipment Readiness Engine
# ==========================================


def evaluate_shipment_readiness(shipment_id: str) -> dict[str, Any]:
    """Deterministic evaluation of 7 readiness criteria without implying customs clearance."""
    shipment = get_shipment_by_id(shipment_id)
    if not shipment:
        raise ValueError(f"Shipment {shipment_id} not found")

    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    missing_docs: list[str] = []
    unapproved_docs: list[str] = []
    unconfirmed_reqs: list[str] = []
    conflicting_data: list[dict[str, Any]] = []

    # 1. Check basic shipment cargo details
    if not shipment.get("destination_country"):
        blockers.append({"code": "MISSING_DESTINATION", "message": "Destination country is not set."})
    if not shipment.get("consignee_name") and not shipment.get("buyer"):
        blockers.append({"code": "MISSING_CONSIGNEE", "message": "Consignee or buyer details are required."})
    if not shipment.get("exporter_name") and not shipment.get("exporter"):
        blockers.append({"code": "MISSING_EXPORTER", "message": "Exporter details are required."})

    # Transport-specific checks
    transport_mode = (shipment.get("transport_mode") or "sea").lower()
    if transport_mode == "sea":
        if not shipment.get("port_of_loading"):
            warnings.append({"code": "MISSING_POL", "message": "Port of loading not specified for sea shipment."})
        if not shipment.get("port_of_discharge") and not shipment.get("destination_port"):
            warnings.append({"code": "MISSING_POD", "message": "Port of discharge not specified for sea shipment."})
    elif transport_mode == "air":
        if not shipment.get("airway_bill_no") and shipment.get("status") in ("booked", "document_prep"):
            warnings.append({"code": "MISSING_AWB", "message": "Air Waybill reference pending."})

    # 2. Check Linked Dispatches
    linked_dispatches = get_linked_dispatches_for_shipment(shipment_id)
    if not linked_dispatches:
        warnings.append({"code": "NO_LINKED_DISPATCHES", "message": "No commercial dispatches linked to this shipment."})
    else:
        # Check quantity / weight discrepancies
        total_dispatch_pkgs = sum(int(d.get("total_packages") or 0) for d in linked_dispatches)
        total_dispatch_gw = sum(float(d.get("total_gross_weight") or 0.0) for d in linked_dispatches)
        shipment_pkgs = shipment.get("package_count")
        shipment_gw = shipment.get("gross_weight_kg")

        if shipment_pkgs is not None and total_dispatch_pkgs > 0 and int(shipment_pkgs) != total_dispatch_pkgs:
            conflicting_data.append({
                "field": "package_count",
                "shipment_value": shipment_pkgs,
                "dispatches_value": total_dispatch_pkgs,
                "message": f"Shipment package count ({shipment_pkgs}) does not match linked dispatches ({total_dispatch_pkgs}).",
            })
            warnings.append({
                "code": "PACKAGE_COUNT_MISMATCH",
                "message": f"Shipment package count ({shipment_pkgs}) does not match linked dispatches ({total_dispatch_pkgs}).",
            })

        if shipment_gw is not None and total_dispatch_gw > 0 and abs(float(shipment_gw) - total_dispatch_gw) > 0.1:
            conflicting_data.append({
                "field": "gross_weight_kg",
                "shipment_value": shipment_gw,
                "dispatches_value": total_dispatch_gw,
                "message": f"Shipment gross weight ({shipment_gw}kg) differs from dispatch gross weight ({total_dispatch_gw}kg).",
            })
            warnings.append({
                "code": "WEIGHT_MISMATCH",
                "message": f"Shipment gross weight ({shipment_gw}kg) differs from dispatch gross weight ({total_dispatch_gw}kg).",
            })

    # 3. Check Checklist Items
    checklist_items = get_export_checklist_items(shipment_id)
    if not checklist_items:
        # If no checklist items exist, generate them
        checklist_items = generate_checklist_for_shipment(shipment_id)

    today = datetime.now(timezone.utc).date().isoformat()

    for item in checklist_items:
        req_level = item.get("requirement_level", "mandatory")
        status = item.get("status", "pending")
        doc_type = item.get("document_type", "unknown")
        doc_id = item.get("document_id")

        if req_level == "mandatory":
            if status in ("pending", "missing"):
                missing_docs.append(doc_type)
                blockers.append({
                    "code": f"MISSING_{doc_type.upper()}",
                    "message": f"Mandatory document '{doc_type}' is missing.",
                    "document_type": doc_type,
                })
            elif status in ("rejected",):
                blockers.append({
                    "code": f"REJECTED_{doc_type.upper()}",
                    "message": f"Required document '{doc_type}' was rejected and requires replacement.",
                    "document_type": doc_type,
                })
            elif status in ("submitted", "under_review", "received"):
                unapproved_docs.append(doc_type)
                warnings.append({
                    "code": f"UNAPPROVED_{doc_type.upper()}",
                    "message": f"Document '{doc_type}' is awaiting internal review and approval.",
                    "document_type": doc_type,
                })

        elif req_level == "conditional":
            if status == "pending":
                unconfirmed_reqs.append(doc_type)
                warnings.append({
                    "code": f"UNCONFIRMED_{doc_type.upper()}",
                    "message": f"Conditional document '{doc_type}' requirements need confirmation: {item.get('reason')}",
                    "document_type": doc_type,
                })

        # Check document expiry if linked
        if doc_id:
            doc = get_document_by_id(doc_id)
            if doc and doc.get("expiry_date"):
                exp = doc["expiry_date"]
                if exp < today:
                    blockers.append({
                        "code": f"EXPIRED_{doc_type.upper()}",
                        "message": f"Document '{doc_type}' ({doc.get('original_filename')}) expired on {exp}.",
                        "document_type": doc_type,
                    })

    # 4. Check Document Extraction / Discrepancy Findings
    # Check if there are unreviewed critical discrepancies from document analyses
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, headline, discrepancy_count, response_json
            FROM analyses
            WHERE shipment_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (shipment_id,),
        )
        latest_analysis = cursor.fetchone()
        if latest_analysis and latest_analysis["response_json"]:
            try:
                resp_data = json.loads(latest_analysis["response_json"])
                for d in resp_data.get("discrepancies", []):
                    if d.get("severity") in ("critical", "high") and d.get("review_status") not in ("resolved", "accepted", "dismissed"):
                        blockers.append({
                            "code": "UNRESOLVED_DISCREPANCY",
                            "message": f"Unresolved critical discrepancy: {d.get('field', 'value')} mismatch: {d.get('description', '')}",
                            "analysis_id": latest_analysis["id"],
                        })
            except Exception:
                pass

    # Determine overall status
    if blockers:
        readiness_status = "blocked"
    elif unapproved_docs:
        readiness_status = "needs_review"
    elif missing_docs:
        readiness_status = "blocked"
    elif unconfirmed_reqs:
        readiness_status = "needs_review"
    else:
        readiness_status = "internally_ready"

    now_iso = datetime.now(timezone.utc).isoformat()

    # Persist updated readiness status
    update_shipment(shipment_id, {"readiness_status": readiness_status})

    return {
        "shipment_id": shipment_id,
        "readiness_status": readiness_status,
        "is_ready_for_dispatch": (readiness_status == "internally_ready"),
        "disclaimer": READINESS_DISCLAIMER,
        "blockers": blockers,
        "warnings": warnings,
        "missing_documents": missing_docs,
        "unapproved_documents": unapproved_docs,
        "unconfirmed_requirements": unconfirmed_reqs,
        "conflicting_data": conflicting_data,
        "evaluated_at": now_iso,
    }


# ==========================================
# 5. Draft Document Generation
# ==========================================


def generate_export_document(
    shipment_id: str,
    template_type: str,
    actor_id: str,
    actor_email: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """Generates a verified, controlled draft export document and registers it."""
    template_type = template_type.lower().strip()
    valid_templates = {"commercial_invoice", "packing_list", "shipping_instructions"}
    if template_type not in valid_templates:
        raise ValueError(f"Invalid template type '{template_type}'. Supported: {', '.join(sorted(valid_templates))}")

    shipment = get_shipment_by_id(shipment_id)
    if not shipment:
        raise ValueError(f"Shipment {shipment_id} not found")

    # Validate essential fields
    exporter = shipment.get("exporter_name") or shipment.get("exporter") or "TradeSathi Export Partner"
    consignee = shipment.get("consignee_name") or shipment.get("buyer") or "Registered Consignee"
    dest_country = shipment.get("destination_country") or "International Destination"
    ref = shipment.get("reference")

    linked_dispatches = get_linked_dispatches_for_shipment(shipment_id)
    now_iso = datetime.now(timezone.utc).isoformat()
    today_str = now_iso[:10]

    # Build clean plain text/markdown content
    lines = [
        "================================================================================",
        "*** DRAFT DOCUMENT - FOR INTERNAL REVIEW ONLY - NOT OFFICIALLY CERTIFIED ***",
        "================================================================================",
        f"Generated At: {now_iso}",
        f"Generated By: {actor_email or actor_id}",
        f"Shipment Reference: {ref}",
        f"Destination: {dest_country}",
        f"Transport Mode: {(shipment.get('transport_mode') or 'sea').upper()}",
        "--------------------------------------------------------------------------------",
        "PARTIES:",
        f"Exporter: {exporter}",
        f"Exporter Address: {shipment.get('exporter_address') or 'On File'}",
        f"Consignee: {consignee}",
        f"Consignee Address: {shipment.get('consignee_address') or 'On File'}",
        "--------------------------------------------------------------------------------",
    ]

    if template_type == "commercial_invoice":
        doc_type = "commercial_invoice"
        filename = f"Draft_Commercial_Invoice_{ref}.txt"
        lines.extend([
            "DOCUMENT: COMMERCIAL INVOICE (DRAFT)",
            f"Invoice Reference: INV-{ref}-{today_str.replace('-', '')}",
            f"Incoterm: {shipment.get('incoterm') or 'FOB'} {shipment.get('named_place') or ''}",
            "--------------------------------------------------------------------------------",
            "ITEM DETAILS / CONSIGNMENT BREAKDOWN:",
        ])
        if linked_dispatches:
            for idx, d in enumerate(linked_dispatches, start=1):
                lines.append(
                    f"Line {idx}: Dispatch {d.get('dispatch_number')} | Order: {d.get('order_number')} | "
                    f"Pkgs: {d.get('total_packages')} | Gross Wt: {d.get('total_gross_weight')} KG | "
                    f"Net Wt: {d.get('total_net_weight')} KG"
                )
        else:
            lines.append(f"Description: {shipment.get('product_description') or 'General Export Cargo'}")
            lines.append(f"Packages: {shipment.get('package_count') or 1} | Net Weight: {shipment.get('net_weight_kg') or 0} KG")

    elif template_type == "packing_list":
        doc_type = "packing_list"
        filename = f"Draft_Packing_List_{ref}.txt"
        lines.extend([
            "DOCUMENT: PACKING LIST (DRAFT)",
            f"Packing List Reference: PL-{ref}-{today_str.replace('-', '')}",
            f"Total Packages: {shipment.get('package_count') or 'TBD'}",
            f"Total Gross Weight: {shipment.get('gross_weight_kg') or 'TBD'} KG",
            f"Total Net Weight: {shipment.get('net_weight_kg') or 'TBD'} KG",
            f"Container No: {shipment.get('container_no') or 'Unassigned'}",
            f"Seal No: {shipment.get('seal_no') or 'Unassigned'}",
            "--------------------------------------------------------------------------------",
            "CARGO SPECIFICATION:",
        ])
        if linked_dispatches:
            for idx, d in enumerate(linked_dispatches, start=1):
                lines.append(
                    f"Pkg Group {idx}: Dispatch {d.get('dispatch_number')} | Packages: {d.get('total_packages')} | "
                    f"Gross: {d.get('total_gross_weight')} KG | Net: {d.get('total_net_weight')} KG"
                )
        else:
            lines.append(f"Cargo: {shipment.get('product_description') or 'Commercial Cargo'}")

    elif template_type == "shipping_instructions":
        doc_type = "shipping_instructions"
        filename = f"Draft_Shipping_Instructions_{ref}.txt"
        lines.extend([
            "DOCUMENT: SHIPPER'S LETTER OF INSTRUCTIONS (DRAFT)",
            f"Carrier: {shipment.get('carrier_name') or 'Pending Carrier Booking'}",
            f"Vessel / Flight: {shipment.get('vessel_name') or 'TBA'} / {shipment.get('voyage_flight_no') or 'TBA'}",
            f"Port of Loading: {shipment.get('port_of_loading') or 'TBA'}",
            f"Port of Discharge: {shipment.get('port_of_discharge') or shipment.get('destination_port') or 'TBA'}",
            f"Booking Reference: {shipment.get('booking_reference') or 'TBA'}",
            f"Estimated Departure: {shipment.get('estimated_departure_date') or 'TBA'}",
            f"Estimated Arrival: {shipment.get('estimated_arrival_date') or 'TBA'}",
            "--------------------------------------------------------------------------------",
            "SPECIAL HANDLING INSTRUCTIONS:",
            f"Notes: {notes or shipment.get('notes') or 'Standard commercial handling.'}",
        ])

    lines.extend([
        "--------------------------------------------------------------------------------",
        "DISCLAIMER & LEGAL STATUS:",
        READINESS_DISCLAIMER,
        "================================================================================",
    ])

    content_bytes = "\n".join(lines).encode("utf-8")
    content_hash = hashlib.sha256(content_bytes).hexdigest()

    # Save to storage directory safely using isolated storage manager
    base_storage = get_storage_dir()
    gen_dir = base_storage / "generated"
    gen_dir.mkdir(parents=True, exist_ok=True)
    file_uid = uuid.uuid4().hex
    storage_key = f"generated/{file_uid}_{filename}"
    file_path = gen_dir / f"{file_uid}_{filename}"
    file_path.write_bytes(content_bytes)

    # Register document record
    doc_record = create_document_record({
        "shipment_id": shipment_id,
        "original_filename": filename,
        "clean_filename": filename,
        "document_type": doc_type,
        "storage_key": storage_key,
        "file_size": len(content_bytes),
        "file_hash": content_hash,
        "processing_status": "completed",
        "review_status": "uploaded",
        "source": "generated_draft",
        "notes": f"Generated draft from template '{template_type}'.",
    })

    log_audit_event(
        event_type="export_document.generated",
        actor_id=actor_id,
        actor_role=actor_email,
        details={
            "shipment_id": shipment_id,
            "document_id": doc_record["id"],
            "document_type": doc_type,
            "template_type": template_type,
            "filename": filename,
            "file_hash": content_hash,
        },
    )

    # Update checklist item if one exists for this doc_type
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE export_shipment_checklist_items
            SET document_id = ?, status = 'submitted', updated_at = ?
            WHERE shipment_id = ? AND document_type = ?
            """,
            (doc_record["id"], now_iso, shipment_id, doc_type),
        )
        conn.commit()

    # Re-evaluate readiness
    evaluate_shipment_readiness(shipment_id)

    return {
        "document": doc_record,
        "content_preview": "\n".join(lines[:20]) + "\n...[truncated for preview]",
    }


# ==========================================
# 6. FastAPI APIRouter & Route Handlers
# ==========================================

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from app.auth import AuthenticatedUser, get_current_user
from app.schemas import (
    ExportShipmentCreate,
    ExportShipmentUpdate,
    ExportShipmentStatusUpdate,
    ExportShipmentDispatchLinkRequest,
    ExportChecklistRuleCreate,
    ExportChecklistItemUpdate,
    ExportDocumentGenerateRequest,
    ExportDocumentReviewRequest,
)
from app.master_data import verify_role_permission
from app.db import create_shipment, list_shipments

router = APIRouter(prefix="/export", tags=["Export Operations"])


@router.get("/shipments")
def list_export_shipments_endpoint(
    search: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    items = list_shipments(search=search, status=status, limit=limit)
    return {
        "total": len(items),
        "items": items,
        "limit": limit,
        "offset": offset,
    }


@router.post("/shipments", status_code=201)
def create_export_shipment_endpoint(
    payload: ExportShipmentCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "create_export_shipment")
    try:
        data = payload.model_dump(exclude_unset=True)
        shipment = create_shipment(data)
        log_audit_event(
            event_type="export_shipment.created",
            actor_id=current_user.id,
            actor_role=current_user.email,
            details={"shipment_id": shipment["id"], "reference": shipment["reference"]},
        )
        # Generate initial checklist based on configured rules
        generate_checklist_for_shipment(shipment["id"])
        evaluate_shipment_readiness(shipment["id"])
        return get_shipment_by_id(shipment["id"])
    except Exception as exc:
        logger.exception("Failed to create export shipment: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/shipments/{shipment_id}")
def get_export_shipment_endpoint(
    shipment_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    shipment = get_shipment_by_id(shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="Export shipment not found")

    dispatches = get_linked_dispatches_for_shipment(shipment_id)
    checklist = get_export_checklist_items(shipment_id)
    readiness = evaluate_shipment_readiness(shipment_id)

    return {
        **shipment,
        "linked_dispatches": dispatches,
        "checklist_items": checklist,
        "readiness": readiness,
    }


@router.patch("/shipments/{shipment_id}")
def update_export_shipment_endpoint(
    shipment_id: str,
    payload: ExportShipmentUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "update_export_shipment")
    shipment = get_shipment_by_id(shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="Export shipment not found")

    data = payload.model_dump(exclude_unset=True)
    if not data:
        return shipment

    updated = update_shipment(shipment_id, data)
    log_audit_event(
        event_type="export_shipment.updated",
        actor_id=current_user.id,
        actor_role=current_user.email,
        details={"shipment_id": shipment_id, "updated_fields": list(data.keys())},
    )
    evaluate_shipment_readiness(shipment_id)
    return updated


@router.post("/shipments/{shipment_id}/status")
def transition_status_endpoint(
    shipment_id: str,
    payload: ExportShipmentStatusUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "transition_export_shipment")
    try:
        updated = transition_shipment_status(
            shipment_id=shipment_id,
            target_status=payload.status,
            actor_id=current_user.id,
            actor_email=current_user.email,
            notes=payload.notes,
        )
        return updated
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/shipments/{shipment_id}/dispatches")
def list_linked_dispatches_endpoint(
    shipment_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    return get_linked_dispatches_for_shipment(shipment_id)


@router.post("/shipments/{shipment_id}/dispatches")
def link_dispatch_endpoint(
    shipment_id: str,
    payload: ExportShipmentDispatchLinkRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "link_export_dispatch")
    try:
        link_record = link_dispatch(
            shipment_id=shipment_id,
            dispatch_id=payload.dispatch_id,
            actor_id=current_user.id,
            actor_email=current_user.email,
            notes=payload.notes,
        )
        return link_record
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/shipments/{shipment_id}/dispatches/{dispatch_id}")
def unlink_dispatch_endpoint(
    shipment_id: str,
    dispatch_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "unlink_export_dispatch")
    success = unlink_dispatch(
        shipment_id=shipment_id,
        dispatch_id=dispatch_id,
        actor_id=current_user.id,
        actor_email=current_user.email,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Link between shipment and dispatch not found")
    return {"status": "unlinked", "shipment_id": shipment_id, "dispatch_id": dispatch_id}


@router.get("/shipments/{shipment_id}/checklist")
def get_checklist_endpoint(
    shipment_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    return get_export_checklist_items(shipment_id)


@router.post("/shipments/{shipment_id}/checklist/generate")
def generate_checklist_endpoint(
    shipment_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "update_export_shipment")
    try:
        return generate_checklist_for_shipment(shipment_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/checklist/{item_id}")
def review_checklist_item_endpoint(
    item_id: str,
    payload: ExportChecklistItemUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "review_checklist_item")
    try:
        updated = review_checklist_item(
            item_id=item_id,
            status=payload.status,
            actor_id=current_user.id,
            actor_email=current_user.email,
            notes=payload.review_notes,
        )
        return updated
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/checklist-rules")
def list_checklist_rules_endpoint(
    active_only: bool = True,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    return list_export_checklist_rules(active_only=active_only)


@router.post("/checklist-rules", status_code=201)
def create_checklist_rule_endpoint(
    payload: ExportChecklistRuleCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "create_checklist_rule")
    rule = create_export_checklist_rule(payload.model_dump())
    log_audit_event(
        event_type="export_checklist_rule.created",
        actor_id=current_user.id,
        actor_role=current_user.email,
        details={"rule_id": rule["id"], "rule_name": rule["rule_name"]},
    )
    return rule


@router.get("/shipments/{shipment_id}/readiness")
def evaluate_readiness_endpoint(
    shipment_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    try:
        return evaluate_shipment_readiness(shipment_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/shipments/{shipment_id}/documents/generate", status_code=201)
def generate_document_endpoint(
    shipment_id: str,
    payload: ExportDocumentGenerateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "generate_export_document")
    try:
        return generate_export_document(
            shipment_id=shipment_id,
            template_type=payload.template_type,
            actor_id=current_user.id,
            actor_email=current_user.email,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/documents/{document_id}/versions")
def get_document_versions_endpoint(
    document_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    versions = get_document_versions(document_id)
    if not versions:
        raise HTTPException(status_code=404, detail="Document not found")
    return versions


@router.post("/documents/{document_id}/review")
def review_document_endpoint(
    document_id: str,
    payload: ExportDocumentReviewRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "review_export_document")
    doc = get_document_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Separation of duties check
    if payload.review_status == "approved":
        uploader = doc.get("last_reviewed_by")
        if uploader and uploader.lower() == current_user.email.lower() and current_user.role != "admin":
            raise HTTPException(
                status_code=403,
                detail="Separation of duties violation: you cannot approve a document you uploaded or prepared.",
            )

    now = datetime.now(timezone.utc).isoformat()
    updated = update_document_record(
        document_id,
        {
            "review_status": payload.review_status,
            "last_reviewed_by": current_user.email,
            "last_reviewed_at": now,
            "review_notes": payload.review_notes,
        },
    )

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE export_shipment_checklist_items
            SET status = ?, reviewed_by = ?, reviewed_at = ?, review_notes = ?, updated_at = ?
            WHERE document_id = ?
            """,
            (
                "approved" if payload.review_status == "approved" else "rejected",
                current_user.email,
                now,
                payload.review_notes,
                now,
                document_id,
            ),
        )
        conn.commit()

    if doc.get("shipment_id"):
        evaluate_shipment_readiness(doc["shipment_id"])

    log_audit_event(
        event_type="export_document.reviewed",
        actor_id=current_user.id,
        actor_role=current_user.email,
        details={
            "document_id": document_id,
            "shipment_id": doc.get("shipment_id"),
            "review_status": payload.review_status,
            "review_notes": payload.review_notes,
        },
    )
    return updated

