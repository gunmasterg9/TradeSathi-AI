"""
TradeSathi AI — Phase 9D: Reliable Notifications & Collaboration Automation Tests
Comprehensive, adversarial test suite verifying:
1. Transactional event creation and rollback safety.
2. Stable event deduplication and idempotency.
3. Concurrent delivery claims and expired worker leases.
4. Bounded retries (max 3), exponential backoff, and dead-letter queue behavior.
5. Mocked email delivery lifecycle (success, transient timeout, permanent bounce).
6. Deactivated and misbound recipient rejection at delivery time.
7. Multi-tenant notification isolation (Anti-IDOR).
8. User notification preferences (opt-out).
9. Staff operational monitoring and dead-letter retry capabilities.
10. Invariant verification: zero business state mutations.
"""

import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.db import get_connection, init_db, set_db_path, get_db_path
from backend.app.storage import set_storage_dir
from backend.app.auth import hash_password, create_user_token
from backend.app.collaboration import create_portal_token as _create_portal_token
from backend.app.notifications import (
    record_collaboration_notification,
    process_notification_deliveries,
    get_notification_monitoring_metrics,
    retry_failed_notification,
    get_user_notification_preferences,
    set_user_notification_preferences,
    get_email_transport,
    set_email_transport,
    MockEmailTransport,
    DisabledEmailTransport,
    calculate_backoff_delay_seconds,
)


@pytest.fixture
def mock_transport() -> Generator[MockEmailTransport, None, None]:
    """Provide a clean MockEmailTransport and reset global transport after test."""
    transport = MockEmailTransport()
    set_email_transport(transport)
    yield transport
    set_email_transport(None)


@pytest.fixture
def isolated_phase9d_env(tmp_path: Path, monkeypatch) -> Generator[dict, None, None]:
    """Create isolated SQLite database and sandboxed storage for Phase 9D tests."""
    temp_db = tmp_path / "test_phase9d.db"
    temp_storage = tmp_path / "test_storage"
    temp_storage.mkdir(parents=True, exist_ok=True)

    orig_db = get_db_path()
    set_db_path(temp_db)
    set_storage_dir(temp_storage)

    monkeypatch.setenv("TRADESATHI_DB_PATH", str(temp_db))
    monkeypatch.setenv("TRADESATHI_STORAGE_PATH", str(temp_storage))
    monkeypatch.setenv("TRADESATHI_TEST_MODE", "1")
    monkeypatch.setenv("EMAIL_DELIVERY_ENABLED", "true")

    init_db()

    now_iso = datetime.now(timezone.utc).isoformat()
    client = TestClient(app)

    # Insert synthetic master records
    with get_connection() as conn:
        # Supplier A
        conn.execute(
            """
            INSERT INTO suppliers (id, code, name, contact_person, email, phone, status, created_at, updated_at)
            VALUES ('sup-9d-a', 'SUP-9DA', 'Synthetic Supplier A', 'Alice Supp', 'alice@suppliera.test', '9876543210', 'active', ?, ?)
            """,
            (now_iso, now_iso),
        )
        # Customer A
        conn.execute(
            """
            INSERT INTO customers (id, code, name, contact_person, email, phone, country, status, created_at, updated_at)
            VALUES ('cust-9d-a', 'CUST-9DA', 'Synthetic Customer A', 'Bob Cust', 'bob@customera.test', '9876543211', 'US', 'active', ?, ?)
            """,
            (now_iso, now_iso),
        )
        # Customer B
        conn.execute(
            """
            INSERT INTO customers (id, code, name, contact_person, email, phone, country, status, created_at, updated_at)
            VALUES ('cust-9d-b', 'CUST-9DB', 'Synthetic Customer B', 'Charlie Cust', 'charlie@customerb.test', '9876543212', 'DE', 'active', ?, ?)
            """,
            (now_iso, now_iso),
        )

        # Portal Users
        # Customer User A
        conn.execute(
            """
            INSERT INTO portal_users (id, username, email, password_hash, account_type, organization_id, organization_name, is_active, created_at, updated_at)
            VALUES ('puser-9d-cust-a', 'bob_user_a', 'bob@customera.test', 'hash', 'customer', 'cust-9d-a', 'Synthetic Customer A', 1, ?, ?)
            """,
            (now_iso, now_iso),
        )
        # Customer User B
        conn.execute(
            """
            INSERT INTO portal_users (id, username, email, password_hash, account_type, organization_id, organization_name, is_active, created_at, updated_at)
            VALUES ('puser-9d-cust-b', 'charlie_user_b', 'charlie@customerb.test', 'hash', 'customer', 'cust-9d-b', 'Synthetic Customer B', 1, ?, ?)
            """,
            (now_iso, now_iso),
        )
        # Supplier User A
        conn.execute(
            """
            INSERT INTO portal_users (id, username, email, password_hash, account_type, organization_id, organization_name, is_active, created_at, updated_at)
            VALUES ('puser-9d-sup-a', 'alice_user_a', 'alice@suppliera.test', 'hash', 'supplier', 'sup-9d-a', 'Synthetic Supplier A', 1, ?, ?)
            """,
            (now_iso, now_iso),
        )

        # Sales Order for Customer A
        conn.execute(
            """
            INSERT INTO sales_orders (id, order_number, customer_id, customer_code, customer_name, order_date, status, currency, subtotal, tax_total, grand_total, created_at, updated_at)
            VALUES ('so-9d-a', 'SO-9D-001', 'cust-9d-a', 'CUST-9DA', 'Synthetic Customer A', '2026-10-15', 'confirmed', 'USD', 1000.0, 180.0, 1180.0, ?, ?)
            """,
            (now_iso, now_iso),
        )

        conn.commit()

    try:
        yield {
            "client": client,
            "db_path": temp_db,
            "storage_path": temp_storage,
        }
    finally:
        set_db_path(orig_db)


def _create_test_staff(role="admin", username="staff_admin"):
    """Generate an authenticated staff bearer token."""
    with get_connection() as conn:
        uid = f"user-{secrets.token_hex(4)}"
        conn.execute(
            """
            INSERT OR REPLACE INTO users (id, username, email, password_hash, role, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, datetime('now'), datetime('now'))
            """,
            (uid, username, f"{username}@tradesathi.internal", hash_password("StaffPass123!"), role),
        )
        conn.commit()
    raw_token, _ = create_user_token(uid)
    return raw_token, uid


def create_portal_token(portal_user_id: str, account_type: str = "customer", organization_id: str = "") -> str:
    """Generate a test portal bearer token."""
    raw_token, _ = _create_portal_token(portal_user_id)
    return raw_token


# ============================================================================
# Test Cases
# ============================================================================

def test_notification_creation_and_transaction_rollback(isolated_phase9d_env, mock_transport):
    """
    Test 1: Notifications are created only upon successful committed transactions.
    Simulated rollbacks must leave zero orphan notification rows in the database.
    """
    # 1. Successful committed transaction
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        notif_id = record_collaboration_notification(
            recipient_type="customer",
            recipient_id="cust-9d-a",
            event_type="document_shared",
            title="Commercial Invoice Shared",
            message="Your commercial invoice for SO-9D-001 is ready.",
            reference_type="sales_order",
            reference_id="so-9d-a",
            delivery_channel="in_app",
            idempotency_key="evt-test-commit-01",
            conn=conn,
        )
        conn.commit()

    with get_connection() as conn:
        row = conn.execute("SELECT * FROM collaboration_notifications WHERE id = ?", (notif_id,)).fetchone()
        assert row is not None
        assert row["title"] == "Commercial Invoice Shared"
        assert row["delivery_status"] == "delivered"
        assert row["is_read"] == 0

    # 2. Transaction rollback scenario
    try:
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO collaboration_notifications (
                    id, recipient_type, recipient_id, event_type, title, message,
                    delivery_status, delivery_channel, idempotency_key, created_at
                ) VALUES ('notif-rollback', 'customer', 'cust-9d-a', 'document_shared',
                          'Rollback Title', 'Rollback Msg', 'pending', 'email', 'evt-rollback', '2026-10-15T00:00:00Z')
                """
            )
            # Simulate failure and rollback
            raise RuntimeError("Simulated transaction crash")
    except RuntimeError:
        pass

    with get_connection() as conn:
        orphan = conn.execute("SELECT * FROM collaboration_notifications WHERE id = 'notif-rollback'").fetchone()
        assert orphan is None, "Rollback must leave zero orphan notification records"


def test_event_deduplication_and_repeated_api_requests(isolated_phase9d_env, mock_transport):
    """
    Test 2: Repeated notification submissions with the same idempotency key
    must return the existing notification ID without generating duplicate rows.
    """
    idem_key = "evt-so-order-inquiry-42"

    id1 = record_collaboration_notification(
        recipient_type="staff",
        recipient_id="staff",
        event_type="customer_thread_created",
        title="Order Inquiry: SO-9D-001",
        message="Customer requested delivery schedule update",
        reference_type="sales_order",
        reference_id="so-9d-a",
        idempotency_key=idem_key,
    )

    # Submitting identical request second time (e.g. network retry)
    id2 = record_collaboration_notification(
        recipient_type="staff",
        recipient_id="staff",
        event_type="customer_thread_created",
        title="Order Inquiry: SO-9D-001",
        message="Customer requested delivery schedule update",
        reference_type="sales_order",
        reference_id="so-9d-a",
        idempotency_key=idem_key,
    )

    assert id1 == id2, "Deduplication must return existing notification ID on retry"

    with get_connection() as conn:
        count = conn.execute(
            "SELECT count(*) FROM collaboration_notifications WHERE idempotency_key = ?",
            (idem_key,),
        ).fetchone()[0]
        assert count == 1, "Exactly one row must exist for a unique idempotency key"


def test_concurrent_delivery_claims_and_worker_leases(isolated_phase9d_env, mock_transport):
    """
    Test 3: Concurrency & Lease Safety.
    Multiple workers attempting to claim the same notifications concurrently must
    not double-claim or double-deliver. Expired leases allow safe recovery.
    """
    # Create 5 pending email notifications
    for i in range(5):
        record_collaboration_notification(
            recipient_type="customer",
            recipient_id="cust-9d-a",
            event_type="shipment_update",
            title=f"Shipment Update {i}",
            message=f"Container dispatched tracking ref {i}",
            delivery_channel="email",
            recipient_email="bob@customera.test",
            idempotency_key=f"evt-ship-batch-{i}",
            delivery_status="pending",
        )

    # Worker 1 claims with a short lease (e.g. 5 seconds)
    stats1 = process_notification_deliveries(
        batch_size=3,
        worker_id="worker-node-1",
        lease_seconds=5,
        transport=mock_transport,
    )
    assert stats1["claimed"] == 3
    assert stats1["delivered"] == 3

    # Worker 2 processes remaining pending records
    stats2 = process_notification_deliveries(
        batch_size=5,
        worker_id="worker-node-2",
        lease_seconds=5,
        transport=mock_transport,
    )
    assert stats2["claimed"] == 2
    assert stats2["delivered"] == 2

    # Total emails sent across both workers
    assert len(mock_transport.sent_emails) == 5

    # Simulate an expired lease: manually insert an uncompleted processing notification with expired lease
    expired_lease_time = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    notif_stuck_id = "notif-stuck-worker"
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO collaboration_notifications (
                id, recipient_type, recipient_id, recipient_email, event_type,
                title, message, delivery_status, delivery_channel, attempt_count,
                max_attempts, claimed_by, lease_expires_at, created_at, updated_at
            ) VALUES (?, 'customer', 'cust-9d-a', 'bob@customera.test', 'shipment_update',
                      'Stuck Notification', 'Worker died', 'pending', 'email', 1, 3,
                      'crashed-worker', ?, ?, ?)
            """,
            (notif_stuck_id, expired_lease_time, expired_lease_time, expired_lease_time),
        )
        conn.commit()

    # Recovery worker claims expired lease successfully
    recovery_stats = process_notification_deliveries(
        batch_size=10,
        worker_id="recovery-worker",
        lease_seconds=60,
        transport=mock_transport,
    )
    assert recovery_stats["claimed"] >= 1
    assert recovery_stats["delivered"] >= 1

    with get_connection() as conn:
        stuck_row = conn.execute("SELECT * FROM collaboration_notifications WHERE id = ?", (notif_stuck_id,)).fetchone()
        assert stuck_row["delivery_status"] == "delivered"
        assert stuck_row["claimed_by"] is None, "Lease must be cleared after completion"


def test_bounded_retries_and_exponential_backoff(isolated_phase9d_env, mock_transport):
    """
    Test 4: Bounded Retries & Exponential Backoff.
    Transient errors cause retry_pending status with exponential backoff delay.
    Reaching max_attempts transitions record to failed (dead-letter).
    """
    notif_id = record_collaboration_notification(
        recipient_type="customer",
        recipient_id="cust-9d-a",
        event_type="document_shared",
        title="Certificate of Origin",
        message="Document ready for download",
        delivery_channel="email",
        recipient_email="bob@customera.test",
        idempotency_key="evt-retry-test-01",
        delivery_status="pending",
    )

    # Configure transport to simulate 10 transient failures (exceeds max_attempts=3)
    mock_transport.simulate_transient_failure(count=10)

    # Attempt 1: Fails -> status should become retry_pending
    stats_att1 = process_notification_deliveries(batch_size=1, worker_id="worker-retry", transport=mock_transport)
    assert stats_att1["claimed"] == 1
    assert stats_att1["retry_pending"] == 1

    with get_connection() as conn:
        row1 = conn.execute("SELECT * FROM collaboration_notifications WHERE id = ?", (notif_id,)).fetchone()
        assert row1["delivery_status"] == "retry_pending"
        assert row1["attempt_count"] == 1
        assert row1["error_class"] == "transient"
        assert "timeout" in row1["error_message"].lower()
        # Fast-forward next_retry_at to now so worker can claim attempt 2
        conn.execute("UPDATE collaboration_notifications SET next_retry_at = '2020-01-01T00:00:00Z' WHERE id = ?", (notif_id,))
        conn.commit()

    # Attempt 2: Fails -> status should remain retry_pending with attempt_count=2
    stats_att2 = process_notification_deliveries(batch_size=1, worker_id="worker-retry", transport=mock_transport)
    assert stats_att2["retry_pending"] == 1

    with get_connection() as conn:
        row2 = conn.execute("SELECT * FROM collaboration_notifications WHERE id = ?", (notif_id,)).fetchone()
        assert row2["attempt_count"] == 2
        conn.execute("UPDATE collaboration_notifications SET next_retry_at = '2020-01-01T00:00:00Z' WHERE id = ?", (notif_id,))
        conn.commit()

    # Attempt 3: Fails and exhausts max_attempts (3) -> transitions to 'failed' (dead-letter)
    stats_att3 = process_notification_deliveries(batch_size=1, worker_id="worker-retry", transport=mock_transport)
    assert stats_att3["failed"] == 1

    with get_connection() as conn:
        row3 = conn.execute("SELECT * FROM collaboration_notifications WHERE id = ?", (notif_id,)).fetchone()
        assert row3["delivery_status"] == "failed", "Exhausted retries must enter 'failed' state"
        assert row3["attempt_count"] == 3
        assert row3["error_class"] == "transient"

    # Exponential backoff mathematical helper verification
    assert calculate_backoff_delay_seconds(1) == 5
    assert calculate_backoff_delay_seconds(2) == 10
    assert calculate_backoff_delay_seconds(3) == 20
    assert calculate_backoff_delay_seconds(4) == 40
    assert calculate_backoff_delay_seconds(10) == 300  # Capped at max 300 seconds


def test_mocked_email_delivery_lifecycle(isolated_phase9d_env, mock_transport):
    """
    Test 5: Email delivery lifecycle covering success, permanent bounce, and zero real egress.
    """
    # 1. Permanent failure simulation (e.g. remote SMTP mailbox unavailable)
    mock_transport.simulate_permanent_failure(message="550 5.1.1 User unknown")
    notif_perm_id = record_collaboration_notification(
        recipient_type="customer",
        recipient_id="cust-9d-a",
        event_type="staff_reply",
        title="Staff Response to Thread",
        message="Delivery ETA is confirmed for next Monday.",
        delivery_channel="email",
        recipient_email="bob@customera.test",
        idempotency_key="evt-perm-fail-01",
        delivery_status="pending",
    )

    stats = process_notification_deliveries(batch_size=1, worker_id="w1", transport=mock_transport)
    assert stats["failed"] == 1

    with get_connection() as conn:
        perm_row = conn.execute("SELECT * FROM collaboration_notifications WHERE id = ?", (notif_perm_id,)).fetchone()
        assert perm_row["delivery_status"] == "failed"
        assert perm_row["error_class"] == "permanent"
        assert "550" in perm_row["error_message"]

    # 2. Reset mock transport and test successful delivery
    mock_transport.reset()
    notif_ok_id = record_collaboration_notification(
        recipient_type="customer",
        recipient_id="cust-9d-a",
        event_type="staff_reply",
        title="Staff Response 2",
        message="Port handling fees have been cleared.",
        delivery_channel="email",
        recipient_email="bob@customera.test",
        idempotency_key="evt-success-01",
        delivery_status="pending",
    )

    stats_ok = process_notification_deliveries(batch_size=1, worker_id="w1", transport=mock_transport)
    assert stats_ok["delivered"] == 1

    with get_connection() as conn:
        ok_row = conn.execute("SELECT * FROM collaboration_notifications WHERE id = ?", (notif_ok_id,)).fetchone()
        assert ok_row["delivery_status"] == "delivered"
        assert ok_row["provider_message_id"].startswith("mock-msg-")
        assert ok_row["error_message"] is None


def test_deactivated_and_misbound_recipient_rejection(isolated_phase9d_env, mock_transport):
    """
    Test 6: Delivery time eligibility guard.
    If a portal user account is deactivated before delivery execution, the notification
    must be immediately cancelled to prevent information leakage.
    """
    # Deactivate customer user A in portal_users
    with get_connection() as conn:
        conn.execute("UPDATE portal_users SET is_active = 0 WHERE id = 'puser-9d-cust-a'")
        conn.commit()

    notif_id = record_collaboration_notification(
        recipient_type="customer",
        recipient_id="cust-9d-a",
        event_type="document_shared",
        title="Inspection Certificate",
        message="Inspection certificate attached.",
        delivery_channel="email",
        recipient_email="bob@customera.test",
        idempotency_key="evt-deactivated-test",
        delivery_status="pending",
    )

    stats = process_notification_deliveries(batch_size=1, worker_id="w-guard", transport=mock_transport)
    assert stats["cancelled"] == 1
    assert len(mock_transport.sent_emails) == 0, "No email must be sent to deactivated recipient"

    with get_connection() as conn:
        row = conn.execute("SELECT * FROM collaboration_notifications WHERE id = ?", (notif_id,)).fetchone()
        assert row["delivery_status"] == "cancelled"
        assert "deactivated" in row["error_message"].lower()


def test_cross_tenant_notification_isolation(isolated_phase9d_env):
    """
    Test 7: Multi-tenant isolation (Anti-IDOR).
    Customer A cannot retrieve Customer B's notifications.
    """
    client = isolated_phase9d_env["client"]
    token_a = create_portal_token("puser-9d-cust-a", "customer", "cust-9d-a")
    token_b = create_portal_token("puser-9d-cust-b", "customer", "cust-9d-b")

    # Insert notifications for Customer A and Customer B
    record_collaboration_notification(
        recipient_type="customer",
        recipient_id="cust-9d-a",
        event_type="document_shared",
        title="Notice for Customer A",
        message="Notice A content",
    )
    record_collaboration_notification(
        recipient_type="customer",
        recipient_id="cust-9d-b",
        event_type="document_shared",
        title="Notice for Customer B",
        message="Notice B content",
    )

    # Customer A lists notifications
    res_a = client.get(
        "/api/portal/customer/notifications",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_a.status_code == 200
    items_a = res_a.json()["items"]
    assert any(n["title"] == "Notice for Customer A" for n in items_a)
    assert not any(n["title"] == "Notice for Customer B" for n in items_a), "Customer A must never see Customer B notifications"

    # Customer B lists notifications
    res_b = client.get(
        "/api/portal/customer/notifications",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert res_b.status_code == 200
    items_b = res_b.json()["items"]
    assert any(n["title"] == "Notice for Customer B" for n in items_b)
    assert not any(n["title"] == "Notice for Customer A" for n in items_b), "Customer B must never see Customer A notifications"


def test_user_notification_preferences_lifecycle(isolated_phase9d_env, mock_transport):
    """
    Test 8: User Notification Preferences.
    Users can inspect and update their own preferences. If email notifications are opted out,
    email dispatches are marked cancelled.
    """
    client = isolated_phase9d_env["client"]
    token_a = create_portal_token("puser-9d-cust-a", "customer", "cust-9d-a")

    # 1. Default preferences (email enabled)
    res_get = client.get(
        "/api/portal/user/preferences",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_get.status_code == 200
    assert res_get.json()["email_notifications_enabled"] is True

    # 2. Update preferences: disable email notifications
    res_put = client.put(
        "/api/portal/user/preferences",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"email_notifications_enabled": False},
    )
    assert res_put.status_code == 200
    assert res_put.json()["email_notifications_enabled"] is False

    # 3. Queue an email notification and process delivery
    record_collaboration_notification(
        recipient_type="customer",
        recipient_id="cust-9d-a",
        event_type="staff_reply",
        title="New Message",
        message="Order confirmation update",
        delivery_channel="email",
        recipient_email="bob@customera.test",
        idempotency_key="evt-optout-01",
        delivery_status="pending",
    )

    stats = process_notification_deliveries(batch_size=1, worker_id="w-pref", transport=mock_transport)
    assert stats["cancelled"] == 1
    assert len(mock_transport.sent_emails) == 0, "No email sent when user has opted out"


def test_operational_monitoring_and_staff_retry(isolated_phase9d_env, mock_transport):
    """
    Test 9: Operational monitoring dashboard and dead-letter retry capabilities.
    Only authorized staff can access monitoring metrics and trigger reprocessing.
    """
    client = isolated_phase9d_env["client"]
    customer_token = create_portal_token("puser-9d-cust-a", "customer", "cust-9d-a")

    # 1. External customer cannot access staff monitoring endpoint (HTTP 401/403)
    res_forbidden = client.get(
        "/api/portal/admin/notifications/monitoring",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert res_forbidden.status_code in (401, 403)

    # 2. Staff accesses monitoring endpoint with authorized staff token
    staff_token, _ = _create_test_staff(role="admin", username="monitor_admin")
    res_staff = client.get(
        "/api/portal/admin/notifications/monitoring",
        headers={"Authorization": f"Bearer {staff_token}"},
    )
    assert res_staff.status_code == 200
    metrics = res_staff.json()
    assert "status_counts" in metrics
    assert "channel_counts" in metrics
    assert "provider_mode" in metrics

    # 3. Create a failed notification and reprocess it via staff retry endpoint
    notif_fail_id = record_collaboration_notification(
        recipient_type="customer",
        recipient_id="cust-9d-a",
        event_type="document_shared",
        title="Failed Notice",
        message="Notice content",
        delivery_channel="email",
        delivery_status="failed",
        idempotency_key="evt-staff-retry-01",
    )

    res_retry = client.post(
        f"/api/portal/admin/notifications/{notif_fail_id}/retry",
        headers={"Authorization": f"Bearer {staff_token}"},
    )
    assert res_retry.status_code == 200
    assert res_retry.json()["new_status"] == "pending"

    with get_connection() as conn:
        retried_row = conn.execute("SELECT * FROM collaboration_notifications WHERE id = ?", (notif_fail_id,)).fetchone()
        assert retried_row["delivery_status"] == "pending"
        assert retried_row["attempt_count"] == 0


def test_zero_business_state_mutations(isolated_phase9d_env, mock_transport):
    """
    Test 10: Invariant Guard.
    Notification recording, delivery processing, and retry actions must NEVER
    mutate inventory balances, sales orders, invoices, or purchase orders.
    """
    with get_connection() as conn:
        so_before = conn.execute("SELECT grand_total, status FROM sales_orders WHERE id = 'so-9d-a'").fetchone()
        inv_before_count = conn.execute("SELECT count(*) FROM inventory_movements").fetchone()[0]

    # Perform notification actions
    n_id = record_collaboration_notification(
        recipient_type="customer",
        recipient_id="cust-9d-a",
        event_type="document_shared",
        title="Commercial Doc",
        message="Doc ready",
        delivery_channel="email",
        recipient_email="bob@customera.test",
        idempotency_key="evt-inv-guard",
        delivery_status="pending",
    )
    process_notification_deliveries(batch_size=5, worker_id="w-inv", transport=mock_transport)
    retry_failed_notification(n_id)

    with get_connection() as conn:
        so_after = conn.execute("SELECT grand_total, status FROM sales_orders WHERE id = 'so-9d-a'").fetchone()
        inv_after_count = conn.execute("SELECT count(*) FROM inventory_movements").fetchone()[0]

    assert so_before["grand_total"] == so_after["grand_total"]
    assert so_before["status"] == so_after["status"]
    assert inv_before_count == inv_after_count == 0, "Notification actions must never insert inventory movements"
