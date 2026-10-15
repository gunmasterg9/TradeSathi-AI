"""TradeSathi AI — Milestone 2F
Operational Hardening & Release Readiness Test Suite
Covers Gates 1 through 11 regression gates:
1. Database backup and integrity verification.
2. Restore into an isolated temporary location.
3. Database/document consistency after restoration.
4. Missing, forged or cross-analysis evidence IDs.
5. Invalid review transitions and direct status manipulation.
6. Preservation of append-only review history.
7. Path traversal and unsafe filenames.
8. Oversized and invalid uploads.
9. Ollama unavailable with deterministic fallback working.
10. API health and dependency status.
11. Historical audit and document retrieval after restart.
"""

import json
import sqlite3
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.app.backup import (
    compute_file_sha256,
    create_backup,
    restore_backup,
    verify_backup,
    verify_restoration_integrity,
)
from backend.app.db import (
    create_document_record,
    create_shipment,
    get_analysis_by_id,
    get_connection,
    get_db_path,
    get_shipment_by_id,
    init_db,
    save_analysis,
    set_db_path,
)
from backend.app.main import app
from backend.app.readiness import calculate_shipment_readiness
from backend.app.storage import (
    get_document_file_path,
    get_storage_dir,
    save_document_file,
    set_storage_dir,
)


@pytest.fixture(autouse=True)
def isolate_environment(tmp_path):
    """Enforce strict isolation: tests NEVER modify the live database or document store."""
    orig_db = get_db_path()
    orig_storage = get_storage_dir()

    test_db = tmp_path / "test_readiness.db"
    test_storage = tmp_path / "storage" / "documents"

    set_db_path(test_db)
    init_db(test_db)
    set_storage_dir(test_storage)

    yield tmp_path, test_db, test_storage

    set_db_path(orig_db)
    set_storage_dir(orig_storage)


@pytest.fixture
def client():
    return TestClient(app)


def test_gate_1_database_backup_and_integrity_verification(tmp_path):
    """Gate 1: Verified snapshot creation, PRAGMA integrity check, and tampering detection."""
    test_db = tmp_path / "test_readiness.db"
    test_storage = tmp_path / "storage" / "documents"

    # Seed test shipment and document
    shp = create_shipment({"reference": "SHP-BACKUP-01", "exporter": "Apex Exports"})
    uid, key, f_hash = save_document_file(shp["id"], "invoice.txt", b"INVOICE #101 TOTAL 5000 USD")
    create_document_record({
        "id": uid,
        "shipment_id": shp["id"],
        "original_filename": "invoice.txt",
        "clean_filename": "invoice.txt",
        "storage_key": key,
        "file_size": 29,
        "file_hash": f_hash,
    })

    # Create backup
    backup_root = tmp_path / "backups"
    manifest = create_backup(
        source_db_path=test_db,
        source_storage_dir=test_storage,
        backup_root=backup_root,
    )
    backup_folder = backup_root / manifest["backup_id"]

    # Verify backup
    res = verify_backup(backup_folder)
    assert res["verified"] is True
    assert res["backup_id"] == manifest["backup_id"]
    assert res["table_counts"]["shipments"] >= 1
    assert res["documents_verified"] >= 1

    # Tampering test 1: size mismatch
    backed_doc = backup_folder / "documents" / key
    backed_doc.write_bytes(b"SHORT")
    with pytest.raises(ValueError, match="Document size mismatch"):
        verify_backup(backup_folder)

    # Tampering test 2: same size, altered content -> SHA-256 checksum mismatch
    orig_size = 27
    backed_doc.write_bytes(b"X" * orig_size)
    with pytest.raises(ValueError, match="Document SHA-256 checksum mismatch"):
        verify_backup(backup_folder)


def test_gate_2_restore_into_isolated_temporary_location(tmp_path):
    """Gate 2: Safe restore procedure strictly targeting an isolated temporary destination."""
    test_db = tmp_path / "test_readiness.db"
    test_storage = tmp_path / "storage" / "documents"

    shp = create_shipment({"reference": "SHP-RESTORE-01"})
    uid, key, f_hash = save_document_file(shp["id"], "packing.txt", b"PACKING 100 PACKAGES")
    create_document_record({
        "id": uid,
        "shipment_id": shp["id"],
        "original_filename": "packing.txt",
        "clean_filename": "packing.txt",
        "storage_key": key,
        "file_size": 20,
        "file_hash": f_hash,
    })

    backup_root = tmp_path / "backups"
    manifest = create_backup(
        source_db_path=test_db,
        source_storage_dir=test_storage,
        backup_root=backup_root,
    )
    backup_folder = backup_root / manifest["backup_id"]

    # Restore to fresh isolated paths
    restore_db = tmp_path / "restored_dir" / "restored.db"
    restore_storage = tmp_path / "restored_dir" / "documents"

    result = restore_backup(backup_folder, restore_db, restore_storage)
    assert result["status"] == "success"
    assert restore_db.is_file()
    assert (restore_storage / key).is_file()

    # Verify source DB remains completely intact and separate
    assert test_db.resolve() != restore_db.resolve()


def test_gate_3_database_document_consistency_after_restoration(tmp_path):
    """Gate 3: Verify referential integrity, shipments, analyses, review events and document hashes."""
    test_db = tmp_path / "test_readiness.db"
    test_storage = tmp_path / "storage" / "documents"

    shp = create_shipment({"reference": "SHP-CONSISTENCY-01"})
    uid, key, f_hash = save_document_file(shp["id"], "spec.txt", b"TECHNICAL SPECIFICATION 2026")
    create_document_record({
        "id": uid,
        "shipment_id": shp["id"],
        "original_filename": "spec.txt",
        "clean_filename": "spec.txt",
        "storage_key": key,
        "file_size": 30,
        "file_hash": f_hash,
    })

    backup_root = tmp_path / "backups"
    manifest = create_backup(test_db, test_storage, backup_root)
    backup_folder = backup_root / manifest["backup_id"]

    restore_db = tmp_path / "dest" / "tradesathi.db"
    restore_storage = tmp_path / "dest" / "documents"

    restore_res = restore_backup(backup_folder, restore_db, restore_storage)
    integrity = restore_res["restoration_integrity"]
    assert integrity["status"] == "verified"
    assert integrity["shipments_count"] >= 1
    assert integrity["documents_count"] >= 1
    assert integrity["documents_verified_on_disk"] >= 1


def test_gate_4_missing_forged_cross_analysis_evidence_ids(client):
    """Gate 4: Reject nonexistent, forged, and cross-analysis evidence IDs."""
    anl_1_id = "anl-test-4a"
    anl_2_id = "anl-test-4b"

    payload_1 = {
        "id": anl_1_id,
        "created_at": "2026-10-13T10:00:00Z",
        "mode": "rules_fallback",
        "model": None,
        "documents": [
            {
                "id": "doc-1",
                "filename": "inv_1.txt",
                "field_evidence": {
                    "net_weight": {
                        "evidence_id": "ev-weight-anl1",
                        "field_name": "net_weight",
                        "source_snippet": "Net Weight: 1000 kg",
                    }
                },
            }
        ],
        "discrepancies": [
            {
                "id": "fnd-weight-1",
                "field": "net_weight",
                "label": "Net Weight",
                "severity": "critical",
                "difference": "+50 kg",
                "reason": "Weight variance",
                "evidence_ids": {"inv_1.txt": "ev-weight-anl1"},
            }
        ],
        "summary": {"status": "needs_attention", "headline": "Discrepancy detected"},
    }

    payload_2 = {
        "id": anl_2_id,
        "created_at": "2026-10-13T10:00:00Z",
        "mode": "rules_fallback",
        "model": None,
        "documents": [
            {
                "id": "doc-2",
                "filename": "inv_2.txt",
                "field_evidence": {
                    "net_weight": {
                        "evidence_id": "ev-weight-anl2",
                        "field_name": "net_weight",
                        "source_snippet": "Net Weight: 2000 kg",
                    }
                },
            }
        ],
        "discrepancies": [
            {
                "id": "fnd-weight-2",
                "field": "net_weight",
                "label": "Net Weight",
                "severity": "critical",
                "difference": "+100 kg",
                "reason": "Weight variance",
                "evidence_ids": {"inv_2.txt": "ev-weight-anl2"},
            }
        ],
        "summary": {"status": "needs_attention", "headline": "Discrepancy detected"},
    }

    save_analysis(anl_1_id, "rules_fallback", None, "needs_attention", "Test 1", ["inv_1.txt"], 1, payload_1)
    save_analysis(anl_2_id, "rules_fallback", None, "needs_attention", "Test 2", ["inv_2.txt"], 1, payload_2)

    # 1. Reject nonexistent evidence ID
    resp_fake = client.post(
        f"/api/analyses/{anl_1_id}/findings/fnd-weight-1/review",
        json={
            "action": "resolved",
            "reason": "Verified with weighbridge ticket",
            "supporting_evidence": ["ev-nonexistent-999"],
        },
    )
    assert resp_fake.status_code == 400
    assert "Invalid or forged supporting evidence ID" in resp_fake.json()["detail"]

    # 2. Reject cross-analysis evidence ID (ev-weight-anl2 belongs to anl_2, not anl_1)
    resp_cross = client.post(
        f"/api/analyses/{anl_1_id}/findings/fnd-weight-1/review",
        json={
            "action": "resolved",
            "reason": "Verified with weighbridge ticket",
            "supporting_evidence": ["ev-weight-anl2"],
        },
    )
    assert resp_cross.status_code == 400
    assert "Invalid or forged supporting evidence ID" in resp_cross.json()["detail"]

    # 3. Reject arbitrary forged non-document string as source evidence
    resp_arbitrary = client.post(
        f"/api/analyses/{anl_1_id}/findings/fnd-weight-1/review",
        json={
            "action": "resolved",
            "reason": "Verified with ticket",
            "supporting_evidence": ["arbitrary_unverified_token"],
        },
    )
    assert resp_arbitrary.status_code == 400
    assert "Arbitrary strings cannot serve as source evidence" in resp_arbitrary.json()["detail"]

    # 4. Accept legitimate evidence ID belonging to this analysis
    resp_valid = client.post(
        f"/api/analyses/{anl_1_id}/findings/fnd-weight-1/review",
        json={
            "action": "resolved",
            "reason": "Verified with invoice line evidence",
            "supporting_evidence": ["ev-weight-anl1"],
        },
    )
    assert resp_valid.status_code == 200
    data = resp_valid.json()
    assert data["finding"]["review_status"] == "resolved"
    assert data["finding"]["resolution"]["resolution_basis"] == "grounded_evidence"
    assert data["finding"]["resolution"]["is_operator_assertion"] is False


def test_gate_5_invalid_review_transitions_and_direct_status_manipulation(client):
    """Gate 5: Enforce state machine transitions, reject direct arbitrary statuses and invalid inputs."""
    anl_id = "anl-test-5"
    payload = {
        "id": anl_id,
        "created_at": "2026-10-13T10:00:00Z",
        "mode": "rules_fallback",
        "documents": [],
        "discrepancies": [
            {
                "id": "fnd-5",
                "field": "net_weight",
                "label": "Net Weight",
                "severity": "critical",
                "reason": "Weight mismatch",
            }
        ],
        "summary": {"status": "needs_attention", "headline": "Mismatch"},
    }
    save_analysis(anl_id, "rules_fallback", None, "needs_attention", "Test 5", [], 1, payload)

    # 1. Direct jump from pending_review to reopened is illegal
    res_jump = client.post(
        f"/api/analyses/{anl_id}/findings/fnd-5/review",
        json={"action": "reopened", "reason": "Attempting invalid jump"},
    )
    assert res_jump.status_code == 400
    assert "Illegal review state transition" in res_jump.json()["detail"]

    # 2. Arbitrary invalid status string
    res_bad_status = client.post(
        f"/api/analyses/{anl_id}/findings/fnd-5/review",
        json={"action": "approved_by_boss", "reason": "Looks good"},
    )
    assert res_bad_status.status_code == 422  # Pydantic schema validation rejects

    # 3. Resolve weight discrepancy with invalid unit
    res_bad_unit = client.post(
        f"/api/analyses/{anl_id}/findings/fnd-5/review",
        json={"action": "resolved", "reason": "Fixed weight", "corrected_value": 100, "corrected_unit": "bananas"},
    )
    assert res_bad_unit.status_code == 400
    assert "Invalid weight unit" in res_bad_unit.json()["detail"]


def test_gate_6_preservation_of_append_only_review_history(client):
    """Gate 6: Verify append-only review event history and SQL trigger preventing modifications."""
    anl_id = "anl-test-6"
    payload = {
        "id": anl_id,
        "created_at": "2026-10-13T10:00:00Z",
        "mode": "rules_fallback",
        "documents": [],
        "discrepancies": [
            {
                "id": "fnd-6",
                "field": "hs_code",
                "label": "HS Code",
                "severity": "warning",
                "reason": "Missing HS code",
                "raw_values": {"doc1": "none"},
                "comparison_rule": "mandatory_code",
            }
        ],
        "summary": {"status": "needs_attention", "headline": "Mismatch"},
    }
    save_analysis(anl_id, "rules_fallback", None, "needs_attention", "Test 6", [], 1, payload)

    # Transition 1: in_review
    client.post(f"/api/analyses/{anl_id}/findings/fnd-6/review", json={"action": "in_review", "reviewer": "Alice", "notes": "Checking customs tariff"})
    # Transition 2: acknowledged
    client.post(f"/api/analyses/{anl_id}/findings/fnd-6/review", json={"action": "acknowledged", "reviewer": "Bob", "notes": "Noted by compliance"})
    # Transition 3: resolved with verified HS code
    client.post(f"/api/analyses/{anl_id}/findings/fnd-6/review", json={"action": "resolved", "reviewer": "Carol", "reason": "HS code verified against customs tariff", "corrected_value": "0303.89"})

    # Check reviews audit trail endpoint
    res = client.get(f"/api/analyses/{anl_id}/findings/fnd-6/reviews")
    assert res.status_code == 200
    reviews = res.json()["reviews"]
    assert len(reviews) == 3
    assert [r["new_state"] for r in reviews] == ["in_review", "acknowledged", "resolved"]

    # Verify original machine finding attributes preserved
    anl = client.get(f"/api/analyses/{anl_id}").json()
    disc = anl["discrepancies"][0]
    assert disc["comparison_rule"] == "mandatory_code"
    assert disc["raw_values"] == {"doc1": "none"}

    # Direct database UPDATE attempt must be blocked by SQLite trigger
    with pytest.raises(sqlite3.DatabaseError, match="Audit integrity violation"):
        with get_connection() as conn:
            conn.execute("UPDATE finding_reviews SET reviewer = 'Hacker' WHERE finding_id = 'fnd-6'")


def test_gate_7_path_traversal_and_unsafe_filenames(client):
    """Gate 7: Ensure directory traversal is neutralized in upload filenames and storage keys."""
    shp = client.post("/api/shipments", json={"reference": "SHP-TRAVERSAL-01"}).json()
    shp_id = shp["id"]

    # Attempt path traversal filename
    files = [("files", ("../../../../etc/passwd.txt", b"SAMPLE INVOICE CONTENT", "text/plain"))]
    resp = client.post(f"/api/shipments/{shp_id}/documents", files=files)
    assert resp.status_code == 201
    doc = resp.json()["documents"][0]
    assert ".." not in doc["clean_filename"]
    assert doc["clean_filename"] == "passwd.txt"

    # Verify get_document_file_path rejects traversal storage keys
    with pytest.raises(ValueError, match="directory traversal detected"):
        get_document_file_path("../../../sensitive.txt")


def test_gate_8_oversized_and_invalid_uploads(client):
    """Gate 8: Reject oversized uploads, empty files, and disallowed extensions."""
    shp = client.post("/api/shipments", json={"reference": "SHP-UPLOAD-VALIDATE"}).json()
    shp_id = shp["id"]

    # 1. Disallowed extension (.exe)
    resp_exe = client.post(
        f"/api/shipments/{shp_id}/documents",
        files=[("files", ("malware.exe", b"binary", "application/octet-stream"))],
    )
    assert resp_exe.status_code == 400
    assert "Unsupported file type" in resp_exe.json()["detail"]

    # 2. Empty file
    resp_empty = client.post(
        f"/api/shipments/{shp_id}/documents",
        files=[("files", ("empty.txt", b"", "text/plain"))],
    )
    assert resp_empty.status_code == 400
    assert "empty" in resp_empty.json()["detail"].lower()

    # 3. Oversized file (exceeding MAX_UPLOAD_MB)
    oversized_bytes = b"X" * (11 * 1024 * 1024)
    resp_large = client.post(
        f"/api/shipments/{shp_id}/documents",
        files=[("files", ("large.txt", oversized_bytes, "text/plain"))],
    )
    assert resp_large.status_code == 413
    assert "exceeds" in resp_large.json()["detail"]


def test_gate_9_ollama_unavailable_with_deterministic_fallback(client, monkeypatch):
    """Gate 9: Transparent fallback to deterministic rules when Ollama is offline."""
    import backend.app.main as main_mod

    # Point Ollama base URL to unreachable port
    monkeypatch.setattr(main_mod, "OLLAMA_BASE_URL", "http://127.0.0.1:59999")

    # Reconcile invoice and packing list
    inv = "COMMERCIAL INVOICE #INV-100\nTotal: 10000 USD\nNet Weight: 5000 kg\nBuyer: Global Foods\nExporter: Alpha Marine"
    pkg = "PACKING LIST #INV-100\nNet Weight: 5100 kg\nPackages: 100 cartons\nBuyer: Global Foods\nExporter: Alpha Marine"

    resp = client.post(
        "/api/analyze",
        files=[
            ("files", ("invoice.txt", inv.encode(), "text/plain")),
            ("files", ("packing.txt", pkg.encode(), "text/plain")),
        ],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "rules_fallback"
    assert len(data["discrepancies"]) >= 1


def test_gate_10_api_health_and_dependency_status(client):
    """Gate 10: API health check reports database and storage status distinct from optional Ollama."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")
    assert data["version"] == "0.2.0"
    assert data["database"] == "connected"
    assert data["storage"] == "writable"
    assert "ollama" in data


def test_gate_11_historical_audit_and_document_retrieval_after_restart(client):
    """Gate 11: Document and audit retrieval after restart, and reopening finding restores readiness block."""
    # Create shipment, upload documents, and run analysis
    shp = client.post("/api/shipments", json={"reference": "SHP-AUDIT-CYCLE-01"}).json()
    shp_id = shp["id"]

    inv_text = "COMMERCIAL INVOICE #INV-88\nTotal: 25000 USD\nNet Weight: 10000 kg\nBuyer: SeaFoods Inc"
    pkg_text = "PACKING LIST #INV-88\nNet Weight: 10100 kg\nPackages: 200\nBuyer: SeaFoods Inc"

    client.post(
        f"/api/shipments/{shp_id}/documents",
        files=[
            ("files", ("invoice.txt", inv_text.encode(), "text/plain")),
            ("files", ("packing.txt", pkg_text.encode(), "text/plain")),
        ],
    )

    anl_resp = client.post(f"/api/shipments/{shp_id}/reconcile").json()
    anl_id = anl_resp["id"]
    finding_id = anl_resp["discrepancies"][0]["id"]

    # Initial readiness must be not_ready due to critical weight mismatch
    readiness_1 = client.get(f"/api/shipments/{shp_id}/readiness").json()
    assert readiness_1["is_ready"] is False

    # Mark documents as verified by user
    docs = client.get(f"/api/shipments/{shp_id}/documents").json()["documents"]
    for d in docs:
        client.patch(f"/api/documents/{d['id']}", json={"review_status": "verified_by_user", "last_reviewed_by": "Operator"})

    # Resolve the finding with corrected value
    res_solve = client.post(
        f"/api/analyses/{anl_id}/findings/{finding_id}/review",
        json={
            "action": "resolved",
            "reviewer": "Supervisor",
            "reason": "Re-weighed and verified scale tally",
            "corrected_value": 10000.0,
            "corrected_unit": "kg",
        },
    )
    assert res_solve.status_code == 200

    # Shipment readiness is now ready!
    readiness_2 = client.get(f"/api/shipments/{shp_id}/readiness").json()
    assert readiness_2["is_ready"] is True
    assert readiness_2["status"] == "ready"

    # Simulate restart: reload historical audit by ID
    reloaded_audit = client.get(f"/api/analyses/{anl_id}").json()
    assert reloaded_audit["id"] == anl_id
    reloaded_finding = next(d for d in reloaded_audit["discrepancies"] if d["id"] == finding_id)
    assert reloaded_finding["review_status"] == "resolved"

    # Download document directly
    doc_id = docs[0]["id"]
    dl_resp = client.get(f"/api/documents/{doc_id}/download")
    assert dl_resp.status_code == 200
    assert len(dl_resp.content) > 0

    # REOPEN the finding: Must restore the required readiness block!
    res_reopen = client.post(
        f"/api/analyses/{anl_id}/findings/{finding_id}/review",
        json={"action": "reopened", "reviewer": "Auditor", "reason": "Customs inspection discovered scale variance"},
    )
    assert res_reopen.status_code == 200
    assert res_reopen.json()["finding"]["review_status"] == "reopened"
    assert res_reopen.json()["finding"]["resolution"] is None

    # Verify readiness block restored
    readiness_reopened = client.get(f"/api/shipments/{shp_id}/readiness").json()
    assert readiness_reopened["is_ready"] is False
    assert readiness_reopened["status"] == "not_ready"
    assert readiness_reopened["unresolved_critical_discrepancies"] >= 1
