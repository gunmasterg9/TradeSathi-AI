import hashlib
import hmac
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from .db import get_connection, is_test_environment


# ==========================================
# Password Hashing & Verification (scrypt)
# ==========================================

def hash_password(password: str) -> str:
    """Hash password using memory-hard scrypt KDF with cryptographically random salt."""
    if not password or len(password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters long."
        )
    salt = secrets.token_bytes(16)
    hash_bytes = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=16384,
        r=8,
        p=1,
    )
    return f"scrypt$16384$8$1${salt.hex()}${hash_bytes.hex()}"


def verify_password(password: str, hashed_password: str) -> bool:
    """Verify password against scrypt hash in timing-safe manner."""
    if not password or not hashed_password:
        return False
    parts = hashed_password.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return False
    try:
        n = int(parts[1])
        r = int(parts[2])
        p = int(parts[3])
        salt = bytes.fromhex(parts[4])
        expected_hash = bytes.fromhex(parts[5])

        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
        )
        return hmac.compare_digest(derived, expected_hash)
    except Exception:
        return False


# ==========================================
# Token Management (Opaque SHA-256 Bearer)
# ==========================================

def hash_token(raw_token: str) -> str:
    """Compute deterministic SHA-256 hash of raw bearer token for database storage."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_user_token(user_id: str, expires_in_seconds: int = 28800) -> tuple[str, str]:
    """Generate a high-entropy 256-bit bearer token and store its hash in user_tokens."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_token(raw_token)
    token_id = f"tok-{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(seconds=expires_in_seconds)).isoformat()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_tokens (token_id, user_id, token_hash, expires_at, revoked, created_at)
            VALUES (?, ?, ?, ?, 0, ?)
            """,
            (token_id, user_id, token_hash, expires_at, now.isoformat()),
        )
        conn.commit()

    return raw_token, expires_at


def revoke_token_by_raw(raw_token: str) -> bool:
    """Mark a bearer token as revoked in the database."""
    token_hash = hash_token(raw_token)
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE user_tokens SET revoked = 1 WHERE token_hash = ?",
            (token_hash,),
        )
        conn.commit()
        return cursor.rowcount > 0


# ==========================================
# User Repository
# ==========================================

def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, username, email, role, is_active, created_at, updated_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def get_user_by_username(username: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, username, email, password_hash, role, is_active, created_at, updated_at FROM users WHERE LOWER(username) = LOWER(?)",
            (username.strip(),),
        ).fetchone()
        return dict(row) if row else None


def create_user_record(data: dict[str, Any], performed_by: str = "system") -> dict[str, Any]:
    username = data["username"].strip()
    email = data.get("email", f"{username.lower()}@tradesathi.local").strip()
    role = data.get("role", "viewer").strip().lower()
    valid_roles = {"admin", "sales", "warehouse", "procurement", "viewer"}
    if role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role '{role}'. Must be one of: {sorted(valid_roles)}")

    password_hash = hash_password(data["password"])
    user_id = f"usr-{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        # Check uniqueness
        chk = conn.execute(
            "SELECT id FROM users WHERE LOWER(username) = LOWER(?) OR LOWER(email) = LOWER(?)",
            (username, email),
        ).fetchone()
        if chk:
            raise HTTPException(status_code=409, detail=f"User with username '{username}' or email '{email}' already exists.")

        conn.execute(
            """
            INSERT INTO users (id, username, email, password_hash, role, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (user_id, username, email, password_hash, role, now, now),
        )
        conn.commit()

    # Record audit log without credentials
    try:
        from .master_data import record_erp_audit_log
        record_erp_audit_log("user", user_id, "create", {"username": username, "role": role}, performed_by)
    except Exception:
        pass

    user = get_user_by_id(user_id)
    assert user is not None
    return user


def count_admin_users() -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT count(*) FROM users WHERE role = 'admin' AND is_active = 1").fetchone()
        return row[0] if row else 0


def provision_initial_admin(username: str, password: str, email: str | None = None) -> dict[str, Any]:
    """Secure procedure to create the first administrator. Fails permanently if an admin already exists."""
    username_clean = username.strip()
    email_clean = (email or f"{username_clean.lower()}@tradesathi.local").strip()
    password_hash = hash_password(password)
    user_id = f"usr-{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT count(*) FROM users WHERE role = 'admin' AND is_active = 1").fetchone()
        existing_admins = row[0] if row else 0
        if existing_admins > 0:
            raise HTTPException(
                status_code=403,
                detail="Initial admin provisioning is permanently locked. An active administrator account already exists."
            )

        # Check uniqueness
        chk = conn.execute(
            "SELECT id FROM users WHERE LOWER(username) = LOWER(?) OR LOWER(email) = LOWER(?)",
            (username_clean, email_clean),
        ).fetchone()
        if chk:
            raise HTTPException(status_code=409, detail=f"User with username '{username_clean}' or email '{email_clean}' already exists.")

        conn.execute(
            """
            INSERT INTO users (id, username, email, password_hash, role, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'admin', 1, ?, ?)
            """,
            (user_id, username_clean, email_clean, password_hash, now, now),
        )
        conn.commit()

    try:
        from .master_data import record_erp_audit_log
        record_erp_audit_log("user", user_id, "provision_initial_admin", {"username": username_clean, "role": "admin"}, "Initial Setup")
    except Exception:
        pass

    user = get_user_by_id(user_id)
    assert user is not None
    return user


# ==========================================
# FastAPI Authentication Dependency (SEC-01)
# ==========================================

class AuthenticatedUser(BaseModel):
    id: str
    username: str
    email: str
    role: str
    is_active: bool = True


async def get_current_user(
    authorization: str | None = Header(None, alias="Authorization"),
    x_user_role: str | None = Header(None, alias="X-User-Role"),
    x_user_name: str | None = Header(None, alias="X-User-Name"),
    x_user_email: str | None = Header(None, alias="X-User-Email"),
) -> AuthenticatedUser:
    """
    Authenticate caller using Bearer token verified against server-side session store.
    Strictly resolves user role and identity from database records, NOT client headers.
    """
    # 1. Standard Bearer Token Flow
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization[len("Bearer "):].strip()
        if raw_token:
            token_hash = hash_token(raw_token)
            with get_connection() as conn:
                row = conn.execute(
                    """
                    SELECT u.id, u.username, u.email, u.role, u.is_active, t.expires_at, t.revoked
                    FROM user_tokens t
                    JOIN users u ON t.user_id = u.id
                    WHERE t.token_hash = ?
                    """,
                    (token_hash,),
                ).fetchone()

            if not row:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or unrecognized authentication token.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            if row["revoked"] == 1:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication token has been revoked.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            now_iso = datetime.now(timezone.utc).isoformat()
            if row["expires_at"] < now_iso:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication token has expired. Please log in again.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            if row["is_active"] != 1:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User account is deactivated. Contact an administrator.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            return AuthenticatedUser(
                id=row["id"],
                username=row["username"],
                email=row["email"],
                role=row["role"],
                is_active=True,
            )

    # 2. Test Environment Backward Compatibility
    # Allowed ONLY when explicitly running in test mode AND TRADESATHI_TEST_ROLE_SIMULATOR is set.
    # In normal production execution, this path is completely unreachable and fails closed.
    env = (os.getenv("ENVIRONMENT") or os.getenv("TRADESATHI_ENV") or "").lower()
    if env not in ("production", "staging") and is_test_environment() and os.getenv("TRADESATHI_TEST_ROLE_SIMULATOR") == "1":
        effective_role = (x_user_role or "viewer").strip().lower()
        effective_name = (x_user_name or "Test Operator").strip()
        effective_email = (x_user_email or f"{effective_role}@test.local").strip()
        return AuthenticatedUser(
            id=f"usr-{effective_name.lower().replace(' ', '-')}",
            username=effective_name,
            email=effective_email,
            role=effective_role,
            is_active=True,
        )

    # 3. Fail Closed (Unauthenticated)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Please provide a valid 'Authorization: Bearer <token>' header.",
        headers={"WWW-Authenticate": "Bearer"},
    )


# ==========================================
# Pydantic Schemas for Auth API
# ==========================================

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: str
    user: dict[str, Any]


class AdminProvisionRequest(BaseModel):
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=8)
    email: str | None = None


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=8)
    email: str | None = None
    role: str = Field("viewer")


class UserUpdateRequest(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None


# ==========================================
# Auth API Router
# ==========================================

from .rate_limiter import auth_rate_limiter

auth_router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@auth_router.post("/login", response_model=LoginResponse, dependencies=[Depends(auth_rate_limiter)])
def login_endpoint(req: LoginRequest):
    """Authenticate user with username and password, issuing an opaque bearer token."""
    user = get_user_by_username(req.username)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user["is_active"] != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated.",
        )

    raw_token, expires_at = create_user_token(user["id"])
    return {
        "access_token": raw_token,
        "token_type": "bearer",
        "expires_at": expires_at,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "role": user["role"],
        },
    }


@auth_router.post("/logout")
def logout_endpoint(
    authorization: str | None = Header(None, alias="Authorization"),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Revoke the caller's active bearer token."""
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization[len("Bearer "):].strip()
        revoke_token_by_raw(raw_token)
    return {"detail": "Successfully logged out. Token revoked."}


@auth_router.get("/me")
def get_me_endpoint(current_user: AuthenticatedUser = Depends(get_current_user)):
    """Return currently authenticated user identity and resolved role."""
    return current_user.model_dump()


@auth_router.post("/provision-admin", status_code=201)
def provision_admin_endpoint(req: AdminProvisionRequest):
    """Secure procedure to set up initial admin. Permanently locked once an admin exists."""
    return provision_initial_admin(req.username, req.password, req.email)


@auth_router.get("/users")
def list_users_endpoint(current_user: AuthenticatedUser = Depends(get_current_user)):
    """List all registered users (admin only)."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only administrators can list users.")
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, username, email, role, is_active, created_at, updated_at FROM users ORDER BY created_at ASC"
        ).fetchall()
        return {"total": len(rows), "items": [dict(r) for r in rows]}


@auth_router.post("/users", status_code=201)
def create_user_endpoint(
    req: UserCreateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Create a new user with assigned role (admin only)."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only administrators can create users.")
    return create_user_record(req.model_dump(), performed_by=current_user.username)


@auth_router.patch("/users/{user_id}")
def update_user_endpoint(
    user_id: str,
    req: UserUpdateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Update role, status, or password of an existing user (admin only)."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only administrators can modify users.")

    existing = get_user_by_id(user_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"User with ID '{user_id}' not found.")

    set_clauses = []
    params = []
    now = datetime.now(timezone.utc).isoformat()

    if req.role is not None:
        valid_roles = {"admin", "sales", "warehouse", "procurement", "viewer"}
        role = req.role.strip().lower()
        if role not in valid_roles:
            raise HTTPException(status_code=400, detail=f"Invalid role '{role}'.")
        set_clauses.append("role = ?")
        params.append(role)

    if req.is_active is not None:
        set_clauses.append("is_active = ?")
        params.append(1 if req.is_active else 0)

    if req.password is not None:
        pw_hash = hash_password(req.password)
        set_clauses.append("password_hash = ?")
        params.append(pw_hash)

    if not set_clauses:
        return existing

    set_clauses.append("updated_at = ?")
    params.append(now)
    params.append(user_id)

    with get_connection() as conn:
        conn.execute(f"UPDATE users SET {', '.join(set_clauses)} WHERE id = ?", params)
        # If user deactivated OR password changed, revoke all their active tokens immediately
        if req.is_active is False or req.password is not None:
            conn.execute("UPDATE user_tokens SET revoked = 1 WHERE user_id = ?", (user_id,))
        conn.commit()

    return get_user_by_id(user_id)
