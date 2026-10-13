import hashlib
import os
import uuid
from pathlib import Path

from .documents import sanitize_filename

DEFAULT_STORAGE_DIR = Path(__file__).resolve().parent.parent / "storage" / "documents"
_active_storage_dir: Path = DEFAULT_STORAGE_DIR


def set_storage_dir(path: Path | str) -> None:
    """Override active document storage directory, useful for isolated test suites."""
    global _active_storage_dir
    _active_storage_dir = Path(path)
    _active_storage_dir.mkdir(parents=True, exist_ok=True)


def get_storage_dir() -> Path:
    _active_storage_dir.mkdir(parents=True, exist_ok=True)
    return _active_storage_dir


def compute_file_hash(content: bytes) -> str:
    """Compute deterministic SHA-256 hash of file content."""
    return hashlib.sha256(content).hexdigest()


def save_document_file(
    shipment_id: str,
    original_filename: str,
    content: bytes,
    doc_id: str | None = None,
) -> tuple[str, str, str]:
    """
    Safely store uploaded document bytes.
    Returns (doc_id, storage_key, file_hash).
    Storage key is relative and safe from path traversal.
    """
    clean_shipment_id = sanitize_filename(shipment_id)
    clean_filename = sanitize_filename(original_filename)
    uid = doc_id or f"doc-{uuid.uuid4().hex[:10]}"
    file_hash = compute_file_hash(content)

    base_dir = get_storage_dir()
    shipment_dir = base_dir / clean_shipment_id
    shipment_dir.mkdir(parents=True, exist_ok=True)

    stored_name = f"{uid}_{clean_filename}"
    target_path = shipment_dir / stored_name

    # Validate target path stays strictly inside base storage dir
    resolved_target = target_path.resolve()
    resolved_base = base_dir.resolve()
    try:
        resolved_target.relative_to(resolved_base)
    except ValueError:
        raise ValueError("Invalid storage path: directory traversal detected.")

    target_path.write_bytes(content)
    storage_key = f"{clean_shipment_id}/{stored_name}"
    return uid, storage_key, file_hash


def get_document_file_path(storage_key: str) -> Path | None:
    """Resolve storage_key to filesystem path safely."""
    base_dir = get_storage_dir().resolve()
    target = (base_dir / storage_key).resolve()
    try:
        target.relative_to(base_dir)
    except ValueError:
        raise ValueError("Invalid storage key: directory traversal detected.")
    if target.is_file():
        return target
    return None


def delete_document_file(storage_key: str) -> bool:
    """Safely delete stored document from disk."""
    try:
        path = get_document_file_path(storage_key)
        if path and path.is_file():
            path.unlink()
            return True
    except (ValueError, OSError):
        pass
    return False
