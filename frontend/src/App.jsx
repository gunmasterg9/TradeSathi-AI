import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  Anchor,
  ArrowDownToLine,
  ArrowLeft,
  Barcode,
  Bot,
  Boxes,
  Building2,
  Calendar,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CircleAlert,
  ClipboardCheck,
  Clock,
  Copy,
  ExternalLink,
  Eye,
  FileCheck2,
  FileText,
  Filter,
  History,
  Info,
  LayoutDashboard,
  LoaderCircle,
  LockKeyhole,
  MapPin,
  Minus,
  Package,
  Pencil,
  Plus,
  Printer,
  RefreshCw,
  Receipt,
  RotateCcw,
  Scale,
  Search,
  ShieldCheck,
  Ship,
  ShoppingBag,
  ShoppingCart,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  UploadCloud,
  Users,
  Warehouse,
  X,
} from 'lucide-react'
import { apiFetch, API_BASE } from './api'
import { generateAuditBrief, exportAuditJson, HUMAN_REVIEW_DISCLAIMER } from './reportHelper'
import CbmCalculator from './CbmCalculator'
import MasterDataView from './MasterDataView'
import ProcurementView from './ProcurementView'
import WarehouseView from './WarehouseView'
import SalesView from './SalesView'
import ExportView from './ExportView'
import InvoicingView from './InvoicingView'
import DashboardView from './DashboardView'
import PortalView from './PortalView'
import CollaborationView from './CollaborationView'

const MAX_FILES = 8

function renderDiscrepancyEvidence(disc) {
  const docList = disc?.source_documents?.length > 0
    ? disc.source_documents
    : (disc?.doc_values ? Object.keys(disc.doc_values) : [])

  if (!docList || docList.length === 0) return null

  return (
    <div className="disc-evidence-section">
      <div className="disc-evidence-title">
        <FileText size={12} />
        <span>Grounded Document Evidence &amp; Traceability</span>
      </div>
      <div className="disc-evidence-grid">
        {docList.map((file) => {
          const ev = disc.evidence?.[file]
          const rawVal = disc.raw_values?.[file] || ev?.raw_value
          const normVal = disc.normalized_values?.[file] !== undefined ? disc.normalized_values[file] : ev?.normalized_value
          const unit = disc.units?.[file] || ev?.unit
          const snippet = disc.source_snippets?.[file] || ev?.source_snippet
          const displayVal = disc.doc_values?.[file] || (rawVal !== undefined && rawVal !== null ? `${rawVal}${unit ? ' ' + unit : ''}` : 'Not present')

          let groundingStatus = 'Source evidence available'
          let groundingClass = 'grounded'
          if (disc.difference?.includes('Unit ambiguity') || disc.difference?.includes('Not directly comparable')) {
            groundingStatus = 'Comparison blocked by uncertainty'
            groundingClass = 'uncertain'
          } else if (ev?.is_grounded === false || ev?.limitations?.some((l) => l.includes('not grounded'))) {
            groundingStatus = 'Value not grounded in source'
            groundingClass = 'ungrounded'
          } else if (!snippet) {
            groundingStatus = 'Evidence location unavailable'
            groundingClass = 'unavailable'
          }

          const method = ev?.method ? (ev.method.startsWith('ollama') ? 'Local Ollama' : 'Rules Engine') : 'Rules Engine'
          const status = ev?.validation_status || disc.provenance_statuses?.[file] || 'verified'

          return (
            <div key={file} className="disc-evidence-card">
              <div className="disc-evidence-card-head">
                <span className="evidence-filename" title={file}>{file}</span>
                <span className={`grounding-badge badge-${groundingClass}`}>{groundingStatus}</span>
              </div>
              <div className="evidence-meta-row">
                <div className="evidence-val-box">
                  <small>VALUE</small>
                  <strong>{displayVal}</strong>
                  {rawVal && normVal !== undefined && normVal !== null && String(rawVal).trim() !== String(normVal).trim() && (
                    <span className="raw-val-sub">Raw: {rawVal}</span>
                  )}
                </div>
                <div className="evidence-provenance-tags">
                  <span className={`provenance-pill status-${status}`}>{status.toUpperCase()}</span>
                  <span className="method-pill">{method}</span>
                </div>
              </div>
              <div className="evidence-snippet-box">
                <div className="snippet-label-row">
                  <small>EXACT SOURCE SNIPPET</small>
                  {ev?.char_start !== null && ev?.char_start !== undefined && (
                    <span className="snippet-coords">
                      chars {ev.char_start}–{ev.char_end}{ev.page_number ? ` • Page ${ev.page_number}` : ''}
                    </span>
                  )}
                </div>
                {snippet ? (
                  <pre className="snippet-text">"{snippet}"</pre>
                ) : (
                  <div className="snippet-unavailable">
                    {ev?.limitations?.[0] || 'Exact snippet location could not be isolated in document.'}
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function App() {
  const [models, setModels] = useState([])
  const [ollamaAvailable, setOllamaAvailable] = useState(false)
  const [model, setModel] = useState('')
  const [files, setFiles] = useState([])
  const [dragging, setDragging] = useState(false)
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [loadingSample, setLoadingSample] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)
  const [activeWorkspace, setActiveWorkspace] = useState('export')
  const [activeTab, setActiveTab] = useState('audit') // 'audit' | 'shipments'
  const [recentAnalyses, setRecentAnalyses] = useState([])
  const [showHistory, setShowHistory] = useState(false)
  const [selectedDocTab, setSelectedDocTab] = useState(0)
  const [copiedBrief, setCopiedBrief] = useState(false)
  const [expandedEvidence, setExpandedEvidence] = useState({})

  // Milestone 2B: Shipment Management State
  const [shipments, setShipments] = useState([])
  const [selectedShipmentForAudit, setSelectedShipmentForAudit] = useState(null)
  const [selectedShipmentDetail, setSelectedShipmentDetail] = useState(null)
  const [shipmentAnalyses, setShipmentAnalyses] = useState([])
  const [shipmentSearch, setShipmentSearch] = useState('')
  const [shipmentStatusFilter, setShipmentStatusFilter] = useState('')
  const [isShipmentModalOpen, setIsShipmentModalOpen] = useState(false)
  const [editingShipment, setEditingShipment] = useState(null)
  const [shipmentFormLoading, setShipmentFormLoading] = useState(false)
  const [shipmentFormError, setShipmentFormError] = useState('')
  const [shipmentFormData, setShipmentFormData] = useState({
    reference: '',
    exporter: '',
    buyer: '',
    product_description: '',
    destination_country: '',
    destination_port: '',
    planned_shipment_date: '',
    incoterm: '',
    named_place: '',
    notes: '',
  })

  // Milestone 2C: Document Register & Readiness State
  const [shipmentDocuments, setShipmentDocuments] = useState([])
  const [shipmentReadiness, setShipmentReadiness] = useState(null)
  const [isUploadDocModalOpen, setIsUploadDocModalOpen] = useState(false)
  const [uploadDocFiles, setUploadDocFiles] = useState([])
  const [uploadDocType, setUploadDocType] = useState('')
  const [uploadDocNotes, setUploadDocNotes] = useState('')
  const [uploadDocDuplicateAction, setUploadDocDuplicateAction] = useState('reject')
  const [uploadDocLoading, setUploadDocLoading] = useState(false)
  const [uploadDocError, setUploadDocError] = useState('')

  const [isReviewModalOpen, setIsReviewModalOpen] = useState(false)
  const [reviewingDoc, setReviewingDoc] = useState(null)
  const [reviewStatusChoice, setReviewStatusChoice] = useState('verified_by_user')
  const [reviewNotesInput, setReviewNotesInput] = useState('')
  const [reviewerNameInput, setReviewerNameInput] = useState('Rahul (User)')
  const [reviewLoading, setReviewLoading] = useState(false)
  const [reviewError, setReviewError] = useState('')
  const [reconcilingDirectly, setReconcilingDirectly] = useState(false)
  const [shipmentCargoMeasurements, setShipmentCargoMeasurements] = useState(null)

  // Milestone 2D: Audit History & Reporting State
  const [historyAudits, setHistoryAudits] = useState([])
  const [historyTotal, setHistoryTotal] = useState(0)
  const [historyPage, setHistoryPage] = useState(1)
  const [historyPageSize, setHistoryPageSize] = useState(20)
  const [historyTotalPages, setHistoryTotalPages] = useState(1)
  const [historySearch, setHistorySearch] = useState('')
  const [historyStatus, setHistoryStatus] = useState('all')
  const [historyAuditType, setHistoryAuditType] = useState('all')
  const [historyDateFrom, setHistoryDateFrom] = useState('')
  const [historyDateTo, setHistoryDateTo] = useState('')
  const [historySortOrder, setHistorySortOrder] = useState('desc')
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState('')
  const [selectedHistoricalAudit, setSelectedHistoricalAudit] = useState(null)
  const [historicalDetailLoading, setHistoricalDetailLoading] = useState(false)
  const [historicalDetailError, setHistoricalDetailError] = useState('')
  const [historyDetailDocTab, setHistoryDetailDocTab] = useState(0)
  const [historyExpandedEvidence, setHistoryExpandedEvidence] = useState({})
  const [historyCopiedBrief, setHistoryCopiedBrief] = useState(false)
  const [historyCopyFeedback, setHistoryCopyFeedback] = useState('')

  // Milestone 2E.4 Finding Review Modal & State
  const [isReviewFindingModalOpen, setIsReviewFindingModalOpen] = useState(false)
  const [reviewFindingTarget, setReviewFindingTarget] = useState(null)
  const [reviewFindingAction, setReviewFindingAction] = useState('resolved')
  const [reviewFindingReviewer, setReviewFindingReviewer] = useState('Local Operator')
  const [reviewFindingReason, setReviewFindingReason] = useState('')
  const [reviewFindingNotes, setReviewFindingNotes] = useState('')
  const [reviewFindingEvidence, setReviewFindingEvidence] = useState('')
  const [reviewFindingCorrectedVal, setReviewFindingCorrectedVal] = useState('')
  const [reviewFindingCorrectedUnit, setReviewFindingCorrectedUnit] = useState('')
  const [reviewFindingSource, setReviewFindingSource] = useState('')
  const [reviewFindingLoading, setReviewFindingLoading] = useState(false)
  const [reviewFindingError, setReviewFindingError] = useState('')
  const [expandedReviewTrails, setExpandedReviewTrails] = useState({})

  const totalBytes = useMemo(() => files.reduce((sum, file) => sum + file.size, 0), [files])

  async function refreshModels() {
    setRefreshing(true)
    try {
      const data = await apiFetch('/api/models', {}, 'Cannot reach models service')
      setOllamaAvailable(Boolean(data?.available))
      setModels(data?.models || [])
      setModel((current) => (current && (data?.models || []).includes(current) ? current : ''))
    } catch {
      setOllamaAvailable(false)
      setModels([])
    } finally {
      setRefreshing(false)
    }
  }

  async function fetchRecentAnalyses() {
    try {
      const data = await apiFetch('/api/analyses', {}, 'Failed to retrieve recent analyses')
      setRecentAnalyses(data?.analyses || [])
    } catch {
      setRecentAnalyses([])
    }
  }

  async function fetchShipments() {
    try {
      const params = new URLSearchParams()
      if (shipmentSearch.trim()) params.append('search', shipmentSearch.trim())
      if (shipmentStatusFilter.trim()) params.append('status', shipmentStatusFilter.trim())
      const data = await apiFetch(`/api/shipments?${params.toString()}`, {}, 'Failed to list shipments')
      setShipments(data?.shipments || [])
    } catch {
      setShipments([])
    }
  }

  async function fetchShipmentAnalyses(shipmentId) {
    try {
      const data = await apiFetch(`/api/shipments/${shipmentId}/analyses`, {}, 'Failed to list shipment audits')
      setShipmentAnalyses(data?.analyses || [])
    } catch {
      setShipmentAnalyses([])
    }
  }

  async function fetchShipmentDocuments(shipmentId) {
    try {
      const data = await apiFetch(`/api/shipments/${shipmentId}/documents`, {}, 'Failed to list shipment documents')
      setShipmentDocuments(data?.documents || [])
    } catch {
      setShipmentDocuments([])
    }
  }

  async function fetchShipmentReadiness(shipmentId) {
    try {
      const data = await apiFetch(`/api/shipments/${shipmentId}/readiness`, {}, 'Failed to evaluate readiness')
      setShipmentReadiness(data)
    } catch {
      setShipmentReadiness(null)
    }
  }

  useEffect(() => {
    refreshModels()
    fetchRecentAnalyses()
    fetchShipments()
    fetchHistoryAudits()
  }, [])

  useEffect(() => {
    fetchShipments()
  }, [shipmentSearch, shipmentStatusFilter])

  useEffect(() => {
    if (activeTab === 'history') {
      fetchHistoryAudits()
    }
  }, [
    historySearch,
    historyStatus,
    historyAuditType,
    historyDateFrom,
    historyDateTo,
    historySortOrder,
    historyPage,
    historyPageSize,
    activeTab,
  ])

  function addFiles(incoming) {
    setError('')
    const supported = ['.pdf', '.txt', '.eml', '.docx']
    const newFiles = Array.from(incoming || [])
    const rejected = newFiles.filter((file) => !supported.some((ext) => file.name.toLowerCase().endsWith(ext)))
    if (rejected.length) {
      setError(`Unsupported file(s): ${rejected.map((f) => f.name).join(', ')}. Use PDF, TXT, EML, or DOCX.`)
    }
    const accepted = newFiles.filter((file) => supported.some((ext) => file.name.toLowerCase().endsWith(ext)))
    setFiles((current) => {
      const merged = [...current]
      for (const file of accepted) {
        if (!merged.some((existing) => existing.name === file.name && existing.size === file.size)) {
          merged.push(file)
        }
      }
      return merged.slice(0, MAX_FILES)
    })
  }

  function removeFile(index) {
    setFiles((current) => current.filter((_, i) => i !== index))
  }

  function resetAll() {
    setFiles([])
    setResult(null)
    setError('')
    setSelectedDocTab(0)
    setSelectedShipmentForAudit(null)
  }

  async function loadSampleFiles() {
    setLoadingSample(true)
    setError('')
    try {
      const data = await apiFetch('/api/samples', {}, 'Failed to load sample documents')
      const samples = data?.samples || []
      if (!samples.length) {
        throw new Error('Backend returned 0 sample documents. Verify sample-documents folder.')
      }
      const fileObjects = samples.map(
        (s) => new File([s.content], s.filename, { type: 'text/plain', lastModified: Date.now() })
      )
      setFiles(fileObjects)
      setResult(null)
      setSelectedShipmentForAudit(null)
    } catch (err) {
      setError(err.message || 'Failed to load sample documents.')
    } finally {
      setLoadingSample(false)
    }
  }

  async function runAnalysis() {
    if (!files.length) {
      setError('Add at least one document first.')
      return
    }
    setLoading(true)
    setError('')
    setResult(null)
    const formData = new FormData()
    files.forEach((file) => formData.append('files', file))
    if (model) formData.append('model', model)
    if (selectedShipmentForAudit) {
      formData.append('shipment_id', selectedShipmentForAudit)
    }

    try {
      const data = await apiFetch(
        '/api/analyze',
        { method: 'POST', body: formData },
        'Reconciliation analysis failed'
      )
      if (!data) {
        throw new Error('Server returned an empty response. Verify backend status.')
      }
      setResult(data)
      setSelectedDocTab(0)
      fetchRecentAnalyses()
      fetchShipments()
    } catch (err) {
      setError(err.message || 'Could not reach the API. Start FastAPI and retry.')
    } finally {
      setLoading(false)
    }
  }

  async function fetchHistoryAudits(overrides = {}) {
    setHistoryLoading(true)
    setHistoryError('')
    try {
      const params = new URLSearchParams()
      const s = overrides.search !== undefined ? overrides.search : historySearch
      if (s && s.trim()) params.append('search', s.trim())

      const st = overrides.status !== undefined ? overrides.status : historyStatus
      if (st && st !== 'all') params.append('status', st)

      const at = overrides.auditType !== undefined ? overrides.auditType : historyAuditType
      if (at && at !== 'all') params.append('audit_type', at)

      const df = overrides.dateFrom !== undefined ? overrides.dateFrom : historyDateFrom
      if (df) params.append('date_from', df)

      const dt = overrides.dateTo !== undefined ? overrides.dateTo : historyDateTo
      if (dt) params.append('date_to', dt)

      const so = overrides.sortOrder !== undefined ? overrides.sortOrder : historySortOrder
      params.append('sort_order', so)

      const p = overrides.page !== undefined ? overrides.page : historyPage
      params.append('page', String(p))

      const ps = overrides.pageSize !== undefined ? overrides.pageSize : historyPageSize
      params.append('page_size', String(ps))

      const data = await apiFetch(`/api/analyses?${params.toString()}`, {}, 'Failed to retrieve audit history')
      setHistoryAudits(data?.analyses || [])
      setHistoryTotal(data?.total || 0)
      setHistoryPage(data?.page || 1)
      setHistoryPageSize(data?.page_size || 20)
      setHistoryTotalPages(data?.total_pages || 1)
    } catch (err) {
      setHistoryError(err.message || 'Error loading audit history')
      setHistoryAudits([])
      setHistoryTotal(0)
    } finally {
      setHistoryLoading(false)
    }
  }

  async function loadHistoricalAuditDetail(id) {
    setHistoricalDetailLoading(true)
    setHistoricalDetailError('')
    setHistoryDetailDocTab(0)
    setHistoryExpandedEvidence({})
    try {
      const data = await apiFetch(`/api/analyses/${id}`, {}, 'Failed to load historical audit detail')
      setSelectedHistoricalAudit(data)
      setActiveWorkspace('export')
      setActiveTab('history')
    } catch (err) {
      const msg = err.message || `Failed to load historical audit "${id}". Historical payload may be missing or malformed.`
      setHistoricalDetailError(msg)
      setSelectedHistoricalAudit({ id, malformed: true, error: msg })
      setActiveWorkspace('export')
      setActiveTab('history')
    } finally {
      setHistoricalDetailLoading(false)
    }
  }

  async function loadSavedAnalysis(id) {
    try {
      const data = await apiFetch(`/api/analyses/${id}`, {}, 'Analysis not found')
      setResult(data)
      setSelectedDocTab(0)
      setShowHistory(false)
      setActiveWorkspace('export')
      setActiveTab('audit')
    } catch (err) {
      setError(err.message)
    }
  }

  async function deleteSavedAnalysis(e, id) {
    e.stopPropagation()
    try {
      await apiFetch(`/api/analyses/${id}`, { method: 'DELETE' }, 'Failed to delete analysis')
      fetchRecentAnalyses()
      fetchHistoryAudits()
      if (result && result.id === id) {
        setResult(null)
      }
      if (selectedHistoricalAudit && selectedHistoricalAudit.id === id) {
        setSelectedHistoricalAudit(null)
      }
    } catch {
      // ignore
    }
  }

  function handleCopyHistoricalBrief(audit) {
    if (!audit) return
    setHistoryCopyFeedback('')
    const brief = generateAuditBrief(audit)
    const triggerSuccess = () => {
      setHistoryCopiedBrief(true)
      setTimeout(() => setHistoryCopiedBrief(false), 2500)
    }

    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(brief)
        .then(triggerSuccess)
        .catch(() => {
          fallbackCopyText(brief)
          triggerSuccess()
        })
    } else {
      fallbackCopyText(brief)
      triggerSuccess()
    }
  }

  function handleExportHistoricalJson(audit) {
    if (!audit) return
    const res = exportAuditJson(audit)
    if (!res) return
    const blob = new Blob([res.jsonString], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = res.filename
    link.click()
    URL.revokeObjectURL(url)
  }

  async function handleQuickCopyBrief(e, id) {
    e.stopPropagation()
    try {
      const data = await apiFetch(`/api/analyses/${id}`, {}, 'Failed to fetch audit for brief')
      handleCopyHistoricalBrief(data)
    } catch (err) {
      alert(`Could not copy brief: ${err.message}`)
    }
  }

  async function handleQuickExportJson(e, id) {
    e.stopPropagation()
    try {
      const data = await apiFetch(`/api/analyses/${id}`, {}, 'Failed to fetch audit for export')
      handleExportHistoricalJson(data)
    } catch (err) {
      alert(`Could not export JSON: ${err.message}`)
    }
  }

  async function handleDeleteHistoricalAudit(e, id) {
    e.stopPropagation()
    if (!window.confirm(`Delete historical audit "${id}" permanently?`)) return
    try {
      await apiFetch(`/api/analyses/${id}`, { method: 'DELETE' }, 'Failed to delete audit')
      fetchHistoryAudits()
      fetchRecentAnalyses()
      if (selectedHistoricalAudit && selectedHistoricalAudit.id === id) {
        setSelectedHistoricalAudit(null)
      }
      if (result && result.id === id) {
        setResult(null)
      }
    } catch (err) {
      alert(`Failed to delete audit: ${err.message}`)
    }
  }

  function reopenInAuditWorkspace(audit) {
    setResult(audit)
    setSelectedDocTab(0)
    setActiveWorkspace('export')
    setActiveTab('audit')
  }

  function downloadJson() {
    if (!result) return
    handleExportHistoricalJson(result)
  }

  function copyBrief() {
    if (!result) return
    const brief = generateAuditBrief(result)
    const triggerSuccess = () => {
      setCopiedBrief(true)
      setTimeout(() => setCopiedBrief(false), 2500)
    }

    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(brief)
        .then(triggerSuccess)
        .catch(() => {
          fallbackCopyText(brief)
          triggerSuccess()
        })
    } else {
      fallbackCopyText(brief)
      triggerSuccess()
    }
  }

  function fallbackCopyText(text) {
    try {
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.focus()
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
    } catch {
      // silent
    }
  }

  function printBrief() {
    window.print()
  }

  function toggleEvidence(key) {
    setExpandedEvidence((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  // Milestone 2E.4: Finding Review & Resolution Handlers
  function openReviewFindingModal(disc, analysisId, source, defaultAction = 'resolved') {
    setReviewFindingTarget({ disc, analysisId, source })
    setReviewFindingAction(defaultAction)
    setReviewFindingReviewer('Local Operator')
    setReviewFindingReason('')
    setReviewFindingNotes('')
    setReviewFindingEvidence(disc.evidence_ids ? Object.values(disc.evidence_ids).filter(Boolean).join(', ') : '')
    setReviewFindingCorrectedVal(disc.normalized_values ? Object.values(disc.normalized_values)[0] || '' : '')
    setReviewFindingCorrectedUnit(disc.units ? Object.values(disc.units)[0] || '' : '')
    setReviewFindingSource('')
    setReviewFindingError('')
    setIsReviewFindingModalOpen(true)
  }

  async function handleQuickReviewAction(disc, analysisId, source, action) {
    if (!analysisId) return
    try {
      const fId = disc.id || disc.field
      const data = await apiFetch(
        `/api/analyses/${analysisId}/findings/${fId}/review`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            action,
            reviewer: 'Local Operator',
            notes: `Review status updated to ${action.replace(/_/g, ' ')}`,
          }),
        },
        'Failed to update review status'
      )
      applyUpdatedFinding(data.finding, source)
    } catch (err) {
      alert(err.message)
    }
  }

  async function handleSaveFindingReview(e) {
    e.preventDefault()
    if (!reviewFindingTarget?.analysisId) return
    setReviewFindingLoading(true)
    setReviewFindingError('')

    const evidenceList = reviewFindingEvidence
      ? reviewFindingEvidence.split(',').map((s) => s.trim()).filter(Boolean)
      : []

    const payload = {
      action: reviewFindingAction,
      reviewer: reviewFindingReviewer.trim() || 'Local Operator',
      reason: reviewFindingReason.trim(),
      notes: reviewFindingNotes.trim(),
      supporting_evidence: evidenceList,
      corrected_value: reviewFindingCorrectedVal !== '' ? reviewFindingCorrectedVal : null,
      corrected_unit: reviewFindingCorrectedUnit.trim() || null,
      source: reviewFindingSource.trim() || null,
    }

    try {
      const fId = reviewFindingTarget.disc.id || reviewFindingTarget.disc.field
      const data = await apiFetch(
        `/api/analyses/${reviewFindingTarget.analysisId}/findings/${fId}/review`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
        'Failed to save finding review'
      )
      applyUpdatedFinding(data.finding, reviewFindingTarget.source)
      setIsReviewFindingModalOpen(false)
      fetchHistoryAudits()
      fetchShipments()
    } catch (err) {
      setReviewFindingError(err.message)
    } finally {
      setReviewFindingLoading(false)
    }
  }

  function applyUpdatedFinding(updatedFinding, source) {
    if (source === 'active' && result) {
      setResult((prev) => {
        if (!prev) return prev
        const newDiscs = (prev.discrepancies || []).map((d) =>
          d.id === updatedFinding.id || d.field === updatedFinding.field ? { ...d, ...updatedFinding } : d
        )
        return { ...prev, discrepancies: newDiscs }
      })
    } else if (source === 'historical' && selectedHistoricalAudit) {
      setSelectedHistoricalAudit((prev) => {
        if (!prev) return prev
        const newDiscs = (prev.discrepancies || []).map((d) =>
          d.id === updatedFinding.id || d.field === updatedFinding.field ? { ...d, ...updatedFinding } : d
        )
        return { ...prev, discrepancies: newDiscs }
      })
    }
  }

  function toggleReviewTrail(findingId) {
    setExpandedReviewTrails((prev) => ({ ...prev, [findingId]: !prev[findingId] }))
  }

  function renderDiscrepancyReviewSection(disc, analysisId, source) {
    if (!analysisId) return null
    const fId = disc.id || disc.field
    const status = disc.review_status || 'pending_review'
    const isResolved = status === 'resolved'
    const history = disc.review_history || []
    const isTrailExpanded = Boolean(expandedReviewTrails[fId])

    return (
      <div className="disc-review-container">
        {/* Human Resolution Banner if resolved */}
        {isResolved && disc.resolution && (
          <div className="disc-resolution-banner">
            <div className="resolution-header-row">
              <span className="resolution-title">
                <CheckCircle2 size={13} /> Human Resolution Verified
              </span>
              <span className="resolution-meta-sub">
                {disc.resolution.resolved_by || 'Operator'} • {new Date(disc.resolution.resolved_at).toLocaleString()}
              </span>
            </div>
            <div className="resolution-reason-text">
              <strong>Rationale:</strong> {disc.resolution.reason}
            </div>
            {(disc.resolution.corrected_value !== null && disc.resolution.corrected_value !== undefined) || disc.resolution.supporting_evidence?.length > 0 ? (
              <div className="resolution-corrections-row">
                {disc.resolution.corrected_value !== null && disc.resolution.corrected_value !== undefined && (
                  <span className="correction-item">
                    Corrected: <strong>{disc.resolution.corrected_value} {disc.resolution.corrected_unit || ''}</strong>
                  </span>
                )}
                {disc.resolution.supporting_evidence?.length > 0 && (
                  <span className="correction-item">
                    Evidence: <em>{disc.resolution.supporting_evidence.join(', ')}</em>
                  </span>
                )}
              </div>
            ) : null}
          </div>
        )}

        {/* Review Action Toolbar */}
        <div className="disc-review-bar">
          <div className="disc-review-status-group">
            <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--slate-400)' }}>Review Lifecycle:</span>
            <span className={`review-state-badge state-${status}`}>
              {status.replace(/_/g, ' ')}
            </span>
          </div>

          <div className="disc-review-action-btns">
            {!isResolved ? (
              <>
                {status !== 'in_review' && (
                  <button
                    className="rev-btn"
                    title="Mark finding as in-review"
                    onClick={() => handleQuickReviewAction(disc, analysisId, source, 'in_review')}
                  >
                    Start Review
                  </button>
                )}
                {status !== 'acknowledged' && (
                  <button
                    className="rev-btn"
                    title="Acknowledge issue without resolving"
                    onClick={() => handleQuickReviewAction(disc, analysisId, source, 'acknowledged')}
                  >
                    Acknowledge
                  </button>
                )}
                <button
                  className="rev-btn escalate"
                  title="Escalate finding to senior reviewer"
                  onClick={() => openReviewFindingModal(disc, analysisId, source, 'escalated')}
                >
                  <AlertTriangle size={12} /> Escalate
                </button>
                <button
                  className="rev-btn resolve"
                  title="Resolve finding with supporting evidence or correction"
                  onClick={() => openReviewFindingModal(disc, analysisId, source, 'resolved')}
                >
                  <Check size={12} /> Resolve Finding
                </button>
              </>
            ) : (
              <button
                className="rev-btn reopen"
                title="Reopen finding if new information contradicts resolution"
                onClick={() => openReviewFindingModal(disc, analysisId, source, 'reopened')}
              >
                <RotateCcw size={12} /> Reopen Finding
              </button>
            )}

            {history.length > 0 && (
              <button
                className="rev-btn"
                style={{ fontSize: 10.5 }}
                title="Toggle decision audit trail"
                onClick={() => toggleReviewTrail(fId)}
              >
                <History size={12} /> Trail ({history.length})
              </button>
            )}
          </div>
        </div>

        {/* Expandable Decision Audit Trail */}
        {isTrailExpanded && history.length > 0 && (
          <div className="review-history-drawer">
            <div className="review-history-head">Append-Only Decision Audit Trail ({history.length} events)</div>
            <div className="review-timeline">
              {history.map((ev, i) => (
                <div key={ev.id || i} className="review-timeline-item">
                  <div className="timeline-meta">
                    <strong>{ev.reviewer || 'Operator'}</strong>
                    <span>transitioned from <code>{ev.previous_state}</code> to <code>{ev.new_state}</code></span>
                    <span>• {new Date(ev.timestamp).toLocaleString()}</span>
                  </div>
                  {(ev.reason || ev.notes) && (
                    <div className="timeline-note">"{ev.reason || ev.notes}"</div>
                  )}
                  {ev.corrected_value !== null && ev.corrected_value !== undefined && (
                    <div style={{ fontSize: 11, color: '#38bdf8' }}>
                      Corrected: {ev.corrected_value} {ev.corrected_unit || ''}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    )
  }

  // Shipment Actions
  function openCreateShipmentModal() {
    setEditingShipment(null)
    setShipmentFormError('')
    setShipmentFormData({
      reference: `SHP-${new Date().getFullYear()}-${Math.floor(100 + Math.random() * 900)}`,
      exporter: '',
      buyer: '',
      product_description: '',
      destination_country: '',
      destination_port: '',
      planned_shipment_date: '',
      incoterm: 'CIF',
      named_place: '',
      notes: '',
    })
    setIsShipmentModalOpen(true)
  }

  function openEditShipmentModal(shipment) {
    setEditingShipment(shipment)
    setShipmentFormError('')
    setShipmentFormData({
      reference: shipment.reference || '',
      exporter: shipment.exporter || '',
      buyer: shipment.buyer || '',
      product_description: shipment.product_description || '',
      destination_country: shipment.destination_country || '',
      destination_port: shipment.destination_port || '',
      planned_shipment_date: shipment.planned_shipment_date || '',
      incoterm: shipment.incoterm || 'CIF',
      named_place: shipment.named_place || '',
      notes: shipment.notes || '',
    })
    setIsShipmentModalOpen(true)
  }

  async function handleSaveShipment(e) {
    e.preventDefault()
    if (!shipmentFormData.reference.trim()) {
      setShipmentFormError('Shipment reference is required.')
      return
    }
    setShipmentFormLoading(true)
    setShipmentFormError('')

    try {
      const url = editingShipment ? `/api/shipments/${editingShipment.id}` : '/api/shipments'
      const method = editingShipment ? 'PATCH' : 'POST'

      const data = await apiFetch(
        url,
        {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(shipmentFormData),
        },
        'Failed to save shipment'
      )

      setIsShipmentModalOpen(false)
      fetchShipments()
      if (selectedShipmentDetail && editingShipment && selectedShipmentDetail.id === editingShipment.id) {
        setSelectedShipmentDetail(data)
      }
    } catch (err) {
      setShipmentFormError(err.message)
    } finally {
      setShipmentFormLoading(false)
    }
  }

  async function handleDeleteShipment(shipmentId, reference) {
    if (
      !window.confirm(
        `Are you sure you want to delete shipment "${reference}"?\n\nAttached register documents will be removed. All previous audit analyses will remain safely preserved in compliance history.`
      )
    ) {
      return
    }
    try {
      await apiFetch(`/api/shipments/${shipmentId}`, { method: 'DELETE' }, 'Failed to delete shipment')
      if (selectedShipmentDetail && selectedShipmentDetail.id === shipmentId) {
        setSelectedShipmentDetail(null)
      }
      fetchShipments()
    } catch (err) {
      alert(err.message)
    }
  }

  async function fetchShipmentCargoMeasurements(shipmentId) {
    try {
      const data = await apiFetch(`/api/shipments/${shipmentId}/cargo-measurements`)
      setShipmentCargoMeasurements(data)
    } catch (err) {
      console.warn('Failed to fetch cargo measurements:', err.message)
      setShipmentCargoMeasurements(null)
    }
  }

  async function viewShipmentDetail(shipment) {
    setSelectedShipmentDetail(shipment)
    fetchShipmentAnalyses(shipment.id)
    fetchShipmentDocuments(shipment.id)
    fetchShipmentReadiness(shipment.id)
    fetchShipmentCargoMeasurements(shipment.id)
  }

  function openUploadDocModal() {
    setUploadDocFiles([])
    setUploadDocType('')
    setUploadDocNotes('')
    setUploadDocDuplicateAction('reject')
    setUploadDocError('')
    setIsUploadDocModalOpen(true)
  }

  async function handleUploadShipmentDocs(e) {
    e.preventDefault()
    if (!uploadDocFiles.length) {
      setUploadDocError('Select at least one document file to upload.')
      return
    }
    setUploadDocLoading(true)
    setUploadDocError('')
    try {
      const formData = new FormData()
      for (const file of uploadDocFiles) {
        formData.append('files', file)
      }
      if (uploadDocType.trim()) {
        formData.append('document_type', uploadDocType.trim())
      }
      if (uploadDocNotes.trim()) {
        formData.append('notes', uploadDocNotes.trim())
      }
      formData.append('duplicate_action', uploadDocDuplicateAction)

      await apiFetch(
        `/api/shipments/${selectedShipmentDetail.id}/documents`,
        { method: 'POST', body: formData },
        'Failed to upload document(s)'
      )
      setIsUploadDocModalOpen(false)
      fetchShipmentDocuments(selectedShipmentDetail.id)
      fetchShipmentReadiness(selectedShipmentDetail.id)
      fetchShipments()
    } catch (err) {
      setUploadDocError(err.message)
    } finally {
      setUploadDocLoading(false)
    }
  }

  function openReviewDocModal(doc) {
    setReviewingDoc(doc)
    setReviewStatusChoice(doc.review_status === 'verified_by_user' ? 'verified_by_user' : 'verified_by_user')
    setReviewNotesInput(doc.review_notes || '')
    setReviewerNameInput(doc.last_reviewed_by || 'Rahul (User)')
    setReviewError('')
    setIsReviewModalOpen(true)
  }

  async function handleQuickReviewChange(docId, newStatus) {
    try {
      await apiFetch(
        `/api/shipments/${selectedShipmentDetail.id}/documents/${docId}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            review_status: newStatus,
            last_reviewed_by: 'Rahul (User)',
            review_notes: `Marked as ${newStatus.replace(/_/g, ' ')} via quick action`,
          }),
        },
        'Failed to update review status'
      )
      fetchShipmentDocuments(selectedShipmentDetail.id)
      fetchShipmentReadiness(selectedShipmentDetail.id)
    } catch (err) {
      alert(err.message)
    }
  }

  async function handleSaveDocReview(e) {
    e.preventDefault()
    setReviewLoading(true)
    setReviewError('')
    try {
      await apiFetch(
        `/api/shipments/${selectedShipmentDetail.id}/documents/${reviewingDoc.id}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            review_status: reviewStatusChoice,
            last_reviewed_by: reviewerNameInput.trim() || 'User',
            review_notes: reviewNotesInput.trim() || null,
          }),
        },
        'Failed to update review decision'
      )
      setIsReviewModalOpen(false)
      fetchShipmentDocuments(selectedShipmentDetail.id)
      fetchShipmentReadiness(selectedShipmentDetail.id)
    } catch (err) {
      setReviewError(err.message)
    } finally {
      setReviewLoading(false)
    }
  }

  async function handleDeleteShipmentDoc(docId) {
    if (!confirm('Are you sure you want to remove this document from the register?')) return
    try {
      await apiFetch(
        `/api/shipments/${selectedShipmentDetail.id}/documents/${docId}`,
        { method: 'DELETE' },
        'Failed to delete document'
      )
      fetchShipmentDocuments(selectedShipmentDetail.id)
      fetchShipmentReadiness(selectedShipmentDetail.id)
      fetchShipments()
    } catch (err) {
      alert(err.message)
    }
  }

  async function handleReconcileDirectly() {
    setReconcilingDirectly(true)
    try {
      const formData = new FormData()
      if (model) formData.append('model', model)
      await apiFetch(
        `/api/shipments/${selectedShipmentDetail.id}/reconcile`,
        { method: 'POST', body: formData },
        'Failed to execute direct reconciliation'
      )
      fetchShipmentAnalyses(selectedShipmentDetail.id)
      fetchShipmentReadiness(selectedShipmentDetail.id)
      fetchShipments()
      const shpData = await apiFetch(`/api/shipments/${selectedShipmentDetail.id}`, {}, 'Failed to refresh shipment')
      if (shpData) {
        setSelectedShipmentDetail(shpData)
      }
    } catch (err) {
      alert(err.message)
    } finally {
      setReconcilingDirectly(false)
    }
  }

  function launchReconciliationForShipment(shipment) {
    setSelectedShipmentForAudit(shipment.id)
    setSelectedShipmentDetail(null)
    setActiveTab('audit')
  }

  const warnings = result?.discrepancies?.filter((item) => item.severity in ['critical', 'warning'] || item.severity === 'warning' || item.severity === 'critical') || []
  const criticals = result?.discrepancies?.filter((item) => item.severity === 'critical') || []

  const linkedShipmentObj = useMemo(() => {
    if (!selectedShipmentForAudit) return null
    return shipments.find((s) => s.id === selectedShipmentForAudit) || null
  }, [selectedShipmentForAudit, shipments])

  return (
    <div className="app-shell">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="brand-lockup">
          <div className="brand-mark">
            <Ship size={23} strokeWidth={2.2} />
          </div>
          <div>
            <div className="brand-name">
              TradeSathi<span> AI</span>
            </div>
            <div className="brand-caption">TRADE OPERATIONS COPILOT</div>
          </div>
        </div>

        <div className="workspace-label">WORKSPACES</div>
        <button
          className={`nav-item ${activeWorkspace === 'export' ? 'selected' : ''}`}
          onClick={() => setActiveWorkspace('export')}
        >
          <FileCheck2 size={18} />
          <span>ExportMate</span>
          <span className="nav-pill">MVP</span>
        </button>
        <button
          className={`nav-item ${activeWorkspace === 'port' ? 'selected' : ''}`}
          onClick={() => setActiveWorkspace('port')}
        >
          <Anchor size={18} />
          <span>PortSathi</span>
          <span className="soon-pill">PHASE 2</span>
        </button>

        {activeWorkspace === 'export' && (
          <>
            <div className="sidebar-divider" />
            <div className="workspace-label">EXPORT OPERATIONS</div>
            <button
              className={`nav-item ${activeTab === 'dashboard' ? 'selected' : ''}`}
              onClick={() => {
                setActiveTab('dashboard')
                setSelectedShipmentDetail(null)
                setSelectedHistoricalAudit(null)
              }}
            >
              <LayoutDashboard size={18} />
              <span>Executive Dashboard</span>
            </button>
            <button
              className={`nav-item ${activeTab === 'audit' ? 'selected' : ''}`}
              onClick={() => {
                setActiveTab('audit')
                setSelectedShipmentDetail(null)
                setSelectedHistoricalAudit(null)
              }}
            >
              <FileCheck2 size={18} />
              <span>Document Audit</span>
            </button>
            <button
              className={`nav-item ${activeTab === 'shipments' ? 'selected' : ''}`}
              onClick={() => {
                setActiveTab('shipments')
                setSelectedShipmentDetail(null)
                setSelectedHistoricalAudit(null)
                fetchShipments()
              }}
            >
              <Package size={18} />
              <span>Shipments</span>
              {shipments.length > 0 && <span className="count-pill">{shipments.length}</span>}
            </button>
            <button
              className={`nav-item ${activeTab === 'export_ops' ? 'selected' : ''}`}
              onClick={() => {
                setActiveTab('export_ops')
                setSelectedShipmentDetail(null)
                setSelectedHistoricalAudit(null)
              }}
            >
              <Ship size={18} />
              <span>Export Operations</span>
            </button>
            <button
              className={`nav-item ${activeTab === 'history' ? 'selected' : ''}`}
              onClick={() => {
                setActiveTab('history')
                setSelectedShipmentDetail(null)
                setSelectedHistoricalAudit(null)
                fetchHistoryAudits({ page: 1 })
              }}
            >
              <History size={18} />
              <span>Audit History</span>
              {historyTotal > 0 && <span className="count-pill">{historyTotal}</span>}
            </button>
            <button
              className={`nav-item ${activeTab === 'cbm_calculator' ? 'selected' : ''}`}
              onClick={() => {
                setActiveTab('cbm_calculator')
                setSelectedShipmentDetail(null)
                setSelectedHistoricalAudit(null)
              }}
            >
              <Scale size={18} />
              <span>CBM Calculator</span>
            </button>

            <div className="sidebar-divider" />
            <div className="workspace-label">MASTER DATA (ERP)</div>
            <button
              className={`nav-item ${activeTab === 'products' ? 'selected' : ''}`}
              onClick={() => {
                setActiveTab('products')
                setSelectedShipmentDetail(null)
                setSelectedHistoricalAudit(null)
              }}
            >
              <Package size={18} />
              <span>Products</span>
            </button>
            <button
              className={`nav-item ${activeTab === 'suppliers' ? 'selected' : ''}`}
              onClick={() => {
                setActiveTab('suppliers')
                setSelectedShipmentDetail(null)
                setSelectedHistoricalAudit(null)
              }}
            >
              <Building2 size={18} />
              <span>Suppliers</span>
            </button>
            <button
              className={`nav-item ${activeTab === 'customers' ? 'selected' : ''}`}
              onClick={() => {
                setActiveTab('customers')
                setSelectedShipmentDetail(null)
                setSelectedHistoricalAudit(null)
              }}
            >
              <Users size={18} />
              <span>Customers &amp; CRM</span>
            </button>

            <div className="sidebar-divider" />
            <div className="workspace-label">PROCUREMENT &amp; INVENTORY</div>
            <button
              className={`nav-item ${activeTab === 'purchase_orders' ? 'selected' : ''}`}
              onClick={() => {
                setActiveTab('purchase_orders')
                setSelectedShipmentDetail(null)
                setSelectedHistoricalAudit(null)
              }}
            >
              <ShoppingCart size={18} />
              <span>Purchase Orders</span>
            </button>
            <button
              className={`nav-item ${activeTab === 'goods_receipts' ? 'selected' : ''}`}
              onClick={() => {
                setActiveTab('goods_receipts')
                setSelectedShipmentDetail(null)
                setSelectedHistoricalAudit(null)
              }}
            >
              <ClipboardCheck size={18} />
              <span>Goods Receipts</span>
            </button>
            <button
              className={`nav-item ${activeTab === 'inventory' ? 'selected' : ''}`}
              onClick={() => {
                setActiveTab('inventory')
                setSelectedShipmentDetail(null)
                setSelectedHistoricalAudit(null)
              }}
            >
              <Boxes size={18} />
              <span>Inventory Ledger</span>
            </button>
            <button
              className={`nav-item ${['warehouses', 'transfers', 'adjustments', 'reservations'].includes(activeTab) ? 'selected' : ''}`}
              onClick={() => {
                setActiveTab('warehouses')
                setSelectedShipmentDetail(null)
                setSelectedHistoricalAudit(null)
              }}
            >
              <Warehouse size={18} />
              <span>Warehouses &amp; Hubs</span>
            </button>
            <button
              className={`nav-item ${['sales_orders', 'quotations', 'picking_packing', 'dispatches', 'sales_returns'].includes(activeTab) ? 'selected' : ''}`}
              onClick={() => {
                setActiveTab('sales_orders')
                setSelectedShipmentDetail(null)
                setSelectedHistoricalAudit(null)
              }}
            >
              <ShoppingBag size={18} />
              <span>Sales &amp; Fulfilment</span>
            </button>
            <button
              className={`nav-item ${activeTab === 'invoicing' ? 'selected' : ''}`}
              onClick={() => {
                setActiveTab('invoicing')
                setSelectedShipmentDetail(null)
                setSelectedHistoricalAudit(null)
              }}
            >
              <Receipt size={18} />
              <span>Invoicing &amp; Finance</span>
            </button>
            <button
              className={`nav-item ${activeTab === 'portal' ? 'selected' : ''}`}
              onClick={() => {
                setActiveTab('portal')
                setSelectedShipmentDetail(null)
                setSelectedHistoricalAudit(null)
              }}
            >
              <Barcode size={18} />
              <span>Operational Portal</span>
            </button>
            <button
              className={`nav-item ${activeTab === 'collaboration' ? 'selected' : ''}`}
              onClick={() => {
                setActiveTab('collaboration')
                setSelectedShipmentDetail(null)
                setSelectedHistoricalAudit(null)
              }}
            >
              <Users size={18} />
              <span>Partner Portals (Collab)</span>
            </button>
          </>
        )}

        <div className="sidebar-divider" />

        <div className="workspace-label">SAVED AUDITS</div>
        <button
          className={`nav-item ${showHistory ? 'selected' : ''}`}
          onClick={() => setShowHistory(!showHistory)}
        >
          <History size={18} />
          <span>Recent Audits</span>
          {recentAnalyses.length > 0 && <span className="count-pill">{recentAnalyses.length}</span>}
        </button>

        {showHistory && (
          <div className="history-drawer">
            {recentAnalyses.length === 0 ? (
              <div className="history-empty">No audits saved yet. Run an analysis to persist it locally.</div>
            ) : (
              recentAnalyses.map((item) => (
                <div
                  key={item.id}
                  className={`history-card ${selectedHistoricalAudit?.id === item.id || result?.id === item.id ? 'active' : ''}`}
                  onClick={() => loadHistoricalAuditDetail(item.id)}
                >
                  <div className="history-card-head">
                    <span className={`status-tag status-${item.status}`}>
                      {item.status === 'ready_for_review' ? 'Ready' : 'Needs Review'}
                    </span>
                    <button
                      className="history-delete"
                      title="Delete audit"
                      onClick={(e) => deleteSavedAnalysis(e, item.id)}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                  <div className="history-title">{item.headline}</div>
                  <div className="history-meta">
                    <span>{item.filenames?.join(', ')}</span>
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        <div className="sidebar-bottom">
          <div className="privacy-card">
            <LockKeyhole size={17} />
            <div>
              <strong>Local-First & Private</strong>
              <p>
                Documents are analyzed on your machine via local open-weight models or deterministic rules. No customer
                files are sent to external cloud APIs.
              </p>
            </div>
          </div>
          <div className="sidebar-foot">
            <span className="status-dot" /> TradeSathi AI <span className="version">v0.2.0 (Milestone 2B)</span>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumb">
            TradeSathi AI <span>/</span>{' '}
            {activeWorkspace === 'export'
              ? activeTab === 'shipments'
                ? selectedShipmentDetail
                  ? `Shipments / ${selectedShipmentDetail.reference}`
                  : 'Shipment Management'
                : activeTab === 'export_ops'
                  ? 'Export Operations & Documentation'
                : activeTab === 'history'
                  ? selectedHistoricalAudit
                    ? `Audit History / ${selectedHistoricalAudit.id}`
                    : 'Audit History & Reporting'
                : activeTab === 'purchase_orders'
                  ? 'Procurement / Purchase Orders'
                : activeTab === 'goods_receipts'
                  ? 'Procurement / Goods Receipts'
                : activeTab === 'inventory'
                  ? 'Inventory / Ledger & Stock Balances'
                : ['warehouses', 'transfers', 'adjustments', 'reservations'].includes(activeTab)
                  ? 'Warehouse & Hubs / Operations'
                : ['sales_orders', 'quotations', 'picking_packing', 'dispatches', 'sales_returns'].includes(activeTab)
                  ? 'Sales & Fulfilment / Commercial Orders'
                : activeTab === 'invoicing'
                  ? 'Finance / Invoices, Payments & GST Billing'
                : activeTab === 'portal'
                  ? 'Operational Portal / Barcode & QR Station'
                : activeTab === 'collaboration'
                  ? 'Collaboration / Supplier & Customer Portals'
                : activeTab === 'products'
                  ? 'Master Data / Products Catalog'
                : activeTab === 'suppliers'
                  ? 'Master Data / Supplier Directory'
                : activeTab === 'customers'
                  ? 'Master Data / Customer CRM'
                : activeTab === 'cbm_calculator'
                  ? 'Logistics / CBM Calculator'
                : activeTab === 'dashboard'
                  ? 'Executive Dashboard & Enterprise Reports'
                : 'Document Audit'
              : 'PortSathi AI'}
          </div>
          <div className="topbar-right">
            <span className="private-badge">
              <ShieldCheck size={14} /> Local-first Sandbox
            </span>
            <span className="avatar">TS</span>
          </div>
        </header>

        {activeWorkspace === 'port' ? (
          /* PortSathi AI Phase 2 Roadmap View */
          <section className="coming-soon panel">
            <div className="coming-icon">
              <Anchor size={36} />
            </div>
            <div className="eyebrow">
              <span className="eyebrow-dot" /> PHASE 2 ROADMAP
            </div>
            <h1>PortSathi AI: Shipping & Vessel Ops</h1>
            <p>
              Vessel-call extraction, Notice of Readiness parsing, Statement of Facts (SOF) reconciliation, and
              automated port correspondence sharing the TradeSathi core engine.
            </p>

            <div className="roadmap-grid">
              <div className="roadmap-card">
                <div className="roadmap-badge">Phase 2.1</div>
                <h3>Vessel-Call Document Parsing</h3>
                <p>Extract IMO, vessel name, cargo manifest, and Notice of Readiness details.</p>
              </div>
              <div className="roadmap-card">
                <div className="roadmap-badge">Phase 2.2</div>
                <h3>ETA & Berth Tracking</h3>
                <p>Compare port agent notices against voyage instructions and calculate laytime triggers.</p>
              </div>
              <div className="roadmap-card">
                <div className="roadmap-badge">Phase 2.3</div>
                <h3>Port Operations Checklist</h3>
                <p>Generate arrival compliance checklists for customs, quarantine, and bunkering.</p>
              </div>
            </div>

            <button className="primary-button" style={{ maxWidth: 280, margin: '28px auto 0' }} onClick={() => setActiveWorkspace('export')}>
              Return to ExportMate MVP
            </button>
          </section>
        ) : activeTab === 'shipments' ? (
          /* ==========================================
             Milestone 2B: Shipment Management View
             ========================================== */
          selectedShipmentDetail ? (
            /* Shipment Detail Page */
            <div className="shipment-detail-panel">
              <button className="detail-nav-back" onClick={() => setSelectedShipmentDetail(null)}>
                <ArrowLeft size={16} /> Back to Shipments Register
              </button>

              <div className="detail-header-card">
                <div className="detail-header-info">
                  <span className={`status-tag status-${selectedShipmentDetail.status}`}>
                    {selectedShipmentDetail.status.replace(/_/g, ' ').toUpperCase()}
                  </span>
                  <h2>{selectedShipmentDetail.reference}</h2>
                  <p style={{ margin: 0, color: 'var(--slate-400)', fontSize: 13 }}>
                    Created on {new Date(selectedShipmentDetail.created_at).toLocaleString()} • Updated {new Date(selectedShipmentDetail.updated_at).toLocaleString()}
                  </p>
                </div>

                <div style={{ display: 'flex', gap: 10 }}>
                  <button className="btn-sm btn-secondary" onClick={() => openEditShipmentModal(selectedShipmentDetail)}>
                    <Pencil size={14} /> Edit Metadata
                  </button>
                  <button className="btn-sm btn-secondary" onClick={openUploadDocModal}>
                    <UploadCloud size={14} /> Upload Documents
                  </button>
                  <button
                    className="btn-sm btn-primary-sm"
                    onClick={handleReconcileDirectly}
                    disabled={reconcilingDirectly || shipmentDocuments.length === 0}
                  >
                    {reconcilingDirectly ? (
                      <>
                        <LoaderCircle size={14} className="spin" /> Reconciling...
                      </>
                    ) : (
                      <>
                        <FileCheck2 size={14} /> Reconcile Attached Docs
                      </>
                    )}
                  </button>
                  <button className="btn-sm btn-secondary" onClick={() => launchReconciliationForShipment(selectedShipmentDetail)}>
                    <FileCheck2 size={14} /> Reconcile in Engine
                  </button>
                  <button
                    className="btn-sm btn-secondary"
                    onClick={() => handleDeleteShipment(selectedShipmentDetail.id, selectedShipmentDetail.reference)}
                    style={{ color: 'var(--rose-400)' }}
                    title="Delete shipment record while preserving audit compliance history"
                  >
                    <Trash2 size={14} /> Delete
                  </button>
                </div>
              </div>

              {/* Milestone 2C: Readiness Dashboard */}
              <div className={`readiness-dashboard-card status-${shipmentReadiness?.status || 'not_ready'}`}>
                <div className="readiness-header-row">
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                      <span className={`readiness-status-badge badge-${shipmentReadiness?.status || 'not_ready'}`}>
                        {shipmentReadiness?.is_ready ? (
                          shipmentReadiness.status === 'ready_with_warnings' ? (
                            <>
                              <AlertTriangle size={15} /> Ready with Warnings
                            </>
                          ) : (
                            <>
                              <CheckCircle2 size={15} /> Ready for Dispatch Review
                            </>
                          )
                        ) : (
                          <>
                            <CircleAlert size={15} /> Not Ready — Action Required
                          </>
                        )}
                      </span>
                      <span style={{ fontSize: 13, color: 'var(--slate-400)' }}>
                        Shipment Reference: <strong>{selectedShipmentDetail.reference}</strong>
                      </span>
                    </div>
                    <h3 style={{ margin: 0, fontSize: 18, color: '#fff' }}>
                      Export Operational Readiness Assessment
                    </h3>
                  </div>

                  <button
                    className="btn-sm btn-primary-sm"
                    onClick={handleReconcileDirectly}
                    disabled={reconcilingDirectly || shipmentDocuments.length === 0}
                  >
                    {reconcilingDirectly ? (
                      <>
                        <LoaderCircle size={14} className="spin" /> Recalculating...
                      </>
                    ) : (
                      <>
                        <RefreshCw size={14} /> Recompute Readiness
                      </>
                    )}
                  </button>
                </div>

                {/* Explicit Legal Disclaimer */}
                <div className="readiness-disclaimer-alert">
                  <ShieldCheck size={18} style={{ flexShrink: 0, color: 'var(--teal-400)' }} />
                  <div>
                    <strong>Operational Dispatch Rule: </strong>
                    {shipmentReadiness?.disclaimer ||
                      'Proposed checklist defaults and operational readiness rules for local verification. This assessment does NOT constitute customs compliance, statutory export clearance, or legal certification.'}
                  </div>
                </div>

                {/* KPI Metrics Grid */}
                <div className="readiness-kpi-grid">
                  <div className="readiness-kpi-box">
                    <span className="kpi-label">Uploaded Documents</span>
                    <span className="kpi-value">
                      {shipmentReadiness?.uploaded_document_count ?? shipmentDocuments.length}
                    </span>
                  </div>
                  <div
                    className={`readiness-kpi-box ${
                      (shipmentReadiness?.missing_documents?.length || 0) > 0 ? 'kpi-alert' : 'kpi-success'
                    }`}
                  >
                    <span className="kpi-label">Missing Required</span>
                    <span className="kpi-value">
                      {shipmentReadiness?.missing_documents?.length ?? 0}
                    </span>
                  </div>
                  <div
                    className={`readiness-kpi-box ${
                      (shipmentReadiness?.unresolved_critical_discrepancies || 0) > 0 ? 'kpi-alert' : 'kpi-success'
                    }`}
                  >
                    <span className="kpi-label">Critical Discrepancies</span>
                    <span className="kpi-value">
                      {shipmentReadiness?.unresolved_critical_discrepancies ?? 0}
                    </span>
                  </div>
                  <div
                    className={`readiness-kpi-box ${
                      (shipmentReadiness?.outstanding_human_reviews || 0) > 0 ? 'kpi-warning' : 'kpi-success'
                    }`}
                  >
                    <span className="kpi-label">Outstanding Reviews</span>
                    <span className="kpi-value">
                      {shipmentReadiness?.outstanding_human_reviews ?? 0}
                    </span>
                  </div>
                  <div className="readiness-kpi-box">
                    <span className="kpi-label">Planned Date</span>
                    <span className="kpi-value" style={{ fontSize: 14 }}>
                      {selectedShipmentDetail.planned_shipment_date || 'Unspecified'}
                    </span>
                  </div>
                  <div className="readiness-kpi-box">
                    <span className="kpi-label">Last Audit</span>
                    <span className="kpi-value" style={{ fontSize: 13 }}>
                      {shipmentReadiness?.last_reconciliation_timestamp
                        ? new Date(shipmentReadiness.last_reconciliation_timestamp).toLocaleDateString()
                        : 'Pending Audit'}
                    </span>
                  </div>
                </div>

                {/* Explainable Decision Reasons */}
                {shipmentReadiness?.reasons && shipmentReadiness.reasons.length > 0 && (
                  <div className="readiness-reasons-box">
                    <div className="readiness-reasons-title">
                      <Sparkles size={14} /> Explainable Readiness Rules Breakdown
                    </div>
                    <div className="readiness-reasons-list">
                      {shipmentReadiness.reasons.map((reason, idx) => (
                        <div key={idx} className="readiness-reason-item">
                          {shipmentReadiness.is_ready ? (
                            <CheckCircle2 size={15} style={{ color: '#34d399', flexShrink: 0, marginTop: 2 }} />
                          ) : (
                            <CircleAlert size={15} style={{ color: '#fb7185', flexShrink: 0, marginTop: 2 }} />
                          )}
                          <span>{reason}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Required Document Checklist Cards */}
                <div style={{ marginTop: 16 }}>
                  <h4 style={{ margin: '0 0 12px 0', fontSize: 13, color: 'var(--slate-300)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                    Required Document Checklist (Proposed Defaults)
                  </h4>
                  <div className="readiness-checklist-grid">
                    {shipmentReadiness?.checklist?.map((chk) => (
                      <div key={chk.id} className="checklist-card">
                        <div className="checklist-card-top">
                          <span className="checklist-title">{chk.title}</span>
                          <span className={`checklist-status-tag chk-${chk.status}`}>
                            {chk.status.replace(/_/g, ' ')}
                          </span>
                        </div>
                        <p className="checklist-detail" style={{ margin: 0 }}>
                          {chk.detail}
                        </p>
                        {chk.attached_document_id && (
                          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 4 }}>
                            {chk.status !== 'verified_by_user' && (
                              <button
                                className="btn-sm btn-secondary"
                                style={{ padding: '3px 8px', fontSize: 11 }}
                                onClick={() => handleQuickReviewChange(chk.attached_document_id, 'verified_by_user')}
                              >
                                <Check size={12} /> Mark Verified
                              </button>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Metadata Fields Grid */}
              <div className="detail-fields-grid">
                <div className="detail-field-box">
                  <label>Exporter / Shipper</label>
                  <span>{selectedShipmentDetail.exporter || <span className="empty-val">Not specified</span>}</span>
                </div>
                <div className="detail-field-box">
                  <label>Buyer / Consignee</label>
                  <span>{selectedShipmentDetail.buyer || <span className="empty-val">Not specified</span>}</span>
                </div>
                <div className="detail-field-box">
                  <label>Product Cargo Description</label>
                  <span>{selectedShipmentDetail.product_description || <span className="empty-val">Not specified</span>}</span>
                </div>
                <div className="detail-field-box">
                  <label>Destination Country & Port</label>
                  <span>
                    {selectedShipmentDetail.destination_port
                      ? `${selectedShipmentDetail.destination_port}${selectedShipmentDetail.destination_country ? ', ' + selectedShipmentDetail.destination_country : ''}`
                      : selectedShipmentDetail.destination_country || <span className="empty-val">Not specified</span>}
                  </span>
                </div>
                <div className="detail-field-box">
                  <label>Planned Shipment Date</label>
                  <span>{selectedShipmentDetail.planned_shipment_date || <span className="empty-val">Not specified</span>}</span>
                </div>
                <div className="detail-field-box">
                  <label>Incoterm & Named Place</label>
                  <span>
                    {selectedShipmentDetail.incoterm
                      ? `${selectedShipmentDetail.incoterm}${selectedShipmentDetail.named_place ? ' (' + selectedShipmentDetail.named_place + ')' : ''}`
                      : <span className="empty-val">Not specified</span>}
                  </span>
                </div>
                <div className="detail-field-box" style={{ gridColumn: '1 / -1' }}>
                  <label>Operational Shipment Notes</label>
                  <span>{selectedShipmentDetail.notes || <span className="empty-val">No notes recorded for this shipment.</span>}</span>
                </div>
              </div>

              {/* Milestone 2C: Document Register Panel */}
              <div className="document-register-panel">
                <div className="document-register-header">
                  <div>
                    <h3 style={{ margin: 0, fontSize: 18, color: '#fff' }}>
                      Shipment Document Register ({shipmentDocuments.length})
                    </h3>
                    <p style={{ margin: '4px 0 0', color: 'var(--slate-400)', fontSize: 13 }}>
                      Persistent local-first file records. Validate file formats, track human review workflows, and inspect audit trails.
                    </p>
                  </div>
                  <div style={{ display: 'flex', gap: 10 }}>
                    <button className="btn-sm btn-secondary" onClick={openUploadDocModal}>
                      <Plus size={14} /> Upload Document
                    </button>
                    <button
                      className="btn-sm btn-primary-sm"
                      onClick={handleReconcileDirectly}
                      disabled={reconcilingDirectly || shipmentDocuments.length === 0}
                    >
                      {reconcilingDirectly ? (
                        <>
                          <LoaderCircle size={14} className="spin" /> Reconciling...
                        </>
                      ) : (
                        <>
                          <FileCheck2 size={14} /> Reconcile Attached
                        </>
                      )}
                    </button>
                  </div>
                </div>

                {shipmentDocuments.length === 0 ? (
                  <div className="history-empty" style={{ padding: '36px 20px' }}>
                    No documents attached to this shipment yet. Click <strong>"Upload Document"</strong> to add Commercial Invoices, Packing Lists, or other trade records.
                  </div>
                ) : (
                  <div className="doc-table-container">
                    <table className="doc-table">
                      <thead>
                        <tr>
                          <th>Document Name</th>
                          <th>Doc Type</th>
                          <th>Uploaded</th>
                          <th>File Size</th>
                          <th>Review Status</th>
                          <th>Human Audit Trail</th>
                          <th style={{ textAlign: 'right' }}>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {shipmentDocuments.map((doc) => (
                          <tr key={doc.id}>
                            <td>
                              <div className="doc-name-cell">
                                <FileText size={16} style={{ color: 'var(--teal-400)', flexShrink: 0 }} />
                                <div>
                                  <div>{doc.original_filename}</div>
                                  <div className="doc-meta-sub">{doc.storage_key}</div>
                                </div>
                              </div>
                            </td>
                            <td>
                              <span className="doc-type-badge">
                                {doc.document_type ? doc.document_type.replace(/_/g, ' ') : 'unknown'}
                              </span>
                            </td>
                            <td>
                              <span style={{ fontSize: 12 }}>
                                {new Date(doc.uploaded_at).toLocaleDateString()}
                              </span>
                            </td>
                            <td>
                              <span style={{ fontSize: 12, fontFamily: 'JetBrains Mono, monospace' }}>
                                {(doc.file_size / 1024).toFixed(1)} KB
                              </span>
                            </td>
                            <td>
                              <span
                                className={`checklist-status-tag chk-${doc.review_status} status-badge-interactive`}
                                onClick={() => openReviewDocModal(doc)}
                                title="Click to update review status"
                              >
                                {doc.review_status.replace(/_/g, ' ')} <Pencil size={11} />
                              </span>
                            </td>
                            <td>
                              {doc.last_reviewed_at ? (
                                <div>
                                  <span style={{ fontSize: 11, color: 'var(--slate-300)' }}>
                                    {doc.last_reviewed_by || 'User'} • {new Date(doc.last_reviewed_at).toLocaleDateString()}
                                  </span>
                                  {doc.review_notes && (
                                    <div className="doc-audit-note">"{doc.review_notes}"</div>
                                  )}
                                </div>
                              ) : (
                                <span style={{ fontSize: 11, color: 'var(--slate-400)' }}>
                                  Pending verification
                                </span>
                              )}
                            </td>
                            <td style={{ textAlign: 'right' }}>
                              <div style={{ display: 'inline-flex', gap: 6 }}>
                                {doc.review_status !== 'verified_by_user' && (
                                  <button
                                    className="btn-sm btn-secondary"
                                    style={{ padding: '4px 8px' }}
                                    title="Verify Document"
                                    onClick={() => handleQuickReviewChange(doc.id, 'verified_by_user')}
                                  >
                                    <Check size={13} style={{ color: '#34d399' }} />
                                  </button>
                                )}
                                <button
                                  className="btn-sm btn-secondary"
                                  style={{ padding: '4px 8px' }}
                                  title="Review Decision & Notes"
                                  onClick={() => openReviewDocModal(doc)}
                                >
                                  <ClipboardCheck size={13} />
                                </button>
                                <a
                                  href={`${API_BASE}/api/shipments/${selectedShipmentDetail.id}/documents/${doc.id}/download`}
                                  className="btn-sm btn-secondary"
                                  style={{ padding: '4px 8px', display: 'inline-flex', alignItems: 'center' }}
                                  title="Download File"
                                  download
                                >
                                  <ArrowDownToLine size={13} />
                                </a>
                                <button
                                  className="btn-sm btn-secondary"
                                  style={{ padding: '4px 8px', color: '#fb7185' }}
                                  title="Delete Document"
                                  onClick={() => handleDeleteShipmentDoc(doc.id)}
                                >
                                  <Trash2 size={13} />
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* Cargo Volume & Weight Planning Section */}
              <div className="document-register-panel" style={{ marginTop: 24 }}>
                <div className="document-register-header">
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <h3 style={{ margin: 0, fontSize: 18, color: '#fff' }}>
                        Cargo Measurements &amp; Volume Planning
                      </h3>
                      {shipmentCargoMeasurements?.has_cargo_measurements && (
                        <span className="count-pill">
                          {shipmentCargoMeasurements.total_cbm?.toFixed(3)} CBM
                        </span>
                      )}
                    </div>
                    <p style={{ margin: '4px 0 0', color: 'var(--slate-400)', fontSize: 13 }}>
                      Physical carton volume, gross weight, volumetric calculations, and export document discrepancy verification.
                    </p>
                  </div>
                  <button
                    className="btn-sm btn-primary-sm"
                    onClick={() => {
                      setActiveTab('cbm_calculator')
                      setSelectedShipmentDetail(null)
                    }}
                  >
                    <Scale size={14} /> Open in CBM Calculator
                  </button>
                </div>

                {shipmentCargoMeasurements?.discrepancy_alert && (
                  <div
                    className="cbm-disclaimer-banner"
                    style={{
                      margin: '14px 0',
                      background: 'rgba(244, 63, 94, 0.12)',
                      borderColor: 'rgba(244, 63, 94, 0.35)',
                      color: '#fca5a5',
                    }}
                  >
                    <AlertTriangle size={18} style={{ color: '#fb7185' }} />
                    <div>
                      <strong>Material Discrepancy Detected: </strong>
                      {shipmentCargoMeasurements.discrepancy_alert}
                    </div>
                  </div>
                )}

                {!shipmentCargoMeasurements?.has_cargo_measurements ? (
                  <div className="history-empty" style={{ padding: '32px 20px' }}>
                    No cargo measurements linked to this shipment yet. Click <strong>"Open in CBM Calculator"</strong> to enter package dimensions, calculate CBM, and assign measurements to shipment <strong>{selectedShipmentDetail.reference}</strong>.
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                    <div className="cbm-kpi-grid">
                      <div className="kpi-card highlight">
                        <div className="kpi-label">TOTAL VOLUME</div>
                        <div className="kpi-value">{shipmentCargoMeasurements.total_cbm?.toFixed(3)} <small>CBM</small></div>
                        <div className="kpi-sub">{(shipmentCargoMeasurements.total_cbm * 35.3146667).toFixed(1)} CuFt</div>
                      </div>
                      <div className="kpi-card">
                        <div className="kpi-label">TOTAL GROSS WEIGHT</div>
                        <div className="kpi-value">{shipmentCargoMeasurements.total_gross_weight_kg?.toFixed(1)} <small>kg</small></div>
                        <div className="kpi-sub">{(shipmentCargoMeasurements.total_gross_weight_kg * 2.2046226218).toFixed(1)} lbs</div>
                      </div>
                      <div className="kpi-card highlight-accent">
                        <div className="kpi-label">CHARGEABLE WEIGHT</div>
                        <div className="kpi-value">{shipmentCargoMeasurements.chargeable_weight_kg?.toFixed(1)} <small>kg</small></div>
                        <div className="kpi-sub">Mode: {(shipmentCargoMeasurements.freight_mode || 'general').toUpperCase()}</div>
                      </div>
                      <div className="kpi-card">
                        <div className="kpi-label">TOTAL PACKAGES</div>
                        <div className="kpi-value">{shipmentCargoMeasurements.total_packages} <small>pkgs</small></div>
                        <div className="kpi-sub">{shipmentCargoMeasurements.calculations?.length || 1} plan draft(s)</div>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* Linked Audits History */}
              <div className="linked-audits-section">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h3 style={{ margin: 0, fontSize: 18, color: '#fff' }}>
                    Linked Reconciliation Audits ({shipmentAnalyses.length})
                  </h3>
                  <button className="btn-sm btn-secondary" onClick={() => launchReconciliationForShipment(selectedShipmentDetail)}>
                    <Plus size={14} /> Run New Audit
                  </button>
                </div>

                {shipmentAnalyses.length === 0 ? (
                  <div className="history-empty" style={{ padding: '36px 20px' }}>
                    No document reconciliation audits linked to this shipment yet. Click <strong>"Reconcile Documents"</strong> to audit invoices and packing lists.
                  </div>
                ) : (
                  shipmentAnalyses.map((anl) => (
                    <div key={anl.id} className="linked-audit-item">
                      <div className="linked-audit-info">
                        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                          <span className={`status-tag status-${anl.status}`}>
                            {anl.status.replace(/_/g, ' ').toUpperCase()}
                          </span>
                          <span className="linked-audit-title">{anl.headline}</span>
                        </div>
                        <div className="linked-audit-sub">
                          <span>Audit ID: {anl.id}</span>
                          <span>•</span>
                          <span>Documents: {anl.filenames?.join(', ')}</span>
                          <span>•</span>
                          <span>Discrepancies: {anl.discrepancy_count}</span>
                          <span>•</span>
                          <span>{new Date(anl.created_at).toLocaleString()}</span>
                        </div>
                      </div>
                      <button className="btn-sm btn-secondary" onClick={() => loadSavedAnalysis(anl.id)}>
                        <Eye size={13} /> View Audit
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>
          ) : (
            /* Shipment Register List View */
            <div className="shipments-workspace">
              <section className="page-heading">
                <div>
                  <div className="eyebrow">
                    <span className="eyebrow-dot" /> PERSISTENT SHIPMENT REGISTER
                  </div>
                  <h1>
                    Shipments &amp; Consignments.
                    <br />
                    <span>Track Commercial Audits.</span>
                  </h1>
                  <p className="heading-copy">
                    Manage persistent shipment records, link multi-document reconciliation audits, and track
                    cross-verification history in one local-first workspace.
                  </p>
                </div>

                <div style={{ display: 'flex', alignItems: 'flex-start' }}>
                  <button className="primary-button" onClick={openCreateShipmentModal} style={{ padding: '12px 20px' }}>
                    <Plus size={18} /> New Shipment Record
                  </button>
                </div>
              </section>

              {/* Controls bar: search and filter */}
              <div className="shipments-controls">
                <div className="search-box">
                  <Search size={16} />
                  <input
                    type="text"
                    placeholder="Search by reference, exporter, buyer, port..."
                    value={shipmentSearch}
                    onChange={(e) => setShipmentSearch(e.target.value)}
                  />
                </div>
                <select
                  className="filter-select"
                  value={shipmentStatusFilter}
                  onChange={(e) => setShipmentStatusFilter(e.target.value)}
                >
                  <option value="">All Review Statuses</option>
                  <option value="draft">Draft (Pending Audit)</option>
                  <option value="ready_for_review">Ready for Review</option>
                  <option value="needs_attention">Needs Attention</option>
                  <option value="missing_information">Missing Information</option>
                </select>
              </div>

              {/* Shipments Cards Grid */}
              {shipments.length === 0 ? (
                <div className="history-empty" style={{ padding: '48px 24px' }}>
                  No shipments found. Click <strong>"+ New Shipment Record"</strong> above to register your first shipment.
                </div>
              ) : (
                <div className="shipments-grid">
                  {shipments.map((s) => (
                    <div key={s.id} className="shipment-card">
                      <div className="shipment-card-head">
                        <div>
                          <div className="shipment-ref">{s.reference}</div>
                          <span style={{ fontSize: 11, color: 'var(--slate-400)' }}>
                            {new Date(s.created_at).toLocaleDateString()}
                          </span>
                        </div>
                        <span className={`status-tag status-${s.status}`}>
                          {s.status.replace(/_/g, ' ')}
                        </span>
                      </div>

                      <div className="shipment-meta-rows">
                        <div className="shipment-meta-row">
                          <Building2 size={14} />
                          <span>
                            <strong>Exporter:</strong> {s.exporter || 'Unspecified'}
                          </span>
                        </div>
                        <div className="shipment-meta-row">
                          <Building2 size={14} />
                          <span>
                            <strong>Buyer:</strong> {s.buyer || 'Unspecified'}
                          </span>
                        </div>
                        {s.destination_port && (
                          <div className="shipment-meta-row">
                            <MapPin size={14} />
                            <span>
                              <strong>Port:</strong> {s.destination_port} {s.destination_country ? `(${s.destination_country})` : ''}
                            </span>
                          </div>
                        )}
                        {s.incoterm && (
                          <div className="shipment-meta-row">
                            <Package size={14} />
                            <span>
                              <strong>Incoterm:</strong> {s.incoterm} {s.named_place ? `at ${s.named_place}` : ''}
                            </span>
                          </div>
                        )}
                      </div>

                      <div className="shipment-card-footer">
                        <span>{s.analysis_count} linked audit{s.analysis_count === 1 ? '' : 's'}</span>
                        <div className="shipment-card-actions">
                          <button className="btn-sm btn-secondary" onClick={() => viewShipmentDetail(s)}>
                            <Eye size={13} /> View
                          </button>
                          <button className="btn-sm btn-primary-sm" onClick={() => launchReconciliationForShipment(s)}>
                            <FileCheck2 size={13} /> Audit
                          </button>
                          <button
                            className="btn-sm btn-secondary"
                            onClick={() => handleDeleteShipment(s.id, s.reference)}
                            style={{ padding: '6px 8px', color: 'var(--rose-400)' }}
                            title="Delete shipment record"
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        ) : activeTab === 'cbm_calculator' ? (
          /* ==========================================
             CBM & Cargo Volume / Weight Calculator
             ========================================== */
          <CbmCalculator
            shipments={shipments}
            onSelectShipment={(shp) => {
              setSelectedShipmentDetail(shp)
              setActiveTab('shipments')
              fetchShipmentAnalyses(shp.id)
              fetchShipmentDocuments(shp.id)
              fetchShipmentReadiness(shp.id)
              fetchShipmentCargoMeasurements(shp.id)
            }}
          />
        ) : activeTab === 'history' ? (
          /* ==========================================
             Milestone 2D: Audit History & Reporting
             ========================================== */
          selectedHistoricalAudit ? (
            /* Historical Audit Detail View */
            <div className="history-detail-panel">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
                <button
                  className="detail-nav-back"
                  onClick={() => setSelectedHistoricalAudit(null)}
                >
                  <ArrowLeft size={16} /> Back to Audit History Register
                </button>

                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  {selectedHistoricalAudit.shipment_id ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span className="scope-chip linked">
                        <Package size={13} /> Linked Shipment: {selectedHistoricalAudit.shipment_reference || selectedHistoricalAudit.shipment_id}
                      </span>
                      <button
                        className="btn-sm btn-secondary"
                        onClick={() => {
                          const found = shipments.find((s) => s.id === selectedHistoricalAudit.shipment_id)
                          if (found) {
                            setActiveTab('shipments')
                            viewShipmentDetail(found)
                          }
                        }}
                      >
                        View Shipment Record
                      </button>
                    </div>
                  ) : (
                    <span className="scope-chip standalone">
                      <Minus size={13} /> Standalone Audit (Not Linked)
                    </span>
                  )}
                  {selectedHistoricalAudit.created_at && (
                    <span style={{ fontSize: 12, color: 'var(--slate-400)' }}>
                      <Calendar size={13} style={{ display: 'inline', marginRight: 4, verticalAlign: 'middle' }} />
                      {new Date(selectedHistoricalAudit.created_at).toLocaleString()}
                    </span>
                  )}
                </div>
              </div>

              {selectedHistoricalAudit.malformed ? (
                /* Recoverable error when historical payload is missing or malformed */
                <div className="panel error-banner" style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--rose-400)', fontWeight: 700, fontSize: 16 }}>
                    <CircleAlert size={24} />
                    <span>Historical Audit Payload Corrupted or Malformed</span>
                  </div>
                  <p style={{ color: 'var(--slate-300)', fontSize: 14 }}>
                    {selectedHistoricalAudit.error || 'The saved JSON payload for this historical audit cannot be parsed.'}
                  </p>
                  <p style={{ color: 'var(--slate-400)', fontSize: 13 }}>
                    To preserve data integrity, TradeSathi AI does not silently substitute or re-run a new analysis.
                    You can inspect or delete this record from the register.
                  </p>
                  <div>
                    <button className="primary-button" style={{ maxWidth: 200 }} onClick={() => setSelectedHistoricalAudit(null)}>
                      <ArrowLeft size={15} /> Back to Register
                    </button>
                  </div>
                </div>
              ) : (
                /* Full Historical Audit View */
                <div className="result-panel panel" style={{ marginTop: 0 }}>
                  {/* Historical Preservation Notice Banner */}
                  <div className="historical-notice-banner">
                    <Clock size={18} color="#38bdf8" />
                    <div>
                      <strong>IMMUTABLE SAVED RESULT:</strong> Reopened historical analysis from{' '}
                      {new Date(selectedHistoricalAudit.created_at).toLocaleString()}.
                      Original extraction is preserved without re-running parsers to prevent model drift or parser divergence.
                    </div>
                  </div>

                  {/* Top Result Banner */}
                  <div className={`result-banner status-${selectedHistoricalAudit.summary?.status || selectedHistoricalAudit.status}`}>
                    <div className="banner-left">
                      <div className="banner-icon">
                        {(selectedHistoricalAudit.summary?.status || selectedHistoricalAudit.status) === 'ready_for_review' ? (
                          <CheckCircle2 size={24} />
                        ) : (
                          <AlertTriangle size={24} />
                        )}
                      </div>
                      <div>
                        <div className="banner-status-tag">
                          AUDIT STATUS: {((selectedHistoricalAudit.summary?.status || selectedHistoricalAudit.status) || '').replace(/_/g, ' ').toUpperCase()}
                        </div>
                        <h2>{selectedHistoricalAudit.summary?.headline || selectedHistoricalAudit.headline}</h2>
                      </div>
                    </div>

                    <div className="banner-actions">
                      <button className="action-btn" onClick={() => handleCopyHistoricalBrief(selectedHistoricalAudit)} title="Copy Brief to Clipboard">
                        <Copy size={14} />
                        <span>{historyCopiedBrief ? 'Copied!' : 'Copy Brief'}</span>
                      </button>
                      <button className="action-btn" onClick={() => handleExportHistoricalJson(selectedHistoricalAudit)} title="Export Raw JSON">
                        <ArrowDownToLine size={14} />
                        <span>JSON</span>
                      </button>
                      <button className="action-btn" onClick={() => window.print()} title="Print or Save PDF Brief">
                        <Printer size={14} />
                        <span>Print / PDF</span>
                      </button>
                      <button className="action-btn" onClick={() => reopenInAuditWorkspace(selectedHistoricalAudit)} title="Load into Document Audit workspace">
                        <RotateCcw size={14} />
                        <span>Reopen in Workspace</span>
                      </button>
                    </div>
                  </div>

                  {/* Mode & Engine Tag */}
                  <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 12 }}>
                    <span className="status-pill online" style={{ fontSize: 11 }}>
                      Engine: {selectedHistoricalAudit.mode === 'ollama' ? `Ollama (${selectedHistoricalAudit.model || 'AI'})` : 'Deterministic Rules Engine'}
                    </span>
                    <span style={{ fontSize: 12, color: 'var(--slate-400)' }}>
                      Audit ID: <code style={{ color: '#38bdf8' }}>{selectedHistoricalAudit.id}</code>
                    </span>
                  </div>

                  {/* Statutory Customs Disclaimer */}
                  <div className="disclaimer-banner" style={{ marginTop: 16 }}>
                    <Info size={16} />
                    <span>
                      <strong>OPERATIONAL READINESS ONLY:</strong> {HUMAN_REVIEW_DISCLAIMER}
                    </span>
                  </div>

                  {/* Executive Summary */}
                  <div className="audit-section">
                    <h3 className="section-title">Historical Executive Summary</h3>
                    <div className="summary-box">
                      <p>{selectedHistoricalAudit.summary?.summary_text || 'Reconciliation analysis completed successfully.'}</p>
                    </div>
                  </div>

                  {/* Operational Review Checklist */}
                  <div className="audit-section">
                    <h3 className="section-title">
                      Operational Review Checklist
                      <span>{selectedHistoricalAudit.summary?.checklist?.length || 0} checks</span>
                    </h3>
                    {(!selectedHistoricalAudit.summary?.checklist || selectedHistoricalAudit.summary?.checklist?.length === 0) ? (
                      <div className="history-empty">No checklist items recorded in this audit.</div>
                    ) : (
                      <div className="checklist-grid">
                        {selectedHistoricalAudit.summary?.checklist?.map((chk) => (
                          <div key={chk.id} className={`checklist-item status-${chk.status}`}>
                            <div className="chk-head">
                              <span className={`status-tag status-${chk.status}`}>
                                {chk.status.replace(/_/g, ' ').toUpperCase()}
                              </span>
                              <strong>{chk.title}</strong>
                            </div>
                            <p className="chk-detail">{chk.detail}</p>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Discrepancies & Recommendations */}
                  <div className="audit-section">
                    <h3 className="section-title">
                      Discrepancies &amp; Verification Actions
                      <span>{selectedHistoricalAudit.discrepancies?.length || 0} detected</span>
                    </h3>
                    {(!selectedHistoricalAudit.discrepancies || selectedHistoricalAudit.discrepancies.length === 0) ? (
                      <div className="clean-audit-card">
                        <CheckCircle2 size={24} color="var(--emerald-400)" />
                        <div>
                          <strong>Zero Discrepancies Detected</strong>
                          <p>All evaluated cross-document data points matched within configured tolerance thresholds.</p>
                        </div>
                      </div>
                    ) : (
                      <div className="discrepancy-list">
                        {selectedHistoricalAudit.discrepancies.map((disc, idx) => (
                          <div key={`${disc.field}-${idx}`} className={`discrepancy-card severity-${disc.severity}`}>
                            <div className="disc-header">
                              <span className={`severity-badge ${disc.severity}`}>
                                {disc.severity.toUpperCase()}
                              </span>
                              <strong>{disc.label || disc.field}</strong>
                              {disc.comparison_rule && (
                                <span className="disc-rule-tag" title="Deterministic comparison rule">
                                  Rule: {disc.comparison_rule.replace(/_/g, ' ')}
                                </span>
                              )}
                              {disc.human_review_required && (
                                <span className="disc-review-tag" title="Human verification required before export">
                                  Review Required
                                </span>
                              )}
                              {disc.difference && <span className="diff-pill">{disc.difference}</span>}
                            </div>
                            <p className="disc-message">{disc.message}</p>
                            {disc.reason && disc.reason !== disc.message && (
                              <p className="disc-reason" style={{ fontSize: '11.5px', color: '#94a3b8', margin: '2px 0 6px' }}>
                                <strong style={{ color: '#cbd5e1' }}>Deterministic Reason:</strong> {disc.reason}
                              </p>
                            )}
                            {renderDiscrepancyEvidence(disc)}
                            {renderDiscrepancyReviewSection(disc, selectedHistoricalAudit.id, 'historical')}
                            <div className="disc-action-box">
                              <Check size={14} />
                              <div>
                                <small>RECOMMENDED ACTION</small>
                                <strong>{disc.recommended_action}</strong>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Original Extracted Documents */}
                  <div className="audit-section">
                    <h3 className="section-title">
                      Original Extracted Documents
                      <span>{selectedHistoricalAudit.documents?.length || 0} document(s)</span>
                    </h3>
                    {selectedHistoricalAudit.documents && selectedHistoricalAudit.documents.length > 0 && (
                      <div className="doc-tabs-container">
                        <div className="doc-tabs-header">
                          {selectedHistoricalAudit.documents.map((doc, idx) => (
                            <button
                              key={`${doc.filename}-${idx}`}
                              className={`doc-tab-btn ${historyDetailDocTab === idx ? 'active' : ''}`}
                              onClick={() => setHistoryDetailDocTab(idx)}
                            >
                              <FileText size={14} />
                              <span>{doc.filename}</span>
                              <span className="doc-type-pill">{doc.document_type || 'unknown'}</span>
                            </button>
                          ))}
                        </div>

                        {selectedHistoricalAudit.documents[historyDetailDocTab] && (() => {
                          const doc = selectedHistoricalAudit.documents[historyDetailDocTab]
                          return (
                            <div className="doc-detail-card">
                              <div className="fields-grid">
                                {doc.invoice_number && (
                                  <div className="field-cell">
                                    <small>INVOICE NUMBER</small>
                                    <strong>{doc.invoice_number}</strong>
                                  </div>
                                )}
                                {doc.exporter && (
                                  <div className="field-cell">
                                    <small>EXPORTER</small>
                                    <strong>{doc.exporter}</strong>
                                  </div>
                                )}
                                {doc.buyer && (
                                  <div className="field-cell">
                                    <small>BUYER</small>
                                    <strong>{doc.buyer}</strong>
                                  </div>
                                )}
                                {doc.total_net_weight_kg !== null && doc.total_net_weight_kg !== undefined && (
                                  <div className="field-cell">
                                    <small>NET WEIGHT</small>
                                    <strong>{doc.total_net_weight_kg} kg {doc.raw_net_weight ? `(${doc.raw_net_weight})` : ''}</strong>
                                  </div>
                                )}
                                {doc.total_gross_weight_kg !== null && doc.total_gross_weight_kg !== undefined && (
                                  <div className="field-cell">
                                    <small>GROSS WEIGHT</small>
                                    <strong>{doc.total_gross_weight_kg} kg {doc.raw_gross_weight ? `(${doc.raw_gross_weight})` : ''}</strong>
                                  </div>
                                )}
                                {doc.total_amount !== null && doc.total_amount !== undefined && (
                                  <div className="field-cell">
                                    <small>TOTAL AMOUNT</small>
                                    <strong>{doc.currency || ''} {doc.total_amount?.toLocaleString()}</strong>
                                  </div>
                                )}
                                {doc.product_description && (
                                  <div className="field-cell">
                                    <small>PRODUCT</small>
                                    <strong>{doc.product_description}</strong>
                                  </div>
                                )}
                                {doc.hs_code && (
                                  <div className="field-cell">
                                    <small>HS CODE</small>
                                    <strong>{doc.hs_code}</strong>
                                  </div>
                                )}
                              </div>

                              {doc.items && doc.items.length > 0 && (
                                <div style={{ marginTop: 16 }}>
                                  <h4 style={{ fontSize: 13, color: 'var(--slate-300)', marginBottom: 8 }}>Line Items ({doc.items.length})</h4>
                                  <table className="items-table">
                                    <thead>
                                      <tr>
                                        <th>Description</th>
                                        <th>HS Code</th>
                                        <th>Qty</th>
                                        <th>Amount</th>
                                        <th>Net Wt</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {doc.items.map((item, itemIdx) => (
                                        <tr key={itemIdx}>
                                          <td>{item.description || '—'}</td>
                                          <td><code>{item.hs_code || '—'}</code></td>
                                          <td>{item.quantity ? `${item.quantity} ${item.unit || ''}` : '—'}</td>
                                          <td>{item.amount ? item.amount.toLocaleString() : '—'}</td>
                                          <td>{item.net_weight_kg ? `${item.net_weight_kg} kg` : '—'}</td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              )}
                            </div>
                          )
                        })()}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          ) : (
            /* Audit History Register / Search / Filters / Table */
            <div className="history-workspace">
              <div className="history-header">
                <div className="history-title-group">
                  <div className="eyebrow">
                    <span className="eyebrow-dot" /> COMPLIANCE &amp; RECONCILIATION ARCHIVE
                  </div>
                  <h1>Audit History &amp; Reporting</h1>
                  <p>Search, review, export, and reopen historical export reconciliation audits.</p>
                </div>

                <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                  <button
                    className="btn-sm btn-secondary"
                    onClick={() => fetchHistoryAudits()}
                    disabled={historyLoading}
                    title="Refresh Audit History"
                  >
                    <RefreshCw size={14} className={historyLoading ? 'spin' : ''} /> Refresh
                  </button>
                  <button
                    className="primary-button"
                    style={{ padding: '8px 16px', fontSize: 13 }}
                    onClick={() => {
                      resetAll()
                      setActiveTab('audit')
                    }}
                  >
                    <FileCheck2 size={15} /> New Reconciliation
                  </button>
                </div>
              </div>

              {/* Stats Overview */}
              <div className="history-stats-grid">
                <div className="history-stat-card">
                  <div className="history-stat-icon total">
                    <History size={20} />
                  </div>
                  <div className="history-stat-meta">
                    <strong>{historyTotal}</strong>
                    <span>Total Audits</span>
                  </div>
                </div>
                <div className="history-stat-card">
                  <div className="history-stat-icon attention">
                    <AlertTriangle size={20} />
                  </div>
                  <div className="history-stat-meta">
                    <strong>
                      {historyAudits.filter((a) => a.status === 'needs_attention').length}
                    </strong>
                    <span>Needs Attention</span>
                  </div>
                </div>
                <div className="history-stat-card">
                  <div className="history-stat-icon ready">
                    <CheckCircle2 size={20} />
                  </div>
                  <div className="history-stat-meta">
                    <strong>
                      {historyAudits.filter((a) => a.status === 'ready_for_review').length}
                    </strong>
                    <span>Ready For Review</span>
                  </div>
                </div>
                <div className="history-stat-card">
                  <div className="history-stat-icon linked">
                    <Package size={20} />
                  </div>
                  <div className="history-stat-meta">
                    <strong>
                      {historyAudits.filter((a) => a.is_linked).length}
                    </strong>
                    <span>Shipment-Linked</span>
                  </div>
                </div>
              </div>

              {/* Search & Filter Toolbar */}
              <div className="history-filters-panel">
                <div className="history-filters-top">
                  <div className="history-search-box">
                    <Search size={16} />
                    <input
                      type="text"
                      className="history-search-input"
                      placeholder="Search by Audit ID, Invoice #, Exporter, Buyer, or Shipment Ref..."
                      value={historySearch}
                      onChange={(e) => {
                        setHistorySearch(e.target.value)
                        setHistoryPage(1)
                      }}
                    />
                  </div>

                  <div className="history-filter-item">
                    <span className="history-filter-label">Status:</span>
                    <select
                      className="history-select"
                      value={historyStatus}
                      onChange={(e) => {
                        setHistoryStatus(e.target.value)
                        setHistoryPage(1)
                      }}
                    >
                      <option value="all">All Statuses</option>
                      <option value="needs_attention">Needs Attention</option>
                      <option value="ready_for_review">Ready for Review</option>
                      <option value="missing_information">Missing Information</option>
                      <option value="analysis_failed">Analysis Failed</option>
                    </select>
                  </div>

                  <div className="history-filter-item">
                    <span className="history-filter-label">Scope:</span>
                    <select
                      className="history-select"
                      value={historyAuditType}
                      onChange={(e) => {
                        setHistoryAuditType(e.target.value)
                        setHistoryPage(1)
                      }}
                    >
                      <option value="all">All Audits</option>
                      <option value="linked">Shipment-Linked</option>
                      <option value="standalone">Standalone Only</option>
                    </select>
                  </div>
                </div>

                <div className="history-filters-row">
                  <div className="history-filter-item">
                    <span className="history-filter-label">From:</span>
                    <input
                      type="date"
                      className="history-date-input"
                      value={historyDateFrom}
                      onChange={(e) => {
                        setHistoryDateFrom(e.target.value)
                        setHistoryPage(1)
                      }}
                    />
                  </div>

                  <div className="history-filter-item">
                    <span className="history-filter-label">To:</span>
                    <input
                      type="date"
                      className="history-date-input"
                      value={historyDateTo}
                      onChange={(e) => {
                        setHistoryDateTo(e.target.value)
                        setHistoryPage(1)
                      }}
                    />
                  </div>

                  {(historyDateFrom || historyDateTo) && (
                    <button
                      className="btn-sm btn-secondary"
                      onClick={() => {
                        setHistoryDateFrom('')
                        setHistoryDateTo('')
                        setHistoryPage(1)
                      }}
                    >
                      Clear Dates
                    </button>
                  )}

                  <div className="history-filter-item" style={{ marginLeft: 'auto' }}>
                    <span className="history-filter-label">Sort:</span>
                    <select
                      className="history-select"
                      value={historySortOrder}
                      onChange={(e) => {
                        setHistorySortOrder(e.target.value)
                        setHistoryPage(1)
                      }}
                    >
                      <option value="desc">Newest First</option>
                      <option value="asc">Oldest First</option>
                    </select>
                  </div>

                  <div className="history-filter-item">
                    <span className="history-filter-label">Per Page:</span>
                    <select
                      className="history-select"
                      value={historyPageSize}
                      onChange={(e) => {
                        setHistoryPageSize(Number(e.target.value))
                        setHistoryPage(1)
                      }}
                    >
                      <option value={10}>10</option>
                      <option value={20}>20</option>
                      <option value={50}>50</option>
                    </select>
                  </div>

                  {(historySearch || historyStatus !== 'all' || historyAuditType !== 'all' || historyDateFrom || historyDateTo) && (
                    <button
                      className="btn-sm btn-secondary"
                      onClick={() => {
                        setHistorySearch('')
                        setHistoryStatus('all')
                        setHistoryAuditType('all')
                        setHistoryDateFrom('')
                        setHistoryDateTo('')
                        setHistorySortOrder('desc')
                        setHistoryPage(1)
                      }}
                    >
                      Reset Filters
                    </button>
                  )}
                </div>
              </div>

              {/* History Error State */}
              {historyError && (
                <div className="error-banner" style={{ margin: 0 }}>
                  <CircleAlert size={18} />
                  <span>{historyError}</span>
                  <button className="btn-sm btn-secondary" onClick={() => fetchHistoryAudits()} style={{ marginLeft: 'auto' }}>
                    Retry
                  </button>
                </div>
              )}

              {/* History Loading State */}
              {historyLoading ? (
                <div className="loading-card panel">
                  <LoaderCircle size={44} className="spin loading-icon" />
                  <h3>Loading Historical Audits...</h3>
                  <p>Searching reconciliation records and business fields.</p>
                </div>
              ) : historyAudits.length === 0 ? (
                /* History Empty State */
                <div className="empty-results-card panel">
                  <History size={54} strokeWidth={1.5} className="empty-icon" />
                  <h3>No Audits Found</h3>
                  <p>
                    {historySearch || historyStatus !== 'all' || historyAuditType !== 'all' || historyDateFrom || historyDateTo
                      ? 'No historical reconciliation audits match your search and filter criteria. Try adjusting your query or resetting filters.'
                      : 'No reconciliation audits saved yet. Run an analysis in the Document Audit workspace to create historical records.'}
                  </p>
                  {(historySearch || historyStatus !== 'all' || historyAuditType !== 'all' || historyDateFrom || historyDateTo) && (
                    <button
                      className="secondary-button"
                      style={{ maxWidth: 180, margin: '14px auto 0' }}
                      onClick={() => {
                        setHistorySearch('')
                        setHistoryStatus('all')
                        setHistoryAuditType('all')
                        setHistoryDateFrom('')
                        setHistoryDateTo('')
                        setHistoryPage(1)
                      }}
                    >
                      Clear Filters
                    </button>
                  )}
                </div>
              ) : (
                /* History Table */
                <div className="history-table-card">
                  <table className="history-table">
                    <thead>
                      <tr>
                        <th>Audit ID &amp; Date</th>
                        <th>Status</th>
                        <th>Scope</th>
                        <th>Business Fields</th>
                        <th>Paperwork &amp; Deltas</th>
                        <th style={{ textAlign: 'right' }}>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {historyAudits.map((item) => (
                        <tr key={item.id}>
                          <td>
                            <span
                              className="audit-id-badge"
                              onClick={() => loadHistoricalAuditDetail(item.id)}
                              title="Click to inspect this historical audit"
                            >
                              {item.id}
                            </span>
                            <div className="audit-time-sub">
                              {new Date(item.created_at).toLocaleString()}
                            </div>
                          </td>
                          <td>
                            {item.status === 'needs_attention' ? (
                              <span className="status-badge-needs-attention">
                                <AlertTriangle size={12} /> Needs Attention
                              </span>
                            ) : item.status === 'ready_for_review' ? (
                              <span className="status-badge-ready">
                                <CheckCircle2 size={12} /> Ready
                              </span>
                            ) : (
                              <span className="status-badge-other">
                                {item.status.replace(/_/g, ' ')}
                              </span>
                            )}
                          </td>
                          <td>
                            {item.is_linked ? (
                              <span
                                className="scope-chip linked"
                                title={`Linked to shipment ${item.shipment_reference || item.shipment_id}`}
                              >
                                <Package size={12} /> {item.shipment_reference || 'Shipment'}
                              </span>
                            ) : (
                              <span className="scope-chip standalone">
                                Standalone
                              </span>
                            )}
                          </td>
                          <td>
                            <div className="biz-fields-cell">
                              {item.invoice_numbers && item.invoice_numbers.length > 0 && (
                                <div className="biz-inv-tag">
                                  Inv: {item.invoice_numbers.join(', ')}
                                </div>
                              )}
                              <div className="biz-parties">
                                {item.exporters && item.exporters.length > 0 && item.exporters[0]}
                                {item.buyers && item.buyers.length > 0 && ` → ${item.buyers[0]}`}
                                {(!item.exporters?.length && !item.buyers?.length && !item.invoice_numbers?.length) && '—'}
                              </div>
                            </div>
                          </td>
                          <td>
                            <div style={{ color: '#fff', fontWeight: 600 }}>
                              {item.discrepancy_count === 0 ? (
                                <span style={{ color: 'var(--emerald-400)' }}>0 discrepancies</span>
                              ) : (
                                <span style={{ color: 'var(--amber-400)' }}>
                                  {item.discrepancy_count} discrepancy(ies)
                                </span>
                              )}
                            </div>
                            <div style={{ fontSize: 11, color: 'var(--slate-400)', marginTop: 2 }}>
                              {item.document_count} doc(s): {item.filenames?.slice(0, 2).join(', ')}
                              {item.filenames?.length > 2 && '...'}
                            </div>
                          </td>
                          <td style={{ textAlign: 'right' }}>
                            <div className="history-actions-cell" style={{ justifyContent: 'flex-end' }}>
                              <button
                                className="btn-sm btn-primary-sm"
                                onClick={() => loadHistoricalAuditDetail(item.id)}
                                title="Reopen and review saved audit"
                              >
                                <Eye size={12} /> Reopen
                              </button>
                              <button
                                className="action-icon-btn"
                                onClick={(e) => handleQuickExportJson(e, item.id)}
                                title="Export complete JSON"
                              >
                                <ArrowDownToLine size={13} />
                              </button>
                              <button
                                className="action-icon-btn"
                                onClick={(e) => handleQuickCopyBrief(e, item.id)}
                                title="Copy trade brief"
                              >
                                <Copy size={13} />
                              </button>
                              <button
                                className="action-icon-btn delete"
                                onClick={(e) => handleDeleteHistoricalAudit(e, item.id)}
                                title="Delete historical audit record"
                              >
                                <Trash2 size={13} />
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>

                  {/* Bounded Pagination Controls */}
                  <div className="history-pagination">
                    <div>
                      Showing audits{' '}
                      <strong>{Math.min((historyPage - 1) * historyPageSize + 1, historyTotal)}</strong> to{' '}
                      <strong>{Math.min(historyPage * historyPageSize, historyTotal)}</strong> of{' '}
                      <strong>{historyTotal}</strong> total
                    </div>

                    <div className="pagination-controls">
                      <button
                        className="pagination-btn"
                        disabled={historyPage <= 1 || historyLoading}
                        onClick={() => setHistoryPage((p) => Math.max(1, p - 1))}
                      >
                        Previous
                      </button>
                      <span className="pagination-page-indicator">
                        Page {historyPage} of {historyTotalPages}
                      </span>
                      <button
                        className="pagination-btn"
                        disabled={historyPage >= historyTotalPages || historyLoading}
                        onClick={() => setHistoryPage((p) => Math.min(historyTotalPages, p + 1))}
                      >
                        Next
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )
        ) : ['sales_orders', 'quotations', 'picking_packing', 'dispatches', 'sales_returns'].includes(activeTab) ? (
          <SalesView
            initialTab={
              activeTab === 'quotations'
                ? 'quotations'
                : activeTab === 'picking_packing'
                ? 'picking'
                : activeTab === 'dispatches'
                ? 'dispatches'
                : activeTab === 'sales_returns'
                ? 'returns'
                : 'orders'
            }
          />
        ) : ['warehouses', 'transfers', 'adjustments', 'reservations'].includes(activeTab) ? (
          <WarehouseView
            initialTab={
              activeTab === 'transfers'
                ? 'transfers'
                : activeTab === 'adjustments'
                ? 'adjustments'
                : activeTab === 'reservations'
                ? 'reservations'
                : 'warehouses'
            }
          />
        ) : ['purchase_orders', 'goods_receipts', 'inventory'].includes(activeTab) ? (
          <ProcurementView
            initialTab={
              activeTab === 'purchase_orders'
                ? 'orders'
                : activeTab === 'goods_receipts'
                ? 'receipts'
                : 'inventory'
            }
          />
        ) : activeTab === 'dashboard' ? (
          <DashboardView />
        ) : activeTab === 'portal' ? (
          <PortalView />
        ) : activeTab === 'collaboration' ? (
          <CollaborationView />
        ) : activeTab === 'export_ops' ? (
          <ExportView />
        ) : activeTab === 'invoicing' ? (
          <InvoicingView />
        ) : ['products', 'suppliers', 'customers'].includes(activeTab) ? (
          <MasterDataView
            initialTab={activeTab}
            onNavigateShipment={(shp) => {
              setSelectedShipmentDetail(shp)
              setActiveTab('shipments')
            }}
          />
        ) : (
          /* ==========================================
             Document Audit Workspace (ExportMate MVP)
             ========================================== */
          <>
            <section className="page-heading">
              <div>
                <div className="eyebrow">
                  <span className="eyebrow-dot" /> EXPORT DOCUMENT RECONCILIATION ENGINE
                </div>
                <h1>
                  Reconcile Trade Paperwork.
                  <br />
                  <span>Before Containers Move.</span>
                </h1>
                <p className="heading-copy">
                  Cross-verify Commercial Invoices, Packing Lists, and Purchase Orders. Surface weight mismatches,
                  pricing discrepancies, and missing HS codes with local open-weight AI.
                </p>
              </div>

              <div className="heading-stats-card">
                <div className="stat-row">
                  <Sparkles size={16} className="stat-icon" />
                  <div>
                    <strong>Open-Weight Models</strong>
                    <span>Local Ollama + Rules Fallback</span>
                  </div>
                </div>
                <div className="stat-row">
                  <LockKeyhole size={16} className="stat-icon" />
                  <div>
                    <strong>Data Confidentiality</strong>
                    <span>Zero External Cloud Ingestion</span>
                  </div>
                </div>
                <div className="stat-row">
                  <ShieldCheck size={16} className="stat-icon" />
                  <div>
                    <strong>Audit-Ready Reconciliation</strong>
                    <span>Deterministic Delta Checks</span>
                  </div>
                </div>
              </div>
            </section>

            {/* Workflow steps indicator */}
            <section className="workflow-steps">
              <div className="step active">
                <span>01</span>
                <div>
                  <strong>Upload Documents</strong>
                  <small>Invoice, Packing List, PO</small>
                </div>
              </div>
              <div className="step-connector" />
              <div className={`step ${result ? 'active' : ''}`}>
                <span>02</span>
                <div>
                  <strong>Reconcile & Extract</strong>
                  <small>Cross-document matching</small>
                </div>
              </div>
              <div className="step-connector" />
              <div className={`step ${result ? 'active' : ''}`}>
                <span>03</span>
                <div>
                  <strong>Export Audit Brief</strong>
                  <small>JSON / Print / Human sign-off</small>
                </div>
              </div>
            </section>

            {/* Main Interactive Work Grid */}
            <div className="work-grid">
              {/* Left Column: Upload and Model Configuration */}
              <div className="work-column upload-panel">
                {/* Linked Shipment Selector */}
                <div className="shipment-selector-bar">
                  <div className="shipment-selector-left">
                    <Package size={16} />
                    <span>Link to Shipment:</span>
                    <select
                      value={selectedShipmentForAudit || ''}
                      onChange={(e) => setSelectedShipmentForAudit(e.target.value || null)}
                    >
                      <option value="">None (Standalone Audit)</option>
                      {shipments.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.reference} {s.exporter ? `— ${s.exporter}` : ''}
                        </option>
                      ))}
                    </select>
                  </div>
                  {linkedShipmentObj && (
                    <button
                      className="btn-sm btn-secondary"
                      style={{ padding: '3px 8px', fontSize: 11 }}
                      onClick={() => setSelectedShipmentForAudit(null)}
                      title="Clear shipment link"
                    >
                      Clear
                    </button>
                  )}
                </div>

                <div className="panel dropzone-panel">
                  <div
                    className={`dropzone ${dragging ? 'dragover' : ''}`}
                    onDragOver={(e) => {
                      e.preventDefault()
                      setDragging(true)
                    }}
                    onDragLeave={() => setDragging(false)}
                    onDrop={(e) => {
                      e.preventDefault()
                      setDragging(false)
                      addFiles(e.dataTransfer.files)
                    }}
                  >
                    <UploadCloud size={44} className="dropzone-icon" />
                    <h3>Drop commercial paperwork here</h3>
                    <p>Supports Commercial Invoices, Packing Lists, POs (PDF, TXT, EML, DOCX)</p>
                    <label className="browse-button">
                      Select Files
                      <input
                        type="file"
                        multiple
                        accept=".pdf,.txt,.eml,.docx"
                        onChange={(e) => addFiles(e.target.files)}
                        hidden
                      />
                    </label>
                  </div>

                  <div className="sample-bar">
                    <span>Quick verification with sample files:</span>
                    <button className="sample-button" onClick={loadSampleFiles} disabled={loadingSample}>
                      {loadingSample ? 'Loading...' : 'Load Sample Invoice & Packing List'}
                    </button>
                  </div>

                  {files.length > 0 && (
                    <div className="file-list">
                      <div className="file-list-head">
                        <strong>Uploaded Documents ({files.length}/8)</strong>
                        <span>{(totalBytes / 1024).toFixed(1)} KB total</span>
                      </div>
                      {files.map((file, idx) => (
                        <div key={`${file.name}-${idx}`} className="file-chip">
                          <FileText size={16} />
                          <span className="file-name">{file.name}</span>
                          <span className="file-size">({(file.size / 1024).toFixed(1)} KB)</span>
                          <button className="file-remove" onClick={() => removeFile(idx)} title="Remove file">
                            <X size={14} />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}

                  {error && (
                    <div className="error-banner">
                      <CircleAlert size={18} />
                      <span>{error}</span>
                    </div>
                  )}
                </div>

                {/* Engine & Model Selection Card */}
                <div className="panel engine-panel">
                  <div className="engine-head">
                    <div className="engine-title">
                      <Bot size={18} />
                      <strong>Reconciliation Engine</strong>
                    </div>
                    <button
                      className="refresh-button"
                      onClick={refreshModels}
                      disabled={refreshing}
                      title="Refresh installed Ollama models"
                    >
                      <RefreshCw size={13} className={refreshing ? 'spin' : ''} />
                    </button>
                  </div>

                  <div className="engine-body">
                    <label htmlFor="model-select">Extraction & Audit Mode:</label>
                    <select
                      id="model-select"
                      value={model}
                      onChange={(e) => setModel(e.target.value)}
                      className="model-select"
                    >
                      <option value="">Rules Engine (Deterministic &amp; Fast — Default)</option>
                      {models.map((m) => (
                        <option key={m} value={m}>
                          Ollama: {m}
                        </option>
                      ))}
                    </select>

                    <div className="engine-status">
                      <span className={`status-pill ${ollamaAvailable ? 'online' : 'fallback'}`}>
                        {ollamaAvailable ? 'Ollama Connected' : 'Rules-Based Fallback Mode'}
                      </span>
                      <small>
                        {ollamaAvailable
                          ? `${models.length} model(s) discovered. Select one for LLM reasoning or keep Rules for pure speed.`
                          : 'Ollama is offline. TradeSathi will use its built-in regex & rule-based parser automatically.'}
                      </small>
                    </div>
                  </div>

                  <div className="action-buttons">
                    <button
                      className="primary-button"
                      onClick={runAnalysis}
                      disabled={loading || files.length === 0}
                    >
                      {loading ? (
                        <>
                          <LoaderCircle size={18} className="spin" />
                          <span>Reconciling Trade Documents...</span>
                        </>
                      ) : (
                        <>
                          <Sparkles size={18} />
                          <span>Reconcile Paperwork</span>
                        </>
                      )}
                    </button>
                    {(files.length > 0 || result) && (
                      <button className="secondary-button" onClick={resetAll} disabled={loading}>
                        <RotateCcw size={16} /> Reset
                      </button>
                    )}
                  </div>
                </div>
              </div>

              {/* Right Column: Reconciliation Results & Discrepancies */}
              <div className="work-column results-column">
                {!result && !loading && (
                  <div className="empty-results-card panel">
                    <FileCheck2 size={54} strokeWidth={1.5} className="empty-icon" />
                    <h3>No Analysis Run Yet</h3>
                    <p>
                      Upload commercial export paperwork on the left or click <strong>"Load Sample Invoice &amp; Packing List"</strong> to inspect discrepancies, weights, and customs checklist validations.
                    </p>
                  </div>
                )}

                {loading && (
                  <div className="loading-card panel">
                    <LoaderCircle size={48} className="spin loading-icon" />
                    <h3>Analyzing Paperwork...</h3>
                    <p>Extracting line items, weights, reference numbers, and validating cross-document parity.</p>
                  </div>
                )}

                {result && !loading && (
                  <div className="result-panel panel">
                    {/* Top Result Banner */}
                    <div className={`result-banner status-${result.summary.status}`}>
                      <div className="banner-left">
                        <div className="banner-icon">
                          {result.summary.status === 'ready_for_review' ? (
                            <CheckCircle2 size={24} />
                          ) : (
                            <AlertTriangle size={24} />
                          )}
                        </div>
                        <div>
                          <div className="banner-status-tag">
                            AUDIT STATUS: {result.summary.status.replace(/_/g, ' ').toUpperCase()}
                          </div>
                          <h2>{result.summary.headline}</h2>
                        </div>
                      </div>

                      <div className="banner-actions">
                        <button className="action-btn" onClick={copyBrief} title="Copy Brief to Clipboard">
                          <Copy size={14} />
                          <span>{copiedBrief ? 'Copied!' : 'Copy Brief'}</span>
                        </button>
                        <button className="action-btn" onClick={downloadJson} title="Export Raw JSON">
                          <ArrowDownToLine size={14} />
                          <span>JSON</span>
                        </button>
                        <button className="action-btn" onClick={printBrief} title="Print or Save PDF Brief">
                          <Printer size={14} />
                          <span>Print / PDF</span>
                        </button>
                      </div>
                    </div>

                    {/* Linked Shipment Notice Badge if linked */}
                    {result.shipment_id && (
                      <div className="shipment-selector-bar" style={{ margin: '16px 0 0' }}>
                        <div className="shipment-selector-left">
                          <Package size={15} color="var(--teal-300)" />
                          <span>Linked Shipment Record:</span>
                          <span className="linked-badge">
                            {shipments.find((s) => s.id === result.shipment_id)?.reference || result.shipment_id}
                          </span>
                        </div>
                        <button
                          className="btn-sm btn-secondary"
                          onClick={() => {
                            const found = shipments.find((s) => s.id === result.shipment_id)
                            if (found) {
                              setActiveTab('shipments')
                              viewShipmentDetail(found)
                            }
                          }}
                        >
                          View Shipment
                        </button>
                      </div>
                    )}

                    {/* Human Verification Notice */}
                    <div className="disclaimer-banner">
                      <Info size={16} />
                      <span>
                        <strong>HUMAN SIGN-OFF REQUIRED:</strong> TradeSathi AI surfaces mathematical deltas and missing
                        declarations. It does not provide customs legal clearance or regulatory certifications.
                      </span>
                    </div>

                    {/* Executive Summary */}
                    <div className="audit-section">
                      <h3 className="section-title">Audit Overview</h3>
                      <div className="summary-box">
                        <p>{result.summary.summary_text}</p>
                      </div>
                    </div>

                    {/* Operational Review Checklist */}
                    <div className="audit-section">
                      <h3 className="section-title">
                        Operational Review Checklist
                        <span>{result.summary.checklist?.length || 0} checks</span>
                      </h3>
                      <div className="checklist-grid">
                        {result.summary.checklist?.map((item) => (
                          <div key={item.id} className={`checklist-item status-${item.status}`}>
                            <div className="chk-icon">
                              {item.status === 'passed' ? (
                                <Check size={14} />
                              ) : item.status === 'failed' ? (
                                <X size={14} />
                              ) : item.status === 'not_applicable' ? (
                                <Minus size={14} />
                              ) : (
                                <AlertTriangle size={14} />
                              )}
                            </div>
                            <div className="chk-content">
                              <div className="chk-head-row">
                                <strong>{item.title}</strong>
                                <span className={`chk-status-pill status-${item.status}`}>
                                  {item.status === 'passed'
                                    ? 'Passed'
                                    : item.status === 'failed'
                                    ? 'Failed'
                                    : item.status === 'not_applicable'
                                    ? 'N/A'
                                    : 'Needs Review'}
                                </span>
                              </div>
                              <p>{item.detail}</p>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Cross-Document Discrepancies */}
                    <div className="audit-section">
                      <h3 className="section-title">
                        Reconciliation Findings & Discrepancies
                        <span className="discrepancy-counter">{result.discrepancies.length}</span>
                      </h3>

                      {result.discrepancies.length === 0 ? (
                        <div className="no-disc-box">
                          <CheckCircle2 size={18} />
                          <span>No discrepancies detected across the evaluated fields.</span>
                        </div>
                      ) : (
                        <div className="discrepancy-list">
                          {result.discrepancies.map((disc, idx) => (
                            <div key={`${disc.field}-${idx}`} className={`discrepancy-card severity-${disc.severity}`}>
                              <div className="disc-head">
                                <div className="disc-title">
                                  <span className={`severity-badge ${disc.severity}`}>
                                    {disc.severity.toUpperCase()}
                                  </span>
                                  <strong>{disc.label}</strong>
                                  {disc.comparison_rule && (
                                    <span className="disc-rule-tag" title="Deterministic comparison rule">
                                      Rule: {disc.comparison_rule.replace(/_/g, ' ')}
                                    </span>
                                  )}
                                  {disc.human_review_required && (
                                    <span className="disc-review-tag" title="Human verification required before export">
                                      Review Required
                                    </span>
                                  )}
                                </div>
                                {disc.difference && <span className="delta-tag">{disc.difference}</span>}
                              </div>

                              <p className="disc-msg">{disc.message}</p>
                              {disc.reason && disc.reason !== disc.message && (
                                <p className="disc-reason" style={{ fontSize: '11.5px', color: '#94a3b8', margin: '2px 0 6px' }}>
                                  <strong style={{ color: '#cbd5e1' }}>Deterministic Reason:</strong> {disc.reason}
                                </p>
                              )}

                              {/* Document Evidence & Traceability Grid */}
                              {renderDiscrepancyEvidence(disc)}
                              {renderDiscrepancyReviewSection(disc, result.id, 'active')}

                              {/* Action to take */}
                              {disc.recommended_action && (
                                <div className="action-box">
                                  <strong>Recommended Action:</strong>
                                  <span>{disc.recommended_action}</span>
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Extracted Document Details Tabs */}
                    <div className="audit-section">
                      <h3 className="section-title">Extracted Document Data</h3>
                      <div className="doc-tabs">
                        {result.documents.map((doc, idx) => (
                          <button
                            key={doc.id || doc.filename}
                            className={`doc-tab-btn ${selectedDocTab === idx ? 'active' : ''}`}
                            onClick={() => setSelectedDocTab(idx)}
                          >
                            <FileText size={14} />
                            <span>{doc.filename}</span>
                          </button>
                        ))}
                      </div>

                      {result.documents[selectedDocTab] && (
                        <div className="doc-detail-card">
                          <div className="doc-type-badge">
                            Document Type: <strong>{result.documents[selectedDocTab].document_type.replace('_', ' ').toUpperCase()}</strong>
                          </div>

                          <div className="fields-grid">
                            <div className="field-cell">
                              <label>
                                Invoice Number
                                {result.documents[selectedDocTab].field_evidence?.invoice_number?.validation_status && (
                                  <span className={`provenance-tag ${result.documents[selectedDocTab].field_evidence.invoice_number.validation_status}`}>
                                    {result.documents[selectedDocTab].field_evidence.invoice_number.validation_status}
                                  </span>
                                )}
                              </label>
                              <strong>{result.documents[selectedDocTab].invoice_number || '—'}</strong>
                              {result.documents[selectedDocTab].raw_invoice_number && result.documents[selectedDocTab].raw_invoice_number !== result.documents[selectedDocTab].invoice_number && (
                                <div className="field-provenance-meta">
                                  <span>Raw: <span className="field-raw-val">{result.documents[selectedDocTab].raw_invoice_number}</span></span>
                                </div>
                              )}
                            </div>

                            <div className="field-cell">
                              <label>
                                Invoice Date
                                {result.documents[selectedDocTab].field_evidence?.invoice_date?.validation_status && (
                                  <span className={`provenance-tag ${result.documents[selectedDocTab].field_evidence.invoice_date.validation_status}`}>
                                    {result.documents[selectedDocTab].field_evidence.invoice_date.validation_status}
                                  </span>
                                )}
                              </label>
                              <strong>{result.documents[selectedDocTab].invoice_date || '—'}</strong>
                              {result.documents[selectedDocTab].raw_invoice_date && result.documents[selectedDocTab].raw_invoice_date !== result.documents[selectedDocTab].invoice_date && (
                                <div className="field-provenance-meta">
                                  <span>Raw: <span className="field-raw-val">{result.documents[selectedDocTab].raw_invoice_date}</span></span>
                                </div>
                              )}
                              {result.documents[selectedDocTab].field_evidence?.invoice_date?.notes && (
                                <div className="field-note-alert">{result.documents[selectedDocTab].field_evidence.invoice_date.notes}</div>
                              )}
                            </div>

                            <div className="field-cell">
                              <label>PO Number</label>
                              <strong>{result.documents[selectedDocTab].purchase_order_number || '—'}</strong>
                            </div>

                            <div className="field-cell">
                              <label>
                                Total Net Weight
                                {result.documents[selectedDocTab].field_evidence?.total_net_weight_kg?.validation_status && (
                                  <span className={`provenance-tag ${result.documents[selectedDocTab].field_evidence.total_net_weight_kg.validation_status}`}>
                                    {result.documents[selectedDocTab].field_evidence.total_net_weight_kg.validation_status}
                                  </span>
                                )}
                              </label>
                              <strong>
                                {result.documents[selectedDocTab].total_net_weight_kg != null
                                  ? `${result.documents[selectedDocTab].total_net_weight_kg.toLocaleString()} kg`
                                  : '—'}
                              </strong>
                              {result.documents[selectedDocTab].raw_net_weight && (
                                <div className="field-provenance-meta">
                                  <span>Raw: <span className="field-raw-val">{result.documents[selectedDocTab].raw_net_weight}</span></span>
                                </div>
                              )}
                              {result.documents[selectedDocTab].field_evidence?.total_net_weight_kg?.notes && (
                                <div className="field-note-alert">{result.documents[selectedDocTab].field_evidence.total_net_weight_kg.notes}</div>
                              )}
                            </div>

                            <div className="field-cell">
                              <label>
                                Total Amount
                                {result.documents[selectedDocTab].field_evidence?.total_amount?.validation_status && (
                                  <span className={`provenance-tag ${result.documents[selectedDocTab].field_evidence.total_amount.validation_status}`}>
                                    {result.documents[selectedDocTab].field_evidence.total_amount.validation_status}
                                  </span>
                                )}
                              </label>
                              <strong>
                                {result.documents[selectedDocTab].total_amount != null
                                  ? `${result.documents[selectedDocTab].currency || ''} ${result.documents[selectedDocTab].total_amount.toLocaleString()}`
                                  : '—'}
                              </strong>
                              {result.documents[selectedDocTab].raw_total_amount && result.documents[selectedDocTab].raw_total_amount !== String(result.documents[selectedDocTab].total_amount) && (
                                <div className="field-provenance-meta">
                                  <span>Raw: <span className="field-raw-val">{result.documents[selectedDocTab].raw_total_amount}</span></span>
                                </div>
                              )}
                            </div>

                            <div className="field-cell">
                              <label>Exporter / Shipper</label>
                              <strong>{result.documents[selectedDocTab].exporter || '—'}</strong>
                            </div>

                            <div className="field-cell">
                              <label>Buyer</label>
                              <strong>{result.documents[selectedDocTab].buyer || '—'}</strong>
                            </div>

                            {result.documents[selectedDocTab].consignee && (
                              <div className="field-cell">
                                <label>Consignee / Notify Party</label>
                                <strong>{result.documents[selectedDocTab].consignee}</strong>
                              </div>
                            )}

                            <div className="field-cell">
                              <label>
                                HS Code
                                {result.documents[selectedDocTab].field_evidence?.hs_code?.validation_status && (
                                  <span className={`provenance-tag ${result.documents[selectedDocTab].field_evidence.hs_code.validation_status}`}>
                                    {result.documents[selectedDocTab].field_evidence.hs_code.validation_status}
                                  </span>
                                )}
                              </label>
                              <strong>{result.documents[selectedDocTab].hs_code || '—'}</strong>
                            </div>

                            <div className="field-cell">
                              <label>Incoterms</label>
                              <strong>{result.documents[selectedDocTab].incoterms || '—'}</strong>
                            </div>

                            <div className="field-cell">
                              <label>Port of Loading</label>
                              <strong>{result.documents[selectedDocTab].port_of_loading || '—'}</strong>
                            </div>

                            <div className="field-cell">
                              <label>Port of Destination</label>
                              <strong>
                                {result.documents[selectedDocTab].port_of_destination ||
                                  result.documents[selectedDocTab].port_of_discharge ||
                                  '—'}
                              </strong>
                            </div>
                          </div>

                          {/* Line Items if any */}
                          {result.documents[selectedDocTab].items?.length > 0 && (
                            <div className="line-items-section">
                              <h4>Extracted Line Items</h4>
                              <table className="line-items-table">
                                <thead>
                                  <tr>
                                    <th>Description</th>
                                    <th>HS Code</th>
                                    <th>Quantity</th>
                                    <th>Net Wt (kg)</th>
                                    <th>Amount</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {result.documents[selectedDocTab].items.map((item, i) => (
                                    <tr key={i}>
                                      <td>{item.description || '—'}</td>
                                      <td>{item.hs_code || '—'}</td>
                                      <td>{item.quantity ? `${item.quantity} ${item.unit || ''}` : '—'}</td>
                                      <td>{item.net_weight_kg != null ? item.net_weight_kg : '—'}</td>
                                      <td>{item.amount != null ? item.amount : '—'}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}

                          {/* Evidence Snippets Accordion */}
                          {(result.documents[selectedDocTab].field_evidence && Object.keys(result.documents[selectedDocTab].field_evidence).length > 0) ||
                           (result.documents[selectedDocTab].evidence && Object.keys(result.documents[selectedDocTab].evidence).length > 0) ? (
                            <div className="evidence-section">
                              <button
                                className="evidence-toggle"
                                onClick={() => toggleEvidence(result.documents[selectedDocTab].filename)}
                              >
                                <span>Source Snippets &amp; Grounding Provenance</span>
                                {expandedEvidence[result.documents[selectedDocTab].filename] ? (
                                  <ChevronUp size={16} />
                                ) : (
                                  <ChevronDown size={16} />
                                )}
                              </button>
                              {expandedEvidence[result.documents[selectedDocTab].filename] && (
                                <div className="evidence-body">
                                  {result.documents[selectedDocTab].field_evidence && Object.keys(result.documents[selectedDocTab].field_evidence).length > 0 ? (
                                    Object.entries(result.documents[selectedDocTab].field_evidence).map(([field, fe]) => (
                                      <div key={field} className="provenance-evidence-card">
                                        <div className="provenance-evidence-head">
                                          <strong>{field}</strong>
                                          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                                            <span className="provenance-method-tag">
                                              {fe.method === 'ollama_model' ? 'AI Model' : 'Rules Engine'}
                                            </span>
                                            {fe.validation_status && (
                                              <span className={`provenance-tag ${fe.validation_status}`}>
                                                {fe.validation_status}
                                              </span>
                                            )}
                                          </div>
                                        </div>
                                        {fe.notes && <div className="field-note-alert" style={{ marginBottom: 4 }}>{fe.notes}</div>}
                                        {fe.source_snippet && <pre>{fe.source_snippet}</pre>}
                                      </div>
                                    ))
                                  ) : (
                                    Object.entries(result.documents[selectedDocTab].evidence || {}).map(([field, snip]) => (
                                      <div key={field} className="evidence-item">
                                        <strong>{field}:</strong>
                                        <pre>{snip}</pre>
                                      </div>
                                    ))
                                  )}
                                </div>
                              )}
                            </div>
                          ) : null}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </main>

      {/* Create / Edit Shipment Modal */}
      {isShipmentModalOpen && (
        <div className="modal-overlay" onClick={() => setIsShipmentModalOpen(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>{editingShipment ? `Edit Shipment: ${editingShipment.reference}` : 'Create New Shipment Record'}</h3>
              <button className="modal-close-btn" onClick={() => setIsShipmentModalOpen(false)}>
                <X size={20} />
              </button>
            </div>

            {shipmentFormError && (
              <div className="error-banner" style={{ marginBottom: 16 }}>
                <CircleAlert size={16} />
                <span>{shipmentFormError}</span>
              </div>
            )}

            <form onSubmit={handleSaveShipment} className="modal-form">
              <div className="form-row">
                <div className="form-group">
                  <label>Shipment Reference *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. SHP-2026-EXP-001"
                    value={shipmentFormData.reference}
                    onChange={(e) => setShipmentFormData({ ...shipmentFormData, reference: e.target.value })}
                  />
                </div>
                <div className="form-group">
                  <label>Planned Shipment Date</label>
                  <input
                    type="date"
                    value={shipmentFormData.planned_shipment_date}
                    onChange={(e) => setShipmentFormData({ ...shipmentFormData, planned_shipment_date: e.target.value })}
                  />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>Exporter / Shipper</label>
                  <input
                    type="text"
                    placeholder="e.g. Oceanic Harvest Exporters"
                    value={shipmentFormData.exporter}
                    onChange={(e) => setShipmentFormData({ ...shipmentFormData, exporter: e.target.value })}
                  />
                </div>
                <div className="form-group">
                  <label>Buyer / Consignee</label>
                  <input
                    type="text"
                    placeholder="e.g. EuroFoods Distribution BV"
                    value={shipmentFormData.buyer}
                    onChange={(e) => setShipmentFormData({ ...shipmentFormData, buyer: e.target.value })}
                  />
                </div>
              </div>

              <div className="form-group">
                <label>Product Cargo Description</label>
                <input
                  type="text"
                  placeholder="e.g. Frozen Vannamei White Shrimp (PUD)"
                  value={shipmentFormData.product_description}
                  onChange={(e) => setShipmentFormData({ ...shipmentFormData, product_description: e.target.value })}
                />
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>Destination Country</label>
                  <input
                    type="text"
                    placeholder="e.g. Netherlands"
                    value={shipmentFormData.destination_country}
                    onChange={(e) => setShipmentFormData({ ...shipmentFormData, destination_country: e.target.value })}
                  />
                </div>
                <div className="form-group">
                  <label>Destination Port</label>
                  <input
                    type="text"
                    placeholder="e.g. Rotterdam"
                    value={shipmentFormData.destination_port}
                    onChange={(e) => setShipmentFormData({ ...shipmentFormData, destination_port: e.target.value })}
                  />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>Incoterm</label>
                  <select
                    value={shipmentFormData.incoterm}
                    onChange={(e) => setShipmentFormData({ ...shipmentFormData, incoterm: e.target.value })}
                  >
                    <option value="">Select Incoterm...</option>
                    <option value="CIF">CIF — Cost, Insurance and Freight</option>
                    <option value="FOB">FOB — Free on Board</option>
                    <option value="CFR">CFR — Cost and Freight</option>
                    <option value="EXW">EXW — Ex Works</option>
                    <option value="DDP">DDP — Delivered Duty Paid</option>
                    <option value="DAP">DAP — Delivered at Place</option>
                    <option value="FCA">FCA — Free Carrier</option>
                    <option value="CPT">CPT — Carriage Paid To</option>
                    <option value="CIP">CIP — Carriage and Insurance Paid</option>
                    <option value="DPU">DPU — Delivered at Place Unloaded</option>
                  </select>
                </div>
                <div className="form-group">
                  <label>Named Place</label>
                  <input
                    type="text"
                    placeholder="e.g. Rotterdam Port / Warehouse"
                    value={shipmentFormData.named_place}
                    onChange={(e) => setShipmentFormData({ ...shipmentFormData, named_place: e.target.value })}
                  />
                </div>
              </div>

              <div className="form-group">
                <label>Operational Shipment Notes</label>
                <textarea
                  placeholder="e.g. Letter of Credit #LC-9901; 40ft Reefer maintained at -18C"
                  value={shipmentFormData.notes}
                  onChange={(e) => setShipmentFormData({ ...shipmentFormData, notes: e.target.value })}
                />
              </div>

              <div className="modal-actions">
                <button
                  type="button"
                  className="btn-sm btn-secondary"
                  onClick={() => setIsShipmentModalOpen(false)}
                  disabled={shipmentFormLoading}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn-sm btn-primary-sm"
                  disabled={shipmentFormLoading}
                >
                  {shipmentFormLoading ? 'Saving...' : editingShipment ? 'Update Shipment' : 'Create Shipment'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Milestone 2C: Upload Document to Shipment Modal */}
      {isUploadDocModalOpen && (
        <div className="modal-backdrop" onClick={() => setIsUploadDocModalOpen(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 540 }}>
            <div className="modal-header">
              <h3>Upload Document to {selectedShipmentDetail?.reference}</h3>
              <button className="modal-close-btn" onClick={() => setIsUploadDocModalOpen(false)}>
                <X size={18} />
              </button>
            </div>

            {uploadDocError && (
              <div className="error-banner" style={{ marginBottom: 16 }}>
                <CircleAlert size={16} />
                <span>{uploadDocError}</span>
              </div>
            )}

            <form onSubmit={handleUploadShipmentDocs} className="modal-form">
              <div className="form-group">
                <label>Select Document Files (PDF, TXT, EML, DOCX)</label>
                <input
                  type="file"
                  multiple
                  onChange={(e) => setUploadDocFiles(Array.from(e.target.files || []))}
                  style={{ padding: '8px 10px', background: 'var(--navy-900)' }}
                />
                {uploadDocFiles.length > 0 && (
                  <span style={{ fontSize: 12, color: 'var(--teal-300)' }}>
                    {uploadDocFiles.length} file(s) selected ({uploadDocFiles.map((f) => f.name).join(', ')})
                  </span>
                )}
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>Document Type</label>
                  <select
                    value={uploadDocType}
                    onChange={(e) => setUploadDocType(e.target.value)}
                  >
                    <option value="">Auto-Detect from Content</option>
                    <option value="commercial_invoice">Commercial Invoice</option>
                    <option value="packing_list">Packing List</option>
                    <option value="purchase_order">Purchase Order</option>
                    <option value="shipping_instructions">Shipping Instructions</option>
                    <option value="other">Other Supplementary Document</option>
                  </select>
                </div>

                <div className="form-group">
                  <label>Duplicate Handling Strategy</label>
                  <select
                    value={uploadDocDuplicateAction}
                    onChange={(e) => setUploadDocDuplicateAction(e.target.value)}
                  >
                    <option value="reject">Reject Duplicate (Default Safety)</option>
                    <option value="replace">Replace Existing Document</option>
                  </select>
                </div>
              </div>

              <div className="form-group">
                <label>Optional Operational Notes</label>
                <textarea
                  placeholder="e.g. Original signed invoice stamped by chamber of commerce"
                  value={uploadDocNotes}
                  onChange={(e) => setUploadDocNotes(e.target.value)}
                />
              </div>

              <div className="modal-actions">
                <button
                  type="button"
                  className="btn-sm btn-secondary"
                  onClick={() => setIsUploadDocModalOpen(false)}
                  disabled={uploadDocLoading}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn-sm btn-primary-sm"
                  disabled={uploadDocLoading || uploadDocFiles.length === 0}
                >
                  {uploadDocLoading ? 'Uploading...' : 'Save Document to Register'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Milestone 2C: Document Review Decision Modal */}
      {isReviewModalOpen && reviewingDoc && (
        <div className="modal-backdrop" onClick={() => setIsReviewModalOpen(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 480 }}>
            <div className="modal-header">
              <h3>Human Review Decision: {reviewingDoc.original_filename}</h3>
              <button className="modal-close-btn" onClick={() => setIsReviewModalOpen(false)}>
                <X size={18} />
              </button>
            </div>

            {reviewError && (
              <div className="error-banner" style={{ marginBottom: 16 }}>
                <CircleAlert size={16} />
                <span>{reviewError}</span>
              </div>
            )}

            <form onSubmit={handleSaveDocReview} className="modal-form">
              <div className="form-group">
                <label>Review Decision Status</label>
                <select
                  value={reviewStatusChoice}
                  onChange={(e) => setReviewStatusChoice(e.target.value)}
                >
                  <option value="verified_by_user">Verified by User</option>
                  <option value="needs_review">Needs Review (Flag for Inspection)</option>
                  <option value="uploaded">Uploaded (Pending Verification)</option>
                  <option value="not_applicable">Not Applicable</option>
                </select>
              </div>

              <div className="form-group">
                <label>Reviewer Name / ID</label>
                <input
                  type="text"
                  placeholder="e.g. Rahul (Trade Lead)"
                  value={reviewerNameInput}
                  onChange={(e) => setReviewerNameInput(e.target.value)}
                />
              </div>

              <div className="form-group">
                <label>Reviewer Notes / Verification Rationale</label>
                <textarea
                  placeholder="e.g. Checked invoice total against LC; buyer consignee address matches master contract."
                  value={reviewNotesInput}
                  onChange={(e) => setReviewNotesInput(e.target.value)}
                />
              </div>

              <div className="modal-actions">
                <button
                  type="button"
                  className="btn-sm btn-secondary"
                  onClick={() => setIsReviewModalOpen(false)}
                  disabled={reviewLoading}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn-sm btn-primary-sm"
                  disabled={reviewLoading}
                >
                  {reviewLoading ? 'Saving...' : 'Record Review Decision'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Milestone 2E.4: Finding Review Decision & Resolution Modal */}
      {isReviewFindingModalOpen && reviewFindingTarget && (
        <div className="modal-backdrop" onClick={() => setIsReviewFindingModalOpen(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 520 }}>
            <div className="modal-header">
              <h3>
                {reviewFindingAction === 'resolved'
                  ? 'Resolve Discrepancy Finding'
                  : reviewFindingAction === 'reopened'
                  ? 'Reopen Discrepancy Finding'
                  : reviewFindingAction === 'escalated'
                  ? 'Escalate Discrepancy Finding'
                  : 'Update Finding Review'}
              </h3>
              <button className="modal-close-btn" onClick={() => setIsReviewFindingModalOpen(false)}>
                <X size={18} />
              </button>
            </div>

            <div style={{ marginBottom: 12, padding: '8px 12px', background: 'rgba(255, 255, 255, 0.03)', borderRadius: 5 }}>
              <div style={{ fontSize: 11, color: 'var(--slate-400)', textTransform: 'uppercase', fontWeight: 700 }}>Target Finding:</div>
              <strong style={{ color: '#38bdf8' }}>{reviewFindingTarget.disc.label || reviewFindingTarget.disc.field}</strong>
              <div style={{ fontSize: 11.5, color: 'var(--slate-300)', marginTop: 2 }}>{reviewFindingTarget.disc.message}</div>
            </div>

            {reviewFindingError && (
              <div className="error-banner" style={{ marginBottom: 16 }}>
                <CircleAlert size={16} />
                <span>{reviewFindingError}</span>
              </div>
            )}

            <form onSubmit={handleSaveFindingReview} className="modal-form">
              <div className="form-group">
                <label>Review Action</label>
                <select
                  value={reviewFindingAction}
                  onChange={(e) => setReviewFindingAction(e.target.value)}
                >
                  <option value="resolved">Resolved with Evidence</option>
                  <option value="in_review">In Review</option>
                  <option value="acknowledged">Acknowledged (Unresolved)</option>
                  <option value="escalated">Escalated (Unresolved)</option>
                  <option value="reopened">Reopened</option>
                </select>
              </div>

              <div className="form-group">
                <label>Reviewer Identity</label>
                <input
                  type="text"
                  placeholder="e.g. Local Operator"
                  value={reviewFindingReviewer}
                  onChange={(e) => setReviewFindingReviewer(e.target.value)}
                />
              </div>

              <div className="form-group">
                <label>
                  {reviewFindingAction === 'resolved'
                    ? 'Resolution Reason / Justification (Required)'
                    : reviewFindingAction === 'reopened'
                    ? 'Reopening Reason (Required)'
                    : 'Notes / Justification'}
                </label>
                <textarea
                  placeholder={
                    reviewFindingAction === 'resolved'
                      ? 'e.g. Verified against physical scale calibration slip #4401 signed by port agent.'
                      : 'Document details and justification...'
                  }
                  value={reviewFindingReason}
                  onChange={(e) => setReviewFindingReason(e.target.value)}
                  required={reviewFindingAction === 'resolved' || reviewFindingAction === 'reopened'}
                />
              </div>

              {reviewFindingAction === 'resolved' && (
                <>
                  <div className="form-group">
                    <label>Supporting Evidence References</label>
                    <input
                      type="text"
                      placeholder="e.g. ev-weight-inv, weighbridge_slip_#402.pdf"
                      value={reviewFindingEvidence}
                      onChange={(e) => setReviewFindingEvidence(e.target.value)}
                    />
                    <small style={{ fontSize: 10.5, color: 'var(--slate-400)' }}>
                      Reference reliable evidence IDs or uploaded document names.
                    </small>
                  </div>

                  <div className="form-row">
                    <div className="form-group">
                      <label>Corrected Value (Optional)</label>
                      <input
                        type="text"
                        placeholder="e.g. 18000"
                        value={reviewFindingCorrectedVal}
                        onChange={(e) => setReviewFindingCorrectedVal(e.target.value)}
                      />
                    </div>
                    <div className="form-group">
                      <label>Unit (e.g. kg, lbs, mt, USD)</label>
                      <input
                        type="text"
                        placeholder="e.g. kg"
                        value={reviewFindingCorrectedUnit}
                        onChange={(e) => setReviewFindingCorrectedUnit(e.target.value)}
                      />
                    </div>
                  </div>

                  <div className="form-group">
                    <label>Source Document / Authority</label>
                    <input
                      type="text"
                      placeholder="e.g. Warehouse Scale Certificate #9901"
                      value={reviewFindingSource}
                      onChange={(e) => setReviewFindingSource(e.target.value)}
                    />
                  </div>
                </>
              )}

              <div className="modal-actions">
                <button
                  type="button"
                  className="btn-sm btn-secondary"
                  onClick={() => setIsReviewFindingModalOpen(false)}
                  disabled={reviewFindingLoading}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn-sm btn-primary-sm"
                  disabled={reviewFindingLoading}
                >
                  {reviewFindingLoading ? 'Recording Decision...' : 'Save Review Decision'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
