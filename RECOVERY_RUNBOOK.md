# TradeSathi AI — Disaster Recovery Runbook & Verification Guide
**Phase 10: Operational Hardening & Production Recovery Reference**

---

## 1. Overview & Purpose

This runbook defines the disaster recovery (DR) procedures for TradeSathi AI. It details:
1. How to run the **Automated Disaster Recovery Verification Drill** (`scripts\test-recovery.ps1`).
2. How to interpret the drill's status codes and generated reports.
3. How to perform an **isolated manual restore drill** without touching live data.
4. How to investigate and resolve recovery discrepancies.
5. How to perform an **authorized production restore** only after an explicit operator sign-off.

---

## 2. Critical Safety Principles

> [!CAUTION]
> **Zero Live Data Modification Guarantee:**
> - Never overwrite, delete, reset, migrate, or modify `backend\tradesathi.db` during recovery testing.
> - Never overwrite, modify, or delete the live document directory (`backend\storage\documents\`).
> - Never execute write requests (`POST`, `PUT`, `PATCH`, `DELETE`) against the production server on port 8000 during a drill.
> - Automated drills MUST target an isolated recovery test instance (default `http://127.0.0.1:8001`).
> - Destructive operations or production restores require explicit operator confirmation.

---

## 3. Automated Recovery Drill Execution

### A. Quick Start (PowerShell)

From the project root:

```powershell
.\scripts\test-recovery.ps1
```

Or with explicit custom paths and endpoints:

```powershell
.\scripts\test-recovery.ps1 `
    -BackupPath "backend\backups\backup_20261013_131946_d599fd" `
    -RestoredDbPath "C:\Users\RAHUL\AppData\Local\Temp\tradesathi-restore-test-20261013-190724\tradesathi-test.db" `
    -RestoredStorageDir "C:\Users\RAHUL\AppData\Local\Temp\tradesathi-restore-test-20261013-190724\documents" `
    -RecoveryUrl "http://127.0.0.1:8001" `
    -OutputDir "reports\recovery"
```

To run both the disaster recovery drill and the codebase regression test suite (backend pytest, frontend tests, frontend production build):

```powershell
.\scripts\test-recovery.ps1 -RunRegressionSuite
```

### B. Python Direct Runner Alternative

Operators can also invoke the Python verification engine directly:

```bash
python -m backend.app.recovery_verifier \
    --backup-path backend/backups/backup_20261013_131946_d599fd \
    --restored-db "C:\Users\RAHUL\AppData\Local\Temp\tradesathi-restore-test-20261013-190724\tradesathi-test.db" \
    --restored-storage "C:\Users\RAHUL\AppData\Local\Temp\tradesathi-restore-test-20261013-190724\documents" \
    --recovery-url "http://127.0.0.1:8001" \
    --output-dir "reports/recovery" \
    --run-regression-suite
```

---

## 4. Arguments and Prerequisites

| Argument | Default Value | Description |
|---|---|---|
| `-BackupPath` | `backend\backups\backup_20261013_131946_d599fd` | Verified backup snapshot folder containing `manifest.json`, `tradesathi.db`, and `documents/`. |
| `-RestoredDbPath` | `...\tradesathi-test.db` | Full path to restored SQLite database in isolated temporary folder. |
| `-RestoredStorageDir` | `...\documents` | Full path to restored documents in isolated temporary folder. |
| `-RecoveryUrl` | `http://127.0.0.1:8001` | Base URL of isolated recovery backend server. |
| `-OutputDir` | `reports\recovery` | Output directory for timestamped Markdown and JSON reports. |
| `-RunRegressionSuite` | `False` | Switch flag to execute existing backend/frontend test suites and production build. |

### Prerequisites
1. **Isolated Restoration Location:** Backup extracted into an isolated directory (e.g. in `%TEMP%` or disposable scratch directory).
2. **Isolated Recovery Server:** An isolated FastAPI backend process running on port 8001 pointed at the isolated paths:
   ```powershell
   $env:TRADESATHI_DB_PATH = "C:\Users\RAHUL\AppData\Local\Temp\tradesathi-restore-test-20261013-190724\tradesathi-test.db"
   $env:TRADESATHI_STORAGE_PATH = "C:\Users\RAHUL\AppData\Local\Temp\tradesathi-restore-test-20261013-190724\documents"
   uvicorn app.main:app --app-dir backend --port 8001 --host 127.0.0.1
   ```

---

## 5. Interpreting Status Codes

The test runner categorizes both individual checks and the overall drill verdict:

### Individual Check Statuses
- **`PASS`**: Check executed successfully and all assertions (hashes, counts, HTTP status, payload structure) matched expected values.
- **`WARN`**: Check succeeded with non-critical observation (e.g. row count variance from snapshot baseline, or Ollama offline with active deterministic fallback).
- **`FAIL`**: Check failed assertion (e.g. SHA-256 mismatch, SQLite corruption, missing document).
- **`BLOCKED`**: Check could not execute (e.g. test server unreachable, path does not exist).

---

## 6. Isolated Manual Restore Drill Procedure

### Step 1: Create an Isolated Working Directory
```powershell
$TargetDir = "$env:TEMP\tradesathi-restore-test-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
New-Item -ItemType Directory -Path $TargetDir -Force
```

### Step 2: Restore the Backup to Isolated Directory
```powershell
python -m backend.app.backup restore "backend\backups\backup_20261013_131946_d599fd" `
    --target-db "$TargetDir\tradesathi-test.db" `
    --target-storage "$TargetDir\documents"
```

### Step 3: Run Integrity and Foreign Key Checks
```bash
python -c "import sqlite3; conn = sqlite3.connect('$TargetDir/tradesathi-test.db'); print('Integrity:', conn.execute('PRAGMA integrity_check').fetchall()); print('Foreign Keys:', conn.execute('PRAGMA foreign_key_check').fetchall()); conn.close()"
```

### Step 4: Start Isolated Test Backend on Port 8001
In a separate terminal:
```powershell
$env:TRADESATHI_DB_PATH = "$TargetDir\tradesathi-test.db"
$env:TRADESATHI_STORAGE_PATH = "$TargetDir\documents"
uvicorn app.main:app --app-dir backend --port 8001 --host 127.0.0.1
```

### Step 5: Verify Health Endpoints on Port 8001
```powershell
curl http://127.0.0.1:8001/health/live
curl http://127.0.0.1:8001/health/ready
```

---

## 7. Authorized Production Restoration Procedure

> [!CAUTION]
> **Zero Live Data Overwrite Without Quiescence:**
> Performing a restoration directly over an active, running application database (`backend/tradesathi.db`) will cause severe database corruption if active write locks or lingering WAL/SHM companion files (`tradesathi.db-wal`, `tradesathi.db-shm`) exist.
> Follow this procedure ONLY during a genuine disaster recovery incident with explicit stakeholder authorization and complete service write quiescence.

### 7.1 Restoration Workflow

1. **Obtain Operator Authorization:** Confirm disaster recovery declaration and Change Advisory Board (CAB) ticket.
2. **Ingress Quiescence (Stop External Traffic):**
   Switch Nginx reverse proxy to maintenance mode (HTTP 503) to prevent incoming write traffic:
   ```bash
   sudo ln -sf /etc/nginx/snippets/maintenance.conf /etc/nginx/sites-enabled/tradesathi.conf
   sudo nginx -s reload
   ```
3. **Service Quiescence (Stop Backend & Background Workers):**
   Terminate running backend workers on port 8000 and verify all file locks are released:
   ```bash
   sudo systemctl stop tradesathi.service
   sudo fuser backend/tradesathi.db || echo "Database locks cleared."
   ```
4. **Preserve Forensic Incident State (fail closed):** Complete this procedure before any restore. Recovery is prohibited if preservation is incomplete, a destination already exists, a copy command fails, or a copied hash/count differs from its source manifest. Record the incident identifier in the change record; never include credentials or secrets in the manifest.

    **Linux production (after Steps 2–3 have stopped the service and `fuser` reports no open database handles):**
    ```bash
    INCIDENT_ID="<approved-incident-id>" # e.g. INC-2026-001; required and unique
    FORENSIC_ROOT="/var/backups/tradesathi/forensic_incidents/${INCIDENT_ID}"
    SOURCE_DB="backend/tradesathi.db"
    SOURCE_DOCS="backend/storage/documents"
    test -n "$INCIDENT_ID" && test ! -e "$FORENSIC_ROOT" || { echo "Refusing unsafe forensic destination"; exit 1; }
    mkdir -p "$FORENSIC_ROOT" || exit 1
    required_bytes=$(du -sb "$SOURCE_DB" "$SOURCE_DOCS" 2>/dev/null | awk '{total += $1} END {print total}')
    available_bytes=$(df -PB1 "$FORENSIC_ROOT" | awk 'NR==2 {print $4}')
    test "${available_bytes:-0}" -ge "${required_bytes:-1}" || { echo "Insufficient forensic storage"; exit 1; }
    { sha256sum "$SOURCE_DB" | sed 's|  .*|  tradesathi.db|'; test ! -e "${SOURCE_DB}-wal" || sha256sum "${SOURCE_DB}-wal" | sed 's|  .*|  tradesathi.db-wal|'; test ! -e "${SOURCE_DB}-shm" || sha256sum "${SOURCE_DB}-shm" | sed 's|  .*|  tradesathi.db-shm|'; (cd "$SOURCE_DOCS" && find . -type f -print0 | sort -z | xargs -0 sha256sum | sed 's|  \./|  documents/|'); } > "$FORENSIC_ROOT/source.sha256" || exit 1
    wc -l < "$FORENSIC_ROOT/source.sha256" > "$FORENSIC_ROOT/source.file-count" || exit 1
    cp --preserve=mode,timestamps "$SOURCE_DB" "$FORENSIC_ROOT/tradesathi.db" || exit 1
    test ! -e "${SOURCE_DB}-wal" || cp --preserve=mode,timestamps "${SOURCE_DB}-wal" "$FORENSIC_ROOT/tradesathi.db-wal" || exit 1
    test ! -e "${SOURCE_DB}-shm" || cp --preserve=mode,timestamps "${SOURCE_DB}-shm" "$FORENSIC_ROOT/tradesathi.db-shm" || exit 1
    cp -a "$SOURCE_DOCS" "$FORENSIC_ROOT/documents" || exit 1
    (cd "$FORENSIC_ROOT" && sha256sum -c source.sha256) || exit 1
    test "$(find "$FORENSIC_ROOT" -type f ! -name 'source.sha256' ! -name 'source.file-count' | wc -l)" -eq "$(cat "$FORENSIC_ROOT/source.file-count")" || exit 1
    printf '{"incident_id":"%s","completed_at":"%s","source_db":"%s","source_documents":"%s","destination":"%s"}\n' "$INCIDENT_ID" "$(date --iso-8601=seconds)" "$SOURCE_DB" "$SOURCE_DOCS" "$FORENSIC_ROOT" > "$FORENSIC_ROOT/completion.json" || exit 1
    ```
    `completion.json` is written only after every required copy, hash verification, and count check succeeds. Do not move or delete WAL/SHM files: preservation copies them only after service quiescence. If a platform cannot provide the storage check, record that limitation and retain the fail-closed copy/hash/count checks.

    **Windows development (isolated or approved incident environment):** Use an empty, incident-specific destination and PowerShell's `Get-FileHash` / `Copy-Item -ErrorAction Stop` equivalents. Do not run Linux commands such as `fuser`, `df`, `cp`, or `chmod` in PowerShell. Confirm services are stopped through the Windows service/process controls before handling SQLite companion files, and retain a source/copy hash manifest plus a completion record only after verification.
5. **Verify Target Backup Snapshot:**
   Confirm integrity and SHA-256 hashes against `manifest.json` before touching production paths:
   ```bash
   python3 -m backend.app.backup verify <PATH_TO_BACKUP>
   ```
6. **Execute Controlled Application-Aware Restore:**
   ```bash
   python3 -m backend.app.backup restore <PATH_TO_BACKUP> \
       --target-db backend/tradesathi.db \
       --target-storage backend/storage/documents
    ```
    The restore first validates the backup manifest, then restores both assets into sibling staging paths and verifies SQLite integrity, foreign keys, table counts, document hashes, and database-to-document references. It retains the prior database and document directory under unique `.pre-restore-*` paths and writes a `.restore-*.json` journal beside the target database.

    Database and document directory replacement are **not a single atomic transaction**. If the process stops between the two replacements, keep maintenance mode enabled and inspect the journal. A `rollback_required` status means restore each existing `previous_db` / `previous_storage` path to its matching target path before restarting the application. A `rolled_back` status means the implementation restored the original pair, but the journal and failed candidates must be retained for investigation.
7. **Post-Restore Integrity & Foreign Key Verification:**
   ```bash
   python3 -c "
   import sqlite3
   conn = sqlite3.connect('file:backend/tradesathi.db?mode=ro', uri=True)
   c = conn.cursor()
   integrity = c.execute('PRAGMA integrity_check').fetchone()[0]
   fk = c.execute('PRAGMA foreign_key_check').fetchall()
   conn.close()
   assert integrity == 'ok', f'Integrity check failed: {integrity}'
   assert len(fk) == 0, f'Foreign key violations: {len(fk)}'
   print('Production database integrity and foreign keys: 100% VERIFIED OK')
   "
   ```
8. **Restart Production Backend & Verify Readiness:**
   ```bash
   sudo systemctl start tradesathi.service
   curl -s http://127.0.0.1:8000/health/ready
   ```
9. **Restore Ingress Traffic:**
   Restore Nginx reverse-proxy configuration and verify public VIP:
   ```bash
   sudo ln -sf /etc/nginx/sites-available/tradesathi.conf /etc/nginx/sites-enabled/tradesathi.conf
   sudo nginx -s reload
   ```
