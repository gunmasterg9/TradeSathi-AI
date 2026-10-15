# TradeSathi AI

**TradeSathi AI** is a local-first open-source trade operations copilot for small exporters, seafood exporters, freight forwarders, and shipping agents.

This application implements the **ExportMate AI** workspace: upload commercial invoices and packing lists, extract critical shipping and customs metadata, reconcile discrepancies with strict unit normalization, and generate human-in-the-loop review checklists. **PortSathi AI** is the designated Phase 2 workspace (vessel-call document processing and port operations).

> **MVP Disclaimer:** TradeSathi AI assists export operators with discrepancy detection and reconciliation. Extracted data must be verified by a human. It does not submit customs declarations or certify legal trade compliance.

---

## Key Features

- **Local-First Privacy:** All document parsing and AI inference occur locally on your machine. No customer documents are uploaded to external cloud AI providers without explicit configuration.
- **Open-Weight AI + Deterministic Rules Fallback:**
  - Discovers installed Ollama models dynamically through the `/api/tags` endpoint.
  - Transparent fallback to regex-based deterministic extraction when Ollama is offline or unconfigured.
  - Clear UI indicators denoting whether an analysis was performed via open-weight AI or the deterministic rules engine.
- **Cross-Document Reconciliation:**
  - Automated comparison of Buyer, Exporter, Commercial Invoice numbers, Currencies, Totals, Net & Gross Weights, and Package Counts.
  - **Explicit Unit Normalization:** Pounds (lbs) and metric tons (MT) are automatically converted to kilograms before comparison.
  - Calculated numeric deltas and percentage differences (e.g. `Delta: +100 kg (+0.56%)`).
  - Actionable human verification recommendations for every finding.
- **Evidence Extraction Snippets:** Preserves and displays supporting text snippets directly from source files for auditability.
- **Operational Review Checklist:** 5-point verification covering party identities, reference numbers, weight/packaging consistency, financials, and customs routing.
- **SQLite Local Persistence:** Every analysis run is persisted in a local SQLite database (`tradesathi.db`) with complete audit histories and one-click reloading.
- **1-Click Sample Testing:** Instant "Load Sample Pair" button loads synthetic test documents (`commercial_invoice.txt` and `packing_list.txt`) with an intentional 100 kg net-weight discrepancy for zero-effort evaluation.
- **Export & Share:** Downloadable structured JSON reports and one-click clipboard copying of formatted shipment audit briefs.

---

## Project Structure

```text
tradesathi-ai/
├── README.md
├── pytest.ini
├── sample-documents/
│   ├── commercial_invoice.txt
│   └── packing_list.txt
├── backend/
│   ├── .env
│   ├── .env.example
│   ├── requirements.txt
│   ├── app/
│   │   ├── __init__.py
│   │   ├── analysis.py       # AI inference & cross-document reconciliation
│   │   ├── db.py             # SQLite persistence (audit history)
│   │   ├── documents.py      # Multi-format document text extraction
│   │   ├── main.py           # FastAPI endpoints
│   │   └── schemas.py        # Pydantic schemas for trade documentation
│   └── tests/
│       └── test_analysis.py  # Comprehensive pytest suite (13 test cases)
└── frontend/
    ├── .env.example
    ├── index.html
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── App.jsx           # React responsive dashboard
        ├── main.jsx
        └── styles.css        # Executive Slate theme styling
```

---

## Quickstart Guide (Windows PowerShell)

### Prerequisites

- **Python 3.12+**
- **Node.js LTS** (`v20+` or `v24+`) and npm
- **Ollama** (optional; deterministic rules engine works out of the box without Ollama)

### 1. Backend Setup

Open a PowerShell terminal and navigate to the project directory:

```powershell
cd C:\Users\RAHUL\Desktop\gautam\tradesathi-ai
```

Install backend dependencies and run tests:

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
.\backend\.venv\Scripts\python.exe -m pytest -v
```

Start the FastAPI backend server:

```powershell
# Standard port 8000:
.\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000

# Or if port 8000 is occupied on your machine, run on port 8001:
.\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8001
```

Verify backend health in your browser:
- Health check (port 8000): [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)
- Health check (port 8001): [http://127.0.0.1:8001/api/health](http://127.0.0.1:8001/api/health)
- Interactive API Docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) (or `:8001/docs`)

### 2. Frontend Setup

Open a second PowerShell terminal in the project directory:

```powershell
cd C:\Users\RAHUL\Desktop\gautam\tradesathi-ai\frontend
npm.cmd install

# If backend is on default port 8000:
npm.cmd run dev

# Or if backend is running on port 8001:
$env:VITE_BACKEND_PORT="8001"
npm.cmd run dev
```

*Note: On Windows PowerShell with restricted script execution policies, prefer `npm.cmd` over `npm`.*

Open the URL provided by Vite: [http://127.0.0.1:5173](http://127.0.0.1:5173).

---

## Demonstrating the ExportMate Workflow

1. Open the web UI at `http://127.0.0.1:5173`.
2. Click **Load Sample Invoice & Packing List** to load `commercial_invoice.txt` and `packing_list.txt` instantly. Both documents are immediately displayed as chips in the Uploaded Documents list, and the primary action button becomes enabled.
3. Select an installed Ollama model from the dropdown (e.g. `qwen2.5:7b` or `llama3.2`) if Ollama is running, or leave **Deterministic Rules Fallback** selected (Ollama is completely optional).
4. Click **Reconcile Paperwork**.
5. Observe:
   - **Review Status:** Flagged as **Action Required** due to a critical weight discrepancy.
   - **Discrepancy Matrix:** Details the net-weight difference (`18,000 kg` in Commercial Invoice vs `18,100 kg` in Packing List, `Delta: +100 kg (+0.56%)`).
   - **Operational Action:** Advises cargo re-weighing prior to container loading to prevent customs hold.
   - **Checklist:** Flags the Weights & Cargo Tally item while passing entity and reference checks.
   - **Evidence Snippets:** Expand the snippet toggle on any field to view the exact text matched in the source document.
   - **Saved History:** Open **Recent Audits** in the sidebar to review previously persisted analyses.
6. Click **Export JSON** or **Copy Brief** to download the analysis report.

---

## API Endpoints

### Core & Reconciliation Engine
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Backend status, upload size limits, and Ollama connection health |
| `GET` | `/api/models` | Discovered open-weight models from Ollama |
| `GET` | `/api/samples` | Pre-loaded synthetic sample commercial documents |
| `POST` | `/api/analyze` | Multipart upload (up to 8 files) with optional model selection and shipment linkage |
| `GET` | `/api/analyses` | Search, filter, and paginate audit history by ID, invoice, exporter, buyer, status, date, and scope |
| `GET` | `/api/analyses/{id}` | Retrieve full historical analysis results by ID (returns 422 if payload corrupted) |
| `DELETE` | `/api/analyses/{id}` | Delete an analysis record from SQLite |

### Shipments Management
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/shipments` | Register a new shipment consignment |
| `GET` | `/api/shipments` | List shipments with search & review status filters |
| `GET` | `/api/shipments/{id}` | Retrieve shipment record details |
| `PATCH` | `/api/shipments/{id}` | Update shipment metadata and details |
| `DELETE` | `/api/shipments/{id}` | Delete shipment while safely preserving audit compliance history |
| `GET` | `/api/shipments/{id}/analyses` | List reconciliation audits linked to shipment |
| `GET` | `/api/shipments/{id}/readiness` | Evaluate comprehensive export readiness checklist |
| `POST` | `/api/shipments/{id}/reconcile` | Direct reconciliation of all documents attached to shipment |

### Document Register & Storage
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/shipments/{id}/documents` | Safe multipart document upload with hash deduplication |
| `GET` | `/api/shipments/{id}/documents` | List documents registered to shipment |
| `GET` | `/api/documents/{id}/download` | Download original binary document file |
| `PATCH` | `/api/documents/{id}` | Update document review status or notes |
| `DELETE` | `/api/documents/{id}` | Remove document and clean up persisted file |

### Human Review & Finding Resolution (Milestone 2E.4 & 2F)
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/analyses/{id}/findings/{id}/review` | Submit review action (in_review, acknowledged, escalated, resolved, reopened) with evidence verification |
| `GET` | `/api/analyses/{id}/findings/{id}/reviews` | Retrieve append-only review audit events for specific finding |
| `GET` | `/api/analyses/{id}/reviews` | Retrieve all review audit trail events for an analysis |

### Backup & Disaster Recovery (Milestone 2F)
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/backups` | List verified snapshot backups and manifest metadata |
| `POST` | `/api/backups` | Trigger full verified snapshot backup of SQLite database and documents |

For complete production ASGI deployment, TLS configuration, and disaster recovery procedures, see [DEPLOYMENT.md](file:///C:/Users/RAHUL/Desktop/gautam/tradesathi-ai/DEPLOYMENT.md).

---

## Supported File Types

- **Plain Text (`.txt`)**
- **Email Messages (`.eml`)**
- **Word Documents (`.docx`)**
- **Selectable PDF (`.pdf`)** (Scanned PDFs without text layer return a clear prompt requiring OCR)

---

## License & Challenge Submission

TradeSathi AI is open-source software created for the **Hacktoberfest 2026 Open-Source AI Side Hustle Challenge**.
