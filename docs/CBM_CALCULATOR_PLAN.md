# TradeSathi AI — CBM Calculator & Cargo Volume/Weight Planning Architecture Plan

**Document:** `docs/CBM_CALCULATOR_PLAN.md`  
**Phase:** Phase 0 — Inspection, Architecture & Implementation Blueprint  
**Status:** Gate 0 Approved  

---

## 1. Executive Summary & Existing Architecture Inspection

TradeSathi AI is a local-first export trade paperwork reconciliation and compliance intelligence engine. This document specifies the architecture and implementation roadmap for the **Shipping CBM & Cargo Volume & Weight Management Module**, expanding the platform's capabilities into freight estimation, container load planning, and cargo measurement discrepancy detection.

### Existing System Inspection
- **Backend:** Python 3.12, FastAPI, SQLite with WAL mode, Pydantic v2 schemas.
  - Core entrypoint: [`backend/app/main.py`](file:///c:/Users/RAHUL/Desktop/gautam/tradesathi-ai/backend/app/main.py)
  - Persistence: [`backend/app/db.py`](file:///c:/Users/RAHUL/Desktop/gautam/tradesathi-ai/backend/app/db.py) with additive schema migrations in `init_db`.
  - Document & File Store: [`backend/app/storage.py`](file:///c:/Users/RAHUL/Desktop/gautam/tradesathi-ai/backend/app/storage.py) & [`backend/app/documents.py`](file:///c:/Users/RAHUL/Desktop/gautam/tradesathi-ai/backend/app/documents.py).
  - Existing Models: `Shipment`, `Document`, `Analysis`, `FindingReview`.
- **Frontend:** React 18 + Vite, Vanilla CSS with custom design tokens (`frontend/src/styles.css`), Lucide icons.
  - Main app: [`frontend/src/App.jsx`](file:///c:/Users/RAHUL/Desktop/gautam/tradesathi-ai/frontend/src/App.jsx) with sidebar navigation (`activeTab`: `'audit'`, `'shipments'`, `'history'`).
  - Shipment Detail View: Comprehensive management view with document register, metadata fields, readiness checklist, and past audit linkages.
- **Baseline Test State (Recorded prior to modifications):**
  - Backend pytest: **134 passed, 1 warning** (12.19s).
  - Frontend node/vitest: **24 passed** (440ms).
  - Production build: **Vite build succeeded** (729ms).
  - Live Database Safety: **Zero modifications to live `backend/tradesathi.db` or live storage**.

---

## 2. Mathematical Specification & Conversion Formulas

All calculations use 64-bit IEEE floating-point numbers with full precision internally. Rounding is applied solely at the display formatting layer or explicit carrier billing step.

### 2.1 Dimension Normalization to Meters
All package dimensions ($L, W, H$) are converted to meters ($m$) before volume calculation:
- **Millimeters (mm):** $m = \frac{\text{mm}}{1000}$
- **Centimeters (cm):** $m = \frac{\text{cm}}{100}$
- **Meters (m):** $m = m$
- **Inches (in):** $m = \text{inches} \times 0.0254$
- **Feet (ft):** $m = \text{feet} \times 0.3048$

Validation constraint: $L > 0, W > 0, H > 0$, finite, non-zero.

### 2.2 Volume Calculations
- **Per-package CBM:**
  $$\text{CBM}_{\text{pkg}} = L_m \times W_m \times H_m$$
- **Total CBM (single line):**
  $$\text{CBM}_{\text{line}} = \text{CBM}_{\text{pkg}} \times Q$$
  where $Q \in \mathbb{Z}^+$ (positive integer quantity).
- **Cubic Feet (CuFt):**
  $$\text{CuFt} = \text{CBM} \times 35.3146667$$

### 2.3 Weight Conversions
- **Weight in Pounds (lb):**
  $$\text{Weight}_{\text{lb}} = \text{Weight}_{\text{kg}} \times 2.2046226218$$
- **Weight in Kilograms (kg):**
  $$\text{Weight}_{\text{kg}} = \frac{\text{Weight}_{\text{lb}}}{2.2046226218}$$
- **Total Gross Weight:**
  $$\text{GrossWeight}_{\text{line}} = \text{GrossWeight}_{\text{pkg}} \times Q$$

### 2.4 Volumetric Weight & Chargeable Weight
Volumetric weight is carrier- and mode-dependent:
- **Formula:**
  $$\text{Volumetric Weight (kg)} = \frac{L_{\text{cm}} \times W_{\text{cm}} \times H_{\text{cm}}}{\text{Dimensional Divisor}} \times Q$$
- **Configurable Divisors:**
  - Standard Air Freight IATA default: **6,000** $\text{cm}^3/\text{kg}$ (or courier express **5,000** $\text{cm}^3/\text{kg}$).
  - Road freight / domestic express: **4,000** to **6,000** $\text{cm}^3/\text{kg}$.
  - Sea freight: Usually billed on weight-measure (W/M) basis where $1 \text{ CBM} = 1,000 \text{ kg}$.
- **Shipment Chargeable Weight:**
  $$\text{Chargeable Weight (kg)} = \max(\text{Total Gross Weight (kg)}, \text{Total Volumetric Weight (kg)})$$
- **Explicit Disclaimers:** Carrier minimums, per-package threshold rounding, and pallet dimensional overhang rules are noted prominently.

### 2.5 Container Capacity Estimation
Approximate standard ISO dry container internal dimensions (configurable by user):

| Container Type | Internal Length ($m$) | Internal Width ($m$) | Internal Height ($m$) | Nominal CBM ($m^3$) | Default Usable Volume (85%) |
|---|---:|---:|---:|---:|---:|
| **20' Standard Dry** | 5.90 | 2.35 | 2.39 | 33.14 | 28.17 |
| **40' Standard Dry** | 12.03 | 2.35 | 2.39 | 67.58 | 57.44 |
| **40' High Cube** | 12.03 | 2.35 | 2.69 | 76.06 | 64.65 |

#### Estimation Models:
1. **Volume-Based Capacity:**
   $$\text{Estimated Units}_{\text{vol}} = \left\lfloor \frac{\text{Usable Container Volume}}{\text{CBM}_{\text{pkg}}} \right\rfloor$$
2. **Simplified Geometric Grid Fit:**
   Evaluates all 6 spatial package orientations $(l, w, h) \in \text{permutations}(L_m, W_m, H_m)$ against container internal dimensions $(C_L, C_W, C_H)$:
   $$\text{Units}_{\text{geom}} = \max_{\text{permutations}} \left( \left\lfloor \frac{C_L}{l} \right\rfloor \times \left\lfloor \frac{C_W}{w} \right\rfloor \times \left\lfloor \frac{C_H}{h} \right\rfloor \right)$$
3. **Payload Feasibility:**
   - If verified max payload capacity is configured ($P_{\max}$):
     - If $\text{Total Weight} \le P_{\max} \implies \textbf{Pass}$
     - If $\text{Total Weight} > P_{\max} \implies \textbf{Exceeds Payload}$
   - If payload capacity is unknown $\implies \textbf{Unknown}$.

---

## 3. Database Schema Design & Migration Strategy

All schema changes are **strictly additive** and applied via `init_db()` in [`backend/app/db.py`](file:///c:/Users/RAHUL/Desktop/gautam/tradesathi-ai/backend/app/db.py).

### 3.1 Table `cargo_calculations`
```sql
CREATE TABLE IF NOT EXISTS cargo_calculations (
    id TEXT PRIMARY KEY,
    calculation_reference TEXT NOT NULL UNIQUE,
    shipment_id TEXT,
    title TEXT,
    freight_mode TEXT NOT NULL DEFAULT 'general',
    dimensional_divisor REAL NOT NULL DEFAULT 6000.0,
    volumetric_rounding TEXT NOT NULL DEFAULT 'standard',
    total_packages INTEGER NOT NULL DEFAULT 0,
    total_cbm REAL NOT NULL DEFAULT 0.0,
    total_cuft REAL NOT NULL DEFAULT 0.0,
    total_gross_weight_kg REAL NOT NULL DEFAULT 0.0,
    total_gross_weight_lb REAL NOT NULL DEFAULT 0.0,
    total_volumetric_weight_kg REAL NOT NULL DEFAULT 0.0,
    chargeable_weight_kg REAL NOT NULL DEFAULT 0.0,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (shipment_id) REFERENCES shipments(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_cargo_calc_shipment ON cargo_calculations(shipment_id);
CREATE INDEX IF NOT EXISTS idx_cargo_calc_created ON cargo_calculations(created_at DESC);
```

### 3.2 Table `cargo_lines`
```sql
CREATE TABLE IF NOT EXISTS cargo_lines (
    id TEXT PRIMARY KEY,
    calculation_id TEXT NOT NULL,
    sku TEXT,
    description TEXT NOT NULL,
    package_type TEXT NOT NULL DEFAULT 'carton',
    length REAL NOT NULL,
    width REAL NOT NULL,
    height REAL NOT NULL,
    dimension_unit TEXT NOT NULL DEFAULT 'cm',
    gross_weight_per_pkg REAL NOT NULL,
    weight_unit TEXT NOT NULL DEFAULT 'kg',
    quantity INTEGER NOT NULL DEFAULT 1,
    length_m REAL NOT NULL,
    width_m REAL NOT NULL,
    height_m REAL NOT NULL,
    weight_kg REAL NOT NULL,
    cbm_per_pkg REAL NOT NULL,
    total_cbm REAL NOT NULL,
    total_cuft REAL NOT NULL,
    total_weight_kg REAL NOT NULL,
    total_weight_lb REAL NOT NULL,
    volumetric_weight_kg REAL NOT NULL,
    notes TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (calculation_id) REFERENCES cargo_calculations(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cargo_lines_calc ON cargo_lines(calculation_id);
```

---

## 4. API Endpoints & Contract Design

New endpoints placed under [`backend/app/cbm_router.py`](file:///c:/Users/RAHUL/Desktop/gautam/tradesathi-ai/backend/app/cbm_router.py) or incorporated in [`backend/app/main.py`](file:///c:/Users/RAHUL/Desktop/gautam/tradesathi-ai/backend/app/main.py):

1. **`POST /api/logistics/cbm/calculate`**
   - Stateless endpoint for immediate calculation of single package or multiple cargo lines.
   - Recalculates full precision totals on the server.
2. **`POST /api/logistics/cbm/container-estimate`**
   - Evaluates single or mixed cargo lines against standard & custom container models.
   - Returns nominal CBM, usable CBM, volume utilization %, volume unit estimate, and geometric fit.
3. **`GET /api/logistics/cbm/calculations`**
   - Paginated list of saved cargo calculations with search and shipment filter.
4. **`GET /api/logistics/cbm/calculations/{id}`**
   - Detailed calculation with full cargo lines and summary.
5. **`POST /api/logistics/cbm/calculations`**
   - Persists a new calculation header and its lines. Recalculates all totals authoritatively.
6. **`PUT /api/logistics/cbm/calculations/{id}`**
   - Updates an existing draft calculation and lines transactionally.
7. **`DELETE /api/logistics/cbm/calculations/{id}`**
   - Safely deletes draft calculation.
8. **`GET /api/shipments/{shipment_id}/cargo-measurements`**
   - Retrieves linked cargo calculations for a shipment.
9. **`POST /api/shipments/{shipment_id}/cargo-measurements`**
   - Attaches/associates a calculation with a shipment and checks for weight/package discrepancies against documents.

---

## 5. Frontend UI/UX Architecture

- **Navigation:**
  - Added to sidebar: `LOGISTICS TOOLS` $\to$ `CBM & Cargo Calculator`.
- **Component Hierarchy:**
  - `CbmCalculator`: Top-level view in `App.jsx`.
  - `FreightModeSelector`: Sea Freight, Air Freight, Road Freight, General Cargo.
  - `CargoLineForm`: Inline package entry (description, SKU, package type, dimensions $L\times W\times H$, unit, weight, weight unit, quantity, notes).
  - `CargoLinesTable`: Multi-item grid with itemized CBM, CuFt, Gross Wt, Volumetric Wt, inline edit & delete.
  - `ShipmentTotalsPanel`: KPI cards for Total CBM, Total CuFt, Total Gross Wt (kg/lb), Total Volumetric Wt, Chargeable Wt, Package Count.
  - `ContainerCapacityCard`: Side-by-side comparison for 20' Std, 40' Std, 40' HC with utilization progress bars and geometric fits.
  - `ShipmentLinkModal`: Modal to associate calculation with an active shipment reference.
  - `CalculationHistoryDrawer`: Saved draft calculations with quick reload and CSV export.
- **Shipment Detail View Integration:**
  - In `selectedShipmentDetail`: A dedicated "Cargo Volume & Weight Planning" panel displaying linked cargo lines, total CBM, chargeable weight, and discrepancy comparison against extracted packing lists or invoices.

---

## 6. Document & Reconciliation Workflow Integration

- When cargo lines are associated with a shipment that has extracted documents (Commercial Invoice, Packing List):
  - System compares:
    1. **Declared Total Gross Weight** (from invoice/packing list) vs **Calculated Cargo Weight**.
    2. **Declared Package Count** vs **Calculated Package Count**.
  - If discrepancy $> 1\%$ (or $> 1 \text{ kg}$), flags an informative notice:  
    `"Cargo calculation (120 kg) differs from declared document weight (100 kg) by 20 kg. Review packing list."`
  - Does **NOT** alter the source document values or existing review decisions.

---

## 7. Implementation Phases & Completion Gates

- **Phase 0:** Plan written (`docs/CBM_CALCULATOR_PLAN.md`), baseline tests recorded $\to$ **Gate 0 Pass**.
- **Phase 1:** Core calculation engine in `backend/app/cbm_engine.py` + comprehensive unit tests in `backend/tests/test_cbm_engine.py` $\to$ **Gate 1 Pass**.
- **Phase 2:** Frontend React CBM Calculator view, cargo lines, container cards, CSV export, unit tests in `frontend/test/cbmCalculator.test.js` $\to$ **Gate 2 Pass**.
- **Phase 3:** Backend FastAPI endpoints, additive database tables & migrations, tests in `backend/tests/test_cbm_api.py` $\to$ **Gate 3 Pass**.
- **Phase 4:** Shipment detail integration & document discrepancy check $\to$ **Gate 4 Pass**.
- **Phase 5:** Full regression suites (backend, frontend, build, recovery verifier) & final verification report `docs/CBM_CALCULATOR_TEST_REPORT.md` $\to$ **Gate 5 Pass**.

---
*Created: 2026-10-13 | TradeSathi AI Milestone 2F*
