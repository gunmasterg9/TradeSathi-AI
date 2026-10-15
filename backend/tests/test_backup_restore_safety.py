"""Failure-injection tests for staged, recoverable backup restoration."""

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from backend.app import backup
from backend.app.db import init_db


def _create_verified_backup(tmp_path: Path) -> Path:
    source_db = tmp_path / "source.db"
    source_storage = tmp_path / "source-documents"
    source_storage.mkdir()
    init_db(source_db)

    document = source_storage / "shp-1" / "invoice.txt"
    document.parent.mkdir()
    document.write_text("verified invoice", encoding="utf-8")
    digest = hashlib.sha256(document.read_bytes()).hexdigest()
    with sqlite3.connect(source_db) as connection:
        connection.execute(
            "INSERT INTO shipments (id, reference, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("shp-1", "RESTORE-TEST-1", "draft", "2026-01-01", "2026-01-01"),
        )
        connection.execute(
            """INSERT INTO documents (
                id, shipment_id, original_filename, clean_filename, document_type,
                uploaded_at, storage_key, file_size, file_hash, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("doc-1", "shp-1", "invoice.txt", "invoice.txt", "invoice", "2026-01-01",
             "shp-1/invoice.txt", document.stat().st_size, digest, "2026-01-01", "2026-01-01"),
        )

    backup_root = tmp_path / "backups"
    manifest = backup.create_backup(source_db, source_storage, backup_root, retention_limit=0)
    return backup_root / manifest["backup_id"]


def _create_existing_targets(tmp_path: Path) -> tuple[Path, Path]:
    target_db = tmp_path / "targets" / "tradesathi.db"
    target_db.parent.mkdir(parents=True)
    target_db.write_text("original database sentinel", encoding="utf-8")
    target_storage = tmp_path / "targets" / "documents"
    target_storage.mkdir()
    (target_storage / "legacy.txt").write_text("original document sentinel", encoding="utf-8")
    return target_db, target_storage


def _assert_original_targets(target_db: Path, target_storage: Path) -> None:
    assert target_db.read_text(encoding="utf-8") == "original database sentinel"
    assert (target_storage / "legacy.txt").read_text(encoding="utf-8") == "original document sentinel"


def test_missing_manifest_does_not_modify_existing_targets(tmp_path: Path):
    target_db, target_storage = _create_existing_targets(tmp_path)
    with pytest.raises(ValueError, match="manifest missing"):
        backup.restore_backup(tmp_path / "missing-backup", target_db, target_storage)
    _assert_original_targets(target_db, target_storage)


def test_invalid_document_hash_does_not_modify_existing_targets(tmp_path: Path):
    snapshot = _create_verified_backup(tmp_path)
    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["documents"]["files"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    target_db, target_storage = _create_existing_targets(tmp_path)

    with pytest.raises(ValueError, match="Document SHA-256 checksum mismatch"):
        backup.restore_backup(snapshot, target_db, target_storage)
    _assert_original_targets(target_db, target_storage)


def test_document_copy_failure_leaves_existing_targets_untouched(tmp_path: Path, monkeypatch):
    snapshot = _create_verified_backup(tmp_path)
    target_db, target_storage = _create_existing_targets(tmp_path)
    original_copy = backup.shutil.copy2

    def fail_staged_document_copy(source, destination, *args, **kwargs):
        if ".restore-stage-" in str(destination):
            raise OSError("simulated disk full")
        return original_copy(source, destination, *args, **kwargs)

    monkeypatch.setattr(backup.shutil, "copy2", fail_staged_document_copy)
    with pytest.raises(OSError, match="simulated disk full"):
        backup.restore_backup(snapshot, target_db, target_storage)
    _assert_original_targets(target_db, target_storage)


def test_database_stage_failure_leaves_existing_targets_untouched(tmp_path: Path, monkeypatch):
    snapshot = _create_verified_backup(tmp_path)
    target_db, target_storage = _create_existing_targets(tmp_path)
    original_backup = backup.backup_sqlite_live

    def fail_staged_database_copy(source, destination):
        if ".restore-stage-" in str(destination):
            raise OSError("simulated database write failure")
        return original_backup(source, destination)

    monkeypatch.setattr(backup, "backup_sqlite_live", fail_staged_database_copy)
    with pytest.raises(OSError, match="simulated database write failure"):
        backup.restore_backup(snapshot, target_db, target_storage)
    _assert_original_targets(target_db, target_storage)


def test_commit_failure_after_database_replacement_restores_original_targets(tmp_path: Path, monkeypatch):
    snapshot = _create_verified_backup(tmp_path)
    target_db, target_storage = _create_existing_targets(tmp_path)

    def fail_between_pair_replacements(step: str):
        if step == "database_replaced_documents_pending":
            raise OSError("simulated commit interruption")

    monkeypatch.setattr(backup, "_restore_commit_checkpoint", fail_between_pair_replacements)
    with pytest.raises(backup.RestoreCommitError, match="original targets were restored"):
        backup.restore_backup(snapshot, target_db, target_storage)
    _assert_original_targets(target_db, target_storage)
    journal = next(target_db.parent.glob(".tradesathi.db.restore-*.json"))
    assert json.loads(journal.read_text(encoding="utf-8"))["status"] == "rolled_back"


def test_simulated_process_interruption_restores_original_targets(tmp_path: Path, monkeypatch):
    snapshot = _create_verified_backup(tmp_path)
    target_db, target_storage = _create_existing_targets(tmp_path)

    def interrupt_after_database_replace(step: str):
        if step == "database_replaced_documents_pending":
            raise KeyboardInterrupt("simulated process interruption")

    monkeypatch.setattr(backup, "_restore_commit_checkpoint", interrupt_after_database_replace)
    with pytest.raises(backup.RestoreCommitError, match="original targets were restored"):
        backup.restore_backup(snapshot, target_db, target_storage)
    _assert_original_targets(target_db, target_storage)


def test_successful_restore_is_consistent_and_second_attempt_is_deterministic(tmp_path: Path):
    snapshot = _create_verified_backup(tmp_path)
    target_db, target_storage = _create_existing_targets(tmp_path)

    first = backup.restore_backup(snapshot, target_db, target_storage)
    assert first["status"] == "success"
    assert Path(first["previous_target_db"]).read_text(encoding="utf-8") == "original database sentinel"
    assert Path(first["previous_target_storage"]).joinpath("legacy.txt").is_file()
    assert backup.verify_restoration_integrity(target_db, target_storage)["documents_verified_on_disk"] == 1

    second = backup.restore_backup(snapshot, target_db, target_storage)
    assert second["status"] == "success"
    assert backup.compute_file_sha256(target_db) == backup.compute_file_sha256(snapshot / "tradesathi.db")
    assert (target_storage / "shp-1" / "invoice.txt").read_text(encoding="utf-8") == "verified invoice"
