# TradeSathi AI — Phase 10.9.2: Recovery Safety Remediation & Verification

**Status date:** 2026-10-16  
**Final decision:** **NOT APPROVED FOR PRODUCTION**

## 1. Executive Summary

This remediation corrected a high-severity restore safety defect: `restore_backup()` previously wrote the database and documents directly to their targets. A copy, checksum, disk, or process failure could therefore leave a mixed version pair. Restore now verifies the source backup, stages both assets beside their intended targets, validates the staged pair, preserves existing targets, and records a durable recovery journal during the two-asset commit.

Live database and document storage were inspected only through read-only checks. Their initial and final values match exactly.

## 2. Findings and Resolution

| ID | Severity | Finding | Resolution |
|---|---:|---|---|
| F-10.9.2-01 | High | Direct restore could partially replace database and documents. | Staged restore, validation before target changes, retained prior targets, per-step journal, automatic rollback where possible. |
| F-10.9.2-02 | Medium | Verification connections remained open on Windows, preventing replacement of the staged SQLite file. | Explicitly close verification connections before commit. |
| F-10.9.2-03 | Medium | Forensic runbook copy steps were not fail-closed or independently verified. | Unique incident destination, capacity check where available, source hash manifest, checked copy commands, count/hash verification, and completion marker last. |
| F-10.9.2-04 | Medium | Earlier documentation implied stronger atomicity than two independent renames can supply. | Documentation now states the limitation and mandatory maintenance-mode/journal recovery procedure. |

## 3. Files Changed

- `backend/app/backup.py`: staged and verified restoration; preserves prior database/document targets under unique `.pre-restore-*` paths; writes `.restore-*.json`; rolls back after a caught commit failure; explicitly closes read-only SQLite verification connections.
- `backend/tests/test_backup_restore_safety.py`: isolated failure injection for absent/invalid manifests, hash mismatch, document copy/disk failure, database staging failure, commit interruption, simulated process interruption, successful consistency, and repeat restore.
- `RECOVERY_RUNBOOK.md`: fail-closed forensic preservation procedure; separate Linux production and Windows guidance; explicit cross-asset atomicity limitation and journal recovery instructions.

## 4. Forensic Preservation Guarantees and Limits

The updated runbook requires an explicit incident identifier and refuses an existing forensic destination. Linux instructions check available capacity where `df` is available, generate a source hash manifest, check every copy command, compare copied hashes and counts, and create `completion.json` only after verification. Database WAL/SHM files are copied only after maintenance mode, service shutdown, and open-handle verification.

The procedure deliberately copies rather than moves or deletes SQLite companion files. Capacity checks are advisory only on platforms without a reliable command; hash/count verification remains mandatory. Operators must stop recovery if any preservation step fails.

## 5. Restore Failure Handling and Atomicity

1. `verify_backup()` validates manifest, database hash/integrity/counts, and each document hash before a target parent is created or target is moved.
2. Database and documents are restored to unique sibling staging paths, keeping each on the respective target filesystem.
3. Staged database size/hash/counts, SQLite integrity, foreign keys, document hashes, and database-to-document references are verified before commit.
4. Existing targets are moved to unique retained recovery locations before staged replacements.
5. A journal records `staged_verified`, preservation, database replacement, completion, and rollback states.
6. On a caught error or simulated interruption, the implementation restores the original pair and leaves the journal plus failed candidates for investigation.

Two separate filesystem replacements are **not** one atomic transaction. A power loss or forced termination between replacements may leave a journal with an incomplete state. The operator must keep maintenance mode enabled, inspect the journal, restore `previous_db` and `previous_storage` to their targets when `rollback_required`, validate both assets, and only then restart the application.

## 6. Isolated Failure-Injection Results

All tests used pytest temporary paths under `scratch/`; no live path was passed to restore.

| Case | Result |
|---|---|
| Missing backup manifest / existing target retained | Passed |
| Manifest document hash mismatch / existing target retained | Passed |
| Simulated document copy failure (disk-full/write failure) | Passed |
| Simulated database staging write failure | Passed |
| Failure after database replacement, before document replacement | Passed; original pair restored; journal `rolled_back` |
| Simulated process interruption at same commit point | Passed; original pair restored |
| Successful restore with database-to-document validation | Passed |
| Second restore attempt | Passed; deterministic consistent result |

The required forensic-destination collision, copy/hash/write failure behavior is documented as an operator fail-closed procedure. It is not an application command, so it was not exercised against live data.

## 7. Commands and Actual Results

| Command | Exit | Result |
|---|---:|---|
| `python -m pytest backend/tests/test_backup_restore_safety.py -v --basetemp scratch\\pytest-phase-10-9-2c` | 0 | 7 passed, 1 unrelated FastAPI deprecation warning |
| `python -m pytest backend/tests/test_backup_restore_safety.py backend/tests/test_phase10_7_blocker_verification.py backend/tests/test_phase10_production_readiness.py backend/tests/test_documents_and_readiness.py -v --basetemp scratch\\pytest-phase-10-9-2-regression` | 0 | 30 passed, 1 warning |
| `python -m pytest backend/tests/test_recovery_verifier.py -v --basetemp scratch\\pytest-phase-10-9-2-verifier` | 0 | 16 passed, 1 warning |

An initial focused-test attempt exited 1 before test setup because the sandboxed system pytest temp directory denied access. Rerunning with an approved disposable workspace `--basetemp` resolved the environment issue; no assertion failed.

Frontend files were not changed, so no frontend tests or production build were run for this milestone.

## 8. Live-Data Invariance

Initial and final read-only measurements were identical:

| Measurement | Initial | Final |
|---|---:|---:|
| `backend/tradesathi.db` SHA-256 | `d16067b3369093b71457a4c22c1e0d5871e6d1201af6849a3efbfaad6090b0bf` | same |
| Database size | 6,127,616 bytes | 6,127,616 bytes |
| Analyses / shipments / documents / finding reviews | 330 / 45 / 48 / 2 | 330 / 45 / 48 / 2 |
| Document files / shipment directories | 143 / 80 | 143 / 80 |
| Aggregate document manifest SHA-256 | `4de3f9a0a187fc48f4b7249b4cad06460e07e70b3655fe4cd0e74bfa6037f834` | same |

No live database, WAL/SHM file, or document-storage file was restored, migrated, deleted, or modified.

## 9. Release Gates and Operator Instructions

The release sequence remains mandatory and human-controlled:

1. **Stage 1 — Offline verification:** collect evidence for DNS/TLS, firewall, KMS/secrets, off-host backup, monitoring, and SMTP. These gates remain unverified without real evidence.
2. **Stage 2 — Baseline and authorization:** create and verify a pre-release backup, complete maintenance/readiness checks, and obtain formal Product Owner and CAB authorization with all prerequisite evidence attached.
3. **Stage 3 — Authorized cutover:** enter maintenance mode, validate readiness, and enable ingress only under the recorded authorization.
4. **Stage 4 — Observation and closure:** the named rollback decision-maker applies explicit abort criteria during the authorized observation window; record incidents, outcome, and closure in the change record.

Abort immediately for missing evidence or authorization, failed pre-release backup/verification, failed maintenance/readiness check, a failed preservation or restore journal state, database integrity/FK failure, document/reference mismatch, or defined operational thresholds such as elevated 5xx, authentication failures, or SQLite errors. No code path grants release approval or bypasses these gates.

## 10. Remaining Risks and Final Decision

The repository cannot prove external DNS, TLS, firewall, KMS, SMTP, cloud backup, monitoring, or human approval gates. Cross-asset replacement remains recoverable rather than globally atomic; maintenance mode and the journal procedure are required.

**GO/NO-GO: NO-GO — NOT APPROVED FOR PRODUCTION.**

The next authorized action is for designated infrastructure, security, database, Product Owner, and CAB operators to supply evidence and approvals for Stage 1 and Stage 2. Do not begin cutover or Phase 11.
