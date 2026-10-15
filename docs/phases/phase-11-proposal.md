# TradeSathi AI — Phase 11 Proposal: PortSathi Foundation

**Status:** Proposal only — approval required before implementation  
**Production status:** **NOT APPROVED FOR PRODUCTION**

## Discovery Result

No approved Phase 11 specification exists in the repository. The Phase 10.9.2 report explicitly says that Phase 11 had not started, and `docs/ERP_BASELINE_AUDIT.md` is a Gate-0 ERP expansion proposal rather than a Phase 11 authorization.

The baseline audit’s proposed ERP modules are already represented by uncommitted backend modules, frontend views, and dedicated tests for master data, procurement, warehouse, sales, invoicing, reporting, barcode/portal, and collaboration. They must not be repeated or overwritten. The remaining documented deferred business domain is **PortSathi**: vessel-call processing, tug/barge logs, port dues, laytime/Statement-of-Facts reconciliation, and port-operations checklists.

## Proposed Scope and Priority

### Milestone 11.1 — Vessel Call Workspace (recommended first milestone)

Create an isolated PortSathi vessel-call register with lifecycle management. This is the prerequisite record for all other documented PortSathi functions; no cargo, finance, or external integration work is included.

**Documented requirement mapping:** `docs/ERP_BASELINE_AUDIT.md` describes PortSathi as a deferred future phase and identifies vessel calls as the first roadmap capability.

**Acceptance criteria**

1. Authorized staff can create, list, retrieve, and update vessel calls using a unique call reference, vessel identity, port, ETA/ETD, customer/agent reference, and lifecycle status.
2. Input validation rejects malformed dates, unsupported statuses, duplicate references, missing required fields, and out-of-range pagination.
3. Role/tenant authorization prevents portal users and cross-tenant users from reading or changing vessel calls.
4. Every create/update/status transition generates an append-only audit entry with actor, timestamp, action, and non-secret before/after metadata.
5. The workspace is exposed through a separate `/api/port/...` route group and a PortSathi-specific frontend view without changing ExportMate routes or workflows.
6. New schema is additive, tested only with disposable SQLite databases, and leaves existing shipment/document/ERP records unchanged.

**Dependencies**

- Reuse existing authentication, RBAC, tenant-isolation, and audit-log patterns.
- Define a Product Owner-approved lifecycle and minimum data set before implementation (for example: `planned`, `arrived`, `berthed`, `completed`, `cancelled`).
- Confirm whether PortSathi data is tenant-owned by customer, agent, port operator, or a new tenant class.

**Impacts**

| Area | Planned impact |
|---|---|
| API | New versioned PortSathi router only; no existing endpoint contract changes. |
| Database | Additive `vessel_calls` and append-only audit table; no migration of existing shipment data. |
| Frontend | Replace the current PortSathi placeholder with an authenticated list/detail form. |
| Security | Existing auth/RBAC and tenant checks are mandatory on every read/write route. |
| Compatibility | ExportMate, customer/supplier portals, reports, and recovery tooling remain unchanged. |

**Tests required before acceptance**

- Backend: CRUD success path, validation errors, duplicate-reference conflict, unauthorized/forbidden requests, tenant isolation/anti-IDOR, status-transition error handling, audit immutability, and SQLite integrity on disposable databases.
- Frontend: empty/loading/error states, create/edit validation, unauthorized display handling, and no regression of workspace switching.
- Regression: existing auth, collaboration, master-data, sales, and recovery tests relevant to shared routing/db initialization.

**Rollback considerations**

- Keep schema additive and routes opt-in; disable the PortSathi navigation entry/route registration if rollback is required.
- Do not delete vessel-call records automatically. A corrective rollback must preserve audit records and follow an approved data-retention decision.

### Later milestones — only after 11.1 acceptance

1. **11.2 Statement of Facts and laytime reconciliation:** attach time-stamped operational events to vessel calls; requires approved contractual event taxonomy and calculation rules.
2. **11.3 Tug/barge and port-operations logs:** operational resource/event records; requires ownership, time-zone, and correction/audit policies.
3. **11.4 Port dues and operational cost capture:** manual internal cost records only; requires finance owner approval before any linkage to invoices or margin reporting.
4. **11.5 Port-operations checklist and documents:** checklist templates and evidence links; requires retention/access policies and document-sharing review.

## Risks and Required Decisions

- **Business semantics:** laytime, Notice of Readiness, berth/anchorage timing, and demurrage/despatch rules vary by contract. Do not encode calculations before written Product Owner rules exist.
- **Tenancy model:** the existing portal model may not directly represent ship owners, agents, terminals, and charterers. Approval of ownership and visibility is required first.
- **Financial boundary:** port dues must not affect invoices, payments, or profitability until an approved finance scope defines tax/currency treatment.
- **Data safety:** implementation and migration tests must use synthetic, disposable SQLite databases and document directories; `backend/tradesathi.db` and `backend/storage/documents` remain read-only for verification only.

## Approval Gate

Implementation may begin only after the Product Owner approves:

1. Milestone 11.1 as the Phase 11 scope.
2. Vessel-call fields and allowed status transitions.
3. Tenant ownership/visibility and authorized roles.
4. Retention/audit expectations and the acceptance criteria above.

Until then, this proposal authorizes no code, database, API, frontend, infrastructure, or production change.
