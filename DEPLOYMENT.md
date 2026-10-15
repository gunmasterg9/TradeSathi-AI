# TradeSathi AI — Deployment, Operational Hardening & Release Configuration Guide
**Phase 10: Production Readiness & Deployment Hardening Reference**

---

## 1. Executive Operational Overview

TradeSathi AI is an enterprise local-first trade paperwork reconciliation, logistics compliance, and operational ERP engine.

This document defines the operational architecture, security boundaries, production configuration requirements, background services, monitoring probes, and disaster recovery procedures required for deploying and maintaining TradeSathi AI in production.

> [!IMPORTANT]
> **Production Readiness Status: PRODUCTION READY**
> The application has completed end-to-end security, tenant isolation, financial integrity, human audit trail, disaster recovery, and operational hardening verification.
> Production deployments MUST follow the loopback host binding and reverse-proxy architecture defined in this guide. Direct exposure of ASGI or development servers to the public internet without TLS reverse-proxy termination is strictly prohibited.

---

## 2. Runtime Requirements & Supported Stacks

| Component | Supported Versions | Notes |
| :--- | :--- | :--- |
| **Operating System** | Linux (Ubuntu 22.04 LTS+, Debian 12+, RHEL 9+) / Windows Server 2022+ | Tested on Linux & Windows |
| **Python** | 3.11, 3.12 | Standard virtual environment (`.venv`) |
| **Node.js** | 18 LTS, 20 LTS, 22 LTS | Required for frontend build |
| **Reverse Proxy** | Nginx 1.22+, Caddy 2.7+, or AWS ALB / Cloudflare | Handles TLS 1.3, static assets, and rate limiting |
| **Database** | SQLite 3.38+ with WAL mode enabled | Integrated zero-admin embedded database |
| **AI Inference** | Local Ollama 0.1.28+ (Optional) | Deterministic fallback operates if offline |

---

## 3. Environment Architecture & Host Binding

```text
       [ Client Browser / Mobile / HTTPS ]
                         │
                         ▼
       ┌──────────────────────────────────────────┐
       │     Reverse Proxy & TLS Termination      │
       │           (Nginx / Caddy)                │
       │  - TLS 1.3 Strict HTTPS                  │
       │  - Rate Limiting / DDoS Protection       │
       │  - Static Asset Delivery (/dist)         │
       │  - API Proxy (/api -> 127.0.0.1:8000)    │
       │  - Health Probes (/health/live, /ready)  │
       └──────────────────┬───────────────────────┘
                          │ HTTP (127.0.0.1:8000 only)
                          ▼
       ┌──────────────────────────────────────────┐
       │        Production ASGI Application       │
       │             (Uvicorn/Gunicorn)           │
       │  - 4 Worker Processes                    │
       │  - Startup Config Validation Gate        │
       │  - Bearer Token Session Management       │
       │  - Multi-Tenant & RBAC Isolation         │
       │  - Notification Worker Service           │
       └──────────┬───────────────────┬───────────┘
                  │                   │
                  ▼                   ▼
       ┌──────────────────────┐   ┌───────────────────────────┐
       │ SQLite WAL Database  │   │ Document File Store       │
       │ - Foreign Keys ON    │   │ - Path Traversal Protected│
       │ - 30s Busy Timeout   │   │ - Content Hash-Indexed    │
       │ - Migration Registry │   │ - Size-Bounded Uploads    │
       └──────────────────────┘   └───────────────────────────┘
```

### Host Binding Invariants
- **Backend ASGI Server:** Strictly bound to `127.0.0.1:8000`. Never bind to `0.0.0.0`.
- **Frontend Distribution:** Static files built via `npm run build` and served directly by Nginx/Caddy from `frontend/dist`. Never run `npm run dev` or Vite dev server in production.

---

## 4. Security Hardening Specifications

### 4.1 Production Configuration Gate
The backend lifespan verifies production configuration at startup:
- Fails closed if `TRADESATHI_TEST_ROLE_SIMULATOR=1`.
- Fails closed if `CORS_ORIGINS` contains `*` (wildcards).
- Fails closed if cryptographic secret keys are missing or set to trivial defaults.
- Fails closed if the storage repository directory is inaccessible or un-writable.

### 4.2 Authentication & Tenant Isolation
- **Internal Staff:** High-entropy bearer tokens stored as SHA-256 hashes with expiration and server-side revocation.
- **Supplier & Customer Portals:** Cryptographically isolated portal accounts, single-use activation invitations, and Anti-IDOR server-side ownership enforcement.
- **Deactivated Accounts:** Instantly revokes all active bearer tokens and rejects subsequent API access.

### 4.3 CSV Formula Injection Defense
All report CSV export endpoints sanitize output fields using `sanitize_csv_cell()` in `backend/app/reports.py`, prepending a single quote `'` to formula triggers (`=`, `+`, `-`, `@`, `|`, `\t`, `\r`, `\n`) to neutralize spreadsheet code execution.

### 4.4 File Upload & Path Traversal Guards
- Upload limit enforced by `MAX_UPLOAD_MB=10` with early stream termination.
- Extension whitelist restricted to `.pdf`, `.txt`, `.docx`, and `.eml`.
- Filename sanitization strips null bytes, path separators, and control characters.
- Resolved filesystem paths verify `Path.resolve().relative_to(base_dir)`.

---

## 5. Health Probes & Operational Diagnostics

| Endpoint | Target Audience | Purpose | Expected Status |
| :--- | :--- | :--- | :--- |
| `GET /health/live` | Reverse Proxy / K8s / Systemd | Process liveness probe | `200 OK` `{"status":"alive"}` |
| `GET /health/ready` | Load Balancer / Health Monitor | Application readiness (DB, storage, workers) | `200 OK` `{"status":"ready"}` or `503` |
| `GET /api/health` | Public UI Dashboard | High-level diagnostic without leaking paths | `200 OK` `{"status":"ok"}` |
| `GET /api/portal/admin/health/summary` | Internal Staff Only | Operational health summary (DB, storage, queues, backups) | `200 OK` (Requires Staff Token) |

---

## 6. Step-by-Step Production Deployment Procedure

### Phase 1: Environment Preparation
```bash
# Clone repository and enter project root
cd /var/www/tradesathi

# Create Python virtual environment
python3.12 -m venv backend/.venv
source backend/.venv/bin/activate

# Install backend dependencies
pip install --upgrade pip
pip install -r backend/requirements.txt

# Configure production environment variables
cp backend/.env.production.example backend/.env
# Edit backend/.env with actual production secrets:
# TRADESATHI_SECRET_KEY, CORS_ORIGINS, ENVIRONMENT=production
```

### Phase 2: Frontend Production Build
```bash
cd frontend
npm ci
npm run build
cd ..
```

### Phase 3: Pre-Release Backup & Migration Verification
```bash
# Create verified pre-release snapshot of live database and storage
python -m backend.app.backup create --retention 10

# Verify database integrity and migrations
python -c "from backend.app.db import init_db, get_applied_migrations; init_db(); print('Applied migrations:', len(get_applied_migrations()))"
```

### Phase 4: Service Startup & Supervision

#### Supported Production Worker Topologies:
- **Topology A (Recommended — Multi-Core Linux Production):**
  Uses Gunicorn process supervisor with 2–4 Uvicorn ASGI workers. Fully compatible with SQLite WAL mode (concurrent readers, serialized atomic writes) and distributed notification worker leasing (`notification_leases` table):
  ```bash
  gunicorn -w 4 -k uvicorn.workers.UvicornWorker app.main:app \
      --chdir backend \
      --bind 127.0.0.1:8000 \
      --access-logfile - \
      --error-logfile -
  ```

- **Topology B (Single-Process / Edge / Development VM):**
  Runs Uvicorn directly with explicit proxy header trust strictly scoped to the local reverse proxy (`127.0.0.1`):
  ```bash
  python -m uvicorn app.main:app \
      --app-dir backend \
      --host 127.0.0.1 \
      --port 8000 \
      --proxy-headers \
      --forwarded-allow-ips="127.0.0.1"
  ```

#### Systemd Production Service Unit (`/etc/systemd/system/tradesathi-backend.service`):
```ini
[Unit]
Description=TradeSathi AI Production ASGI Backend
After=network.target

[Service]
Type=simple
User=tradesathi
Group=tradesathi
WorkingDirectory=/var/www/tradesathi
Environment="PATH=/var/www/tradesathi/backend/.venv/bin"
EnvironmentFile=/var/www/tradesathi/backend/.env
ExecStart=/var/www/tradesathi/backend/.venv/bin/gunicorn -w 4 -k uvicorn.workers.UvicornWorker app.main:app --chdir backend --bind 127.0.0.1:8000
Restart=always
RestartSec=5s
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start systemd service
sudo systemctl daemon-reload
sudo systemctl enable tradesathi-backend
sudo systemctl restart tradesathi-backend
sudo systemctl status tradesathi-backend
```

### Phase 5: Post-Deployment Smoke Verification
```bash
# Probe liveness
curl -f http://127.0.0.1:8000/health/live

# Probe readiness
curl -f http://127.0.0.1:8000/health/ready

# Check reverse proxy HTTPS endpoint
curl -f https://tradesathi.internal.company.com/health/ready
```

---

## 7. Rollback Procedure

If a release fails post-deployment verification:
1. **Stop Application Service:**
   ```bash
   sudo systemctl stop tradesathi-backend
   ```
2. **Restore Database and Document Storage from Pre-Release Backup:**
   ```bash
   python -m backend.app.backup restore backend/backups/<PRE_RELEASE_BACKUP_ID> --target-db backend/tradesathi.db --target-storage backend/storage/documents
   ```
3. **Verify Restored Database Integrity:**
   ```bash
   python -c "import sqlite3; conn = sqlite3.connect('backend/tradesathi.db'); print(conn.execute('PRAGMA integrity_check').fetchall()); conn.close()"
   ```
4. **Revert Frontend Static Assets:**
   ```bash
   git checkout <PREVIOUS_COMMIT_TAG> -- frontend/dist
   ```
5. **Restart Application Service:**
   ```bash
   sudo systemctl start tradesathi-backend
   curl -f http://127.0.0.1:8000/health/ready
   ```

---

## 8. Routine Maintenance Schedule

| Cadence | Operational Task | Procedure |
| :--- | :--- | :--- |
| **Hourly** | Notification Worker Lease Reclamation | Automated via background queue worker |
| **Daily** | Automated Live Snapshot | Scheduled cron: `python -m backend.app.backup create --retention 14` |
| **Weekly** | Isolated Recovery Drill | Run `test-recovery.ps1` or `recovery_verifier.py` against scratch copy |
| **Monthly** | SQLite Maintenance | `sqlite3 backend/tradesathi.db "PRAGMA optimize; VACUUM;"` |
| **Quarterly** | Secret & Token Rotation | Generate fresh `TRADESATHI_SECRET_KEY` and cycle portal tokens |
