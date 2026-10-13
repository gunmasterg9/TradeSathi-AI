import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "tradesathi.db"
_active_db_path: Path = DB_PATH


def set_db_path(path: Path | str) -> None:
    """Override active database path, useful for isolated test suites."""
    global _active_db_path
    _active_db_path = Path(path)


def get_db_path() -> Path:
    return _active_db_path


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    target_path = Path(db_path) if db_path else _active_db_path
    conn = sqlite3.connect(str(target_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | str | None = None) -> None:
    """Initialize SQLite tables and apply safe backward-compatible migrations."""
    with get_connection(db_path) as conn:
        # Create shipments table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shipments (
                id TEXT PRIMARY KEY,
                reference TEXT NOT NULL UNIQUE,
                exporter TEXT,
                buyer TEXT,
                product_description TEXT,
                destination_country TEXT,
                destination_port TEXT,
                planned_shipment_date TEXT,
                incoterm TEXT,
                named_place TEXT,
                notes TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shipments_reference ON shipments(reference)")

        # Create analyses table if not exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS analyses (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                mode TEXT NOT NULL,
                model TEXT,
                status TEXT NOT NULL,
                headline TEXT NOT NULL,
                document_count INTEGER NOT NULL,
                filenames_json TEXT NOT NULL,
                discrepancy_count INTEGER NOT NULL,
                response_json TEXT NOT NULL,
                shipment_id TEXT
            )
        """)

        # Migration: Ensure shipment_id column exists on pre-existing analyses table
        cursor = conn.execute("PRAGMA table_info(analyses)")
        columns = [row["name"] for row in cursor.fetchall()]
        if "shipment_id" not in columns:
            conn.execute("ALTER TABLE analyses ADD COLUMN shipment_id TEXT")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_analyses_shipment_id ON analyses(shipment_id)")

        # Create documents table for Milestone 2C Document Register
        conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                shipment_id TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                clean_filename TEXT NOT NULL,
                document_type TEXT NOT NULL DEFAULT 'unknown',
                uploaded_at TEXT NOT NULL,
                storage_key TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                file_hash TEXT NOT NULL,
                processing_status TEXT NOT NULL DEFAULT 'completed',
                review_status TEXT NOT NULL DEFAULT 'uploaded',
                notes TEXT,
                last_reviewed_by TEXT,
                last_reviewed_at TEXT,
                review_notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (shipment_id) REFERENCES shipments(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_shipment_id ON documents(shipment_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_file_hash ON documents(file_hash)")

        conn.commit()


# ==========================================
# Shipment Persistence Functions
# ==========================================


def create_shipment(data: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    shipment_id = data.get("id")
    if not shipment_id:
        shipment_id = f"shp-{uuid.uuid4().hex[:10]}"

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO shipments (
                id, reference, exporter, buyer, product_description,
                destination_country, destination_port, planned_shipment_date,
                incoterm, named_place, notes, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                shipment_id,
                data["reference"].strip(),
                data.get("exporter"),
                data.get("buyer"),
                data.get("product_description"),
                data.get("destination_country"),
                data.get("destination_port"),
                data.get("planned_shipment_date"),
                data.get("incoterm"),
                data.get("named_place"),
                data.get("notes"),
                data.get("status", "draft"),
                now,
                now,
            ),
        )
        conn.commit()

    return get_shipment_by_id(shipment_id)  # type: ignore[return-value]


def get_shipment_by_id(shipment_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT s.*,
                   COUNT(DISTINCT a.id) AS analysis_count,
                   (SELECT COUNT(d.id) FROM documents d WHERE d.shipment_id = s.id) AS document_count,
                   (SELECT a2.status FROM analyses a2 WHERE a2.shipment_id = s.id ORDER BY a2.created_at DESC LIMIT 1) AS latest_analysis_status
            FROM shipments s
            LEFT JOIN analyses a ON a.shipment_id = s.id
            WHERE s.id = ?
            GROUP BY s.id
            """,
            (shipment_id,),
        )
        row = cursor.fetchone()

    if not row:
        return None

    return _row_to_shipment_dict(row)


def get_shipment_by_reference(reference: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT s.*,
                   COUNT(DISTINCT a.id) AS analysis_count,
                   (SELECT COUNT(d.id) FROM documents d WHERE d.shipment_id = s.id) AS document_count,
                   (SELECT a2.status FROM analyses a2 WHERE a2.shipment_id = s.id ORDER BY a2.created_at DESC LIMIT 1) AS latest_analysis_status
            FROM shipments s
            LEFT JOIN analyses a ON a.shipment_id = s.id
            WHERE LOWER(TRIM(s.reference)) = LOWER(TRIM(?))
            GROUP BY s.id
            """,
            (reference,),
        )
        row = cursor.fetchone()

    if not row:
        return None

    return _row_to_shipment_dict(row)


def list_shipments(
    search: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    query = """
        SELECT s.*,
               COUNT(DISTINCT a.id) AS analysis_count,
               (SELECT COUNT(d.id) FROM documents d WHERE d.shipment_id = s.id) AS document_count,
               (SELECT a2.status FROM analyses a2 WHERE a2.shipment_id = s.id ORDER BY a2.created_at DESC LIMIT 1) AS latest_analysis_status
        FROM shipments s
        LEFT JOIN analyses a ON a.shipment_id = s.id
        WHERE 1=1
    """
    params: list[Any] = []

    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        query += """ AND (
            LOWER(s.reference) LIKE ? OR
            LOWER(COALESCE(s.exporter, '')) LIKE ? OR
            LOWER(COALESCE(s.buyer, '')) LIKE ? OR
            LOWER(COALESCE(s.destination_port, '')) LIKE ? OR
            LOWER(COALESCE(s.product_description, '')) LIKE ?
        )"""
        params.extend([term, term, term, term, term])

    if status and status.strip():
        query += " AND s.status = ?"
        params.append(status.strip())

    query += """
        GROUP BY s.id
        ORDER BY s.created_at DESC
        LIMIT ?
    """
    params.append(limit)

    with get_connection() as conn:
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()

    return [_row_to_shipment_dict(row) for row in rows]


def update_shipment(shipment_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    allowed_fields = {
        "reference",
        "exporter",
        "buyer",
        "product_description",
        "destination_country",
        "destination_port",
        "planned_shipment_date",
        "incoterm",
        "named_place",
        "notes",
        "status",
    }
    filtered = {k: v for k, v in updates.items() if k in allowed_fields}
    if not filtered:
        return get_shipment_by_id(shipment_id)

    now = datetime.now(timezone.utc).isoformat()
    filtered["updated_at"] = now

    set_clauses = [f"{k} = ?" for k in filtered.keys()]
    values = list(filtered.values())
    values.append(shipment_id)

    with get_connection() as conn:
        cursor = conn.execute(
            f"UPDATE shipments SET {', '.join(set_clauses)} WHERE id = ?",
            values,
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None

    return get_shipment_by_id(shipment_id)


def _row_to_shipment_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": data["id"],
        "reference": data["reference"],
        "exporter": data.get("exporter"),
        "buyer": data.get("buyer"),
        "product_description": data.get("product_description"),
        "destination_country": data.get("destination_country"),
        "destination_port": data.get("destination_port"),
        "planned_shipment_date": data.get("planned_shipment_date"),
        "incoterm": data.get("incoterm"),
        "named_place": data.get("named_place"),
        "notes": data.get("notes"),
        "status": data.get("status", "draft"),
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        "analysis_count": data.get("analysis_count", 0),
        "document_count": data.get("document_count", 0),
        "latest_analysis_status": data.get("latest_analysis_status"),
    }


# ==========================================
# Document Persistence Functions (Milestone 2C)
# ==========================================


def _row_to_document_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": data["id"],
        "shipment_id": data["shipment_id"],
        "original_filename": data["original_filename"],
        "clean_filename": data["clean_filename"],
        "document_type": data.get("document_type", "unknown"),
        "uploaded_at": data["uploaded_at"],
        "storage_key": data["storage_key"],
        "file_size": data["file_size"],
        "file_hash": data["file_hash"],
        "processing_status": data.get("processing_status", "completed"),
        "review_status": data.get("review_status", "uploaded"),
        "notes": data.get("notes"),
        "last_reviewed_by": data.get("last_reviewed_by"),
        "last_reviewed_at": data.get("last_reviewed_at"),
        "review_notes": data.get("review_notes"),
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
    }


def create_document_record(data: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    doc_id = data.get("id") or f"doc-{uuid.uuid4().hex[:10]}"

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO documents (
                id, shipment_id, original_filename, clean_filename,
                document_type, uploaded_at, storage_key, file_size, file_hash,
                processing_status, review_status, notes, last_reviewed_by,
                last_reviewed_at, review_notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc_id,
                data["shipment_id"],
                data["original_filename"],
                data.get("clean_filename", data["original_filename"]),
                data.get("document_type", "unknown"),
                data.get("uploaded_at", now),
                data["storage_key"],
                int(data.get("file_size", 0)),
                data["file_hash"],
                data.get("processing_status", "completed"),
                data.get("review_status", "uploaded"),
                data.get("notes"),
                data.get("last_reviewed_by"),
                data.get("last_reviewed_at"),
                data.get("review_notes"),
                now,
                now,
            ),
        )
        conn.commit()

    return get_document_by_id(doc_id)  # type: ignore[return-value]


def get_document_by_id(doc_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        cursor = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
        row = cursor.fetchone()
    if not row:
        return None
    return _row_to_document_dict(row)


def list_documents_for_shipment(shipment_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT * FROM documents WHERE shipment_id = ? ORDER BY uploaded_at ASC",
            (shipment_id,),
        )
        rows = cursor.fetchall()
    return [_row_to_document_dict(r) for r in rows]


def get_duplicate_document(
    shipment_id: str,
    file_hash: str | None = None,
    filename: str | None = None,
) -> dict[str, Any] | None:
    with get_connection() as conn:
        if file_hash:
            cursor = conn.execute(
                "SELECT * FROM documents WHERE shipment_id = ? AND file_hash = ? LIMIT 1",
                (shipment_id, file_hash),
            )
            row = cursor.fetchone()
            if row:
                return _row_to_document_dict(row)
        if filename:
            clean_name = filename.strip().lower()
            cursor = conn.execute(
                "SELECT * FROM documents WHERE shipment_id = ? AND LOWER(original_filename) = ? LIMIT 1",
                (shipment_id, clean_name),
            )
            row = cursor.fetchone()
            if row:
                return _row_to_document_dict(row)
    return None


def update_document_record(doc_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    allowed_fields = {
        "document_type",
        "processing_status",
        "review_status",
        "notes",
        "last_reviewed_by",
        "last_reviewed_at",
        "review_notes",
    }
    filtered = {k: v for k, v in updates.items() if k in allowed_fields}
    if not filtered:
        return get_document_by_id(doc_id)

    now = datetime.now(timezone.utc).isoformat()
    filtered["updated_at"] = now

    set_clauses = [f"{k} = ?" for k in filtered.keys()]
    values = list(filtered.values())
    values.append(doc_id)

    with get_connection() as conn:
        cursor = conn.execute(
            f"UPDATE documents SET {', '.join(set_clauses)} WHERE id = ?",
            values,
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None

    return get_document_by_id(doc_id)


def delete_document_record(doc_id: str) -> dict[str, Any] | None:
    doc = get_document_by_id(doc_id)
    if not doc:
        return None
    with get_connection() as conn:
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        conn.commit()
    return doc


# ==========================================
# Analysis Persistence Functions
# ==========================================


def save_analysis(
    analysis_id: str,
    mode: str,
    model: str | None,
    status: str,
    headline: str,
    filenames: list[str],
    discrepancy_count: int,
    response_data: dict[str, Any],
    shipment_id: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO analyses (
                id, created_at, mode, model, status, headline,
                document_count, filenames_json, discrepancy_count, response_json,
                shipment_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analysis_id,
                now,
                mode,
                model,
                status,
                headline,
                len(filenames),
                json.dumps(filenames),
                discrepancy_count,
                json.dumps(response_data),
                shipment_id,
            ),
        )

        # If linked to a shipment, update the shipment's status and updated_at
        if shipment_id:
            conn.execute(
                """
                UPDATE shipments
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, now, shipment_id),
            )

        conn.commit()


def list_analyses(limit: int = 20) -> list[dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, created_at, mode, model, status, headline,
                   document_count, filenames_json, discrepancy_count, shipment_id
            FROM analyses
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()

    results = []
    for row in rows:
        results.append({
            "id": row["id"],
            "created_at": row["created_at"],
            "mode": row["mode"],
            "model": row["model"],
            "status": row["status"],
            "headline": row["headline"],
            "document_count": row["document_count"],
            "filenames": json.loads(row["filenames_json"]),
            "discrepancy_count": row["discrepancy_count"],
            "shipment_id": row["shipment_id"] if "shipment_id" in row.keys() else None,
        })
    return results


def list_analyses_for_shipment(shipment_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, created_at, mode, model, status, headline,
                   document_count, filenames_json, discrepancy_count, response_json, shipment_id
            FROM analyses
            WHERE shipment_id = ?
            ORDER BY created_at DESC
            """,
            (shipment_id,),
        )
        rows = cursor.fetchall()

    results = []
    for row in rows:
        results.append({
            "id": row["id"],
            "created_at": row["created_at"],
            "mode": row["mode"],
            "model": row["model"],
            "status": row["status"],
            "headline": row["headline"],
            "document_count": row["document_count"],
            "filenames": json.loads(row["filenames_json"]),
            "discrepancy_count": row["discrepancy_count"],
            "response_data": json.loads(row["response_json"]),
            "shipment_id": row["shipment_id"],
        })
    return results


def get_latest_analysis_for_shipment(shipment_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, created_at, mode, model, status, headline,
                   document_count, filenames_json, discrepancy_count, response_json, shipment_id
            FROM analyses
            WHERE shipment_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (shipment_id,),
        )
        row = cursor.fetchone()
    if not row:
        return None
    data = dict(row)
    return {
        "id": data["id"],
        "created_at": data["created_at"],
        "mode": data["mode"],
        "model": data["model"],
        "status": data["status"],
        "headline": data["headline"],
        "document_count": data["document_count"],
        "filenames": json.loads(data["filenames_json"]),
        "discrepancy_count": data["discrepancy_count"],
        "response_data": json.loads(data["response_json"]),
        "shipment_id": data["shipment_id"],
    }


def get_analysis_by_id(analysis_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT response_json FROM analyses WHERE id = ?",
            (analysis_id,),
        )
        row = cursor.fetchone()
    if row:
        return json.loads(row["response_json"])
    return None


def delete_analysis_by_id(analysis_id: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,))
        conn.commit()
        return cursor.rowcount > 0
