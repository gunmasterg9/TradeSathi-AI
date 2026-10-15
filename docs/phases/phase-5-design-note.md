# TradeSathi AI — Phase 5: Export Operations & Documentation Design Note

## 1. Overview and Architecture Principles

Phase 5 implements a robust, end-to-end export operations workflow that bridges commercial sales, fulfilment, shipment logistics, document preparation, and shipment readiness.

In strict compliance with TradeSathi AI safety principles:
- **No Competing Registries:** Existing `shipments` and `documents` tables are preserved and reused.
- **Additive Migrations Only:** New operational fields are added via nullable `ALTER TABLE ADD COLUMN` statements or new auxiliary tables, guaranteeing 100% backward compatibility with all historical shipments, documents, analyses, and reviews.
- **Deterministic Separation:** Software validation checks are strictly separated from official legal/customs advice. Uploaded or generated documents are never represented as officially cleared without human verification.
- **Strict Concurrency & Idempotency:** Linking dispatches to shipments enforces that no dispatch can be linked to multiple shipments simultaneously.

---

## 2. Reused Records & Schema Linkage

| Existing Entity | Current Record Count | Reused Attributes | Phase 5 Linkage & Extensions |
| :--- | :--- | :--- | :--- |
| **`shipments`** | 45 rows | `id`, `reference`, `exporter`, `buyer`, `product_description`, `destination_country`, `destination_port`, `planned_shipment_date`, `incoterm`, `status`, `notes` | Reused as the core export shipment entity. Additive columns for transport logistics (`customer_id`, `consignee_name`, `consignee_address`, `port_of_loading`, `port_of_discharge`, `transport_mode`, `carrier_name`, `vessel_name`, `voyage_flight_no`, `booking_reference`, `bill_of_lading_no`, `container_no`, `seal_no`, `package_count`, `gross_weight_kg`, `net_weight_kg`, `weight_uom`, `readiness_status`). |
| **`documents`** | 48 rows | `id`, `shipment_id`, `original_filename`, `clean_filename`, `document_type`, `storage_key`, `file_size`, `file_hash`, `review_status`, `notes` | Reused for export document registry. Additive versioning columns (`version`, `parent_document_id`, `is_current_version`, `issue_date`, `expiry_date`, `sales_order_id`, `dispatch_id`, `source`). |
| **`analyses`** | 330 rows | `id`, `shipment_id`, `status`, `response_json`, `discrepancy_count` | Reused for multi-document reconciliation evidence. |
| **`finding_reviews`** | 2 rows | `id`, `analysis_id`, `finding_id`, `reviewer`, `timestamp`, `corrected_value` | Reused for operator discrepancy resolution audit trail. |
| **`customers`** | Master data | `id`, `code`, `name`, `legal_name`, `country`, `destination_port` | Linked via `shipments.customer_id`. |
| **`sales_orders`** | Phase 4 | `id`, `order_number`, `customer_id`, `shipment_id`, `status`, `items` | Linked to shipment via `sales_orders.shipment_id`. |
| **`sales_dispatches`**| Phase 4 | `id`, `dispatch_number`, `sales_order_id`, `shipment_id`, `status`, `items` | Linked to shipment via `sales_dispatches.shipment_id` and tracked in `export_shipment_dispatches`. |

---

## 3. Detailed Data Models

### 3.1 Extended `shipments` Table (Additive Migration)
```sql
ALTER TABLE shipments ADD COLUMN customer_id TEXT;
ALTER TABLE shipments ADD COLUMN consignee_name TEXT;
ALTER TABLE shipments ADD COLUMN consignee_address TEXT;
ALTER TABLE shipments ADD COLUMN exporter_name TEXT;
ALTER TABLE shipments ADD COLUMN exporter_address TEXT;
ALTER TABLE shipments ADD COLUMN port_of_loading TEXT;
ALTER TABLE shipments ADD COLUMN port_of_discharge TEXT;
ALTER TABLE shipments ADD COLUMN transport_mode TEXT DEFAULT 'ocean';
ALTER TABLE shipments ADD COLUMN carrier_name TEXT;
ALTER TABLE shipments ADD COLUMN vessel_name TEXT;
ALTER TABLE shipments ADD COLUMN voyage_flight_no TEXT;
ALTER TABLE shipments ADD COLUMN booking_reference TEXT;
ALTER TABLE shipments ADD COLUMN bill_of_lading_no TEXT;
ALTER TABLE shipments ADD COLUMN airway_bill_no TEXT;
ALTER TABLE shipments ADD COLUMN container_no TEXT;
ALTER TABLE shipments ADD COLUMN seal_no TEXT;
ALTER TABLE shipments ADD COLUMN package_count INTEGER;
ALTER TABLE shipments ADD COLUMN gross_weight_kg REAL;
ALTER TABLE shipments ADD COLUMN net_weight_kg REAL;
ALTER TABLE shipments ADD COLUMN weight_uom TEXT DEFAULT 'KG';
ALTER TABLE shipments ADD COLUMN estimated_departure_date TEXT;
ALTER TABLE shipments ADD COLUMN actual_departure_date TEXT;
ALTER TABLE shipments ADD COLUMN estimated_arrival_date TEXT;
ALTER TABLE shipments ADD COLUMN actual_arrival_date TEXT;
ALTER TABLE shipments ADD COLUMN readiness_status TEXT DEFAULT 'not_evaluated';
```

### 3.2 Extended `documents` Table (Additive Migration)
```sql
ALTER TABLE documents ADD COLUMN version INTEGER DEFAULT 1;
ALTER TABLE documents ADD COLUMN parent_document_id TEXT;
ALTER TABLE documents ADD COLUMN is_current_version INTEGER DEFAULT 1;
ALTER TABLE documents ADD COLUMN issue_date TEXT;
ALTER TABLE documents ADD COLUMN expiry_date TEXT;
ALTER TABLE documents ADD COLUMN sales_order_id TEXT;
ALTER TABLE documents ADD COLUMN dispatch_id TEXT;
ALTER TABLE documents ADD COLUMN source TEXT DEFAULT 'upload';
```

### 3.3 New Table: `export_shipment_dispatches` (Multi-Dispatch Linkage Guard)
Ensures a commercial dispatch can only be linked to **one** export shipment, preventing double-exporting of fulfilled quantities:
```sql
CREATE TABLE IF NOT EXISTS export_shipment_dispatches (
    id TEXT PRIMARY KEY,
    shipment_id TEXT NOT NULL,
    dispatch_id TEXT NOT NULL UNIQUE,
    sales_order_id TEXT NOT NULL,
    linked_at TEXT NOT NULL,
    linked_by TEXT NOT NULL,
    FOREIGN KEY (shipment_id) REFERENCES shipments(id) ON DELETE CASCADE,
    FOREIGN KEY (dispatch_id) REFERENCES sales_dispatches(id) ON DELETE RESTRICT,
    FOREIGN KEY (sales_order_id) REFERENCES sales_orders(id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_esd_shipment ON export_shipment_dispatches(shipment_id);
CREATE INDEX IF NOT EXISTS idx_esd_dispatch ON export_shipment_dispatches(dispatch_id);
```

### 3.4 New Table: `export_checklist_rules` (Configurable Document Checklist Framework)
```sql
CREATE TABLE IF NOT EXISTS export_checklist_rules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    document_type TEXT NOT NULL,
    description TEXT,
    destination_country TEXT, -- NULL matches all countries
    product_category TEXT,     -- NULL matches all categories
    transport_mode TEXT,       -- ocean, air, road, rail, multimodal (NULL matches all)
    requirement_level TEXT NOT NULL DEFAULT 'mandatory' CHECK(requirement_level IN ('mandatory', 'conditional', 'optional')),
    rule_source TEXT NOT NULL DEFAULT 'standard_sop',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ecr_country ON export_checklist_rules(destination_country);
CREATE INDEX IF NOT EXISTS idx_ecr_active ON export_checklist_rules(is_active);
```

### 3.5 New Table: `export_shipment_checklist_items` (Shipment-Level Checklist State)
```sql
CREATE TABLE IF NOT EXISTS export_shipment_checklist_items (
    id TEXT PRIMARY KEY,
    shipment_id TEXT NOT NULL,
    document_type TEXT NOT NULL,
    title TEXT NOT NULL,
    requirement_level TEXT NOT NULL CHECK(requirement_level IN ('mandatory', 'conditional', 'optional')),
    rule_id TEXT,
    rule_source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'missing' CHECK(status IN ('missing', 'submitted', 'under_review', 'approved', 'rejected', 'expired', 'superseded', 'needs_confirmation')),
    document_id TEXT,
    reviewed_by TEXT,
    reviewed_at TEXT,
    review_notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (shipment_id) REFERENCES shipments(id) ON DELETE CASCADE,
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE SET NULL,
    FOREIGN KEY (rule_id) REFERENCES export_checklist_rules(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_esci_shipment ON export_shipment_checklist_items(shipment_id);
CREATE INDEX IF NOT EXISTS idx_esci_status ON export_shipment_checklist_items(status);
```

---

## 4. State Machines and Lifecycle Transitions

### 4.1 Export Shipment Status State Machine
- `draft`: Initial planning stage.
- `booked`: Carrier booking confirmed; vessel/voyage/flight assigned.
- `document_prep`: Compiling required export documents and packing.
- `ready_for_dispatch`: Internal paperwork, dispatches, and checks verified.
- `departed`: Vessel/flight departed port of loading.
- `arrived`: Arrived at destination port.
- `completed`: Delivery fulfilled, customs clearance confirmed by buyer.
- `cancelled`: Shipment cancelled. (Released dispatches can be re-allocated).

**Allowed Transitions:**
- `draft` -> `booked`, `cancelled`
- `booked` -> `document_prep`, `draft`, `cancelled`
- `document_prep` -> `ready_for_dispatch`, `booked`, `cancelled`
- `ready_for_dispatch` -> `departed`, `document_prep`, `cancelled`
- `departed` -> `arrived`, `cancelled`
- `arrived` -> `completed`

### 4.2 Document Review & Verification Lifecycle
- `missing`: Required item not yet attached.
- `submitted`: File uploaded, awaiting operator check.
- `under_review`: Discrepancy noted or operator actively inspecting.
- `approved`: Verified and signed off by authorized personnel.
- `rejected`: Incomplete, unreadable, or invalid; operator must re-upload.
- `expired`: Document issue/expiry date indicates expiration.
- `superseded`: Replaced by a newer version (e.g. v2 replaces v1).
- `needs_confirmation`: Destination or regulatory rules ambiguous/unconfirmed.

---

## 5. Shipment Readiness Service Architecture

The shipment readiness service evaluates 7 deterministic criteria:
1. **Mandatory Document Checklist:** Are all mandatory items attached and in `approved` status?
2. **Missing Document Count:** Number of mandatory checklist items in `missing` status.
3. **Pending Reviews:** Documents in `submitted` or `under_review` status.
4. **Expired Documents:** Any attached document where `expiry_date < current_date`.
5. **Reconciliation Audit Discrepancies:** Latest cross-document audit results (`analyses`):
   - Unresolved `critical` discrepancies: Hard blocker (`blocked`).
   - Unresolved `warning` discrepancies: Soft warning (`needs_review`).
6. **Fulfilment Reconciliation:** Dispatched quantities from linked sales dispatches match the export shipment's stated cargo package count and line items.
7. **Completeness of Mandatory Shipping Details:** Consignee, destination port, carrier/transport mode, and gross weight must be populated.

**Evaluated Readiness Statuses:**
- `blocked`: Missing mandatory documents, unresolved critical discrepancies, or expired certificates.
- `needs_review`: Outstanding human reviews, warnings, or unconfirmed checklist rules.
- `ready_for_review`: All documents uploaded, zero critical discrepancies, awaiting final sign-off.
- `internally_ready`: All internal paperwork, reconciliation, and logistics verified.
- **Mandatory Disclaimer:** *"Internal operational readiness assessment only. Does not constitute statutory customs clearance or official regulatory certification."*

---

## 6. Document Generation Architecture

Controlled file generation for 3 core export documents:
1. **Commercial Invoice:** Formatted trade document with exporter details, consignee details, sales order lines, incoterms, currency, subtotal, and tax breakdowns.
2. **Packing List:** Detailed package breakdown, carton count, gross weight, net weight, volume (CBM), and dimension specs.
3. **Shipping Instructions:** Transport routing, carrier name, port of loading/discharge, container/seal instructions, and consignee notify parties.

**Safety Controls:**
- Watermarked clearly as `DRAFT - NOT FOR OFFICIAL SUBMISSION` until reviewed.
- Generated documents are saved to the document register with `source = 'generated'` and `review_status = 'uploaded'`.
- Draft versions are never overwritten; regenerating creates a new version with incremented `version` number.

---

## 7. Role-Based Access Control (RBAC) & Separation of Duties

| Action | Allowed Roles | Rule Enforcement |
| :--- | :--- | :--- |
| **Create/Update Shipment** | `sales`, `admin` | Cannot edit departed or completed shipments. |
| **Link Dispatches** | `sales`, `warehouse`, `admin` | Dispatch must be `dispatched` status and not linked elsewhere. |
| **Upload Document / New Version** | `sales`, `warehouse`, `procurement`, `admin` | Generates new version; does not overwrite file. |
| **Approve Document** | `admin`, `sales` | **Separation of duties:** Uploader cannot approve their own document unless caller is `admin`. |
| **Generate Draft Documents** | `sales`, `admin` | Requires linked order and shipment header details. |
| **Read/View Export Operations** | All authenticated (`viewer`+) | Full read access to shipments, documents, checklist, readiness. |

---

## 8. Migration Safety & Live Data Protection

- Baseline live database `backend/tradesathi.db` (6,127,616 bytes) will remain untouched during development and testing.
- Automated testing will strictly utilize temporary SQLite databases in scratch locations (`TRADESATHI_TEST_MODE=1`).
- All migrations will be executed and verified twice against an isolated clone of the live populated database before any production deployment.
