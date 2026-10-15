import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  ArrowDownToLine,
  Box,
  Boxes,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CircleAlert,
  Copy,
  Edit2,
  FileSpreadsheet,
  FileText,
  HelpCircle,
  History,
  Info,
  Layers,
  LoaderCircle,
  Package,
  Pencil,
  Plane,
  Plus,
  Printer,
  RefreshCw,
  RotateCcw,
  Save,
  Scale,
  Search,
  ShieldCheck,
  Ship,
  Trash2,
  Truck,
  X,
} from 'lucide-react'
import { apiFetch } from './api'
import {
  CONTAINER_DISCLAIMER,
  DEFAULT_CONTAINERS,
  calculateCargoAggregate,
  calculateCargoLine,
  estimateContainerCapacity,
  formatDec,
  generateCargoCsv,
  normalizeDimensionToMeters,
} from './cbmHelper'

export default function CbmCalculator({ shipments = [], onSelectShipment = null }) {
  // Freight Mode & Divisor State
  const [freightMode, setFreightMode] = useState('general') // 'sea' | 'air' | 'road' | 'general'
  const [dimensionalDivisor, setDimensionalDivisor] = useState(6000)
  const [perPkgRounding, setPerPkgRounding] = useState(false)
  const [usableRatio, setUsableRatio] = useState(0.85) // 85% usable volume
  const [customPayloadKg, setCustomPayloadKg] = useState('')

  // Cargo Lines State
  const [lines, setLines] = useState([
    {
      id: 'init-1',
      description: 'Standard Export Carton',
      sku: 'SKU-EXP-101',
      package_type: 'carton',
      length: 60,
      width: 40,
      height: 30,
      dimension_unit: 'cm',
      gross_weight_per_pkg: 12,
      weight_unit: 'kg',
      quantity: 10,
      notes: 'Fragile electronics accessories',
    },
  ])

  // Form input state (for adding / editing line)
  const [editingLineId, setEditingLineId] = useState(null)
  const [lineDesc, setLineDesc] = useState('')
  const [lineSku, setLineSku] = useState('')
  const [linePkgType, setLinePkgType] = useState('carton')
  const [lineLength, setLineLength] = useState('60')
  const [lineWidth, setLineWidth] = useState('40')
  const [lineHeight, setLineHeight] = useState('30')
  const [lineDimUnit, setLineDimUnit] = useState('cm')
  const [lineWeight, setLineWeight] = useState('12')
  const [lineWeightUnit, setLineWeightUnit] = useState('kg')
  const [lineQty, setLineQty] = useState('10')
  const [lineNotes, setLineNotes] = useState('')
  const [formError, setFormError] = useState('')

  // Selected container estimator line
  const [selectedEstimatorLineIndex, setSelectedEstimatorLineIndex] = useState(0)

  // Persistence & Draft Management
  const [calcTitle, setCalcTitle] = useState('New Cargo Plan')
  const [associatedShipmentId, setAssociatedShipmentId] = useState('')
  const [activeCalcId, setActiveCalcId] = useState(null)
  const [activeCalcRef, setActiveCalcRef] = useState(null)
  const [saveLoading, setSaveLoading] = useState(false)
  const [saveSuccessMsg, setSaveSuccessMsg] = useState('')
  const [saveErrorMsg, setSaveErrorMsg] = useState('')

  // Calculation History Drawer
  const [showHistoryDrawer, setShowHistoryDrawer] = useState(false)
  const [savedCalculations, setSavedCalculations] = useState([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historySearch, setHistorySearch] = useState('')

  // Print Summary Modal
  const [showPrintModal, setShowPrintModal] = useState(false)

  // Sync mode default divisor
  useEffect(() => {
    if (freightMode === 'air' && dimensionalDivisor === 6000) {
      setDimensionalDivisor(5000)
    } else if (freightMode === 'sea' && dimensionalDivisor === 5000) {
      setDimensionalDivisor(6000)
    }
  }, [freightMode])

  // Aggregate Calculation
  const aggregate = useMemo(() => {
    try {
      return calculateCargoAggregate(lines, freightMode, dimensionalDivisor, perPkgRounding)
    } catch (err) {
      console.warn('Calculation error:', err.message)
      return calculateCargoAggregate([], freightMode, dimensionalDivisor, perPkgRounding)
    }
  }, [lines, freightMode, dimensionalDivisor, perPkgRounding])

  // Container Estimates for active package
  const containerEstimates = useMemo(() => {
    if (!lines || lines.length === 0) return []
    const targetLine = lines[selectedEstimatorLineIndex] || lines[0]
    if (!targetLine) return []

    try {
      const lM = normalizeDimensionToMeters(targetLine.length, targetLine.dimension_unit)
      const wM = normalizeDimensionToMeters(targetLine.width, targetLine.dimension_unit)
      const hM = normalizeDimensionToMeters(targetLine.height, targetLine.dimension_unit)
      const wKg = targetLine.weight_unit === 'lb'
        ? Number(targetLine.gross_weight_per_pkg || 0) / 2.2046226218
        : Number(targetLine.gross_weight_per_pkg || 0)

      const payloadNum = customPayloadKg ? parseFloat(customPayloadKg) : null

      return DEFAULT_CONTAINERS.map((cont) =>
        estimateContainerCapacity(lM, wM, hM, wKg, usableRatio, payloadNum, cont)
      )
    } catch (e) {
      return []
    }
  }, [lines, selectedEstimatorLineIndex, usableRatio, customPayloadKg])

  // Form Reset / Populate for editing
  function resetForm() {
    setEditingLineId(null)
    setLineDesc('')
    setLineSku('')
    setLinePkgType('carton')
    setLineLength('60')
    setLineWidth('40')
    setLineHeight('30')
    setLineDimUnit('cm')
    setLineWeight('12')
    setLineWeightUnit('kg')
    setLineQty('10')
    setLineNotes('')
    setFormError('')
  }

  function handleEditLine(line) {
    setEditingLineId(line.id)
    setLineDesc(line.description || '')
    setLineSku(line.sku || '')
    setLinePkgType(line.package_type || 'carton')
    setLineLength(String(line.length))
    setLineWidth(String(line.width))
    setLineHeight(String(line.height))
    setLineDimUnit(line.dimension_unit || 'cm')
    setLineWeight(String(line.gross_weight_per_pkg || 0))
    setLineWeightUnit(line.weight_unit || 'kg')
    setLineQty(String(line.quantity))
    setLineNotes(line.notes || '')
    setFormError('')
  }

  function handleSaveLine(e) {
    e.preventDefault()
    setFormError('')

    const l = parseFloat(lineLength)
    const w = parseFloat(lineWidth)
    const h = parseFloat(lineHeight)
    const wt = parseFloat(lineWeight)
    const q = parseInt(lineQty, 10)

    if (isNaN(l) || l <= 0) return setFormError('Length must be a positive number')
    if (isNaN(w) || w <= 0) return setFormError('Width must be a positive number')
    if (isNaN(h) || h <= 0) return setFormError('Height must be a positive number')
    if (isNaN(wt) || wt < 0) return setFormError('Gross weight per package must be non-negative')
    if (isNaN(q) || q < 1) return setFormError('Quantity must be a positive integer (minimum 1)')

    const newLineData = {
      id: editingLineId || `line-${Date.now()}-${Math.random().toString(36).substr(2, 4)}`,
      description: lineDesc.trim() || 'Cargo Package',
      sku: lineSku.trim() || null,
      package_type: linePkgType,
      length: l,
      width: w,
      height: h,
      dimension_unit: lineDimUnit,
      gross_weight_per_pkg: wt,
      weight_unit: lineWeightUnit,
      quantity: q,
      notes: lineNotes.trim() || null,
    }

    if (editingLineId) {
      setLines((prev) => prev.map((item) => (item.id === editingLineId ? newLineData : item)))
    } else {
      setLines((prev) => [...prev, newLineData])
    }

    resetForm()
  }

  function handleDeleteLine(lineId) {
    if (lines.length <= 1) {
      if (!confirm('This is the only cargo line. Are you sure you want to remove it?')) return
    }
    setLines((prev) => prev.filter((item) => item.id !== lineId))
    if (editingLineId === lineId) resetForm()
  }

  function handleResetAllLines() {
    if (lines.length > 0 && !confirm('Are you sure you want to clear all cargo lines? Unsaved changes will be lost.')) {
      return
    }
    setLines([])
    resetForm()
  }

  function handleLoadSamplePreset() {
    setLines([
      {
        id: `line-${Date.now()}-1`,
        description: 'Cotton Fabric Master Cartons',
        sku: 'TEX-CTN-400',
        package_type: 'carton',
        length: 60,
        width: 40,
        height: 35,
        dimension_unit: 'cm',
        gross_weight_per_pkg: 18.5,
        weight_unit: 'kg',
        quantity: 120,
        notes: 'Double-walled export carton with polybag inner lining',
      },
      {
        id: `line-${Date.now()}-2`,
        description: 'Garment Sample Boxes',
        sku: 'TEX-SMP-05',
        package_type: 'box',
        length: 45,
        width: 30,
        height: 20,
        dimension_unit: 'cm',
        gross_weight_per_pkg: 6.0,
        weight_unit: 'kg',
        quantity: 15,
        notes: 'Commercial trade show samples',
      },
    ])
    setCalcTitle('Sample Garment Export Consignment')
  }

  // Fetch saved calculations history
  async function fetchCalculations() {
    setHistoryLoading(true)
    try {
      const data = await apiFetch('/api/logistics/cbm/calculations?page_size=30')
      if (data && data.calculations) {
        setSavedCalculations(data.calculations)
      }
    } catch (err) {
      console.warn('Failed to load calculations:', err.message)
    } finally {
      setHistoryLoading(false)
    }
  }

  // Save current calculation to database
  async function handleSaveCalculation() {
    if (lines.length === 0) {
      alert('Please add at least one cargo line before saving.')
      return
    }

    setSaveLoading(true)
    setSaveSuccessMsg('')
    setSaveErrorMsg('')

    const payload = {
      title: calcTitle.trim() || 'Cargo Plan',
      shipment_id: associatedShipmentId || null,
      freight_mode: freightMode,
      dimensional_divisor: dimensionalDivisor,
      per_package_chargeable_rounding: perPkgRounding,
      notes: `Saved from CBM Calculator (${lines.length} lines, ${aggregate.total_packages} pkgs)`,
      items: lines.map((l) => ({
        description: l.description,
        sku: l.sku,
        package_type: l.package_type,
        length: Number(l.length),
        width: Number(l.width),
        height: Number(l.height),
        dimension_unit: l.dimension_unit,
        gross_weight_per_pkg: Number(l.gross_weight_per_pkg || 0),
        weight_unit: l.weight_unit || 'kg',
        quantity: parseInt(l.quantity, 10),
        notes: l.notes,
      })),
    }

    try {
      let saved
      if (activeCalcId) {
        saved = await apiFetch(`/api/logistics/cbm/calculations/${activeCalcId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
        setSaveSuccessMsg(`Updated calculation ${saved.calculation_reference || activeCalcRef}`)
      } else {
        saved = await apiFetch('/api/logistics/cbm/calculations', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
        setActiveCalcId(saved.id)
        setActiveCalcRef(saved.calculation_reference)
        setSaveSuccessMsg(`Saved calculation draft #${saved.calculation_reference}`)
      }
      fetchCalculations()
    } catch (err) {
      setSaveErrorMsg(err.message || 'Failed to persist calculation.')
    } finally {
      setSaveLoading(false)
    }
  }

  // Load a previously saved calculation
  function handleLoadSavedCalculation(record) {
    if (!record) return
    setActiveCalcId(record.id)
    setActiveCalcRef(record.calculation_reference)
    setCalcTitle(record.title || 'Loaded Plan')
    setFreightMode(record.freight_mode || 'general')
    setDimensionalDivisor(record.dimensional_divisor || 6000)
    setPerPkgRounding(record.volumetric_rounding === 'per_package')
    setAssociatedShipmentId(record.shipment_id || '')

    if (record.lines && record.lines.length > 0) {
      setLines(
        record.lines.map((l, idx) => ({
          id: l.id || `line-loaded-${idx}`,
          description: l.description,
          sku: l.sku,
          package_type: l.package_type,
          length: l.length_orig,
          width: l.width_orig,
          height: l.height_orig,
          dimension_unit: l.dimension_unit,
          gross_weight_per_pkg: l.gross_weight_orig,
          weight_unit: l.weight_unit,
          quantity: l.quantity,
          notes: l.notes,
        }))
      )
    }
    setShowHistoryDrawer(false)
  }

  // Duplicate as new draft
  function handleDuplicateAsDraft() {
    setActiveCalcId(null)
    setActiveCalcRef(null)
    setCalcTitle(`${calcTitle} (Copy)`)
    setSaveSuccessMsg('Created fresh draft from existing calculation.')
  }

  // Delete saved calculation
  async function handleDeleteSavedCalculation(calcId, ref) {
    if (!confirm(`Are you sure you want to delete calculation ${ref}? This action cannot be undone.`)) return
    try {
      await apiFetch(`/api/logistics/cbm/calculations/${calcId}`, { method: 'DELETE' })
      if (activeCalcId === calcId) {
        setActiveCalcId(null)
        setActiveCalcRef(null)
      }
      fetchCalculations()
    } catch (err) {
      alert(`Error deleting calculation: ${err.message}`)
    }
  }

  // Export to CSV
  function handleExportCsv() {
    const csvContent = generateCargoCsv(aggregate, calcTitle)
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.setAttribute('href', url)
    link.setAttribute('download', `tradesathi-cargo-${activeCalcRef || 'estimate'}.csv`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  return (
    <div className="cbm-calc-container">
      {/* Header Bar */}
      <div className="cbm-header">
        <div className="cbm-header-titles">
          <div className="cbm-badge">
            <Scale size={13} />
            <span>EXPORT LOGISTICS &amp; FREIGHT ENGINE</span>
          </div>
          <h1>CBM Calculator &amp; Cargo Capacity Planner</h1>
          <p>
            Deterministic cubic meter (CBM), volumetric weight, container loading feasibility, and
            shipping tally estimation for global export consignments.
          </p>
        </div>

        <div className="cbm-actions">
          <button
            className="btn-sm btn-secondary"
            onClick={() => {
              setShowHistoryDrawer(true)
              fetchCalculations()
            }}
          >
            <History size={14} /> Saved Calculations ({savedCalculations.length})
          </button>
          <button className="btn-sm btn-secondary" onClick={handleExportCsv} disabled={lines.length === 0}>
            <FileSpreadsheet size={14} /> Export CSV
          </button>
          <button className="btn-sm btn-secondary" onClick={() => setShowPrintModal(true)} disabled={lines.length === 0}>
            <Printer size={14} /> Print Summary
          </button>
          <button
            className="btn-sm btn-primary-sm"
            onClick={handleSaveCalculation}
            disabled={saveLoading || lines.length === 0}
          >
            {saveLoading ? <LoaderCircle size={14} className="spin" /> : <Save size={14} />}
            {activeCalcId ? 'Update Calculation' : 'Save Calculation'}
          </button>
        </div>
      </div>

      {/* Notifications */}
      {saveSuccessMsg && (
        <div className="cbm-alert success">
          <CheckCircle2 size={16} />
          <span>{saveSuccessMsg}</span>
          <button onClick={() => setSaveSuccessMsg('')}>
            <X size={14} />
          </button>
        </div>
      )}
      {saveErrorMsg && (
        <div className="cbm-alert error">
          <CircleAlert size={16} />
          <span>{saveErrorMsg}</span>
          <button onClick={() => setSaveErrorMsg('')}>
            <X size={14} />
          </button>
        </div>
      )}

      {/* Controls Bar: Freight Mode, Divisor & Shipment Association */}
      <div className="cbm-controls-panel">
        <div className="cbm-mode-selector">
          <span className="control-label">FREIGHT MODE:</span>
          <div className="mode-pill-group">
            <button
              className={`mode-pill ${freightMode === 'general' ? 'active' : ''}`}
              onClick={() => setFreightMode('general')}
            >
              <Boxes size={14} /> General Cargo
            </button>
            <button
              className={`mode-pill ${freightMode === 'sea' ? 'active' : ''}`}
              onClick={() => setFreightMode('sea')}
            >
              <Ship size={14} /> Sea Freight (FCL/LCL)
            </button>
            <button
              className={`mode-pill ${freightMode === 'air' ? 'active' : ''}`}
              onClick={() => setFreightMode('air')}
            >
              <Plane size={14} /> Air Freight
            </button>
            <button
              className={`mode-pill ${freightMode === 'road' ? 'active' : ''}`}
              onClick={() => setFreightMode('road')}
            >
              <Truck size={14} /> Road Freight
            </button>
          </div>
        </div>

        <div className="cbm-config-row">
          <div className="config-item">
            <label>Title / Reference</label>
            <input
              type="text"
              value={calcTitle}
              onChange={(e) => setCalcTitle(e.target.value)}
              placeholder="e.g. Consignment 2026-B"
              className="cbm-input"
            />
          </div>

          <div className="config-item">
            <label>Associate Shipment</label>
            <select
              value={associatedShipmentId}
              onChange={(e) => setAssociatedShipmentId(e.target.value)}
              className="cbm-select"
            >
              <option value="">-- Standalone (No Shipment) --</option>
              {shipments.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.reference} {s.buyer ? `• ${s.buyer}` : ''}
                </option>
              ))}
            </select>
          </div>

          <div className="config-item">
            <label>
              Dimensional Divisor (cm³/kg)
              <span className="tooltip-tag" title="Carrier dimensional divisor used for volumetric weight calculation. Example: 5000 cm3/kg for courier/express air; 6000 cm3/kg for IATA standard cargo.">
                <HelpCircle size={12} />
              </span>
            </label>
            <div className="divisor-input-wrap">
              <input
                type="number"
                min="1000"
                max="20000"
                step="100"
                value={dimensionalDivisor}
                onChange={(e) => setDimensionalDivisor(Math.max(100, parseFloat(e.target.value) || 6000))}
                className="cbm-input"
              />
              <button
                type="button"
                className={`preset-btn ${dimensionalDivisor === 6000 ? 'active' : ''}`}
                onClick={() => setDimensionalDivisor(6000)}
              >
                6,000
              </button>
              <button
                type="button"
                className={`preset-btn ${dimensionalDivisor === 5000 ? 'active' : ''}`}
                onClick={() => setDimensionalDivisor(5000)}
              >
                5,000
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Aggregate KPI Summary Cards */}
      <div className="cbm-kpi-grid">
        <div className="kpi-card highlight">
          <div className="kpi-label">TOTAL VOLUME (CBM)</div>
          <div className="kpi-value">{formatDec(aggregate.total_cbm, 3)}</div>
          <div className="kpi-sub">{formatDec(aggregate.total_cuft, 2)} Cubic Feet (CuFt)</div>
        </div>

        <div className="kpi-card">
          <div className="kpi-label">TOTAL GROSS WEIGHT</div>
          <div className="kpi-value">{formatDec(aggregate.total_gross_weight_kg, 2)} <small>kg</small></div>
          <div className="kpi-sub">{formatDec(aggregate.total_gross_weight_lb, 2)} lbs</div>
        </div>

        <div className="kpi-card">
          <div className="kpi-label">
            VOLUMETRIC WEIGHT
            <span className="divisor-sub">@{dimensionalDivisor}</span>
          </div>
          <div className="kpi-value">{formatDec(aggregate.total_volumetric_weight_kg, 2)} <small>kg</small></div>
          <div className="kpi-sub">
            {aggregate.total_volumetric_weight_kg > aggregate.total_gross_weight_kg ? (
              <span className="badge-vol-heavy">Volumetric Heavy (+{(aggregate.total_volumetric_weight_kg - aggregate.total_gross_weight_kg).toFixed(1)} kg)</span>
            ) : (
              <span className="badge-gross-heavy">Weight Dense Consignment</span>
            )}
          </div>
        </div>

        <div className="kpi-card highlight-accent">
          <div className="kpi-label">CHARGEABLE WEIGHT</div>
          <div className="kpi-value">{formatDec(aggregate.chargeable_weight_kg, 2)} <small>kg</small></div>
          <div className="kpi-sub">
            Rule: max(Gross {formatDec(aggregate.total_gross_weight_kg, 1)} kg, Vol {formatDec(aggregate.total_volumetric_weight_kg, 1)} kg)
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-label">TOTAL PACKAGES</div>
          <div className="kpi-value">{aggregate.total_packages} <small>pkgs</small></div>
          <div className="kpi-sub">Across {lines.length} cargo {lines.length === 1 ? 'line' : 'lines'}</div>
        </div>

        <div className="kpi-card">
          <div className="kpi-label">AVERAGE STATS</div>
          <div className="kpi-value-sm">
            <span>Vol: <strong>{formatDec(aggregate.average_cbm_per_pkg, 4)}</strong> CBM/pkg</span>
            <span>Wt: <strong>{formatDec(aggregate.average_weight_kg_per_pkg, 2)}</strong> kg/pkg</span>
          </div>
          <div className="kpi-sub">
            Range: {formatDec(aggregate.smallest_cbm_pkg, 3)} – {formatDec(aggregate.largest_cbm_pkg, 3)} CBM
          </div>
        </div>
      </div>

      {/* Main Split Layout: Package Entry Form & Multiple Cargo Lines Table */}
      <div className="cbm-body-grid">
        {/* Cargo Entry Form */}
        <div className="cbm-panel form-panel">
          <div className="panel-head">
            <div className="panel-title">
              <Package size={16} />
              <span>{editingLineId ? 'Edit Cargo Line' : 'Add Package / Carton'}</span>
            </div>
            {editingLineId ? (
              <button className="btn-text-sm" onClick={resetForm}>
                Cancel Edit
              </button>
            ) : (
              <button className="btn-text-sm" onClick={handleLoadSamplePreset} title="Populate with realistic export sample">
                Load Preset
              </button>
            )}
          </div>

          <form onSubmit={handleSaveLine} className="cbm-form">
            {formError && (
              <div className="form-error-banner">
                <CircleAlert size={14} />
                <span>{formError}</span>
              </div>
            )}

            <div className="form-group">
              <label>Package / Product Description *</label>
              <input
                type="text"
                value={lineDesc}
                onChange={(e) => setLineDesc(e.target.value)}
                placeholder="e.g. Master Carton #A, Pallet 1"
                className="cbm-input"
                required
              />
            </div>

            <div className="form-row-2">
              <div className="form-group">
                <label>SKU / Reference (Optional)</label>
                <input
                  type="text"
                  value={lineSku}
                  onChange={(e) => setLineSku(e.target.value)}
                  placeholder="e.g. SKU-1049"
                  className="cbm-input"
                />
              </div>

              <div className="form-group">
                <label>Package Type</label>
                <select
                  value={linePkgType}
                  onChange={(e) => setLinePkgType(e.target.value)}
                  className="cbm-select"
                >
                  <option value="carton">Carton</option>
                  <option value="box">Box</option>
                  <option value="pallet">Pallet</option>
                  <option value="crate">Crate</option>
                  <option value="drum">Drum</option>
                  <option value="custom">Custom</option>
                </select>
              </div>
            </div>

            <div className="form-group">
              <div className="dim-header-row">
                <label>Dimensions (Length × Width × Height) *</label>
                <select
                  value={lineDimUnit}
                  onChange={(e) => setLineDimUnit(e.target.value)}
                  className="cbm-select-mini"
                >
                  <option value="cm">cm (Centimeters)</option>
                  <option value="mm">mm (Millimeters)</option>
                  <option value="m">m (Meters)</option>
                  <option value="inch">in (Inches)</option>
                  <option value="feet">ft (Feet)</option>
                </select>
              </div>

              <div className="dim-inputs-grid">
                <div>
                  <input
                    type="number"
                    step="any"
                    min="0.001"
                    placeholder="Length"
                    value={lineLength}
                    onChange={(e) => setLineLength(e.target.value)}
                    className="cbm-input"
                    required
                  />
                  <small>Length ({lineDimUnit})</small>
                </div>
                <div>
                  <input
                    type="number"
                    step="any"
                    min="0.001"
                    placeholder="Width"
                    value={lineWidth}
                    onChange={(e) => setLineWidth(e.target.value)}
                    className="cbm-input"
                    required
                  />
                  <small>Width ({lineDimUnit})</small>
                </div>
                <div>
                  <input
                    type="number"
                    step="any"
                    min="0.001"
                    placeholder="Height"
                    value={lineHeight}
                    onChange={(e) => setLineHeight(e.target.value)}
                    className="cbm-input"
                    required
                  />
                  <small>Height ({lineDimUnit})</small>
                </div>
              </div>
            </div>

            <div className="form-row-2">
              <div className="form-group">
                <div className="dim-header-row">
                  <label>Gross Wt / Package *</label>
                  <select
                    value={lineWeightUnit}
                    onChange={(e) => setLineWeightUnit(e.target.value)}
                    className="cbm-select-mini"
                  >
                    <option value="kg">kg</option>
                    <option value="lb">lb</option>
                  </select>
                </div>
                <input
                  type="number"
                  step="any"
                  min="0"
                  placeholder="0.0"
                  value={lineWeight}
                  onChange={(e) => setLineWeight(e.target.value)}
                  className="cbm-input"
                  required
                />
              </div>

              <div className="form-group">
                <label>Number of Packages (Qty) *</label>
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={lineQty}
                  onChange={(e) => setLineQty(e.target.value)}
                  className="cbm-input"
                  required
                />
              </div>
            </div>

            <div className="form-group">
              <label>Cargo Notes (Optional)</label>
              <input
                type="text"
                value={lineNotes}
                onChange={(e) => setLineNotes(e.target.value)}
                placeholder="e.g. Do not stack more than 4 high"
                className="cbm-input"
              />
            </div>

            <button type="submit" className="btn-primary w-full">
              {editingLineId ? <Check size={16} /> : <Plus size={16} />}
              {editingLineId ? 'Update Cargo Line' : 'Add to Cargo Tally'}
            </button>
          </form>
        </div>

        {/* Cargo Lines Table Panel */}
        <div className="cbm-panel table-panel">
          <div className="panel-head">
            <div className="panel-title">
              <Layers size={16} />
              <span>Multiple Cargo Lines ({lines.length})</span>
            </div>
            <div className="table-actions">
              <button
                className="btn-text-sm danger"
                onClick={handleResetAllLines}
                disabled={lines.length === 0}
              >
                <RotateCcw size={13} /> Reset All Lines
              </button>
            </div>
          </div>

          {lines.length === 0 ? (
            <div className="cbm-empty-state">
              <Package size={36} />
              <h4>No cargo lines entered</h4>
              <p>Add carton or package measurements using the form on the left, or load a sample preset.</p>
              <button className="btn-sm btn-secondary" onClick={handleLoadSamplePreset}>
                Load Sample Consignment
              </button>
            </div>
          ) : (
            <div className="cbm-table-wrap">
              <table className="cbm-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Package Description</th>
                    <th>Dimensions</th>
                    <th>Weight / Pkg</th>
                    <th>Qty</th>
                    <th>CBM / Pkg</th>
                    <th>Total CBM</th>
                    <th>Total Gross Wt</th>
                    <th>Vol Wt (kg)</th>
                    <th style={{ textAlign: 'right' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {aggregate.lines.map((item, idx) => (
                    <tr
                      key={lines[idx]?.id || idx}
                      className={editingLineId === lines[idx]?.id ? 'editing-row' : ''}
                    >
                      <td className="row-idx">{idx + 1}</td>
                      <td>
                        <div className="item-title">
                          <strong>{item.description}</strong>
                          <span className="pkg-type-tag">{item.package_type}</span>
                        </div>
                        {item.sku && <small className="item-sku">SKU: {item.sku}</small>}
                      </td>
                      <td className="dim-cell">
                        {item.length_orig} × {item.width_orig} × {item.height_orig} {item.dimension_unit}
                        <br />
                        <span className="dim-metric-sub">
                          ({formatDec(item.length_m, 2)} × {formatDec(item.width_m, 2)} × {formatDec(item.height_m, 2)} m)
                        </span>
                      </td>
                      <td>
                        {item.gross_weight_orig} {item.weight_unit}
                        <br />
                        <span className="dim-metric-sub">({formatDec(item.weight_kg, 2)} kg)</span>
                      </td>
                      <td>
                        <strong className="qty-badge">{item.quantity}</strong>
                      </td>
                      <td className="numeric-cell">{formatDec(item.cbm_per_pkg, 4)}</td>
                      <td className="numeric-cell highlight-cell">
                        <strong>{formatDec(item.total_cbm, 4)}</strong>
                      </td>
                      <td className="numeric-cell">
                        {formatDec(item.total_gross_weight_kg, 2)} kg
                        <br />
                        <span className="dim-metric-sub">({formatDec(item.total_gross_weight_lb, 1)} lb)</span>
                      </td>
                      <td className="numeric-cell">{formatDec(item.volumetric_weight_kg, 2)}</td>
                      <td style={{ textAlign: 'right' }}>
                        <div className="action-buttons-cell">
                          <button
                            className="btn-icon"
                            onClick={() => handleEditLine(lines[idx])}
                            title="Edit this line"
                          >
                            <Pencil size={14} />
                          </button>
                          <button
                            className="btn-icon danger"
                            onClick={() => handleDeleteLine(lines[idx].id)}
                            title="Remove this line"
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="tfoot-row">
                    <td colSpan={4}>AGGREGATE CARGO TOTALS</td>
                    <td><strong>{aggregate.total_packages}</strong></td>
                    <td>-</td>
                    <td className="numeric-cell"><strong>{formatDec(aggregate.total_cbm, 3)} CBM</strong></td>
                    <td className="numeric-cell"><strong>{formatDec(aggregate.total_gross_weight_kg, 2)} kg</strong></td>
                    <td className="numeric-cell"><strong>{formatDec(aggregate.total_volumetric_weight_kg, 2)} kg</strong></td>
                    <td></td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Volumetric Weight & Freight Mode Details Panel */}
      <div className="cbm-panel detail-mode-panel">
        <div className="panel-head">
          <div className="panel-title">
            <Scale size={16} />
            <span>Volumetric &amp; Chargeable Weight Breakdown ({freightMode.toUpperCase()})</span>
          </div>
          <div className="rounding-toggle">
            <label>
              <input
                type="checkbox"
                checked={perPkgRounding}
                onChange={(e) => setPerPkgRounding(e.target.checked)}
              />
              <span>Per-package chargeable comparison (instead of shipment aggregate)</span>
            </label>
          </div>
        </div>

        <div className="volumetric-info-grid">
          <div className="vol-formula-box">
            <div className="formula-title">FORMULA APPLIED:</div>
            <code>
              Volumetric Weight (kg) = (Length_cm × Width_cm × Height_cm) / {dimensionalDivisor} × Quantity
            </code>
            <p className="formula-desc">
              At divisor {dimensionalDivisor} cm³/kg, 1 CBM equates to{' '}
              <strong>{(1000000 / dimensionalDivisor).toFixed(1)} kg</strong> of volumetric weight.
            </p>
          </div>

          <div className="vol-summary-comparison">
            <div className="comp-row">
              <span>Actual Gross Weight:</span>
              <strong>{formatDec(aggregate.total_gross_weight_kg, 2)} kg</strong>
            </div>
            <div className="comp-row">
              <span>Total Volumetric Weight:</span>
              <strong>{formatDec(aggregate.total_volumetric_weight_kg, 2)} kg</strong>
            </div>
            <div className="comp-row highlight">
              <span>Chargeable Weight:</span>
              <strong>{formatDec(aggregate.chargeable_weight_kg, 2)} kg</strong>
            </div>
            <div className="comp-note">
              {aggregate.total_volumetric_weight_kg > aggregate.total_gross_weight_kg
                ? `Carrier will bill based on Volumetric Weight (${formatDec(aggregate.total_volumetric_weight_kg, 2)} kg) because cargo is lightweight relative to volume.`
                : `Carrier will bill based on Actual Gross Weight (${formatDec(aggregate.total_gross_weight_kg, 2)} kg) because cargo is sufficiently dense.`}
            </div>
          </div>
        </div>

        <div className="cbm-disclaimer-banner">
          <Info size={16} />
          <span>
            <strong>Freight Tariff Disclaimer:</strong> Chargeable weight displayed is an operational estimate.
            Actual airline and shipping lines apply contractual dimensional divisors, minimum shipment charges,
            tare pallet weights, and tariff-specific rounding rules.
          </span>
        </div>
      </div>

      {/* Container Capacity Estimator Panel */}
      <div className="cbm-panel container-panel">
        <div className="panel-head">
          <div className="panel-title">
            <Ship size={16} />
            <span>Shipping Container Capacity Estimator</span>
          </div>

          <div className="container-controls">
            {lines.length > 1 && (
              <div className="estimator-line-pick">
                <label>Evaluate Package:</label>
                <select
                  value={selectedEstimatorLineIndex}
                  onChange={(e) => setSelectedEstimatorLineIndex(parseInt(e.target.value, 10))}
                  className="cbm-select-mini"
                >
                  {lines.map((l, idx) => (
                    <option key={l.id || idx} value={idx}>
                      #{idx + 1}: {l.description} ({l.length}×{l.width}×{l.height} {l.dimension_unit})
                    </option>
                  ))}
                </select>
              </div>
            )}

            <div className="usable-volume-pick">
              <label>Usable Ratio:</label>
              <select
                value={usableRatio}
                onChange={(e) => setUsableRatio(parseFloat(e.target.value))}
                className="cbm-select-mini"
              >
                <option value="0.75">75% (Bulky / Palletized)</option>
                <option value="0.80">80% (Loose Cartons + Allowance)</option>
                <option value="0.85">85% (Standard Hand-Stacked)</option>
                <option value="0.90">90% (Dense Uniform Hand-Pack)</option>
              </select>
            </div>

            <div className="payload-input-wrap">
              <label>Payload Limit (kg):</label>
              <input
                type="number"
                placeholder="Verified Payload"
                value={customPayloadKg}
                onChange={(e) => setCustomPayloadKg(e.target.value)}
                className="cbm-input-mini"
              />
            </div>
          </div>
        </div>

        {/* Container Comparison Cards */}
        <div className="containers-grid">
          {containerEstimates.map((c) => (
            <div key={c.container_key} className="container-card">
              <div className="container-card-head">
                <h4>{c.container_name}</h4>
                <span className="container-dim-tag">
                  {c.internal_length_m} × {c.internal_width_m} × {c.internal_height_m} m
                </span>
              </div>

              <div className="container-volume-specs">
                <div>
                  <small>NOMINAL</small>
                  <strong>{c.nominal_volume_cbm} CBM</strong>
                </div>
                <div>
                  <small>USABLE ({(c.usable_ratio * 100).toFixed(0)}%)</small>
                  <strong>{formatDec(c.usable_volume_cbm, 2)} CBM</strong>
                </div>
              </div>

              <div className="utilization-bar-wrap">
                <div className="utilization-labels">
                  <span>Shipment Volume ({formatDec(aggregate.total_cbm, 2)} CBM)</span>
                  <strong>{Math.min(100, (aggregate.total_cbm / c.usable_volume_cbm) * 100).toFixed(1)}% Usable</strong>
                </div>
                <div className="progress-track">
                  <div
                    className={`progress-fill ${aggregate.total_cbm > c.usable_volume_cbm ? 'overflow' : ''}`}
                    style={{
                      width: `${Math.min(100, (aggregate.total_cbm / c.usable_volume_cbm) * 100)}%`,
                    }}
                  />
                </div>
              </div>

              <div className="container-fit-grid">
                <div className="fit-stat">
                  <small>Max Cartons by Volume</small>
                  <strong>{c.estimated_units_by_volume.toLocaleString()} units</strong>
                </div>

                <div className="fit-stat">
                  <small>Grid Fit (6 Orientations)</small>
                  <strong>{c.estimated_units_by_grid.toLocaleString()} units</strong>
                </div>

                <div className="fit-stat">
                  <small>Est. Grid Weight</small>
                  <strong>{formatDec(c.estimated_cargo_weight_at_grid_kg, 0)} kg</strong>
                </div>

                <div className="fit-stat">
                  <small>Payload Feasibility</small>
                  <span className={`feasibility-badge ${c.payload_feasibility.toLowerCase().replace(/\s/g, '-')}`}>
                    {c.payload_feasibility}
                  </span>
                </div>
              </div>

              <div className="container-fit-footer">
                {aggregate.total_cbm <= c.usable_volume_cbm ? (
                  <span className="fit-status-pass">
                    <CheckCircle2 size={13} /> Current consignment fits in 1 container
                  </span>
                ) : (
                  <span className="fit-status-mult">
                    <AlertTriangle size={13} /> Requires {Math.ceil(aggregate.total_cbm / c.usable_volume_cbm)} containers
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Limitation & Physical Packing Note */}
        <div className="cbm-disclaimer-banner">
          <ShieldCheck size={16} />
          <span>
            <strong>Physical Loading Limitations: </strong>
            {CONTAINER_DISCLAIMER}
          </span>
        </div>
      </div>

      {/* History Drawer Modal */}
      {showHistoryDrawer && (
        <div className="cbm-modal-backdrop" onClick={() => setShowHistoryDrawer(false)}>
          <div className="cbm-history-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-header">
              <div className="drawer-title">
                <History size={18} />
                <h3>Saved Cargo Calculations</h3>
              </div>
              <button className="btn-icon" onClick={() => setShowHistoryDrawer(false)}>
                <X size={16} />
              </button>
            </div>

            <div className="drawer-search">
              <Search size={14} />
              <input
                type="text"
                placeholder="Search by reference or title..."
                value={historySearch}
                onChange={(e) => setHistorySearch(e.target.value)}
              />
            </div>

            <div className="drawer-body">
              {historyLoading ? (
                <div className="drawer-loading">
                  <LoaderCircle size={24} className="spin" />
                  <span>Loading calculations...</span>
                </div>
              ) : savedCalculations.length === 0 ? (
                <div className="drawer-empty">No calculations saved yet.</div>
              ) : (
                savedCalculations
                  .filter((item) =>
                    !historySearch ||
                    item.calculation_reference.toLowerCase().includes(historySearch.toLowerCase()) ||
                    item.title.toLowerCase().includes(historySearch.toLowerCase())
                  )
                  .map((item) => (
                    <div
                      key={item.id}
                      className={`history-calc-item ${activeCalcId === item.id ? 'active' : ''}`}
                    >
                      <div className="calc-item-top">
                        <span className="calc-ref">{item.calculation_reference}</span>
                        <span className="calc-date">{new Date(item.created_at).toLocaleDateString()}</span>
                      </div>
                      <div className="calc-title">{item.title}</div>
                      <div className="calc-metrics">
                        <span><strong>{formatDec(item.total_cbm, 3)}</strong> CBM</span>
                        <span><strong>{formatDec(item.total_gross_weight_kg, 1)}</strong> kg</span>
                        <span><strong>{item.total_packages}</strong> pkgs</span>
                        <span className="calc-mode-pill">{item.freight_mode}</span>
                      </div>
                      <div className="calc-actions">
                        <button
                          className="btn-sm btn-primary-sm"
                          onClick={() => handleLoadSavedCalculation(item)}
                        >
                          Load Calculation
                        </button>
                        <button
                          className="btn-icon danger"
                          onClick={() => handleDeleteSavedCalculation(item.id, item.calculation_reference)}
                          title="Delete calculation"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </div>
                  ))
              )}
            </div>
          </div>
        </div>
      )}

      {/* Print Summary Modal */}
      {showPrintModal && (
        <div className="cbm-modal-backdrop" onClick={() => setShowPrintModal(false)}>
          <div className="cbm-print-modal" onClick={(e) => e.stopPropagation()}>
            <div className="print-modal-head no-print">
              <h3>Consignment Cargo &amp; CBM Summary</h3>
              <div className="print-head-actions">
                <button className="btn-sm btn-secondary" onClick={() => window.print()}>
                  <Printer size={14} /> Print Now
                </button>
                <button className="btn-icon" onClick={() => setShowPrintModal(false)}>
                  <X size={16} />
                </button>
              </div>
            </div>

            <div className="print-document">
              <div className="print-brand-row">
                <h2>TradeSathi AI — Logistics Cargo &amp; CBM Manifest</h2>
                <span className="print-ref">Reference: {activeCalcRef || 'DRAFT-ESTIMATE'}</span>
              </div>

              <div className="print-meta-grid">
                <div>
                  <strong>Consignment Title:</strong> {calcTitle}
                </div>
                <div>
                  <strong>Freight Mode:</strong> {freightMode.toUpperCase()}
                </div>
                <div>
                  <strong>Dimensional Divisor:</strong> {dimensionalDivisor} cm³/kg
                </div>
                <div>
                  <strong>Date:</strong> {new Date().toLocaleDateString()}
                </div>
              </div>

              <table className="print-table">
                <thead>
                  <tr>
                    <th>Line</th>
                    <th>Description</th>
                    <th>Package Type</th>
                    <th>Dimensions</th>
                    <th>Qty</th>
                    <th>CBM/Pkg</th>
                    <th>Total CBM</th>
                    <th>Gross Wt</th>
                    <th>Vol Wt</th>
                  </tr>
                </thead>
                <tbody>
                  {aggregate.lines.map((l, i) => (
                    <tr key={i}>
                      <td>{i + 1}</td>
                      <td>{l.description}</td>
                      <td>{l.package_type}</td>
                      <td>{l.length_orig}×{l.width_orig}×{l.height_orig} {l.dimension_unit}</td>
                      <td>{l.quantity}</td>
                      <td>{formatDec(l.cbm_per_pkg, 4)}</td>
                      <td>{formatDec(l.total_cbm, 4)}</td>
                      <td>{formatDec(l.total_gross_weight_kg, 2)} kg</td>
                      <td>{formatDec(l.volumetric_weight_kg, 2)} kg</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={4}><strong>TOTAL SHIPMENT TALLY</strong></td>
                    <td><strong>{aggregate.total_packages}</strong></td>
                    <td>-</td>
                    <td><strong>{formatDec(aggregate.total_cbm, 3)} CBM</strong></td>
                    <td><strong>{formatDec(aggregate.total_gross_weight_kg, 2)} kg</strong></td>
                    <td><strong>{formatDec(aggregate.total_volumetric_weight_kg, 2)} kg</strong></td>
                  </tr>
                </tfoot>
              </table>

              <div className="print-kpi-summary">
                <div><strong>Chargeable Weight:</strong> {formatDec(aggregate.chargeable_weight_kg, 2)} kg</div>
                <div><strong>Total Volume in CuFt:</strong> {formatDec(aggregate.total_cuft, 2)} cu ft</div>
                <div><strong>Average Weight:</strong> {formatDec(aggregate.average_weight_kg_per_pkg, 2)} kg / package</div>
              </div>

              <div className="print-legal-note">
                <small>
                  Note: Computed by TradeSathi AI Cargo Engine. Real-world stowage is subject to carrier
                  survey, container equipment variation, and pallet clearances.
                </small>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
