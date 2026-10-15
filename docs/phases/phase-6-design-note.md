# TradeSathi AI — Phase 6: Invoices, Payments & Indian GST Billing Design Note

**Document ID:** `docs/phases/phase-6-design-note.md`  
**Phase:** 6 — Commercial Finance, Invoicing, Payments, Indian GST & Multi-Currency  
**Target Database:** `backend/tradesathi.db` (Protected — Zero Writes during testing)  
**Primary Modules:** `backend/app/db.py`, `backend/app/schemas.py`, `backend/app/invoicing.py`, `frontend/src/InvoicingView.jsx`

---

## 1. Context & Objectives

Phase 6 implements the complete commercial finance layer of TradeSathi AI, connecting:
- Customer Master Data & Products Master Data
- Sales Orders, Pick Lists, and Commercial Dispatches (Phase 4)
- Export Shipments & Transport Routing (Phase 5)
- Document Evidence & Audit Logs (Phases 1–5)

### Core Financial Objectives
1. **Customer Invoicing:** Single and partial invoicing against sales orders and dispatches with cumulative quantity guards.
2. **Indian GST Calculation Framework:** Deterministic, versioned, configurable tax calculation engine distinguishing Intra-state (CGST + SGST), Inter-state (IGST), and Export Zero-Rated supplies (LUT / Bond vs. with payment of tax).
3. **Multi-Currency Architecture:** Explicit transaction vs. reporting base currency (`INR`), immutable exchange rate snapshots, and realized foreign exchange gain/loss tracking upon payment.
4. **Payment Recording & Allocation:** Multi-method payments (Wire, LC, Bank Transfer, Cheque) with partial and multi-invoice allocations.
5. **Credit Notes:** Immutable post-issue corrections, return reversals, and tax balance adjustments without modifying historical issued invoices.
6. **Receivables & Aging Reports:** Outstanding balance tracking categorized into standard aging buckets (`0–30`, `31–60`, `61–90`, `90+` days overdue).
7. **Statutory Non-Certification Notice:** Explicit disclaimer that invoice generation and tax summaries are internal commercial accounting records and do not constitute official statutory e-invoicing or tax portal filing without authorized verification.

---

## 2. Reused Records and Integration Touchpoints

TradeSathi AI reuses all existing commercial entities without duplicating records:
- **`customers`:** Reused for billing address snapshot, shipping address, tax ID (GSTIN/VAT), default currency, and payment terms days.
- **`products`:** Reused for SKU, description, unit of measure (`uom`), HSN/SAC code, and base tax rate percentage.
- **`sales_orders` & `sales_order_items`:** Linked via `sales_order_id` and `sales_order_item_id`. Invoices draw ordered quantities and unit prices directly from verified sales orders.
- **`sales_dispatches`:** Linked via `dispatch_id` to invoice against fulfilled and dispatched quantities.
- **`shipments` (Export Shipments):** Linked via `export_shipment_id` for export invoices, capturing shipping details, port of loading/discharge, and vessel/flight references.
- **`erp_audit_logs`:** Reused for append-only audit trail for every financial transaction (`invoice.created`, `invoice.issued`, `invoice.cancelled`, `payment.recorded`, `payment.allocated`, `credit_note.created`).

---

## 3. Database Schema Design (Additive & Non-Destructive)

### 3.1. `customer_invoices` Table
```sql
CREATE TABLE IF NOT EXISTS customer_invoices (
    id TEXT PRIMARY KEY,
    invoice_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
    customer_id TEXT NOT NULL,
    customer_code TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    billing_address TEXT NOT NULL,
    shipping_address TEXT,
    customer_tax_id TEXT,             -- Customer GSTIN / VAT No
    supplier_tax_id TEXT NOT NULL DEFAULT '19AAACT1234A1Z5', -- Seller GSTIN
    supplier_state_code TEXT NOT NULL DEFAULT '19',          -- West Bengal (19)
    place_of_supply TEXT NOT NULL DEFAULT '19-West Bengal',  -- POS State Code + Name
    invoice_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'INR',
    exchange_rate REAL NOT NULL DEFAULT 1.0,
    exchange_rate_date TEXT,
    payment_terms TEXT,
    payment_terms_days INTEGER NOT NULL DEFAULT 30,
    sales_order_id TEXT,
    dispatch_id TEXT,
    export_shipment_id TEXT,
    tax_scheme TEXT NOT NULL DEFAULT 'GST' CHECK(tax_scheme IN ('GST', 'EXPORT_ZERO_RATED', 'EXPORT_LUT', 'SEZ', 'EXEMPT')),
    lut_bond_number TEXT,
    subtotal REAL NOT NULL DEFAULT 0.0,
    discount_total REAL NOT NULL DEFAULT 0.0,
    cgst_total REAL NOT NULL DEFAULT 0.0,
    sgst_total REAL NOT NULL DEFAULT 0.0,
    igst_total REAL NOT NULL DEFAULT 0.0,
    tax_total REAL NOT NULL DEFAULT 0.0,
    grand_total REAL NOT NULL DEFAULT 0.0,
    amount_paid REAL NOT NULL DEFAULT 0.0,
    amount_credited REAL NOT NULL DEFAULT 0.0,
    outstanding_balance REAL NOT NULL DEFAULT 0.0,
    base_grand_total REAL NOT NULL DEFAULT 0.0,  -- In INR
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft', 'approved', 'issued', 'partially_paid', 'paid', 'overdue', 'credited', 'cancelled')),
    is_posted INTEGER NOT NULL DEFAULT 0,
    issued_at TEXT,
    issued_by TEXT,
    cancelled_at TEXT,
    cancelled_by TEXT,
    cancellation_reason TEXT,
    notes TEXT,
    created_by TEXT NOT NULL DEFAULT 'Local Operator',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT,
    FOREIGN KEY (sales_order_id) REFERENCES sales_orders(id) ON DELETE SET NULL,
    FOREIGN KEY (dispatch_id) REFERENCES sales_dispatches(id) ON DELETE SET NULL,
    FOREIGN KEY (export_shipment_id) REFERENCES shipments(id) ON DELETE SET NULL
);
```

### 3.2. `customer_invoice_items` Table
```sql
CREATE TABLE IF NOT EXISTS customer_invoice_items (
    id TEXT PRIMARY KEY,
    invoice_id TEXT NOT NULL,
    sales_order_item_id TEXT,
    product_id TEXT,
    product_sku TEXT NOT NULL,
    description TEXT NOT NULL,
    hsn_code TEXT,
    uom TEXT NOT NULL DEFAULT 'PCS',
    quantity REAL NOT NULL CHECK(quantity > 0),
    unit_price REAL NOT NULL CHECK(unit_price >= 0),
    discount_pct REAL NOT NULL DEFAULT 0.0 CHECK(discount_pct >= 0 AND discount_pct <= 100),
    discount_amount REAL NOT NULL DEFAULT 0.0,
    taxable_amount REAL NOT NULL DEFAULT 0.0,
    tax_classification TEXT NOT NULL DEFAULT 'taxable' CHECK(tax_classification IN ('taxable', 'exempt', 'nil_rated', 'zero_rated_export', 'non_gst')),
    gst_rate_pct REAL NOT NULL DEFAULT 0.0,
    cgst_rate_pct REAL NOT NULL DEFAULT 0.0,
    cgst_amount REAL NOT NULL DEFAULT 0.0,
    sgst_rate_pct REAL NOT NULL DEFAULT 0.0,
    sgst_amount REAL NOT NULL DEFAULT 0.0,
    igst_rate_pct REAL NOT NULL DEFAULT 0.0,
    igst_amount REAL NOT NULL DEFAULT 0.0,
    line_total REAL NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (invoice_id) REFERENCES customer_invoices(id) ON DELETE CASCADE,
    FOREIGN KEY (sales_order_item_id) REFERENCES sales_order_items(id) ON DELETE SET NULL,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT
);
```

### 3.3. `customer_payments` & `customer_payment_allocations` Tables
```sql
CREATE TABLE IF NOT EXISTS customer_payments (
    id TEXT PRIMARY KEY,
    payment_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
    customer_id TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    payment_date TEXT NOT NULL,
    payment_method TEXT NOT NULL CHECK(payment_method IN ('bank_transfer', 'wire_swift', 'letter_of_credit', 'cheque', 'upi', 'cash')),
    reference_number TEXT,            -- UTR / Cheque / LC reference
    currency TEXT NOT NULL DEFAULT 'INR',
    exchange_rate REAL NOT NULL DEFAULT 1.0,
    amount REAL NOT NULL CHECK(amount > 0),
    allocated_amount REAL NOT NULL DEFAULT 0.0,
    unallocated_amount REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'posted' CHECK(status IN ('posted', 'cancelled')),
    notes TEXT,
    created_by TEXT NOT NULL DEFAULT 'Local Operator',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS customer_payment_allocations (
    id TEXT PRIMARY KEY,
    payment_id TEXT NOT NULL,
    invoice_id TEXT NOT NULL,
    allocated_amount REAL NOT NULL CHECK(allocated_amount > 0),
    realized_gain_loss REAL NOT NULL DEFAULT 0.0,
    allocated_at TEXT NOT NULL,
    allocated_by TEXT NOT NULL,
    notes TEXT,
    FOREIGN KEY (payment_id) REFERENCES customer_payments(id) ON DELETE CASCADE,
    FOREIGN KEY (invoice_id) REFERENCES customer_invoices(id) ON DELETE RESTRICT
);
```

### 3.4. `customer_credit_notes` & `customer_credit_note_items` Tables
```sql
CREATE TABLE IF NOT EXISTS customer_credit_notes (
    id TEXT PRIMARY KEY,
    credit_note_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
    invoice_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    credit_note_date TEXT NOT NULL,
    reason TEXT NOT NULL CHECK(reason IN ('goods_return', 'pricing_error', 'discount_adjustment', 'defective_goods', 'other')),
    currency TEXT NOT NULL DEFAULT 'INR',
    exchange_rate REAL NOT NULL DEFAULT 1.0,
    subtotal REAL NOT NULL DEFAULT 0.0,
    cgst_total REAL NOT NULL DEFAULT 0.0,
    sgst_total REAL NOT NULL DEFAULT 0.0,
    igst_total REAL NOT NULL DEFAULT 0.0,
    tax_total REAL NOT NULL DEFAULT 0.0,
    grand_total REAL NOT NULL DEFAULT 0.0,
    notes TEXT,
    created_by TEXT NOT NULL DEFAULT 'Local Operator',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (invoice_id) REFERENCES customer_invoices(id) ON DELETE RESTRICT,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS customer_credit_note_items (
    id TEXT PRIMARY KEY,
    credit_note_id TEXT NOT NULL,
    invoice_item_id TEXT,
    product_sku TEXT NOT NULL,
    description TEXT NOT NULL,
    quantity REAL NOT NULL CHECK(quantity > 0),
    unit_price REAL NOT NULL CHECK(unit_price >= 0),
    taxable_amount REAL NOT NULL,
    gst_rate_pct REAL NOT NULL DEFAULT 0.0,
    cgst_amount REAL NOT NULL DEFAULT 0.0,
    sgst_amount REAL NOT NULL DEFAULT 0.0,
    igst_amount REAL NOT NULL DEFAULT 0.0,
    line_total REAL NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (credit_note_id) REFERENCES customer_credit_notes(id) ON DELETE CASCADE
);
```

---

## 4. Indian GST Tax Engine Specification

### 4.1. Place of Supply Rules
- **Supplier State Code:** `19` (West Bengal).
- **Intra-State Supply:** `place_of_supply` begins with `19` (or matches supplier state).
  - Tax applied: **CGST** (`rate / 2`) + **SGST** (`rate / 2`).
  - **IGST is strictly 0.0**.
- **Inter-State Supply:** `place_of_supply` is any other Indian state (e.g. `27-Maharashtra`, `07-Delhi`, `33-Tamil Nadu`).
  - Tax applied: **IGST** (`rate`).
  - **CGST and SGST are strictly 0.0**.
  - **MUTUAL EXCLUSION RULE:** Under no circumstance may CGST/SGST and IGST be applied together to the same line item.
- **Export Supply (LUT / Bond):** `tax_scheme == 'EXPORT_LUT'`.
  - `CGST = 0`, `SGST = 0`, `IGST = 0`.
- **Export Supply (With Payment of Tax):** `tax_scheme == 'EXPORT_ZERO_RATED'`.
  - `IGST = rate`, `CGST = 0`, `SGST = 0`.
- **Exempt / Nil-Rated:**
  - `CGST = 0`, `SGST = 0`, `IGST = 0`.

### 4.2. Decimal Precision & Rounding Rules
- Line taxable amounts are rounded to 2 decimal places: `round(quantity * unit_price * (1 - discount_pct / 100), 2)`.
- Line tax amounts are calculated on rounded taxable amounts: `round(taxable_amount * (tax_rate / 100), 2)`.
- Invoice subtotal, tax totals, and grand totals are sums of line items rounded to 2 decimal places.

---

## 5. Multi-Currency Specification

- **Transaction Currency:** The currency negotiated on the sales order / invoice (`INR`, `USD`, `EUR`, `AED`, `GBP`, `SGD`).
- **Reporting Base Currency:** Fixed as `INR`.
- **Exchange Rate:**
  - For `INR`, exchange rate is exactly `1.0`.
  - For foreign currencies, exchange rate represents `1 Foreign Unit = X INR` (e.g. `1 USD = 83.50 INR`).
  - When payment is recorded in the transaction currency, if the payment exchange rate differs from invoice exchange rate, realized foreign exchange gain or loss is computed:
    $$\text{Realized FX Gain/Loss} = \text{Allocated Amount} \times (\text{Payment Exchange Rate} - \text{Invoice Exchange Rate})$$

---

## 6. Over-Invoicing Prevention & Cumulative Checks

When an invoice is created or confirmed from a Sales Order:
1. Query `customer_invoice_items` joined with non-cancelled `customer_invoices` for `sales_order_item_id`.
2. Compute `cumulative_invoiced_qty = SUM(quantity)`.
3. Verify: `cumulative_invoiced_qty + new_quantity <= ordered_quantity`.
4. If it exceeds, reject transaction with `HTTP 400: Invoiced quantity exceeds order balance`.

---

## 7. Safety, Separation-of-Duties, & Non-Certification Guard

- **Separation-of-Duties:** If separation-of-duties is enforced, the operator who created the draft invoice cannot issue or approve it.
- **Statutory Notice:** All generated invoices display:
  > *"TradeSathi AI Commercial Invoice — Internal accounting and trade document. Not an official e-invoice or statutory GST filing acknowledgement."*
