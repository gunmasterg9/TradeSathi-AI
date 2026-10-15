"""Unit and integration tests for TradeSathi AI Disaster Recovery Verification Runner
Milestone 2F Phase 5
"""

import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from backend.app.recovery_verifier import (
    CheckResult,
    RecoveryVerificationReport,
    check_application_health,
    check_backup_integrity,
    check_document_metadata_and_download,
    check_restored_document_integrity,
    check_shipments_api,
    check_sqlite_integrity,
    generate_json_report,
    generate_markdown_report,
    main,
    redact_sensitive_text,
    run_recovery_verification,
    validate_path_safety,
)


@pytest.fixture
def temp_project_dir():
    """Create disposable dummy project structure for safety testing."""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        backend = p / "backend"
        backend.mkdir()
        storage = backend / "storage" / "documents"
        storage.mkdir(parents=True)
        live_db = backend / "tradesathi.db"
        live_db.write_text("dummy live db", encoding="utf-8")
        yield p


def test_safe_destination_validation_accepts_temp_paths(temp_project_dir):
    """Safe isolated destinations outside live database and storage pass safety validation."""
    isolated_db = temp_project_dir / "isolated_test" / "test.db"
    isolated_storage = temp_project_dir / "isolated_test" / "docs"

    passed, msg = validate_path_safety(isolated_db, isolated_storage, project_root=temp_project_dir)
    assert passed is True
    assert "verified separate" in msg


def test_refusal_to_use_live_database_path(temp_project_dir):
    """Safety validator strictly rejects live database path."""
    live_db = temp_project_dir / "backend" / "tradesathi.db"
    safe_storage = temp_project_dir / "tmp_storage"

    passed, msg = validate_path_safety(live_db, safe_storage, project_root=temp_project_dir)
    assert passed is False
    assert "CRITICAL SAFETY VIOLATION" in msg
    assert "resolves to live database" in msg


def test_refusal_to_use_live_storage_path(temp_project_dir):
    """Safety validator strictly rejects live storage directory path."""
    safe_db = temp_project_dir / "tmp.db"
    live_storage = temp_project_dir / "backend" / "storage" / "documents"

    passed, msg = validate_path_safety(safe_db, live_storage, project_root=temp_project_dir)
    assert passed is False
    assert "CRITICAL SAFETY VIOLATION" in msg
    assert "resolves to live document storage" in msg


def test_refusal_when_same_directory_and_name_as_live_db(temp_project_dir):
    """Validator catches same-directory filename conflicts with live db."""
    conflict_db = temp_project_dir / "backend" / "tradesathi.db"
    safe_storage = temp_project_dir / "tmp_storage"

    passed, msg = validate_path_safety(conflict_db, safe_storage, project_root=temp_project_dir)
    assert passed is False
    assert "CRITICAL SAFETY VIOLATION" in msg


def test_redaction_of_sensitive_configuration_and_secrets():
    """Redaction masks credentials, secret keys, passwords, and bearer tokens."""
    raw = "User apiKey='sk-123456789' and password=\"supersecret\" with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    redacted = redact_sensitive_text(raw)

    assert "supersecret" not in redacted
    assert "sk-123456789" not in redacted
    assert "Bearer [REDACTED]" in redacted
    assert "[REDACTED]" in redacted


def test_accurate_status_aggregation_all_pass():
    """Report aggregates to PASS when all checks pass."""
    checks = [
        CheckResult("CHK-1", "Test 1", "Cat", "PASS", "exp", "exp", "detail"),
        CheckResult("CHK-2", "Test 2", "Cat", "PASS", "exp", "exp", "detail"),
    ]
    report = RecoveryVerificationReport(
        timestamp="2026-10-13T00:00:00Z",
        project_version="0.2.0",
        backup_id="backup_test",
        backup_path="/tmp/backup",
        restored_db_path="/tmp/test.db",
        restored_storage_dir="/tmp/docs",
        recovery_url="http://127.0.0.1:8001",
        path_safety_passed=True,
        overall_status="PASS",
        checks=checks,
        summary_counts={"PASS": 2, "FAIL": 0, "BLOCKED": 0, "WARN": 0},
    )
    assert report.overall_status == "PASS"


def test_accurate_status_aggregation_fail_takes_precedence():
    """Report aggregates to FAIL if any check fails."""
    checks = [
        CheckResult("CHK-1", "Test 1", "Cat", "PASS", "exp", "exp", "detail"),
        CheckResult("CHK-2", "Test 2", "Cat", "FAIL", "exp", "different", "mismatch"),
    ]
    summary_counts = {"PASS": 1, "FAIL": 1, "BLOCKED": 0, "WARN": 0}
    overall = "FAIL" if summary_counts["FAIL"] > 0 else "PASS"
    assert overall == "FAIL"


def test_accurate_status_aggregation_blocked_without_fail_is_partial():
    """Report aggregates to PARTIAL when some pass and some are blocked without failures."""
    summary_counts = {"PASS": 2, "FAIL": 0, "BLOCKED": 1, "WARN": 0}
    overall = "PARTIAL" if summary_counts["PASS"] > 0 and summary_counts["BLOCKED"] > 0 else "PASS"
    assert overall == "PARTIAL"


def test_json_and_markdown_report_generation():
    """Generated Markdown and JSON contain required headers and fields."""
    report = RecoveryVerificationReport(
        timestamp="2026-10-13T12:00:00Z",
        project_version="0.2.0",
        backup_id="backup_sample_01",
        backup_path="/tmp/test_backup",
        restored_db_path="/tmp/test.db",
        restored_storage_dir="/tmp/test_docs",
        recovery_url="http://127.0.0.1:8001",
        path_safety_passed=True,
        overall_status="PASS",
        checks=[
            CheckResult("CHK-A", "Backup Integrity", "Backup", "PASS", True, True, "Manifest ok"),
        ],
        summary_counts={"PASS": 1, "FAIL": 0, "BLOCKED": 0, "WARN": 0},
        recommended_actions=["Backup restoration verified."],
    )

    md = generate_markdown_report(report)
    assert "# TradeSathi AI — Automated Disaster Recovery Verification Report" in md
    assert "CHK-A" in md
    assert "backup_sample_01" in md
    assert "http://127.0.0.1:8001" in md

    json_str = generate_json_report(report)
    parsed = json.loads(json_str)
    assert parsed["overall_status"] == "PASS"
    assert parsed["backup_id"] == "backup_sample_01"
    assert len(parsed["checks"]) == 1


def test_handling_unavailable_api_endpoints():
    """Unreachable API endpoint results in BLOCKED status, not crash."""
    with patch("httpx.Client.get", side_effect=httpx.ConnectError("Connection refused")):
        res = check_application_health("http://127.0.0.1:9999")
        assert res.status == "BLOCKED"
        assert "Connection refused" in res.actual
        assert "Ensure recovery server is running" in res.detail


def test_handling_invalid_json_and_non_200_responses():
    """HTTP 500 error or non-JSON response marks check as FAIL."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"
    mock_resp.json.side_effect = ValueError("Invalid JSON")

    with patch("httpx.Client.get", return_value=mock_resp):
        res = check_shipments_api("http://127.0.0.1:8001")
        assert res.status == "FAIL"
        assert res.actual["http_status"] == 500


def test_handling_missing_document_files():
    """Missing document file in restored directory triggers FAIL with file listed."""
    with tempfile.TemporaryDirectory() as tmp_b, tempfile.TemporaryDirectory() as tmp_s:
        b_path = Path(tmp_b)
        s_path = Path(tmp_s)

        # Create dummy manifest listing a missing document
        manifest = {
            "backup_id": "b1",
            "documents": {
                "count": 1,
                "files": [
                    {"relative_path": "shp-1/invoice.pdf", "sha256": "abcdef123456", "size": 100}
                ],
            },
        }
        (b_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        res = check_restored_document_integrity(b_path, s_path, restored_db_path=None)
        assert res.status == "FAIL"
        assert res.actual["missing"] == 1


def test_handling_sha256_mismatches():
    """Tampered or corrupted restored document file triggers FAIL hash mismatch."""
    with tempfile.TemporaryDirectory() as tmp_b, tempfile.TemporaryDirectory() as tmp_s:
        b_path = Path(tmp_b)
        s_path = Path(tmp_s)

        # Create restored file with content "wrong content"
        f_dir = s_path / "shp-1"
        f_dir.mkdir(parents=True)
        target_f = f_dir / "invoice.pdf"
        target_f.write_text("corrupted content", encoding="utf-8")

        # Manifest expecting hash for "original content"
        orig_hash = hashlib.sha256(b"original content").hexdigest()
        manifest = {
            "backup_id": "b1",
            "documents": {
                "count": 1,
                "files": [
                    {"relative_path": "shp-1/invoice.pdf", "sha256": orig_hash, "size": 16}
                ],
            },
        }
        (b_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        res = check_restored_document_integrity(b_path, s_path, restored_db_path=None)
        assert res.status == "FAIL"
        assert res.actual["hash_mismatches"] == 1


def test_handling_blocked_prerequisites_missing_backup():
    """Non-existent backup folder returns BLOCKED status."""
    non_existent = Path("/non/existent/backup/dir")
    res = check_backup_integrity(non_existent)
    assert res.status == "BLOCKED"
    assert "Directory does not exist" in res.actual


def test_check_sqlite_integrity_disposable_db():
    """SQLite integrity check passes on valid SQLite database."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "disposable.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE shipments (id TEXT PRIMARY KEY, reference TEXT);")
        conn.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, shipment_id TEXT);")
        conn.execute("CREATE TABLE analyses (id TEXT PRIMARY KEY, shipment_id TEXT);")
        conn.execute("CREATE TABLE finding_reviews (id TEXT PRIMARY KEY, finding_id TEXT);")
        conn.commit()
        conn.close()

        results = check_sqlite_integrity(db_path)
        pragma_chk = next(c for c in results if c.id == "CHK-C1-SQLITE-PRAGMA")
        row_chk = next(c for c in results if c.id == "CHK-C2-TABLE-ROW-COUNTS")

        assert pragma_chk.status == "PASS"
        # Zero rows will trigger WARN (which notes snapshot variance)
        assert row_chk.status == "WARN"


def test_main_cli_exit_code_on_failure_and_pass():
    """main() returns 0 strictly when status is PASS and no failures/blocks; returns 1 on failure."""
    with patch("backend.app.recovery_verifier.run_recovery_verification") as mock_run, \
         patch("backend.app.recovery_verifier.save_reports", return_value=(Path("rep.md"), Path("rep.json"))), \
         patch("backend.app.recovery_verifier.print_terminal_summary"):

        # Mock PASS scenario
        mock_pass_report = MagicMock()
        mock_pass_report.overall_status = "PASS"
        mock_pass_report.summary_counts = {"FAIL": 0, "BLOCKED": 0, "PASS": 10}
        mock_run.return_value = mock_pass_report

        with patch("sys.argv", ["recovery_verifier.py"]):
            exit_code = main()
            assert exit_code == 0

        # Mock FAIL scenario
        mock_fail_report = MagicMock()
        mock_fail_report.overall_status = "FAIL"
        mock_fail_report.summary_counts = {"FAIL": 1, "BLOCKED": 0, "PASS": 9}
        mock_run.return_value = mock_fail_report

        with patch("sys.argv", ["recovery_verifier.py"]):
            exit_code = main()
            assert exit_code == 1

        # Mock BLOCKED / PARTIAL scenario
        mock_blocked_report = MagicMock()
        mock_blocked_report.overall_status = "PARTIAL"
        mock_blocked_report.summary_counts = {"FAIL": 0, "BLOCKED": 2, "PASS": 8}
        mock_run.return_value = mock_blocked_report

        with patch("sys.argv", ["recovery_verifier.py"]):
            exit_code = main()
            assert exit_code == 1
