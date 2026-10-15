import { useEffect, useState, useMemo } from 'react'
import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  Boxes,
  Calendar,
  CheckCircle2,
  Clock,
  Compass,
  Download,
  ExternalLink,
  Eye,
  FileCheck,
  FileCode,
  FilePlus,
  FileQuestion,
  FileText,
  Filter,
  Globe,
  Hash,
  History,
  Layers,
  Link as LinkIcon,
  Lock,
  Plus,
  RefreshCw,
  Search,
  Shield,
  ShieldAlert,
  Ship,
  Truck,
  Unlink,
  Upload,
  UserCheck,
  X,
  XCircle,
} from 'lucide-react'
import { apiFetch, API_BASE } from './api'

export default function ExportView() {
  const [currentRole, setCurrentRole] = useState('admin')
  const [operatorEmail, setOperatorEmail] = useState('admin@tradesathi.local')

  // Auth headers for backend role enforcement
  const authHeaders = useMemo(
    () => ({
      'X-User-Role': currentRole,
      'X-User-Email': operatorEmail,
      'X-User-Id': operatorEmail.split('@')[0],
    }),
    [currentRole, operatorEmail]
  )

  // Shipments state
  const [shipments, setShipments] = useState([])
  const [loading, setLoading] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [selectedShipment, setSelectedShipment] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState(null)
  const [successMessage, setSuccessMessage] = useState(null)

  // Modals state
  const [isNewShipmentModalOpen, setIsNewShipmentModalOpen] = useState(false)
  const [isLinkDispatchModalOpen, setIsLinkDispatchModalOpen] = useState(false)
  const [isGenerateDocModalOpen, setIsGenerateDocModalOpen] = useState(false)
  const [isReviewDocModalOpen, setIsReviewDocModalOpen] = useState(false)
  const [isVersionHistoryOpen, setIsVersionHistoryOpen] = useState(false)
  const [selectedDocForReview, setSelectedDocForReview] = useState(null)
  const [selectedDocVersions, setSelectedDocVersions] = useState([])

  // Available dispatches for linking
  const [availableDispatches, setAvailableDispatches] = useState([])
  const [selectedDispatchId, setSelectedDispatchId] = useState('')
  const [linkNotes, setLinkNotes] = useState('')

  // New Shipment Form State
  const [newShipmentForm, setNewShipmentForm] = useState({
    reference: '',
    consignee_name: '',
    consignee_address: '',
    exporter_name: 'TradeSathi Agro Exporters Pvt Ltd',
    exporter_address: 'Kolkata Port Terminal, West Bengal, India',
    destination_country: 'AE',
    port_of_loading: 'Kolkata Port',
    port_of_discharge: 'Jebel Ali Port',
    transport_mode: 'sea',
    vessel_name: '',
    voyage_flight_no: '',
    booking_reference: '',
    package_count: 1,
    gross_weight_kg: 0,
    net_weight_kg: 0,
    incoterm: 'FOB',
    named_place: '',
    notes: '',
  })

  // Review Form State
  const [reviewForm, setReviewForm] = useState({
    decision: 'approved',
    review_notes: '',
  })

  // Document Generation Form State
  const [genDocForm, setGenDocForm] = useState({
    template_type: 'commercial_invoice',
  })

  // Auto-dismiss banners
  useEffect(() => {
    if (successMessage) {
      const t = setTimeout(() => setSuccessMessage(null), 5000)
      return () => clearTimeout(t)
    }
  }, [successMessage])

  // Fetch shipments on mount
  useEffect(() => {
    fetchShipments()
  }, [])

  // Fetch full detail when selectedShipment changes
  useEffect(() => {
    if (selectedShipment?.id) {
      fetchShipmentDetail(selectedShipment.id)
    }
  }, [selectedShipment?.id])

  async function fetchShipments() {
    setLoading(true)
    setErrorMessage(null)
    try {
      const data = await apiFetch('/api/export/shipments', { headers: authHeaders }, 'Failed to fetch export shipments')
      setShipments(data || [])
    } catch (err) {
      setErrorMessage(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function fetchShipmentDetail(id) {
    setDetailLoading(true)
    try {
      const data = await apiFetch(`/api/export/shipments/${id}`, { headers: authHeaders }, 'Failed to fetch shipment details')
      setSelectedShipment(data)
    } catch (err) {
      setErrorMessage(err.message)
    } finally {
      setDetailLoading(false)
    }
  }

  async function handleCreateShipment(e) {
    e.preventDefault()
    setErrorMessage(null)
    try {
      const payload = {
        ...newShipmentForm,
        package_count: Number(newShipmentForm.package_count) || 1,
        gross_weight_kg: Number(newShipmentForm.gross_weight_kg) || 0,
        net_weight_kg: Number(newShipmentForm.net_weight_kg) || 0,
      }
      const created = await apiFetch(
        '/api/export/shipments',
        {
          method: 'POST',
          headers: { ...authHeaders, 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
        'Failed to create export shipment'
      )
      setSuccessMessage(`Export shipment ${created.reference || created.id} created successfully!`)
      setIsNewShipmentModalOpen(false)
      fetchShipments()
      setSelectedShipment(created)
    } catch (err) {
      setErrorMessage(err.message)
    }
  }

  async function handleStatusTransition(targetStatus) {
    if (!selectedShipment) return
    setErrorMessage(null)
    try {
      const updated = await apiFetch(
        `/api/export/shipments/${selectedShipment.id}/status`,
        {
          method: 'POST',
          headers: { ...authHeaders, 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: targetStatus, notes: `Transitioned by ${operatorEmail}` }),
        },
        'Failed to update shipment status'
      )
      setSuccessMessage(`Shipment transitioned to status: ${updated.status}`)
      fetchShipmentDetail(selectedShipment.id)
      fetchShipments()
    } catch (err) {
      setErrorMessage(err.message)
    }
  }

  async function handleOpenLinkDispatchModal() {
    setIsLinkDispatchModalOpen(true)
    setSelectedDispatchId('')
    setLinkNotes('')
    try {
      // Fetch dispatches list from sales
      const data = await apiFetch('/api/sales/dispatches', { headers: authHeaders }, 'Failed to fetch dispatches')
      // Filter out already linked dispatches
      const alreadyLinkedIds = new Set((selectedShipment?.linked_dispatches || []).map((d) => d.dispatch_id))
      const available = (data || []).filter((d) => !alreadyLinkedIds.has(d.id))
      setAvailableDispatches(available)
      if (available.length > 0) {
        setSelectedDispatchId(available[0].id)
      }
    } catch (err) {
      setErrorMessage('Could not load dispatches: ' + err.message)
    }
  }

  async function handleLinkDispatch(e) {
    e.preventDefault()
    if (!selectedDispatchId || !selectedShipment) return
    try {
      await apiFetch(
        `/api/export/shipments/${selectedShipment.id}/dispatches`,
        {
          method: 'POST',
          headers: { ...authHeaders, 'Content-Type': 'application/json' },
          body: JSON.stringify({ dispatch_id: selectedDispatchId, notes: linkNotes }),
        },
        'Failed to link dispatch'
      )
      setSuccessMessage('Commercial dispatch linked and shipment cargo weights synced.')
      setIsLinkDispatchModalOpen(false)
      fetchShipmentDetail(selectedShipment.id)
      fetchShipments()
    } catch (err) {
      setErrorMessage(err.message)
    }
  }

  async function handleUnlinkDispatch(dispatchId) {
    if (!selectedShipment) return
    if (!window.confirm('Unlink this dispatch from the export shipment?')) return
    try {
      await apiFetch(
        `/api/export/shipments/${selectedShipment.id}/dispatches/${dispatchId}`,
        {
          method: 'DELETE',
          headers: authHeaders,
        },
        'Failed to unlink dispatch'
      )
      setSuccessMessage('Dispatch unlinked and weights updated.')
      fetchShipmentDetail(selectedShipment.id)
      fetchShipments()
    } catch (err) {
      setErrorMessage(err.message)
    }
  }

  async function handleGenerateDraftDocument(e) {
    e.preventDefault()
    if (!selectedShipment) return
    try {
      const generated = await apiFetch(
        `/api/export/shipments/${selectedShipment.id}/generate-document`,
        {
          method: 'POST',
          headers: { ...authHeaders, 'Content-Type': 'application/json' },
          body: JSON.stringify(genDocForm),
        },
        'Failed to generate draft document'
      )
      setSuccessMessage(`Draft ${generated.document_type} (Version ${generated.version}) generated successfully!`)
      setIsGenerateDocModalOpen(false)
      fetchShipmentDetail(selectedShipment.id)
    } catch (err) {
      setErrorMessage(err.message)
    }
  }

  function handleOpenReviewModal(doc) {
    setSelectedDocForReview(doc)
    setReviewForm({ decision: 'approved', review_notes: '' })
    setIsReviewDocModalOpen(true)
  }

  async function handleDocumentReviewSubmit(e) {
    e.preventDefault()
    if (!selectedDocForReview) return
    try {
      await apiFetch(
        `/api/export/documents/${selectedDocForReview.id}/review`,
        {
          method: 'POST',
          headers: { ...authHeaders, 'Content-Type': 'application/json' },
          body: JSON.stringify(reviewForm),
        },
        'Failed to review document'
      )
      setSuccessMessage(`Document marked as ${reviewForm.decision}.`)
      setIsReviewDocModalOpen(false)
      fetchShipmentDetail(selectedShipment.id)
    } catch (err) {
      setErrorMessage(err.message)
    }
  }

  async function handleViewVersionHistory(docId) {
    try {
      const versions = await apiFetch(`/api/export/documents/${docId}/versions`, { headers: authHeaders }, 'Failed to fetch version history')
      setSelectedDocVersions(versions || [])
      setIsVersionHistoryOpen(true)
    } catch (err) {
      setErrorMessage(err.message)
    }
  }

  const filteredShipments = useMemo(() => {
    return shipments.filter((s) => {
      const matchesSearch =
        (s.reference || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
        (s.destination_country || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
        (s.consignee_name || '').toLowerCase().includes(searchQuery.toLowerCase())
      const matchesStatus = statusFilter === 'all' || s.status === statusFilter
      return matchesSearch && matchesStatus
    })
  }, [shipments, searchQuery, statusFilter])

  return (
    <div className="export-view p-6 bg-slate-900 text-slate-100 min-h-screen">
      {/* Top Header & Role Switcher */}
      <div className="flex flex-wrap items-center justify-between pb-6 border-b border-slate-800 gap-4">
        <div>
          <div className="flex items-center gap-3">
            <Ship className="w-8 h-8 text-indigo-400" />
            <h1 className="text-2xl font-bold tracking-tight text-white">Export Operations & Documentation</h1>
            <span className="text-xs uppercase px-2.5 py-0.5 rounded-full font-semibold bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              Phase 5
            </span>
          </div>
          <p className="text-sm text-slate-400 mt-1">
            End-to-end export lifecycle: dispatch linking, checklist rules, versioned documents, and deterministic readiness.
          </p>
        </div>

        {/* Security & Operator Role Selector */}
        <div className="flex items-center gap-3 bg-slate-800/80 p-2.5 rounded-xl border border-slate-700/60 shadow-inner">
          <Shield className="w-4 h-4 text-emerald-400" />
          <div className="text-xs">
            <span className="text-slate-400 block font-mono">Actor Context</span>
            <span className="text-white font-medium">{operatorEmail}</span>
          </div>
          <select
            value={currentRole}
            onChange={(e) => {
              const r = e.target.value
              setCurrentRole(r)
              setOperatorEmail(`${r}@tradesathi.local`)
            }}
            className="bg-slate-900 border border-slate-700 text-xs rounded-lg px-2.5 py-1.5 text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          >
            <option value="admin">Role: Admin</option>
            <option value="manager">Role: Manager</option>
            <option value="operator">Role: Operator</option>
            <option value="sales">Role: Sales</option>
            <option value="warehouse">Role: Warehouse</option>
            <option value="viewer">Role: Viewer (Read-only)</option>
          </select>
        </div>
      </div>

      {/* Error / Success Banners */}
      {errorMessage && (
        <div className="mt-4 p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5 text-rose-400" />
          <div className="flex-1 text-sm font-medium">{errorMessage}</div>
          <button onClick={() => setErrorMessage(null)} className="text-rose-400 hover:text-rose-200">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {successMessage && (
        <div className="mt-4 p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 flex items-start gap-3">
          <CheckCircle2 className="w-5 h-5 flex-shrink-0 mt-0.5 text-emerald-400" />
          <div className="flex-1 text-sm font-medium">{successMessage}</div>
          <button onClick={() => setSuccessMessage(null)} className="text-emerald-400 hover:text-emerald-200">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Main Content Area */}
      {!selectedShipment ? (
        /* Shipments List View */
        <div className="mt-6 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3 flex-1 min-w-[280px]">
              <div className="relative flex-1">
                <Search className="w-4 h-4 absolute left-3 top-3 text-slate-400" />
                <input
                  type="text"
                  placeholder="Search by reference, country, consignee..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full bg-slate-800/80 border border-slate-700/80 rounded-xl pl-9 pr-4 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div className="flex items-center gap-2 bg-slate-800/80 border border-slate-700/80 rounded-xl px-3 py-2">
                <Filter className="w-4 h-4 text-slate-400" />
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  className="bg-transparent text-sm text-slate-200 focus:outline-none"
                >
                  <option value="all">All Statuses</option>
                  <option value="draft">Draft</option>
                  <option value="booked">Booked</option>
                  <option value="document_prep">Document Prep</option>
                  <option value="ready_for_dispatch">Ready for Dispatch</option>
                  <option value="departed">Departed</option>
                  <option value="arrived">Arrived</option>
                  <option value="completed">Completed</option>
                  <option value="cancelled">Cancelled</option>
                </select>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={fetchShipments}
                disabled={loading}
                className="p-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition"
                title="Refresh shipments"
              >
                <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              </button>

              <button
                onClick={() => setIsNewShipmentModalOpen(true)}
                disabled={currentRole === 'viewer'}
                className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-xl text-sm font-semibold shadow-lg shadow-indigo-600/20 transition"
              >
                <Plus className="w-4 h-4" />
                <span>New Export Shipment</span>
              </button>
            </div>
          </div>

          {/* Shipments Grid / Table */}
          <div className="border border-slate-800 rounded-2xl bg-slate-800/40 backdrop-blur overflow-hidden shadow-xl">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-slate-800/80 text-xs uppercase tracking-wider text-slate-400 border-b border-slate-700/80">
                  <tr>
                    <th className="px-6 py-4">Reference</th>
                    <th className="px-6 py-4">Destination</th>
                    <th className="px-6 py-4">Consignee</th>
                    <th className="px-6 py-4">Transport</th>
                    <th className="px-6 py-4">Packages / Weight</th>
                    <th className="px-6 py-4">Readiness Status</th>
                    <th className="px-6 py-4">Shipment State</th>
                    <th className="px-6 py-4 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/80">
                  {loading && shipments.length === 0 ? (
                    <tr>
                      <td colSpan="8" className="px-6 py-12 text-center text-slate-400">
                        <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-indigo-400" />
                        Loading export shipments...
                      </td>
                    </tr>
                  ) : filteredShipments.length === 0 ? (
                    <tr>
                      <td colSpan="8" className="px-6 py-12 text-center text-slate-400">
                        No export shipments found matching criteria.
                      </td>
                    </tr>
                  ) : (
                    filteredShipments.map((s) => (
                      <tr key={s.id} className="hover:bg-slate-800/60 transition group">
                        <td className="px-6 py-4 font-mono font-medium text-white flex items-center gap-2">
                          <Ship className="w-4 h-4 text-indigo-400" />
                          <span>{s.reference || s.id.slice(0, 8)}</span>
                        </td>
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-slate-200">{s.destination_country || '—'}</span>
                            {s.port_of_discharge && (
                              <span className="text-xs text-slate-400">({s.port_of_discharge})</span>
                            )}
                          </div>
                        </td>
                        <td className="px-6 py-4 text-slate-300">{s.consignee_name || '—'}</td>
                        <td className="px-6 py-4 text-slate-300">
                          <span className="capitalize">{s.transport_mode || 'sea'}</span>
                          {s.vessel_name && <span className="block text-xs text-slate-400">{s.vessel_name}</span>}
                        </td>
                        <td className="px-6 py-4 text-slate-300">
                          <div>{s.package_count || 0} pkgs</div>
                          <div className="text-xs text-slate-400 font-mono">
                            {s.gross_weight_kg ? `${s.gross_weight_kg} kg` : '—'}
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <ReadinessBadge status={s.readiness_status} />
                        </td>
                        <td className="px-6 py-4">
                          <StateBadge status={s.status} />
                        </td>
                        <td className="px-6 py-4 text-right">
                          <button
                            onClick={() => setSelectedShipment(s)}
                            className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-indigo-300 hover:text-white rounded-lg text-xs font-medium border border-slate-700 transition"
                          >
                            Manage Shipment &rarr;
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : (
        /* Detailed Shipment Workspace */
        <div className="mt-6 space-y-6">
          {/* Top Bar with Back Button & Key Actions */}
          <div className="flex flex-wrap items-center justify-between gap-4 bg-slate-800/80 p-4 rounded-2xl border border-slate-700/80">
            <div className="flex items-center gap-4">
              <button
                onClick={() => {
                  setSelectedShipment(null)
                  fetchShipments()
                }}
                className="px-3 py-2 rounded-xl bg-slate-700/60 hover:bg-slate-700 text-slate-300 text-xs font-semibold flex items-center gap-1.5 transition"
              >
                &larr; Back to List
              </button>
              <div>
                <div className="flex items-center gap-3">
                  <h2 className="text-xl font-bold text-white font-mono">{selectedShipment.reference}</h2>
                  <StateBadge status={selectedShipment.status} />
                  <ReadinessBadge status={selectedShipment.readiness_status} />
                </div>
                <div className="text-xs text-slate-400 mt-1 flex items-center gap-4">
                  <span>Destination: <strong>{selectedShipment.destination_country}</strong></span>
                  <span>Transport: <strong className="capitalize">{selectedShipment.transport_mode}</strong></span>
                  <span>Incoterm: <strong>{selectedShipment.incoterm || 'FOB'}</strong></span>
                </div>
              </div>
            </div>

            {/* State Transition Actions */}
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs text-slate-400 mr-1">Move State:</span>
              {selectedShipment.status === 'draft' && (
                <button
                  onClick={() => handleStatusTransition('booked')}
                  disabled={currentRole === 'viewer'}
                  className="px-3 py-1.5 bg-sky-600 hover:bg-sky-500 text-white rounded-lg text-xs font-semibold"
                >
                  Mark Booked
                </button>
              )}
              {selectedShipment.status === 'booked' && (
                <button
                  onClick={() => handleStatusTransition('document_prep')}
                  disabled={currentRole === 'viewer'}
                  className="px-3 py-1.5 bg-amber-600 hover:bg-amber-500 text-white rounded-lg text-xs font-semibold"
                >
                  Start Document Prep
                </button>
              )}
              {selectedShipment.status === 'document_prep' && (
                <button
                  onClick={() => handleStatusTransition('ready_for_dispatch')}
                  disabled={currentRole === 'viewer'}
                  className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold shadow"
                >
                  Ready for Dispatch
                </button>
              )}
              {selectedShipment.status === 'ready_for_dispatch' && (
                <button
                  onClick={() => handleStatusTransition('departed')}
                  disabled={currentRole === 'viewer'}
                  className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold"
                >
                  Mark Departed
                </button>
              )}
              {selectedShipment.status === 'departed' && (
                <button
                  onClick={() => handleStatusTransition('arrived')}
                  disabled={currentRole === 'viewer'}
                  className="px-3 py-1.5 bg-teal-600 hover:bg-teal-500 text-white rounded-lg text-xs font-semibold"
                >
                  Mark Arrived
                </button>
              )}
              {selectedShipment.status === 'arrived' && (
                <button
                  onClick={() => handleStatusTransition('completed')}
                  disabled={currentRole === 'viewer'}
                  className="px-3 py-1.5 bg-emerald-700 hover:bg-emerald-600 text-white rounded-lg text-xs font-semibold"
                >
                  Complete Shipment
                </button>
              )}
              {selectedShipment.status !== 'completed' && selectedShipment.status !== 'cancelled' && (
                <button
                  onClick={() => handleStatusTransition('cancelled')}
                  disabled={currentRole === 'viewer'}
                  className="px-3 py-1.5 bg-rose-600/80 hover:bg-rose-600 text-white rounded-lg text-xs font-semibold"
                >
                  Cancel
                </button>
              )}
            </div>
          </div>

          {/* 1. DETERMINISTIC READINESS & COMPLIANCE SECTION */}
          <div className="bg-slate-800/40 border border-slate-700/80 rounded-2xl p-6 backdrop-blur space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-700/60 pb-4">
              <div className="flex items-center gap-3">
                <ShieldAlert className="w-6 h-6 text-indigo-400" />
                <div>
                  <h3 className="text-base font-bold text-white">Deterministic Shipment Readiness Engine</h3>
                  <p className="text-xs text-slate-400">
                    Evaluates missing documents, approval statuses, discrepancy findings, and cargo reconciliation.
                  </p>
                </div>
              </div>
              <button
                onClick={() => fetchShipmentDetail(selectedShipment.id)}
                className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-medium border border-slate-700 flex items-center gap-1.5"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                Re-evaluate Readiness
              </button>
            </div>

            {/* MANDATORY LEGAL & REGULATORY NON-CLEARANCE DISCLAIMER */}
            <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-200 text-xs leading-relaxed flex items-start gap-3">
              <AlertTriangle className="w-5 h-5 flex-shrink-0 text-amber-400 mt-0.5" />
              <div>
                <strong className="block text-amber-300 font-semibold mb-0.5">
                  OFFICIAL COMPLIANCE & LEGAL NOTICE
                </strong>
                TradeSathi AI readiness assessment is an internal software preparation tool and does NOT constitute
                official customs clearance, legal compliance, or regulatory authorization. All shipping documents must be
                reviewed and certified by licensed customs brokers and authorized company officers.
              </div>
            </div>

            {/* Readiness Summary Cards */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-slate-900/60 p-4 rounded-xl border border-slate-800">
                <span className="text-xs text-slate-400 block font-medium">Evaluation Outcome</span>
                <span className="text-lg font-bold text-white capitalize mt-1 block">
                  {selectedShipment.readiness?.readiness_status?.replace(/_/g, ' ') || 'Not Evaluated'}
                </span>
                <span className="text-xs text-slate-500 mt-1 block">
                  Last Checked: {selectedShipment.readiness?.evaluated_at?.slice(0, 19).replace('T', ' ') || 'Never'}
                </span>
              </div>

              <div className="bg-slate-900/60 p-4 rounded-xl border border-slate-800">
                <span className="text-xs text-slate-400 block font-medium">Active Blockers</span>
                <span className="text-lg font-bold text-rose-400 mt-1 block">
                  {selectedShipment.readiness?.blockers?.length || 0} Blockers
                </span>
                <span className="text-xs text-slate-500 mt-1 block">Must be resolved prior to dispatch</span>
              </div>

              <div className="bg-slate-900/60 p-4 rounded-xl border border-slate-800">
                <span className="text-xs text-slate-400 block font-medium">Advisory Warnings</span>
                <span className="text-lg font-bold text-amber-400 mt-1 block">
                  {selectedShipment.readiness?.warnings?.length || 0} Warnings
                </span>
                <span className="text-xs text-slate-500 mt-1 block">Review recommended</span>
              </div>
            </div>

            {/* Blockers List */}
            {selectedShipment.readiness?.blockers?.length > 0 && (
              <div className="space-y-2 mt-4">
                <h4 className="text-xs font-semibold uppercase text-rose-400 tracking-wider flex items-center gap-2">
                  <XCircle className="w-4 h-4" />
                  Readiness Blockers (Immediate Action Required)
                </h4>
                <div className="space-y-2">
                  {selectedShipment.readiness.blockers.map((b, idx) => (
                    <div
                      key={idx}
                      className="p-3 bg-rose-500/10 border border-rose-500/20 rounded-xl text-xs text-rose-200 flex items-start justify-between gap-3"
                    >
                      <div>
                        <span className="font-semibold text-rose-300 block">{b.message}</span>
                        {b.document_type && (
                          <span className="text-slate-400 font-mono text-[11px] block mt-0.5">
                            Target Document: {b.document_type}
                          </span>
                        )}
                      </div>
                      <span className="px-2 py-0.5 rounded text-[10px] uppercase font-mono bg-rose-500/20 text-rose-300">
                        {b.code}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Warnings List */}
            {selectedShipment.readiness?.warnings?.length > 0 && (
              <div className="space-y-2 mt-4">
                <h4 className="text-xs font-semibold uppercase text-amber-400 tracking-wider flex items-center gap-2">
                  <AlertCircle className="w-4 h-4" />
                  Operational Warnings
                </h4>
                <div className="space-y-2">
                  {selectedShipment.readiness.warnings.map((w, idx) => (
                    <div
                      key={idx}
                      className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-xl text-xs text-amber-200 flex items-start justify-between gap-3"
                    >
                      <div>
                        <span className="font-semibold text-amber-300 block">{w.message}</span>
                        {w.details && (
                          <span className="text-slate-400 font-mono text-[11px] block mt-0.5">
                            Details: {JSON.stringify(w.details)}
                          </span>
                        )}
                      </div>
                      <span className="px-2 py-0.5 rounded text-[10px] uppercase font-mono bg-amber-500/20 text-amber-300">
                        {w.code}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* 2. LINKED COMMERCIAL DISPATCHES & CARGO RECONCILIATION */}
          <div className="bg-slate-800/40 border border-slate-700/80 rounded-2xl p-6 backdrop-blur space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-700/60 pb-4">
              <div className="flex items-center gap-3">
                <Boxes className="w-6 h-6 text-sky-400" />
                <div>
                  <h3 className="text-base font-bold text-white">Linked Commercial Dispatches</h3>
                  <p className="text-xs text-slate-400">
                    Connects warehouse fulfilment dispatches. Prevents duplicate allocation and automatically reconciles cargo totals.
                  </p>
                </div>
              </div>

              <button
                onClick={handleOpenLinkDispatchModal}
                disabled={currentRole === 'viewer'}
                className="px-3.5 py-1.5 bg-sky-600 hover:bg-sky-500 text-white rounded-xl text-xs font-semibold shadow transition flex items-center gap-1.5"
              >
                <LinkIcon className="w-3.5 h-3.5" />
                Link Commercial Dispatch
              </button>
            </div>

            {/* Linked Dispatches Table */}
            <div className="border border-slate-800 rounded-xl overflow-hidden bg-slate-900/60">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-800/80 uppercase text-slate-400">
                  <tr>
                    <th className="px-4 py-3">Dispatch Number</th>
                    <th className="px-4 py-3">Sales Order</th>
                    <th className="px-4 py-3">Customer</th>
                    <th className="px-4 py-3">Carrier / Tracking</th>
                    <th className="px-4 py-3">Packages</th>
                    <th className="px-4 py-3">Gross Weight</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {!selectedShipment.linked_dispatches || selectedShipment.linked_dispatches.length === 0 ? (
                    <tr>
                      <td colSpan="8" className="px-4 py-8 text-center text-slate-500">
                        No commercial dispatches linked yet. Click &quot;Link Commercial Dispatch&quot; to attach warehouse packages.
                      </td>
                    </tr>
                  ) : (
                    selectedShipment.linked_dispatches.map((d) => (
                      <tr key={d.link_id || d.dispatch_id} className="hover:bg-slate-800/40">
                        <td className="px-4 py-3 font-mono font-medium text-white">{d.dispatch_number}</td>
                        <td className="px-4 py-3 text-slate-300 font-mono">{d.order_number || d.order_id}</td>
                        <td className="px-4 py-3 text-slate-300">{d.customer_name || '—'}</td>
                        <td className="px-4 py-3 text-slate-400">
                          {d.carrier_name || '—'} {d.tracking_number && `(${d.tracking_number})`}
                        </td>
                        <td className="px-4 py-3 text-slate-200 font-medium">{d.total_packages || 1} pkgs</td>
                        <td className="px-4 py-3 text-slate-300 font-mono">
                          {d.total_gross_weight ? `${d.total_gross_weight} kg` : '0 kg'}
                        </td>
                        <td className="px-4 py-3">
                          <span className="capitalize px-2 py-0.5 rounded text-[10px] font-semibold bg-sky-500/10 text-sky-400 border border-sky-500/20">
                            {d.dispatch_status || 'dispatched'}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button
                            onClick={() => handleUnlinkDispatch(d.dispatch_id)}
                            disabled={currentRole === 'viewer'}
                            className="p-1 text-rose-400 hover:text-rose-200 hover:bg-rose-500/20 rounded transition"
                            title="Unlink dispatch"
                          >
                            <Unlink className="w-4 h-4" />
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* 3. EXPORT DOCUMENT CHECKLIST & VERSIONED REGISTRY */}
          <div className="bg-slate-800/40 border border-slate-700/80 rounded-2xl p-6 backdrop-blur space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-700/60 pb-4">
              <div className="flex items-center gap-3">
                <FileCheck className="w-6 h-6 text-emerald-400" />
                <div>
                  <h3 className="text-base font-bold text-white">Configurable Export Document Checklist</h3>
                  <p className="text-xs text-slate-400">
                    Destination and transport-specific checklist. Supports version history, separation of duties, and audit tracking.
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={() => setIsGenerateDocModalOpen(true)}
                  disabled={currentRole === 'viewer'}
                  className="px-3.5 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-semibold shadow transition flex items-center gap-1.5"
                >
                  <FileCode className="w-3.5 h-3.5" />
                  Generate Draft Document
                </button>
              </div>
            </div>

            {/* Checklist Items Table */}
            <div className="border border-slate-800 rounded-xl overflow-hidden bg-slate-900/60">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-800/80 uppercase text-slate-400">
                  <tr>
                    <th className="px-4 py-3">Document Category</th>
                    <th className="px-4 py-3">Requirement</th>
                    <th className="px-4 py-3">Rule Source</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Current Version</th>
                    <th className="px-4 py-3">Review Details</th>
                    <th className="px-4 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {!selectedShipment.checklist_items || selectedShipment.checklist_items.length === 0 ? (
                    <tr>
                      <td colSpan="7" className="px-4 py-8 text-center text-slate-500">
                        No checklist items configured for this shipment.
                      </td>
                    </tr>
                  ) : (
                    selectedShipment.checklist_items.map((it) => (
                      <tr key={it.id} className="hover:bg-slate-800/40">
                        <td className="px-4 py-3 font-medium text-white">
                          <span className="capitalize">{it.document_type?.replace(/_/g, ' ')}</span>
                          <span className="block text-[11px] text-slate-400">{it.reason}</span>
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] uppercase font-semibold border ${
                              it.requirement_level === 'mandatory'
                                ? 'bg-rose-500/10 text-rose-400 border-rose-500/20'
                                : it.requirement_level === 'conditional'
                                ? 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                                : 'bg-slate-500/10 text-slate-400 border-slate-500/20'
                            }`}
                          >
                            {it.requirement_level}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-400 font-mono">{it.rule_source || 'standard'}</td>
                        <td className="px-4 py-3">
                          <DocStatusBadge status={it.status} />
                        </td>
                        <td className="px-4 py-3 font-mono text-slate-300">
                          {it.document_id ? (
                            <div className="flex items-center gap-1.5">
                              <span>v{it.document_version || 1}</span>
                              <button
                                onClick={() => handleViewVersionHistory(it.document_id)}
                                className="text-indigo-400 hover:text-indigo-200 underline text-[11px]"
                              >
                                History
                              </button>
                            </div>
                          ) : (
                            <span className="text-slate-500">Not Uploaded</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-slate-300">
                          {it.reviewed_by ? (
                            <div>
                              <span>{it.reviewed_by}</span>
                              <span className="block text-[10px] text-slate-500">
                                {it.reviewed_at?.slice(0, 16).replace('T', ' ')}
                              </span>
                            </div>
                          ) : (
                            <span className="text-slate-500">—</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-right space-x-2">
                          {it.document_id && (
                            <button
                              onClick={() =>
                                handleOpenReviewModal({
                                  id: it.document_id,
                                  type: it.document_type,
                                  checklist_item_id: it.id,
                                })
                              }
                              disabled={currentRole === 'viewer'}
                              className="px-2 py-1 bg-emerald-600/80 hover:bg-emerald-600 text-white rounded text-[11px] font-semibold transition"
                            >
                              Review
                            </button>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* 4. CARGO & TRANSPORT MILESTONES SUMMARY */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="bg-slate-800/40 border border-slate-700/80 rounded-2xl p-6 backdrop-blur space-y-3">
              <h4 className="text-sm font-bold text-white flex items-center gap-2 border-b border-slate-700/60 pb-3">
                <Truck className="w-4 h-4 text-indigo-400" />
                Consignment & Cargo Summary
              </h4>
              <div className="grid grid-cols-2 gap-4 text-xs">
                <div>
                  <span className="text-slate-400 block">Exporter Name</span>
                  <span className="text-white font-medium">{selectedShipment.exporter_name || '—'}</span>
                </div>
                <div>
                  <span className="text-slate-400 block">Consignee Name</span>
                  <span className="text-white font-medium">{selectedShipment.consignee_name || '—'}</span>
                </div>
                <div>
                  <span className="text-slate-400 block">Total Packages</span>
                  <span className="text-white font-bold">{selectedShipment.package_count || 0} pkgs</span>
                </div>
                <div>
                  <span className="text-slate-400 block">Gross Weight</span>
                  <span className="text-white font-bold">{selectedShipment.gross_weight_kg || 0} kg</span>
                </div>
                <div>
                  <span className="text-slate-400 block">Net Weight</span>
                  <span className="text-white font-bold">{selectedShipment.net_weight_kg || 0} kg</span>
                </div>
                <div>
                  <span className="text-slate-400 block">Booking Reference</span>
                  <span className="text-white font-mono">{selectedShipment.booking_reference || '—'}</span>
                </div>
              </div>
            </div>

            <div className="bg-slate-800/40 border border-slate-700/80 rounded-2xl p-6 backdrop-blur space-y-3">
              <h4 className="text-sm font-bold text-white flex items-center gap-2 border-b border-slate-700/60 pb-3">
                <Compass className="w-4 h-4 text-indigo-400" />
                Logistics & Ports Routing
              </h4>
              <div className="grid grid-cols-2 gap-4 text-xs">
                <div>
                  <span className="text-slate-400 block">Port of Loading</span>
                  <span className="text-white font-medium">{selectedShipment.port_of_loading || '—'}</span>
                </div>
                <div>
                  <span className="text-slate-400 block">Port of Discharge</span>
                  <span className="text-white font-medium">{selectedShipment.port_of_discharge || '—'}</span>
                </div>
                <div>
                  <span className="text-slate-400 block">Vessel / Flight</span>
                  <span className="text-white font-medium">{selectedShipment.vessel_name || '—'}</span>
                </div>
                <div>
                  <span className="text-slate-400 block">Voyage / Flight No</span>
                  <span className="text-white font-mono">{selectedShipment.voyage_flight_no || '—'}</span>
                </div>
                <div>
                  <span className="text-slate-400 block">Carrier</span>
                  <span className="text-white font-medium">{selectedShipment.carrier_name || '—'}</span>
                </div>
                <div>
                  <span className="text-slate-400 block">Bill of Lading / AWB</span>
                  <span className="text-white font-mono">{selectedShipment.bill_of_lading_number || '—'}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* MODAL: New Export Shipment */}
      {/* ======================================================== */}
      {isNewShipmentModalOpen && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl max-w-2xl w-full p-6 shadow-2xl space-y-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <Ship className="w-5 h-5 text-indigo-400" />
                Create New Export Shipment
              </h3>
              <button onClick={() => setIsNewShipmentModalOpen(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreateShipment} className="space-y-4 text-xs">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-slate-400 mb-1 font-medium">Export Reference *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. EXP-2026-1049"
                    value={newShipmentForm.reference}
                    onChange={(e) => setNewShipmentForm({ ...newShipmentForm, reference: e.target.value })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1 font-medium">Destination Country (2-letter ISO) *</label>
                  <input
                    type="text"
                    required
                    maxLength="2"
                    placeholder="e.g. AE, SG, US, GB"
                    value={newShipmentForm.destination_country}
                    onChange={(e) =>
                      setNewShipmentForm({ ...newShipmentForm, destination_country: e.target.value.toUpperCase() })
                    }
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white font-mono"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-slate-400 mb-1 font-medium">Consignee Name *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Emirates Trading LLC"
                    value={newShipmentForm.consignee_name}
                    onChange={(e) => setNewShipmentForm({ ...newShipmentForm, consignee_name: e.target.value })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1 font-medium">Consignee Address</label>
                  <input
                    type="text"
                    placeholder="e.g. Warehouse 4B, Jebel Ali Free Zone, Dubai"
                    value={newShipmentForm.consignee_address}
                    onChange={(e) => setNewShipmentForm({ ...newShipmentForm, consignee_address: e.target.value })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="block text-slate-400 mb-1 font-medium">Transport Mode</label>
                  <select
                    value={newShipmentForm.transport_mode}
                    onChange={(e) => setNewShipmentForm({ ...newShipmentForm, transport_mode: e.target.value })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                  >
                    <option value="sea">Sea Freight</option>
                    <option value="air">Air Freight</option>
                    <option value="road">Road / Cross-Border</option>
                    <option value="rail">Rail Transport</option>
                  </select>
                </div>
                <div>
                  <label className="block text-slate-400 mb-1 font-medium">Port of Loading</label>
                  <input
                    type="text"
                    placeholder="e.g. Kolkata Port"
                    value={newShipmentForm.port_of_loading}
                    onChange={(e) => setNewShipmentForm({ ...newShipmentForm, port_of_loading: e.target.value })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1 font-medium">Port of Discharge</label>
                  <input
                    type="text"
                    placeholder="e.g. Jebel Ali Port"
                    value={newShipmentForm.port_of_discharge}
                    onChange={(e) => setNewShipmentForm({ ...newShipmentForm, port_of_discharge: e.target.value })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="block text-slate-400 mb-1 font-medium">Package Count</label>
                  <input
                    type="number"
                    min="1"
                    value={newShipmentForm.package_count}
                    onChange={(e) => setNewShipmentForm({ ...newShipmentForm, package_count: e.target.value })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1 font-medium">Gross Weight (kg)</label>
                  <input
                    type="number"
                    step="0.1"
                    value={newShipmentForm.gross_weight_kg}
                    onChange={(e) => setNewShipmentForm({ ...newShipmentForm, gross_weight_kg: e.target.value })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1 font-medium">Net Weight (kg)</label>
                  <input
                    type="number"
                    step="0.1"
                    value={newShipmentForm.net_weight_kg}
                    onChange={(e) => setNewShipmentForm({ ...newShipmentForm, net_weight_kg: e.target.value })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                  />
                </div>
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setIsNewShipmentModalOpen(false)}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl font-semibold shadow"
                >
                  Create Shipment
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* MODAL: Link Commercial Dispatch */}
      {/* ======================================================== */}
      {isLinkDispatchModalOpen && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <LinkIcon className="w-5 h-5 text-sky-400" />
                Link Warehouse Commercial Dispatch
              </h3>
              <button onClick={() => setIsLinkDispatchModalOpen(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleLinkDispatch} className="space-y-4 text-xs">
              <div>
                <label className="block text-slate-400 mb-1 font-medium">Select Available Dispatch</label>
                {availableDispatches.length === 0 ? (
                  <div className="p-3 bg-slate-800/80 rounded-xl text-slate-400">
                    No unlinked dispatches found. All warehouse dispatches are already linked or none exist.
                  </div>
                ) : (
                  <select
                    value={selectedDispatchId}
                    onChange={(e) => setSelectedDispatchId(e.target.value)}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                  >
                    {availableDispatches.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.dispatch_number} — Packages: {d.packages_count || 1} — Carrier: {d.carrier || 'N/A'}
                      </option>
                    ))}
                  </select>
                )}
              </div>

              <div>
                <label className="block text-slate-400 mb-1 font-medium">Linkage Notes</label>
                <input
                  type="text"
                  placeholder="e.g. First partial container consignment"
                  value={linkNotes}
                  onChange={(e) => setLinkNotes(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                />
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setIsLinkDispatchModalOpen(false)}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={availableDispatches.length === 0}
                  className="px-4 py-2 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white rounded-xl font-semibold shadow"
                >
                  Confirm Linkage
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* MODAL: Generate Draft Document */}
      {/* ======================================================== */}
      {isGenerateDocModalOpen && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl max-w-md w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <FileCode className="w-5 h-5 text-indigo-400" />
                Generate Controlled Draft Document
              </h3>
              <button onClick={() => setIsGenerateDocModalOpen(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <p className="text-xs text-slate-400 leading-relaxed">
              Populates document template from validated shipment and linked order data. Watermarked as{' '}
              <strong className="text-amber-400 font-mono">DRAFT</strong> until authorized review and issuance.
            </p>

            <form onSubmit={handleGenerateDraftDocument} className="space-y-4 text-xs">
              <div>
                <label className="block text-slate-400 mb-1 font-medium">Document Template</label>
                <select
                  value={genDocForm.template_type}
                  onChange={(e) => setGenDocForm({ template_type: e.target.value })}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                >
                  <option value="commercial_invoice">Commercial Invoice</option>
                  <option value="packing_list">Packing List</option>
                  <option value="shipping_instructions">Shipping Instructions</option>
                </select>
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setIsGenerateDocModalOpen(false)}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl font-semibold shadow"
                >
                  Generate Draft
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* MODAL: Review Document (Separation of Duties) */}
      {/* ======================================================== */}
      {isReviewDocModalOpen && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl max-w-md w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <UserCheck className="w-5 h-5 text-emerald-400" />
                Document Verification & Approval
              </h3>
              <button onClick={() => setIsReviewDocModalOpen(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <p className="text-xs text-slate-400 leading-relaxed">
              Enforces separation-of-duties: the operator who uploaded or generated this document cannot approve it.
            </p>

            <form onSubmit={handleDocumentReviewSubmit} className="space-y-4 text-xs">
              <div>
                <label className="block text-slate-400 mb-1 font-medium">Review Decision</label>
                <select
                  value={reviewForm.decision}
                  onChange={(e) => setReviewForm({ ...reviewForm, decision: e.target.value })}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                >
                  <option value="approved">Approve Document</option>
                  <option value="rejected">Reject Document</option>
                </select>
              </div>

              <div>
                <label className="block text-slate-400 mb-1 font-medium">Review Notes</label>
                <textarea
                  rows="3"
                  placeholder="Verification rationale, stamp verification, or rejection reasons..."
                  value={reviewForm.review_notes}
                  onChange={(e) => setReviewForm({ ...reviewForm, review_notes: e.target.value })}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                />
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setIsReviewDocModalOpen(false)}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl font-semibold shadow"
                >
                  Submit Decision
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* DRAWER / MODAL: Version History Chain */}
      {/* ======================================================== */}
      {isVersionHistoryOpen && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl max-w-xl w-full p-6 shadow-2xl space-y-4 max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <History className="w-5 h-5 text-indigo-400" />
                Document Version Lineage & Evidence
              </h3>
              <button onClick={() => setIsVersionHistoryOpen(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3">
              {selectedDocVersions.length === 0 ? (
                <div className="text-slate-400 text-xs text-center py-6">No previous versions found.</div>
              ) : (
                selectedDocVersions.map((v) => (
                  <div key={v.id} className="p-3 bg-slate-800/80 rounded-xl border border-slate-700/60 text-xs space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-white flex items-center gap-2">
                        <span>Version {v.version || 1}</span>
                        {v.is_current_version === 1 && (
                          <span className="px-2 py-0.5 rounded text-[10px] bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                            Current
                          </span>
                        )}
                      </span>
                      <DocStatusBadge status={v.review_status} />
                    </div>
                    <div className="text-slate-400 font-mono text-[11px]">Filename: {v.original_filename}</div>
                    <div className="text-slate-500 font-mono text-[10px] truncate">SHA256: {v.sha256_hash}</div>
                    <div className="text-slate-400 text-[11px]">
                      Uploaded: {v.created_at?.slice(0, 19).replace('T', ' ')}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function ReadinessBadge({ status }) {
  switch (status) {
    case 'internally_ready':
      return (
        <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1.5 w-fit">
          <CheckCircle2 className="w-3.5 h-3.5" /> Internally Ready
        </span>
      )
    case 'ready_for_internal_review':
      return (
        <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-sky-500/10 text-sky-400 border border-sky-500/20 flex items-center gap-1.5 w-fit">
          <UserCheck className="w-3.5 h-3.5" /> Ready for Review
        </span>
      )
    case 'needs_review':
      return (
        <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20 flex items-center gap-1.5 w-fit">
          <AlertCircle className="w-3.5 h-3.5" /> Needs Review
        </span>
      )
    case 'blocked':
      return (
        <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20 flex items-center gap-1.5 w-fit">
          <XCircle className="w-3.5 h-3.5" /> Blocked
        </span>
      )
    default:
      return (
        <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-slate-500/10 text-slate-400 border border-slate-500/20 flex items-center gap-1.5 w-fit">
          <Clock className="w-3.5 h-3.5" /> Not Evaluated
        </span>
      )
  }
}

function StateBadge({ status }) {
  const styles = {
    draft: 'bg-slate-500/10 text-slate-400 border-slate-500/20',
    booked: 'bg-sky-500/10 text-sky-400 border-sky-500/20',
    document_prep: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
    ready_for_dispatch: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20',
    departed: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
    arrived: 'bg-teal-500/10 text-teal-400 border-teal-500/20',
    completed: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
    cancelled: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
  }
  return (
    <span
      className={`px-2.5 py-0.5 rounded-full text-xs font-semibold capitalize border ${
        styles[status] || styles.draft
      }`}
    >
      {status?.replace(/_/g, ' ') || 'draft'}
    </span>
  )
}

function DocStatusBadge({ status }) {
  switch (status) {
    case 'approved':
    case 'verified_by_user':
      return (
        <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
          Approved
        </span>
      )
    case 'rejected':
      return (
        <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">
          Rejected
        </span>
      )
    case 'under_review':
      return (
        <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-sky-500/10 text-sky-400 border border-sky-500/20">
          Under Review
        </span>
      )
    case 'uploaded':
    case 'submitted':
      return (
        <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">
          Submitted
        </span>
      )
    case 'missing':
    default:
      return (
        <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-slate-500/10 text-slate-400 border border-slate-500/20">
          Missing
        </span>
      )
  }
}
