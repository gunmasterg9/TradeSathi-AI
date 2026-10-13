from typing import Any, Literal
from pydantic import BaseModel, Field


class FieldEvidence(BaseModel):
    value: Any = None
    source_snippet: str | None = None
    confidence: float | None = None


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
    document_type: Literal[
        "commercial_invoice",
        "packing_list",
        "purchase_order",
        "shipping_instructions",
        "unknown",
    ] = "unknown"
    exporter: str | None = None
    buyer: str | None = None
    invoice_number: str | None = None
    purchase_order_number: str | None = None
    invoice_date: str | None = None
    currency: str | None = None
    total_amount: float | None = None
    total_net_weight_kg: float | None = None
    total_gross_weight_kg: float | None = None
    raw_net_weight: str | None = None
    raw_gross_weight: str | None = None
    packages: int | None = None
    package_type: str | None = None
    product_description: str | None = None
    hs_code: str | None = None
    incoterms: str | None = None
    country_of_origin: str | None = None
    port_of_loading: str | None = None
    port_of_discharge: str | None = None
    port_of_destination: str | None = None
    shipment_reference: str | None = None
    items: list[LineItem] = Field(default_factory=list)
    evidence: dict[str, str] = Field(default_factory=dict)
    field_evidence: dict[str, FieldEvidence] = Field(default_factory=dict)
    extraction_notes: list[str] = Field(default_factory=list)


class Discrepancy(BaseModel):
    field: str
    label: str
    severity: Literal["critical", "warning", "info"]
    doc_values: dict[str, Any] = Field(default_factory=dict)
    difference: str | None = None
    reason: str
    source_document: str | None = None
    recommended_action: str
    message: str


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


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int


class DocumentUpdate(BaseModel):
    document_type: str | None = None
    review_status: (
        Literal["uploaded", "needs_review", "verified_by_user", "not_applicable"] | None
    ) = None
    notes: str | None = None
    last_reviewed_by: str | None = None
    review_notes: str | None = None


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

