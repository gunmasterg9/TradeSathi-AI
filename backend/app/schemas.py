from typing import Any, Literal
from pydantic import BaseModel, Field


class FieldEvidence(BaseModel):
    evidence_id: str | None = None
    value: Any = None
    raw_value: str | None = None
    normalized_value: Any = None
    unit: str | None = None
    source_snippet: str | None = None
    source_document: str | None = None
    document_id: str | None = None
    field_name: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    page_number: int | None = None
    method: Literal["deterministic_rules", "ollama_model", "hybrid", "unknown"] | str | None = "deterministic_rules"
    validation_status: Literal["verified", "uncertain", "invalid", "missing"] | str | None = "verified"
    confidence: float | None = None
    notes: str | None = None
    limitations: list[str] = Field(default_factory=list)
    is_grounded: bool = True


class LineItem(BaseModel):
    description: str | None = None
    hs_code: str | None = None
    quantity: float | None = None
    unit: str | None = None
    unit_price: float | None = None
    amount: float | None = None
    net_weight_kg: float | None = None
    gross_weight_kg: float | None = None


class ExtractedDocument(BaseModel):
    id: str = ""
    filename: str
    file_hash: str | None = None
    document_type: Literal[
        "commercial_invoice",
        "packing_list",
        "purchase_order",
        "shipping_instructions",
        "unknown",
    ] = "unknown"
    exporter: str | None = None
    buyer: str | None = None
    consignee: str | None = None
    invoice_number: str | None = None
    purchase_order_number: str | None = None
    invoice_date: str | None = None
    currency: str | None = None
    total_amount: float | None = None
    total_net_weight_kg: float | None = None
    total_gross_weight_kg: float | None = None
    raw_invoice_number: str | None = None
    raw_invoice_date: str | None = None
    raw_currency: str | None = None
    raw_total_amount: str | None = None
    raw_net_weight: str | None = None
    raw_gross_weight: str | None = None
    packages: int | None = None
    raw_packages: str | None = None
    package_type: str | None = None
    product_description: str | None = None
    raw_product_description: str | None = None
    hs_code: str | None = None
    raw_hs_code: str | None = None
    incoterms: str | None = None
    raw_incoterms: str | None = None
    country_of_origin: str | None = None
    raw_country_of_origin: str | None = None
    port_of_loading: str | None = None
    raw_port_of_loading: str | None = None
    port_of_discharge: str | None = None
    raw_port_of_discharge: str | None = None
    port_of_destination: str | None = None
    shipment_reference: str | None = None
    raw_shipment_reference: str | None = None
    items: list[LineItem] = Field(default_factory=list)
    evidence: dict[str, str] = Field(default_factory=dict)
    field_evidence: dict[str, FieldEvidence] = Field(default_factory=dict)
    extraction_notes: list[str] = Field(default_factory=list)


ReviewState = Literal["pending_review", "in_review", "acknowledged", "resolved", "escalated", "reopened"]


class ReviewEvent(BaseModel):
    id: str
    analysis_id: str
    finding_id: str
    previous_state: ReviewState
    new_state: ReviewState
    reviewer: str
    timestamp: str
    notes: str = ""
    reason: str = ""
    supporting_evidence: list[str] = Field(default_factory=list)
    corrected_value: Any | None = None
    corrected_unit: str | None = None
    source: str | None = None
    is_operator_assertion: bool = False
    resolution_basis: Literal["grounded_evidence", "operator_assertion", "hybrid"] = "operator_assertion"
    is_authenticated: bool = False


class FindingResolution(BaseModel):
    resolved_at: str
    resolved_by: str
    reason: str
    supporting_evidence: list[str] = Field(default_factory=list)
    corrected_value: Any | None = None
    corrected_unit: str | None = None
    source: str | None = None
    is_operator_assertion: bool = False
    resolution_basis: Literal["grounded_evidence", "operator_assertion", "hybrid"] = "operator_assertion"
    is_authenticated: bool = False


class ReviewActionRequest(BaseModel):
    action: ReviewState
    reviewer: str = "Local Operator"
    notes: str = ""
    reason: str = ""
    supporting_evidence: list[str] = Field(default_factory=list)
    corrected_value: Any | None = None
    corrected_unit: str | None = None
    source: str | None = None


class Discrepancy(BaseModel):
    id: str = ""
    field: str
    label: str
    severity: Literal["critical", "warning", "info"]
    doc_values: dict[str, Any] = Field(default_factory=dict)
    difference: str | None = None
    reason: str
    source_document: str | None = None
    recommended_action: str
    message: str
    comparison_rule: str | None = None
    raw_values: dict[str, Any] = Field(default_factory=dict)
    normalized_values: dict[str, Any] = Field(default_factory=dict)
    units: dict[str, str | None] = Field(default_factory=dict)
    provenance_statuses: dict[str, str] = Field(default_factory=dict)
    source_documents: list[str] = Field(default_factory=list)
    source_snippets: dict[str, str | None] = Field(default_factory=dict)
    evidence: dict[str, FieldEvidence] = Field(default_factory=dict)
    evidence_ids: dict[str, str | None] = Field(default_factory=dict)
    delta_numeric: float | None = None
    delta_percentage: float | None = None
    human_review_required: bool = False
    review_status: ReviewState = "pending_review"
    resolution: FindingResolution | None = None
    review_history: list[ReviewEvent] = Field(default_factory=list)


class ChecklistItem(BaseModel):
    id: str
    title: str
    status: Literal["passed", "failed", "needs_review", "not_applicable", "warning", "skipped"]
    detail: str


class ShipmentSummary(BaseModel):
    status: Literal["ready_for_review", "needs_attention", "missing_information", "analysis_failed"]
    headline: str
    documents_received: list[str] = Field(default_factory=list)
    confirmed_values: list[dict[str, str]] = Field(default_factory=list)
    conflicting_fields: list[str] = Field(default_factory=list)
    conflicting_items: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    missing_items: list[str] = Field(default_factory=list)
    checklist: list[ChecklistItem] = Field(default_factory=list)
    summary_text: str


class AnalyzeResponse(BaseModel):
    id: str
    created_at: str
    mode: Literal["ollama", "rules_fallback"]
    model: str | None = None
    documents: list[ExtractedDocument]
    discrepancies: list[Discrepancy]
    summary: ShipmentSummary
    shipment_id: str | None = None


class AuditSummaryItem(BaseModel):
    id: str
    created_at: str
    mode: str
    model: str | None = None
    status: str
    headline: str
    document_count: int
    filenames: list[str] = Field(default_factory=list)
    discrepancy_count: int = 0
    shipment_id: str | None = None
    shipment_reference: str | None = None
    invoice_numbers: list[str] = Field(default_factory=list)
    exporters: list[str] = Field(default_factory=list)
    buyers: list[str] = Field(default_factory=list)
    is_linked: bool = False


class AuditListResponse(BaseModel):
    analyses: list[AuditSummaryItem]
    total: int
    page: int = 1
    page_size: int = 20
    total_pages: int = 1



class ShipmentCreate(BaseModel):
    reference: str = Field(..., min_length=1, max_length=100, description="Unique human-facing shipment reference")
    exporter: str | None = None
    buyer: str | None = None
    product_description: str | None = None
    destination_country: str | None = None
    destination_port: str | None = None
    planned_shipment_date: str | None = None
    incoterm: str | None = None
    named_place: str | None = None
    notes: str | None = None


class ShipmentUpdate(BaseModel):
    reference: str | None = Field(default=None, min_length=1, max_length=100)
    exporter: str | None = None
    buyer: str | None = None
    product_description: str | None = None
    destination_country: str | None = None
    destination_port: str | None = None
    planned_shipment_date: str | None = None
    incoterm: str | None = None
    named_place: str | None = None
    notes: str | None = None
    status: str | None = None


class ShipmentResponse(BaseModel):
    id: str
    reference: str
    exporter: str | None = None
    buyer: str | None = None
    product_description: str | None = None
    destination_country: str | None = None
    destination_port: str | None = None
    planned_shipment_date: str | None = None
    incoterm: str | None = None
    named_place: str | None = None
    notes: str | None = None
    status: str = "draft"
    created_at: str
    updated_at: str
    analysis_count: int = 0
    document_count: int = 0
    latest_analysis_status: str | None = None


class ShipmentListResponse(BaseModel):
    shipments: list[ShipmentResponse]
    total: int


class DocumentResponse(BaseModel):
    id: str
    shipment_id: str
    original_filename: str
    clean_filename: str
    document_type: str
    uploaded_at: str
    storage_key: str
    file_size: int
    file_hash: str
    processing_status: str
    review_status: Literal["uploaded", "needs_review", "verified_by_user", "not_applicable"]
    notes: str | None = None
    last_reviewed_by: str | None = None
    last_reviewed_at: str | None = None
    review_notes: str | None = None
    created_at: str
    updated_at: str
    shared_with_customer: bool | None = False
    shared_with_supplier: bool | None = False
    shared_at: str | None = None
    shared_by: str | None = None
    sharing_notes: str | None = None


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int


class DocumentUpdate(BaseModel):
    document_type: str | None = None
    review_status: (
        Literal["uploaded", "needs_review", "verified_by_user", "not_applicable", "superseded", "rejected"] | None
    ) = None
    notes: str | None = None
    last_reviewed_by: str | None = None
    review_notes: str | None = None
    shared_with_customer: bool | None = None
    shared_with_supplier: bool | None = None
    sharing_notes: str | None = None


class ReadinessChecklistItem(BaseModel):
    id: str
    title: str
    document_type: str
    required: bool
    status: Literal["missing", "uploaded", "needs_review", "verified_by_user", "not_applicable"]
    attached_document_id: str | None = None
    attached_filename: str | None = None
    detail: str


class ShipmentReadinessResponse(BaseModel):
    shipment_id: str
    status: Literal["ready", "ready_with_warnings", "not_ready"]
    is_ready: bool
    uploaded_document_count: int
    missing_documents: list[str]
    unresolved_critical_discrepancies: int
    unresolved_warning_discrepancies: int
    outstanding_human_reviews: int
    planned_shipment_date: str | None = None
    last_reconciliation_timestamp: str | None = None
    last_reconciliation_id: str | None = None
    last_reconciliation_status: str | None = None
    checklist: list[ReadinessChecklistItem]
    reasons: list[str]
    disclaimer: str


# ==========================================
# CBM & Cargo Logistics Schemas
# ==========================================


class CargoLineRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=200)
    length: float = Field(..., gt=0)
    width: float = Field(..., gt=0)
    height: float = Field(..., gt=0)
    dimension_unit: Literal["mm", "cm", "m", "inch", "inches", "in", "foot", "feet", "ft"] = "cm"
    gross_weight_per_pkg: float = Field(default=0.0, ge=0)
    weight_unit: Literal["kg", "kilogram", "lb", "lbs", "pound"] = "kg"
    quantity: int = Field(default=1, ge=1, le=1000000)
    sku: str | None = None
    package_type: str = "carton"
    notes: str | None = None


class CargoLineResponse(BaseModel):
    id: str | None = None
    description: str
    sku: str | None = None
    package_type: str
    quantity: int
    length_orig: float
    width_orig: float
    height_orig: float
    dimension_unit: str
    gross_weight_orig: float
    weight_unit: str
    length_m: float
    width_m: float
    height_m: float
    weight_kg: float
    cbm_per_pkg: float
    total_cbm: float
    total_cuft: float
    total_gross_weight_kg: float
    total_gross_weight_lb: float
    volumetric_weight_kg: float
    notes: str | None = None


class CargoCalculationRequest(BaseModel):
    items: list[CargoLineRequest] = Field(default_factory=list)
    freight_mode: Literal["sea", "air", "road", "general"] = "general"
    dimensional_divisor: float = Field(default=6000.0, gt=0)
    per_package_chargeable_rounding: bool = False
    title: str | None = None
    shipment_id: str | None = None
    notes: str | None = None


class CargoCalculationResponse(BaseModel):
    total_packages: int
    total_cbm: float
    total_cuft: float
    total_gross_weight_kg: float
    total_gross_weight_lb: float
    total_volumetric_weight_kg: float
    chargeable_weight_kg: float
    dimensional_divisor_used: float
    freight_mode: str
    average_cbm_per_pkg: float
    average_weight_kg_per_pkg: float
    smallest_cbm_pkg: float
    largest_cbm_pkg: float
    lines: list[CargoLineResponse]


class ContainerEstimateRequest(BaseModel):
    package_length: float = Field(..., gt=0)
    package_width: float = Field(..., gt=0)
    package_height: float = Field(..., gt=0)
    dimension_unit: Literal["mm", "cm", "m", "inch", "inches", "in", "foot", "feet", "ft"] = "cm"
    package_weight: float = Field(default=0.0, ge=0)
    weight_unit: Literal["kg", "lb"] = "kg"
    usable_volume_ratio: float = Field(default=0.85, ge=0.1, le=1.0)
    custom_payload_capacity_kg: float | None = None


class ContainerEstimateResponse(BaseModel):
    container_key: str
    container_name: str
    internal_length_m: float
    internal_width_m: float
    internal_height_m: float
    nominal_volume_cbm: float
    usable_ratio: float
    usable_volume_cbm: float
    cargo_cbm: float
    volume_utilization_pct: float
    remaining_usable_cbm: float
    estimated_units_by_volume: int
    estimated_units_by_grid: int
    best_orientation: tuple[float, float, float] | None = None
    does_fit_geometrically: bool
    estimated_cargo_weight_at_grid_kg: float
    payload_capacity_kg: float | None = None
    payload_feasibility: str
    limitation_notes: str


class CargoCalculationRecord(BaseModel):
    id: str
    calculation_reference: str
    shipment_id: str | None = None
    title: str
    freight_mode: str
    dimensional_divisor: float
    volumetric_rounding: str
    total_packages: int
    total_cbm: float
    total_cuft: float
    total_gross_weight_kg: float
    total_gross_weight_lb: float
    total_volumetric_weight_kg: float
    chargeable_weight_kg: float
    notes: str | None = None
    created_at: str
    updated_at: str
    lines: list[CargoLineResponse] = Field(default_factory=list)


class CargoCalculationListResponse(BaseModel):
    calculations: list[CargoCalculationRecord]
    total: int
    page: int
    page_size: int
    total_pages: int


# ===========================================================================
# Milestone Phase 1: Master Data Schemas
# ===========================================================================

class ProductCreate(BaseModel):
    sku: str = Field(..., min_length=1, max_length=50, description="Unique product SKU")
    name: str = Field(..., min_length=1, max_length=255, description="Product name")
    description: str | None = None
    category: str = "General"
    uom: str = Field(default="PCS", min_length=1, max_length=20)
    purchase_uom: str | None = None
    conversion_factor: float = Field(default=1.0, gt=0.0)
    default_purchase_cost: float = Field(default=0.0, ge=0.0)
    default_selling_price: float = Field(default=0.0, ge=0.0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    hsn_code: str | None = None
    tax_rate_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    country_of_origin: str = Field(default="IN", min_length=2, max_length=3)
    net_weight_kg: float = Field(default=0.0, ge=0.0)
    gross_weight_kg: float = Field(default=0.0, ge=0.0)
    barcode: str | None = None
    batch_tracking: bool = False
    is_active: bool = True
    notes: str | None = None


class ProductUpdate(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    category: str | None = None
    uom: str | None = None
    purchase_uom: str | None = None
    conversion_factor: float | None = Field(default=None, gt=0.0)
    default_purchase_cost: float | None = Field(default=None, ge=0.0)
    default_selling_price: float | None = Field(default=None, ge=0.0)
    currency: str | None = None
    hsn_code: str | None = None
    tax_rate_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    country_of_origin: str | None = None
    net_weight_kg: float | None = Field(default=None, ge=0.0)
    gross_weight_kg: float | None = Field(default=None, ge=0.0)
    barcode: str | None = None
    batch_tracking: bool | None = None
    is_active: bool | None = None
    notes: str | None = None


class ProductResponse(BaseModel):
    id: str
    sku: str
    name: str
    description: str | None = None
    category: str
    uom: str
    purchase_uom: str | None = None
    conversion_factor: float
    default_purchase_cost: float
    default_selling_price: float
    currency: str
    hsn_code: str | None = None
    tax_rate_pct: float
    country_of_origin: str
    net_weight_kg: float
    gross_weight_kg: float
    barcode: str | None = None
    batch_tracking: bool
    is_active: bool
    notes: str | None = None
    created_at: str
    updated_at: str


class ProductListResponse(BaseModel):
    total: int
    items: list[ProductResponse]
    limit: int
    offset: int


class SupplierCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50, description="Unique supplier code")
    name: str = Field(..., min_length=1, max_length=255, description="Supplier trade name")
    legal_name: str | None = None
    tax_id: str | None = Field(default=None, description="GSTIN / VAT / Tax ID")
    country: str = Field(default="IN", min_length=2, max_length=3)
    state: str | None = None
    address: str | None = None
    contact_person: str | None = None
    email: str | None = None
    phone: str | None = None
    currency: str = Field(default="INR", min_length=3, max_length=3)
    payment_terms: str = "Net 30"
    payment_terms_days: int = Field(default=30, ge=0)
    bank_name: str | None = None
    bank_account_no: str | None = None
    bank_ifsc_swift: str | None = None
    status: str = "active"
    notes: str | None = None


class SupplierUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    legal_name: str | None = None
    tax_id: str | None = None
    country: str | None = None
    state: str | None = None
    address: str | None = None
    contact_person: str | None = None
    email: str | None = None
    phone: str | None = None
    currency: str | None = None
    payment_terms: str | None = None
    payment_terms_days: int | None = Field(default=None, ge=0)
    bank_name: str | None = None
    bank_account_no: str | None = None
    bank_ifsc_swift: str | None = None
    status: str | None = None
    notes: str | None = None


class SupplierResponse(BaseModel):
    id: str
    code: str
    name: str
    legal_name: str | None = None
    tax_id: str | None = None
    country: str
    state: str | None = None
    address: str | None = None
    contact_person: str | None = None
    email: str | None = None
    phone: str | None = None
    currency: str
    payment_terms: str
    payment_terms_days: int
    bank_name: str | None = None
    bank_account_no: str | None = None
    bank_ifsc_swift: str | None = None
    status: str
    notes: str | None = None
    created_at: str
    updated_at: str


class SupplierListResponse(BaseModel):
    total: int
    items: list[SupplierResponse]
    limit: int
    offset: int


class CustomerCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50, description="Unique customer code")
    name: str = Field(..., min_length=1, max_length=255, description="Customer name")
    legal_name: str | None = None
    tax_id: str | None = None
    customer_type: str = Field(default="international", description="'domestic' or 'international'")
    country: str = Field(..., min_length=2, max_length=3)
    destination_port: str | None = None
    billing_address: str | None = None
    shipping_address: str | None = None
    contact_person: str | None = None
    email: str | None = None
    phone: str | None = None
    currency: str = Field(default="USD", min_length=3, max_length=3)
    payment_terms: str = "LC at sight"
    payment_terms_days: int = Field(default=30, ge=0)
    credit_limit: float = Field(default=0.0, ge=0.0)
    incoterm_preference: str = "FOB"
    status: str = "active"
    notes: str | None = None


class CustomerUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    legal_name: str | None = None
    tax_id: str | None = None
    customer_type: str | None = None
    country: str | None = None
    destination_port: str | None = None
    billing_address: str | None = None
    shipping_address: str | None = None
    contact_person: str | None = None
    email: str | None = None
    phone: str | None = None
    currency: str | None = None
    payment_terms: str | None = None
    payment_terms_days: int | None = Field(default=None, ge=0)
    credit_limit: float | None = Field(default=None, ge=0.0)
    incoterm_preference: str | None = None
    status: str | None = None
    notes: str | None = None


class CustomerResponse(BaseModel):
    id: str
    code: str
    name: str
    legal_name: str | None = None
    tax_id: str | None = None
    customer_type: str
    country: str
    destination_port: str | None = None
    billing_address: str | None = None
    shipping_address: str | None = None
    contact_person: str | None = None
    email: str | None = None
    phone: str | None = None
    currency: str
    payment_terms: str
    payment_terms_days: int
    credit_limit: float
    incoterm_preference: str
    status: str
    notes: str | None = None
    created_at: str
    updated_at: str


class CustomerListResponse(BaseModel):
    total: int
    items: list[CustomerResponse]
    limit: int
    offset: int


class AuditLogEntry(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    action: str
    performed_by: str
    changes: dict[str, Any] = Field(default_factory=dict)
    timestamp: str


class AuditLogListResponse(BaseModel):
    total: int
    items: list[AuditLogEntry]
    limit: int
    offset: int


# ===========================================================================
# Milestone Phase 2: Procurement & Goods Receipt Schemas
# ===========================================================================

class PurchaseOrderItemCreate(BaseModel):
    product_id: str
    ordered_qty: float = Field(..., gt=0, description="Quantity to purchase (must be > 0)")
    unit_price: float = Field(..., ge=0, description="Agreed purchase price per unit")
    tax_rate_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Tax rate percentage")


class PurchaseOrderItemResponse(BaseModel):
    id: str
    po_id: str
    product_id: str
    sku: str
    product_name: str
    uom: str
    ordered_qty: float
    unit_price: float
    tax_rate_pct: float
    line_total: float
    received_qty: float
    sort_order: int
    created_at: str
    updated_at: str


class PurchaseOrderCreate(BaseModel):
    po_number: str = Field(..., min_length=2, max_length=50, description="Unique purchase order reference")
    supplier_id: str = Field(..., description="Target supplier ID")
    order_date: str = Field(..., description="Order date YYYY-MM-DD")
    expected_delivery_date: str | None = None
    currency: str = Field(default="INR", min_length=3, max_length=3)
    payment_terms: str = "Net 30"
    notes: str | None = None
    items: list[PurchaseOrderItemCreate] = Field(..., min_length=1, description="List of purchase order lines")


class PurchaseOrderUpdate(BaseModel):
    expected_delivery_date: str | None = None
    payment_terms: str | None = None
    notes: str | None = None
    items: list[PurchaseOrderItemCreate] | None = None


class PurchaseOrderResponse(BaseModel):
    id: str
    po_number: str
    supplier_id: str
    supplier_name: str | None = None
    order_date: str
    expected_delivery_date: str | None = None
    currency: str
    payment_terms: str
    subtotal: float
    tax_total: float
    grand_total: float
    status: str
    notes: str | None = None
    created_by: str
    created_at: str
    updated_at: str
    supplier_ack_status: str | None = "unacknowledged"
    supplier_ack_at: str | None = None
    supplier_ack_by: str | None = None
    supplier_ack_notes: str | None = None
    supplier_proposed_delivery_date: str | None = None
    items: list[PurchaseOrderItemResponse] = []


class PurchaseOrderListResponse(BaseModel):
    total: int
    items: list[PurchaseOrderResponse]
    limit: int
    offset: int


class GoodsReceiptItemCreate(BaseModel):
    po_item_id: str
    received_qty: float = Field(..., ge=0, description="Total physical quantity received at dock")
    accepted_qty: float = Field(default=0.0, ge=0, description="Accepted quantity after QA inspection")
    rejected_qty: float = Field(default=0.0, ge=0, description="Rejected quantity")
    quarantined_qty: float = Field(default=0.0, ge=0, description="Quarantined quantity pending QA review")
    inspection_notes: str | None = None
    rejection_reason: str | None = None
    inspection_status: str = Field(default="pending", description="pending, passed, rejected, quarantine")


class GoodsReceiptItemResponse(BaseModel):
    id: str
    receipt_id: str
    po_item_id: str
    product_id: str
    sku: str
    product_name: str
    uom: str
    unit_cost: float
    received_qty: float
    accepted_qty: float
    rejected_qty: float
    quarantined_qty: float
    inspection_notes: str | None = None
    rejection_reason: str | None = None
    inspection_status: str
    inspected_by: str | None = None
    inspected_at: str | None = None
    created_at: str


class GoodsReceiptCreate(BaseModel):
    receipt_number: str = Field(..., min_length=2, max_length=50, description="Unique goods receipt reference")
    idempotency_key: str = Field(..., min_length=8, max_length=100, description="Client idempotency key")
    po_id: str = Field(..., description="Target purchase order ID")
    receipt_date: str = Field(..., description="Receipt date YYYY-MM-DD")
    notes: str | None = None
    items: list[GoodsReceiptItemCreate] = Field(..., min_length=1, description="Receipt lines")


class GoodsReceiptInspectionUpdate(BaseModel):
    items: list[GoodsReceiptItemCreate] = Field(..., min_length=1)
    notes: str | None = None


class GoodsReceiptResponse(BaseModel):
    id: str
    receipt_number: str
    idempotency_key: str
    po_id: str
    po_number: str | None = None
    supplier_id: str
    supplier_name: str | None = None
    receipt_date: str
    received_by: str
    status: str
    notes: str | None = None
    created_at: str
    updated_at: str
    items: list[GoodsReceiptItemResponse] = []


class GoodsReceiptListResponse(BaseModel):
    total: int
    items: list[GoodsReceiptResponse]
    limit: int
    offset: int


class InventoryMovementResponse(BaseModel):
    id: str
    movement_number: str
    idempotency_key: str
    movement_type: str
    reference_doc_type: str
    reference_doc_id: str
    product_id: str
    sku: str
    product_name: str | None = None
    quantity: float
    stock_type: str
    unit_cost: float
    total_cost: float
    performed_by: str
    notes: str | None = None
    created_at: str


class InventoryMovementListResponse(BaseModel):
    total: int
    items: list[InventoryMovementResponse]
    limit: int
    offset: int


class InventoryBalanceResponse(BaseModel):
    product_id: str
    sku: str
    product_name: str | None = None
    stock_type: str
    on_hand_qty: float
    total_value: float
    updated_at: str


class InventoryBalanceListResponse(BaseModel):
    total: int
    items: list[InventoryBalanceResponse]


# ==========================================
# Milestone Phase 3: Warehouse & Storage Locations Schemas
# ==========================================

class WarehouseCreateRequest(BaseModel):
    code: str
    name: str
    address: str | None = None
    city: str | None = None
    country: str = "IN"


class WarehouseUpdateRequest(BaseModel):
    name: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None
    is_active: bool | None = None


class WarehouseResponse(BaseModel):
    id: str
    code: str
    name: str
    address: str | None = None
    city: str | None = None
    country: str
    is_active: bool
    created_at: str
    updated_at: str


class WarehouseListResponse(BaseModel):
    total: int
    items: list[WarehouseResponse]


class WarehouseLocationCreateRequest(BaseModel):
    warehouse_id: str
    location_code: str
    zone: str | None = None
    rack: str | None = None
    shelf: str | None = None
    bin: str | None = None


class WarehouseLocationUpdateRequest(BaseModel):
    zone: str | None = None
    rack: str | None = None
    shelf: str | None = None
    bin: str | None = None
    is_active: bool | None = None


class WarehouseLocationResponse(BaseModel):
    id: str
    warehouse_id: str
    warehouse_code: str | None = None
    location_code: str
    zone: str | None = None
    rack: str | None = None
    shelf: str | None = None
    bin: str | None = None
    is_active: bool
    created_at: str
    updated_at: str


class WarehouseLocationListResponse(BaseModel):
    total: int
    items: list[WarehouseLocationResponse]


# ==========================================
# Milestone Phase 3: Stock Transfers Schemas
# ==========================================

class StockTransferItemCreate(BaseModel):
    product_id: str
    requested_quantity: float
    notes: str | None = None


class StockTransferCreateRequest(BaseModel):
    source_warehouse_id: str
    source_location_id: str | None = None
    dest_warehouse_id: str
    dest_location_id: str | None = None
    notes: str | None = None
    items: list[StockTransferItemCreate]
    idempotency_key: str | None = None


class StockTransferItemResponse(BaseModel):
    id: str
    transfer_id: str
    product_id: str
    sku: str
    product_name: str
    requested_quantity: float
    dispatched_quantity: float
    received_quantity: float
    damaged_quantity: float
    shortage_quantity: float
    uom: str
    discrepancy_reason: str | None = None
    notes: str | None = None


class StockTransferResponse(BaseModel):
    id: str
    transfer_number: str
    idempotency_key: str | None = None
    source_warehouse_id: str
    source_warehouse_code: str | None = None
    source_location_id: str | None = None
    source_location_code: str | None = None
    dest_warehouse_id: str
    dest_warehouse_code: str | None = None
    dest_location_id: str | None = None
    dest_location_code: str | None = None
    status: str
    created_by: str
    approved_by: str | None = None
    dispatched_by: str | None = None
    received_by: str | None = None
    notes: str | None = None
    created_at: str
    updated_at: str
    approved_at: str | None = None
    dispatched_at: str | None = None
    received_at: str | None = None
    items: list[StockTransferItemResponse] = []


class StockTransferListResponse(BaseModel):
    total: int
    items: list[StockTransferResponse]


class StockTransferReceiveItemRequest(BaseModel):
    item_id: str
    received_quantity: float
    damaged_quantity: float = 0.0
    discrepancy_reason: str | None = None


class StockTransferReceiveRequest(BaseModel):
    items: list[StockTransferReceiveItemRequest]
    notes: str | None = None
    idempotency_key: str | None = None


# ==========================================
# Milestone Phase 3: Inventory Adjustments Schemas
# ==========================================

class InventoryAdjustmentCreateRequest(BaseModel):
    product_id: str
    warehouse_id: str
    location_id: str | None = None
    stock_type: str = "available"
    system_quantity: float
    counted_quantity: float
    reason_code: str
    notes: str | None = None
    idempotency_key: str | None = None


class InventoryAdjustmentResponse(BaseModel):
    id: str
    adjustment_number: str
    idempotency_key: str | None = None
    product_id: str
    sku: str
    product_name: str | None = None
    warehouse_id: str
    warehouse_code: str | None = None
    location_id: str | None = None
    location_code: str | None = None
    stock_type: str
    system_quantity: float
    counted_quantity: float
    difference_quantity: float
    uom: str
    reason_code: str
    notes: str | None = None
    status: str
    created_by: str
    approved_by: str | None = None
    approved_at: str | None = None
    created_at: str
    updated_at: str


class InventoryAdjustmentListResponse(BaseModel):
    total: int
    items: list[InventoryAdjustmentResponse]


# ==========================================
# Milestone Phase 3: Stock Reservations Schemas
# ==========================================

class StockReservationCreateRequest(BaseModel):
    product_id: str
    warehouse_id: str
    location_id: str | None = None
    quantity: float
    reference_type: str = "manual"
    reference_id: str | None = None
    expires_at: str | None = None
    notes: str | None = None
    idempotency_key: str | None = None


class StockReservationResponse(BaseModel):
    id: str
    reservation_number: str
    idempotency_key: str | None = None
    product_id: str
    sku: str
    product_name: str | None = None
    warehouse_id: str
    warehouse_code: str | None = None
    location_id: str | None = None
    location_code: str | None = None
    quantity: float
    uom: str
    reference_type: str
    reference_id: str | None = None
    status: str
    notes: str | None = None
    reserved_by: str
    released_by: str | None = None
    consumed_by: str | None = None
    expires_at: str | None = None
    created_at: str
    updated_at: str


class StockReservationListResponse(BaseModel):
    total: int
    items: list[StockReservationResponse]


# ==========================================
# Milestone Phase 3: Reports Schemas
# ==========================================

class ProductStockBalanceDetail(BaseModel):
    product_id: str
    sku: str
    product_name: str
    uom: str
    on_hand_qty: float
    available_qty: float
    reserved_qty: float
    available_to_promise: float
    quarantined_qty: float
    rejected_qty: float
    in_transit_qty: float
    reorder_threshold: float
    is_low_stock: bool


class ProductStockBalanceReportResponse(BaseModel):
    total: int
    items: list[ProductStockBalanceDetail]


class WarehouseLocationStockDetail(BaseModel):
    warehouse_id: str
    warehouse_code: str
    warehouse_name: str
    location_id: str | None = None
    location_code: str | None = None
    product_id: str
    sku: str
    product_name: str
    stock_type: str
    on_hand_qty: float
    uom: str


class WarehouseStockReportResponse(BaseModel):
    total: int
    items: list[WarehouseLocationStockDetail]


class ReconciliationItem(BaseModel):
    product_id: str
    sku: str
    stock_type: str
    balance_on_hand: float
    ledger_sum_qty: float
    discrepancy: float
    is_reconciled: bool


class ReconciliationReportResponse(BaseModel):
    is_fully_reconciled: bool
    total_checked: int
    discrepancies_found: int
    items: list[ReconciliationItem]


# ==========================================
# Phase 4: Sales Orders & Fulfilment Schemas
# ==========================================

class QuotationItemCreate(BaseModel):
    product_id: str
    quantity: float
    unit_price: float
    discount_pct: float = 0.0
    tax_rate_pct: float = 0.0


class QuotationCreateRequest(BaseModel):
    customer_id: str
    quotation_date: str | None = None
    valid_until: str | None = None
    currency: str = "USD"
    notes: str | None = None
    items: list[QuotationItemCreate] = Field(default_factory=list)


class QuotationUpdateRequest(BaseModel):
    quotation_date: str | None = None
    valid_until: str | None = None
    currency: str | None = None
    notes: str | None = None
    items: list[QuotationItemCreate] | None = None


class QuotationItemResponse(BaseModel):
    id: str
    quotation_id: str
    product_id: str
    sku: str
    product_name: str
    uom: str
    quantity: float
    unit_price: float
    discount_pct: float
    tax_rate_pct: float
    line_subtotal: float
    line_discount: float
    line_tax: float
    line_total: float


class QuotationResponse(BaseModel):
    id: str
    quotation_number: str
    quotation_version: int
    customer_id: str
    customer_code: str
    customer_name: str
    billing_address: str | None = None
    shipping_address: str | None = None
    contact_email: str | None = None
    tax_id: str | None = None
    quotation_date: str
    valid_until: str | None = None
    currency: str
    subtotal: float
    discount_total: float
    tax_total: float
    grand_total: float
    status: str
    notes: str | None = None
    created_by: str | None = None
    updated_by: str | None = None
    created_at: str
    updated_at: str
    items: list[QuotationItemResponse] = Field(default_factory=list)


class QuotationListResponse(BaseModel):
    total: int
    items: list[QuotationResponse]


class QuotationConvertRequest(BaseModel):
    requested_delivery_date: str | None = None
    payment_terms: str | None = "Net 30"
    delivery_address: str | None = None
    notes: str | None = None


# Sales Order Schemas
class SalesOrderItemCreate(BaseModel):
    product_id: str
    ordered_quantity: float
    unit_price: float
    discount_pct: float = 0.0
    tax_rate_pct: float = 0.0


class SalesOrderCreateRequest(BaseModel):
    customer_id: str
    quotation_id: str | None = None
    order_date: str | None = None
    requested_delivery_date: str | None = None
    currency: str = "USD"
    payment_terms: str | None = "Net 30"
    delivery_address: str | None = None
    notes: str | None = None
    shipment_id: str | None = None
    items: list[SalesOrderItemCreate] = Field(default_factory=list)


class SalesOrderUpdateRequest(BaseModel):
    order_date: str | None = None
    requested_delivery_date: str | None = None
    currency: str | None = None
    payment_terms: str | None = None
    delivery_address: str | None = None
    notes: str | None = None
    shipment_id: str | None = None
    items: list[SalesOrderItemCreate] | None = None


class SalesOrderItemResponse(BaseModel):
    id: str
    sales_order_id: str
    product_id: str
    sku: str
    product_name: str
    uom: str
    ordered_quantity: float
    allocated_quantity: float
    picked_quantity: float
    packed_quantity: float
    dispatched_quantity: float
    delivered_quantity: float
    unit_price: float
    discount_pct: float
    tax_rate_pct: float
    line_subtotal: float
    line_discount: float
    line_tax: float
    line_total: float


class SalesOrderResponse(BaseModel):
    id: str
    order_number: str
    quotation_id: str | None = None
    customer_id: str
    customer_code: str
    customer_name: str
    billing_address: str | None = None
    shipping_address: str | None = None
    contact_email: str | None = None
    tax_id: str | None = None
    order_date: str
    requested_delivery_date: str | None = None
    currency: str
    payment_terms: str | None = None
    delivery_address: str | None = None
    status: str
    subtotal: float
    discount_total: float
    tax_total: float
    grand_total: float
    notes: str | None = None
    shipment_id: str | None = None
    created_by: str | None = None
    updated_by: str | None = None
    created_at: str
    updated_at: str
    items: list[SalesOrderItemResponse] = Field(default_factory=list)


class SalesOrderListResponse(BaseModel):
    total: int
    items: list[SalesOrderResponse]


class SalesOrderAllocateRequest(BaseModel):
    warehouse_id: str
    auto_allocate_all: bool = True


# Picking & Packing Schemas
class SalesPickItemCreate(BaseModel):
    order_item_id: str
    quantity_to_pick: float
    location_id: str | None = None


class SalesPickListCreateRequest(BaseModel):
    sales_order_id: str
    warehouse_id: str
    assigned_picker: str | None = None
    notes: str | None = None
    items: list[SalesPickItemCreate] | None = None


class SalesPickItemRecord(BaseModel):
    pick_item_id: str
    picked_quantity: float
    short_picked_quantity: float = 0.0
    short_pick_reason: str | None = None


class SalesPickListCompleteRequest(BaseModel):
    items: list[SalesPickItemRecord] = Field(default_factory=list)
    notes: str | None = None


class SalesPickItemResponse(BaseModel):
    id: str
    pick_list_id: str
    order_item_id: str
    product_id: str
    sku: str
    product_name: str
    location_id: str | None = None
    location_code: str | None = None
    reserved_quantity: float
    picked_quantity: float
    short_picked_quantity: float
    short_pick_reason: str | None = None
    is_short_picked: bool
    picked_at: str | None = None


class SalesPickListResponse(BaseModel):
    id: str
    pick_list_number: str
    sales_order_id: str
    order_number: str | None = None
    warehouse_id: str
    warehouse_code: str | None = None
    status: str
    assigned_picker: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    notes: str | None = None
    created_by: str | None = None
    created_at: str
    updated_at: str
    items: list[SalesPickItemResponse] = Field(default_factory=list)


class SalesPickListListResponse(BaseModel):
    total: int
    items: list[SalesPickListResponse]


class SalesOrderPackRequest(BaseModel):
    notes: str | None = None


# Commercial Dispatch Schemas
class SalesDispatchItemCreate(BaseModel):
    order_item_id: str
    quantity_dispatched: float


class SalesDispatchCreateRequest(BaseModel):
    sales_order_id: str
    warehouse_id: str
    carrier_name: str | None = None
    tracking_number: str | None = None
    vehicle_number: str | None = None
    package_count: int | None = 1
    total_weight_kg: float | None = None
    dispatch_date: str | None = None
    notes: str | None = None
    idempotency_key: str | None = None
    shipment_id: str | None = None
    items: list[SalesDispatchItemCreate] = Field(default_factory=list)


class SalesDispatchItemDeliveryRecord(BaseModel):
    dispatch_item_id: str
    quantity_delivered: float
    quantity_damaged: float = 0.0
    quantity_rejected: float = 0.0
    discrepancy_notes: str | None = None


class SalesDispatchDeliveryRequest(BaseModel):
    delivery_date: str | None = None
    delivered_by: str | None = None
    notes: str | None = None
    items: list[SalesDispatchItemDeliveryRecord] = Field(default_factory=list)


class SalesDispatchItemResponse(BaseModel):
    id: str
    dispatch_id: str
    order_item_id: str
    product_id: str
    sku: str
    quantity_dispatched: float
    quantity_delivered: float
    quantity_damaged: float
    quantity_rejected: float
    discrepancy_notes: str | None = None


class SalesDispatchResponse(BaseModel):
    id: str
    dispatch_number: str
    idempotency_key: str | None = None
    payload_hash: str | None = None
    sales_order_id: str
    order_number: str | None = None
    warehouse_id: str
    warehouse_code: str | None = None
    carrier_name: str | None = None
    tracking_number: str | None = None
    vehicle_number: str | None = None
    package_count: int | None = 1
    total_weight_kg: float | None = None
    dispatch_date: str
    status: str
    dispatched_by: str | None = None
    delivery_date: str | None = None
    delivered_by: str | None = None
    shipment_id: str | None = None
    notes: str | None = None
    created_at: str
    updated_at: str
    items: list[SalesDispatchItemResponse] = Field(default_factory=list)


class SalesDispatchListResponse(BaseModel):
    total: int
    items: list[SalesDispatchResponse]


# Returns Schemas
class SalesReturnItemCreate(BaseModel):
    order_item_id: str
    returned_quantity: float
    accepted_quantity: float = 0.0
    quarantined_quantity: float = 0.0
    rejected_quantity: float = 0.0
    warehouse_id: str | None = None
    location_id: str | None = None
    inspection_notes: str | None = None


class SalesReturnCreateRequest(BaseModel):
    sales_order_id: str
    dispatch_id: str | None = None
    reason: str
    notes: str | None = None
    items: list[SalesReturnItemCreate] = Field(default_factory=list)


class SalesReturnProcessRequest(BaseModel):
    items: list[SalesReturnItemCreate] = Field(default_factory=list)
    notes: str | None = None


class SalesReturnItemResponse(BaseModel):
    id: str
    return_id: str
    order_item_id: str
    product_id: str
    sku: str
    returned_quantity: float
    accepted_quantity: float
    quarantined_quantity: float
    rejected_quantity: float
    warehouse_id: str | None = None
    location_id: str | None = None
    inspection_notes: str | None = None


class SalesReturnResponse(BaseModel):
    id: str
    return_number: str
    sales_order_id: str
    order_number: str | None = None
    dispatch_id: str | None = None
    customer_id: str
    customer_name: str | None = None
    return_date: str
    reason: str
    status: str
    received_by: str | None = None
    inspected_by: str | None = None
    notes: str | None = None
    created_at: str
    updated_at: str
    items: list[SalesReturnItemResponse] = Field(default_factory=list)


class SalesReturnListResponse(BaseModel):
    total: int
    items: list[SalesReturnResponse]


# ==========================================
# Phase 5: Export Operations Schemas
# ==========================================


class ExportShipmentCreate(BaseModel):
    reference: str = Field(..., min_length=1, max_length=100)
    customer_id: str | None = None
    consignee_name: str | None = None
    consignee_address: str | None = None
    exporter_name: str | None = None
    exporter_address: str | None = None
    product_description: str | None = None
    destination_country: str | None = None
    port_of_loading: str | None = None
    port_of_discharge: str | None = None
    transport_mode: str = "sea"
    carrier_name: str | None = None
    vessel_name: str | None = None
    voyage_flight_no: str | None = None
    booking_reference: str | None = None
    bill_of_lading_no: str | None = None
    airway_bill_no: str | None = None
    container_no: str | None = None
    seal_no: str | None = None
    package_count: int | None = Field(default=None, ge=0)
    gross_weight_kg: float | None = Field(default=None, ge=0.0)
    net_weight_kg: float | None = Field(default=None, ge=0.0)
    weight_uom: str = "KG"
    incoterm: str | None = None
    named_place: str | None = None
    planned_shipment_date: str | None = None
    estimated_departure_date: str | None = None
    actual_departure_date: str | None = None
    estimated_arrival_date: str | None = None
    actual_arrival_date: str | None = None
    notes: str | None = None


class ExportShipmentUpdate(BaseModel):
    reference: str | None = None
    customer_id: str | None = None
    consignee_name: str | None = None
    consignee_address: str | None = None
    exporter_name: str | None = None
    exporter_address: str | None = None
    product_description: str | None = None
    destination_country: str | None = None
    port_of_loading: str | None = None
    port_of_discharge: str | None = None
    transport_mode: str | None = None
    carrier_name: str | None = None
    vessel_name: str | None = None
    voyage_flight_no: str | None = None
    booking_reference: str | None = None
    bill_of_lading_no: str | None = None
    airway_bill_no: str | None = None
    container_no: str | None = None
    seal_no: str | None = None
    package_count: int | None = Field(default=None, ge=0)
    gross_weight_kg: float | None = Field(default=None, ge=0.0)
    net_weight_kg: float | None = Field(default=None, ge=0.0)
    weight_uom: str | None = None
    incoterm: str | None = None
    named_place: str | None = None
    planned_shipment_date: str | None = None
    estimated_departure_date: str | None = None
    actual_departure_date: str | None = None
    estimated_arrival_date: str | None = None
    actual_arrival_date: str | None = None
    notes: str | None = None


class ExportShipmentStatusUpdate(BaseModel):
    status: str = Field(..., description="Target lifecycle state")
    notes: str | None = None


class ExportShipmentDispatchLinkRequest(BaseModel):
    dispatch_id: str = Field(..., min_length=1)
    notes: str | None = None


class ExportChecklistRuleCreate(BaseModel):
    rule_name: str = Field(..., min_length=1, max_length=150)
    document_type: str = Field(..., min_length=1, max_length=100)
    destination_country: str | None = None
    product_category: str | None = None
    transport_mode: str | None = None
    customer_id: str | None = None
    requirement_level: str = Field(default="mandatory", description="mandatory, conditional, optional")
    reason: str = Field(..., min_length=1)
    is_active: bool = True


class ExportChecklistItemUpdate(BaseModel):
    status: str = Field(..., description="pending, submitted, received, under_review, approved, rejected, expired, superseded")
    document_id: str | None = None
    review_notes: str | None = None


class ExportDocumentGenerateRequest(BaseModel):
    template_type: str = Field(..., description="commercial_invoice, packing_list, shipping_instructions")
    title: str | None = None
    notes: str | None = None


class ExportDocumentReviewRequest(BaseModel):
    review_status: str = Field(..., description="approved or rejected")
    review_notes: str | None = None


# ==========================================
# Phase 6: Invoicing, Payments & GST Schemas
# ==========================================


class CustomerInvoiceItemCreate(BaseModel):
    sales_order_item_id: str | None = None
    product_id: str | None = None
    product_sku: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    hsn_code: str | None = None
    uom: str = "PCS"
    quantity: float = Field(..., gt=0)
    unit_price: float = Field(..., ge=0)
    discount_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    tax_classification: str = Field(default="taxable", description="taxable, exempt, nil_rated, zero_rated_export, non_gst")
    gst_rate_pct: float = Field(default=0.0, ge=0.0)


class CustomerInvoiceCreate(BaseModel):
    invoice_number: str | None = None
    customer_id: str = Field(..., min_length=1)
    place_of_supply: str = Field(default="19-West Bengal", description="State Code + Name e.g. 19-West Bengal or 27-Maharashtra")
    invoice_date: str = Field(..., description="YYYY-MM-DD")
    due_date: str = Field(..., description="YYYY-MM-DD")
    currency: str = Field(default="INR", description="INR, USD, EUR, AED, GBP")
    exchange_rate: float = Field(default=1.0, gt=0)
    payment_terms: str = "Net 30"
    payment_terms_days: int = Field(default=30, ge=0)
    sales_order_id: str | None = None
    dispatch_id: str | None = None
    export_shipment_id: str | None = None
    tax_scheme: str = Field(default="GST", description="GST, EXPORT_ZERO_RATED, EXPORT_LUT, SEZ, EXEMPT")
    lut_bond_number: str | None = None
    notes: str | None = None
    items: list[CustomerInvoiceItemCreate] = Field(..., min_length=1)


class CustomerInvoiceStatusUpdate(BaseModel):
    status: str = Field(..., description="approved, issued, cancelled, paid")
    reason: str | None = None


class CustomerPaymentCreate(BaseModel):
    payment_number: str | None = None
    customer_id: str = Field(..., min_length=1)
    payment_date: str = Field(..., description="YYYY-MM-DD")
    payment_method: str = Field(..., description="bank_transfer, wire_swift, letter_of_credit, cheque, upi, cash")
    reference_number: str | None = None
    currency: str = "INR"
    exchange_rate: float = Field(default=1.0, gt=0)
    amount: float = Field(..., gt=0)
    notes: str | None = None


class CustomerPaymentAllocationRequest(BaseModel):
    invoice_id: str = Field(..., min_length=1)
    amount: float = Field(..., gt=0)
    notes: str | None = None


class CustomerCreditNoteItemCreate(BaseModel):
    invoice_item_id: str | None = None
    product_sku: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    quantity: float = Field(..., gt=0)
    unit_price: float = Field(..., ge=0)
    gst_rate_pct: float = Field(default=0.0, ge=0.0)


class CustomerCreditNoteCreate(BaseModel):
    credit_note_number: str | None = None
    invoice_id: str = Field(..., min_length=1)
    credit_note_date: str | None = None
    reason: str = Field(..., description="goods_return, pricing_error, discount_adjustment, defective_goods, other")
    notes: str | None = None
    items: list[CustomerCreditNoteItemCreate] = Field(..., min_length=1)


