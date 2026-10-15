# Phase 10 Design Note: Production Readiness & Deployment Hardening

**Author:** Antigravity Engineering  
**Date:** October 15, 2026  
**Status:** DRAFT / PENDING REVIEW  
**Scope:** TradeSathi AI — Full-Stack Operational Hardening, Production Configuration Validation, Security Safeguards, Schema Version Tracking, Health Probes, and Disaster Recovery Procedures.

---

## 1. Executive Summary & Operational Topology

TradeSathi AI is an enterprise local-first trade reconciliation and operational ERP engine comprising:
- **Core Engine:** Document parsing, OCR extraction, rules and AI reconciliation, and human review audit trail.
- **Master Data & Procurement:** Products, suppliers, customers, purchase orders, goods receipts, and QA inspection.
- **Warehouse & Inventory:** Multi-warehouse locations, batch tracking, stock transfers, reservations, and inventory ledgers.
- **Sales & Exports:** Quotations, sales orders, pick lists, dispatches, export shipments, container optimization (CBM), and custom filings.
- **Finance & Compliance:** Commercial invoicing, multi-currency exchange, payment allocation, Indian GST, and receivables aging reports.
- **Operational Portals & Barcodes:** Thermal barcode/QR generation (Code 128 / QR Code), scanner-driven goods receipt, warehouse transfer, and packing.
- **Supplier & Customer Portals:** External collaboration, single-use invitations, PO acknowledgement, ASNs, customer document requests, order communication, and role segregation.
- **Notifications Engine:** Durable outbox, atomic worker leasing, bounded retries with exponential backoff, recipient eligibility checks, and email transport abstraction.

### Operational Topology

```text
       [ Public Internet / Untrusted Network ]
                         │
                         ▼
       ┌───────────────────────────────────────┐
       │     Reverse Proxy & TLS Termination   │
       │   (Nginx / Caddy / Cloudflare Tunnel) │
       │  - TLS 1.3 Strict HTTPS               │
       │  - Rate Limiting & DDoS Shield        │
       │  - CSP, HSTS, X-Frame-Options         │
       │  - Static Asset Delivery (/dist)      │
       └──────────────────┬────────────────────┘
                          │ HTTP Reverse Proxy (127.0.0.1:8000 only)
                          ▼
       ┌───────────────────────────────────────┐
       │        FastAPI ASGI Application       │
       │  - Production Config Validation       │
       │  - Token-Based Auth & Session Store   │
       │  - Tenant Isolation & RBAC Guards     │
       │  - CSV Injection Defense              │
       │  - Liveness & Readiness Probes        │
       │  - Notification Worker Service        │
       └──────────┬─────────────────┬──────────┘
                  │                 │
                  ▼                 ▼
       ┌────────────────────┐   ┌───────────────────────────┐
       │ SQLite Database    │   │ Document Storage Store    │
       │ (WAL Mode, 30s BT) │   │ (Hash Deduplication,      │
       │ - Live DB Path:    │   │  Traversal Guards)        │
       │   backend/         │   │ - Live Storage Path:      │
       │   tradesathi.db    │   │   backend/storage/docs    │
       └────────────────────┘   └───────────────────────────┘
```

### Live Paths & Deployment Matrix
- **Live Database File:** `backend/tradesathi.db` (SHA-256: `d16067b3369093b71457a4c22c1e0d5871e6d1201af6849a3efbfaad6090b0bf`, Size: `6,127,616 bytes`).
- **Live Document Directory:** `backend/storage/documents` (143 verified documents, 80 subdirectories).
- **Default Backup Root:** `backend/backups` (contains verified baseline snapshots).
- **Production Host Binding:** Bound strictly to loopback `127.0.0.1:8000`. Direct external socket binding (`0.0.0.0`) is prohibited.
- **Node/Frontend Stack:** Node.js 18+ (tested v20+), Vite production build output to `frontend/dist`.

---

## 2. Non-Negotiable Data Safety & Test Isolation

1. **Live Database Guard:**
   - Any test run executing under pytest or with `TRADESATHI_TEST_MODE=1` that attempts to open `backend/tradesathi.db` triggers an immediate `RuntimeError`.
   - Mutation tests must allocate a temporary SQLite database and temporary storage directory via `tempfile.TemporaryDirectory()`.
2. **Zero In-Place Overwrites:**
   - Live documents and database records must remain untouched during all test cycles, health probes, and isolated recovery drills.
3. **Pre/Post Verification:**
   - Bit-for-bit SHA-256 hash checks, file sizes, and table row counts are baselined before and verified after execution.

---

## 3. Backup & Disaster Recovery Architecture

### Online Snapshot Mechanism
- SQLite online backup API (`sqlite3.Connection.backup()`) captures transactionally consistent point-in-time snapshots without write-lock contention, safely capturing active WAL frames.
- Document storage is synchronized alongside the database snapshot.
- A deterministic `manifest.json` records SHA-256 hashes of the database and every document file.

### Recovery Objectives
- **Recovery Point Objective (RPO):** Maximum 1 hour of transaction loss with automated hourly backup cron; zero data loss for manual pre-release snapshots.
- **Recovery Time Objective (RTO):** Measured at under 2 minutes for complete offline restore and verification drill.

### Isolated Disaster Recovery Drill
- The operator executes restore drills into isolated temporary target directories using `backend/app/backup.py` and `backend/app/recovery_verifier.py`.
- Automated checks verify:
  1. Manifest integrity and SHA-256 checksums.
  2. Database `PRAGMA integrity_check` returns `ok`.
  3. `PRAGMA foreign_key_check` returns 0 violations.
  4. Core table row counts match expected snapshot baselines.
  5. Every document file in the manifest exists and matches its recorded hash.

---

## 4. Production Configuration & Startup Validation Gate

### Configuration Matrix & Template
`backend/.env.production.example` defines all production settings with placeholders:
- `ENVIRONMENT=production`
- `CORS_ORIGINS=https://tradesathi.internal.company.com` (wildcard `*` rejected)
- `MAX_UPLOAD_MB=10`
- `EMAIL_DELIVERY_ENABLED=false` (safe default)
- `OLLAMA_BASE_URL=http://127.0.0.1:11434` (optional)
- `TRADESATHI_SECRET_KEY` (placeholder, minimum 32 characters)

### Startup Validation Gate (`validate_production_config()`)
When `ENVIRONMENT == "production"` or `TRADESATHI_ENV == "production"`:
1. Rejects execution if `TRADESATHI_TEST_ROLE_SIMULATOR == "1"` (prevents test bypasses in production).
2. Rejects `CORS_ORIGINS` if it contains `*` (wildcards) or plain HTTP origins (other than loopback during controlled local pilots).
3. Validates that secrets are not known trivial defaults (e.g. `changeme`, `secret`, `admin`).
4. Verifies database and storage directories are readable and writable.
5. Fails closed with structured fatal log message if any validation check fails.

---

## 5. Security & Access Review

1. **Authentication & Token Protection:**
   - Opaque high-entropy bearer tokens (`secrets.token_urlsafe(32)`).
   - Only SHA-256 hashes of tokens are persisted in `user_tokens`.
   - Explicit revocation (`revoked = 1`) and TTL checking (`expires_at`).
   - Deactivated accounts (`is_active = 0`) are rejected immediately on every authenticated request.
2. **Tenant Isolation:**
   - Supplier portal users are strictly restricted to their own supplier organization records (`organization_id`).
   - Customer portal users are strictly restricted to their own customer organization records.
   - Cross-tenant queries return 404 or empty sets; tampering with foreign IDs raises 403/404.
3. **CSV Formula Injection Defense:**
   - Implemented via `sanitize_csv_cell()` in `backend/app/reports.py`.
   - Prefixes formula triggers (`=`, `+`, `-`, `@`, `|`, `\t`, `\r`, `\n`) with a single quote `'` for non-numeric strings, neutralising formula execution in Excel/Calc/Sheets.
4. **File Upload & Path Traversal Guards:**
   - Extension whitelist (`.pdf`, `.txt`, `.docx`, `.eml`).
   - Sanitized filenames via `sanitize_filename()`.
   - Strict `Path.resolve().relative_to(storage_dir)` bounds check preventing path traversal.
5. **Information Leakage Prevention:**
   - Global exception handlers catch unhandled exceptions and return generic 500 error messages without internal stack traces, SQL syntax, or filesystem paths.

---

## 6. Database Migrations & Version Tracking

### Schema Version Registry (`schema_migrations`)
We introduce a version tracking table:
```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
```

### Migration Lifecycle
- On application startup (`init_db()`), each schema phase is registered idempotently:
  - `phase-1_core`: shipments, analyses, documents, finding_reviews.
  - `phase-2_cbm`: cargo_calculations, cargo_lines.
  - `phase-3_warehouse`: warehouses, warehouse_locations, stock_transfers, stock_adjustments, stock_reservations.
  - `phase-4_sales`: quotations, quotation_items, sales_orders, sales_order_items, sales_pick_lists, sales_dispatches.
  - `phase-5_exports`: export_filings, shipping_bills, customs_documents.
  - `phase-6_invoicing`: customer_invoices, invoice_items, payments, gst_tax_entries.
  - `phase-7_reporting`: erp_audit_logs, report_exports.
  - `phase-8_barcodes`: entity_barcodes, thermal_label_templates.
  - `phase-9_collaboration`: portal_users, portal_tokens, supplier_commitments, asns, supplier_documents, delivery_discrepancies, customer_threads, customer_messages, document_requests, document_shares, collaboration_notifications, portal_user_notification_preferences.
  - `phase-10_production_readiness`: schema_migrations and operational metadata.
- All migrations are additive and idempotent. Re-running `init_db()` is a safe no-op.

---

## 7. Observability, Health Probes & Operational Diagnostics

### Probe Endpoints
1. **Liveness Probe (`GET /health/live` and `GET /api/health/live`):**
   - Returns `200 OK` with `{"status": "alive", "timestamp": "..."}`.
   - Proves ASGI server event loop is responsive.
2. **Readiness Probe (`GET /health/ready` and `GET /api/health/ready`):**
   - Executes `SELECT 1` on SQLite database.
   - Verifies document storage directory is accessible and writable.
   - Verifies notification queue health (counts stuck worker leases).
   - Returns `200 OK` with `{"status": "ready"}` or `503 Service Unavailable` with `{"status": "unhealthy", "reasons": [...]}` without leaking internal paths or secrets.
3. **Public API Health (`GET /api/health`):**
   - Preserved for frontend backward compatibility, returning high-level statuses without leaking internal infrastructure details.
4. **Internal Operational Diagnostics (`GET /api/portal/admin/health/summary`):**
   - Authorized endpoint requiring internal staff role (`admin`, `manager`, `operator`).
   - Reports:
     - Notification queue counts (pending, processing, delivered, failed).
     - Oldest pending notification age (seconds).
     - Database integrity (`PRAGMA quick_check`).
     - Storage document count and total size.
     - Email transport configuration mode (`disabled`, `mocked`, `smtp`).
     - Last verified backup timestamp and ID.

---

## 8. Notification Worker Durability & Lease Recovery

- Periodic lease recovery scans `collaboration_notifications` for deliveries stuck in `processing` where `lease_expires_at < current_timestamp`.
- Reclaims abandoned leases by resetting state to `retry_pending` (if attempt < max) or `failed` (if attempt >= max), preventing stalled jobs if a worker process terminates abruptly.
- Zero external email egress when `EMAIL_DELIVERY_ENABLED=false`.

---

## 9. Verification & Acceptance Gates

- **Gate A:** Live business database & storage safety (bit-for-bit unchanged).
- **Gate B:** Backup & isolated restore verification (complete drill on temp copy).
- **Gate C:** Production configuration & secret handling (validation gate tests).
- **Gate D:** Authentication, authorization & tenant isolation (security audit tests).
- **Gate E:** Migration & startup safety (schema version tracking idempotency).
- **Gate F:** Health checks, logging & notification worker operations (liveness, readiness, lease reclamation).
- **Gate G:** Reproducible build & deployment documentation (`DEPLOYMENT.md`, `RECOVERY_RUNBOOK.md`).
- **Gate H:** Full regression suite (full backend suite + frontend build).
