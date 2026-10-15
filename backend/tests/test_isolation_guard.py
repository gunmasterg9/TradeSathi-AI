"""TradeSathi AI — Data Isolation Guard and Live Path Safety Verification Tests
Verifies that:
1. The runtime isolation guard raises RuntimeError if any test attempts to connect to LIVE database.
2. The runtime isolation guard raises RuntimeError if any test attempts to access LIVE storage.
3. The global conftest fixture successfully isolates database and storage for every test.
4. Record creation in tests does not affect live database records, size, or timestamps.
"""

import os
import sqlite3
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.db import (
    LIVE_DB_PATH,
    create_shipment,
    get_connection,
    get_db_path,
    get_shipment_by_id,
    list_shipments,
    set_db_path,
)
from app.main import app
from app.storage import (
    LIVE_STORAGE_DIR,
    get_storage_dir,
    save_document_file,
    set_storage_dir,
)


def test_guard_blocks_live_database_connection():
    """Attempting to open a connection to the live database during testing MUST raise RuntimeError."""
    with pytest.raises(RuntimeError, match="CRITICAL TEST ISOLATION FAILURE.*LIVE database"):
        get_connection(LIVE_DB_PATH)


def test_guard_blocks_live_storage_access():
    """Attempting to access the live document storage during testing MUST raise RuntimeError."""
    current_storage = get_storage_dir()
    try:
        set_storage_dir(LIVE_STORAGE_DIR)
        with pytest.raises(RuntimeError, match="CRITICAL TEST ISOLATION FAILURE.*LIVE document storage"):
            get_storage_dir()
    finally:
        set_storage_dir(current_storage)


def test_active_environment_is_strictly_isolated(isolated_test_environment):
    """The active test paths must be strictly distinct from live paths and exist in temp directory."""
    active_db = get_db_path().resolve()
    active_storage = get_storage_dir().resolve()

    assert active_db != LIVE_DB_PATH
    assert active_storage != LIVE_STORAGE_DIR
    assert "test_tradesathi.db" in str(active_db)
    assert active_db.exists()
    assert active_storage.exists()


def test_write_operations_do_not_touch_live_database(isolated_test_environment):
    """Creating shipments and documents in tests must NOT write to or alter the live database."""
    # Capture live DB state before test write
    assert LIVE_DB_PATH.exists()
    live_stat_before = LIVE_DB_PATH.stat()
    
    conn_ro = sqlite3.connect(f"file:{LIVE_DB_PATH}?mode=ro", uri=True)
    cur = conn_ro.cursor()
    cur.execute("SELECT count(*) FROM shipments")
    live_shipment_count_before = cur.fetchone()[0]
    conn_ro.close()

    # Perform writes using app logic in test environment
    client = TestClient(app)
    resp = client.post("/api/shipments", json={
        "reference": "SHP-ISOLATION-VERIFIED-001",
        "exporter": "Safety Test Exporter",
        "buyer": "Safety Test Buyer",
    })
    assert resp.status_code == 201
    created = resp.json()
    assert created["reference"] == "SHP-ISOLATION-VERIFIED-001"

    # Verify write exists in isolated test DB
    test_shipments = list_shipments()
    assert len(test_shipments) == 1
    assert test_shipments[0]["reference"] == "SHP-ISOLATION-VERIFIED-001"

    # Verify live database remains 100% UNTOUCHED
    live_stat_after = LIVE_DB_PATH.stat()
    assert live_stat_after.st_size == live_stat_before.st_size
    assert live_stat_after.st_mtime == live_stat_before.st_mtime

    conn_ro = sqlite3.connect(f"file:{LIVE_DB_PATH}?mode=ro", uri=True)
    cur = conn_ro.cursor()
    cur.execute("SELECT count(*) FROM shipments")
    live_shipment_count_after = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM shipments WHERE reference = 'SHP-ISOLATION-VERIFIED-001'")
    test_ref_in_live = cur.fetchone()[0]
    conn_ro.close()

    assert live_shipment_count_after == live_shipment_count_before
    assert test_ref_in_live == 0, "Test record leaked into live database!"
