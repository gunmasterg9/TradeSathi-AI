import hashlib
import os
import shutil
import sqlite3
import sys

from app.db import init_db

LIVE_DB_PATH = os.path.join(os.path.dirname(__file__), "tradesathi.db")
SCRATCH_DIR = r"C:\Users\RAHUL\.gemini\antigravity-ide\brain\9cf2773f-75ef-4375-9081-60405096f5cd\scratch"
CLONE_DB_PATH = os.path.join(SCRATCH_DIR, "phase6_migration_clone.db")

EXPECTED_SHA256 = "d16067b3369093b71457a4c22c1e0d5871e6d1201af6849a3efbfaad6090b0bf"

def get_file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def main():
    print("=" * 60)
    print("PHASE 6: INVOICING & FINANCE DATABASE MIGRATION VERIFICATION")
    print("=" * 60)

    # 1. Check live database existence and hash
    assert os.path.exists(LIVE_DB_PATH), f"Live DB not found at {LIVE_DB_PATH}"
    initial_live_sha256 = get_file_sha256(LIVE_DB_PATH)
    print(f"[1] Live DB SHA256 before test: {initial_live_sha256}")
    assert initial_live_sha256 == EXPECTED_SHA256, f"Live DB hash mismatch! Expected {EXPECTED_SHA256}, got {initial_live_sha256}"

    # 2. Inspect historical record counts in live DB
    with sqlite3.connect(LIVE_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        shipments_count = c.execute("SELECT COUNT(*) FROM shipments").fetchone()[0]
        documents_count = c.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        analyses_count = c.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
        reviews_count = c.execute("SELECT COUNT(*) FROM finding_reviews").fetchone()[0]
        print(f"[2] Live DB baseline counts: Shipments={shipments_count}, Documents={documents_count}, Analyses={analyses_count}, Reviews={reviews_count}")

    # 3. Clone live DB to scratch
    os.makedirs(SCRATCH_DIR, exist_ok=True)
    if os.path.exists(CLONE_DB_PATH):
        os.remove(CLONE_DB_PATH)
    shutil.copy2(LIVE_DB_PATH, CLONE_DB_PATH)
    clone_sha256 = get_file_sha256(CLONE_DB_PATH)
    assert clone_sha256 == initial_live_sha256
    print(f"[3] Created isolated clone at {CLONE_DB_PATH}")

    # 4. Apply additive migration (init_db) on clone - Pass 1
    init_db(CLONE_DB_PATH)
    print("[4] Applied init_db (migration) pass 1 to clone")

    # 5. Apply additive migration (init_db) on clone - Pass 2 (Idempotency)
    init_db(CLONE_DB_PATH)
    print("[5] Applied init_db (migration) pass 2 (idempotency check) to clone")

    # 6. Verify integrity and foreign keys on clone
    with sqlite3.connect(CLONE_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        integrity = c.execute("PRAGMA integrity_check").fetchone()[0]
        assert integrity == "ok", f"Integrity check failed: {integrity}"
        fk_check = c.execute("PRAGMA foreign_key_check").fetchall()
        assert len(fk_check) == 0, f"Foreign key check failed: {fk_check}"
        print(f"[6] Clone PRAGMA integrity_check: {integrity}, foreign_key_check: {len(fk_check)} violations")

        # 7. Verify new Phase 6 tables exist in clone
        phase6_tables = [
            "customer_invoices",
            "customer_invoice_items",
            "customer_payments",
            "customer_payment_allocations",
            "customer_credit_notes",
            "customer_credit_note_items"
        ]
        existing_tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        for t in phase6_tables:
            assert t in existing_tables, f"Missing table {t} in migrated clone!"
        print(f"[7] Verified all {len(phase6_tables)} Phase 6 tables exist in clone schema")

        # 8. Verify historical baseline preserved in clone
        c_shipments = c.execute("SELECT COUNT(*) FROM shipments").fetchone()[0]
        c_documents = c.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        c_analyses = c.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
        c_reviews = c.execute("SELECT COUNT(*) FROM finding_reviews").fetchone()[0]
        assert c_shipments == shipments_count, f"Shipments count changed: {c_shipments} vs {shipments_count}"
        assert c_documents == documents_count, f"Documents count changed: {c_documents} vs {documents_count}"
        assert c_analyses == analyses_count, f"Analyses count changed: {c_analyses} vs {analyses_count}"
        assert c_reviews == reviews_count, f"Reviews count changed: {c_reviews} vs {reviews_count}"
        print(f"[8] Historical counts preserved: Shipments={c_shipments}, Documents={c_documents}, Analyses={c_analyses}, Reviews={c_reviews}")

    # 9. Verify live DB was NOT modified
    final_live_sha256 = get_file_sha256(LIVE_DB_PATH)
    print(f"[9] Live DB SHA256 after migration test: {final_live_sha256}")
    assert final_live_sha256 == initial_live_sha256, "CRITICAL: Live DB was altered!"
    print("=" * 60)
    print("MIGRATION TEST PASSED: Live database 100% untouched and additive schema is valid!")
    print("=" * 60)

if __name__ == "__main__":
    main()
