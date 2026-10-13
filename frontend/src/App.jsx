import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  Anchor,
  ArrowDownToLine,
  ArrowLeft,
  Bot,
  Building2,
  Calendar,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CircleAlert,
  ClipboardCheck,
  Copy,
  ExternalLink,
  Eye,
  FileCheck2,
  FileText,
  History,
  Info,
  LoaderCircle,
  LockKeyhole,
  MapPin,
  Minus,
  Package,
  Pencil,
  Plus,
  Printer,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldCheck,
  Ship,
  Sparkles,
  Trash2,
  UploadCloud,
  X,
} from 'lucide-react'

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
const MAX_FILES = 8

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

  const totalBytes = useMemo(() => files.reduce((sum, file) => sum + file.size, 0), [files])

  async function refreshModels() {
    setRefreshing(true)
    try {
      const response = await fetch(`${API_BASE}/api/models`)
      const data = await response.json()
      setOllamaAvailable(Boolean(data.available))
      setModels(data.models || [])
      setModel((current) => (current && (data.models || []).includes(current) ? current : ''))
    } catch {
      setOllamaAvailable(false)
      setModels([])
    } finally {
      setRefreshing(false)
    }
  }

  async function fetchRecentAnalyses() {
    try {
      const response = await fetch(`${API_BASE}/api/analyses`)
      const data = await response.json()
      setRecentAnalyses(data.analyses || [])
    } catch {
      setRecentAnalyses([])
    }
  }

  async function fetchShipments() {
    try {
      const params = new URLSearchParams()
      if (shipmentSearch.trim()) params.append('search', shipmentSearch.trim())
      if (shipmentStatusFilter.trim()) params.append('status', shipmentStatusFilter.trim())
      const response = await fetch(`${API_BASE}/api/shipments?${params.toString()}`)
      const data = await response.json()
      setShipments(data.shipments || [])
    } catch {
      setShipments([])
    }
  }

  async function fetchShipmentAnalyses(shipmentId) {
    try {
      const response = await fetch(`${API_BASE}/api/shipments/${shipmentId}/analyses`)
      const data = await response.json()
      setShipmentAnalyses(data.analyses || [])
    } catch {
      setShipmentAnalyses([])
    }
  }

  async function fetchShipmentDocuments(shipmentId) {
    try {
      const response = await fetch(`${API_BASE}/api/shipments/${shipmentId}/documents`)
      const data = await response.json()
      setShipmentDocuments(data.documents || [])
    } catch {
      setShipmentDocuments([])
    }
  }

  async function fetchShipmentReadiness(shipmentId) {
    try {
      const response = await fetch(`${API_BASE}/api/shipments/${shipmentId}/readiness`)
      const data = await response.json()
      setShipmentReadiness(data)
    } catch {
      setShipmentReadiness(null)
    }
  }

  useEffect(() => {
    refreshModels()
    fetchRecentAnalyses()
    fetchShipments()
  }, [])

  useEffect(() => {
    fetchShipments()
  }, [shipmentSearch, shipmentStatusFilter])

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
      const response = await fetch(`${API_BASE}/api/samples`)
      if (!response.ok) throw new Error('Could not fetch sample documents.')
      const data = await response.json()
      const samples = data.samples || []
      const fileObjects = samples.map(
        (s) => new File([s.content], s.filename, { type: 'text/plain', lastModified: Date.now() })
      )
      setFiles(fileObjects)
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
      const response = await fetch(`${API_BASE}/api/analyze`, { method: 'POST', body: formData })
      const data = await response.json()
      if (!response.ok) {
        throw new Error(data.detail || 'Analysis failed. Check the API logs and try again.')
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

  async function loadSavedAnalysis(id) {
    try {
      const response = await fetch(`${API_BASE}/api/analyses/${id}`)
      if (!response.ok) throw new Error('Analysis not found')
      const data = await response.json()
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
      await fetch(`${API_BASE}/api/analyses/${id}`, { method: 'DELETE' })
      fetchRecentAnalyses()
      if (result && result.id === id) {
        setResult(null)
      }
    } catch {
      // ignore
    }
  }

  function downloadJson() {
    if (!result) return
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `tradesathi-analysis-${result.id || 'export'}.json`
    link.click()
    URL.revokeObjectURL(url)
  }

  function copyBrief() {
    const discText = result.discrepancies
      .map((d) => `• [${d.severity.toUpperCase()}] ${d.label}: ${d.message}\n  Action: ${d.recommended_action}`)
      .join('\n')

    const chkText = (result.summary?.checklist || [])
      .map((c) => `• [${c.status.toUpperCase().replace('_', ' ')}] ${c.title}: ${c.detail}`)
      .join('\n')

    const brief = `=== TRADESATHI AI SHIPMENT AUDIT BRIEF ===
ID: ${result.id}
Status: ${result.summary?.status.toUpperCase()}
Mode: ${result.mode} (${result.model || 'Deterministic Rules'})
Documents: ${result.summary?.documents_received.join(', ')}

Headline: ${result.summary?.headline}
Summary: ${result.summary?.summary_text}

OPERATIONAL REVIEW CHECKLIST:
${chkText || '• None recorded.'}

DISCREPANCIES & HUMAN VERIFICATION ACTIONS:
${discText || '• None detected across evaluated fields.'}

Note: Generated by TradeSathi AI. Human sign-off required prior to customs lodgement.`

    navigator.clipboard.writeText(brief)
    setCopiedBrief(true)
    setTimeout(() => setCopiedBrief(false), 2500)
  }

  function printBrief() {
    window.print()
  }

  function toggleEvidence(key) {
    setExpandedEvidence((prev) => ({ ...prev, [key]: !prev[key] }))
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
      const url = editingShipment
        ? `${API_BASE}/api/shipments/${editingShipment.id}`
        : `${API_BASE}/api/shipments`
      const method = editingShipment ? 'PATCH' : 'POST'

      const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(shipmentFormData),
      })
      const data = await response.json()
      if (!response.ok) {
        throw new Error(data.detail || 'Failed to save shipment.')
      }

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

  async function viewShipmentDetail(shipment) {
    setSelectedShipmentDetail(shipment)
    fetchShipmentAnalyses(shipment.id)
    fetchShipmentDocuments(shipment.id)
    fetchShipmentReadiness(shipment.id)
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

      const response = await fetch(`${API_BASE}/api/shipments/${selectedShipmentDetail.id}/documents`, {
        method: 'POST',
        body: formData,
      })
      const data = await response.json()
      if (!response.ok) {
        throw new Error(data.detail || 'Failed to upload document(s).')
      }
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
      const response = await fetch(`${API_BASE}/api/shipments/${selectedShipmentDetail.id}/documents/${docId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          review_status: newStatus,
          last_reviewed_by: 'Rahul (User)',
          review_notes: `Marked as ${newStatus.replace(/_/g, ' ')} via quick action`,
        }),
      })
      if (!response.ok) {
        const errData = await response.json()
        throw new Error(errData.detail || 'Failed to update review status.')
      }
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
      const response = await fetch(`${API_BASE}/api/shipments/${selectedShipmentDetail.id}/documents/${reviewingDoc.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          review_status: reviewStatusChoice,
          last_reviewed_by: reviewerNameInput.trim() || 'User',
          review_notes: reviewNotesInput.trim() || null,
        }),
      })
      const data = await response.json()
      if (!response.ok) {
        throw new Error(data.detail || 'Failed to update review decision.')
      }
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
      const response = await fetch(`${API_BASE}/api/shipments/${selectedShipmentDetail.id}/documents/${docId}`, {
        method: 'DELETE',
      })
      if (!response.ok) throw new Error('Failed to delete document.')
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
      const response = await fetch(`${API_BASE}/api/shipments/${selectedShipmentDetail.id}/reconcile`, {
        method: 'POST',
        body: formData,
      })
      const data = await response.json()
      if (!response.ok) {
        throw new Error(data.detail || 'Failed to execute reconciliation.')
      }
      fetchShipmentAnalyses(selectedShipmentDetail.id)
      fetchShipmentReadiness(selectedShipmentDetail.id)
      fetchShipments()
      const shpResp = await fetch(`${API_BASE}/api/shipments/${selectedShipmentDetail.id}`)
      if (shpResp.ok) {
        const shpData = await shpResp.json()
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
              className={`nav-item ${activeTab === 'audit' ? 'selected' : ''}`}
              onClick={() => {
                setActiveTab('audit')
                setSelectedShipmentDetail(null)
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
                fetchShipments()
              }}
            >
              <Package size={18} />
              <span>Shipments</span>
              {shipments.length > 0 && <span className="count-pill">{shipments.length}</span>}
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
                  className={`history-card ${result?.id === item.id ? 'active' : ''}`}
                  onClick={() => loadSavedAnalysis(item.id)}
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
                : 'ExportMate AI'
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
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
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
                                </div>
                                {disc.difference && <span className="delta-tag">{disc.difference}</span>}
                              </div>

                              <p className="disc-msg">{disc.message}</p>

                              {/* Document Values Grid */}
                              {disc.doc_values && Object.keys(disc.doc_values).length > 0 && (
                                <div className="values-grid">
                                  {Object.entries(disc.doc_values).map(([file, val]) => (
                                    <div key={file} className="value-chip">
                                      <span className="chip-file">{file}:</span>
                                      <span className="chip-val">{val || 'Not present'}</span>
                                    </div>
                                  ))}
                                </div>
                              )}

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
                              <label>Invoice Number</label>
                              <strong>{result.documents[selectedDocTab].invoice_number || '—'}</strong>
                            </div>
                            <div className="field-cell">
                              <label>PO Number</label>
                              <strong>{result.documents[selectedDocTab].purchase_order_number || '—'}</strong>
                            </div>
                            <div className="field-cell">
                              <label>Total Net Weight</label>
                              <strong>
                                {result.documents[selectedDocTab].total_net_weight_kg != null
                                  ? `${result.documents[selectedDocTab].total_net_weight_kg.toLocaleString()} kg`
                                  : '—'}
                              </strong>
                            </div>
                            <div className="field-cell">
                              <label>Total Amount</label>
                              <strong>
                                {result.documents[selectedDocTab].total_amount != null
                                  ? `${result.documents[selectedDocTab].currency || ''} ${result.documents[selectedDocTab].total_amount.toLocaleString()}`
                                  : '—'}
                              </strong>
                            </div>
                            <div className="field-cell">
                              <label>Exporter / Shipper</label>
                              <strong>{result.documents[selectedDocTab].exporter || '—'}</strong>
                            </div>
                            <div className="field-cell">
                              <label>Buyer / Consignee</label>
                              <strong>{result.documents[selectedDocTab].buyer || '—'}</strong>
                            </div>
                            <div className="field-cell">
                              <label>HS Code</label>
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
                          {result.documents[selectedDocTab].evidence &&
                            Object.keys(result.documents[selectedDocTab].evidence).length > 0 && (
                              <div className="evidence-section">
                                <button
                                  className="evidence-toggle"
                                  onClick={() => toggleEvidence(result.documents[selectedDocTab].filename)}
                                >
                                  <span>Source Snippets &amp; Text Grounding Evidence</span>
                                  {expandedEvidence[result.documents[selectedDocTab].filename] ? (
                                    <ChevronUp size={16} />
                                  ) : (
                                    <ChevronDown size={16} />
                                  )}
                                </button>
                                {expandedEvidence[result.documents[selectedDocTab].filename] && (
                                  <div className="evidence-body">
                                    {Object.entries(result.documents[selectedDocTab].evidence).map(([field, snip]) => (
                                      <div key={field} className="evidence-item">
                                        <strong>{field}:</strong>
                                        <pre>{snip}</pre>
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            )}
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
    </div>
  )
}

export default App
