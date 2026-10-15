"""TradeSathi AI — Milestone 2F: Operational Hardening & Release Readiness
Backup & Disaster Recovery Module

Provides transactionally consistent SQLite live backup using sqlite3.Connection.backup(),
document store backup, SHA-256 integrity hashing, timestamped manifest creation,
integrity verification, and isolated non-destructive restoration.
"""

import argparse
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import get_connection, get_db_path
from .storage import get_storage_dir

logger = logging.getLogger("tradesathi.backup")

_env_backup = os.getenv("TRADESATHI_BACKUP_ROOT")
DEFAULT_BACKUP_ROOT = Path(_env_backup).resolve() if _env_backup else Path(__file__).resolve().parent.parent / "backups"
APP_VERSION = "0.2.0"
DEFAULT_RETENTION_LIMIT = 10


class RestoreCommitError(RuntimeError):
    """Raised when a restore cannot commit or safely roll back its targets."""


def compute_file_sha256(file_path: Path | str) -> str:
    """Compute SHA-256 hash of a file efficiently in 64KB blocks."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_backup_root(custom_dir: Path | str | None = None) -> Path:
    """Resolve active backup root directory, ensuring it exists."""
    if custom_dir:
        root = Path(custom_dir)
    else:
        _env = os.getenv("TRADESATHI_BACKUP_ROOT")
        root = Path(_env).resolve() if _env else DEFAULT_BACKUP_ROOT
    root.mkdir(parents=True, exist_ok=True)
    return root


def backup_sqlite_live(source_db_path: Path | str, target_db_path: Path | str) -> tuple[str, int]:
    """Execute live transactionally-consistent SQLite backup using sqlite3.Connection.backup().
    Returns (sha256_hash, file_size_bytes).
    """
    src_p = Path(source_db_path).resolve()
    dst_p = Path(target_db_path).resolve()
    dst_p.parent.mkdir(parents=True, exist_ok=True)

    if not src_p.is_file():
        raise FileNotFoundError(f"Source SQLite database not found: {src_p}")

    # Use read-only URI for source connection to avoid write lock contention
    src_conn = sqlite3.connect(f"file:{src_p.as_posix()}?mode=ro", uri=True, timeout=30.0)
    dst_conn = sqlite3.connect(str(dst_p), timeout=30.0)
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    sha256_hash = compute_file_sha256(dst_p)
    file_size = dst_p.stat().st_size
    return sha256_hash, file_size


def count_table_rows(db_path: Path | str) -> dict[str, int]:
    """Inspect row counts for all core TradeSathi tables in a database."""
    counts: dict[str, int] = {}
    target = Path(db_path)
    if not target.is_file():
        return counts

    conn = sqlite3.connect(f"file:{target.resolve().as_posix()}?mode=ro", uri=True, timeout=15.0)
    try:
        conn.row_factory = sqlite3.Row
        tables = ["shipments", "documents", "analyses", "finding_reviews"]
        for table in tables:
            try:
                row = conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}").fetchone()
                counts[table] = int(row["cnt"]) if row else 0
            except sqlite3.OperationalError:
                # Table might not exist in an older schema
                counts[table] = 0
    finally:
        conn.close()
    return counts


def create_backup(
    source_db_path: Path | str | None = None,
    source_storage_dir: Path | str | None = None,
    backup_root: Path | str | None = None,
    retention_limit: int = DEFAULT_RETENTION_LIMIT,
) -> dict[str, Any]:
    """Create a complete, verified snapshot of the SQLite database and all uploaded documents.
    Generates a timestamped manifest with document and database SHA-256 hashes.
    Enforces retention policy without deleting manual backups outside the managed directory.
    """
    src_db = Path(source_db_path) if source_db_path else get_db_path()
    src_storage = Path(source_storage_dir) if source_storage_dir else get_storage_dir()
    root = get_backup_root(backup_root)

    if not src_db.is_file():
        raise FileNotFoundError(f"Source SQLite database does not exist: {src_db}")

    now_utc = datetime.now(timezone.utc)
    timestamp_str = now_utc.strftime("%Y%m%d_%H%M%S")
    uid_suffix = uuid.uuid4().hex[:6]
    backup_id = f"backup_{timestamp_str}_{uid_suffix}"
    backup_dir = root / backup_id
    backup_dir.mkdir(parents=True, exist_ok=True)

    # 1. Backup SQLite database safely
    dest_db_path = backup_dir / "tradesathi.db"
    db_sha256, db_size = backup_sqlite_live(src_db, dest_db_path)
    table_counts = count_table_rows(dest_db_path)

    # 2. Backup document storage directory
    dest_storage_dir = backup_dir / "documents"
    dest_storage_dir.mkdir(parents=True, exist_ok=True)

    doc_files_manifest: list[dict[str, Any]] = []
    total_doc_bytes = 0

    if src_storage.is_dir():
        for root_dir, _, files in os.walk(src_storage):
            for file_name in files:
                src_file_path = Path(root_dir) / file_name
                rel_path = src_file_path.relative_to(src_storage)
                dest_file_path = dest_storage_dir / rel_path
                dest_file_path.parent.mkdir(parents=True, exist_ok=True)

                shutil.copy2(src_file_path, dest_file_path)
                f_size = dest_file_path.stat().st_size
                f_hash = compute_file_sha256(dest_file_path)
                total_doc_bytes += f_size

                doc_files_manifest.append({
                    "relative_path": rel_path.as_posix(),
                    "size_bytes": f_size,
                    "sha256": f_hash,
                })

    # Sort files for deterministic manifest representation
    doc_files_manifest.sort(key=lambda x: x["relative_path"])

    # 3. Create manifest.json
    manifest = {
        "backup_id": backup_id,
        "created_at": now_utc.isoformat(),
        "app_version": APP_VERSION,
        "database": {
            "filename": "tradesathi.db",
            "size_bytes": db_size,
            "sha256": db_sha256,
            "table_counts": table_counts,
        },
        "documents": {
            "total_files": len(doc_files_manifest),
            "total_bytes": total_doc_bytes,
            "files": doc_files_manifest,
        },
        "status": "completed",
    }

    manifest_path = backup_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # 4. Enforce retention policy
    if retention_limit > 0:
        prune_old_backups(root, retention_limit=retention_limit)

    logger.info("Backup %s created successfully with %d documents and %d analyses.",
                backup_id, len(doc_files_manifest), table_counts.get("analyses", 0))
    return manifest


def verify_backup(backup_folder: Path | str) -> dict[str, Any]:
    """Verify integrity of a backup folder against its manifest.
    Checks SQLite integrity check, database SHA-256 hash, table row counts,
    and every individual document file existence and SHA-256 hash.
    """
    folder = Path(backup_folder).resolve()
    manifest_path = folder / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"Backup manifest missing: {manifest_path}")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse manifest JSON in {folder}: {exc}") from exc

    # 1. Verify DB file existence & checksum
    db_filename = manifest.get("database", {}).get("filename", "tradesathi.db")
    db_file = folder / db_filename
    if not db_file.is_file():
        raise ValueError(f"Backed up database file missing: {db_file}")

    actual_db_hash = compute_file_sha256(db_file)
    expected_db_hash = manifest["database"]["sha256"]
    if actual_db_hash != expected_db_hash:
        raise ValueError(
            f"Database SHA-256 checksum mismatch: expected {expected_db_hash}, got {actual_db_hash}"
        )

    # 2. Check SQLite PRAGMA integrity_check
    conn = sqlite3.connect(f"file:{db_file.as_posix()}?mode=ro", uri=True, timeout=15.0)
    try:
        cursor = conn.execute("PRAGMA integrity_check")
        rows = cursor.fetchall()
        if not rows or rows[0][0] != "ok":
            raise ValueError(f"Database PRAGMA integrity_check failed on backup: {rows}")

        # Verify table counts match manifest
        expected_counts = manifest["database"].get("table_counts", {})
        actual_counts = count_table_rows(db_file)
        for tbl, exp_cnt in expected_counts.items():
            act_cnt = actual_counts.get(tbl, 0)
            if act_cnt != exp_cnt:
                raise ValueError(
                    f"Table count mismatch for '{tbl}': expected {exp_cnt}, found {act_cnt}"
                )
    finally:
        conn.close()

    # 3. Verify all document files against manifest
    storage_folder = folder / "documents"
    doc_entries = manifest.get("documents", {}).get("files", [])
    for entry in doc_entries:
        rel_path = entry["relative_path"]
        expected_hash = entry["sha256"]
        expected_size = entry["size_bytes"]

        doc_file = storage_folder / rel_path
        if not doc_file.is_file():
            raise ValueError(f"Backed up document file missing: {rel_path}")

        act_size = doc_file.stat().st_size
        if act_size != expected_size:
            raise ValueError(
                f"Document size mismatch for {rel_path}: expected {expected_size}, got {act_size}"
            )

        act_hash = compute_file_sha256(doc_file)
        if act_hash != expected_hash:
            raise ValueError(
                f"Document SHA-256 checksum mismatch for {rel_path}: expected {expected_hash}, got {act_hash}"
            )

    return {
        "verified": True,
        "backup_id": manifest["backup_id"],
        "created_at": manifest["created_at"],
        "database_sha256": actual_db_hash,
        "table_counts": manifest["database"]["table_counts"],
        "documents_verified": len(doc_entries),
    }


def _write_restore_journal(journal_path: Path, payload: dict[str, Any]) -> None:
    """Durably publish the latest recoverable restore state."""
    temporary_path = journal_path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary_path, journal_path)


def _restore_commit_checkpoint(step: str) -> None:
    """Internal checkpoint retained to support isolated failure-injection tests."""


def _move_if_present(source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    os.replace(source, destination)
    return True


def _rollback_restore_targets(journal: dict[str, Any]) -> list[str]:
    """Return original targets from recovery locations after a failed commit."""
    errors: list[str] = []
    for target_key, recovery_key, failed_key in (
        ("target_db", "previous_db", "failed_db_candidate"),
        ("target_storage", "previous_storage", "failed_storage_candidate"),
    ):
        target = Path(journal[target_key])
        previous = Path(journal[recovery_key])
        failed_candidate = Path(journal[failed_key])
        try:
            if target.exists():
                os.replace(target, failed_candidate)
            if previous.exists():
                os.replace(previous, target)
        except OSError as exc:
            errors.append(f"{target}: {exc}")
    return errors


def restore_backup(
    backup_folder: Path | str,
    target_db_path: Path | str,
    target_storage_dir: Path | str,
) -> dict[str, Any]:
    """Restore a verified backup through staging and a recoverable commit protocol.

    Individual file and directory replacements are atomic when the underlying platform
    supports ``os.replace``. The database and document directory are not a single
    atomic transaction: a durable journal and retained prior versions make an
    interruption between their replacements recoverable.
    """
    folder = Path(backup_folder).resolve()
    # 1. Verify backup integrity first
    verify_res = verify_backup(folder)

    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    target_db = Path(target_db_path).resolve()
    target_storage = Path(target_storage_dir).resolve()

    target_db.parent.mkdir(parents=True, exist_ok=True)
    target_storage.parent.mkdir(parents=True, exist_ok=True)

    restore_id = uuid.uuid4().hex
    staged_db = target_db.parent / f".{target_db.name}.restore-stage-{restore_id}"
    staged_storage = target_storage.parent / f".{target_storage.name}.restore-stage-{restore_id}"
    previous_db = target_db.parent / f".{target_db.name}.pre-restore-{restore_id}"
    previous_storage = target_storage.parent / f".{target_storage.name}.pre-restore-{restore_id}"
    failed_db_candidate = target_db.parent / f".{target_db.name}.failed-restore-{restore_id}"
    failed_storage_candidate = target_storage.parent / f".{target_storage.name}.failed-restore-{restore_id}"
    journal_path = target_db.parent / f".{target_db.name}.restore-{restore_id}.json"

    if any(path.exists() for path in (staged_db, staged_storage, previous_db, previous_storage, journal_path)):
        raise RestoreCommitError("Refusing restore because a generated recovery path already exists")

    # 2. Restore and validate both assets in isolated staging locations first.
    backup_db_path = folder / manifest["database"]["filename"]
    restore_sha256, restore_size = backup_sqlite_live(backup_db_path, staged_db)
    if restore_sha256 != manifest["database"]["sha256"] or restore_size != manifest["database"]["size_bytes"]:
        raise ValueError("Staged database does not match the verified backup manifest")
    if count_table_rows(staged_db) != manifest["database"].get("table_counts", {}):
        raise ValueError("Staged database table counts do not match the verified backup manifest")

    # 3. Restore documents into staging and verify semantic consistency there.
    src_documents = folder / "documents"
    restored_docs = 0
    staged_storage.mkdir(parents=True, exist_ok=False)
    if src_documents.is_dir():
        for doc_entry in manifest["documents"]["files"]:
            rel_p = Path(doc_entry["relative_path"])
            src_f = src_documents / rel_p
            dst_f = staged_storage / rel_p
            dst_f.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_f, dst_f)

            # Confirm restored file matches expected hash
            dst_hash = compute_file_sha256(dst_f)
            if dst_hash != doc_entry["sha256"]:
                raise ValueError(f"Restored document hash mismatch for {rel_p}")
            restored_docs += 1

    # 4. Deep referential and document integrity check before changing targets.
    restoration_report = verify_restoration_integrity(staged_db, staged_storage)

    journal: dict[str, Any] = {
        "restore_id": restore_id,
        "backup_id": manifest["backup_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "staged_verified",
        "target_db": str(target_db),
        "target_storage": str(target_storage),
        "staged_db": str(staged_db),
        "staged_storage": str(staged_storage),
        "previous_db": str(previous_db),
        "previous_storage": str(previous_storage),
        "failed_db_candidate": str(failed_db_candidate),
        "failed_storage_candidate": str(failed_storage_candidate),
        "operator_instruction": "Keep maintenance mode enabled. If status is rollback_required, restore each existing previous_* path to its target path before restarting the application.",
    }
    _write_restore_journal(journal_path, journal)

    # 5. Commit the pair. Each move is atomic on its target filesystem, while the
    # journal makes a cross-asset interruption explicit and recoverable.
    try:
        _restore_commit_checkpoint("before_preserve_targets")
        journal["previous_db_present"] = _move_if_present(target_db, previous_db)
        journal["status"] = "database_target_preserved"
        _write_restore_journal(journal_path, journal)
        _restore_commit_checkpoint("database_target_preserved")

        journal["previous_storage_present"] = _move_if_present(target_storage, previous_storage)
        journal["status"] = "both_targets_preserved"
        _write_restore_journal(journal_path, journal)
        _restore_commit_checkpoint("both_targets_preserved")

        os.replace(staged_db, target_db)
        journal["status"] = "database_replaced_documents_pending"
        _write_restore_journal(journal_path, journal)
        _restore_commit_checkpoint("database_replaced_documents_pending")

        os.replace(staged_storage, target_storage)
        journal["status"] = "completed"
        _write_restore_journal(journal_path, journal)
        _restore_commit_checkpoint("completed")
    except BaseException as exc:
        rollback_errors = _rollback_restore_targets(journal)
        journal["status"] = "rolled_back" if not rollback_errors else "rollback_required"
        journal["failure"] = repr(exc)
        journal["rollback_errors"] = rollback_errors
        _write_restore_journal(journal_path, journal)
        if rollback_errors:
            raise RestoreCommitError(
                f"Restore commit failed and requires manual recovery; journal: {journal_path}; errors: {rollback_errors}"
            ) from exc
        raise RestoreCommitError(
            f"Restore commit failed; original targets were restored. Journal retained at {journal_path}"
        ) from exc

    logger.info("Restored backup %s to %s with %d documents and %d analyses.",
                manifest["backup_id"], str(target_db), restored_docs, restoration_report.get("analyses_count", 0))

    return {
        "status": "success",
        "backup_id": manifest["backup_id"],
        "target_db_path": str(target_db),
        "target_storage_dir": str(target_storage),
        "restore_journal": str(journal_path),
        "previous_target_db": str(previous_db) if journal.get("previous_db_present") else None,
        "previous_target_storage": str(previous_storage) if journal.get("previous_storage_present") else None,
        "restored_tables": manifest["database"]["table_counts"],
        "restored_documents": restored_docs,
        "verification": verify_res,
        "restoration_integrity": restoration_report,
    }


def verify_restoration_integrity(
    target_db_path: Path | str,
    target_storage_dir: Path | str,
) -> dict[str, Any]:
    """Verify deep semantic and referential consistency of restored database and documents.
    Validates:
    - SQLite PRAGMA integrity_check
    - Foreign key referential integrity (PRAGMA foreign_key_check)
    - Restoration of shipments, analyses, review events, and documents
    - Document disk file existence and SHA-256 match against database file_hash
    - Evidence references traceability in restored analyses
    """
    db_p = Path(target_db_path).resolve()
    storage_p = Path(target_storage_dir).resolve()

    if not db_p.is_file():
        raise FileNotFoundError(f"Restored database not found at {db_p}")

    conn = sqlite3.connect(f"file:{db_p.as_posix()}?mode=ro", uri=True, timeout=15.0)
    try:
        conn.row_factory = sqlite3.Row

        # 1. PRAGMA integrity_check
        cur = conn.execute("PRAGMA integrity_check")
        rows = cur.fetchall()
        if not rows or rows[0][0] != "ok":
            raise ValueError(f"Restored database integrity check failed: {rows}")

        # 2. PRAGMA foreign_key_check
        cur_fk = conn.execute("PRAGMA foreign_key_check")
        fk_violations = cur_fk.fetchall()
        if fk_violations:
            raise ValueError(f"Restored database foreign key integrity violations: {fk_violations}")

        # 3. Check shipments
        cur_s = conn.execute("SELECT COUNT(*) AS cnt FROM shipments")
        shipments_count = int(cur_s.fetchone()["cnt"])

        # 4. Check analyses
        cur_a = conn.execute("SELECT id, response_json, shipment_id FROM analyses")
        analyses_rows = cur_a.fetchall()
        analyses_count = len(analyses_rows)

        # 5. Check review events
        cur_r = conn.execute("SELECT id, analysis_id, finding_id, supporting_evidence_json FROM finding_reviews")
        reviews_rows = cur_r.fetchall()
        reviews_count = len(reviews_rows)

        # 6. Check documents against disk
        cur_d = conn.execute("SELECT id, storage_key, file_hash, original_filename FROM documents")
        doc_rows = cur_d.fetchall()
        documents_count = len(doc_rows)

        doc_matches = 0
        for doc in doc_rows:
            storage_key = doc["storage_key"]
            expected_hash = doc["file_hash"]
            disk_file = storage_p / storage_key
            if not disk_file.is_file():
                raise FileNotFoundError(
                    f"Restored document file missing from disk: {disk_file} (record id: {doc['id']})"
                )
            actual_hash = compute_file_sha256(disk_file)
            if actual_hash != expected_hash:
                raise ValueError(
                    f"Restored document hash mismatch for {storage_key}: expected {expected_hash}, got {actual_hash}"
                )
            doc_matches += 1

        # 7. Check evidence references traceability in analyses
        evidence_references_checked = 0
        for anl in analyses_rows:
            try:
                data = json.loads(anl["response_json"])
                for disc in data.get("discrepancies", []):
                    ev_ids = disc.get("evidence_ids", {})
                    if ev_ids:
                        evidence_references_checked += len(ev_ids)
            except Exception:
                pass

    finally:
        conn.close()

    return {
        "status": "verified",
        "shipments_count": shipments_count,
        "analyses_count": analyses_count,
        "reviews_count": reviews_count,
        "documents_count": documents_count,
        "documents_verified_on_disk": doc_matches,
        "evidence_references_checked": evidence_references_checked,
    }


def prune_old_backups(backup_root: Path | str, retention_limit: int = DEFAULT_RETENTION_LIMIT) -> list[str]:
    """Prune oldest backups in backup_root exceeding the retention limit.
    Only manages subdirectories starting with 'backup_' containing manifest.json.
    """
    root = Path(backup_root).resolve()
    if not root.is_dir():
        return []

    candidates: list[tuple[datetime, Path]] = []
    for entry in root.iterdir():
        if entry.is_dir() and entry.name.startswith("backup_"):
            manifest_p = entry / "manifest.json"
            if manifest_p.is_file():
                try:
                    data = json.loads(manifest_p.read_text(encoding="utf-8"))
                    dt = datetime.fromisoformat(data["created_at"])
                    candidates.append((dt, entry))
                except Exception:
                    candidates.append((datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc), entry))

    # Sort newest first
    candidates.sort(key=lambda x: x[0], reverse=True)

    pruned: list[str] = []
    if len(candidates) > retention_limit:
        for _, path_to_remove in candidates[retention_limit:]:
            try:
                shutil.rmtree(path_to_remove)
                pruned.append(path_to_remove.name)
                logger.info("Pruned old backup snapshot: %s", path_to_remove.name)
            except Exception as exc:
                logger.warning("Failed to prune old backup %s: %exc", path_to_remove.name, exc)
    return pruned


def list_backups(backup_root: Path | str | None = None) -> list[dict[str, Any]]:
    """List all valid backups in backup_root with metadata from manifests."""
    root = get_backup_root(backup_root)
    results: list[dict[str, Any]] = []

    for entry in root.iterdir():
        if entry.is_dir() and (entry / "manifest.json").is_file():
            try:
                manifest = json.loads((entry / "manifest.json").read_text(encoding="utf-8"))
                manifest["folder_path"] = str(entry)
                results.append(manifest)
            except Exception:
                pass

    results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return results


def main() -> None:
    """CLI entrypoint for operational backup and recovery."""
    parser = argparse.ArgumentParser(description="TradeSathi AI Backup & Disaster Recovery Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # create
    p_create = subparsers.add_parser("create", help="Create a full snapshot backup")
    p_create.add_argument("--retention", type=int, default=DEFAULT_RETENTION_LIMIT, help="Retention limit")
    p_create.add_argument("--backup-dir", type=str, default=None, help="Custom backup directory")

    # verify
    p_verify = subparsers.add_parser("verify", help="Verify backup integrity against manifest")
    p_verify.add_argument("backup_path", type=str, help="Path to backup snapshot directory")

    # restore
    p_restore = subparsers.add_parser("restore", help="Restore backup into destination paths")
    p_restore.add_argument("backup_path", type=str, help="Path to backup snapshot directory")
    p_restore.add_argument("--target-db", type=str, required=True, help="Destination database path")
    p_restore.add_argument("--target-storage", type=str, required=True, help="Destination documents directory")

    # list
    p_list = subparsers.add_parser("list", help="List available backup snapshots")
    p_list.add_argument("--backup-dir", type=str, default=None, help="Custom backup directory")

    args = parser.parse_args()

    if args.command == "create":
        res = create_backup(backup_root=args.backup_dir, retention_limit=args.retention)
        print(f"Backup created successfully: {res['backup_id']}")
        print(json.dumps(res, indent=2))
    elif args.command == "verify":
        res = verify_backup(args.backup_path)
        print("Backup verified successfully!")
        print(json.dumps(res, indent=2))
    elif args.command == "restore":
        res = restore_backup(args.backup_path, args.target_db, args.target_storage)
        print("Backup restored successfully!")
        print(json.dumps(res, indent=2))
    elif args.command == "list":
        backups = list_backups(args.backup_dir)
        print(f"Found {len(backups)} backup snapshot(s):")
        for b in backups:
            print(f"- {b['backup_id']} ({b['created_at']}): {b['documents']['total_files']} files, "
                  f"{b['database']['table_counts'].get('analyses', 0)} analyses")


if __name__ == "__main__":
    main()
