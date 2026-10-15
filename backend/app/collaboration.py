"""TradeSathi AI — Phase 9A: Secure Supplier & Customer Collaboration Service
Provides:
1. Additive external account identity model (portal_users, portal_invitations, portal_user_tokens).
2. Authoritative supplier & customer master data association.
3. Centralized server-side entity-level authorization (Anti-IDOR).
4. Controlled purchase-order acknowledgement workflow for suppliers.
5. Read-only customer portal (sales orders, dispatches, issued invoices, export tracking).
6. Secure authorization-aware document access and sharing policy.
7. Secret-safe audit logging for collaboration events.
"""

import hashlib
import os
import re
import hashlib
import json
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .auth import AuthenticatedUser, get_current_user, hash_password, verify_password
from .db import get_connection, is_test_environment
from .documents import sanitize_filename
from .master_data import record_erp_audit_log, verify_role_permission
from .storage import compute_file_hash, delete_document_file, get_document_file_path, save_document_file
from .rate_limiter import auth_rate_limiter, invitation_rate_limiter


# ==========================================
# Token Hashing & Utilities
# ==========================================

def hash_portal_token(raw_token: str) -> str:
    """Compute deterministic SHA-256 hash of raw bearer token or invitation token."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_portal_token(portal_user_id: str, expires_in_seconds: int = 28800) -> tuple[str, str]:
    """Generate high-entropy 256-bit bearer token for portal user and store its hash."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_portal_token(raw_token)
    token_id = f"ptok-{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(seconds=expires_in_seconds)).isoformat()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO portal_user_tokens (token_id, portal_user_id, token_hash, expires_at, revoked, created_at)
            VALUES (?, ?, ?, ?, 0, ?)
            """,
            (token_id, portal_user_id, token_hash, expires_at, now.isoformat()),
        )
        conn.commit()

    return raw_token, expires_at


def revoke_portal_token_by_raw(raw_token: str) -> bool:
    """Revoke a portal bearer token."""
    token_hash = hash_portal_token(raw_token)
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE portal_user_tokens SET revoked = 1 WHERE token_hash = ?",
            (token_hash,),
        )
        conn.commit()
        return cursor.rowcount > 0


# ==========================================
# External Portal User Context & Dependency
# ==========================================

class AuthenticatedPortalUser(BaseModel):
    id: str
    username: str
    email: str
    account_type: Literal["supplier", "customer"]
    organization_id: str
    organization_name: str
    is_active: bool = True


async def get_current_portal_user(
    authorization: str | None = Header(None, alias="Authorization"),
    x_portal_account_type: str | None = Header(None, alias="X-Portal-Account-Type"),
    x_portal_org_id: str | None = Header(None, alias="X-Portal-Org-Id"),
    x_portal_user_name: str | None = Header(None, alias="X-Portal-User-Name"),
    x_portal_user_email: str | None = Header(None, alias="X-Portal-User-Email"),
) -> AuthenticatedPortalUser:
    """
    Authenticate external supplier/customer portal caller using Bearer token.
    Strictly resolves user identity, account type, and organization from database.
    """
    # 1. Bearer Token Verification
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization[len("Bearer "):].strip()
        if raw_token:
            token_hash = hash_portal_token(raw_token)
            with get_connection() as conn:
                row = conn.execute(
                    """
                    SELECT u.id, u.username, u.email, u.account_type, u.organization_id,
                           u.organization_name, u.is_active, t.expires_at, t.revoked
                    FROM portal_user_tokens t
                    JOIN portal_users u ON t.portal_user_id = u.id
                    WHERE t.token_hash = ?
                    """,
                    (token_hash,),
                ).fetchone()

            if not row:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or unrecognized portal authentication token.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            if row["revoked"] == 1:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Portal authentication token has been revoked.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            now_iso = datetime.now(timezone.utc).isoformat()
            if row["expires_at"] < now_iso:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Portal session has expired. Please log in again.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            if row["is_active"] != 1:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="External account is deactivated. Contact the TradeSathi system administrator.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            return AuthenticatedPortalUser(
                id=row["id"],
                username=row["username"],
                email=row["email"],
                account_type=row["account_type"],
                organization_id=row["organization_id"],
                organization_name=row["organization_name"],
                is_active=True,
            )

    # 2. Test Environment Role Simulator (Test-mode only)
    env = (os.getenv("ENVIRONMENT") or os.getenv("TRADESATHI_ENV") or "").lower()
    if env not in ("production", "staging") and is_test_environment() and os.getenv("TRADESATHI_TEST_ROLE_SIMULATOR") == "1":
        if x_portal_account_type and x_portal_org_id:
            account_type = x_portal_account_type.strip().lower()
            if account_type in ("supplier", "customer"):
                user_name = (x_portal_user_name or f"test_{account_type}").strip()
                user_email = (x_portal_user_email or f"{user_name}@portal.test").strip()
                return AuthenticatedPortalUser(
                    id=f"pusr-test-{user_name.lower().replace(' ', '-')}",
                    username=user_name,
                    email=user_email,
                    account_type=account_type,  # type: ignore[arg-type]
                    organization_id=x_portal_org_id.strip(),
                    organization_name=f"Simulated {account_type.capitalize()} Org",
                    is_active=True,
                )

    # 3. Fail Closed
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Portal authentication required. Please provide a valid 'Authorization: Bearer <token>' header.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_supplier_user(
    portal_user: AuthenticatedPortalUser = Depends(get_current_portal_user),
) -> AuthenticatedPortalUser:
    """Ensure authenticated portal caller is an authorized supplier portal user."""
    if portal_user.account_type != "supplier":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Supplier portal access only.",
        )
    return portal_user


async def get_current_customer_user(
    portal_user: AuthenticatedPortalUser = Depends(get_current_portal_user),
) -> AuthenticatedPortalUser:
    """Ensure authenticated portal caller is an authorized customer portal user."""
    if portal_user.account_type != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Customer portal access only.",
        )
    return portal_user


# ==========================================
# Pydantic Schemas for Collaboration API
# ==========================================

class InvitationCreateRequest(BaseModel):
    account_type: Literal["supplier", "customer"]
    organization_id: str = Field(..., min_length=1)
    email: str = Field(..., min_length=3)
    notes: str | None = None
    expires_in_days: int = Field(default=7, ge=1, le=30)


class InvitationResponse(BaseModel):
    id: str
    account_type: str
    organization_id: str
    organization_name: str
    email: str
    invited_by: str
    status: str
    expires_at: str
    created_at: str
    invitation_token: str | None = None  # Returned only upon creation


class InvitationVerifyRequest(BaseModel):
    invitation_token: str = Field(..., min_length=16)


class InvitationVerifyResponse(BaseModel):
    valid: bool
    account_type: str
    organization_id: str
    organization_name: str
    email: str
    expires_at: str


class InvitationAcceptRequest(BaseModel):
    invitation_token: str = Field(..., min_length=16)
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)


class PortalLoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class PortalLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: str
    user: dict[str, Any]


class POAcknowledgeRequest(BaseModel):
    action: Literal["accept", "reject", "request_clarification"]
    supplier_comments: str | None = Field(default=None, max_length=1000)
    proposed_delivery_date: str | None = None
    idempotency_key: str | None = None


class DocumentShareRequest(BaseModel):
    shared_with_customer: bool | None = None
    shared_with_supplier: bool | None = None
    sharing_notes: str | None = None
    notes: str | None = None


# --- Phase 9B Advanced Supplier Collaboration Schemas ---

class DeliveryCommitmentLineItem(BaseModel):
    po_item_id: str = Field(..., min_length=1)
    committed_qty: float = Field(..., gt=0)


class DeliveryCommitmentCreateRequest(BaseModel):
    proposed_delivery_date: str = Field(..., min_length=1)
    supplier_dispatch_ref: str | None = Field(default=None, max_length=100)
    carrier_name: str | None = Field(default=None, max_length=100)
    tracking_number: str | None = Field(default=None, max_length=100)
    supplier_comments: str | None = Field(default=None, max_length=1000)
    lines: list[DeliveryCommitmentLineItem] = Field(default_factory=list)
    idempotency_key: str | None = None


class DeliveryCommitmentReviewRequest(BaseModel):
    decision: Literal["accept", "reject"]
    internal_review_notes: str | None = Field(default=None, max_length=1000)


class ASNItemCreate(BaseModel):
    po_item_id: str = Field(..., min_length=1)
    shipped_qty: float = Field(..., gt=0)
    package_label: str | None = Field(default=None, max_length=100)


class ASNCreateRequest(BaseModel):
    po_id: str = Field(..., min_length=1)
    dispatch_reference: str = Field(..., min_length=1, max_length=100)
    package_count: int = Field(default=1, ge=0)
    carrier_name: str | None = Field(default=None, max_length=100)
    tracking_number: str | None = Field(default=None, max_length=100)
    dispatch_date: str = Field(..., min_length=1)
    expected_arrival_date: str = Field(..., min_length=1)
    notes: str | None = Field(default=None, max_length=1000)
    items: list[ASNItemCreate] = Field(..., min_length=1)
    idempotency_key: str | None = None


class SupplierDocumentReviewRequest(BaseModel):
    action: Literal["accept", "reject", "request_replacement"]
    review_notes: str | None = Field(default=None, max_length=1000)


class DiscrepancyCreateRequest(BaseModel):
    po_id: str = Field(..., min_length=1)
    asn_id: str | None = None
    commitment_id: str | None = None
    category: Literal[
        "quantity_mismatch",
        "short_shipment",
        "damaged_goods",
        "delayed_shipment",
        "incorrect_product",
        "missing_documentation",
        "other",
    ]
    title: str = Field(..., min_length=3, max_length=200)
    description: str = Field(..., min_length=10, max_length=2000)
    document_ids: list[str] = Field(default_factory=list)
    idempotency_key: str | None = None


class DiscrepancyMessageCreateRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    document_ids: list[str] = Field(default_factory=list)


class DiscrepancyStaffReviewRequest(BaseModel):
    action: Literal["under_review", "request_supplier_info", "resolve", "reject", "close"]
    internal_notes: str | None = Field(default=None, max_length=2000)
    shared_resolution_notes: str | None = Field(default=None, max_length=2000)
    message: str | None = Field(default=None, max_length=2000)


# Phase 9C: Customer Collaboration & Order Communication Schemas

class CustomerThreadCreateRequest(BaseModel):
    subject: str = Field(..., min_length=3, max_length=200)
    message: str | None = Field(default=None, max_length=2000)
    initial_message: str | None = Field(default=None, max_length=2000)
    idempotency_key: str | None = None


class CustomerMessageCreateRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    idempotency_key: str | None = None


class StaffThreadMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    is_internal_note: bool = False


class StaffThreadStatusRequest(BaseModel):
    status: Literal["open", "under_review", "resolved", "closed"]
    internal_notes: str | None = Field(default=None, max_length=2000)


class CustomerDocumentRequestCreate(BaseModel):
    sales_order_id: str | None = None
    shipment_id: str | None = None
    category: str | None = None
    document_category: str | None = None
    message: str | None = Field(default=None, max_length=1000)
    idempotency_key: str | None = None


class StaffDocumentRequestReview(BaseModel):
    action: str | None = None
    status: str | None = None
    fulfilled_document_id: str | None = None
    decision_notes: str | None = Field(default=None, max_length=2000)
    review_notes: str | None = Field(default=None, max_length=2000)


class DocumentShareUpdateRequest(BaseModel):
    shared_with_customer: bool | None = None
    shared_with_supplier: bool | None = None
    sharing_notes: str | None = Field(default=None, max_length=1000)


# Document Upload Validation Helper
ALLOWED_SUPPLIER_EXTENSIONS = {".pdf", ".txt", ".docx", ".png", ".jpg", ".jpeg"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


def validate_supplier_file(filename: str, content: bytes) -> str:
    """Validate file extension, size, and magic bytes. Returns detected extension."""
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="File exceeds maximum permitted size of 10 MB.")
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    clean_name = sanitize_filename(filename)
    lower_ext = os.path.splitext(clean_name)[1].lower()

    if lower_ext not in ALLOWED_SUPPLIER_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{lower_ext}'. Allowed types: PDF, TXT, DOCX, PNG, JPG, JPEG.",
        )

    # Magic byte inspection
    if lower_ext == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise HTTPException(status_code=400, detail="Invalid PDF file format (header signature mismatch).")
    elif lower_ext == ".png":
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise HTTPException(status_code=400, detail="Invalid PNG file format (header signature mismatch).")
    elif lower_ext in (".jpg", ".jpeg"):
        if not (content.startswith(b"\xff\xd8\xff") or content.startswith(b"\xff\xd8")):
            raise HTTPException(status_code=400, detail="Invalid JPEG/JPG file format (header signature mismatch).")
    elif lower_ext == ".docx":
        if not content.startswith(b"PK\x03\x04"):
            raise HTTPException(status_code=400, detail="Invalid DOCX file format (header signature mismatch).")
    elif lower_ext == ".txt":
        try:
            content.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                content.decode("latin-1")
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid text file encoding.")

    return lower_ext


def sanitize_plain_text(val: str) -> str:
    """Strip dangerous HTML tags, script blocks, or control characters from user text inputs."""
    if not val:
        return ""
    clean = re.sub(r"(?is)<script[^>]*>.*?</script>", "", val)
    clean = re.sub(r"(?is)<style[^>]*>.*?</style>", "", clean)
    clean = re.sub(r"<[^>]*>", "", clean)
    return clean.strip()


from .notifications import (
    record_collaboration_notification,
    process_notification_deliveries,
    get_notification_monitoring_metrics,
    retry_failed_notification,
    get_user_notification_preferences,
    set_user_notification_preferences,
    get_email_transport,
    set_email_transport,
    EmailDeliveryResult,
    EmailTransport,
    MockEmailTransport,
    DisabledEmailTransport,
    SmtpEmailTransport,
)


class UserNotificationPreferencesRequest(BaseModel):
    email_notifications_enabled: bool


class ProcessDeliveriesRequest(BaseModel):
    batch_size: int = Field(default=20, ge=1, le=100)
    worker_id: str = "worker-manual"


# ==========================================
# Collaboration API Router
# ==========================================

router = APIRouter(prefix="/api/portal", tags=["Collaboration Portal"])


# ------------------------------------------
# Public / Partner Authentication & Registration
# ------------------------------------------

@router.post("/auth/login", response_model=PortalLoginResponse, dependencies=[Depends(auth_rate_limiter)])
def portal_login_endpoint(req: PortalLoginRequest):
    """Authenticate external supplier or customer portal user and issue bearer token."""
    username = req.username.strip()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, username, email, password_hash, account_type, organization_id, organization_name, is_active
            FROM portal_users
            WHERE LOWER(username) = LOWER(?) OR LOWER(email) = LOWER(?)
            """,
            (username, username),
        ).fetchone()

    # Timing-safe verification & generic response
    if not row or not verify_password(req.password, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if row["is_active"] != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="External account is deactivated. Contact your account manager.",
        )

    raw_token, expires_at = create_portal_token(row["id"])
    return {
        "access_token": raw_token,
        "token_type": "bearer",
        "expires_at": expires_at,
        "user": {
            "id": row["id"],
            "username": row["username"],
            "email": row["email"],
            "account_type": row["account_type"],
            "organization_id": row["organization_id"],
            "organization_name": row["organization_name"],
        },
    }


@router.post("/auth/logout")
def portal_logout_endpoint(
    authorization: str | None = Header(None, alias="Authorization"),
    current_user: AuthenticatedPortalUser = Depends(get_current_portal_user),
):
    """Revoke active bearer token for portal user."""
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization[len("Bearer "):].strip()
        revoke_portal_token_by_raw(raw_token)
    return {"detail": "Successfully logged out from portal."}


@router.get("/auth/me")
def portal_get_me_endpoint(current_user: AuthenticatedPortalUser = Depends(get_current_portal_user)):
    """Return currently authenticated portal user profile and authoritative organization."""
    return current_user.model_dump()


@router.post("/invitations/verify", response_model=InvitationVerifyResponse)
def verify_invitation_endpoint(req: InvitationVerifyRequest):
    """Verify an invitation token before registration, returning non-sensitive organization preview."""
    token_hash = hash_portal_token(req.invitation_token.strip())
    now_iso = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, account_type, organization_id, organization_name, email, status, expires_at
            FROM portal_invitations
            WHERE invitation_token_hash = ?
            """,
            (token_hash,),
        ).fetchone()

    if not row or row["status"] != "pending" or row["expires_at"] < now_iso:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid invitation token or invitation has expired.",
        )

    return {
        "valid": True,
        "account_type": row["account_type"],
        "organization_id": row["organization_id"],
        "organization_name": row["organization_name"],
        "email": row["email"],
        "expires_at": row["expires_at"],
    }


@router.post("/invitations/accept", response_model=PortalLoginResponse, dependencies=[Depends(invitation_rate_limiter)])
def accept_invitation_endpoint(req: InvitationAcceptRequest):
    """
    Accept single-use invitation token, create external user record, and return session token.
    Enforces atomic status update so invitation cannot be replayed or duplicated.
    """
    raw_token = req.invitation_token.strip()
    token_hash = hash_portal_token(raw_token)
    username = req.username.strip()
    now_iso = datetime.now(timezone.utc).isoformat()

    if len(username) < 3 or not re.match(r"^[a-zA-Z0-9_\-\.]+$", username):
        raise HTTPException(
            status_code=400,
            detail="Username must be at least 3 characters and contain only letters, numbers, hyphens, underscores, or dots.",
        )

    pw_hash = hash_password(req.password)
    user_id = f"pusr-{uuid.uuid4().hex[:10]}"

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        inv = conn.execute(
            """
            SELECT id, account_type, organization_id, organization_name, email, status, expires_at
            FROM portal_invitations
            WHERE invitation_token_hash = ?
            """,
            (token_hash,),
        ).fetchone()

        if not inv or inv["status"] != "pending" or inv["expires_at"] < now_iso:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid invitation token or invitation has expired.",
            )

        # Check username uniqueness in portal_users
        chk = conn.execute(
            "SELECT id FROM portal_users WHERE LOWER(username) = LOWER(?) OR LOWER(email) = LOWER(?)",
            (username, inv["email"]),
        ).fetchone()
        if chk:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"An account with username '{username}' or email '{inv['email']}' already exists.",
            )

        # Atomic mark as accepted
        conn.execute(
            """
            UPDATE portal_invitations
            SET status = 'accepted', accepted_at = ?, updated_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (now_iso, now_iso, inv["id"]),
        )

        # Insert external portal user bound to invitation's authoritative organization
        conn.execute(
            """
            INSERT INTO portal_users (
                id, username, email, password_hash, account_type,
                organization_id, organization_name, invitation_id, is_active,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                user_id,
                username,
                inv["email"],
                pw_hash,
                inv["account_type"],
                inv["organization_id"],
                inv["organization_name"],
                inv["id"],
                now_iso,
                now_iso,
            ),
        )
        conn.commit()

    record_erp_audit_log(
        "portal_user",
        user_id,
        "activate_portal_account",
        {
            "username": username,
            "account_type": inv["account_type"],
            "organization_id": inv["organization_id"],
        },
        performed_by=username,
    )

    raw_bearer, expires_at = create_portal_token(user_id)
    return {
        "access_token": raw_bearer,
        "token_type": "bearer",
        "expires_at": expires_at,
        "user": {
            "id": user_id,
            "username": username,
            "email": inv["email"],
            "account_type": inv["account_type"],
            "organization_id": inv["organization_id"],
            "organization_name": inv["organization_name"],
        },
    }


# ------------------------------------------
# Internal Staff Management of Invitations & External Users
# ------------------------------------------

@router.post("/admin/invitations", response_model=InvitationResponse, status_code=201)
def create_invitation_endpoint(
    req: InvitationCreateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Generate an expiring single-use invitation for a supplier or customer.
    Authorized internal staff: admin, procurement (suppliers), sales (customers).
    """
    if current_user.role != "admin":
        if req.account_type == "supplier" and current_user.role != "procurement":
            raise HTTPException(status_code=403, detail="Procurement or Admin role required to invite suppliers.")
        if req.account_type == "customer" and current_user.role != "sales":
            raise HTTPException(status_code=403, detail="Sales or Admin role required to invite customers.")

    org_id = req.organization_id.strip()
    email = req.email.strip().lower()
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(days=req.expires_in_days)).isoformat()
    now_iso = now.isoformat()

    with get_connection() as conn:
        if req.account_type == "supplier":
            org_row = conn.execute("SELECT id, name, status FROM suppliers WHERE id = ?", (org_id,)).fetchone()
            if not org_row:
                raise HTTPException(status_code=404, detail=f"Supplier '{org_id}' not found.")
            org_name = org_row["name"]
        else:
            org_row = conn.execute("SELECT id, name, status FROM customers WHERE id = ?", (org_id,)).fetchone()
            if not org_row:
                raise HTTPException(status_code=404, detail=f"Customer '{org_id}' not found.")
            org_name = org_row["name"]

        if org_row["status"] == "inactive":
            raise HTTPException(status_code=400, detail=f"Cannot invite inactive organization '{org_name}'.")

        # Generate single-use invitation secret
        raw_token = secrets.token_urlsafe(32)
        token_hash = hash_portal_token(raw_token)
        inv_id = f"inv-{uuid.uuid4().hex[:10]}"

        conn.execute(
            """
            INSERT INTO portal_invitations (
                id, invitation_token_hash, account_type, organization_id,
                organization_name, email, invited_by, status, expires_at,
                notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            """,
            (
                inv_id,
                token_hash,
                req.account_type,
                org_id,
                org_name,
                email,
                current_user.username,
                expires_at,
                req.notes,
                now_iso,
                now_iso,
            ),
        )
        conn.commit()

    record_erp_audit_log(
        "portal_invitation",
        inv_id,
        "create_invitation",
        {"account_type": req.account_type, "organization_id": org_id, "email": email},
        performed_by=current_user.username,
    )

    return {
        "id": inv_id,
        "account_type": req.account_type,
        "organization_id": org_id,
        "organization_name": org_name,
        "email": email,
        "invited_by": current_user.username,
        "status": "pending",
        "expires_at": expires_at,
        "created_at": now_iso,
        "invitation_token": raw_token,
    }


@router.get("/admin/invitations")
def list_invitations_endpoint(
    account_type: str | None = Query(None, description="Filter by account type (supplier, customer)"),
    organization_id: str | None = Query(None, description="Filter by organization ID"),
    status_filter: str | None = Query(None, alias="status", description="Filter by status (pending, accepted, expired, revoked)"),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """List issued invitations with status and organization filtering (internal staff)."""
    clauses = []
    params: list[Any] = []
    if account_type:
        clauses.append("account_type = ?")
        params.append(account_type.strip().lower())
    if organization_id:
        clauses.append("organization_id = ?")
        params.append(organization_id.strip())
    if status_filter:
        clauses.append("status = ?")
        params.append(status_filter.strip().lower())

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, account_type, organization_id, organization_name, email,
                   invited_by, status, expires_at, accepted_at, revoked_at, notes, created_at, updated_at
            FROM portal_invitations
            {where}
            ORDER BY created_at DESC
            """,
            params,
        ).fetchall()

    return {"total": len(rows), "items": [dict(r) for r in rows]}


@router.post("/admin/invitations/{invitation_id}/revoke")
def revoke_invitation_endpoint(
    invitation_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Revoke an active invitation (internal staff)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        inv = conn.execute("SELECT id, status FROM portal_invitations WHERE id = ?", (invitation_id,)).fetchone()
        if not inv:
            raise HTTPException(status_code=404, detail=f"Invitation '{invitation_id}' not found.")
        if inv["status"] != "pending":
            raise HTTPException(status_code=400, detail=f"Cannot revoke invitation in '{inv['status']}' state.")

        conn.execute(
            "UPDATE portal_invitations SET status = 'revoked', revoked_at = ?, updated_at = ? WHERE id = ?",
            (now_iso, now_iso, invitation_id),
        )
        conn.commit()

    record_erp_audit_log(
        "portal_invitation",
        invitation_id,
        "revoke_invitation",
        {},
        performed_by=current_user.username,
    )
    return {"detail": f"Invitation '{invitation_id}' has been revoked."}


@router.get("/admin/users")
def list_portal_users_endpoint(
    account_type: str | None = Query(None),
    organization_id: str | None = Query(None),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """List registered external portal accounts (internal staff)."""
    clauses = []
    params: list[Any] = []
    if account_type:
        clauses.append("account_type = ?")
        params.append(account_type.strip().lower())
    if organization_id:
        clauses.append("organization_id = ?")
        params.append(organization_id.strip())

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, username, email, account_type, organization_id, organization_name,
                   is_active, invitation_id, created_at, updated_at
            FROM portal_users
            {where}
            ORDER BY created_at DESC
            """,
            params,
        ).fetchall()

    return {"total": len(rows), "items": [dict(r) for r in rows]}


@router.post("/admin/users/{user_id}/deactivate")
def deactivate_portal_user_endpoint(
    user_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Deactivate an external portal account and immediately revoke all active sessions."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        user = conn.execute("SELECT id, username, organization_id FROM portal_users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail=f"Portal user '{user_id}' not found.")

        conn.execute(
            "UPDATE portal_users SET is_active = 0, updated_at = ? WHERE id = ?",
            (now_iso, user_id),
        )
        # Immediately revoke all active tokens
        conn.execute("UPDATE portal_user_tokens SET revoked = 1 WHERE portal_user_id = ?", (user_id,))
        conn.commit()

    record_erp_audit_log(
        "portal_user",
        user_id,
        "deactivate_portal_user",
        {"username": user["username"], "organization_id": user["organization_id"]},
        performed_by=current_user.username,
    )
    return {"detail": f"Portal user '{user['username']}' deactivated and active tokens revoked."}


@router.post("/admin/documents/{document_id}/share")
def share_document_endpoint(
    document_id: str,
    payload: DocumentShareRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Explicitly approve or revoke sharing of an existing document with external customers/suppliers."""
    verify_staff_collaboration_access(current_user)
    with get_connection() as conn:
        doc = conn.execute("SELECT id, original_filename FROM documents WHERE id = ?", (document_id,)).fetchone()
        if not doc:
            raise HTTPException(status_code=404, detail=f"Document '{document_id}' not found.")

        now_iso = datetime.now(timezone.utc).isoformat()
        set_clauses = ["updated_at = ?"]
        params: list[Any] = [now_iso]

        if payload.shared_with_customer is not None:
            set_clauses.append("shared_with_customer = ?")
            params.append(1 if payload.shared_with_customer else 0)
        if payload.shared_with_supplier is not None:
            set_clauses.append("shared_with_supplier = ?")
            params.append(1 if payload.shared_with_supplier else 0)
        effective_notes = payload.sharing_notes or payload.notes
        if effective_notes is not None:
            set_clauses.append("sharing_notes = ?")
            params.append(effective_notes.strip())

        set_clauses.append("shared_at = ?")
        params.append(now_iso)
        set_clauses.append("shared_by = ?")
        params.append(current_user.username)
        params.append(document_id)

        conn.execute(f"UPDATE documents SET {', '.join(set_clauses)} WHERE id = ?", params)
        conn.commit()

    record_erp_audit_log(
        "document",
        document_id,
        "update_document_sharing_policy",
        payload.model_dump(exclude_unset=True),
        performed_by=current_user.username,
    )
    return {
        "detail": f"Document '{doc['original_filename']}' sharing policy updated.",
        "document_id": document_id,
        "shared_with_customer": 1 if payload.shared_with_customer else (0 if payload.shared_with_customer is not None else None),
        "shared_with_supplier": 1 if payload.shared_with_supplier else (0 if payload.shared_with_supplier is not None else None),
    }


# ------------------------------------------
# Staff Review Console (Phase 9B Admin Endpoints)
# ------------------------------------------

def verify_staff_collaboration_access(current_user: AuthenticatedUser) -> None:
    if current_user.role not in ("admin", "procurement", "warehouse", "manager", "sales"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: role '{current_user.role}' is not authorized for staff collaboration management.",
        )


@router.get("/admin/commitments")
def list_admin_commitments_endpoint(
    status_filter: str | None = Query(None, alias="status"),
    supplier_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """List supplier delivery commitments across suppliers for internal staff."""
    verify_staff_collaboration_access(current_user)
    clauses: list[str] = []
    params: list[Any] = []
    if status_filter:
        clauses.append("c.status = ?")
        params.append(status_filter.strip().lower())
    if supplier_id:
        clauses.append("c.supplier_id = ?")
        params.append(supplier_id.strip())

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with get_connection() as conn:
        total = conn.execute(f"SELECT count(*) FROM supplier_delivery_commitments c {where}", params).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT c.id, c.po_id, c.supplier_id, s.name as supplier_name, po.po_number,
                   c.revision_number, c.proposed_delivery_date, c.supplier_dispatch_ref,
                   c.carrier_name, c.tracking_number, c.supplier_comments, c.status,
                   c.internal_review_notes, c.reviewed_by, c.reviewed_at, c.created_at
            FROM supplier_delivery_commitments c
            JOIN suppliers s ON c.supplier_id = s.id
            JOIN purchase_orders po ON c.po_id = po.id
            {where}
            ORDER BY c.created_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()

    return {"total": total, "items": [dict(r) for r in rows]}


@router.post("/admin/commitments/{commitment_id}/review")
def review_commitment_endpoint(
    commitment_id: str,
    req: DeliveryCommitmentReviewRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Review and accept/reject a supplier delivery commitment."""
    verify_staff_collaboration_access(current_user)
    now_iso = datetime.now(timezone.utc).isoformat()
    new_status = "accepted" if req.decision == "accept" else "rejected"

    with get_connection() as conn:
        c = conn.execute("SELECT * FROM supplier_delivery_commitments WHERE id = ?", (commitment_id,)).fetchone()
        if not c:
            raise HTTPException(status_code=404, detail=f"Commitment '{commitment_id}' not found.")
        if c["status"] not in ("proposed", "under_review"):
            raise HTTPException(status_code=400, detail=f"Commitment cannot be reviewed in '{c['status']}' state.")

        conn.execute(
            """
            UPDATE supplier_delivery_commitments
            SET status = ?, internal_review_notes = ?, reviewed_by = ?, reviewed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_status, req.internal_review_notes, current_user.username, now_iso, now_iso, commitment_id),
        )
        conn.commit()

    record_erp_audit_log(
        "supplier_delivery_commitment",
        commitment_id,
        "review_supplier_commitment",
        {"decision": req.decision, "po_id": c["po_id"], "supplier_id": c["supplier_id"]},
        performed_by=current_user.username,
    )
    return {"status": "success", "commitment_id": commitment_id, "new_status": new_status}


@router.get("/admin/asns")
def list_admin_asns_endpoint(
    status_filter: str | None = Query(None, alias="status"),
    supplier_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """List supplier ASNs across all suppliers for internal procurement & warehouse staff."""
    verify_staff_collaboration_access(current_user)
    clauses: list[str] = []
    params: list[Any] = []
    if status_filter:
        clauses.append("a.status = ?")
        params.append(status_filter.strip().lower())
    if supplier_id:
        clauses.append("a.supplier_id = ?")
        params.append(supplier_id.strip())

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with get_connection() as conn:
        total = conn.execute(f"SELECT count(*) FROM supplier_asns a {where}", params).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT a.id, a.asn_number, a.po_id, a.supplier_id, s.name as supplier_name, po.po_number,
                   a.dispatch_reference, a.package_count, a.carrier_name, a.tracking_number,
                   a.dispatch_date, a.expected_arrival_date, a.status, a.notes, a.created_at,
                   (SELECT count(*) FROM supplier_asn_items WHERE asn_id = a.id) as item_count
            FROM supplier_asns a
            JOIN suppliers s ON a.supplier_id = s.id
            JOIN purchase_orders po ON a.po_id = po.id
            {where}
            ORDER BY a.created_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()

    return {"total": total, "items": [dict(r) for r in rows]}


@router.get("/admin/asns/{asn_id}")
def get_admin_asn_detail_endpoint(
    asn_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Retrieve full ASN details with line items for internal staff."""
    verify_staff_collaboration_access(current_user)
    with get_connection() as conn:
        asn = conn.execute(
            """
            SELECT a.*, s.name as supplier_name, po.po_number
            FROM supplier_asns a
            JOIN suppliers s ON a.supplier_id = s.id
            JOIN purchase_orders po ON a.po_id = po.id
            WHERE a.id = ?
            """,
            (asn_id,),
        ).fetchone()
        if not asn:
            raise HTTPException(status_code=404, detail=f"ASN '{asn_id}' not found.")

        items = conn.execute("SELECT * FROM supplier_asn_items WHERE asn_id = ?", (asn_id,)).fetchall()
        docs = conn.execute("SELECT * FROM documents WHERE asn_id = ?", (asn_id,)).fetchall()

    return {"asn": dict(asn), "items": [dict(it) for it in items], "documents": [dict(d) for d in docs]}


@router.post("/admin/asns/{asn_id}/acknowledge")
def acknowledge_asn_endpoint(
    asn_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Acknowledge receipt of advance shipment notice by internal staff."""
    verify_staff_collaboration_access(current_user)
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        asn = conn.execute("SELECT id, status, po_id, supplier_id FROM supplier_asns WHERE id = ?", (asn_id,)).fetchone()
        if not asn:
            raise HTTPException(status_code=404, detail=f"ASN '{asn_id}' not found.")

        conn.execute(
            "UPDATE supplier_asns SET status = 'acknowledged', updated_at = ? WHERE id = ?",
            (now_iso, asn_id),
        )
        conn.commit()

    record_erp_audit_log(
        "supplier_asn",
        asn_id,
        "acknowledge_supplier_asn",
        {"po_id": asn["po_id"], "supplier_id": asn["supplier_id"]},
        performed_by=current_user.username,
    )
    return {"status": "success", "asn_id": asn_id, "new_status": "acknowledged"}


@router.get("/admin/supplier-documents")
def list_admin_supplier_documents_endpoint(
    review_status: str | None = Query(None),
    supplier_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """List documents uploaded by suppliers for internal review."""
    verify_staff_collaboration_access(current_user)
    clauses = ["d.supplier_id IS NOT NULL"]
    params: list[Any] = []
    if review_status:
        clauses.append("d.review_status = ?")
        params.append(review_status.strip().lower())
    if supplier_id:
        clauses.append("d.supplier_id = ?")
        params.append(supplier_id.strip())

    where = f"WHERE {' AND '.join(clauses)}"

    with get_connection() as conn:
        total = conn.execute(f"SELECT count(*) FROM documents d {where}", params).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT d.id, d.original_filename, d.clean_filename, d.document_type,
                   d.file_size, d.file_hash, d.review_status, d.review_notes,
                   d.last_reviewed_by, d.last_reviewed_at, d.created_at,
                   d.supplier_id, s.name as supplier_name, d.po_id, po.po_number,
                   d.asn_id, a.asn_number
            FROM documents d
            LEFT JOIN suppliers s ON d.supplier_id = s.id
            LEFT JOIN purchase_orders po ON d.po_id = po.id
            LEFT JOIN supplier_asns a ON d.asn_id = a.id
            {where}
            ORDER BY d.created_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()

    return {"total": total, "items": [dict(r) for r in rows]}


@router.post("/admin/supplier-documents/{document_id}/review")
def review_supplier_document_endpoint(
    document_id: str,
    req: SupplierDocumentReviewRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Accept, reject, or request replacement for a supplier-uploaded document."""
    verify_staff_collaboration_access(current_user)
    now_iso = datetime.now(timezone.utc).isoformat()
    new_status = req.action

    with get_connection() as conn:
        doc = conn.execute("SELECT id, supplier_id, original_filename FROM documents WHERE id = ?", (document_id,)).fetchone()
        if not doc:
            raise HTTPException(status_code=404, detail=f"Document '{document_id}' not found.")

        conn.execute(
            """
            UPDATE documents
            SET review_status = ?, review_notes = ?, last_reviewed_by = ?, last_reviewed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_status, req.review_notes, current_user.username, now_iso, now_iso, document_id),
        )
        conn.commit()

    record_erp_audit_log(
        "document",
        document_id,
        "review_supplier_document",
        {"action": req.action, "supplier_id": doc["supplier_id"]},
        performed_by=current_user.username,
    )
    return {"status": "success", "document_id": document_id, "review_status": new_status}


@router.get("/admin/discrepancies")
def list_admin_discrepancies_endpoint(
    status_filter: str | None = Query(None, alias="status"),
    supplier_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """List all supplier discrepancies including internal notes for internal staff."""
    verify_staff_collaboration_access(current_user)
    clauses: list[str] = []
    params: list[Any] = []
    if status_filter:
        clauses.append("d.status = ?")
        params.append(status_filter.strip().lower())
    if supplier_id:
        clauses.append("d.supplier_id = ?")
        params.append(supplier_id.strip())

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with get_connection() as conn:
        total = conn.execute(f"SELECT count(*) FROM supplier_discrepancies d {where}", params).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT d.id, d.discrepancy_number, d.supplier_id, s.name as supplier_name,
                   d.po_id, po.po_number, d.asn_id, a.asn_number, d.category, d.title,
                   d.description, d.status, d.internal_notes, d.shared_resolution_notes,
                   d.resolved_by, d.resolved_at, d.created_at, d.updated_at
            FROM supplier_discrepancies d
            JOIN suppliers s ON d.supplier_id = s.id
            JOIN purchase_orders po ON d.po_id = po.id
            LEFT JOIN supplier_asns a ON d.asn_id = a.id
            {where}
            ORDER BY d.created_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()

    return {"total": total, "items": [dict(r) for r in rows]}


@router.get("/admin/discrepancies/{discrepancy_id}")
def get_admin_discrepancy_detail_endpoint(
    discrepancy_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Retrieve full discrepancy detail including internal notes and complete message history."""
    verify_staff_collaboration_access(current_user)
    with get_connection() as conn:
        disc = conn.execute(
            """
            SELECT d.*, s.name as supplier_name, po.po_number, a.asn_number
            FROM supplier_discrepancies d
            JOIN suppliers s ON d.supplier_id = s.id
            JOIN purchase_orders po ON d.po_id = po.id
            LEFT JOIN supplier_asns a ON d.asn_id = a.id
            WHERE d.id = ?
            """,
            (discrepancy_id,),
        ).fetchone()
        if not disc:
            raise HTTPException(status_code=404, detail=f"Discrepancy '{discrepancy_id}' not found.")

        messages = conn.execute(
            """
            SELECT id, sender_type, sender_id, sender_name, message, attachments_json, created_at
            FROM supplier_discrepancy_messages
            WHERE discrepancy_id = ?
            ORDER BY created_at ASC
            """,
            (discrepancy_id,),
        ).fetchall()

    return {"discrepancy": dict(disc), "messages": [dict(m) for m in messages]}


@router.post("/admin/discrepancies/{discrepancy_id}/review")
def review_admin_discrepancy_endpoint(
    discrepancy_id: str,
    req: DiscrepancyStaffReviewRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Review, request supplier information, or resolve/reject a supplier discrepancy."""
    verify_staff_collaboration_access(current_user)
    now_iso = datetime.now(timezone.utc).isoformat()

    status_map = {
        "under_review": "under_review",
        "request_supplier_info": "awaiting_supplier",
        "resolve": "resolved",
        "reject": "rejected",
        "close": "closed",
    }
    new_status = status_map[req.action]

    with get_connection() as conn:
        disc = conn.execute("SELECT * FROM supplier_discrepancies WHERE id = ?", (discrepancy_id,)).fetchone()
        if not disc:
            raise HTTPException(status_code=404, detail=f"Discrepancy '{discrepancy_id}' not found.")

        resolved_by = current_user.username if new_status in ("resolved", "rejected") else disc["resolved_by"]
        resolved_at = now_iso if new_status in ("resolved", "rejected") else disc["resolved_at"]

        conn.execute(
            """
            UPDATE supplier_discrepancies
            SET status = ?, internal_notes = COALESCE(?, internal_notes),
                shared_resolution_notes = COALESCE(?, shared_resolution_notes),
                resolved_by = ?, resolved_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_status, req.internal_notes, req.shared_resolution_notes, resolved_by, resolved_at, now_iso, discrepancy_id),
        )

        if req.message and req.message.strip():
            msg_id = f"dmsg-{uuid.uuid4().hex[:10]}"
            conn.execute(
                """
                INSERT INTO supplier_discrepancy_messages (
                    id, discrepancy_id, sender_type, sender_id, sender_name, message, attachments_json, created_at
                ) VALUES (?, ?, 'staff', ?, ?, ?, '[]', ?)
                """,
                (msg_id, discrepancy_id, current_user.id, current_user.username, req.message.strip(), now_iso),
            )

        conn.commit()

    record_erp_audit_log(
        "supplier_discrepancy",
        discrepancy_id,
        "review_supplier_discrepancy",
        {"action": req.action, "new_status": new_status, "supplier_id": disc["supplier_id"]},
        performed_by=current_user.username,
    )
    return {"status": "success", "discrepancy_id": discrepancy_id, "new_status": new_status}


# ------------------------------------------
# Supplier Portal Endpoints
# ------------------------------------------

@router.get("/supplier/purchase-orders")
def list_supplier_purchase_orders_endpoint(
    search: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: AuthenticatedPortalUser = Depends(get_current_supplier_user),
):
    """
    Retrieve purchase orders belonging exclusively to the authenticated supplier organization.
    Anti-IDOR: Filters strictly by current_user.organization_id.
    """
    supplier_id = current_user.organization_id
    clauses = ["po.supplier_id = ?"]
    params: list[Any] = [supplier_id]

    if search:
        s = f"%{search.strip().lower()}%"
        clauses.append("LOWER(po.po_number) LIKE ?")
        params.append(s)
    if status_filter:
        clauses.append("po.status = ?")
        params.append(status_filter.strip().lower())

    where = f"WHERE {' AND '.join(clauses)}"

    with get_connection() as conn:
        count_row = conn.execute(f"SELECT count(*) FROM purchase_orders po {where}", params).fetchone()
        total = count_row[0]

        rows = conn.execute(
            f"""
            SELECT po.id, po.po_number, po.order_date, po.expected_delivery_date,
                   po.currency, po.payment_terms, po.subtotal, po.tax_total, po.grand_total,
                   po.status, po.supplier_ack_status, po.supplier_ack_at, po.supplier_ack_by,
                   po.supplier_ack_notes, po.supplier_proposed_delivery_date, po.created_at,
                   (SELECT count(*) FROM purchase_order_items WHERE po_id = po.id) as item_count
            FROM purchase_orders po
            {where}
            ORDER BY po.order_date DESC, po.created_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()

    return {"total": total, "items": [dict(r) for r in rows], "supplier_id": supplier_id}


@router.get("/supplier/purchase-orders/{po_id}")
def get_supplier_purchase_order_endpoint(
    po_id: str,
    current_user: AuthenticatedPortalUser = Depends(get_current_supplier_user),
):
    """
    Retrieve detailed purchase order information for the authenticated supplier.
    Anti-IDOR: Denies access (404) if purchase order does not belong to caller's organization.
    """
    supplier_id = current_user.organization_id
    with get_connection() as conn:
        po_row = conn.execute(
            """
            SELECT id, po_number, supplier_id, order_date, expected_delivery_date,
                   currency, payment_terms, subtotal, tax_total, grand_total,
                   status, supplier_ack_status, supplier_ack_at, supplier_ack_by,
                   supplier_ack_notes, supplier_proposed_delivery_date, created_at, updated_at
            FROM purchase_orders
            WHERE id = ? AND supplier_id = ?
            """,
            (po_id, supplier_id),
        ).fetchone()

        if not po_row:
            # Deny by default: 404 prevents leaking existence of other tenants' orders
            raise HTTPException(status_code=404, detail=f"Purchase order '{po_id}' not found.")

        # Approved line items
        items = conn.execute(
            """
            SELECT id, product_id, sku, product_name, uom, ordered_qty, unit_price,
                   tax_rate_pct, line_total, received_qty, sort_order
            FROM purchase_order_items
            WHERE po_id = ?
            ORDER BY sort_order ASC
            """,
            (po_id,),
        ).fetchall()

        # Acknowledgement history
        acks = conn.execute(
            """
            SELECT id, action, previous_ack_status, supplier_comments,
                   proposed_delivery_date, portal_username, created_at
            FROM po_acknowledgements
            WHERE po_id = ? AND supplier_id = ?
            ORDER BY created_at DESC
            """,
            (po_id, supplier_id),
        ).fetchall()

        # Authorized goods receipts status (safe overview without internal notes)
        receipts = conn.execute(
            """
            SELECT id, receipt_number, receipt_date, status, created_at
            FROM goods_receipts
            WHERE po_id = ? AND supplier_id = ?
            ORDER BY receipt_date DESC
            """,
            (po_id, supplier_id),
        ).fetchall()

    po_dict = dict(po_row)
    po_dict["items"] = [dict(i) for i in items]
    po_dict["acknowledgement_history"] = [dict(a) for a in acks]
    po_dict["goods_receipts"] = [dict(r) for r in receipts]
    return po_dict


@router.post("/supplier/purchase-orders/{po_id}/acknowledge")
def acknowledge_purchase_order_endpoint(
    po_id: str,
    req: POAcknowledgeRequest,
    current_user: AuthenticatedPortalUser = Depends(get_current_supplier_user),
):
    """
    Controlled external write operation for suppliers to acknowledge a purchase order.
    - Accept, reject, or request clarification.
    - Optional comments and proposed delivery date.
    - Strict validation, idempotency, and anti-IDOR verification.
    - Strictly forbids mutating stock or internal approvals.
    """
    supplier_id = current_user.organization_id
    now_iso = datetime.now(timezone.utc).isoformat()

    # Comment validation
    clean_comments = req.supplier_comments.strip() if req.supplier_comments else None
    if clean_comments and len(clean_comments) > 1000:
        raise HTTPException(status_code=400, detail="Supplier comments cannot exceed 1000 characters.")

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        po = conn.execute(
            "SELECT id, po_number, supplier_id, status, supplier_ack_status FROM purchase_orders WHERE id = ?",
            (po_id,),
        ).fetchone()

        if not po or po["supplier_id"] != supplier_id:
            # IDOR defense: return 404
            raise HTTPException(status_code=404, detail=f"Purchase order '{po_id}' not found.")

        # Status eligibility: only submitted or approved orders can be acknowledged
        if po["status"] not in ("submitted", "approved"):
            raise HTTPException(
                status_code=400,
                detail=f"Purchase order cannot be acknowledged in '{po['status']}' status (must be submitted or approved).",
            )

        # Idempotency Guard
        if req.idempotency_key:
            existing_ack = conn.execute(
                "SELECT * FROM po_acknowledgements WHERE idempotency_key = ? AND supplier_id = ?",
                (req.idempotency_key, supplier_id),
            ).fetchone()
            if existing_ack:
                if existing_ack["po_id"] == po_id and existing_ack["action"] == req.action:
                    conn.commit()
                    return {
                        "status": "idempotent_duplicate",
                        "acknowledgement": dict(existing_ack),
                        "po_number": po["po_number"],
                    }
                else:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency key was previously used with different acknowledgement parameters.",
                    )

        ack_id = f"ack-{uuid.uuid4().hex[:10]}"
        prev_ack = po["supplier_ack_status"] or "unacknowledged"

        # Record immutable acknowledgement
        conn.execute(
            """
            INSERT INTO po_acknowledgements (
                id, po_id, supplier_id, portal_user_id, portal_username,
                action, previous_ack_status, supplier_comments,
                proposed_delivery_date, idempotency_key, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ack_id,
                po_id,
                supplier_id,
                current_user.id,
                current_user.username,
                req.action,
                prev_ack,
                clean_comments,
                req.proposed_delivery_date,
                req.idempotency_key,
                now_iso,
            ),
        )

        # Update purchase order acknowledgement metadata
        conn.execute(
            """
            UPDATE purchase_orders
            SET supplier_ack_status = ?,
                supplier_ack_at = ?,
                supplier_ack_by = ?,
                supplier_ack_notes = ?,
                supplier_proposed_delivery_date = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                req.action,
                now_iso,
                current_user.username,
                clean_comments,
                req.proposed_delivery_date,
                now_iso,
                po_id,
            ),
        )
        conn.commit()

    record_erp_audit_log(
        "purchase_order",
        po_id,
        "supplier_acknowledge_po",
        {
            "action": req.action,
            "previous_ack_status": prev_ack,
            "supplier_id": supplier_id,
            "proposed_delivery_date": req.proposed_delivery_date,
        },
        performed_by=f"Supplier:{current_user.username}",
    )

    return {
        "status": "success",
        "acknowledgement_id": ack_id,
        "action": req.action,
        "po_number": po["po_number"],
        "timestamp": now_iso,
    }


# ------------------------------------------
# Phase 9B: Advanced Supplier Collaboration Endpoints
# ------------------------------------------

@router.post("/supplier/purchase-orders/{po_id}/commitments")
def create_delivery_commitment_endpoint(
    po_id: str,
    req: DeliveryCommitmentCreateRequest,
    current_user: AuthenticatedPortalUser = Depends(get_current_supplier_user),
):
    """
    Submit or revise a delivery commitment for an authorized supplier purchase order.
    - Preserves revision history (increments revision_number).
    - Validates partial delivery quantities against remaining PO item quantities.
    - Idempotent submission guard.
    - Strictly does NOT create goods receipts or post inventory.
    """
    supplier_id = current_user.organization_id
    now_iso = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        po = conn.execute(
            "SELECT id, po_number, supplier_id, status FROM purchase_orders WHERE id = ?",
            (po_id,),
        ).fetchone()

        if not po or po["supplier_id"] != supplier_id:
            raise HTTPException(status_code=404, detail=f"Purchase order '{po_id}' not found.")

        if po["status"] not in ("submitted", "approved"):
            raise HTTPException(
                status_code=400,
                detail=f"Commitment cannot be created for purchase order in '{po['status']}' status.",
            )

        # Idempotency check
        if req.idempotency_key:
            existing = conn.execute(
                "SELECT * FROM supplier_delivery_commitments WHERE idempotency_key = ? AND supplier_id = ?",
                (req.idempotency_key, supplier_id),
            ).fetchone()
            if existing:
                if existing["po_id"] == po_id:
                    conn.commit()
                    return {
                        "status": "idempotent_duplicate",
                        "commitment": dict(existing),
                        "po_number": po["po_number"],
                    }
                else:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency key was previously used with a different purchase order.",
                    )

        # Validate line items
        if req.lines:
            for line in req.lines:
                item = conn.execute(
                    "SELECT id, ordered_qty, received_qty, sku FROM purchase_order_items WHERE id = ? AND po_id = ?",
                    (line.po_item_id, po_id),
                ).fetchone()
                if not item:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Line item '{line.po_item_id}' does not belong to purchase order '{po_id}'.",
                    )
                remaining_qty = max(0.0, float(item["ordered_qty"]) - float(item["received_qty"]))
                if line.committed_qty > remaining_qty:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Committed quantity {line.committed_qty} exceeds remaining balance {remaining_qty} for SKU '{item['sku']}'.",
                    )

        # Calculate next revision number
        max_rev = conn.execute(
            "SELECT COALESCE(MAX(revision_number), 0) FROM supplier_delivery_commitments WHERE po_id = ?",
            (po_id,),
        ).fetchone()[0]
        next_rev = max_rev + 1

        # Supersede old proposed commitments for this PO
        conn.execute(
            "UPDATE supplier_delivery_commitments SET status = 'superseded', updated_at = ? WHERE po_id = ? AND status = 'proposed'",
            (now_iso, po_id),
        )

        commitment_id = f"sdc-{uuid.uuid4().hex[:10]}"
        conn.execute(
            """
            INSERT INTO supplier_delivery_commitments (
                id, po_id, supplier_id, revision_number, proposed_delivery_date,
                supplier_dispatch_ref, carrier_name, tracking_number,
                supplier_comments, status, idempotency_key, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?, ?)
            """,
            (
                commitment_id,
                po_id,
                supplier_id,
                next_rev,
                req.proposed_delivery_date,
                req.supplier_dispatch_ref,
                req.carrier_name,
                req.tracking_number,
                req.supplier_comments,
                req.idempotency_key,
                current_user.id,
                now_iso,
                now_iso,
            ),
        )

        # Insert commitment lines
        for line in req.lines:
            line_id = f"sdcl-{uuid.uuid4().hex[:10]}"
            conn.execute(
                """
                INSERT INTO supplier_delivery_commitment_lines (
                    id, commitment_id, po_item_id, product_id, committed_qty, created_at
                ) VALUES (?, ?, ?, (SELECT product_id FROM purchase_order_items WHERE id = ?), ?, ?)
                """,
                (line_id, commitment_id, line.po_item_id, line.po_item_id, line.committed_qty, now_iso),
            )

        # Update proposed delivery date on purchase order record
        conn.execute(
            "UPDATE purchase_orders SET supplier_proposed_delivery_date = ?, updated_at = ? WHERE id = ?",
            (req.proposed_delivery_date, now_iso, po_id),
        )
        conn.commit()

    record_erp_audit_log(
        "supplier_delivery_commitment",
        commitment_id,
        "create_delivery_commitment",
        {
            "po_id": po_id,
            "revision_number": next_rev,
            "proposed_delivery_date": req.proposed_delivery_date,
            "supplier_id": supplier_id,
        },
        performed_by=f"Supplier:{current_user.username}",
    )

    return {
        "status": "success",
        "commitment_id": commitment_id,
        "revision_number": next_rev,
        "po_number": po["po_number"],
        "proposed_delivery_date": req.proposed_delivery_date,
    }


@router.get("/supplier/purchase-orders/{po_id}/commitments")
def list_supplier_commitments_endpoint(
    po_id: str,
    current_user: AuthenticatedPortalUser = Depends(get_current_supplier_user),
):
    """List delivery commitments and revision history for a supplier's purchase order."""
    supplier_id = current_user.organization_id
    with get_connection() as conn:
        po = conn.execute(
            "SELECT id, po_number FROM purchase_orders WHERE id = ? AND supplier_id = ?",
            (po_id, supplier_id),
        ).fetchone()
        if not po:
            raise HTTPException(status_code=404, detail=f"Purchase order '{po_id}' not found.")

        rows = conn.execute(
            """
            SELECT * FROM supplier_delivery_commitments
            WHERE po_id = ? AND supplier_id = ?
            ORDER BY revision_number DESC, created_at DESC
            """,
            (po_id, supplier_id),
        ).fetchall()

        commitments = []
        for r in rows:
            lines = conn.execute(
                """
                SELECT cl.*, poi.sku, poi.product_name, poi.uom
                FROM supplier_delivery_commitment_lines cl
                JOIN purchase_order_items poi ON cl.po_item_id = poi.id
                WHERE cl.commitment_id = ?
                """,
                (r["id"],),
            ).fetchall()
            c_dict = dict(r)
            c_dict["lines"] = [dict(l) for l in lines]
            commitments.append(c_dict)

    return {"po_number": po["po_number"], "total": len(commitments), "items": commitments}


@router.post("/supplier/asns")
def create_supplier_asn_endpoint(
    req: ASNCreateRequest,
    current_user: AuthenticatedPortalUser = Depends(get_current_supplier_user),
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
):
    """
    Create an Advance Shipment Notice (ASN) for a supplier-owned purchase order.
    - Validates lines against remaining PO balances.
    - Enforces dispatch reference uniqueness per supplier.
    - Protects against duplicate submissions via idempotency keys.
    - Strictly does NOT post inventory or create goods receipts.
    """
    supplier_id = current_user.organization_id
    effective_idemp = req.idempotency_key or x_idempotency_key
    now_iso = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        po = conn.execute(
            "SELECT id, po_number, supplier_id, status FROM purchase_orders WHERE id = ?",
            (req.po_id,),
        ).fetchone()

        if not po or po["supplier_id"] != supplier_id:
            raise HTTPException(status_code=404, detail=f"Purchase order '{req.po_id}' not found.")

        if po["status"] not in ("submitted", "approved"):
            raise HTTPException(
                status_code=400,
                detail=f"ASN cannot be submitted for purchase order in '{po['status']}' status.",
            )

        # 1. Idempotency verification if key provided
        if effective_idemp:
            existing_idemp = conn.execute(
                "SELECT * FROM supplier_asns WHERE supplier_id = ? AND idempotency_key = ?",
                (supplier_id, effective_idemp),
            ).fetchone()
            if existing_idemp:
                if existing_idemp["po_id"] == req.po_id and existing_idemp["dispatch_reference"] == req.dispatch_reference:
                    conn.commit()
                    return {
                        "status": "idempotent_duplicate",
                        "asn_id": existing_idemp["id"],
                        "asn_number": existing_idemp["asn_number"],
                    }
                else:
                    raise HTTPException(
                        status_code=409,
                        detail="Payload does not match previous request with this idempotency key.",
                    )

        # 2. Dispatch reference uniqueness per supplier
        existing_dispatch = conn.execute(
            "SELECT * FROM supplier_asns WHERE supplier_id = ? AND dispatch_reference = ?",
            (supplier_id, req.dispatch_reference),
        ).fetchone()

        if existing_dispatch:
            if effective_idemp and existing_dispatch["idempotency_key"] == effective_idemp:
                if existing_dispatch["po_id"] == req.po_id:
                    conn.commit()
                    return {
                        "status": "idempotent_duplicate",
                        "asn_id": existing_dispatch["id"],
                        "asn_number": existing_dispatch["asn_number"],
                    }
                else:
                    raise HTTPException(
                        status_code=409,
                        detail="Payload does not match previous request with this idempotency key.",
                    )
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Dispatch reference '{req.dispatch_reference}' has already been used by your organization.",
                )

        # Validate line items against PO items and quantities
        for item in req.items:
            po_item = conn.execute(
                "SELECT id, ordered_qty, received_qty, sku FROM purchase_order_items WHERE id = ? AND po_id = ?",
                (item.po_item_id, req.po_id),
            ).fetchone()
            if not po_item:
                raise HTTPException(
                    status_code=400,
                    detail=f"Item '{item.po_item_id}' does not belong to purchase order '{req.po_id}'.",
                )
            remaining_qty = max(0.0, float(po_item["ordered_qty"]) - float(po_item["received_qty"]))
            if item.shipped_qty > remaining_qty:
                raise HTTPException(
                    status_code=400,
                    detail=f"Shipped quantity {item.shipped_qty} exceeds remaining quantity {remaining_qty} for SKU '{po_item['sku']}'.",
                )

        asn_id = f"asn-{uuid.uuid4().hex[:10]}"
        today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        seq = conn.execute("SELECT count(*) FROM supplier_asns").fetchone()[0] + 1
        asn_number = f"ASN-{today_str}-{seq:04d}"

        conn.execute(
            """
            INSERT INTO supplier_asns (
                id, asn_number, po_id, supplier_id, dispatch_reference,
                package_count, carrier_name, tracking_number, dispatch_date,
                expected_arrival_date, status, notes, idempotency_key,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'submitted', ?, ?, ?, ?, ?)
            """,
            (
                asn_id,
                asn_number,
                req.po_id,
                supplier_id,
                req.dispatch_reference,
                req.package_count,
                req.carrier_name,
                req.tracking_number,
                req.dispatch_date,
                req.expected_arrival_date,
                req.notes,
                effective_idemp,
                current_user.id,
                now_iso,
                now_iso,
            ),
        )

        for item in req.items:
            item_id = f"asni-{uuid.uuid4().hex[:10]}"
            conn.execute(
                """
                INSERT INTO supplier_asn_items (
                    id, asn_id, po_item_id, product_id, sku, product_name, uom, shipped_qty, package_label, created_at
                )
                SELECT ?, ?, poi.id, poi.product_id, poi.sku, poi.product_name, poi.uom, ?, ?, ?
                FROM purchase_order_items poi
                WHERE poi.id = ?
                """,
                (item_id, asn_id, item.shipped_qty, item.package_label, now_iso, item.po_item_id),
            )

        conn.commit()

    record_erp_audit_log(
        "supplier_asn",
        asn_id,
        "create_supplier_asn",
        {
            "asn_number": asn_number,
            "po_id": req.po_id,
            "supplier_id": supplier_id,
            "dispatch_reference": req.dispatch_reference,
        },
        performed_by=f"Supplier:{current_user.username}",
    )

    return {
        "status": "success",
        "asn_id": asn_id,
        "asn_number": asn_number,
        "po_number": po["po_number"],
    }


@router.get("/supplier/asns")
def list_supplier_asns_endpoint(
    po_id: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    current_user: AuthenticatedPortalUser = Depends(get_current_supplier_user),
):
    """List ASNs created by the authenticated supplier."""
    supplier_id = current_user.organization_id
    clauses = ["a.supplier_id = ?"]
    params: list[Any] = [supplier_id]

    if po_id:
        clauses.append("a.po_id = ?")
        params.append(po_id.strip())
    if status_filter:
        clauses.append("a.status = ?")
        params.append(status_filter.strip().lower())

    where = f"WHERE {' AND '.join(clauses)}"

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT a.*, po.po_number,
                   (SELECT count(*) FROM supplier_asn_items WHERE asn_id = a.id) as item_count
            FROM supplier_asns a
            JOIN purchase_orders po ON a.po_id = po.id
            {where}
            ORDER BY a.created_at DESC
            """,
            params,
        ).fetchall()

    return {"total": len(rows), "items": [dict(r) for r in rows]}


@router.get("/supplier/asns/{asn_id}")
def get_supplier_asn_detail_endpoint(
    asn_id: str,
    current_user: AuthenticatedPortalUser = Depends(get_current_supplier_user),
):
    """Retrieve full ASN details for the authenticated supplier (Anti-IDOR protected)."""
    supplier_id = current_user.organization_id
    with get_connection() as conn:
        asn = conn.execute(
            """
            SELECT a.*, po.po_number
            FROM supplier_asns a
            JOIN purchase_orders po ON a.po_id = po.id
            WHERE a.id = ? AND a.supplier_id = ?
            """,
            (asn_id, supplier_id),
        ).fetchone()
        if not asn:
            raise HTTPException(status_code=404, detail=f"ASN '{asn_id}' not found.")

        items = conn.execute("SELECT * FROM supplier_asn_items WHERE asn_id = ?", (asn_id,)).fetchall()
        docs = conn.execute("SELECT * FROM documents WHERE asn_id = ? AND supplier_id = ?", (asn_id, supplier_id)).fetchall()

    return {"asn": dict(asn), "items": [dict(it) for it in items], "documents": [dict(d) for d in docs]}


@router.post("/supplier/documents/upload")
async def upload_supplier_document_endpoint(
    file: UploadFile = File(...),
    po_id: str = Form(...),
    asn_id: str | None = Form(None),
    document_type: str = Form("supplier_document"),
    notes: str | None = Form(None),
    current_user: AuthenticatedPortalUser = Depends(get_current_supplier_user),
):
    """
    Secure supplier document upload.
    - Validates file size, extension allowlist, and file signature.
    - Verifies supplier ownership of target purchase order and ASN.
    - Enters 'pending_review' state for internal staff approval.
    - Strictly private by default (never exposed to customers).
    """
    supplier_id = current_user.organization_id
    now_iso = datetime.now(timezone.utc).isoformat()

    # Verify PO ownership and ensure backing shipment record
    with get_connection() as conn:
        po = conn.execute("SELECT id, po_number FROM purchase_orders WHERE id = ? AND supplier_id = ?", (po_id, supplier_id)).fetchone()
        if not po:
            raise HTTPException(status_code=404, detail=f"Purchase order '{po_id}' not found.")

        if asn_id:
            asn = conn.execute("SELECT id FROM supplier_asns WHERE id = ? AND supplier_id = ?", (asn_id, supplier_id)).fetchone()
            if not asn:
                raise HTTPException(status_code=404, detail=f"ASN '{asn_id}' not found.")

        # Ensure backing shipment record exists for documents.shipment_id foreign key constraint
        shp = conn.execute("SELECT id FROM shipments WHERE id = ?", (po_id,)).fetchone()
        if not shp:
            conn.execute(
                """
                INSERT OR IGNORE INTO shipments (id, reference, exporter, buyer, status, created_at, updated_at)
                VALUES (?, ?, ?, 'TradeSathi Internal', 'draft', ?, ?)
                """,
                (po_id, po["po_number"], current_user.organization_name, now_iso, now_iso),
            )
            conn.commit()

    content = await file.read()
    validate_supplier_file(file.filename, content)

    # Save to disk using isolated storage helper
    doc_id = f"doc-{uuid.uuid4().hex[:10]}"
    try:
        _, storage_key, file_hash = save_document_file(
            shipment_id=po_id,
            original_filename=file.filename,
            content=content,
            doc_id=doc_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Insert into database with rollback guard
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO documents (
                    id, shipment_id, original_filename, clean_filename,
                    document_type, uploaded_at, storage_key, file_size, file_hash,
                    processing_status, review_status, notes, created_at, updated_at,
                    shared_with_customer, shared_with_supplier, po_id, asn_id, supplier_id, uploaded_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed', 'pending_review', ?, ?, ?, 0, 1, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    po_id,
                    file.filename,
                    sanitize_filename(file.filename),
                    document_type,
                    now_iso,
                    storage_key,
                    len(content),
                    file_hash,
                    notes,
                    now_iso,
                    now_iso,
                    po_id,
                    asn_id,
                    supplier_id,
                    current_user.id,
                ),
            )
            conn.commit()
    except Exception as exc:
        delete_document_file(storage_key)
        raise HTTPException(status_code=500, detail="Failed to record document metadata.") from exc

    record_erp_audit_log(
        "document",
        doc_id,
        "supplier_upload_document",
        {
            "po_id": po_id,
            "asn_id": asn_id,
            "filename": file.filename,
            "file_size": len(content),
            "file_hash": file_hash,
            "supplier_id": supplier_id,
        },
        performed_by=f"Supplier:{current_user.username}",
    )

    return {
        "status": "success",
        "document_id": doc_id,
        "filename": file.filename,
        "review_status": "pending_review",
    }


@router.get("/supplier/documents")
def list_supplier_documents_endpoint(
    po_id: str | None = Query(None),
    asn_id: str | None = Query(None),
    current_user: AuthenticatedPortalUser = Depends(get_current_supplier_user),
):
    """List documents uploaded by or shared with the authenticated supplier."""
    supplier_id = current_user.organization_id
    clauses = ["(supplier_id = ? OR po_id IN (SELECT id FROM purchase_orders WHERE supplier_id = ?))"]
    params: list[Any] = [supplier_id, supplier_id]

    if po_id:
        clauses.append("po_id = ?")
        params.append(po_id.strip())
    if asn_id:
        clauses.append("asn_id = ?")
        params.append(asn_id.strip())

    where = f"WHERE {' AND '.join(clauses)}"
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, original_filename, clean_filename, document_type, uploaded_at,
                   file_size, review_status, notes, po_id, asn_id, created_at
            FROM documents
            {where}
            ORDER BY created_at DESC
            """,
            tuple(params),
        ).fetchall()

    return {"total": len(rows), "items": [dict(r) for r in rows]}


@router.post("/supplier/discrepancies")
def create_supplier_discrepancy_endpoint(
    req: DiscrepancyCreateRequest,
    current_user: AuthenticatedPortalUser = Depends(get_current_supplier_user),
):
    """
    Submit a delivery discrepancy against a supplier's purchase order or ASN.
    - Status initialized to 'open'.
    - Strictly separate internal notes from supplier visibility.
    - Strictly does NOT mutate inventory or goods receipts.
    """
    supplier_id = current_user.organization_id
    now_iso = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        po = conn.execute("SELECT id, po_number FROM purchase_orders WHERE id = ? AND supplier_id = ?", (req.po_id, supplier_id)).fetchone()
        if not po:
            raise HTTPException(status_code=404, detail=f"Purchase order '{req.po_id}' not found.")

        if req.asn_id:
            asn = conn.execute("SELECT id FROM supplier_asns WHERE id = ? AND supplier_id = ?", (req.asn_id, supplier_id)).fetchone()
            if not asn:
                raise HTTPException(status_code=404, detail=f"ASN '{req.asn_id}' not found.")

        # Idempotency check
        if req.idempotency_key:
            existing = conn.execute(
                "SELECT id, discrepancy_number FROM supplier_discrepancies WHERE idempotency_key = ? AND supplier_id = ?",
                (req.idempotency_key, supplier_id),
            ).fetchone()
            if existing:
                conn.commit()
                return {
                    "status": "idempotent_duplicate",
                    "discrepancy_id": existing["id"],
                    "discrepancy_number": existing["discrepancy_number"],
                }

        disc_id = f"disc-{uuid.uuid4().hex[:10]}"
        today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        seq = conn.execute("SELECT count(*) FROM supplier_discrepancies").fetchone()[0] + 1
        disc_num = f"DISC-{today_str}-{seq:04d}"

        conn.execute(
            """
            INSERT INTO supplier_discrepancies (
                id, discrepancy_number, supplier_id, po_id, asn_id, commitment_id,
                category, title, description, status, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)
            """,
            (
                disc_id,
                disc_num,
                supplier_id,
                req.po_id,
                req.asn_id,
                req.commitment_id,
                req.category,
                req.title.strip(),
                req.description.strip(),
                current_user.id,
                now_iso,
                now_iso,
            ),
        )

        msg_id = f"dmsg-{uuid.uuid4().hex[:10]}"
        conn.execute(
            """
            INSERT INTO supplier_discrepancy_messages (
                id, discrepancy_id, sender_type, sender_id, sender_name, message, attachments_json, created_at
            ) VALUES (?, ?, 'supplier', ?, ?, ?, ?, ?)
            """,
            (
                msg_id,
                disc_id,
                current_user.id,
                current_user.username,
                req.description.strip(),
                json.dumps(req.document_ids),
                now_iso,
            ),
        )
        conn.commit()

    record_erp_audit_log(
        "supplier_discrepancy",
        disc_id,
        "create_supplier_discrepancy",
        {
            "discrepancy_number": disc_num,
            "po_id": req.po_id,
            "category": req.category,
            "supplier_id": supplier_id,
        },
        performed_by=f"Supplier:{current_user.username}",
    )

    return {
        "status": "success",
        "discrepancy_id": disc_id,
        "discrepancy_number": disc_num,
        "po_number": po["po_number"],
    }


@router.get("/supplier/discrepancies")
def list_supplier_discrepancies_endpoint(
    po_id: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    current_user: AuthenticatedPortalUser = Depends(get_current_supplier_user),
):
    """List discrepancies reported by the authenticated supplier (strictly excludes internal notes)."""
    supplier_id = current_user.organization_id
    clauses = ["d.supplier_id = ?"]
    params: list[Any] = [supplier_id]

    if po_id:
        clauses.append("d.po_id = ?")
        params.append(po_id.strip())
    if status_filter:
        clauses.append("d.status = ?")
        params.append(status_filter.strip().lower())

    where = f"WHERE {' AND '.join(clauses)}"

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT d.id, d.discrepancy_number, d.po_id, po.po_number, d.asn_id, a.asn_number,
                   d.category, d.title, d.description, d.status, d.shared_resolution_notes,
                   d.resolved_at, d.created_at, d.updated_at
            FROM supplier_discrepancies d
            JOIN purchase_orders po ON d.po_id = po.id
            LEFT JOIN supplier_asns a ON d.asn_id = a.id
            {where}
            ORDER BY d.created_at DESC
            """,
            params,
        ).fetchall()

    return {"total": len(rows), "items": [dict(r) for r in rows]}


@router.get("/supplier/discrepancies/{discrepancy_id}")
def get_supplier_discrepancy_detail_endpoint(
    discrepancy_id: str,
    current_user: AuthenticatedPortalUser = Depends(get_current_supplier_user),
):
    """Retrieve full discrepancy details and message thread for supplier (strictly excludes internal notes)."""
    supplier_id = current_user.organization_id
    with get_connection() as conn:
        disc = conn.execute(
            """
            SELECT d.id, d.discrepancy_number, d.po_id, po.po_number, d.asn_id, a.asn_number,
                   d.category, d.title, d.description, d.status, d.shared_resolution_notes,
                   d.resolved_at, d.created_at, d.updated_at
            FROM supplier_discrepancies d
            JOIN purchase_orders po ON d.po_id = po.id
            LEFT JOIN supplier_asns a ON d.asn_id = a.id
            WHERE d.id = ? AND d.supplier_id = ?
            """,
            (discrepancy_id, supplier_id),
        ).fetchone()

        if not disc:
            raise HTTPException(status_code=404, detail=f"Discrepancy '{discrepancy_id}' not found.")

        messages = conn.execute(
            """
            SELECT id, sender_type, sender_name, message, attachments_json, created_at
            FROM supplier_discrepancy_messages
            WHERE discrepancy_id = ?
            ORDER BY created_at ASC
            """,
            (discrepancy_id,),
        ).fetchall()

    return {"discrepancy": dict(disc), "messages": [dict(m) for m in messages]}


@router.post("/supplier/discrepancies/{discrepancy_id}/messages")
def add_supplier_discrepancy_message_endpoint(
    discrepancy_id: str,
    req: DiscrepancyMessageCreateRequest,
    current_user: AuthenticatedPortalUser = Depends(get_current_supplier_user),
):
    """Add a supplier message/evidence to an open discrepancy. Transitions awaiting_supplier -> under_review."""
    supplier_id = current_user.organization_id
    now_iso = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        disc = conn.execute(
            "SELECT id, status, supplier_id FROM supplier_discrepancies WHERE id = ? AND supplier_id = ?",
            (discrepancy_id, supplier_id),
        ).fetchone()

        if not disc:
            raise HTTPException(status_code=404, detail=f"Discrepancy '{discrepancy_id}' not found.")

        if disc["status"] in ("resolved", "closed", "rejected"):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot add messages to a discrepancy in '{disc['status']}' status.",
            )

        new_status = "under_review" if disc["status"] == "awaiting_supplier" else disc["status"]

        msg_id = f"dmsg-{uuid.uuid4().hex[:10]}"
        conn.execute(
            """
            INSERT INTO supplier_discrepancy_messages (
                id, discrepancy_id, sender_type, sender_id, sender_name, message, attachments_json, created_at
            ) VALUES (?, ?, 'supplier', ?, ?, ?, ?, ?)
            """,
            (
                msg_id,
                discrepancy_id,
                current_user.id,
                current_user.username,
                req.message.strip(),
                json.dumps(req.document_ids),
                now_iso,
            ),
        )

        conn.execute(
            "UPDATE supplier_discrepancies SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, now_iso, discrepancy_id),
        )
        conn.commit()

    record_erp_audit_log(
        "supplier_discrepancy",
        discrepancy_id,
        "supplier_add_discrepancy_message",
        {"new_status": new_status, "supplier_id": supplier_id},
        performed_by=f"Supplier:{current_user.username}",
    )

    return {"status": "success", "message_id": msg_id, "discrepancy_status": new_status}


# ------------------------------------------
# Customer Portal Endpoints (Read-Only)
# ------------------------------------------

@router.get("/customer/sales-orders")
def list_customer_sales_orders_endpoint(
    search: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: AuthenticatedPortalUser = Depends(get_current_customer_user),
):
    """
    Retrieve sales orders belonging exclusively to the authenticated customer organization.
    Anti-IDOR: Filters strictly by current_user.organization_id.
    """
    customer_id = current_user.organization_id
    clauses = ["so.customer_id = ?"]
    params: list[Any] = [customer_id]

    if search:
        s = f"%{search.strip().lower()}%"
        clauses.append("LOWER(so.order_number) LIKE ?")
        params.append(s)
    if status_filter:
        clauses.append("so.status = ?")
        params.append(status_filter.strip().lower())

    where = f"WHERE {' AND '.join(clauses)}"

    with get_connection() as conn:
        count_row = conn.execute(f"SELECT count(*) FROM sales_orders so {where}", params).fetchone()
        total = count_row[0]

        rows = conn.execute(
            f"""
            SELECT so.id, so.order_number, so.order_date, so.requested_delivery_date,
                   so.currency, so.payment_terms, so.incoterm, so.destination_port,
                   so.subtotal, so.tax_total, so.grand_total, so.status, so.created_at,
                   (SELECT count(*) FROM sales_order_items WHERE sales_order_id = so.id) as item_count,
                   (SELECT count(*) FROM sales_dispatches WHERE sales_order_id = so.id) as dispatch_count
            FROM sales_orders so
            {where}
            ORDER BY so.order_date DESC, so.created_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()

    return {"total": total, "items": [dict(r) for r in rows], "customer_id": customer_id}


@router.get("/customer/sales-orders/{so_id}")
def get_customer_sales_order_endpoint(
    so_id: str,
    current_user: AuthenticatedPortalUser = Depends(get_current_customer_user),
):
    """
    Retrieve sales order details for the authenticated customer.
    Anti-IDOR: Denies access (404) if sales order does not belong to caller's organization.
    """
    customer_id = current_user.organization_id
    with get_connection() as conn:
        so_row = conn.execute(
            """
            SELECT id, order_number, customer_id, customer_name, billing_address,
                   shipping_address, order_date, requested_delivery_date,
                   currency, payment_terms, incoterm, destination_port,
                   subtotal, discount_total, tax_total, grand_total, status, created_at
            FROM sales_orders
            WHERE id = ? AND customer_id = ?
            """,
            (so_id, customer_id),
        ).fetchone()

        if not so_row:
            raise HTTPException(status_code=404, detail=f"Sales order '{so_id}' not found.")

        # Line items with fulfilment tracking quantities
        items = conn.execute(
            """
            SELECT id, product_sku, product_name, uom, ordered_quantity,
                   allocated_quantity, picked_quantity, dispatched_quantity, delivered_quantity,
                   unit_price, line_total
            FROM sales_order_items
            WHERE sales_order_id = ?
            ORDER BY sort_order ASC
            """,
            (so_id,),
        ).fetchall()

        # Customer-permitted dispatches and carrier tracking
        dispatches = conn.execute(
            """
            SELECT id, dispatch_number, dispatch_date, carrier, tracking_reference,
                   packages_count, total_weight_kg, status, delivered_at
            FROM sales_dispatches
            WHERE sales_order_id = ?
            ORDER BY dispatch_date DESC
            """,
            (so_id,),
        ).fetchall()

        # Explicitly shared documents
        docs = conn.execute(
            """
            SELECT id, original_filename, clean_filename, document_type, uploaded_at, file_size
            FROM documents
            WHERE sales_order_id = ? AND shared_with_customer = 1
            ORDER BY uploaded_at DESC
            """,
            (so_id,),
        ).fetchall()

    so_dict = dict(so_row)
    so_dict["items"] = [dict(i) for i in items]
    so_dict["dispatches"] = [dict(d) for d in dispatches]
    so_dict["shared_documents"] = [dict(doc) for doc in docs]
    return so_dict


@router.get("/customer/invoices")
def list_customer_invoices_endpoint(
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: AuthenticatedPortalUser = Depends(get_current_customer_user),
):
    """
    Retrieve issued invoices for the customer.
    Anti-IDOR: Filters strictly by customer_id.
    Safety Guard: Excludes internal 'draft' and 'cancelled' invoices.
    """
    customer_id = current_user.organization_id
    clauses = ["customer_id = ?", "status NOT IN ('draft', 'cancelled')"]
    params: list[Any] = [customer_id]

    if status_filter:
        clauses.append("status = ?")
        params.append(status_filter.strip().lower())

    where = f"WHERE {' AND '.join(clauses)}"

    with get_connection() as conn:
        count_row = conn.execute(f"SELECT count(*) FROM customer_invoices {where}", params).fetchone()
        total = count_row[0]

        rows = conn.execute(
            f"""
            SELECT id, invoice_number, invoice_date, due_date, currency,
                   grand_total, amount_paid, outstanding_balance, status, issued_at
            FROM customer_invoices
            {where}
            ORDER BY invoice_date DESC, created_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()

    return {"total": total, "items": [dict(r) for r in rows], "customer_id": customer_id}


@router.get("/customer/invoices/{invoice_id}")
def get_customer_invoice_endpoint(
    invoice_id: str,
    current_user: AuthenticatedPortalUser = Depends(get_current_customer_user),
):
    """Retrieve detailed issued invoice for the customer."""
    customer_id = current_user.organization_id
    with get_connection() as conn:
        inv = conn.execute(
            """
            SELECT id, invoice_number, customer_id, customer_name, billing_address,
                   invoice_date, due_date, currency, subtotal, discount_total,
                   tax_total, grand_total, amount_paid, outstanding_balance, status, issued_at
            FROM customer_invoices
            WHERE id = ? AND customer_id = ? AND status NOT IN ('draft', 'cancelled')
            """,
            (invoice_id, customer_id),
        ).fetchone()

        if not inv:
            raise HTTPException(status_code=404, detail=f"Invoice '{invoice_id}' not found.")

        items = conn.execute(
            """
            SELECT id, product_sku, description, hsn_code, uom, quantity,
                   unit_price, line_total, gst_rate_pct
            FROM customer_invoice_items
            WHERE invoice_id = ?
            ORDER BY sort_order ASC
            """,
            (invoice_id,),
        ).fetchall()

    inv_dict = dict(inv)
    inv_dict["items"] = [dict(i) for i in items]
    return inv_dict


@router.get("/customer/shipments")
def list_customer_shipments_endpoint(
    current_user: AuthenticatedPortalUser = Depends(get_current_customer_user),
):
    """
    Retrieve customer-linked export shipments with transit and readiness status.
    Anti-IDOR: Resolves strictly through customer_id or linked customer sales orders.
    """
    customer_id = current_user.organization_id
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT s.id, s.reference, s.destination_country, s.destination_port,
                            s.transport_mode, s.carrier_name, s.vessel_name, s.voyage_flight_no,
                            s.booking_reference, s.bill_of_lading_no, s.airway_bill_no,
                            s.package_count, s.gross_weight_kg, s.estimated_departure_date,
                            s.actual_departure_date, s.estimated_arrival_date, s.actual_arrival_date,
                            s.readiness_status, s.status
            FROM shipments s
            LEFT JOIN sales_orders so ON s.id = so.shipment_id
            WHERE s.customer_id = ? OR so.customer_id = ?
            ORDER BY s.created_at DESC
            """,
            (customer_id, customer_id),
        ).fetchall()

    return {"total": len(rows), "items": [dict(r) for r in rows]}


# ==========================================
# Phase 9C: Customer Communication Threads Endpoints
# ==========================================

@router.post("/customer/sales-orders/{so_id}/threads", status_code=status.HTTP_201_CREATED)
def create_customer_order_thread_endpoint(
    so_id: str,
    req: CustomerThreadCreateRequest,
    current_user: AuthenticatedPortalUser = Depends(get_current_customer_user),
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
):
    """
    Create a new order-specific communication thread linked to an authorized sales order.
    - Anti-IDOR: Validates sales order belongs to caller's customer organization.
    - Sanitizes subject & message against XSS payloads.
    - Thread status initialized to 'open'.
    - Append-only message creation.
    - Does NOT mutate order commercial terms, inventory, or readiness.
    """
    customer_id = current_user.organization_id
    effective_idemp = req.idempotency_key or x_idempotency_key
    clean_subject = sanitize_plain_text(req.subject)
    raw_message = req.message or req.initial_message or ""
    clean_message = sanitize_plain_text(raw_message)

    if len(clean_subject) < 3:
        raise HTTPException(status_code=400, detail="Subject must be at least 3 characters.")
    if len(clean_message) < 1:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    now_iso = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        so = conn.execute(
            "SELECT id, order_number, customer_id FROM sales_orders WHERE id = ? AND customer_id = ?",
            (so_id, customer_id),
        ).fetchone()

        if not so:
            raise HTTPException(status_code=404, detail=f"Sales order '{so_id}' not found.")

        # Idempotency check
        if effective_idemp:
            existing_msg = conn.execute(
                """
                SELECT m.thread_id, m.message, t.subject, t.sales_order_id
                FROM customer_order_messages m
                JOIN customer_order_threads t ON m.thread_id = t.id
                WHERE t.customer_id = ? AND m.idempotency_key = ?
                """,
                (customer_id, effective_idemp),
            ).fetchone()
            if existing_msg:
                if existing_msg["sales_order_id"] == so_id and existing_msg["subject"] == clean_subject:
                    conn.commit()
                    return Response(
                        content=json.dumps({
                            "status": "idempotent_duplicate",
                            "id": existing_msg["thread_id"],
                            "thread_id": existing_msg["thread_id"],
                            "subject": existing_msg["subject"],
                            "sales_order_id": so_id,
                            "status": "open",
                        }),
                        media_type="application/json",
                        status_code=200,
                    )
                else:
                    raise HTTPException(status_code=409, detail="Idempotency key reused with different parameters.")

        thread_id = f"thrd-{uuid.uuid4().hex[:10]}"
        msg_id = f"cmsg-{uuid.uuid4().hex[:10]}"

        conn.execute(
            """
            INSERT INTO customer_order_threads (
                id, sales_order_id, customer_id, subject, status,
                internal_notes, last_message_at, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'open', NULL, ?, ?, ?, ?)
            """,
            (
                thread_id,
                so_id,
                customer_id,
                clean_subject,
                now_iso,
                current_user.id,
                now_iso,
                now_iso,
            ),
        )

        conn.execute(
            """
            INSERT INTO customer_order_messages (
                id, thread_id, sender_type, sender_id, sender_name,
                message, is_internal_note, idempotency_key, created_at
            ) VALUES (?, ?, 'customer', ?, ?, ?, 0, ?, ?)
            """,
            (
                msg_id,
                thread_id,
                current_user.id,
                current_user.username,
                clean_message,
                effective_idemp,
                now_iso,
            ),
        )

        conn.commit()

    record_collaboration_notification(
        "staff",
        "all_staff",
        "customer_thread_created",
        f"New Inquiry on SO {so['order_number']}",
        clean_message[:100],
        "thread",
        thread_id,
    )

    record_erp_audit_log(
        "customer_order_thread",
        thread_id,
        "create_customer_order_thread",
        {
            "sales_order_id": so_id,
            "order_number": so["order_number"],
            "subject": clean_subject,
            "customer_id": customer_id,
        },
        performed_by=f"Customer:{current_user.username}",
    )

    return {
        "status": "open",
        "id": thread_id,
        "thread_id": thread_id,
        "message_id": msg_id,
        "subject": clean_subject,
        "sales_order_id": so_id,
    }


@router.get("/customer/sales-orders/{so_id}/threads")
def list_customer_order_threads_endpoint(
    so_id: str,
    current_user: AuthenticatedPortalUser = Depends(get_current_customer_user),
):
    """List message threads associated with an authorized sales order for the customer."""
    customer_id = current_user.organization_id
    with get_connection() as conn:
        so = conn.execute(
            "SELECT id FROM sales_orders WHERE id = ? AND customer_id = ?",
            (so_id, customer_id),
        ).fetchone()
        if not so:
            raise HTTPException(status_code=404, detail=f"Sales order '{so_id}' not found.")

        rows = conn.execute(
            """
            SELECT t.id, t.sales_order_id, t.subject, t.status, t.last_message_at,
                   t.created_at, t.updated_at,
                   (SELECT count(*) FROM customer_order_messages WHERE thread_id = t.id AND is_internal_note = 0) as message_count
            FROM customer_order_threads t
            WHERE t.sales_order_id = ? AND t.customer_id = ?
            ORDER BY t.last_message_at DESC
            """,
            (so_id, customer_id),
        ).fetchall()

    return {"total": len(rows), "items": [dict(r) for r in rows]}


@router.get("/customer/threads/{thread_id}")
def get_customer_thread_detail_endpoint(
    thread_id: str,
    current_user: AuthenticatedPortalUser = Depends(get_current_customer_user),
):
    """
    Retrieve thread details and message history for the customer.
    Anti-IDOR: strictly filters by customer_id.
    Safety Guard: completely excludes staff internal notes (is_internal_note = 1).
    """
    customer_id = current_user.organization_id
    with get_connection() as conn:
        thread_row = conn.execute(
            """
            SELECT t.id, t.sales_order_id, t.customer_id, t.subject, t.status,
                   t.last_message_at, t.created_at, t.updated_at,
                   so.order_number
            FROM customer_order_threads t
            JOIN sales_orders so ON t.sales_order_id = so.id
            WHERE t.id = ? AND t.customer_id = ?
            """,
            (thread_id, customer_id),
        ).fetchone()

        if not thread_row:
            raise HTTPException(status_code=404, detail=f"Thread '{thread_id}' not found.")

        messages = conn.execute(
            """
            SELECT id, thread_id, sender_type, sender_name, message, is_internal_note, created_at
            FROM customer_order_messages
            WHERE thread_id = ? AND is_internal_note = 0
            ORDER BY created_at ASC
            """,
            (thread_id,),
        ).fetchall()

    res = dict(thread_row)
    res["messages"] = [dict(m) for m in messages]
    return res


@router.post("/customer/threads/{thread_id}/messages", status_code=status.HTTP_201_CREATED)
def post_customer_thread_message_endpoint(
    thread_id: str,
    req: CustomerMessageCreateRequest,
    current_user: AuthenticatedPortalUser = Depends(get_current_customer_user),
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
):
    """
    Post a reply message in an existing order thread.
    - Rejects posting if thread status is 'closed'.
    - Sanitizes text content against XSS.
    - Idempotency guard prevents duplicate posts.
    """
    customer_id = current_user.organization_id
    effective_idemp = req.idempotency_key or x_idempotency_key
    clean_message = sanitize_plain_text(req.message)

    if len(clean_message) < 1:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    now_iso = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        thread_row = conn.execute(
            """
            SELECT t.id, t.status, t.sales_order_id, so.order_number
            FROM customer_order_threads t
            JOIN sales_orders so ON t.sales_order_id = so.id
            WHERE t.id = ? AND t.customer_id = ?
            """,
            (thread_id, customer_id),
        ).fetchone()

        if not thread_row:
            raise HTTPException(status_code=404, detail=f"Thread '{thread_id}' not found.")

        if thread_row["status"] == "closed":
            raise HTTPException(
                status_code=400,
                detail="Thread is closed. Please create a new thread for additional inquiries.",
            )

        # Idempotency check
        if effective_idemp:
            existing_msg = conn.execute(
                "SELECT id, message FROM customer_order_messages WHERE thread_id = ? AND idempotency_key = ?",
                (thread_id, effective_idemp),
            ).fetchone()
            if existing_msg:
                conn.commit()
                return Response(
                    content=json.dumps({
                        "status": "idempotent_duplicate",
                        "id": existing_msg["id"],
                        "message_id": existing_msg["id"],
                        "thread_id": thread_id,
                        "sender_type": "customer",
                        "is_internal_note": 0,
                    }),
                    media_type="application/json",
                    status_code=200,
                )

        msg_id = f"cmsg-{uuid.uuid4().hex[:10]}"
        conn.execute(
            """
            INSERT INTO customer_order_messages (
                id, thread_id, sender_type, sender_id, sender_name,
                message, is_internal_note, idempotency_key, created_at
            ) VALUES (?, ?, 'customer', ?, ?, ?, 0, ?, ?)
            """,
            (
                msg_id,
                thread_id,
                current_user.id,
                current_user.username,
                clean_message,
                effective_idemp,
                now_iso,
            ),
        )

        conn.execute(
            """
            UPDATE customer_order_threads
            SET last_message_at = ?, status = 'open', updated_at = ?
            WHERE id = ?
            """,
            (now_iso, now_iso, thread_id),
        )

        conn.commit()

    record_collaboration_notification(
        "staff",
        "all_staff",
        "customer_message",
        f"Reply on SO {thread_row['order_number']}",
        clean_message[:100],
        "thread",
        thread_id,
    )

    record_erp_audit_log(
        "customer_order_message",
        msg_id,
        "create_customer_order_message",
        {
            "thread_id": thread_id,
            "sales_order_id": thread_row["sales_order_id"],
            "customer_id": customer_id,
        },
        performed_by=f"Customer:{current_user.username}",
    )

    return {
        "status": "success",
        "id": msg_id,
        "message_id": msg_id,
        "thread_id": thread_id,
        "sender_type": "customer",
        "is_internal_note": 0,
    }


# ==========================================
# Phase 9C: Customer Document Requests Endpoints
# ==========================================

@router.post("/customer/sales-orders/{so_id}/document-requests", status_code=status.HTTP_201_CREATED)
def create_customer_document_request_endpoint(
    so_id: str,
    req: CustomerDocumentRequestCreate,
    current_user: AuthenticatedPortalUser = Depends(get_current_customer_user),
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
):
    """
    Submit a formal document request for an eligible document associated with a customer-owned sales order.
    - Anti-IDOR: Validates sales order belongs to caller's customer organization.
    - Enforces idempotency to prevent duplicate requests.
    - Status initialized to 'open'.
    - Does NOT automatically grant access to unshared documents or fabricate certificates.
    """
    customer_id = current_user.organization_id
    effective_idemp = req.idempotency_key or x_idempotency_key
    clean_message = sanitize_plain_text(req.message or "")
    cat = req.category or req.document_category

    ALLOWED_CATEGORIES = {
        "commercial_invoice",
        "packing_list",
        "shipping_bill",
        "bill_of_lading",
        "certificate_of_origin",
        "quality_certificate",
        "inspection_certificate",
        "other",
    }
    if not cat or cat not in ALLOWED_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid or missing document category '{cat}'. Allowed: {sorted(ALLOWED_CATEGORIES)}",
        )

    now_iso = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        so = conn.execute(
            "SELECT id, order_number, shipment_id FROM sales_orders WHERE id = ? AND customer_id = ?",
            (so_id, customer_id),
        ).fetchone()

        if not so:
            raise HTTPException(status_code=404, detail=f"Sales order '{so_id}' not found.")

        # If shipment_id was specified, verify association
        target_shipment_id = req.shipment_id or so["shipment_id"]
        if req.shipment_id and req.shipment_id != so["shipment_id"]:
            # Check if shipment explicitly belongs to customer
            shp = conn.execute(
                "SELECT id FROM shipments WHERE id = ? AND customer_id = ?",
                (req.shipment_id, customer_id),
            ).fetchone()
            if not shp:
                raise HTTPException(status_code=404, detail=f"Shipment '{req.shipment_id}' not associated with order or customer.")

        # Idempotency check
        if effective_idemp:
            existing = conn.execute(
                "SELECT id, request_number, sales_order_id, document_category FROM customer_document_requests WHERE customer_id = ? AND idempotency_key = ?",
                (customer_id, effective_idemp),
            ).fetchone()
            if existing:
                if existing["sales_order_id"] == so_id and existing["document_category"] == cat:
                    conn.commit()
                    return Response(
                        content=json.dumps({
                            "status": "open",
                            "id": existing["id"],
                            "request_id": existing["id"],
                            "request_number": existing["request_number"],
                            "category": cat,
                            "document_category": cat,
                            "sales_order_id": so_id,
                        }),
                        media_type="application/json",
                        status_code=200,
                    )
                else:
                    raise HTTPException(status_code=409, detail="Idempotency key reused with different parameters.")

        # Prevent duplicate active request for identical order and category
        existing_active = conn.execute(
            "SELECT id, request_number FROM customer_document_requests WHERE customer_id = ? AND sales_order_id = ? AND document_category = ? AND status IN ('open', 'under_review')",
            (customer_id, so_id, cat),
        ).fetchone()
        if existing_active:
            raise HTTPException(
                status_code=400,
                detail=f"Sales order '{so_id}' already has an active document request ({existing_active['request_number']}) for category '{cat}'.",
            )

        dreq_id = f"dreq-{uuid.uuid4().hex[:10]}"
        today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        seq = conn.execute("SELECT count(*) FROM customer_document_requests").fetchone()[0] + 1
        request_number = f"DOCREQ-{today_str}-{seq:04d}"

        conn.execute(
            """
            INSERT INTO customer_document_requests (
                id, request_number, customer_id, sales_order_id, shipment_id,
                document_category, message, status, fulfilled_document_id,
                staff_decision_notes, reviewed_by, reviewed_at, idempotency_key,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', NULL, NULL, NULL, NULL, ?, ?, ?, ?)
            """,
            (
                dreq_id,
                request_number,
                customer_id,
                so_id,
                target_shipment_id,
                cat,
                clean_message or None,
                effective_idemp,
                current_user.id,
                now_iso,
                now_iso,
            ),
        )

        conn.commit()

    record_collaboration_notification(
        "staff",
        "all_staff",
        "document_request_status",
        f"New Document Request {request_number}",
        f"Order {so['order_number']}: {cat}",
        "document_request",
        dreq_id,
    )

    record_erp_audit_log(
        "customer_document_request",
        dreq_id,
        "create_customer_document_request",
        {
            "request_number": request_number,
            "sales_order_id": so_id,
            "document_category": cat,
            "customer_id": customer_id,
        },
        performed_by=f"Customer:{current_user.username}",
    )

    return {
        "status": "open",
        "id": dreq_id,
        "request_id": dreq_id,
        "request_number": request_number,
        "category": cat,
        "document_category": cat,
        "sales_order_id": so_id,
    }


@router.get("/customer/document-requests")
def list_customer_document_requests_endpoint(
    status_filter: str | None = Query(None, alias="status"),
    so_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: AuthenticatedPortalUser = Depends(get_current_customer_user),
):
    """List document requests submitted by the authenticated customer."""
    customer_id = current_user.organization_id
    clauses = ["r.customer_id = ?"]
    params: list[Any] = [customer_id]

    if status_filter:
        clauses.append("r.status = ?")
        params.append(status_filter.strip().lower())
    if so_id:
        clauses.append("r.sales_order_id = ?")
        params.append(so_id.strip())

    where = f"WHERE {' AND '.join(clauses)}"
    with get_connection() as conn:
        count_row = conn.execute(f"SELECT count(*) FROM customer_document_requests r {where}", params).fetchone()
        total = count_row[0]

        rows = conn.execute(
            f"""
            SELECT r.*, so.order_number, d.original_filename as fulfilled_filename,
                   d.document_type as fulfilled_document_type, d.file_size as fulfilled_file_size
            FROM customer_document_requests r
            JOIN sales_orders so ON r.sales_order_id = so.id
            LEFT JOIN documents d ON r.fulfilled_document_id = d.id
            {where}
            ORDER BY r.created_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()

    return {"total": total, "items": [dict(r) for r in rows]}


@router.get("/customer/document-requests/{id}")
def get_customer_document_request_endpoint(
    id: str,
    current_user: AuthenticatedPortalUser = Depends(get_current_customer_user),
):
    """Retrieve details of an individual customer document request."""
    customer_id = current_user.organization_id
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT r.*, so.order_number, d.original_filename as fulfilled_filename,
                   d.document_type as fulfilled_document_type, d.file_size as fulfilled_file_size
            FROM customer_document_requests r
            JOIN sales_orders so ON r.sales_order_id = so.id
            LEFT JOIN documents d ON r.fulfilled_document_id = d.id
            WHERE r.id = ? AND r.customer_id = ?
            """,
            (id, customer_id),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Document request '{id}' not found.")

    return dict(row)


# ==========================================
# Phase 9C: Collaboration Notifications Endpoints
# ==========================================

@router.get("/customer/notifications")
def list_customer_notifications_endpoint(
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    current_user: AuthenticatedPortalUser = Depends(get_current_customer_user),
):
    """List in-app notifications for the customer."""
    customer_id = current_user.organization_id
    clauses = ["recipient_type = 'customer'", "recipient_id = ?"]
    params: list[Any] = [customer_id]

    if unread_only:
        clauses.append("is_read = 0")

    where = f"WHERE {' AND '.join(clauses)}"
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM collaboration_notifications
            {where}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params + [limit],
        ).fetchall()

    return {"total": len(rows), "items": [dict(r) for r in rows]}


@router.post("/customer/notifications/{id}/read")
def mark_customer_notification_read_endpoint(
    id: str,
    current_user: AuthenticatedPortalUser = Depends(get_current_customer_user),
):
    """Mark a customer notification as read."""
    customer_id = current_user.organization_id
    with get_connection() as conn:
        conn.execute(
            "UPDATE collaboration_notifications SET is_read = 1 WHERE id = ? AND recipient_type = 'customer' AND recipient_id = ?",
            (id, customer_id),
        )
        conn.commit()
    return {"status": "success", "id": id}


# ==========================================
# Phase 9C: Staff Review Console Endpoints
# ==========================================

@router.get("/admin/customer-threads")
def list_admin_customer_threads_endpoint(
    status_filter: str | None = Query(None, alias="status"),
    customer_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """List customer order threads across customers for authorized staff."""
    verify_staff_collaboration_access(current_user)
    clauses = ["1=1"]
    params: list[Any] = []

    if status_filter:
        clauses.append("t.status = ?")
        params.append(status_filter.strip().lower())
    if customer_id:
        clauses.append("t.customer_id = ?")
        params.append(customer_id.strip())

    where = f"WHERE {' AND '.join(clauses)}"
    with get_connection() as conn:
        count_row = conn.execute(f"SELECT count(*) FROM customer_order_threads t {where}", params).fetchone()
        total = count_row[0]

        rows = conn.execute(
            f"""
            SELECT t.*, so.order_number, c.name as customer_name,
                   (SELECT count(*) FROM customer_order_messages WHERE thread_id = t.id) as message_count
            FROM customer_order_threads t
            JOIN sales_orders so ON t.sales_order_id = so.id
            JOIN customers c ON t.customer_id = c.id
            {where}
            ORDER BY t.last_message_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()

    return {"total": total, "items": [dict(r) for r in rows]}


@router.get("/admin/customer-threads/{thread_id}")
def get_admin_customer_thread_detail_endpoint(
    thread_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Retrieve full thread details including staff internal notes."""
    verify_staff_collaboration_access(current_user)
    with get_connection() as conn:
        thread_row = conn.execute(
            """
            SELECT t.*, so.order_number, c.name as customer_name
            FROM customer_order_threads t
            JOIN sales_orders so ON t.sales_order_id = so.id
            JOIN customers c ON t.customer_id = c.id
            WHERE t.id = ?
            """,
            (thread_id,),
        ).fetchone()

        if not thread_row:
            raise HTTPException(status_code=404, detail=f"Thread '{thread_id}' not found.")

        messages = conn.execute(
            """
            SELECT id, thread_id, sender_type, sender_id, sender_name, message, is_internal_note, created_at
            FROM customer_order_messages
            WHERE thread_id = ?
            ORDER BY created_at ASC
            """,
            (thread_id,),
        ).fetchall()

    res = dict(thread_row)
    res["messages"] = [dict(m) for m in messages]
    return res


@router.post("/admin/customer-threads/{thread_id}/messages", status_code=status.HTTP_201_CREATED)
def post_admin_thread_message_endpoint(
    thread_id: str,
    req: StaffThreadMessageRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Post a staff reply or private internal note in a customer order thread."""
    verify_staff_collaboration_access(current_user)
    clean_message = sanitize_plain_text(req.message)
    if not clean_message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    now_iso = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        thread_row = conn.execute(
            "SELECT id, customer_id, sales_order_id FROM customer_order_threads WHERE id = ?",
            (thread_id,),
        ).fetchone()

        if not thread_row:
            raise HTTPException(status_code=404, detail=f"Thread '{thread_id}' not found.")

        msg_id = f"cmsg-{uuid.uuid4().hex[:10]}"
        conn.execute(
            """
            INSERT INTO customer_order_messages (
                id, thread_id, sender_type, sender_id, sender_name,
                message, is_internal_note, created_at
            ) VALUES (?, ?, 'staff', ?, ?, ?, ?, ?)
            """,
            (
                msg_id,
                thread_id,
                current_user.id,
                current_user.username,
                clean_message,
                1 if req.is_internal_note else 0,
                now_iso,
            ),
        )

        conn.execute(
            """
            UPDATE customer_order_threads
            SET last_message_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (now_iso, now_iso, thread_id),
        )

        conn.commit()

    # If this is not an internal note, notify the customer
    if not req.is_internal_note:
        record_collaboration_notification(
            "customer",
            thread_row["customer_id"],
            "staff_reply",
            "Staff replied to your inquiry",
            clean_message[:100],
            "thread",
            thread_id,
        )

    record_erp_audit_log(
        "customer_order_message",
        msg_id,
        "admin_post_order_message",
        {
            "thread_id": thread_id,
            "is_internal_note": req.is_internal_note,
        },
        performed_by=f"Staff:{current_user.username}",
    )

    return {
        "status": "success",
        "id": msg_id,
        "message_id": msg_id,
        "thread_id": thread_id,
        "is_internal_note": 1 if req.is_internal_note else 0,
    }


@router.post("/admin/customer-threads/{thread_id}/status")
def update_admin_thread_status_endpoint(
    thread_id: str,
    req: StaffThreadStatusRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Transition thread status and optionally update private staff notes."""
    verify_staff_collaboration_access(current_user)
    now_iso = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        thread_row = conn.execute(
            "SELECT id, status FROM customer_order_threads WHERE id = ?",
            (thread_id,),
        ).fetchone()

        if not thread_row:
            raise HTTPException(status_code=404, detail=f"Thread '{thread_id}' not found.")

        conn.execute(
            """
            UPDATE customer_order_threads
            SET status = ?, internal_notes = COALESCE(?, internal_notes), updated_at = ?
            WHERE id = ?
            """,
            (req.status, req.internal_notes, now_iso, thread_id),
        )

        conn.commit()

    record_erp_audit_log(
        "customer_order_thread",
        thread_id,
        "admin_update_thread_status",
        {"status": req.status, "previous_status": thread_row["status"]},
        performed_by=f"Staff:{current_user.username}",
    )

    return {"status": "success", "thread_id": thread_id, "status": req.status}


@router.get("/admin/customer-document-requests")
def list_admin_customer_document_requests_endpoint(
    status_filter: str | None = Query(None, alias="status"),
    customer_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """List customer document requests for staff review."""
    verify_staff_collaboration_access(current_user)
    clauses = ["1=1"]
    params: list[Any] = []

    if status_filter:
        clauses.append("r.status = ?")
        params.append(status_filter.strip().lower())
    if customer_id:
        clauses.append("r.customer_id = ?")
        params.append(customer_id.strip())

    where = f"WHERE {' AND '.join(clauses)}"
    with get_connection() as conn:
        count_row = conn.execute(f"SELECT count(*) FROM customer_document_requests r {where}", params).fetchone()
        total = count_row[0]

        rows = conn.execute(
            f"""
            SELECT r.*, so.order_number, c.name as customer_name,
                   d.original_filename as fulfilled_filename
            FROM customer_document_requests r
            JOIN sales_orders so ON r.sales_order_id = so.id
            JOIN customers c ON r.customer_id = c.id
            LEFT JOIN documents d ON r.fulfilled_document_id = d.id
            {where}
            ORDER BY r.created_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()

    return {"total": total, "items": [dict(r) for r in rows]}


@router.get("/admin/customer-document-requests/{id}")
def get_admin_customer_document_request_endpoint(
    id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Retrieve details of a customer document request for staff review."""
    verify_staff_collaboration_access(current_user)
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT r.*, so.order_number, c.name as customer_name,
                   d.original_filename as fulfilled_filename
            FROM customer_document_requests r
            JOIN sales_orders so ON r.sales_order_id = so.id
            JOIN customers c ON r.customer_id = c.id
            LEFT JOIN documents d ON r.fulfilled_document_id = d.id
            WHERE r.id = ?
            """,
            (id,),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Document request '{id}' not found.")

        # Also fetch list of eligible documents linked to this sales order or shipment
        eligible_docs = conn.execute(
            """
            SELECT id, original_filename, document_type, file_size, shared_with_customer, uploaded_at
            FROM documents
            WHERE sales_order_id = ? OR (shipment_id IS NOT NULL AND shipment_id = ?)
            ORDER BY uploaded_at DESC
            """,
            (row["sales_order_id"], row["shipment_id"]),
        ).fetchall()

    res = dict(row)
    res["eligible_documents"] = [dict(d) for d in eligible_docs]
    return res


@router.post("/admin/customer-document-requests/{id}/review")
def review_admin_customer_document_request_endpoint(
    id: str,
    req: StaffDocumentRequestReview,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Staff review action on a customer document request.
    - If 'fulfilled': requires a valid fulfilled_document_id linked to the order.
      Explicitly sets documents.shared_with_customer = 1.
    - If 'rejected': records decision notes and marks rejected.
    """
    verify_staff_collaboration_access(current_user)
    target_action = (req.action or req.status or "").lower()
    notes = req.decision_notes or req.review_notes
    ALLOWED_ACTIONS = {"open", "under_review", "fulfilled", "rejected"}
    if target_action not in ALLOWED_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Invalid action/status '{target_action}'. Must be one of: {sorted(ALLOWED_ACTIONS)}")

    now_iso = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        dreq = conn.execute(
            "SELECT * FROM customer_document_requests WHERE id = ?",
            (id,),
        ).fetchone()

        if not dreq:
            raise HTTPException(status_code=404, detail=f"Document request '{id}' not found.")

        current_status = dreq["status"]
        if current_status in ("fulfilled", "rejected") and target_action in ("open", "under_review"):
            raise HTTPException(status_code=400, detail="Invalid transition: finalized requests cannot be reopened.")

        if target_action == "fulfilled":
            if not req.fulfilled_document_id:
                raise HTTPException(
                    status_code=400,
                    detail="Fulfillment requires selecting an eligible document (fulfilled_document_id).",
                )

            # Verify document exists and belongs to the order/shipment
            doc = conn.execute(
                "SELECT id, sales_order_id, shipment_id FROM documents WHERE id = ?",
                (req.fulfilled_document_id,),
            ).fetchone()

            if not doc:
                raise HTTPException(status_code=404, detail=f"Document '{req.fulfilled_document_id}' not found.")

            # Explicitly share document with customer
            conn.execute(
                """
                UPDATE documents
                SET shared_with_customer = 1, shared_at = ?, shared_by = ?,
                    sales_order_id = COALESCE(sales_order_id, ?),
                    customer_id = COALESCE(customer_id, ?)
                WHERE id = ?
                """,
                (
                    now_iso,
                    current_user.username,
                    dreq["sales_order_id"],
                    dreq["customer_id"],
                    req.fulfilled_document_id,
                ),
            )

            conn.execute(
                """
                UPDATE customer_document_requests
                SET status = 'fulfilled', fulfilled_document_id = ?,
                    staff_decision_notes = ?, reviewed_by = ?, reviewed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    req.fulfilled_document_id,
                    notes,
                    current_user.username,
                    now_iso,
                    now_iso,
                    id,
                ),
            )

        elif target_action == "rejected":
            conn.execute(
                """
                UPDATE customer_document_requests
                SET status = 'rejected', staff_decision_notes = ?,
                    reviewed_by = ?, reviewed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (notes, current_user.username, now_iso, now_iso, id),
            )

        elif target_action == "under_review":
            conn.execute(
                """
                UPDATE customer_document_requests
                SET status = 'under_review', staff_decision_notes = COALESCE(?, staff_decision_notes),
                    reviewed_by = ?, reviewed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (notes, current_user.username, now_iso, now_iso, id),
            )

        conn.commit()

    if target_action == "fulfilled":
        record_collaboration_notification(
            "customer",
            dreq["customer_id"],
            "document_shared",
            "Your requested document is now available",
            f"Document request {dreq['request_number']} fulfilled.",
            "document",
            req.fulfilled_document_id,
        )
    elif target_action == "rejected":
        record_collaboration_notification(
            "customer",
            dreq["customer_id"],
            "document_request_status",
            f"Document request {dreq['request_number']} update",
            notes or "Your document request could not be fulfilled.",
            "document_request",
            id,
        )

    record_erp_audit_log(
        "customer_document_request",
        id,
        "admin_review_document_request",
        {
            "action": target_action,
            "fulfilled_document_id": req.fulfilled_document_id,
            "request_number": dreq["request_number"],
        },
        performed_by=f"Staff:{current_user.username}",
    )

    return {
        "status": target_action,
        "action": target_action,
        "id": id,
        "request_id": id,
        "fulfilled_document_id": req.fulfilled_document_id,
        "decision_notes": notes,
        "review_notes": notes,
    }


@router.post("/admin/documents/{doc_id}/share")
def update_admin_document_sharing_endpoint(
    doc_id: str,
    req: DocumentShareUpdateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Explicitly grant or revoke document sharing permissions for customer or supplier.
    Setting shared_with_customer = False immediately blocks subsequent customer downloads.
    """
    verify_staff_collaboration_access(current_user)
    now_iso = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        doc = conn.execute("SELECT id, shared_with_customer, shared_with_supplier FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if not doc:
            raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found.")

        updates = ["updated_at = ?"]
        params: list[Any] = [now_iso]

        if req.shared_with_customer is not None:
            updates.append("shared_with_customer = ?")
            params.append(1 if req.shared_with_customer else 0)
        if req.shared_with_supplier is not None:
            updates.append("shared_with_supplier = ?")
            params.append(1 if req.shared_with_supplier else 0)
        if req.sharing_notes is not None:
            updates.append("sharing_notes = ?")
            params.append(req.sharing_notes.strip())

        updates.append("shared_at = ?")
        params.append(now_iso)
        updates.append("shared_by = ?")
        params.append(current_user.username)

        params.append(doc_id)
        conn.execute(
            f"UPDATE documents SET {', '.join(updates)} WHERE id = ?",
            params,
        )

        conn.commit()

    record_erp_audit_log(
        "document",
        doc_id,
        "admin_update_document_sharing",
        {
            "shared_with_customer": req.shared_with_customer,
            "shared_with_supplier": req.shared_with_supplier,
        },
        performed_by=f"Staff:{current_user.username}",
    )

    return {
        "status": "success",
        "doc_id": doc_id,
        "shared_with_customer": req.shared_with_customer,
        "shared_with_supplier": req.shared_with_supplier,
    }


@router.get("/admin/notifications")
def list_admin_notifications_endpoint(
    limit: int = Query(50, ge=1, le=100),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """List collaboration notifications for staff."""
    verify_staff_collaboration_access(current_user)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM collaboration_notifications
            WHERE recipient_type = 'staff'
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return {"total": len(rows), "items": [dict(r) for r in rows]}


@router.get("/admin/notifications/monitoring")
def get_notification_monitoring_endpoint(
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Operational monitoring dashboard metrics for notification delivery queues."""
    verify_staff_collaboration_access(current_user)
    return get_notification_monitoring_metrics()


@router.get("/admin/health/summary")
def get_operational_health_summary_endpoint(
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Authorized operational health summary for internal management and operators.
    Aggregates database status, storage metrics, notification queues, and backup status.
    """
    verify_staff_collaboration_access(current_user)

    db_metrics = {"status": "connected", "integrity": "ok", "applied_migrations": 0}
    try:
        with get_connection() as conn:
            cur = conn.execute("PRAGMA quick_check")
            row = cur.fetchone()
            db_metrics["integrity"] = row[0] if row else "ok"
            try:
                cnt = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()
                db_metrics["applied_migrations"] = cnt[0] if cnt else 0
            except Exception:
                db_metrics["applied_migrations"] = 0
    except Exception as exc:
        db_metrics["status"] = f"unhealthy: {type(exc).__name__}"

    storage_metrics = {"status": "writable", "document_files": 0}
    try:
        s_dir = get_storage_dir()
        if s_dir.is_dir():
            storage_metrics["document_files"] = len([f for f in s_dir.rglob("*") if f.is_file()])
        else:
            storage_metrics["status"] = "unavailable"
    except Exception as exc:
        storage_metrics["status"] = f"error: {type(exc).__name__}"

    notif_metrics = get_notification_monitoring_metrics()

    backup_metrics = {"status": "available", "total_backups": 0, "latest_backup_id": None}
    try:
        from .backup import list_backups
        backups = list_backups()
        backup_metrics["total_backups"] = len(backups)
        if backups:
            backup_metrics["latest_backup_id"] = backups[0].get("backup_id")
    except Exception:
        pass

    return {
        "status": "healthy" if db_metrics["status"] == "connected" and storage_metrics["status"] == "writable" else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": db_metrics,
        "storage": storage_metrics,
        "notifications": notif_metrics,
        "backups": backup_metrics,
    }


@router.post("/admin/notifications/{notification_id}/retry")
def retry_notification_endpoint(
    notification_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Reset an exhausted or failed notification delivery to pending for reprocessing."""
    verify_staff_collaboration_access(current_user)
    result = retry_failed_notification(notification_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "Notification not found"))

    record_erp_audit_log(
        "notification",
        notification_id,
        "admin_retry_notification",
        {"notification_id": notification_id},
        performed_by=f"Staff:{current_user.username}",
    )
    return result


@router.post("/admin/notifications/process-queue")
def process_notification_queue_endpoint(
    req: ProcessDeliveriesRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Manually or worker-triggered delivery queue execution for pending notifications."""
    verify_staff_collaboration_access(current_user)
    stats = process_notification_deliveries(
        batch_size=req.batch_size,
        worker_id=req.worker_id,
    )
    return {"status": "success", "processed_stats": stats}


# ------------------------------------------
# User Notification Preferences Endpoints
# ------------------------------------------

@router.get("/user/preferences")
def get_portal_user_preferences_endpoint(
    current_user: AuthenticatedPortalUser = Depends(get_current_portal_user),
):
    """Retrieve notification preferences for the authenticated portal user."""
    return get_user_notification_preferences(current_user.id)


@router.put("/user/preferences")
def update_portal_user_preferences_endpoint(
    req: UserNotificationPreferencesRequest,
    current_user: AuthenticatedPortalUser = Depends(get_current_portal_user),
):
    """Update notification preferences for the authenticated portal user."""
    res = set_user_notification_preferences(
        user_id=current_user.id,
        email_notifications_enabled=req.email_notifications_enabled,
    )
    record_erp_audit_log(
        "portal_user_preferences",
        current_user.id,
        "update_notification_preferences",
        {"email_notifications_enabled": req.email_notifications_enabled},
        performed_by=f"{current_user.account_type.capitalize()}:{current_user.username}",
    )
    return res


# ------------------------------------------
# Secure Document Retrieval Endpoint
# ------------------------------------------

@router.get("/documents/{document_id}/download")
def portal_download_document_endpoint(
    document_id: str,
    current_user: AuthenticatedPortalUser = Depends(get_current_portal_user),
):
    """
    Download a document verifying tenancy ownership and explicit sharing policy.
    - Customer users require shared_with_customer = 1 AND authoritative ownership of linked sales order or shipment.
    - Supplier users require shared_with_supplier = 1 AND authoritative ownership of linked purchase order.
    - Prevents path traversal and leaks zero absolute storage paths.
    """
    with get_connection() as conn:
        doc = conn.execute(
            """
            SELECT id, shipment_id, sales_order_id, original_filename, clean_filename,
                   storage_key, shared_with_customer, shared_with_supplier,
                   po_id, asn_id, supplier_id, customer_id
            FROM documents
            WHERE id = ?
            """,
            (document_id,),
        ).fetchone()

        if not doc:
            raise HTTPException(status_code=404, detail="Document not found.")

        # 1. Tenancy Authorization Check
        is_authorized = False
        org_id = current_user.organization_id
        doc_dict = dict(doc)

        if current_user.account_type == "customer":
            if doc_dict.get("shared_with_customer") == 1:
                # If explicit customer_id is recorded, verify ownership directly
                if doc_dict.get("customer_id"):
                    if doc_dict["customer_id"] == org_id:
                        is_authorized = True
                # Check linked sales order
                elif doc_dict.get("sales_order_id"):
                    so_chk = conn.execute(
                        "SELECT customer_id FROM sales_orders WHERE id = ?",
                        (doc_dict["sales_order_id"],),
                    ).fetchone()
                    if so_chk and so_chk["customer_id"] == org_id:
                        is_authorized = True

                # Check linked shipment
                elif doc_dict.get("shipment_id"):
                    shp_chk = conn.execute(
                        """
                        SELECT s.customer_id, so.customer_id as so_cust
                        FROM shipments s
                        LEFT JOIN sales_orders so ON s.id = so.shipment_id
                        WHERE s.id = ?
                        """,
                        (doc_dict["shipment_id"],),
                    ).fetchall()
                    for r in shp_chk:
                        if r["customer_id"] == org_id or r["so_cust"] == org_id:
                            is_authorized = True
                            break

        elif current_user.account_type == "supplier":
            if doc_dict.get("shared_with_supplier") == 1:
                # If explicit supplier_id is recorded, strictly verify ownership
                if doc_dict.get("supplier_id"):
                    if doc_dict["supplier_id"] == org_id:
                        is_authorized = True
                elif doc_dict.get("po_id"):
                    po_chk = conn.execute(
                        "SELECT id FROM purchase_orders WHERE id = ? AND supplier_id = ?",
                        (doc_dict["po_id"], org_id),
                    ).fetchone()
                    if po_chk:
                        is_authorized = True
                elif doc_dict.get("asn_id"):
                    asn_chk = conn.execute(
                        "SELECT id FROM supplier_asns WHERE id = ? AND supplier_id = ?",
                        (doc_dict["asn_id"], org_id),
                    ).fetchone()
                    if asn_chk:
                        is_authorized = True
                elif doc_dict.get("shipment_id"):
                    po_chk = conn.execute(
                        "SELECT id FROM purchase_orders WHERE (id = ? OR shipment_id = ?) AND supplier_id = ?",
                        (doc_dict["shipment_id"], doc_dict["shipment_id"], org_id),
                    ).fetchone()
                    if po_chk:
                        is_authorized = True

        if not is_authorized:
            # Deny by default: 404 to avoid leaking existence of confidential document
            raise HTTPException(
                status_code=404,
                detail="Document not found or access not authorized for this account.",
            )

    # 2. File Path Resolution with Traversal Protection
    file_path = get_document_file_path(doc["storage_key"])
    if not file_path or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Document file not available in storage.")

    # 3. Secret-safe audit trail
    record_erp_audit_log(
        "document",
        document_id,
        "portal_download_document",
        {
            "portal_username": current_user.username,
            "organization_id": current_user.organization_id,
            "account_type": current_user.account_type,
        },
        performed_by=f"Portal:{current_user.username}",
    )

    return FileResponse(
        path=file_path,
        filename=doc["clean_filename"] or doc["original_filename"],
        media_type="application/octet-stream",
    )
