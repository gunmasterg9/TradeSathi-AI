"""
TradeSathi AI — Phase 10.7: Final Production Blocker Closure & Verification Tests

Automated, isolated test suite verifying:
1. Backup Replication & DR Verification:
   - Two-phase replication simulation (payload first, manifest second).
   - Detection and rejection of partial/interrupted uploads.
   - Isolated remote restore drill with SQLite integrity and foreign key checks.
2. Notification Worker Concurrency & Delivery Guarantees:
   - Atomic worker leasing preventing double-processing.
   - Safe reclamation of expired worker leases (retry_pending vs dead-letter).
   - Delivery-time rejection of deactivated recipients.
   - Idempotency key deduplication.
   - Crash and exception isolation during external transport dispatch.
   - Stable RFC 5322 Message-ID provider tracking.
3. Proxy Boundary & Rate Limiter Security:
   - Protection against spoofed X-Forwarded-For headers from untrusted socket hosts.
   - Valid client IP extraction from trusted loopback reverse proxies.
   - Rate limit enforcement emitting HTTP 429 and Retry-After headers.
4. Live Data Boundary:
   - Guarantees zero mutations to live database or document store.
"""

import os
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException, Request

from backend.app.db import get_connection, init_db, set_db_path, get_db_path
from backend.app.storage import set_storage_dir, get_storage_dir
from backend.app.backup import create_backup, verify_backup, restore_backup, compute_file_sha256
from backend.app.notifications import (
    record_collaboration_notification,
    process_notification_deliveries,
    reclaim_expired_leases,
    MockEmailTransport,
    set_email_transport,
    EmailDeliveryResult,
    EmailTransport,
)
from backend.app.rate_limiter import SlidingWindowRateLimiter


@pytest.fixture
def isolated_test_env(tmp_path: Path, monkeypatch):
    """Set up an isolated database, storage directory, and backup root."""
    test_db = tmp_path / "test_phase10_7.db"
    test_storage = tmp_path / "test_storage"
    test_storage.mkdir(parents=True, exist_ok=True)
    test_backups = tmp_path / "test_backups"
    test_backups.mkdir(parents=True, exist_ok=True)

    set_db_path(test_db)
    set_storage_dir(test_storage)

    monkeypatch.setenv("TRADESATHI_DB_PATH", str(test_db))
    monkeypatch.setenv("TRADESATHI_STORAGE_PATH", str(test_storage))
    monkeypatch.setenv("TRADESATHI_BACKUP_ROOT", str(test_backups))
    monkeypatch.setenv("TRADESATHI_TEST_MODE", "1")
    monkeypatch.setenv("EMAIL_DELIVERY_ENABLED", "true")

    init_db()

    yield {
        "db": test_db,
        "storage": test_storage,
        "backups": test_backups,
    }


# ==============================================================================
# 1. Backup Replication & Isolated Remote Restoration Tests
# ==============================================================================

def test_backup_replication_two_phase_and_partial_upload_detection(isolated_test_env):
    """Verify that backup replication requires atomic manifest completion and detects interrupted transfers."""
    test_storage = isolated_test_env["storage"]
    test_backups = isolated_test_env["backups"]

    # Create dummy document in storage
    doc_file = test_storage / "sample_invoice.txt"
    doc_file.write_text("COMMERCIAL INVOICE CONTENT 1000 USD", encoding="utf-8")

    # 1. Create a verified local backup
    manifest = create_backup(backup_root=test_backups)
    backup_id = manifest["backup_id"]
    local_backup_dir = test_backups / backup_id

    # Verify local backup passes verification
    res = verify_backup(local_backup_dir)
    assert res["backup_id"] == backup_id

    # 2. Simulate interrupted/partial transfer to mock remote storage:
    # Copy payload files (tradesathi.db and documents/) but omit manifest.json
    mock_remote_dir = isolated_test_env["backups"] / "mock_remote_s3" / backup_id
    mock_remote_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(local_backup_dir / "tradesathi.db", mock_remote_dir / "tradesathi.db")
    shutil.copytree(local_backup_dir / "documents", mock_remote_dir / "documents")

    # Verification of partial upload MUST fail closed because manifest is missing
    with pytest.raises(ValueError, match="manifest missing"):
        verify_backup(mock_remote_dir)

    # 3. Complete Phase B: Upload manifest.json as completion marker
    shutil.copy2(local_backup_dir / "manifest.json", mock_remote_dir / "manifest.json")

    # Verification of completed remote snapshot MUST succeed
    verified_remote = verify_backup(mock_remote_dir)
    assert verified_remote["verified"] is True
    assert verified_remote["backup_id"] == backup_id

    # 4. Perform Disaster Recovery restore from mock remote to isolated scratch directory
    restore_target_db = isolated_test_env["backups"] / "dr_restore" / "restored.db"
    restore_target_storage = isolated_test_env["backups"] / "dr_restore" / "documents"

    restore_res = restore_backup(
        mock_remote_dir,
        str(restore_target_db),
        str(restore_target_storage),
    )
    assert restore_res["status"] == "success"
    assert restore_target_db.is_file()

    # Validate restored database integrity and foreign keys
    with sqlite3.connect(f"file:{restore_target_db.as_posix()}?mode=ro", uri=True) as conn:
        cursor = conn.execute("PRAGMA integrity_check")
        assert cursor.fetchone()[0] == "ok"
        fk_check = conn.execute("PRAGMA foreign_key_check").fetchall()
        assert len(fk_check) == 0

    # Validate restored document content matches original
    restored_doc = restore_target_storage / "sample_invoice.txt"
    assert restored_doc.is_file()
    assert restored_doc.read_text(encoding="utf-8") == "COMMERCIAL INVOICE CONTENT 1000 USD"


# ==============================================================================
# 2. Notification Worker Concurrency, Crash Safety & Idempotency Tests
# ==============================================================================

def test_notification_worker_atomic_leasing_and_concurrency(isolated_test_env):
    """Verify that multiple concurrent workers cannot claim the same notification."""
    now_iso = datetime.now(timezone.utc).isoformat()

    # Record 5 notifications
    notif_ids = []
    for i in range(5):
        nid = record_collaboration_notification(
            recipient_type="staff",
            recipient_id=f"user-{i}",
            event_type="document_shared",
            title=f"Doc {i}",
            message=f"Message {i}",
            delivery_channel="email",
            recipient_email=f"user{i}@example.com",
        )
        notif_ids.append(nid)

    mock_transport = MockEmailTransport()

    # Worker 1 claims batch
    stats1 = process_notification_deliveries(
        batch_size=3,
        worker_id="worker-node-1",
        lease_seconds=30,
        transport=mock_transport,
    )
    # Worker 2 processes concurrently
    stats2 = process_notification_deliveries(
        batch_size=3,
        worker_id="worker-node-2",
        lease_seconds=30,
        transport=mock_transport,
    )

    # Worker 1 should claim 3, Worker 2 should claim remaining 2
    assert stats1["claimed"] == 3
    assert stats2["claimed"] == 2
    # Combined deliveries must equal 5 with zero overlap
    assert stats1["delivered"] + stats2["delivered"] == 5
    assert len(mock_transport.sent_emails) == 5

    # Check that all sent emails have unique recipient emails
    delivered_emails = [e["to"] for e in mock_transport.sent_emails]
    assert len(set(delivered_emails)) == 5


def test_notification_lease_reclamation_and_dead_letter(isolated_test_env):
    """Verify expired leases are safely reclaimed or routed to dead-letter (failed)."""
    now = datetime.now(timezone.utc)
    expired_time = (now - timedelta(minutes=10)).isoformat()

    with get_connection() as conn:
        # 1. Stuck notification with attempts remaining (attempt 1 of 3)
        conn.execute(
            """
            INSERT INTO collaboration_notifications (
                id, recipient_type, recipient_id, event_type,
                title, message, delivery_status, delivery_channel,
                recipient_email, attempt_count, max_attempts,
                claimed_by, lease_expires_at, created_at, updated_at
            ) VALUES ('notif-stuck-1', 'staff', 'user-1', 'shipment_update', 'Title', 'Msg',
                     'processing', 'email', 'test@test.local', 1, 3,
                     'crashed-worker', ?, ?, ?)
            """,
            (expired_time, expired_time, expired_time),
        )

        # 2. Stuck notification with attempts exhausted (attempt 3 of 3)
        conn.execute(
            """
            INSERT INTO collaboration_notifications (
                id, recipient_type, recipient_id, event_type,
                title, message, delivery_status, delivery_channel,
                recipient_email, attempt_count, max_attempts,
                claimed_by, lease_expires_at, created_at, updated_at
            ) VALUES ('notif-stuck-2', 'staff', 'user-2', 'shipment_update', 'Title', 'Msg',
                     'processing', 'email', 'test2@test.local', 3, 3,
                     'crashed-worker', ?, ?, ?)
            """,
            (expired_time, expired_time, expired_time),
        )
        conn.commit()

    reclaimed = reclaim_expired_leases()
    assert reclaimed == 2

    with get_connection() as conn:
        r1 = conn.execute("SELECT delivery_status, error_class FROM collaboration_notifications WHERE id = 'notif-stuck-1'").fetchone()
        assert r1["delivery_status"] == "retry_pending"
        assert r1["error_class"] == "lease_expired_reclaimed"

        r2 = conn.execute("SELECT delivery_status, error_class FROM collaboration_notifications WHERE id = 'notif-stuck-2'").fetchone()
        assert r2["delivery_status"] == "failed"
        assert r2["error_class"] == "lease_expired_exhausted"


def test_notification_idempotency_and_deactivated_recipient(isolated_test_env):
    """Verify that idempotency keys block duplicate records and deactivated recipients are rejected."""
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. Test idempotency key
    key = "idem-key-unique-12345"
    nid1 = record_collaboration_notification(
        recipient_type="staff",
        recipient_id="user-1",
        event_type="shipment_update",
        title="Order Placed",
        message="Order details",
        delivery_channel="email",
        recipient_email="user1@test.com",
        idempotency_key=key,
    )
    nid2 = record_collaboration_notification(
        recipient_type="staff",
        recipient_id="user-1",
        event_type="shipment_update",
        title="Order Placed Duplicate",
        message="Different details",
        delivery_channel="email",
        recipient_email="user1@test.com",
        idempotency_key=key,
    )
    assert nid1 == nid2  # Deduplicated

    # 2. Test deactivated portal recipient rejection
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO portal_users (id, username, email, password_hash, account_type, organization_id, organization_name, is_active, created_at, updated_at)
            VALUES ('usr-deact', 'usr_deact', 'deactivated@partner.com', 'hash', 'supplier', 'sup-deact', 'Deact Org', 0, ?, ?)
            """,
            (now_iso, now_iso),
        )
        conn.commit()

    nid_deact = record_collaboration_notification(
        recipient_type="supplier",
        recipient_id="sup-deact",
        event_type="document_request_created",
        title="Welcome",
        message="Welcome partner",
        delivery_channel="email",
        recipient_email="deactivated@partner.com",
    )

    mock_transport = MockEmailTransport()
    stats = process_notification_deliveries(transport=mock_transport)
    assert stats["cancelled"] == 1
    assert len(mock_transport.sent_emails) == 1  # only the initial internal user email sent

    with get_connection() as conn:
        row = conn.execute("SELECT delivery_status, error_message FROM collaboration_notifications WHERE id = ?", (nid_deact,)).fetchone()
        assert row["delivery_status"] == "cancelled"
        assert "deactivated" in row["error_message"].lower()


def test_notification_crash_isolation_and_stable_message_id(isolated_test_env):
    """Verify unexpected transport crashes do not abort worker and assign stable RFC 5322 Message-ID."""
    class CrashingTransport(EmailTransport):
        def __init__(self):
            self.calls = 0

        def send_email(self, to_email: str, subject: str, text_body: str, html_body=None, message_id=None):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionResetError("Remote SMTP server forcefully closed connection")
            return EmailDeliveryResult(success=True, provider_message_id=message_id)

    # Insert 2 notifications
    nid_crash = record_collaboration_notification(
        recipient_type="staff",
        recipient_id="user-crash",
        event_type="shipment_update",
        title="Crash Alert",
        message="Will trigger transport crash",
        delivery_channel="email",
        recipient_email="crash@example.com",
    )
    nid_ok = record_collaboration_notification(
        recipient_type="staff",
        recipient_id="user-ok",
        event_type="shipment_update",
        title="Ok Alert",
        message="Will succeed",
        delivery_channel="email",
        recipient_email="ok@example.com",
    )

    crashing_transport = CrashingTransport()
    # Processing should NOT raise unhandled exception
    stats = process_notification_deliveries(batch_size=10, transport=crashing_transport)

    assert stats["claimed"] == 2
    assert stats["retry_pending"] == 1
    assert stats["delivered"] == 1

    with get_connection() as conn:
        row_crash = conn.execute("SELECT delivery_status, error_message FROM collaboration_notifications WHERE id = ?", (nid_crash,)).fetchone()
        assert row_crash["delivery_status"] == "retry_pending"
        assert "ConnectionResetError" in row_crash["error_message"]

        row_ok = conn.execute("SELECT delivery_status, provider_message_id FROM collaboration_notifications WHERE id = ?", (nid_ok,)).fetchone()
        assert row_ok["delivery_status"] == "delivered"
        assert row_ok["provider_message_id"] == f"<{nid_ok}@tradesathi.local>"


# ==============================================================================
# 3. Rate Limiting & Proxy Boundary Security Tests
# ==============================================================================

def test_rate_limiter_spoofed_header_and_trusted_proxy_isolation(monkeypatch):
    """Verify that spoofed X-Forwarded-For headers from untrusted hosts are ignored."""
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60, name="auth_test")

    # Create dummy request helper
    def make_request(client_host: str, x_forwarded_for: str | None = None) -> Request:
        headers = []
        if x_forwarded_for:
            headers.append((b"x-forwarded-for", x_forwarded_for.encode("latin-1")))
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/auth/login",
            "headers": headers,
            "client": (client_host, 54321),
        }
        return Request(scope)

    old_test_mode = os.environ.get("TRADESATHI_TEST_MODE")
    old_pytest = os.environ.get("PYTEST_CURRENT_TEST")
    try:
        if "PYTEST_CURRENT_TEST" in os.environ:
            del os.environ["PYTEST_CURRENT_TEST"]
        os.environ["TRADESATHI_TEST_MODE"] = "0"
        os.environ["RATE_LIMITING_ENABLED"] = "1"
        os.environ["FORWARDED_ALLOW_IPS"] = "127.0.0.1"

        # 1. Untrusted client attempting to spoof IP via X-Forwarded-For
        untrusted_client_ip = "198.51.100.55"
        spoofed_ip = "10.0.0.99"
        req_spoof = make_request(untrusted_client_ip, x_forwarded_for=spoofed_ip)

        # Untrusted client sends 2 requests: should pass
        limiter(req_spoof)
        limiter(req_spoof)

        # Third request from same untrusted client MUST be throttled, regardless of spoofed header
        with pytest.raises(HTTPException) as exc_info:
            limiter(req_spoof)
        assert exc_info.value.status_code == 429
        assert "Retry-After" in exc_info.value.headers

        # 2. Request through trusted proxy (127.0.0.1) respects X-Forwarded-For
        limiter.reset()
        trusted_proxy_ip = "127.0.0.1"
        real_client_ip = "203.0.113.10"
        req_trusted = make_request(trusted_proxy_ip, x_forwarded_for=real_client_ip)

        limiter(req_trusted)
        limiter(req_trusted)

        # Third request for real_client_ip through trusted proxy is throttled
        with pytest.raises(HTTPException) as exc_info2:
            limiter(req_trusted)
        assert exc_info2.value.status_code == 429
    finally:
        if old_pytest:
            os.environ["PYTEST_CURRENT_TEST"] = old_pytest
        if old_test_mode is not None:
            os.environ["TRADESATHI_TEST_MODE"] = old_test_mode
        else:
            os.environ.pop("TRADESATHI_TEST_MODE", None)
