# TradeSathi AI — Phase 4.1: Security Remediation Plan

**Date:** October 14, 2026  
**Auditor & Architect:** Antigravity IDE  
**Scope:** Fix SEC-01 (Authentication Bypass) and ARC-01/ARC-02 (Dispatch Idempotency & Concurrency)

---

## 1. Root Cause Analysis

### SEC-01: Header-Based Authorization Bypass
- **Root Cause:** All ERP route handlers (`main.py`, `sales.py`, `warehouse.py`, `procurement.py`) accept `X-User-Role` and `X-User-Name` directly from unauthenticated caller HTTP headers without verifying credentials, signatures, or session tokens.
- **Impact:** Any network caller can forge `X-User-Role: admin` to execute privileged ERP mutations, create warehouses, approve purchase orders, or alter inventory balances.

### ARC-01: Idempotency Payload Mismatch
- **Root Cause:** In [`backend/app/sales.py`](file:///c:/Users/RAHUL/Desktop/gautam/tradesathi-ai/backend/app/sales.py), `create_sales_dispatch` checks if `idempotency_key` exists. If found, it immediately returns the existing dispatch without validating whether the new payload matches the original dispatch payload.
- **Impact:** A client retrying a different dispatch payload with a reused key silently receives the old dispatch instead of an explicit `HTTP 409 Conflict`.

### ARC-02: Concurrent Duplicate Dispatch Race Condition
- **Root Cause:** In `create_sales_dispatch`, the preliminary `SELECT` check and subsequent `INSERT` are non-atomic. Two simultaneous requests with the same key pass the check, causing the loser to throw an unhandled `sqlite3.IntegrityError` resulting in an `HTTP 500 Internal Server Error`.
- **Impact:** Unhandled server crashes on race conditions instead of clean idempotent replay.

---

## 2. Remediation Strategy

### SEC-01: Trusted Server-Side Authentication
1. **Schema Migration:**
   - Create `users` table: `id`, `username`, `email`, `password_hash`, `role`, `is_active`, `created_at`, `updated_at`.
   - Create `user_tokens` table: `token_id`, `user_id`, `token_hash` (SHA-256), `expires_at`, `revoked`, `created_at`.
2. **Password Security:**
   - Implement `hashlib.scrypt` with 16-byte cryptographically secure random salt (`n=16384, r=8, p=1`).
   - Timing-safe verification with `hmac.compare_digest`.
3. **Session & Token Management:**
   - Issue cryptographically secure random 256-bit bearer tokens (`secrets.token_urlsafe(32)`).
   - Store SHA-256 hash of tokens in `user_tokens`. Raw tokens are never stored in the database.
   - Enforce 8-hour token expiry and explicit revocation on logout.
   - Server-side user active check: disabled users (`is_active = 0`) are rejected immediately on every request.
4. **Backend Role Resolution:**
   - Resolve `user.role` from database record, never from request headers.
   - Provide `get_current_user` FastAPI dependency.
   - Secure initial admin provisioning: `/api/auth/provision-admin` closes permanently once the first admin user exists.
5. **Backward Compatibility & Test Isolation:**
   - In production runs, fail closed (401 Unauthorized) if `Authorization: Bearer <token>` is missing or invalid.
   - For isolated automated test suites only (`TRADESATHI_TEST_MODE=1` AND `TRADESATHI_TEST_ROLE_SIMULATOR=1`), allow backward-compatible role simulation to prevent breaking historical test suites.

### ARC-01: Payload-Bound Idempotency
1. **Schema Migration:**
   - Add `payload_hash TEXT` column to `sales_dispatches` (safe additive migration).
2. **Deterministic Payload Hashing:**
   - Compute SHA-256 over normalized, sorted JSON representation: `sales_order_id`, `warehouse_id`, and sorted `items` (`order_item_id`, `quantity_dispatched`).
3. **Mismatched Payload Detection:**
   - If key matches and payload hash matches -> return existing dispatch (HTTP 200).
   - If key matches and payload hash differs -> raise `HTTP 409 Conflict`.
4. **Legacy Record Compatibility:**
   - If `payload_hash` is NULL (created before migration), allow replay if `sales_order_id` matches; reject with 409 if order ID differs.

### ARC-02: Atomic Concurrency Handling
1. **Integrity Error Interception:**
   - Enclose dispatch insertion within an explicit `try...except sqlite3.IntegrityError` block.
2. **Conflict Resolution:**
   - If uniqueness conflict on `idempotency_key` occurs, rollback transaction, query winning record, compare `payload_hash`, and return HTTP 200 (if match) or HTTP 409 (if mismatch).
   - Unrelated integrity errors (foreign keys, null constraints) bubble up as `HTTP 400 Bad Request`.

---

## 3. Implementation Plan & Gate Checklist

1. **Step 2:** Implement `backend/app/auth.py` and register routes in `backend/app/main.py`.
2. **Step 3:** Implement additive migration in `backend/app/db.py` (`users`, `user_tokens`, `payload_hash`).
3. **Step 4:** Implement payload hashing and concurrency handling in `backend/app/sales.py`.
4. **Step 5:** Add adversarial security tests (`test_auth_security.py`).
5. **Step 6:** Add idempotency and concurrency tests (`test_dispatch_idempotency_concurrency.py`).
6. **Step 7:** Run safe migration validation on isolated database clone.
7. **Step 8:** Run full regression suite and generate `docs/phases/phase-4.1-security-remediation-verification.md`.
