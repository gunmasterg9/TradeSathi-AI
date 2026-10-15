# TradeSathi AI — Phase 8.1: Barcode & Operational Portal Adversarial Audit Report

**Audit Date:** October 15, 2026  
**Auditor:** Antigravity Autonomous Security & Safety Assurance Agent  
**Environment:** Windows 11 (PowerShell), Python 3.12.10, SQLite 3 (WAL mode), Node.js / Vite 8.3.4, React 19  
**Executive Verdict:** **PASS**  
**Phase 9 Readiness:** **PENDING HUMAN REVIEW — DO NOT PROCEED AUTOMATICALLY**  
**Live Data Safety:** Confirmed 100% byte-for-byte identical between Gate A and Gate H.

---

## 1. Executive Summary

An independent, rigorous adversarial audit of Phase 8 (Barcode & Operational Scanning Portal) was executed in accordance with Phase 8.1 guidelines. The audit evaluated inventory integrity, barcode/QR security, duplicate operations, concurrent scans, authorization, generated-label storage isolation, and backward compatibility.

All mutation, concurrency, and security testing was executed strictly against isolated temporary databases (`adversarial_audit.db`), synthetic users, and isolated temporary document storage directories. Zero test operations or mutations were performed against the production database or live storage.

### Findings & Remediation Ledger

| ID | Severity | Category | Description | Remediation Status |
|---|---|---|---|---|
| **AUD-8.1-01** | **Medium** | Label Storage Resolution | `preview_label_html` in `portal.py` resolved `Path(record["file_path"]).resolve()` against process CWD instead of `get_storage_dir()`. Because `file_path` is relative (`labels/<filename>.html`), it failed the containment check `labels_dir in file_path.parents` and unnecessarily re-generated the label on every preview request. | **RESOLVED:** Updated `portal.py` to resolve relative paths as `(get_storage_dir() / raw_path).resolve()`, verifying containment strictly inside `labels_dir`. |
| **AUD-8.1-02** | **High** | Barcode Lifecycle & Constraints | `entity_barcodes` table possessed a table-level `UNIQUE(entity_type, entity_id, symbology)` constraint. When an operator deactivated a damaged label and re-generated a replacement, SQLite raised a `UNIQUE constraint failed` error, locking out label re-issuance. | **RESOLVED:** Replaced table-level constraint in `db.py` with partial unique index `idx_barcodes_active_entity ON entity_barcodes(entity_type, entity_id, symbology) WHERE is_active = 1`. Deactivated barcodes retain historical audit trails while allowing active re-generation. |
| **AUD-8.1-03** | **Medium** | Idempotency Integrity | In `procurement.py`, `create_goods_receipt` retrieved existing receipts matching an `idempotency_key` without verifying that the caller's target `po_id` matched the existing receipt. Reusing an idempotency key against a different PO silently returned the receipt of the original PO. | **RESOLVED:** Updated `create_goods_receipt` in `procurement.py` to assert `existing_receipt["po_id"] == po_id`, raising `HTTPException(409 Conflict)` if an idempotency key is reused across distinct purchase orders. |
| **AUD-8.1-04** | **High** | Inventory ATP Guard | In `portal.py`, `scan_execute_stock_transfer` inspected raw global `inventory_balances.on_hand_qty` without subtracting active sales reservations (`stock_reservations`) or verifying warehouse/location-level on-hand balances. This permitted transferring committed stock. | **RESOLVED:** Updated `portal.py` to calculate location/warehouse-level stock from `location_inventory_balances` (with fallback to global), subtract active reservations (`net_atp = max(0.0, avail - reserved)`), and raise HTTP 400 if requested quantity exceeds unreserved ATP. |
| **AUD-8.1-05** | **Medium** | Fulfilment Packing Guard | In `portal.py`, `scan_execute_packing_verification` validated packed quantities against `ordered_quantity` instead of `allocated_quantity` for orders in `allocated` or `picking` status, allowing over-packing of partially allocated sales orders. | **RESOLVED:** Updated `portal.py` to enforce `max_packable = allocated_quantity if (allocated_quantity > 0 and so["status"] in ("allocated", "picking")) else ordered_qty`. |
| **AUD-8.1-06** | **High** | HTML / XSS Escaping | In `barcode_engine.py`, `build_label_html` interpolated raw metadata strings (`title`, `subtitle`, `safe_ref`, `extra_lines`) into thermal label HTML templates without escaping, introducing stored XSS risk into printable preview if malicious entities were scanned. | **RESOLVED:** Applied `html.escape()` to `title`, `subtitle`, `safe_ref`, and all key-value tuples in `extra_lines` within `barcode_engine.py`. |

---

## 2. Gate-by-Gate Evaluation & Evidence

### Gate A — Establish Data-Safety Baseline
- **Live Database Path:** `C:\Users\RAHUL\Desktop\gautam\tradesathi-ai\backend\tradesathi.db`
- **Live Database Size:** `6,127,616 bytes`
- **Live Database SHA-256:** `d16067b3369093b71457a4c22c1e0d5871e6d1201af6849a3efbfaad6090b0bf`
- **Critical Live Row Counts:**
  - `analyses`: 330
  - `cargo_calculations`: 0
  - `cargo_lines`: 0
  - `documents`: 48
  - `finding_reviews`: 2
  - `shipments`: 45
- **Document-Storage File Manifest:** 143 files indexed in `scratch/phase8_1_gate_a_baseline.json`.
- **Storage Isolation & Hardcoded Path Audit:**
  - Confirmed all storage writes in `barcode_engine.py`, `portal.py`, `storage.py`, `export_operations.py` call `get_storage_dir()`.
  - Confirmed `test_isolation_guard.py` and `conftest.py` actively assert `RuntimeError` if any test targets the live database or storage directory.
  - Verified that live storage contains `0` label artifacts (`labels/` directory does not exist in production storage).
- **Status:** **PASS**

### Gate B — Barcode and QR Identification
- **Identifier Structure:** Structured QR payload format `TS:v1:<ENTITY_TYPE>:<REFERENCE>` validated across `product`, `location`, `purchase_order`, `sales_order`, and `shipment`.
- **Legacy Fallback:** Raw Code 128 barcodes (e.g., `SKU-AUDIT-001`) tested and resolved via `products.sku` or legacy entity references without requiring `TS:v1` prefix.
- **Deactivation Handling:** Deactivated barcodes tested against `/api/portal/scan-resolve`. Correctly rejected with HTTP 400 (`Barcode ... has been deactivated`).
- **Re-generation After Deactivation:** Re-generating a replacement label for the same entity and symbology after deactivation succeeds without UNIQUE constraint collision (verified via partial unique index `idx_barcodes_active_entity`).
- **Malformed & Adversarial Payloads:**
  - Malformed structure (`INVALID:TRUNCATED:123`): Gracefully rejected with HTTP 400.
  - Unsupported version (`TS:v99:PROD:SKU-001`): Handled safely without exception leakage.
  - SQL injection payloads (`' OR 1=1 --`): Handled safely via parameterized queries.
  - Path traversal payloads (`../../etc/passwd`): Prevented by strict regex stripping and sanitization.
- **Status:** **PASS**

### Gate C — Goods Receipt Integrity
- **Partial Receipts:** Synthetic PO ordered 100 units; partial receipt of 40 units posted successfully. PO item `received_qty` incremented from 0.0 to 40.0.
- **Over-Receipt Tolerance:** Attempted receipt of 115 units against 100 ordered (exceeding 10% maximum tolerance). Correctly rejected with HTTP 400 (`Exceeds 10% maximum allowable tolerance`).
- **Idempotency Protection:**
  - Duplicate submission with identical `idempotency_key` returned the original receipt without creating duplicate inventory movements or double-incrementing PO item quantities (`received_qty` remained exactly 40.0).
  - Cross-PO idempotency key reuse: Submitting the same key against `po-audit-002` correctly returned HTTP 409 Conflict (`Idempotency key was previously used for PO ... Cannot reuse key with different target PO`).
- **Status:** **PASS**

### Gate D — Warehouse Transfer Integrity
- **Over-Transfer Prevention:** Attempted transfer of 500 units when only 100 on-hand. Correctly rejected with HTTP 400 (`Insufficient available stock`).
- **Identical Location Guard:** Transfer with matching `source_location_id` and `dest_location_id` rejected with HTTP 400 (`Source and destination storage locations cannot be identical`).
- **ATP Reservation Guard:**
  - On-hand stock: 75 units in source bin. Active sales reservation: 110 units committed.
  - Net Available-to-Promise (ATP): 0 units.
  - Attempted transfer of 20 units rejected with HTTP 400 (`Insufficient available stock (unreserved ATP) ... On-hand available: 75.0, Active reservations: 110.0, Net ATP: 0.0`).
- **Valid Relocation & Ledger Reconciliation:**
  - Valid transfer of 25 units from Kolkata Hub (`WH1`) to Siliguri Depot (`WH2`) posted successfully.
  - Created balanced `TRANSFER_DISPATCH` movement (-25) and `TRANSFER_RECEIPT` movement (+25) reconciled in `inventory_movements`.
- **Status:** **PASS**

### Gate E — Picking, Packing, and Dispatch
- **Over-Packing Beyond Ordered:** Sales order item ordered 30 units; attempting to pack 35 units rejected with HTTP 400.
- **Over-Packing Beyond Allocated Limit:**
  - Sales order allocated 20 units (ordered 30 units).
  - Attempting to pack 25 units rejected with HTTP 400 (`Packing quantity exceeds order limit / allocated limit for SKU ... allocated 20.0 (ordered 30.0)`).
- **Scan Mutation Non-Dispatch Guarantee:** Verifying and packing items advances sales order status from `allocated` to `picking`/`packed`, but strictly does NOT trigger dispatch movements or deplete inventory ledger until explicit authenticated dispatch workflow is invoked.
- **Status:** **PASS**

### Gate F — Authentication and Authorization
- **Anonymous Requests:** Requests without authentication headers receive HTTP 403 Forbidden / 422 Unprocessable.
- **Role Permission Scoping:**
  - `viewer` calling `/api/portal/execute-transfer` &rarr; `403 Forbidden`.
  - `procurement` calling `/api/portal/execute-transfer` &rarr; `403 Forbidden`.
  - `warehouse` calling `/api/portal/execute-transfer` &rarr; `200 OK`.
- **Audit Logging:** Every scan-executed receipt, transfer, and label generation records an entry in `erp_audit_logs` tracking `performed_by`, `entity_type`, `entity_id`, and before/after change state.
- **Status:** **PASS**

### Gate G — Label Generation and Browser Scanning
- **HTML & XSS Escaping:** Metadata containing `<script>alert('XSS')</script>`, `"><img src=x onerror=alert(1)>`, and `<b onmouseover=alert(2)>` tested against `build_label_html`. Rendered HTML strictly escaped all tags (`&lt;script&gt;`, `&lt;img`, `&lt;b`), neutralizing script injection.
- **Storage Isolation & Containment Check:**
  - Generated label HTML files saved strictly inside `<storage_dir>/labels/`.
  - Path traversal attempt `GET /api/portal/labels/../../etc/passwd/preview` blocked with 404/422.
- **Symbology Standards:**
  - Code 128: Validated high-density barcode SVG rendering with quiet zones and human-readable text.
  - QR Code: High-contrast 2D matrix SVG rendering with error correction.
- **Hardware & Wedge Limitations:**
  - Physical wedge scanners operating in USB HID mode emit keystrokes followed by `Enter` (ASCII 13 / `\n`). The frontend portal handles this via `onKeyDown` Enter-capture and rapid scan buffer debouncing.
  - Mobile web camera scanning requires HTTPS and explicit camera permissions (`navigator.mediaDevices.getUserMedia`). Fallback to manual text input is guaranteed in `PortalView.jsx`.
- **Status:** **PASS**

### Gate H — Regression & Final Evidence
- **Focused Barcode Portal Tests:**
  - Command: `python -m pytest backend/tests/test_barcode_portal.py -v`
  - Result: **17 passed, 1 warning in 10.61s** (Exit Code: 0)
- **Full Backend Regression Suite:**
  - Command: `python -m pytest backend/tests/ -q`
  - Result: **275 passed, 1 warning in 215.22s** (Exit Code: 0)
- **Frontend Test Suite:**
  - Command: `npm.cmd test -- --watchAll=false`
  - Result: **109 passed in 1.55s** (Exit Code: 0)
- **Frontend Production Build:**
  - Command: `npm.cmd run build`
  - Result: **SUCCESS in 11.82s** (Exit Code: 0, 1602 modules transformed)
- **Pre/Post Live Data Verification:**
  - Database Path: `C:\Users\RAHUL\Desktop\gautam\tradesathi-ai\backend\tradesathi.db`
  - Database Size: `6,127,616 bytes` (Identical)
  - Database SHA-256: `d16067b3369093b71457a4c22c1e0d5871e6d1201af6849a3efbfaad6090b0bf` (Identical)
  - Critical Row Counts: `analyses`: 330, `cargo_calculations`: 0, `cargo_lines`: 0, `documents`: 48, `finding_reviews`: 2, `shipments`: 45 (Identical)
  - Live Storage Manifest: 143 files (Identical hashes, 0 label files in live storage)
- **Status:** **PASS**

---

## 3. Files and Functions Inspected & Remediated

- [`backend/app/portal.py`](file:///C:/Users/RAHUL/Desktop/gautam/tradesathi-ai/backend/app/portal.py):
  - `preview_label_html`: Remediated relative file path containment resolution (`AUD-8.1-01`).
  - `scan_execute_stock_transfer`: Remediated warehouse and location ATP reservation guard (`AUD-8.1-04`).
  - `scan_execute_packing_verification`: Remediated allocated quantity limit guard (`AUD-8.1-05`).
  - `scan_resolve_barcode`, `generate_label`, `list_labels`, `scan_execute_goods_receipt`.
- [`backend/app/db.py`](file:///C:/Users/RAHUL/Desktop/gautam/tradesathi-ai/backend/app/db.py):
  - `init_db`: Replaced table-level unique constraint on `entity_barcodes` with partial unique index `idx_barcodes_active_entity` (`AUD-8.1-02`).
  - `get_or_create_entity_barcode_record`, `get_barcode_record_by_id`, `deactivate_entity_barcode_record`.
- [`backend/app/procurement.py`](file:///C:/Users/RAHUL/Desktop/gautam/tradesathi-ai/backend/app/procurement.py):
  - `create_goods_receipt`: Enforced cross-PO idempotency key validation returning 409 Conflict (`AUD-8.1-03`).
- [`backend/app/barcode_engine.py`](file:///C:/Users/RAHUL/Desktop/gautam/tradesathi-ai/backend/app/barcode_engine.py):
  - `build_label_html`: Applied `html.escape()` across all metadata fields and attributes (`AUD-8.1-06`).
  - `generate_qr_svg`, `generate_code128_svg`, `save_label_artifact`, `generate_entity_label`, `resolve_scanned_barcode_payload`.
- [`frontend/src/PortalView.jsx`](file:///C:/Users/RAHUL/Desktop/gautam/tradesathi-ai/frontend/src/PortalView.jsx):
  - Keyboard wedge scanner capture, camera scanner handler, label thermal preview modal, and role-based action gating.
- [`scratch/audit_phase8_1_adversarial_suite.py`](file:///C:/Users/RAHUL/.gemini/antigravity-ide/brain/9cf2773f-75ef-4375-9081-60405096f5cd/scratch/audit_phase8_1_adversarial_suite.py):
  - End-to-end adversarial audit test suite covering Gates A through G.
- [`scratch/audit_phase8_1_post_check.py`](file:///C:/Users/RAHUL/.gemini/antigravity-ide/brain/9cf2773f-75ef-4375-9081-60405096f5cd/scratch/audit_phase8_1_post_check.py):
  - Post-audit live database and document storage byte-for-byte immutability verifier.

---

## 4. Hardware Limitations & Boundary Disclaimers

1. **Physical Hardware Scanners:** The system supports standard USB/Bluetooth barcode wedges emitting ASCII keyboard characters. 2D imagers must be configured in HID POS mode with standard carriage-return suffixes.
2. **Thermal Label Printers:** Label HTML documents are formatted for 203 DPI thermal printers (4"x2" and 2"x1" standard continuous roll media). Printing from browsers requires setting page margins to `None` in the browser print dialog.
3. **Camera Scanning:** Mobile browser camera scanning requires HTTPS and user permission. On devices lacking back-facing cameras or where permission is denied, operators must use the manual keyboard entry fallback.

---

## 5. Phase 8.1 Completion Gate Decision

**VERDICT: PASS — ALL GATES VERIFIED AND DEFECTS REMEDIATED.**

- All 8 audit gates (A through H) have met their evidentiary criteria.
- All 6 findings (AUD-8.1-01 through AUD-8.1-06) have been documented, remediated in code, and verified via automated tests.
- Full regression suites passed: 275 backend tests, 109 frontend tests, and frontend production build succeeded.
- Live production database and document storage are proven 100% byte-for-byte identical to baseline.
- **Per instruction, Phase 9 is NOT started automatically and awaits user direction.**
