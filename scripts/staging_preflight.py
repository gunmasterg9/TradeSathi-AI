"""TradeSathi AI — Staging Environment Preflight & Isolation Verification Engine.
Validates strict separation of staging database, storage, backups, and credentials
from live assets before application startup.
"""
import hashlib
import os
import sqlite3
import sys
from pathlib import Path


def run_preflight() -> dict:
    print("=" * 70)
    print("TRADESATHI AI — STAGING ENVIRONMENT PREFLIGHT ISOLATION AUDIT")
    print("=" * 70)

    # 1. Resolve live vs staging paths
    repo_root = Path(__file__).resolve().parent.parent
    live_db = (repo_root / "backend" / "tradesathi.db").resolve()
    live_storage = (repo_root / "backend" / "storage" / "documents").resolve()
    live_backup = (repo_root / "backend" / "backups").resolve()

    staging_dir = (repo_root / "staging_data").resolve()
    staging_db = (staging_dir / "tradesathi_staging.db").resolve()
    staging_storage = (staging_dir / "storage" / "documents").resolve()
    staging_backup = (staging_dir / "backups").resolve()
    staging_recovery = (staging_dir / "recovery_target").resolve()

    print(f"Live Database Path:        {live_db}")
    print(f"Staging Database Path:     {staging_db}")
    print(f"Live Storage Path:         {live_storage}")
    print(f"Staging Storage Path:      {staging_storage}")
    print(f"Live Backup Root:          {live_backup}")
    print(f"Staging Backup Root:       {staging_backup}")
    print(f"Staging Recovery Target:   {staging_recovery}")

    # Ensure staging directories exist
    staging_dir.mkdir(parents=True, exist_ok=True)
    staging_storage.mkdir(parents=True, exist_ok=True)
    staging_backup.mkdir(parents=True, exist_ok=True)
    staging_recovery.mkdir(parents=True, exist_ok=True)

    # 2. Strict non-aliasing assertions
    assert staging_db != live_db, "CRITICAL ISOLATION FAILURE: Staging DB resolves to Live DB!"
    assert staging_storage != live_storage, "CRITICAL ISOLATION FAILURE: Staging storage resolves to Live storage!"
    assert staging_backup != live_backup, "CRITICAL ISOLATION FAILURE: Staging backup resolves to Live backup!"
    assert staging_db.parent == staging_dir, "Staging DB must reside inside staging_data directory"
    print("Data directory non-aliasing checks: PASSED")

    # 3. Live Baseline Recording
    if not live_db.is_file():
        raise FileNotFoundError(f"Live database not found at {live_db}")

    live_hash = hashlib.sha256(live_db.read_bytes()).hexdigest()
    live_size = live_db.stat().st_size
    live_files = len([f for f in live_storage.rglob("*") if f.is_file()]) if live_storage.is_dir() else 0

    print(f"Live DB Checksum:          {live_hash}")
    print(f"Live DB Size:              {live_size} bytes")
    print(f"Live Document Count:       {live_files} files")

    # 4. Staging Configuration Validation
    env_file = staging_dir / "staging.env"
    if not env_file.is_file():
        raise FileNotFoundError(f"Staging env file missing: {env_file}")

    env_content = env_file.read_text(encoding="utf-8")
    env_vars = {}
    for line in env_content.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()

    assert env_vars.get("ENVIRONMENT") == "staging", "ENVIRONMENT must be 'staging'"
    assert env_vars.get("TRADESATHI_TEST_ROLE_SIMULATOR") == "0", "Role simulator must be '0' in staging"
    assert "*" not in env_vars.get("CORS_ORIGINS", ""), "CORS_ORIGINS cannot contain wildcards"
    secret = env_vars.get("TRADESATHI_SECRET_KEY", "")
    assert len(secret) >= 32, "TRADESATHI_SECRET_KEY must be >= 32 characters"
    assert secret not in ("secret", "changeme", "admin", "password", "tradesathi"), "Insecure secret detected"
    print("Staging configuration parameters: PASSED")

    print("=" * 70)
    print("PREFLIGHT ISOLATION CHECKS COMPLETE: ALL PASSED")
    print("=" * 70)

    return {
        "live_db": str(live_db),
        "live_hash": live_hash,
        "live_size": live_size,
        "live_files": live_files,
        "staging_db": str(staging_db),
        "staging_storage": str(staging_storage),
        "staging_backup": str(staging_backup),
    }


if __name__ == "__main__":
    run_preflight()
