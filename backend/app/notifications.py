"""
TradeSathi AI — Phase 9D: Reliable Notifications & Collaboration Automation
Provides durable notification recording, deduplication, atomic worker leasing,
exponential backoff retry policies, recipient eligibility checks, email transports
(Mock, Disabled, SMTP), and operational monitoring metrics.
"""

from __future__ import annotations

import logging
import math
import os
import smtplib
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Literal

from .db import get_connection

logger = logging.getLogger("tradesathi.notifications")


# ============================================================================
# 1. Email Delivery Result & Transport Abstractions
# ============================================================================

class EmailDeliveryResult:
    """Encapsulates the outcome of an external email dispatch attempt."""

    def __init__(
        self,
        success: bool,
        provider_message_id: str | None = None,
        error_message: str | None = None,
        error_class: Literal["transient", "permanent"] | None = None,
    ):
        self.success = success
        self.provider_message_id = provider_message_id
        self.error_message = error_message
        self.error_class = error_class

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "provider_message_id": self.provider_message_id,
            "error_message": self.error_message,
            "error_class": self.error_class,
        }


class EmailTransport(ABC):
    """Abstract interface for email delivery providers."""

    @abstractmethod
    def send_email(
        self,
        to_email: str,
        subject: str,
        text_body: str,
        html_body: str | None = None,
        message_id: str | None = None,
    ) -> EmailDeliveryResult:
        """Send an email to a single recipient with optional provider message_id."""
        pass


class MockEmailTransport(EmailTransport):
    """
    In-memory email transport for deterministic, zero-egress automated tests.
    Supports simulating transient network timeouts and permanent recipient bounces.
    """

    def __init__(self):
        self.sent_emails: list[dict[str, Any]] = []
        self.transient_failures_remaining: int = 0
        self.permanent_failure: bool = False
        self.permanent_failure_message: str = "Permanent delivery rejection: Address does not exist"

    def reset(self) -> None:
        self.sent_emails.clear()
        self.transient_failures_remaining = 0
        self.permanent_failure = False

    def simulate_transient_failure(self, count: int = 1) -> None:
        self.transient_failures_remaining = count

    def simulate_permanent_failure(self, message: str | None = None) -> None:
        self.permanent_failure = True
        if message:
            self.permanent_failure_message = message

    def send_email(
        self,
        to_email: str,
        subject: str,
        text_body: str,
        html_body: str | None = None,
        message_id: str | None = None,
    ) -> EmailDeliveryResult:
        if self.permanent_failure:
            logger.info("MockEmailTransport: Simulating permanent rejection for %s", to_email)
            return EmailDeliveryResult(
                success=False,
                error_message=self.permanent_failure_message,
                error_class="permanent",
            )

        if self.transient_failures_remaining > 0:
            self.transient_failures_remaining -= 1
            logger.info(
                "MockEmailTransport: Simulating transient timeout (%d remaining)",
                self.transient_failures_remaining,
            )
            return EmailDeliveryResult(
                success=False,
                error_message="Simulated network timeout connecting to SMTP server (transient)",
                error_class="transient",
            )

        msg_id = f"mock-msg-{uuid.uuid4().hex[:12]}"
        record = {
            "message_id": msg_id,
            "client_message_id": message_id,
            "to": to_email,
            "subject": subject,
            "text_body": text_body,
            "html_body": html_body,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }
        self.sent_emails.append(record)
        logger.info("MockEmailTransport: Successfully delivered email %s to %s", msg_id, to_email)
        return EmailDeliveryResult(
            success=True,
            provider_message_id=msg_id,
        )


class DisabledEmailTransport(EmailTransport):
    """
    Default production transport when external email delivery is not configured
    or explicitly disabled via EMAIL_DELIVERY_ENABLED=false.
    """

    def send_email(
        self,
        to_email: str,
        subject: str,
        text_body: str,
        html_body: str | None = None,
        message_id: str | None = None,
    ) -> EmailDeliveryResult:
        return EmailDeliveryResult(
            success=False,
            error_message="Outbound email delivery is disabled by configuration (EMAIL_DELIVERY_ENABLED=false).",
            error_class="permanent",
        )


class SmtpEmailTransport(EmailTransport):
    """
    Standard TLS/STARTTLS SMTP transport for production email dispatch.
    Scrubs credentials and authorization headers from error messages and logs.
    """

    def __init__(
        self,
        host: str,
        port: int = 587,
        username: str | None = None,
        password: str | None = None,
        from_email: str = "noreply@tradesathi.local",
        use_tls: bool = True,
        timeout_seconds: int = 10,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.use_tls = use_tls
        self.timeout = timeout_seconds

    def send_email(
        self,
        to_email: str,
        subject: str,
        text_body: str,
        html_body: str | None = None,
        message_id: str | None = None,
    ) -> EmailDeliveryResult:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.from_email
        msg["To"] = to_email
        domain = self.from_email.split("@")[-1] if "@" in self.from_email else "tradesathi.local"
        assigned_msg_id = message_id or f"<{uuid.uuid4().hex}@{domain}>"
        msg["Message-ID"] = assigned_msg_id
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        if html_body:
            msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as server:
                if self.use_tls:
                    server.starttls()
                if self.username and self.password:
                    server.login(self.username, self.password)
                server.send_message(msg)

            return EmailDeliveryResult(success=True, provider_message_id=assigned_msg_id)

        except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, TimeoutError) as exc:
            logger.warning("SMTP transient connection error: %s", type(exc).__name__)
            return EmailDeliveryResult(
                success=False,
                error_message=f"Transient SMTP error: {type(exc).__name__}",
                error_class="transient",
            )
        except smtplib.SMTPRecipientsRefused as exc:
            logger.warning("SMTP permanent recipient refused for %s", to_email)
            return EmailDeliveryResult(
                success=False,
                error_message="Recipient address rejected by remote server.",
                error_class="permanent",
            )
        except smtplib.SMTPAuthenticationError:
            logger.error("SMTP authentication failed. Check configured credentials.")
            return EmailDeliveryResult(
                success=False,
                error_message="SMTP authentication failed on configured relay.",
                error_class="permanent",
            )
        except Exception as exc:
            logger.exception("Unexpected error during SMTP send: %s", type(exc).__name__)
            return EmailDeliveryResult(
                success=False,
                error_message=f"Unexpected delivery error: {type(exc).__name__}",
                error_class="transient",
            )


# Global Transport Singleton & Accessors
_GLOBAL_EMAIL_TRANSPORT: EmailTransport | None = None


def get_email_transport() -> EmailTransport:
    """Resolve active email transport provider according to environment configuration."""
    global _GLOBAL_EMAIL_TRANSPORT
    if _GLOBAL_EMAIL_TRANSPORT is not None:
        return _GLOBAL_EMAIL_TRANSPORT

    enabled = os.getenv("EMAIL_DELIVERY_ENABLED", "false").lower() in ("true", "1", "yes")
    smtp_host = os.getenv("SMTP_HOST")

    if not enabled or not smtp_host:
        _GLOBAL_EMAIL_TRANSPORT = DisabledEmailTransport()
    else:
        _GLOBAL_EMAIL_TRANSPORT = SmtpEmailTransport(
            host=smtp_host,
            port=int(os.getenv("SMTP_PORT", "587")),
            username=os.getenv("SMTP_USER"),
            password=os.getenv("SMTP_PASSWORD"),
            from_email=os.getenv("SMTP_FROM_EMAIL", "noreply@tradesathi.local"),
            use_tls=os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes"),
        )
    return _GLOBAL_EMAIL_TRANSPORT


def set_email_transport(transport: EmailTransport | None) -> None:
    """Override email transport provider (used extensively in test suites)."""
    global _GLOBAL_EMAIL_TRANSPORT
    _GLOBAL_EMAIL_TRANSPORT = transport


# ============================================================================
# 2. Durable Notification Creation & Deduplication (Gate B & C)
# ============================================================================

def record_collaboration_notification(
    recipient_type: str,
    recipient_id: str,
    event_type: str,
    title: str,
    message: str,
    reference_type: str | None = None,
    reference_id: str | None = None,
    delivery_channel: str = "in_app",
    recipient_email: str | None = None,
    idempotency_key: str | None = None,
    delivery_status: str | None = None,
    conn: Any | None = None,
) -> str:
    """
    Persist a durable collaboration notification record with deduplication guards.

    Delivery guarantees:
    - In-app channel: persisted immediately with delivery_status='delivered'.
    - Email channel: persisted with delivery_status='pending' for asynchronous dispatch.
    - Idempotency key: deduplicates retried requests to ensure zero duplicate notifications.
    - Optional conn parameter allows participating in caller's active database transaction.
    """
    clean_idem = idempotency_key.strip() if idempotency_key else None
    now_iso = datetime.now(timezone.utc).isoformat()

    # Determine default initial delivery status
    if delivery_status is None:
        delivery_status = "delivered" if delivery_channel == "in_app" else "pending"

    def _execute_insert(c: Any) -> str:
        if clean_idem:
            existing = c.execute(
                "SELECT id FROM collaboration_notifications WHERE idempotency_key = ?",
                (clean_idem,),
            ).fetchone()
            if existing:
                return existing["id"]

        notif_id = f"notif-{uuid.uuid4().hex[:10]}"
        c.execute(
            """
            INSERT INTO collaboration_notifications (
                id, recipient_type, recipient_id, event_type,
                title, message, reference_type, reference_id, is_read,
                delivery_status, delivery_channel, idempotency_key, recipient_email,
                attempt_count, max_attempts, next_retry_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, 0, 3, ?, ?, ?)
            """,
            (
                notif_id,
                recipient_type,
                recipient_id,
                event_type,
                title[:200],
                message[:1000],
                reference_type,
                reference_id,
                delivery_status,
                delivery_channel,
                clean_idem,
                recipient_email.strip().lower() if recipient_email else None,
                now_iso if delivery_status == "pending" else None,
                now_iso,
                now_iso,
            ),
        )
        return notif_id

    if conn is not None:
        return _execute_insert(conn)

    with get_connection() as c:
        notif_id = _execute_insert(c)
        c.commit()
        return notif_id


# ============================================================================
# 3. Delivery Queue Processor with Atomic Worker Leases (Gate C & E)
# ============================================================================

def calculate_backoff_delay_seconds(attempt: int, base_seconds: int = 5, max_seconds: int = 300) -> int:
    """Calculate exponential backoff delay: delay = min(max_seconds, base_seconds * 2^(attempt - 1))."""
    backoff = base_seconds * (2 ** max(0, attempt - 1))
    return min(max_seconds, backoff)


def reclaim_expired_leases() -> int:
    """
    Find notifications stuck in 'processing' where lease_expires_at <= now_iso.
    Reclaims abandoned worker leases:
    - If attempt_count >= max_attempts, transitions to 'failed' (dead-letter).
    - If attempt_count < max_attempts, resets to 'retry_pending', claimed_by=None.
    """
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    reclaimed_count = 0

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        stuck_rows = conn.execute(
            """
            SELECT id, attempt_count, max_attempts
            FROM collaboration_notifications
            WHERE delivery_status = 'processing'
              AND lease_expires_at IS NOT NULL
              AND lease_expires_at <= ?
            """,
            (now_iso,),
        ).fetchall()

        for r in stuck_rows:
            notif_id = r["id"]
            attempts = r["attempt_count"]
            max_att = r["max_attempts"]
            if attempts >= max_att:
                conn.execute(
                    """
                    UPDATE collaboration_notifications
                    SET delivery_status = 'failed',
                        error_class = 'lease_expired_exhausted',
                        error_message = 'Worker lease expired and retry attempts exhausted',
                        claimed_by = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (now_iso, notif_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE collaboration_notifications
                    SET delivery_status = 'retry_pending',
                        error_class = 'lease_expired_reclaimed',
                        error_message = 'Worker lease expired; reclaimed for retry',
                        claimed_by = NULL,
                        next_retry_at = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (now_iso, now_iso, notif_id),
                )
            reclaimed_count += 1

        conn.commit()

    if reclaimed_count > 0:
        logger.warning("Reclaimed %d expired notification worker leases.", reclaimed_count)
    return reclaimed_count


def process_notification_deliveries(
    batch_size: int = 20,
    worker_id: str = "worker-1",
    lease_seconds: int = 60,
    transport: EmailTransport | None = None,
) -> dict[str, int]:
    """
    Process pending and retry_pending email delivery notifications.
    Uses atomic worker leasing to prevent double-processing across concurrent workers.
    Re-evaluates recipient eligibility at execution time.
    """
    # Reclaim any abandoned leases prior to claiming new work
    reclaim_expired_leases()

    if transport is None:
        transport = get_email_transport()

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    lease_expiry = (now + timedelta(seconds=lease_seconds)).isoformat()

    stats = {
        "claimed": 0,
        "delivered": 0,
        "retry_pending": 0,
        "failed": 0,
        "cancelled": 0,
    }

    # Step 1: Claim eligible notifications atomically under IMMEDIATE transaction
    claimed_rows: list[dict[str, Any]] = []
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """
            SELECT id, recipient_type, recipient_id, recipient_email, event_type,
                   title, message, reference_type, reference_id, attempt_count, max_attempts
            FROM collaboration_notifications
            WHERE delivery_channel = 'email'
              AND delivery_status IN ('pending', 'retry_pending')
              AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
              AND (next_retry_at IS NULL OR next_retry_at <= ?)
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (now_iso, now_iso, batch_size),
        ).fetchall()

        for r in rows:
            notif_dict = dict(r)
            new_attempts = notif_dict["attempt_count"] + 1
            updated = conn.execute(
                """
                UPDATE collaboration_notifications
                SET delivery_status = 'processing',
                    claimed_by = ?,
                    claimed_at = ?,
                    lease_expires_at = ?,
                    attempt_count = ?,
                    last_attempt_at = ?,
                    updated_at = ?
                WHERE id = ? AND delivery_status IN ('pending', 'retry_pending')
                """,
                (
                    worker_id,
                    now_iso,
                    lease_expiry,
                    new_attempts,
                    now_iso,
                    now_iso,
                    notif_dict["id"],
                ),
            ).rowcount
            if updated > 0:
                notif_dict["attempt_count"] = new_attempts
                claimed_rows.append(notif_dict)

        conn.commit()

    stats["claimed"] = len(claimed_rows)

    # Step 2: Deliver each claimed notification
    for notif in claimed_rows:
        notif_id = notif["id"]
        recipient_type = notif["recipient_type"]
        recipient_id = notif["recipient_id"]
        target_email = notif.get("recipient_email")

        # Recipient eligibility verification
        is_eligible = True
        cancellation_reason = ""

        with get_connection() as conn:
            # Check portal user account status if recipient is a supplier or customer
            if recipient_type in ("supplier", "customer"):
                user_row = conn.execute(
                    """
                    SELECT id, email, is_active, organization_id
                    FROM portal_users
                    WHERE (organization_id = ? AND account_type = ?)
                       OR (email = ? AND account_type = ?)
                    LIMIT 1
                    """,
                    (recipient_id, recipient_type, target_email or "", recipient_type),
                ).fetchone()

                if not user_row:
                    is_eligible = False
                    cancellation_reason = f"No portal user found for {recipient_type} organization '{recipient_id}'."
                elif user_row["is_active"] != 1:
                    is_eligible = False
                    cancellation_reason = "Recipient account is deactivated."
                else:
                    target_email = target_email or user_row["email"]
                    # Check user notification preferences
                    pref = conn.execute(
                        "SELECT email_notifications_enabled FROM portal_user_notification_preferences WHERE user_id = ?",
                        (user_row["id"],),
                    ).fetchone()
                    if pref and pref["email_notifications_enabled"] == 0:
                        is_eligible = False
                        cancellation_reason = "Recipient has opted out of email notifications in user preferences."

        if not is_eligible or not target_email:
            # Cancel delivery
            with get_connection() as conn:
                conn.execute(
                    """
                    UPDATE collaboration_notifications
                    SET delivery_status = 'cancelled',
                        error_message = ?,
                        error_class = 'permanent',
                        claimed_by = NULL,
                        claimed_at = NULL,
                        lease_expires_at = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (cancellation_reason or "Missing recipient email address", datetime.now(timezone.utc).isoformat(), notif_id),
                )
                conn.commit()
            stats["cancelled"] += 1
            continue

        # Execute dispatch via configured email transport with crash isolation
        stable_message_id = f"<{notif_id}@tradesathi.local>"
        try:
            result = transport.send_email(
                to_email=target_email,
                subject=notif["title"],
                text_body=notif["message"],
                message_id=stable_message_id,
            )
        except Exception as exc:
            logger.exception("Unexpected exception during email dispatch for notification %s", notif_id)
            result = EmailDeliveryResult(
                success=False,
                error_message=f"Transport exception: {type(exc).__name__}: {str(exc)}",
                error_class="transient",
            )

        fin_iso = datetime.now(timezone.utc).isoformat()

        with get_connection() as conn:
            if result.success:
                conn.execute(
                    """
                    UPDATE collaboration_notifications
                    SET delivery_status = 'delivered',
                        provider_message_id = ?,
                        error_message = NULL,
                        error_class = NULL,
                        claimed_by = NULL,
                        claimed_at = NULL,
                        lease_expires_at = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (result.provider_message_id, fin_iso, notif_id),
                )
                stats["delivered"] += 1
            else:
                attempts = notif["attempt_count"]
                max_att = notif["max_attempts"]

                if result.error_class == "transient" and attempts < max_att:
                    # Retry pending with exponential backoff
                    delay_sec = calculate_backoff_delay_seconds(attempts)
                    next_retry = (datetime.now(timezone.utc) + timedelta(seconds=delay_sec)).isoformat()
                    conn.execute(
                        """
                        UPDATE collaboration_notifications
                        SET delivery_status = 'retry_pending',
                            next_retry_at = ?,
                            error_message = ?,
                            error_class = 'transient',
                            claimed_by = NULL,
                            claimed_at = NULL,
                            lease_expires_at = NULL,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (next_retry, result.error_message, fin_iso, notif_id),
                    )
                    stats["retry_pending"] += 1
                else:
                    # Permanent failure or attempts exhausted (dead-letter state)
                    conn.execute(
                        """
                        UPDATE collaboration_notifications
                        SET delivery_status = 'failed',
                            error_message = ?,
                            error_class = ?,
                            claimed_by = NULL,
                            claimed_at = NULL,
                            lease_expires_at = NULL,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (result.error_message, result.error_class or "permanent", fin_iso, notif_id),
                    )
                    stats["failed"] += 1

            conn.commit()

    return stats


# ============================================================================
# 4. Operational Monitoring & Admin Reprocessing (Gate E & F)
# ============================================================================

def get_notification_monitoring_metrics() -> dict[str, Any]:
    """Compile real-time operational delivery metrics for internal staff."""
    with get_connection() as conn:
        status_counts = dict(
            conn.execute(
                "SELECT delivery_status, count(*) FROM collaboration_notifications GROUP BY delivery_status"
            ).fetchall()
        )

        channel_counts = dict(
            conn.execute(
                "SELECT delivery_channel, count(*) FROM collaboration_notifications GROUP BY delivery_channel"
            ).fetchall()
        )

        oldest_pending_row = conn.execute(
            """
            SELECT created_at FROM collaboration_notifications
            WHERE delivery_status IN ('pending', 'retry_pending')
            ORDER BY created_at ASC LIMIT 1
            """
        ).fetchone()

        last_delivered_row = conn.execute(
            """
            SELECT updated_at FROM collaboration_notifications
            WHERE delivery_status = 'delivered'
            ORDER BY updated_at DESC LIMIT 1
            """
        ).fetchone()

        recent_failures_rows = conn.execute(
            """
            SELECT id, recipient_type, recipient_id, recipient_email, event_type,
                   title, delivery_channel, attempt_count, error_message, error_class, updated_at
            FROM collaboration_notifications
            WHERE delivery_status = 'failed'
            ORDER BY updated_at DESC LIMIT 10
            """
        ).fetchall()

    oldest_age_seconds = None
    if oldest_pending_row and oldest_pending_row["created_at"]:
        try:
            created_dt = datetime.fromisoformat(oldest_pending_row["created_at"])
            oldest_age_seconds = max(0, int((datetime.now(timezone.utc) - created_dt).total_seconds()))
        except Exception:
            pass

    transport = get_email_transport()
    provider_name = transport.__class__.__name__.replace("EmailTransport", "").lower() or "unknown"

    return {
        "status_counts": {
            "pending": status_counts.get("pending", 0),
            "processing": status_counts.get("processing", 0),
            "delivered": status_counts.get("delivered", 0),
            "retry_pending": status_counts.get("retry_pending", 0),
            "failed": status_counts.get("failed", 0),
            "cancelled": status_counts.get("cancelled", 0),
        },
        "channel_counts": {
            "in_app": channel_counts.get("in_app", 0),
            "email": channel_counts.get("email", 0),
        },
        "oldest_pending_age_seconds": oldest_age_seconds,
        "last_successful_delivery_at": last_delivered_row["updated_at"] if last_delivered_row else None,
        "provider_mode": provider_name,
        "email_delivery_enabled": os.getenv("EMAIL_DELIVERY_ENABLED", "false").lower() in ("true", "1", "yes"),
        "recent_failures": [dict(r) for r in recent_failures_rows],
    }


def retry_failed_notification(notification_id: str) -> dict[str, Any]:
    """
    Reset an exhausted or failed notification back to 'pending' with 0 attempts,
    allowing authorized staff to trigger reprocessing.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        notif = conn.execute(
            "SELECT id, delivery_status, attempt_count FROM collaboration_notifications WHERE id = ?",
            (notification_id,),
        ).fetchone()

        if not notif:
            return {"success": False, "error": f"Notification '{notification_id}' not found."}

        conn.execute(
            """
            UPDATE collaboration_notifications
            SET delivery_status = 'pending',
                attempt_count = 0,
                next_retry_at = ?,
                claimed_by = NULL,
                claimed_at = NULL,
                lease_expires_at = NULL,
                error_message = NULL,
                error_class = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (now_iso, now_iso, notification_id),
        )
        conn.commit()

    return {"success": True, "notification_id": notification_id, "new_status": "pending"}


# ============================================================================
# 5. User Notification Preferences (Gate D)
# ============================================================================

def get_user_notification_preferences(user_id: str) -> dict[str, Any]:
    """Fetch user-specific notification preferences, defaulting to email enabled."""
    with get_connection() as conn:
        pref = conn.execute(
            "SELECT email_notifications_enabled, updated_at FROM portal_user_notification_preferences WHERE user_id = ?",
            (user_id,),
        ).fetchone()

        if pref:
            return {
                "user_id": user_id,
                "email_notifications_enabled": bool(pref["email_notifications_enabled"]),
                "updated_at": pref["updated_at"],
            }

        return {
            "user_id": user_id,
            "email_notifications_enabled": True,
            "updated_at": None,
        }


def set_user_notification_preferences(user_id: str, email_notifications_enabled: bool) -> dict[str, Any]:
    """Set user-specific notification preferences (tenant isolated to caller user ID)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    val = 1 if email_notifications_enabled else 0

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO portal_user_notification_preferences (user_id, email_notifications_enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                email_notifications_enabled = excluded.email_notifications_enabled,
                updated_at = excluded.updated_at
            """,
            (user_id, val, now_iso, now_iso),
        )
        conn.commit()

    return {
        "user_id": user_id,
        "email_notifications_enabled": email_notifications_enabled,
        "updated_at": now_iso,
    }
