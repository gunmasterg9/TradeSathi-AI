"""TradeSathi AI — Phase 10 Production Readiness & Operational Hardening Test Suite
Verifies:
1. Startup configuration validation (fails safely on production misconfig).
2. Schema migration tracking and idempotency.
3. Live database test isolation guard.
4. End-to-end isolated disaster recovery drill.
5. Health probes & information disclosure safety.
6. Security controls: anonymous rejection, role enforcement, tenant isolation, deactivated user revocation.
7. CSV formula injection defense.
8. Path traversal & file upload safeguards.
9. Notification worker lease recovery & durability.
10. Zero business state mutations across operational checks.
"""

from datetime import datetime, timedelta, timezone
from collections.abc import Generator
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import (
    AuthenticatedUser,
    create_user_record,
    create_user_token,
    get_current_user,
    hash_password,
)
from app.backup import (
    compute_file_sha256,
    create_backup,
    restore_backup,
    verify_backup,
)
from app.collaboration import (
    create_portal_token,
    get_current_portal_user,
)
from app.db import (
    DEFAULT_DB_PATH,
    LIVE_DB_PATH,
    get_applied_migrations,
    get_connection,
    get_db_path,
    init_db,
    set_db_path,
)
from app.documents import sanitize_filename
from app.main import app, validate_production_config
from app.notifications import (
    MockEmailTransport,
    process_notification_deliveries,
    reclaim_expired_leases,
    record_collaboration_notification,
    set_email_transport,
)
from app.reports import sanitize_csv_cell
from app.storage import get_document_file_path, get_storage_dir, set_storage_dir


@pytest.fixture
def isolated_phase10_env(tmp_path: Path, monkeypatch) -> Generator[dict, None, None]:
    """Create isolated SQLite database and sandboxed storage for Phase 10 tests."""
    temp_db = tmp_path / "test_phase10.db"
    temp_storage = tmp_path / "test_storage"
    temp_storage.mkdir(parents=True, exist_ok=True)

    orig_db = get_db_path()
    orig_storage = get_storage_dir()

    set_db_path(temp_db)
    set_storage_dir(temp_storage)

    monkeypatch.setenv("TRADESATHI_DB_PATH", str(temp_db))
    monkeypatch.setenv("TRADESATHI_STORAGE_PATH", str(temp_storage))
    monkeypatch.setenv("TRADESATHI_TEST_MODE", "1")

    init_db(temp_db)

    mock_transport = MockEmailTransport()
    set_email_transport(mock_transport)

    try:
        yield {
            "db_path": temp_db,
            "storage_dir": temp_storage,
            "mock_transport": mock_transport,
            "temp_dir": tmp_path,
        }
    finally:
        set_db_path(orig_db)
        set_storage_dir(orig_storage)
        set_email_transport(None)


def test_production_startup_validation(isolated_phase10_env, monkeypatch):
    """Test 1: Validate production startup configuration gate."""
    # Development mode: No errors expected even with test role simulator
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("TRADESATHI_TEST_ROLE_SIMULATOR", "1")
    errors = validate_production_config()
    assert errors == []

    # Production mode with test simulator enabled: Fatal error
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("TRADESATHI_TEST_ROLE_SIMULATOR", "1")
    errors = validate_production_config()
    assert any("TRADESATHI_TEST_ROLE_SIMULATOR" in e for e in errors)

    # Production mode with wildcard CORS: Fatal error
    monkeypatch.setenv("TRADESATHI_TEST_ROLE_SIMULATOR", "0")
    monkeypatch.setenv("CORS_ORIGINS", "https://example.com, *")
    errors = validate_production_config()
    assert any("wildcard '*'" in e for e in errors)

    # Production mode with insecure default secret key: Fatal error
    monkeypatch.setenv("CORS_ORIGINS", "https://tradesathi.internal.company.com")
    monkeypatch.setenv("TRADESATHI_SECRET_KEY", "secret")
    errors = validate_production_config()
    assert any("TRADESATHI_SECRET_KEY" in e for e in errors)

    # Production mode with hardened configuration: Clean pass
    monkeypatch.setenv("TRADESATHI_SECRET_KEY", "f8a92b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a")
    errors = validate_production_config()
    assert errors == []


def test_schema_migration_registry_and_idempotency(isolated_phase10_env):
    """Test 2: Schema migrations are tracked and repeated execution is idempotent."""
    env = isolated_phase10_env
    db_path = env["db_path"]

    # Verify migrations registered on first init
    migrations = get_applied_migrations(db_path)
    assert len(migrations) >= 10
    versions = [m["version"] for m in migrations]
    assert "phase-1_core" in versions
    assert "phase-9_collaboration" in versions
    assert "phase-10_production_readiness" in versions

    initial_count = len(migrations)

    # Re-run init_db a second time: must be idempotent and preserve exact row count
    init_db(db_path)
    migrations_second = get_applied_migrations(db_path)
    assert len(migrations_second) == initial_count


def test_live_database_isolation_guard(monkeypatch):
    """Test 3: Live database isolation guard raises RuntimeError when test connects to LIVE_DB_PATH."""
    monkeypatch.setenv("TRADESATHI_TEST_MODE", "1")
    with pytest.raises(RuntimeError) as exc_info:
        get_connection(LIVE_DB_PATH)
    assert "CRITICAL TEST ISOLATION FAILURE" in str(exc_info.value)


def test_e2e_isolated_disaster_recovery_drill(isolated_phase10_env):
    """Test 4: End-to-end disaster recovery drill on an isolated backup."""
    env = isolated_phase10_env
    src_db = env["db_path"]
    src_storage = env["storage_dir"]
    temp_dir = env["temp_dir"]

    # 1. Seed test database with a shipment, document record, and physical document
    now = datetime.now(timezone.utc).isoformat()
    doc_content = b"Commercial Invoice: INVOICE-DR-001\nTotal Amount: USD 50,000"
    doc_hash = hashlib.sha256(doc_content).hexdigest()
    rel_doc_path = "shp-dr-test/commercial_invoice.txt"
    abs_doc_path = src_storage / rel_doc_path
    abs_doc_path.parent.mkdir(parents=True, exist_ok=True)
    abs_doc_path.write_bytes(doc_content)

    with get_connection(src_db) as conn:
        conn.execute(
            """
            INSERT INTO shipments (id, reference, exporter, buyer, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("shp-dr-01", "EXP-DR-2026-001", "Global Exports", "Acme Importers", "draft", now, now),
        )
        conn.execute(
            """
            INSERT INTO documents (
                id, shipment_id, original_filename, clean_filename, document_type,
                uploaded_at, storage_key, file_size, file_hash, processing_status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "doc-dr-01",
                "shp-dr-01",
                "commercial_invoice.txt",
                "commercial_invoice.txt",
                "commercial_invoice",
                now,
                rel_doc_path,
                len(doc_content),
                doc_hash,
                "completed",
                now,
                now,
            ),
        )
        conn.commit()

    # 2. Create backup snapshot
    backup_root = temp_dir / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    manifest = create_backup(
        source_db_path=src_db,
        source_storage_dir=src_storage,
        backup_root=backup_root,
        retention_limit=5,
    )
    assert manifest["status"] == "completed"
    backup_folder = backup_root / manifest["backup_id"]

    # 3. Verify backup snapshot against manifest
    verify_result = verify_backup(backup_folder)
    assert verify_result.get("verified") is True

    # 4. Perform isolated restore into a separate scratch directory
    restore_target = temp_dir / "restored_drill"
    restore_target_db = restore_target / "restored_tradesathi.db"
    restore_target_storage = restore_target / "documents"
    restore_target.mkdir(parents=True, exist_ok=True)

    restore_backup(
        backup_folder=backup_folder,
        target_db_path=restore_target_db,
        target_storage_dir=restore_target_storage,
    )

    # 5. Check restored SQLite database integrity and foreign keys
    assert restore_target_db.is_file()
    with sqlite3.connect(str(restore_target_db)) as r_conn:
        r_conn.execute("PRAGMA foreign_keys = ON")
        chk = r_conn.execute("PRAGMA integrity_check").fetchall()
        assert chk == [("ok",)]

        fk_chk = r_conn.execute("PRAGMA foreign_key_check").fetchall()
        assert len(fk_chk) == 0

        # Check seeded rows exist in restored DB
        row = r_conn.execute("SELECT reference FROM shipments WHERE id = 'shp-dr-01'").fetchone()
        assert row is not None
        assert row[0] == "EXP-DR-2026-001"

    # 6. Check restored document exists and matches hash
    restored_doc = restore_target_storage / rel_doc_path
    assert restored_doc.is_file()
    assert compute_file_sha256(restored_doc) == doc_hash


def test_health_probes_and_information_disclosure_safety(isolated_phase10_env):
    """Test 5: Health probes return correct statuses and disclose zero secrets or filesystem paths."""
    client = TestClient(app)

    # 1. Liveness probe
    live_resp = client.get("/health/live")
    assert live_resp.status_code == 200
    live_data = live_resp.json()
    assert live_data["status"] == "alive"
    assert "timestamp" in live_data
    # Assert no sensitive paths or secrets exposed
    assert "path" not in json.dumps(live_data).lower()
    assert "secret" not in json.dumps(live_data).lower()

    # 2. Readiness probe
    ready_resp = client.get("/health/ready")
    assert ready_resp.status_code == 200
    ready_data = ready_resp.json()
    assert ready_data["status"] == "ready"
    assert ready_data["database"] == "connected"
    assert ready_data["storage"] == "writable"
    assert "path" not in json.dumps(ready_data).lower()
    assert "secret" not in json.dumps(ready_data).lower()

    # 3. Public health diagnostic (/api/health)
    health_resp = client.get("/api/health")
    assert health_resp.status_code == 200
    health_data = health_resp.json()
    assert health_data["status"] in ("ok", "degraded")
    assert "database" in health_data
    assert "storage" in health_data
    # Verify no raw filesystem paths leaked
    assert "c:\\" not in json.dumps(health_data).lower()
    assert "/var/" not in json.dumps(health_data).lower()


def test_security_audit_authorization_and_tenant_isolation(isolated_phase10_env):
    """Test 6: Authentication enforcement, tenant isolation, and deactivated user revocation."""
    env = isolated_phase10_env
    db_path = env["db_path"]
    client = TestClient(app)

    # 1. Anonymous request to protected customer notification endpoint fails 401
    anon_resp = client.get("/api/portal/customer/notifications")
    assert anon_resp.status_code == 401

    # 2. Create customer and active portal user
    p_user_id = "pusr-p10-test-01"
    now = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO customers (id, code, name, country, currency, status, created_at, updated_at)
            VALUES ('cust-p10-01', 'CUST-P10', 'Test Customer', 'IN', 'INR', 'active', ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO portal_users (
                id, email, password_hash, username, account_type, organization_id,
                organization_name, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                p_user_id,
                "customer_p10@test.com",
                hash_password("CustomerPass123!"),
                "Customer P10",
                "customer",
                "cust-p10-01",
                "Test Customer Org",
                now,
                now,
            ),
        )
        conn.commit()

    token_raw, _ = create_portal_token(p_user_id)
    headers = {"Authorization": f"Bearer {token_raw}"}

    # Authenticated portal user queries notifications successfully
    auth_resp = client.get("/api/portal/customer/notifications", headers=headers)
    assert auth_resp.status_code == 200

    # Portal user attempting to access internal staff health summary fails 401/403 (not staff)
    staff_resp = client.get("/api/portal/admin/health/summary", headers=headers)
    assert staff_resp.status_code in (401, 403)

    # Internal non-admin staff (e.g. viewer) fails with 403
    v_user = create_user_record({"username": "viewer_p10", "password": "ViewerPass123!", "role": "viewer"}, performed_by="test")
    v_token, _ = create_user_token(v_user["id"])
    v_resp = client.get("/api/portal/admin/health/summary", headers={"Authorization": f"Bearer {v_token}"})
    assert v_resp.status_code == 403

    # Internal admin staff succeeds with 200
    a_user = create_user_record({"username": "admin_p10", "password": "AdminPass123!", "role": "admin"}, performed_by="test")
    a_token, _ = create_user_token(a_user["id"])
    a_resp = client.get("/api/portal/admin/health/summary", headers={"Authorization": f"Bearer {a_token}"})
    assert a_resp.status_code == 200
    assert a_resp.json()["status"] in ("healthy", "degraded")

    # 3. Deactivate portal user: Subsequent requests must instantly return 401/403
    with get_connection(db_path) as conn:
        conn.execute("UPDATE portal_users SET is_active = 0 WHERE id = ?", (p_user_id,))
        conn.commit()

    deact_resp = client.get("/api/portal/customer/notifications", headers=headers)
    assert deact_resp.status_code in (401, 403)
    assert "deactivated" in deact_resp.json()["detail"].lower()


def test_csv_formula_injection_defense():
    """Test 7: Verify spreadsheet formula injection defense against all trigger symbols."""
    dangerous_inputs = [
        "=cmd|' /C calc'!A0",
        "+cmd|' /C calc'!A0",
        "@SUM(A1:A10)",
        "|malicious_pipe",
        "\t=tab_formula",
        "\r=cr_formula",
        "\n=nl_formula",
        "   =leading_space_formula",
    ]

    for malicious in dangerous_inputs:
        sanitized = sanitize_csv_cell(malicious)
        assert sanitized.startswith("'"), f"Failed to neutralize formula injection in: {malicious!r}"

    # Legitimate numbers (including negative numbers and integers) must remain numeric
    assert sanitize_csv_cell(123) == "123"
    assert sanitize_csv_cell(-125.50) == "-125.5"
    assert sanitize_csv_cell(0) == "0"
    assert sanitize_csv_cell("+100") == "+100"
    assert sanitize_csv_cell("-45.99") == "-45.99"
    assert sanitize_csv_cell(None) == ""


def test_path_traversal_and_file_upload_guards(isolated_phase10_env):
    """Test 8: Verify path traversal defense and filename sanitization."""
    # 1. Filename sanitization
    assert sanitize_filename("../../etc/passwd.pdf") == "passwd.pdf"
    assert sanitize_filename("..\\..\\windows\\system32\\cmd.exe.pdf") == "cmd.exe.pdf"
    assert sanitize_filename("safe_document.pdf") == "safe_document.pdf"

    # 2. Path traversal bound check
    storage_dir = isolated_phase10_env["storage_dir"]

    # Write a test file within storage
    test_rel = "shp-100/test.pdf"
    target_f = storage_dir / test_rel
    target_f.parent.mkdir(parents=True, exist_ok=True)
    target_f.write_bytes(b"Sample PDF bytes")

    safe_path = get_document_file_path(test_rel)
    assert safe_path is not None
    assert safe_path.resolve().is_relative_to(storage_dir.resolve())

    # Resolving traversal path raises ValueError
    with pytest.raises(ValueError):
        get_document_file_path("../../../etc/shadow")


def test_notification_worker_lease_recovery_and_durability(isolated_phase10_env):
    """Test 9: Reclaim expired worker leases and route exhausted retries to dead-letter state."""
    env = isolated_phase10_env
    db_path = env["db_path"]

    past_iso = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()

    notif_id_1 = "notif-lease-retry-01"
    notif_id_2 = "notif-lease-exhaust-02"

    with get_connection(db_path) as conn:
        # Stuck notification with attempts remaining
        conn.execute(
            """
            INSERT INTO collaboration_notifications (
                id, recipient_type, recipient_id, event_type, title, message,
                delivery_channel, delivery_status, attempt_count, max_attempts,
                claimed_by, claimed_at, lease_expires_at, created_at, updated_at
            ) VALUES (?, 'customer', 'cust-1', 'document_shared', 'Order Update', 'Message',
                      'email', 'processing', 1, 3, 'worker-dead', ?, ?, ?, ?)
            """,
            (notif_id_1, past_iso, past_iso, past_iso, past_iso),
        )
        # Stuck notification with attempts exhausted
        conn.execute(
            """
            INSERT INTO collaboration_notifications (
                id, recipient_type, recipient_id, event_type, title, message,
                delivery_channel, delivery_status, attempt_count, max_attempts,
                claimed_by, claimed_at, lease_expires_at, created_at, updated_at
            ) VALUES (?, 'customer', 'cust-2', 'asn_submitted', 'ASN Update', 'Message',
                      'email', 'processing', 3, 3, 'worker-dead', ?, ?, ?, ?)
            """,
            (notif_id_2, past_iso, past_iso, past_iso, past_iso),
        )
        conn.commit()

    # Run lease reclamation
    reclaimed = reclaim_expired_leases()
    assert reclaimed == 2

    with get_connection(db_path) as conn:
        row1 = conn.execute(
            "SELECT delivery_status, claimed_by, error_class FROM collaboration_notifications WHERE id = ?",
            (notif_id_1,),
        ).fetchone()
        assert row1["delivery_status"] == "retry_pending"
        assert row1["claimed_by"] is None
        assert row1["error_class"] == "lease_expired_reclaimed"

        row2 = conn.execute(
            "SELECT delivery_status, claimed_by, error_class FROM collaboration_notifications WHERE id = ?",
            (notif_id_2,),
        ).fetchone()
        assert row2["delivery_status"] == "failed"
        assert row2["claimed_by"] is None
        assert row2["error_class"] == "lease_expired_exhausted"


def test_zero_business_state_mutations_across_operational_checks(isolated_phase10_env):
    """Test 10: Ensure health checks, lease recovery, and monitoring do not mutate business ledgers."""
    env = isolated_phase10_env
    db_path = env["db_path"]
    client = TestClient(app)

    now = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO customers (id, code, name, country, currency, status, created_at, updated_at)
            VALUES ('cust-p10-01', 'CUST-P10', 'Test Customer', 'IN', 'INR', 'active', ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO sales_orders (
                id, order_number, customer_id, customer_code, customer_name,
                order_date, currency, subtotal, tax_total, grand_total, status, created_at, updated_at
            ) VALUES ('so-p10-01', 'SO-P10-001', 'cust-p10-01', 'CUST-P10', 'Test Customer',
                      ?, 'INR', 1000.0, 180.0, 1180.0, 'confirmed', ?, ?)
            """,
            (now, now, now),
        )
        conn.execute(
            """
            INSERT INTO customer_invoices (
                id, invoice_number, customer_id, customer_code, customer_name, billing_address, invoice_date,
                due_date, currency, exchange_rate, subtotal, tax_total, grand_total,
                outstanding_balance, status, is_posted, created_at, updated_at
            ) VALUES ('inv-p10-01', 'INV-P10-001', 'cust-p10-01', 'CUST-P10', 'Test Customer', '123 Commercial St',
                      ?, ?, 'INR', 1.0, 1000.0, 180.0, 1180.0, 1180.0, 'approved', 1, ?, ?)
            """,
            (now, now, now, now),
        )
        conn.commit()

    # Capture pre-state
    with get_connection(db_path) as conn:
        pre_so = dict(conn.execute("SELECT grand_total, status FROM sales_orders WHERE id = 'so-p10-01'").fetchone())
        pre_inv = dict(conn.execute("SELECT outstanding_balance, status FROM customer_invoices WHERE id = 'inv-p10-01'").fetchone())

    # Execute health checks, monitoring, and lease reclamation
    client.get("/health/live")
    client.get("/health/ready")
    client.get("/api/health")
    reclaim_expired_leases()

    # Verify post-state is 100% identical
    with get_connection(db_path) as conn:
        post_so = dict(conn.execute("SELECT grand_total, status FROM sales_orders WHERE id = 'so-p10-01'").fetchone())
        post_inv = dict(conn.execute("SELECT outstanding_balance, status FROM customer_invoices WHERE id = 'inv-p10-01'").fetchone())

    assert pre_so == post_so
    assert pre_inv == post_inv
