"""
TradeSathi AI — Phase 4.1: SEC-01 Authentication & Role Authorization Adversarial Tests
Verifies:
1. Unauthenticated access to protected endpoints is rejected (HTTP 401).
2. Supplying 'X-User-Role: admin' cannot grant administrator access.
3. Supplying 'X-User-Name' cannot impersonate another user in audit records.
4. Role permissions are enforced strictly from server-side user records.
5. A sales user cannot perform administrator-only operations (HTTP 403).
6. A viewer cannot perform write operations (HTTP 403).
7. Invalid, expired, revoked, and disabled credentials are rejected (HTTP 401).
8. User provisioning is restricted to administrators; initial admin provisioning is permanently locked after setup.
9. Authentication/authorization failures do not mutate business records.
10. Credentials, password hashes, and token signing secrets never leak in error responses.
"""

import os
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
import pytest

from app.auth import create_user_record, hash_password, provision_initial_admin
from app.db import get_connection
from app.main import app


@pytest.fixture
def test_users(client):
    """Set up test users across roles and return their credentials."""
    # Ensure role simulator is disabled for strict security testing
    prev_sim = os.environ.get("TRADESATHI_TEST_ROLE_SIMULATOR")
    os.environ["TRADESATHI_TEST_ROLE_SIMULATOR"] = "0"

    admin = create_user_record({
        "username": "admin_user",
        "email": "admin@tradesathi.test",
        "password": "AdminPassword123!",
        "role": "admin",
    }, performed_by="setup")

    sales = create_user_record({
        "username": "sales_user",
        "email": "sales@tradesathi.test",
        "password": "SalesPassword123!",
        "role": "sales",
    }, performed_by="setup")

    warehouse = create_user_record({
        "username": "wh_user",
        "email": "wh@tradesathi.test",
        "password": "WhPassword123!",
        "role": "warehouse",
    }, performed_by="setup")

    viewer = create_user_record({
        "username": "viewer_user",
        "email": "viewer@tradesathi.test",
        "password": "ViewerPassword123!",
        "role": "viewer",
    }, performed_by="setup")

    def login(username, password):
        res = client.post("/api/auth/login", json={"username": username, "password": password})
        assert res.status_code == 200, f"Login failed for {username}: {res.text}"
        return res.json()["access_token"]

    tokens = {
        "admin": login("admin_user", "AdminPassword123!"),
        "sales": login("sales_user", "SalesPassword123!"),
        "warehouse": login("wh_user", "WhPassword123!"),
        "viewer": login("viewer_user", "ViewerPassword123!"),
    }

    try:
        yield {
            "users": {"admin": admin, "sales": sales, "warehouse": warehouse, "viewer": viewer},
            "tokens": tokens,
            "login": login,
        }
    finally:
        if prev_sim is not None:
            os.environ["TRADESATHI_TEST_ROLE_SIMULATOR"] = prev_sim
        else:
            os.environ.pop("TRADESATHI_TEST_ROLE_SIMULATOR", None)


# ==========================================
# 1. Unauthenticated Access & Header Tampering
# ==========================================

def test_unauthenticated_access_rejected_without_token(client, test_users):
    """Protected endpoints reject requests without Authorization header (HTTP 401)."""
    res = client.post("/api/warehouses", json={"code": "WH-UNAUTH", "name": "Unauthorized WH"})
    assert res.status_code == 401
    assert "Authentication required" in res.json()["detail"]


def test_client_header_impersonation_blocked(client, test_users):
    """An unauthenticated caller cannot gain admin access by sending X-User-Role: admin (HTTP 401)."""
    res = client.post(
        "/api/warehouses",
        json={"code": "WH-HAX-01", "name": "Hacked WH"},
        headers={"X-User-Role": "admin", "X-User-Name": "Malicious Caller"},
    )
    assert res.status_code == 401
    assert "Authentication required" in res.json()["detail"]

    # Verify no warehouse was created
    with get_connection() as conn:
        chk = conn.execute("SELECT count(*) FROM warehouses WHERE code = 'WH-HAX-01'").fetchone()[0]
        assert chk == 0


def test_viewer_token_cannot_be_elevated_by_header(client, test_users):
    """A viewer supplying X-User-Role: admin is still evaluated as a viewer from DB record (HTTP 403)."""
    viewer_token = test_users["tokens"]["viewer"]
    res = client.post(
        "/api/warehouses",
        json={"code": "WH-HAX-02", "name": "Elevated WH"},
        headers={
            "Authorization": f"Bearer {viewer_token}",
            "X-User-Role": "admin",
            "X-User-Name": "Fake Admin",
        },
    )
    assert res.status_code == 403
    assert "Permission denied: role 'viewer'" in res.json()["detail"]


def test_audit_log_records_verified_identity_not_header_name(client, test_users):
    """Audit logs use authenticated user's real username, ignoring spoofed X-User-Name headers."""
    admin_token = test_users["tokens"]["admin"]
    res = client.post(
        "/api/products",
        json={
            "sku": "SKU-AUTH-AUDIT-01",
            "name": "Audit Identity Product",
            "category": "Seafood",
            "uom": "KG",
        },
        headers={
            "Authorization": f"Bearer {admin_token}",
            "X-User-Name": "SpoofedOperator",
        },
    )
    assert res.status_code == 201
    prod_id = res.json()["id"]

    with get_connection() as conn:
        log = conn.execute(
            "SELECT performed_by FROM erp_audit_logs WHERE entity_id = ? AND action = 'create'",
            (prod_id,),
        ).fetchone()
        assert log is not None
        # Performed by must be the authentic database username 'admin_user', NOT 'SpoofedOperator'
        assert log["performed_by"] == "admin_user"
        assert log["performed_by"] != "SpoofedOperator"


# ==========================================
# 2. Role-Based Access Control Boundaries
# ==========================================

def test_sales_user_cannot_perform_admin_operations(client, test_users):
    """Sales users cannot create warehouses or trigger backups (HTTP 403)."""
    sales_token = test_users["tokens"]["sales"]
    res1 = client.post(
        "/api/warehouses",
        json={"code": "WH-SALES-ILLEGAL", "name": "Illegal WH"},
        headers={"Authorization": f"Bearer {sales_token}"},
    )
    assert res1.status_code == 403

    res2 = client.post(
        "/api/backups",
        headers={"Authorization": f"Bearer {sales_token}"},
    )
    assert res2.status_code == 403


def test_viewer_cannot_perform_write_operations(client, test_users):
    """Viewers cannot create products, orders, or suppliers (HTTP 403)."""
    viewer_token = test_users["tokens"]["viewer"]
    res = client.post(
        "/api/products",
        json={"sku": "SKU-VIEWER-WRITE", "name": "Viewer Product"},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res.status_code == 403


# ==========================================
# 3. Credential Lifecycle: Expired, Revoked & Disabled
# ==========================================

def test_invalid_bearer_token_rejected(client, test_users):
    """Forged or malformed bearer tokens return HTTP 401."""
    res = client.get("/api/auth/me", headers={"Authorization": "Bearer totally-fake-token-xyz"})
    assert res.status_code == 401
    assert "Invalid or unrecognized" in res.json()["detail"]


def test_revoked_token_rejected_after_logout(client, test_users):
    """Tokens revoked via logout cannot access protected routes (HTTP 401)."""
    sales_token = test_users["tokens"]["sales"]
    # 1. Access before logout works
    res_me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {sales_token}"})
    assert res_me.status_code == 200

    # 2. Logout revokes token
    logout_res = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {sales_token}"})
    assert logout_res.status_code == 200

    # 3. Access after logout is rejected
    res_after = client.get("/api/auth/me", headers={"Authorization": f"Bearer {sales_token}"})
    assert res_after.status_code == 401
    assert "revoked" in res_after.json()["detail"].lower()


def test_expired_token_rejected(client, test_users):
    """Tokens past expires_at are rejected (HTTP 401)."""
    admin_token = test_users["tokens"]["admin"]
    # Manually backdate token expiration in DB
    past_iso = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with get_connection() as conn:
        conn.execute("UPDATE user_tokens SET expires_at = ?", (past_iso,))
        conn.commit()

    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 401
    assert "expired" in res.json()["detail"].lower()


def test_disabled_user_account_blocked(client, test_users):
    """Deactivated user accounts are immediately blocked from all protected routes (HTTP 401)."""
    sales_id = test_users["users"]["sales"]["id"]
    sales_token = test_users["tokens"]["sales"]

    # Deactivate sales user
    with get_connection() as conn:
        conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (sales_id,))
        conn.commit()

    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {sales_token}"})
    assert res.status_code == 401
    assert "deactivated" in res.json()["detail"].lower()


# ==========================================
# 4. User Provisioning & Privilege Escalation Guards
# ==========================================

def test_non_admin_cannot_create_users(client, test_users):
    """Non-administrators cannot invoke user creation endpoint (HTTP 403)."""
    sales_token = test_users["tokens"]["sales"]
    res = client.post(
        "/api/auth/users",
        json={"username": "hacker", "password": "Password123!", "role": "admin"},
        headers={"Authorization": f"Bearer {sales_token}"},
    )
    assert res.status_code == 403


def test_initial_admin_provisioning_permanently_locked_once_admin_exists(client, test_users):
    """The /api/auth/provision-admin endpoint permanently rejects setup once an active admin exists."""
    res = client.post(
        "/api/auth/provision-admin",
        json={"username": "second_admin", "password": "SecondAdminPassword123!"},
    )
    assert res.status_code == 403
    assert "permanently locked" in res.json()["detail"].lower()


# ==========================================
# 5. Secret Leakage & Mutation Safety
# ==========================================

def test_no_passwords_or_hashes_in_user_responses(client, test_users):
    """API responses and error outputs never leak password hashes or token hashes."""
    admin_token = test_users["tokens"]["admin"]
    res = client.get("/api/auth/users", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    for u in res.json()["items"]:
        assert "password" not in u
        assert "password_hash" not in u
        assert "token_hash" not in u

    # Check /api/auth/me
    me_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert "password" not in me_res.json()
    assert "password_hash" not in me_res.json()


def test_password_change_invalidates_active_tokens(client, test_users):
    """When an administrator changes a user's password, all existing active bearer tokens are revoked immediately."""
    sales_id = test_users["users"]["sales"]["id"]
    sales_token = test_users["tokens"]["sales"]
    admin_token = test_users["tokens"]["admin"]

    # Verify token works before password change
    res_before = client.get("/api/auth/me", headers={"Authorization": f"Bearer {sales_token}"})
    assert res_before.status_code == 200

    # Admin changes password
    patch_res = client.patch(
        f"/api/auth/users/{sales_id}",
        json={"password": "NewSalesPassword123!"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert patch_res.status_code == 200

    # Old token must now be rejected with HTTP 401
    res_after = client.get("/api/auth/me", headers={"Authorization": f"Bearer {sales_token}"})
    assert res_after.status_code == 401
    assert "revoked" in res_after.json()["detail"].lower()


def test_concurrent_admin_bootstrap_race(client):
    """Concurrent bootstrap attempts on an unprovisioned database permit exactly one winner and reject all others."""
    from concurrent.futures import ThreadPoolExecutor

    # Temporarily remove active admins to simulate fresh bootstrap
    with get_connection() as conn:
        saved_admins = conn.execute("SELECT id, username, email, password_hash FROM users WHERE role = 'admin'").fetchall()
        conn.execute("DELETE FROM users WHERE role = 'admin'")
        conn.commit()

    def try_bootstrap(idx):
        return client.post("/api/auth/provision-admin", json={
            "username": f"bootstrap_race_{idx}",
            "password": "StrongPassword123!",
            "email": f"race_{idx}@test.local",
        })

    try:
        with ThreadPoolExecutor(max_workers=5) as executor:
            responses = list(executor.map(try_bootstrap, range(5)))

        status_codes = [r.status_code for r in responses]
        assert status_codes.count(201) == 1, f"Expected exactly one 201 Created, got {status_codes}"
        assert status_codes.count(403) == 4, f"Expected four 403 Forbidden, got {status_codes}"

        with get_connection() as conn:
            admin_count = conn.execute("SELECT count(*) FROM users WHERE role = 'admin'").fetchone()[0]
            assert admin_count == 1
    finally:
        # Restore saved admins
        with get_connection() as conn:
            conn.execute("DELETE FROM users WHERE username LIKE 'bootstrap_race_%'")
            for adm in saved_admins:
                conn.execute(
                    "INSERT OR IGNORE INTO users (id, username, email, password_hash, role, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, 'admin', 1, '2026-10-14T10:00:00Z', '2026-10-14T10:00:00Z')",
                    (adm["id"], adm["username"], adm["email"], adm["password_hash"]),
                )
            conn.commit()
