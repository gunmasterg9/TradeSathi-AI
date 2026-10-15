# TradeSathi AI — Phase 7: Financial Reports & Executive Dashboard Design Note

**Document Version:** 1.0.0  
**Phase:** 7 (Financial Reports & Executive Dashboard)  
**Date:** October 14, 2026  
**Status:** Approved for Implementation  

---

## 1. Architectural Objectives & Safety Principles

Phase 7 aggregates authoritative business records across sales, procurement, inventory, export operations, customer invoicing, payments, and Indian GST billing into an **Executive Dashboard and Enterprise Reporting Suite**.

### Mandatory Safety & Calculation Principles
1. **Reuse Authoritative Records (Single Source of Truth):**
   - Sales figures derive directly from `sales_orders` and `sales_order_lines`.
   - Invoiced revenue, receivables, and collections derive strictly from `customer_invoices`, `customer_payments`, `customer_payment_allocations`, and `customer_credit_notes`.
   - Inventory quantities derive directly from `inventory_balances`, `location_inventory_balances`, and active `stock_reservations`.
   - Procurement commitments derive strictly from `purchase_orders` and `purchase_order_items`.
   - Export readiness derives from `shipments` and `export_shipment_checklist_items`.
2. **Never Sum Unconverted Currencies:**
   - Financial aggregations are either kept in their original transaction currency or converted using immutable transaction-time exchange rate snapshots (`grand_total_base_inr`, `amount_base_inr`).
   - All financial numbers must be accompanied by explicit ISO currency symbols (`INR`, `USD`, `EUR`, etc.).
3. **Statutory & Legal Disclaimers:**
   - **Statutory Tax Disclaimer:** Invoices and GST summaries are internal trade accounting records, not official GSTN e-invoicing filings.
   - **Procurement Commitment Notice:** Purchase order totals represent commercial purchasing commitments, not supplier accounts-payable balances (no vendor invoice ledger is configured).
   - **Export Non-Clearance Notice:** Document readiness evaluation is an internal compliance checklist and does not constitute official customs clearance.
4. **Data Safety & Zero-Mutation:**
   - Reporting queries are strictly read-only (`SELECT`).
   - No modifications to posted financial, inventory, or shipment records.
   - Isolated clone migrations and testing ensure live database (`backend/tradesathi.db`) remains completely untouched.

---

## 2. Authoritative Metrics Specification

### A. Sales Analytics
| Metric | Authoritative Table | Calculation Formula | Currency Policy |
|---|---|---|---|
| **Confirmed Order Value** | `sales_orders` | `SUM(grand_total)` WHERE `status IN ('confirmed', 'allocated', 'dispatched', 'delivered')` | Grouped by `currency`; optional conversion via base rate. |
| **Fulfilled Quantity** | `sales_order_lines` | `SUM(dispatched_quantity)` | UOM-specific |
| **Outstanding Order Qty** | `sales_order_lines` | `SUM(quantity - delivered_quantity)` WHERE parent order is not cancelled | UOM-specific |
| **Cancelled Orders** | `sales_orders` | Count and `SUM(grand_total)` WHERE `status = 'cancelled'` | Kept separate from confirmed sales. |
| **Sales by Customer** | `sales_orders` + `customers` | `SUM(grand_total)` grouped by `customer_name` | Transaction currency & Base INR |
| **Sales by Product** | `sales_order_lines` | `SUM(quantity)` and `SUM(line_total)` grouped by `sku` | Unit sales & Base INR |

### B. Financial & Receivables Analytics
| Metric | Authoritative Table | Calculation Formula | Currency Policy |
|---|---|---|---|
| **Issued Invoice Receivables** | `customer_invoices` | `SUM(balance_due)` WHERE `status IN ('issued', 'partially_paid')` | Base INR snapshot & Per-currency breakdown |
| **Total Invoiced Value** | `customer_invoices` | `SUM(grand_total_base_inr)` WHERE `status NOT IN ('draft', 'cancelled')` | Base INR snapshot |
| **Collected Payments** | `customer_payments` | `SUM(amount_base_inr)` | Base INR snapshot |
| **Unallocated Credits** | `customer_payments` | `SUM(unallocated_balance * exchange_rate)` WHERE `unallocated_balance > 0` | Base INR snapshot |
| **Credit Notes Total** | `customer_credit_notes` | `SUM(grand_total_base_inr)` WHERE `status = 'issued'` | Base INR snapshot |
| **Realized FX Differences** | `customer_payment_allocations` | `SUM(realized_fx_diff)` | INR (Realized gain/loss) |
| **Receivables Aging Buckets** | `customer_invoices` | Overdue days = `as_of_date - due_date`: <br>• Current (&le; 0 days)<br>• 1-30 days<br>• 31-60 days<br>• 61-90 days<br>• 90+ days | Base INR snapshot & Per-currency |
| **GST Outward Supplies** | `customer_invoice_items` | `SUM(taxable_amount)`, `SUM(cgst_amount)`, `SUM(sgst_amount)`, `SUM(igst_amount)` grouped by supply type | Base INR |

### C. Procurement Commitments
| Metric | Authoritative Table | Calculation Formula | Currency Policy |
|---|---|---|---|
| **Active PO Commitments** | `purchase_orders` | `SUM(grand_total)` WHERE `status IN ('approved', 'partial_receipt')` | By PO currency; labeled "Commitments" |
| **Pending Receipts Qty** | `purchase_order_items` | `SUM(ordered_qty - received_qty)` WHERE parent PO is active | UOM-specific |
| **Supplier Balances** | *N/A* | Explicitly flagged as "Requires Vendor Invoice Ledger" | Disclaimed in reports |

### D. Inventory Balances & Health
| Metric | Authoritative Table | Calculation Formula | Notes |
|---|---|---|---|
| **Available Stock** | `inventory_balances` | `SUM(on_hand_qty)` WHERE `stock_type = 'available'` | Deducts active reservations |
| **Reserved Stock** | `stock_reservations` | `SUM(quantity)` WHERE `status = 'active'` | Earmarked for orders |
| **Quarantined Stock** | `inventory_balances` | `SUM(on_hand_qty)` WHERE `stock_type = 'quarantined'` | Under inspection |
| **Rejected Stock** | `inventory_balances` | `SUM(on_hand_qty)` WHERE `stock_type = 'rejected'` | Discard/Return queue |
| **In-Transit Stock** | `inventory_balances` | `SUM(on_hand_qty)` WHERE `stock_type = 'in_transit'` | Inter-warehouse transfer |
| **Low Stock Alert** | `products` + `inventory_balances` | Products where `available_qty <= reorder_level` | Urgent replenishment |
| **Warehouse Breakdown** | `location_inventory_balances` | Grouped by `warehouse_id` | Physical site totals |

### E. Export Operations & Compliance
| Metric | Authoritative Table | Calculation Formula | Notes |
|---|---|---|---|
| **Shipments by Stage** | `shipments` | Counts grouped by `workflow_status` | Linear state flow |
| **Readiness Status** | `shipments` | Counts grouped by `readiness_status` | Deterministic compliance |
| **Blocked Shipments** | `shipments` | List where `readiness_status = 'blocked'` | Drill-down table |
| **Document Backlog** | `export_shipment_checklist_items` | Items WHERE `status IN ('pending', 'missing', 'under_review')` | Actionable queue |

---

## 3. CSV Formula-Injection Protection Standard

When exporting data to CSV format, spreadsheet applications (Excel, LibreOffice, Google Sheets) can execute malicious code if a text cell begins with special characters.

All exported CSV values are passed through a strict sanitizer:
```python
def sanitize_csv_cell(value: Any) -> str:
    s = str(value or "")
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s  # Prepend single apostrophe to neutralize formula execution
    return s
```

---

## 4. Role-Based Access Control (RBAC) Specification

| Action | Admin | Manager | Sales | Procurement | Warehouse | Operator | Viewer |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `view_dashboard` | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| `view_financial_reports` | Yes | Yes | No | No | No | No | No |
| `export_reports` | Yes | Yes | No | No | No | No | No |

Viewers and domain-specific roles (sales, warehouse, procurement) have access restricted to operational KPIs without exposing sensitive overall finance/tax P&L or administrative audits.
