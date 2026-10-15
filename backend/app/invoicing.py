"""
TradeSathi AI — Phase 6: Commercial Invoicing, Payments, Indian GST & Multi-Currency Engine
"""

from datetime import datetime, timezone
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from app.auth import AuthenticatedUser, get_current_user
from app.db import (
    get_connection,
    create_customer_invoice_record,
    get_customer_invoice_record,
    list_customer_invoices_record,
    update_customer_invoice_status_record,
    create_customer_payment_record,
    get_customer_payment_record,
    list_customer_payments_record,
    allocate_customer_payment_record,
    create_customer_credit_note_record,
    get_customer_credit_note_record,
    list_customer_credit_notes_record,
    get_receivables_aging_data,
    get_gst_outward_supplies_data,
)
from app.master_data import verify_role_permission, record_erp_audit_log
from app.schemas import (
    CustomerInvoiceCreate,
    CustomerInvoiceStatusUpdate,
    CustomerPaymentCreate,
    CustomerPaymentAllocationRequest,
    CustomerCreditNoteCreate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/finance", tags=["Finance & Invoicing"])

INVOICE_STATUTORY_NOTICE = (
    "TradeSathi AI Commercial Invoice — Internal commercial accounting and trade preparation document. "
    "Not an official e-invoice or statutory GST filing acknowledgement."
)


def log_audit_event(
    event_type: str,
    actor_id: str,
    actor_role: str,
    details: dict[str, Any],
) -> None:
    entity_id = (
        details.get("invoice_id")
        or details.get("payment_id")
        or details.get("credit_note_id")
        or "finance"
    )
    record_erp_audit_log(
        entity_type="finance",
        entity_id=entity_id,
        action=event_type,
        changes=details,
        performed_by=actor_role or actor_id or "system",
    )


# ==========================================
# Indian GST Calculation Engine
# ==========================================


def extract_state_code(pos_string: str) -> str:
    """Extracts the 2-digit Indian State code from a place_of_supply string (e.g. '19-West Bengal' -> '19')."""
    if not pos_string:
        return "19"
    parts = pos_string.strip().split("-")
    if len(parts) >= 2 and len(parts[0].strip()) == 2 and parts[0].strip().isdigit():
        return parts[0].strip()
    clean = pos_string.strip()[:2]
    if clean.isdigit():
        return clean
    return "19"


def compute_gst_line_item(
    quantity: float,
    unit_price: float,
    discount_pct: float,
    gst_rate_pct: float,
    tax_classification: str,
    tax_scheme: str,
    place_of_supply: str,
    supplier_state_code: str = "19",
) -> dict[str, float]:
    """
    Computes line-level taxable amount, CGST, SGST, IGST, and line total.
    Enforces strict mutual exclusion: CGST/SGST and IGST must NEVER be applied together.
    """
    qty = float(quantity)
    price = float(unit_price)
    disc = max(0.0, min(100.0, float(discount_pct or 0.0)))
    raw_subtotal = qty * price
    discount_amount = round(raw_subtotal * (disc / 100.0), 2)
    taxable_amount = round(raw_subtotal - discount_amount, 2)

    gst_rate = max(0.0, float(gst_rate_pct or 0.0))
    pos_state = extract_state_code(place_of_supply)

    # 1. Exempt / Nil-Rated / Non-GST
    if tax_classification in ("exempt", "nil_rated", "non_gst") or tax_scheme == "EXEMPT":
        cgst_rate = 0.0
        cgst_amount = 0.0
        sgst_rate = 0.0
        sgst_amount = 0.0
        igst_rate = 0.0
        igst_amount = 0.0

    # 2. Export under Letter of Undertaking (LUT / Bond)
    elif tax_scheme == "EXPORT_LUT":
        cgst_rate = 0.0
        cgst_amount = 0.0
        sgst_rate = 0.0
        sgst_amount = 0.0
        igst_rate = 0.0
        igst_amount = 0.0

    # 3. Export with payment of IGST
    elif tax_scheme == "EXPORT_ZERO_RATED":
        cgst_rate = 0.0
        cgst_amount = 0.0
        sgst_rate = 0.0
        sgst_amount = 0.0
        igst_rate = gst_rate
        igst_amount = round(taxable_amount * (igst_rate / 100.0), 2)

    # 4. Intra-State Supply (Supplier State == Place of Supply State)
    elif pos_state == supplier_state_code:
        cgst_rate = gst_rate / 2.0
        cgst_amount = round(taxable_amount * (cgst_rate / 100.0), 2)
        sgst_rate = gst_rate / 2.0
        sgst_amount = round(taxable_amount * (sgst_rate / 100.0), 2)
        igst_rate = 0.0
        igst_amount = 0.0

    # 5. Inter-State Supply (Supplier State != Place of Supply State)
    else:
        cgst_rate = 0.0
        cgst_amount = 0.0
        sgst_rate = 0.0
        sgst_amount = 0.0
        igst_rate = gst_rate
        igst_amount = round(taxable_amount * (igst_rate / 100.0), 2)

    # Invariant enforcement: CGST/SGST and IGST cannot both be > 0
    if igst_amount > 0 and (cgst_amount > 0 or sgst_amount > 0):
        raise ValueError("Invalid tax state: CGST/SGST and IGST cannot be applied together to the same line item")

    line_total = round(taxable_amount + cgst_amount + sgst_amount + igst_amount, 2)

    return {
        "discount_amount": discount_amount,
        "taxable_amount": taxable_amount,
        "gst_rate_pct": gst_rate,
        "cgst_rate_pct": cgst_rate,
        "cgst_amount": cgst_amount,
        "sgst_rate_pct": sgst_rate,
        "sgst_amount": sgst_amount,
        "igst_rate_pct": igst_rate,
        "igst_amount": igst_amount,
        "line_total": line_total,
    }


# ==========================================
# Invoicing Endpoints
# ==========================================


@router.get("/invoices")
def list_invoices_endpoint(
    customer_id: str | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    return list_customer_invoices_record(
        customer_id=customer_id,
        status=status,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.post("/invoices")
def create_invoice_endpoint(
    payload: CustomerInvoiceCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "create_invoice")

    # Validate Customer exists and fetch billing address
    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM customers WHERE id = ?", (payload.customer_id,))
        cust = cur.fetchone()
        if not cust:
            raise HTTPException(status_code=400, detail=f"Customer {payload.customer_id} not found")

    supplier_state = "19"  # Default West Bengal (TradeSathi headquarters)
    processed_items: list[dict[str, Any]] = []

    for item in payload.items:
        tax_res = compute_gst_line_item(
            quantity=item.quantity,
            unit_price=item.unit_price,
            discount_pct=item.discount_pct,
            gst_rate_pct=item.gst_rate_pct,
            tax_classification=item.tax_classification,
            tax_scheme=payload.tax_scheme,
            place_of_supply=payload.place_of_supply,
            supplier_state_code=supplier_state,
        )
        processed_items.append({
            "sales_order_item_id": item.sales_order_item_id,
            "product_id": item.product_id,
            "product_sku": item.product_sku,
            "description": item.description,
            "hsn_code": item.hsn_code,
            "uom": item.uom,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "discount_pct": item.discount_pct,
            "discount_amount": tax_res["discount_amount"],
            "taxable_amount": tax_res["taxable_amount"],
            "tax_classification": item.tax_classification,
            "gst_rate_pct": tax_res["gst_rate_pct"],
            "cgst_rate_pct": tax_res["cgst_rate_pct"],
            "cgst_amount": tax_res["cgst_amount"],
            "sgst_rate_pct": tax_res["sgst_rate_pct"],
            "sgst_amount": tax_res["sgst_amount"],
            "igst_rate_pct": tax_res["igst_rate_pct"],
            "igst_amount": tax_res["igst_amount"],
            "line_total": tax_res["line_total"],
        })

    invoice_data = {
        "invoice_number": payload.invoice_number,
        "customer_id": payload.customer_id,
        "customer_code": cust["code"],
        "customer_name": cust["name"],
        "billing_address": cust["billing_address"] or cust["name"],
        "shipping_address": cust["shipping_address"] or cust["billing_address"],
        "customer_tax_id": cust["tax_id"],
        "supplier_tax_id": "19AAACT1234A1Z5",
        "supplier_state_code": supplier_state,
        "place_of_supply": payload.place_of_supply,
        "invoice_date": payload.invoice_date,
        "due_date": payload.due_date,
        "currency": payload.currency,
        "exchange_rate": payload.exchange_rate,
        "payment_terms": payload.payment_terms,
        "payment_terms_days": payload.payment_terms_days,
        "sales_order_id": payload.sales_order_id,
        "dispatch_id": payload.dispatch_id,
        "export_shipment_id": payload.export_shipment_id,
        "tax_scheme": payload.tax_scheme,
        "lut_bond_number": payload.lut_bond_number,
        "status": "draft",
        "notes": payload.notes,
        "created_by": current_user.email or current_user.id,
    }

    try:
        created = create_customer_invoice_record(invoice_data, processed_items)
        log_audit_event(
            event_type="invoice.created",
            actor_id=current_user.id,
            actor_role=current_user.email,
            details={
                "invoice_id": created["id"],
                "invoice_number": created["invoice_number"],
                "grand_total": created["grand_total"],
                "currency": created["currency"],
            },
        )
        return created
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/invoices/{invoice_id}")
def get_invoice_endpoint(
    invoice_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    invoice = get_customer_invoice_record(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
    return {
        **invoice,
        "statutory_notice": INVOICE_STATUTORY_NOTICE,
    }


@router.post("/invoices/{invoice_id}/status")
def update_invoice_status_endpoint(
    invoice_id: str,
    payload: CustomerInvoiceStatusUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "update_invoice")
    invoice = get_customer_invoice_record(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Separation of duties: creator cannot issue/approve their own invoice
    if payload.status in ("approved", "issued"):
        creator = invoice.get("created_by")
        actor = current_user.email or current_user.id
        if creator and actor and creator == actor and current_user.role != "admin":
            raise HTTPException(
                status_code=403,
                detail="Separation-of-duties violation: Invoice creator cannot approve or issue their own invoice",
            )

    try:
        updated = update_customer_invoice_status_record(
            invoice_id=invoice_id,
            target_status=payload.status,
            actor=current_user.email or current_user.id,
            reason=payload.reason,
        )
        log_audit_event(
            event_type=f"invoice.{payload.status}",
            actor_id=current_user.id,
            actor_role=current_user.email,
            details={"invoice_id": invoice_id, "status": payload.status, "reason": payload.reason},
        )
        return updated
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ==========================================
# Payments & Allocations Endpoints
# ==========================================


@router.get("/payments")
def list_payments_endpoint(
    customer_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    return list_customer_payments_record(customer_id=customer_id, limit=limit, offset=offset)


@router.post("/payments")
def create_payment_endpoint(
    payload: CustomerPaymentCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "record_payment")

    with get_connection() as conn:
        cur = conn.execute("SELECT name FROM customers WHERE id = ?", (payload.customer_id,))
        cust = cur.fetchone()
        if not cust:
            raise HTTPException(status_code=400, detail="Customer not found")

    data = {
        "payment_number": payload.payment_number,
        "customer_id": payload.customer_id,
        "customer_name": cust["name"],
        "payment_date": payload.payment_date,
        "payment_method": payload.payment_method,
        "reference_number": payload.reference_number,
        "currency": payload.currency,
        "exchange_rate": payload.exchange_rate,
        "amount": payload.amount,
        "notes": payload.notes,
        "created_by": current_user.email or current_user.id,
    }

    created = create_customer_payment_record(data)
    log_audit_event(
        event_type="payment.recorded",
        actor_id=current_user.id,
        actor_role=current_user.email,
        details={
            "payment_id": created["id"],
            "payment_number": created["payment_number"],
            "amount": created["amount"],
            "currency": created["currency"],
        },
    )
    return created


@router.get("/payments/{payment_id}")
def get_payment_endpoint(
    payment_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    payment = get_customer_payment_record(payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment


@router.post("/payments/{payment_id}/allocate")
def allocate_payment_endpoint(
    payment_id: str,
    payload: CustomerPaymentAllocationRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "record_payment")
    try:
        updated_payment = allocate_customer_payment_record(
            payment_id=payment_id,
            invoice_id=payload.invoice_id,
            amount=payload.amount,
            actor=current_user.email or current_user.id,
            notes=payload.notes,
        )
        log_audit_event(
            event_type="payment.allocated",
            actor_id=current_user.id,
            actor_role=current_user.email,
            details={
                "payment_id": payment_id,
                "invoice_id": payload.invoice_id,
                "allocated_amount": payload.amount,
            },
        )
        return updated_payment
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ==========================================
# Credit Notes Endpoints
# ==========================================


@router.get("/credit-notes")
def list_credit_notes_endpoint(
    invoice_id: str | None = None,
    customer_id: str | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    return list_customer_credit_notes_record(invoice_id=invoice_id, customer_id=customer_id)


@router.post("/credit-notes")
def create_credit_note_endpoint(
    payload: CustomerCreditNoteCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "create_credit_note")
    invoice = get_customer_invoice_record(payload.invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    supplier_state = invoice.get("supplier_state_code", "19")
    processed_items: list[dict[str, Any]] = []

    for it in payload.items:
        tax_res = compute_gst_line_item(
            quantity=it.quantity,
            unit_price=it.unit_price,
            discount_pct=0.0,
            gst_rate_pct=it.gst_rate_pct,
            tax_classification="taxable",
            tax_scheme=invoice.get("tax_scheme", "GST"),
            place_of_supply=invoice.get("place_of_supply", "19-West Bengal"),
            supplier_state_code=supplier_state,
        )
        processed_items.append({
            "invoice_item_id": it.invoice_item_id,
            "product_sku": it.product_sku,
            "description": it.description,
            "quantity": it.quantity,
            "unit_price": it.unit_price,
            "taxable_amount": tax_res["taxable_amount"],
            "gst_rate_pct": tax_res["gst_rate_pct"],
            "cgst_amount": tax_res["cgst_amount"],
            "sgst_amount": tax_res["sgst_amount"],
            "igst_amount": tax_res["igst_amount"],
            "line_total": tax_res["line_total"],
        })

    data = {
        "credit_note_number": payload.credit_note_number,
        "invoice_id": payload.invoice_id,
        "credit_note_date": payload.credit_note_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "reason": payload.reason,
        "notes": payload.notes,
        "created_by": current_user.email or current_user.id,
    }

    try:
        created = create_customer_credit_note_record(data, processed_items)
        log_audit_event(
            event_type="credit_note.created",
            actor_id=current_user.id,
            actor_role=current_user.email,
            details={
                "credit_note_id": created["id"],
                "credit_note_number": created["credit_note_number"],
                "invoice_id": payload.invoice_id,
                "grand_total": created["grand_total"],
            },
        )
        return created
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/credit-notes/{crn_id}")
def get_credit_note_endpoint(
    crn_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    crn = get_customer_credit_note_record(crn_id)
    if not crn:
        raise HTTPException(status_code=404, detail="Credit Note not found")
    return crn


# ==========================================
# Finance Reports Endpoints
# ==========================================


@router.get("/reports/receivables-aging")
def get_receivables_aging_endpoint(
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    return get_receivables_aging_data()


@router.get("/reports/gst-outward")
def get_gst_outward_report_endpoint(
    from_date: str | None = None,
    to_date: str | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    verify_role_permission(current_user.role, "read")
    return get_gst_outward_supplies_data(from_date=from_date, to_date=to_date)
