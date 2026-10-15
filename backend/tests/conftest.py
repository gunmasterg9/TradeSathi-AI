"""TradeSathi AI — Global Test Configuration & Test Isolation Fixtures
Guarantees that EVERY test in backend/tests runs against an isolated,
temporary SQLite database and temporary document storage directory.
Zero tests are allowed to read or write to live database or storage paths.
"""

import os
from pathlib import Path
import sys
import pytest
from fastapi.testclient import TestClient

# Ensure both workspace root and backend directory are in sys.path
_ws_root = str(Path(__file__).resolve().parent.parent.parent)
_backend_dir = str(Path(__file__).resolve().parent.parent)
if _ws_root not in sys.path:
    sys.path.insert(0, _ws_root)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from app.db import get_db_path, init_db, set_db_path
from app.main import app
from app.storage import get_storage_dir, set_storage_dir


@pytest.fixture(autouse=True)
def isolated_test_environment(tmp_path):
    """
    Autouse fixture that runs before and after every test in the suite.
    Enforces that an isolated temporary SQLite database and temporary
    document directory are created, initialized, and pointed to.
    Restores original environment and paths on teardown.
    """
    prev_db = get_db_path()
    prev_env_db = os.getenv("TRADESATHI_DB_PATH")
    prev_env_storage = os.getenv("TRADESATHI_STORAGE_PATH")
    prev_test_mode = os.getenv("TRADESATHI_TEST_MODE")
    prev_simulator = os.getenv("TRADESATHI_TEST_ROLE_SIMULATOR")

    test_db = tmp_path / "test_tradesathi.db"
    test_storage = tmp_path / "test_documents"
    test_storage.mkdir(parents=True, exist_ok=True)

    os.environ["TRADESATHI_TEST_MODE"] = "1"
    os.environ["TRADESATHI_DB_PATH"] = str(test_db)
    os.environ["TRADESATHI_STORAGE_PATH"] = str(test_storage)
    os.environ["TRADESATHI_TEST_ROLE_SIMULATOR"] = "1"

    set_db_path(test_db)
    set_storage_dir(test_storage)
    init_db(test_db)

    try:
        yield {
            "db_path": test_db,
            "storage_dir": test_storage,
        }
    finally:
        set_db_path(prev_db)

        if prev_simulator is not None:
            os.environ["TRADESATHI_TEST_ROLE_SIMULATOR"] = prev_simulator
        else:
            os.environ.pop("TRADESATHI_TEST_ROLE_SIMULATOR", None)

        if prev_env_storage:
            set_storage_dir(Path(prev_env_storage))
            os.environ["TRADESATHI_STORAGE_PATH"] = prev_env_storage
        else:
            os.environ.pop("TRADESATHI_STORAGE_PATH", None)

        if prev_env_db:
            os.environ["TRADESATHI_DB_PATH"] = prev_env_db
        else:
            os.environ.pop("TRADESATHI_DB_PATH", None)

        if prev_test_mode:
            os.environ["TRADESATHI_TEST_MODE"] = prev_test_mode
        else:
            os.environ.pop("TRADESATHI_TEST_MODE", None)


@pytest.fixture
def client():
    """Pre-configured TestClient running within the isolated test environment."""
    return TestClient(app)
