import os
import shutil
import sqlite3
import hashlib
from datetime import datetime, timezone

WORKSPACE_ROOT = r"C:\Users\RAHUL\Desktop\gautam\tradesathi-ai"
LIVE_DB_PATH = os.path.join(WORKSPACE_ROOT, "backend", "tradesathi.db")
SCRATCH_DIR = r"C:\Users\RAHUL\.gemini\antigravity-ide\brain\9cf2773f-75ef-4375-9081-60405096f5cd\scratch"
CLONE_DB_PATH = os.path.join(SCRATCH_DIR, "phase5_migration_clone.db")
RESTORE_TEST_PATH = os.path.join(SCRATCH_DIR, "phase5_restore_test.db")
DOC_STORAGE_PATH = os.path.join(WORKSPACE_ROOT, "backend", "storage", "documents")

def get_file_hash(path):
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def get_row_counts(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    counts = {}
    tables = [
        "shipments", "documents", "analyses", "finding_reviews", "sales_orders",
        "sales_dispatches", "inventory_movements", "erp_audit_logs",
        "export_shipment_dispatches", "export_checklist_rules", "export_shipment_checklist_items"
    ]
    for tbl in tables:
        try:
            cur = conn.execute(f"SELECT COUNT(*) as cnt FROM {tbl}")
            counts[tbl] = cur.fetchone()["cnt"]
        except sqlite3.OperationalError:
            counts[tbl] = "TABLE_NOT_EXIST"
    conn.close()
    return counts

def main():
    print("=== Phase 5 Migration & Preservation Verification ===")
    
    # 1. Baseline metadata of live DB
    live_size = os.path.getsize(LIVE_DB_PATH)
    live_hash = get_file_hash(LIVE_DB_PATH)
    print(f"Live DB Path: {LIVE_DB_PATH}")
    print(f"Live DB Size: {live_size} bytes")
    print(f"Live DB SHA256: {live_hash}")
    
    # Baseline document storage metadata
    doc_files = []
    if os.path.exists(DOC_STORAGE_PATH):
        for f in os.listdir(DOC_STORAGE_PATH):
            fp = os.path.join(DOC_STORAGE_PATH, f)
            if os.path.isfile(fp):
                doc_files.append((f, os.path.getsize(fp), get_file_hash(fp)))
    print(f"Document storage files count: {len(doc_files)}")
    
    # 2. Baseline row counts on LIVE DB (READ-ONLY)
    baseline_counts = get_row_counts(LIVE_DB_PATH)
    print("\nBaseline Row Counts (Live DB):")
    for k, v in baseline_counts.items():
        print(f"  {k}: {v}")
        
    # 3. Clone populated database to isolated scratch location
    if os.path.exists(CLONE_DB_PATH):
        os.remove(CLONE_DB_PATH)
    shutil.copy2(LIVE_DB_PATH, CLONE_DB_PATH)
    print(f"\nCloned Live DB to isolated scratch: {CLONE_DB_PATH}")
    
    # 4. Run migration (init_db) against clone
    # Set TRADESATHI_DB_PATH env var to target the clone
    os.environ["TRADESATHI_DB_PATH"] = CLONE_DB_PATH
    import sys
    sys.path.insert(0, os.path.join(WORKSPACE_ROOT, "backend"))
    from app.db import init_db
    
    print("\n--- Running Migration on Clone (Pass 1) ---")
    init_db()
    
    print("\n--- Running Migration on Clone (Pass 2 - Idempotency Check) ---")
    init_db()
    
    # 5. Verify integrity_check and foreign_key_check on clone
    clone_conn = sqlite3.connect(CLONE_DB_PATH)
    clone_conn.row_factory = sqlite3.Row
    
    integrity = clone_conn.execute("PRAGMA integrity_check").fetchall()
    fk_check = clone_conn.execute("PRAGMA foreign_key_check").fetchall()
    
    integrity_ok = len(integrity) == 1 and integrity[0][0] == "ok"
    fk_ok = len(fk_check) == 0
    print(f"\nClone SQLite PRAGMA integrity_check: {'PASS (ok)' if integrity_ok else integrity}")
    print(f"Clone SQLite PRAGMA foreign_key_check: {'PASS (0 violations)' if fk_ok else fk_check}")
    
    # 6. Post-migration row counts on clone
    post_counts = get_row_counts(CLONE_DB_PATH)
    print("\nPost-Migration Row Counts on Clone:")
    for k, v in post_counts.items():
        print(f"  {k}: {v}")
        
    # Check that historical rows were strictly preserved
    historical_tables = ["shipments", "documents", "analyses", "finding_reviews", "sales_orders", "sales_dispatches", "inventory_movements", "erp_audit_logs"]
    all_preserved = True
    for tbl in historical_tables:
        before = baseline_counts.get(tbl, 0)
        after = post_counts.get(tbl, 0)
        if before != after:
            print(f"ERROR: Row count mismatch on {tbl}: before={before}, after={after}")
            all_preserved = False
        else:
            print(f"  Verified {tbl}: {before} -> {after} (PRESERVED)")
            
    # Verify new export tables were created and populated
    print(f"  Export checklist rules seeded: {post_counts.get('export_checklist_rules')} rules")
    
    # 7. Test restore only into isolated destinations
    print("\n--- Testing Restore to Isolated Scratch Destination ---")
    if os.path.exists(RESTORE_TEST_PATH):
        os.remove(RESTORE_TEST_PATH)
    shutil.copy2(CLONE_DB_PATH, RESTORE_TEST_PATH)
    restore_counts = get_row_counts(RESTORE_TEST_PATH)
    restore_conn = sqlite3.connect(RESTORE_TEST_PATH)
    restore_integrity = restore_conn.execute("PRAGMA integrity_check").fetchone()[0]
    restore_conn.close()
    print(f"Restored DB Integrity: {restore_integrity}")
    print(f"Restored DB Shipments: {restore_counts.get('shipments')}, Documents: {restore_counts.get('documents')}")
    
    # 8. Re-check Live DB and storage files to confirm ZERO changes during testing
    live_size_after = os.path.getsize(LIVE_DB_PATH)
    live_hash_after = get_file_hash(LIVE_DB_PATH)
    live_untouched = (live_size == live_size_after) and (live_hash == live_hash_after)
    print(f"\nLive DB Untouched Verification:")
    print(f"  Before SHA256: {live_hash}")
    print(f"  After  SHA256: {live_hash_after}")
    print(f"  Status: {'PASSED (Zero Writes to Live DB)' if live_untouched else 'FAILED (Live DB Modified!)'}")
    
    doc_storage_untouched = True
    for fname, fsize, fhash in doc_files:
        fp = os.path.join(DOC_STORAGE_PATH, fname)
        if not os.path.exists(fp) or os.path.getsize(fp) != fsize or get_file_hash(fp) != fhash:
            doc_storage_untouched = False
            break
    print(f"Live Storage Untouched Verification: {'PASSED (All Hashes Identical)' if doc_storage_untouched else 'FAILED'}")

if __name__ == "__main__":
    main()
