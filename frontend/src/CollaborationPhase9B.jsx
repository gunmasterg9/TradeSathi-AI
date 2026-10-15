import { useEffect, useState } from 'react'
import {
  AlertTriangle,
  ArrowLeft,
  Calendar,
  Check,
  CheckCircle2,
  Clock,
  Download,
  Eye,
  FileCheck2,
  FileText,
  FileUp,
  MessageSquare,
  Package,
  Plus,
  RefreshCw,
  Send,
  Shield,
  ShieldAlert,
  ShieldCheck,
  ShoppingCart,
  Truck,
  Upload,
  X,
  XCircle,
} from 'lucide-react'
import { apiFetch, API_BASE } from './api'

// ============================================================================
// 1. SUPPLIER DELIVERY COMMITMENTS SECTION
// ============================================================================

export function SupplierCommitmentsSection({ supplierSession, supplierPOs, onRefreshPOs }) {
  const [selectedPOId, setSelectedPOId] = useState('')
  const [commitments, setCommitments] = useState([])
  const [poDetail, setPoDetail] = useState(null)
  const [loading, setLoading] = useState(false)
  const [feedback, setFeedback] = useState(null)

  // Commitment form state
  const [proposedDate, setProposedDate] = useState('')
  const [dispatchRef, setDispatchRef] = useState('')
  const [carrierName, setCarrierName] = useState('')
  const [trackingNumber, setTrackingNumber] = useState('')
  const [comments, setComments] = useState('')
  const [lineQuantities, setLineQuantities] = useState({})
  const [submitting, setSubmitting] = useState(false)

  // Fetch commitments when PO changes
  useEffect(() => {
    if (!selectedPOId || !supplierSession?.access_token) {
      setCommitments([])
      setPoDetail(null)
      return
    }
    loadPOAndCommitments(selectedPOId)
  }, [selectedPOId, supplierSession])

  async function loadPOAndCommitments(poId) {
    setLoading(true)
    setFeedback(null)
    try {
      // Load PO details to know line items
      const poData = await apiFetch(`/api/portal/supplier/purchase-orders/${poId}`, {
        headers: { Authorization: `Bearer ${supplierSession.access_token}` },
      })
      setPoDetail(poData)

      // Initialize line quantities from remaining PO quantities
      const initialQtys = {}
      poData.items?.forEach((item) => {
        const remaining = Math.max(0, (item.ordered_qty || 0) - (item.received_qty || 0))
        initialQtys[item.id] = remaining
      })
      setLineQuantities(initialQtys)

      // Load existing commitments
      const comData = await apiFetch(`/api/portal/supplier/purchase-orders/${poId}/commitments`, {
        headers: { Authorization: `Bearer ${supplierSession.access_token}` },
      })
      setCommitments(comData.items || [])
    } catch (err) {
      setFeedback({ type: 'error', message: err.detail || 'Failed to load commitments for this PO.' })
    } finally {
      setLoading(false)
    }
  }

  async function handleSubmitCommitment(e) {
    if (e) e.preventDefault()
    if (!selectedPOId) return
    setSubmitting(true)
    setFeedback(null)

    try {
      const lines = Object.entries(lineQuantities)
        .filter(([_, qty]) => Number(qty) > 0)
        .map(([po_item_id, committed_qty]) => ({
          po_item_id,
          committed_qty: Number(committed_qty),
        }))

      const payload = {
        proposed_delivery_date: proposedDate || null,
        dispatch_reference: dispatchRef.trim() || null,
        carrier_name: carrierName.trim() || null,
        tracking_number: trackingNumber.trim() || null,
        supplier_comments: comments.trim() || null,
        lines: lines.length > 0 ? lines : null,
      }

      await apiFetch(`/api/portal/supplier/purchase-orders/${selectedPOId}/commitments`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${supplierSession.access_token}`,
        },
        body: JSON.stringify(payload),
      }, 'Failed to submit commitment')

      setFeedback({ type: 'success', message: 'Delivery commitment submitted successfully. Awaiting internal staff review.' })
      setProposedDate('')
      setDispatchRef('')
      setCarrierName('')
      setTrackingNumber('')
      setComments('')
      loadPOAndCommitments(selectedPOId)
      if (onRefreshPOs) onRefreshPOs()
    } catch (err) {
      setFeedback({ type: 'error', message: err.detail || 'Error submitting delivery commitment.' })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="panel" style={{ padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20, borderBottom: '1px solid var(--navy-800)', paddingBottom: 14 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 10 }}>
            <Calendar size={18} color="var(--teal-400)" /> Delivery Commitments &amp; Schedules
          </h2>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--slate-400)' }}>
            Submit, revise, or plan partial deliveries against active purchase orders without mutating internal terms.
          </p>
        </div>
      </div>

      {feedback && (
        <div className={feedback.type === 'success' ? 'clean-audit-card' : 'error-banner'} style={{ marginBottom: 16 }}>
          {feedback.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}
          <span>{feedback.message}</span>
        </div>
      )}

      {/* Purchase Order Selector */}
      <div style={{ maxWidth: 400, marginBottom: 24 }}>
        <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>
          Select Purchase Order
        </label>
        <select
          value={selectedPOId}
          onChange={(e) => setSelectedPOId(e.target.value)}
          style={{ width: '100%', padding: '10px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
        >
          <option value="">-- Choose Purchase Order --</option>
          {supplierPOs.map((po) => (
            <option key={po.id} value={po.id}>
              {po.po_number} ({po.status.toUpperCase()}) — Total: {po.currency} {Number(po.grand_total).toFixed(2)}
            </option>
          ))}
        </select>
      </div>

      {selectedPOId && poDetail && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
          {/* Commitment Proposal Form */}
          <div className="panel" style={{ background: 'var(--navy-950)', border: '1px solid var(--navy-800)', padding: 20, borderRadius: 10 }}>
            <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 16px', display: 'flex', alignItems: 'center', gap: 8 }}>
              <Clock size={16} color="var(--teal-300)" /> Submit / Revise Delivery Commitment
            </h3>
            <form onSubmit={handleSubmitCommitment} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 4 }}>
                  Proposed Delivery Date / ETA
                </label>
                <input
                  type="date"
                  value={proposedDate}
                  onChange={(e) => setProposedDate(e.target.value)}
                  style={{ width: '100%', padding: '8px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 4 }}>
                    Dispatch Reference
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. DISP-2026-001"
                    value={dispatchRef}
                    onChange={(e) => setDispatchRef(e.target.value)}
                    style={{ width: '100%', padding: '8px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 4 }}>
                    Carrier Name
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. DHL Express"
                    value={carrierName}
                    onChange={(e) => setCarrierName(e.target.value)}
                    style={{ width: '100%', padding: '8px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
                  />
                </div>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 4 }}>
                  Tracking Reference
                </label>
                <input
                  type="text"
                  placeholder="e.g. TRK-98234823"
                  value={trackingNumber}
                  onChange={(e) => setTrackingNumber(e.target.value)}
                  style={{ width: '100%', padding: '8px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
                />
              </div>

              {/* Partial Delivery Line Quantities */}
              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>
                  Partial Delivery Quantities by SKU
                </label>
                <div style={{ background: 'var(--navy-900)', borderRadius: 8, padding: 12, border: '1px solid var(--navy-800)' }}>
                  {poDetail.items?.map((item) => {
                    const remaining = Math.max(0, (item.ordered_qty || 0) - (item.received_qty || 0))
                    return (
                      <div key={item.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--navy-800)', fontSize: 13 }}>
                        <div>
                          <strong>{item.sku}</strong> — <span style={{ color: 'var(--slate-400)' }}>{item.product_name}</span>
                          <div style={{ fontSize: 11, color: 'var(--slate-400)' }}>Remaining: {remaining} {item.uom}</div>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <input
                            type="number"
                            min="0"
                            max={remaining}
                            step="any"
                            value={lineQuantities[item.id] ?? ''}
                            onChange={(e) => setLineQuantities({ ...lineQuantities, [item.id]: e.target.value })}
                            style={{ width: 80, padding: '4px 8px', borderRadius: 6, background: 'var(--navy-950)', border: '1px solid var(--navy-700)', color: '#fff', textAlign: 'right' }}
                          />
                          <span style={{ fontSize: 12, color: 'var(--slate-400)', width: 30 }}>{item.uom}</span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 4 }}>
                  Supplier Notes / Remarks
                </label>
                <textarea
                  rows={2}
                  placeholder="Notes on batch availability or manufacturing timeline..."
                  value={comments}
                  onChange={(e) => setComments(e.target.value.slice(0, 500))}
                  style={{ width: '100%', padding: '8px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
                />
              </div>

              <button type="submit" className="primary-button" disabled={submitting}>
                {submitting ? 'Submitting...' : 'Submit Commitment Proposal'}
              </button>
            </form>
          </div>

          {/* Commitment Revision History */}
          <div>
            <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 16px', display: 'flex', alignItems: 'center', gap: 8 }}>
              <FileCheck2 size={16} color="var(--teal-300)" /> Commitment Revision History
            </h3>
            {commitments.length === 0 ? (
              <div className="panel" style={{ padding: 30, textAlign: 'center', color: 'var(--slate-400)', background: 'var(--navy-950)' }}>
                No delivery commitments recorded yet for this purchase order.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {commitments.map((com) => (
                  <div key={com.id} className="panel" style={{ background: 'var(--navy-950)', border: '1px solid var(--navy-800)', padding: 16, borderRadius: 8 }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span className="provenance-pill status-ready">Rev v{com.revision_number}</span>
                        <span className={`status-tag status-${com.status}`}>{com.status.toUpperCase()}</span>
                      </div>
                      <small style={{ color: 'var(--slate-400)' }}>{new Date(com.created_at).toLocaleString()}</small>
                    </div>

                    <div style={{ fontSize: 13, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
                      <div>Proposed Date: <strong>{com.proposed_delivery_date || 'None'}</strong></div>
                      <div>Dispatch Ref: <strong>{com.dispatch_reference || 'None'}</strong></div>
                      <div>Carrier: <strong>{com.carrier_name || 'None'}</strong></div>
                      <div>Tracking: <strong>{com.tracking_number || 'None'}</strong></div>
                    </div>

                    {com.supplier_comments && (
                      <div style={{ fontSize: 12, color: 'var(--slate-300)', background: 'var(--navy-900)', padding: '6px 10px', borderRadius: 6, marginBottom: 8 }}>
                        "{com.supplier_comments}"
                      </div>
                    )}

                    {com.lines?.length > 0 && (
                      <div style={{ fontSize: 12, borderTop: '1px solid var(--navy-800)', paddingTop: 6 }}>
                        <small style={{ color: 'var(--slate-400)' }}>Committed Quantities:</small>
                        <ul style={{ margin: '4px 0 0', paddingLeft: 18, color: 'var(--teal-300)' }}>
                          {com.lines.map((l) => (
                            <li key={l.id}>{l.sku}: <strong>{l.committed_qty}</strong></li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ============================================================================
// 2. ADVANCE SHIPMENT NOTICES (ASN) SECTION
// ============================================================================

export function SupplierASNsSection({ supplierSession, supplierPOs }) {
  const [asns, setAsns] = useState([])
  const [total, setTotal] = useState(0)
  const [selectedASN, setSelectedASN] = useState(null)
  const [loading, setLoading] = useState(false)
  const [feedback, setFeedback] = useState(null)

  // Create ASN modal state
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [poId, setPoId] = useState('')
  const [poDetail, setPoDetail] = useState(null)
  const [dispatchRef, setDispatchRef] = useState('')
  const [dispatchDate, setDispatchDate] = useState('')
  const [arrivalDate, setArrivalDate] = useState('')
  const [packageCount, setPackageCount] = useState(1)
  const [carrierName, setCarrierName] = useState('')
  const [trackingNumber, setTrackingNumber] = useState('')
  const [notes, setNotes] = useState('')
  const [shippedQuantities, setShippedQuantities] = useState({})
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    if (supplierSession?.access_token) {
      loadASNs()
    }
  }, [supplierSession])

  async function loadASNs() {
    setLoading(true)
    try {
      const data = await apiFetch('/api/portal/supplier/asns', {
        headers: { Authorization: `Bearer ${supplierSession.access_token}` },
      })
      setAsns(data.items || [])
      setTotal(data.total || 0)
    } catch (err) {
      setFeedback({ type: 'error', message: err.detail || 'Failed to load ASNs.' })
    } finally {
      setLoading(false)
    }
  }

  async function handlePOChange(id) {
    setPoId(id)
    if (!id) {
      setPoDetail(null)
      setShippedQuantities({})
      return
    }
    try {
      const data = await apiFetch(`/api/portal/supplier/purchase-orders/${id}`, {
        headers: { Authorization: `Bearer ${supplierSession.access_token}` },
      })
      setPoDetail(data)
      const initial = {}
      data.items?.forEach((item) => {
        const remaining = Math.max(0, (item.ordered_qty || 0) - (item.received_qty || 0))
        initial[item.id] = remaining
      })
      setShippedQuantities(initial)
    } catch (err) {
      setFeedback({ type: 'error', message: 'Could not load order line items.' })
    }
  }

  async function handleCreateASN(e) {
    if (e) e.preventDefault()
    setCreating(true)
    setFeedback(null)

    try {
      const items = Object.entries(shippedQuantities)
        .filter(([_, qty]) => Number(qty) > 0)
        .map(([po_item_id, shipped_qty]) => ({
          po_item_id,
          shipped_qty: Number(shipped_qty),
        }))

      if (items.length === 0) {
        throw new Error('Please enter a shipped quantity for at least one item.')
      }

      const payload = {
        po_id: poId,
        dispatch_reference: dispatchRef.trim(),
        dispatch_date: dispatchDate,
        expected_arrival_date: arrivalDate,
        package_count: Number(packageCount) || 1,
        carrier_name: carrierName.trim() || null,
        tracking_number: trackingNumber.trim() || null,
        notes: notes.trim() || null,
        items,
      }

      await apiFetch('/api/portal/supplier/asns', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${supplierSession.access_token}`,
        },
        body: JSON.stringify(payload),
      }, 'Failed to create ASN')

      setFeedback({ type: 'success', message: 'Advance Shipment Notice created successfully!' })
      setIsModalOpen(false)
      setPoId('')
      setDispatchRef('')
      setDispatchDate('')
      setArrivalDate('')
      setCarrierName('')
      setTrackingNumber('')
      setNotes('')
      loadASNs()
    } catch (err) {
      setFeedback({ type: 'error', message: err.detail || err.message || 'Error creating ASN.' })
    } finally {
      setCreating(false)
    }
  }

  async function handleViewASNDetail(asnId) {
    try {
      const data = await apiFetch(`/api/portal/supplier/asns/${asnId}`, {
        headers: { Authorization: `Bearer ${supplierSession.access_token}` },
      })
      setSelectedASN(data)
    } catch (err) {
      setFeedback({ type: 'error', message: 'Could not retrieve ASN details.' })
    }
  }

  return (
    <div className="panel" style={{ padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20, borderBottom: '1px solid var(--navy-800)', paddingBottom: 14 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 10 }}>
            <Truck size={18} color="var(--teal-400)" /> Advance Shipment Notices (ASN)
          </h2>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--slate-400)' }}>
            Notify TradeSathi AI that goods have been dispatched. ASNs are notifications that undergo warehouse receipt verification.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button className="btn-sm btn-secondary" onClick={loadASNs} disabled={loading}>
            <RefreshCw size={13} className={loading ? 'spin' : ''} /> Refresh
          </button>
          <button className="btn-sm btn-primary-sm" onClick={() => setIsModalOpen(true)}>
            <Plus size={14} /> Create New ASN
          </button>
        </div>
      </div>

      {feedback && (
        <div className={feedback.type === 'success' ? 'clean-audit-card' : 'error-banner'} style={{ marginBottom: 16 }}>
          {feedback.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}
          <span>{feedback.message}</span>
        </div>
      )}

      {selectedASN ? (
        /* ASN Detail View */
        <div className="panel" style={{ background: 'var(--navy-950)', border: '1px solid var(--navy-800)', padding: 20, borderRadius: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, borderBottom: '1px solid var(--navy-800)', paddingBottom: 12 }}>
            <button className="btn-sm btn-secondary" onClick={() => setSelectedASN(null)}>
              <ArrowLeft size={14} /> Back to ASNs
            </button>
            <span className={`status-tag status-${selectedASN.status}`}>{selectedASN.status.toUpperCase()}</span>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 14, marginBottom: 20 }} className="fields-grid">
            <div className="field-cell"><small>ASN NUMBER</small><strong>{selectedASN.asn_number}</strong></div>
            <div className="field-cell"><small>PO NUMBER</small><strong>{selectedASN.po_number}</strong></div>
            <div className="field-cell"><small>DISPATCH REFERENCE</small><strong>{selectedASN.dispatch_reference}</strong></div>
            <div className="field-cell"><small>DISPATCH DATE</small><strong>{selectedASN.dispatch_date}</strong></div>
            <div className="field-cell"><small>EXPECTED ARRIVAL</small><strong>{selectedASN.expected_arrival_date}</strong></div>
            <div className="field-cell"><small>CARRIER / TRACKING</small><strong>{selectedASN.carrier_name || 'N/A'} {selectedASN.tracking_number ? `(${selectedASN.tracking_number})` : ''}</strong></div>
          </div>

          <h3 style={{ fontSize: 14, fontWeight: 700, margin: '16px 0 10px' }}>Dispatched Line Items</h3>
          <table className="portal-table" style={{ width: '100%', fontSize: 13 }}>
            <thead>
              <tr style={{ background: 'var(--navy-900)' }}>
                <th style={{ padding: 8 }}>SKU</th>
                <th style={{ padding: 8 }}>Product</th>
                <th style={{ padding: 8, textAlign: 'right' }}>Shipped Qty</th>
                <th style={{ padding: 8 }}>Package Label</th>
              </tr>
            </thead>
            <tbody>
              {selectedASN.items?.map((it) => (
                <tr key={it.id} style={{ borderBottom: '1px solid var(--navy-800)' }}>
                  <td style={{ padding: 8 }}><code>{it.sku}</code></td>
                  <td style={{ padding: 8 }}>{it.product_name}</td>
                  <td style={{ padding: 8, textAlign: 'right', fontWeight: 700, color: 'var(--teal-300)' }}>{it.shipped_qty} {it.uom}</td>
                  <td style={{ padding: 8 }}>{it.package_label || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        /* ASN List Table */
        <div>
          {asns.length === 0 ? (
            <div className="panel" style={{ padding: 40, textAlign: 'center', color: 'var(--slate-400)' }}>
              No Advance Shipment Notices created yet. Click "Create New ASN" to notify dispatch.
            </div>
          ) : (
            <table className="portal-table" style={{ width: '100%', fontSize: 13 }}>
              <thead>
                <tr style={{ background: 'var(--navy-900)' }}>
                  <th style={{ padding: 10 }}>ASN #</th>
                  <th style={{ padding: 10 }}>PO #</th>
                  <th style={{ padding: 10 }}>Dispatch Ref</th>
                  <th style={{ padding: 10 }}>Dispatch Date</th>
                  <th style={{ padding: 10 }}>ETA</th>
                  <th style={{ padding: 10 }}>Carrier</th>
                  <th style={{ padding: 10 }}>Status</th>
                  <th style={{ padding: 10, textAlign: 'right' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {asns.map((asn) => (
                  <tr key={asn.id} style={{ borderBottom: '1px solid var(--navy-800)' }}>
                    <td style={{ padding: 10 }}><strong>{asn.asn_number}</strong></td>
                    <td style={{ padding: 10 }}>{asn.po_number}</td>
                    <td style={{ padding: 10 }}>{asn.dispatch_reference}</td>
                    <td style={{ padding: 10 }}>{asn.dispatch_date}</td>
                    <td style={{ padding: 10 }}>{asn.expected_arrival_date}</td>
                    <td style={{ padding: 10 }}>{asn.carrier_name || '—'}</td>
                    <td style={{ padding: 10 }}><span className={`status-tag status-${asn.status}`}>{asn.status.toUpperCase()}</span></td>
                    <td style={{ padding: 10, textAlign: 'right' }}>
                      <button className="btn-sm btn-primary-sm" onClick={() => handleViewASNDetail(asn.id)}>
                        View Details
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Modal: Create New ASN */}
      {isModalOpen && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'grid', placeItems: 'center', zIndex: 1000, padding: 20 }}>
          <div className="panel" style={{ maxWidth: 640, width: '100%', maxHeight: '90vh', overflowY: 'auto', padding: 24, background: 'var(--navy-900)', border: '1px solid var(--teal-500)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
              <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 }}>
                <Truck size={18} color="var(--teal-400)" /> Create Advance Shipment Notice
              </h3>
              <button onClick={() => setIsModalOpen(false)} style={{ background: 'transparent', border: 'none', color: 'var(--slate-400)', cursor: 'pointer' }}>
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleCreateASN} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 4 }}>
                  Select Purchase Order *
                </label>
                <select
                  value={poId}
                  onChange={(e) => handlePOChange(e.target.value)}
                  required
                  style={{ width: '100%', padding: '8px 12px', borderRadius: 8, background: 'var(--navy-950)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
                >
                  <option value="">-- Choose Purchase Order --</option>
                  {supplierPOs.map((p) => (
                    <option key={p.id} value={p.id}>{p.po_number} ({p.status.toUpperCase()})</option>
                  ))}
                </select>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 4 }}>
                    Dispatch Reference *
                  </label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. DISPATCH-001"
                    value={dispatchRef}
                    onChange={(e) => setDispatchRef(e.target.value)}
                    style={{ width: '100%', padding: '8px 12px', borderRadius: 8, background: 'var(--navy-950)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 4 }}>
                    Package / Carton Count
                  </label>
                  <input
                    type="number"
                    min="1"
                    value={packageCount}
                    onChange={(e) => setPackageCount(e.target.value)}
                    style={{ width: '100%', padding: '8px 12px', borderRadius: 8, background: 'var(--navy-950)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
                  />
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 4 }}>
                    Dispatch Date *
                  </label>
                  <input
                    type="date"
                    required
                    value={dispatchDate}
                    onChange={(e) => setDispatchDate(e.target.value)}
                    style={{ width: '100%', padding: '8px 12px', borderRadius: 8, background: 'var(--navy-950)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 4 }}>
                    Expected Arrival Date *
                  </label>
                  <input
                    type="date"
                    required
                    value={arrivalDate}
                    onChange={(e) => setArrivalDate(e.target.value)}
                    style={{ width: '100%', padding: '8px 12px', borderRadius: 8, background: 'var(--navy-950)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
                  />
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 4 }}>
                    Carrier Name
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. FedEx Logistics"
                    value={carrierName}
                    onChange={(e) => setCarrierName(e.target.value)}
                    style={{ width: '100%', padding: '8px 12px', borderRadius: 8, background: 'var(--navy-950)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 4 }}>
                    Tracking Number
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. TRK-481923"
                    value={trackingNumber}
                    onChange={(e) => setTrackingNumber(e.target.value)}
                    style={{ width: '100%', padding: '8px 12px', borderRadius: 8, background: 'var(--navy-950)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
                  />
                </div>
              </div>

              {/* Line Items for Shipped Quantities */}
              {poDetail && (
                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>
                    Dispatched Quantities by Line Item
                  </label>
                  <div style={{ background: 'var(--navy-950)', borderRadius: 8, padding: 12, border: '1px solid var(--navy-800)' }}>
                    {poDetail.items?.map((item) => {
                      const remaining = Math.max(0, (item.ordered_qty || 0) - (item.received_qty || 0))
                      return (
                        <div key={item.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--navy-800)', fontSize: 12 }}>
                          <div>
                            <strong>{item.sku}</strong> — {item.product_name}
                            <div style={{ color: 'var(--slate-400)' }}>Remaining: {remaining} {item.uom}</div>
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <input
                              type="number"
                              min="0"
                              max={remaining}
                              step="any"
                              value={shippedQuantities[item.id] ?? ''}
                              onChange={(e) => setShippedQuantities({ ...shippedQuantities, [item.id]: e.target.value })}
                              style={{ width: 80, padding: '4px 8px', borderRadius: 6, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff', textAlign: 'right' }}
                            />
                            <span style={{ color: 'var(--slate-400)', width: 30 }}>{item.uom}</span>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 4 }}>
                  Notes / Dispatch Remarks
                </label>
                <textarea
                  rows={2}
                  placeholder="Additional dispatch notes..."
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  style={{ width: '100%', padding: '8px 12px', borderRadius: 8, background: 'var(--navy-950)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
                />
              </div>

              <div style={{ display: 'flex', gap: 10, marginTop: 10 }}>
                <button type="submit" className="primary-button" style={{ flex: 1 }} disabled={creating}>
                  {creating ? 'Submitting...' : 'Submit ASN'}
                </button>
                <button type="button" className="btn-sm btn-secondary" onClick={() => setIsModalOpen(false)}>
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

// ============================================================================
// 3. SUPPLIER DOCUMENT SUBMISSIONS SECTION
// ============================================================================

export function SupplierDocumentsSection({ supplierSession, supplierPOs, asns }) {
  const [docs, setDocs] = useState([])
  const [loading, setLoading] = useState(false)
  const [feedback, setFeedback] = useState(null)

  // Upload state
  const [file, setFile] = useState(null)
  const [selectedPOId, setSelectedPOId] = useState('')
  const [selectedASNId, setSelectedASNId] = useState('')
  const [uploadNotes, setUploadNotes] = useState('')
  const [uploading, setUploading] = useState(false)

  useEffect(() => {
    if (supplierSession?.access_token) {
      loadDocs()
    }
  }, [supplierSession])

  async function loadDocs() {
    setLoading(true)
    try {
      const data = await apiFetch('/api/portal/supplier/documents', {
        headers: { Authorization: `Bearer ${supplierSession.access_token}` },
      })
      setDocs(data.items || [])
    } catch (err) {
      setFeedback({ type: 'error', message: err.detail || 'Failed to load supplier documents.' })
    } finally {
      setLoading(false)
    }
  }

  async function handleUpload(e) {
    if (e) e.preventDefault()
    if (!file) {
      setFeedback({ type: 'error', message: 'Please select a file to upload.' })
      return
    }

    setUploading(true)
    setFeedback(null)

    try {
      const formData = new FormData()
      formData.append('file', file)
      if (selectedPOId) formData.append('po_id', selectedPOId)
      if (selectedASNId) formData.append('asn_id', selectedASNId)
      if (uploadNotes) formData.append('notes', uploadNotes.trim())

      const res = await fetch(`${API_BASE}/api/portal/supplier/documents/upload`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${supplierSession.access_token}`,
        },
        body: formData,
      })

      if (!res.ok) {
        const errorJson = await res.json().catch(() => ({}))
        throw new Error(errorJson.detail || 'Upload failed.')
      }

      setFeedback({ type: 'success', message: `File "${file.name}" uploaded successfully. It is now in pending review status.` })
      setFile(null)
      setSelectedPOId('')
      setSelectedASNId('')
      setUploadNotes('')
      loadDocs()
    } catch (err) {
      setFeedback({ type: 'error', message: err.message || 'Upload error.' })
    } finally {
      setUploading(false)
    }
  }

  async function handleDownload(docId, filename) {
    try {
      const res = await fetch(`${API_BASE}/api/portal/documents/${docId}/download`, {
        headers: { Authorization: `Bearer ${supplierSession.access_token}` },
      })
      if (!res.ok) throw new Error('Download failed or not authorized.')
      const blob = await res.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename || 'document'
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch (err) {
      setFeedback({ type: 'error', message: err.message })
    }
  }

  return (
    <div className="panel" style={{ padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20, borderBottom: '1px solid var(--navy-800)', paddingBottom: 14 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 10 }}>
            <FileUp size={18} color="var(--teal-400)" /> Supplier Document Submissions
          </h2>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--slate-400)' }}>
            Securely upload invoices, packing lists, dispatch notes, and certificates. All uploads enter a pending review state.
          </p>
        </div>
        <button className="btn-sm btn-secondary" onClick={loadDocs} disabled={loading}>
          <RefreshCw size={13} className={loading ? 'spin' : ''} /> Refresh
        </button>
      </div>

      {feedback && (
        <div className={feedback.type === 'success' ? 'clean-audit-card' : 'error-banner'} style={{ marginBottom: 16 }}>
          {feedback.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}
          <span>{feedback.message}</span>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '360px 1fr', gap: 24 }}>
        {/* Upload Form */}
        <div className="panel" style={{ background: 'var(--navy-950)', border: '1px solid var(--navy-800)', padding: 20, borderRadius: 10 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 16px', display: 'flex', alignItems: 'center', gap: 8 }}>
            <Upload size={16} color="var(--teal-300)" /> Upload New Document
          </h3>
          <form onSubmit={handleUpload} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 4 }}>
                File (PDF, TXT, DOCX, PNG, JPG) *
              </label>
              <input
                type="file"
                required
                accept=".pdf,.txt,.docx,.png,.jpg,.jpeg"
                onChange={(e) => setFile(e.target.files[0] || null)}
                style={{ width: '100%', fontSize: 12, color: 'var(--slate-300)' }}
              />
              <small style={{ color: 'var(--slate-400)', fontSize: 11, display: 'block', marginTop: 4 }}>Max 25 MB. Magic bytes validated.</small>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 4 }}>
                Related Purchase Order (Optional)
              </label>
              <select
                value={selectedPOId}
                onChange={(e) => setSelectedPOId(e.target.value)}
                style={{ width: '100%', padding: '8px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
              >
                <option value="">-- No PO link --</option>
                {supplierPOs.map((p) => (
                  <option key={p.id} value={p.id}>{p.po_number}</option>
                ))}
              </select>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 4 }}>
                Related ASN (Optional)
              </label>
              <select
                value={selectedASNId}
                onChange={(e) => setSelectedASNId(e.target.value)}
                style={{ width: '100%', padding: '8px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
              >
                <option value="">-- No ASN link --</option>
                {asns?.map((a) => (
                  <option key={a.id} value={a.id}>{a.asn_number} ({a.dispatch_reference})</option>
                ))}
              </select>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 4 }}>
                Document Notes / Description
              </label>
              <textarea
                rows={2}
                placeholder="e.g. Commercial invoice and certificate of origin..."
                value={uploadNotes}
                onChange={(e) => setUploadNotes(e.target.value)}
                style={{ width: '100%', padding: '8px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
              />
            </div>

            <button type="submit" className="primary-button" disabled={uploading}>
              {uploading ? 'Uploading...' : 'Upload Document'}
            </button>
          </form>
        </div>

        {/* Documents Table */}
        <div>
          <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 16px' }}>Uploaded Documents</h3>
          {docs.length === 0 ? (
            <div className="panel" style={{ padding: 40, textAlign: 'center', color: 'var(--slate-400)', background: 'var(--navy-950)' }}>
              No documents uploaded yet.
            </div>
          ) : (
            <table className="portal-table" style={{ width: '100%', fontSize: 13 }}>
              <thead>
                <tr style={{ background: 'var(--navy-900)' }}>
                  <th style={{ padding: 8 }}>Filename</th>
                  <th style={{ padding: 8 }}>Type</th>
                  <th style={{ padding: 8 }}>Size</th>
                  <th style={{ padding: 8 }}>Review Status</th>
                  <th style={{ padding: 8 }}>Uploaded</th>
                  <th style={{ padding: 8, textAlign: 'right' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {docs.map((d) => (
                  <tr key={d.id} style={{ borderBottom: '1px solid var(--navy-800)' }}>
                    <td style={{ padding: 8 }}>
                      <strong>{d.original_filename}</strong>
                      {d.notes && <div style={{ fontSize: 11, color: 'var(--slate-400)' }}>{d.notes}</div>}
                    </td>
                    <td style={{ padding: 8 }}>{d.document_type}</td>
                    <td style={{ padding: 8 }}>{(d.file_size / 1024).toFixed(1)} KB</td>
                    <td style={{ padding: 8 }}>
                      <span className={`status-tag status-${d.review_status}`}>{d.review_status?.toUpperCase()}</span>
                    </td>
                    <td style={{ padding: 8 }}>{new Date(d.created_at).toLocaleDateString()}</td>
                    <td style={{ padding: 8, textAlign: 'right' }}>
                      <button className="btn-sm btn-secondary" onClick={() => handleDownload(d.id, d.original_filename)}>
                        <Download size={13} /> Download
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

// ============================================================================
// 4. DELIVERY DISCREPANCY WORKFLOW SECTION
// ============================================================================

export function SupplierDiscrepanciesSection({ supplierSession, supplierPOs, asns }) {
  const [discrepancies, setDiscrepancies] = useState([])
  const [selectedDiscrepancy, setSelectedDiscrepancy] = useState(null)
  const [loading, setLoading] = useState(false)
  const [feedback, setFeedback] = useState(null)

  // Report modal state
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [poId, setPoId] = useState('')
  const [asnId, setAsnId] = useState('')
  const [category, setCategory] = useState('short_shipment')
  const [description, setDescription] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // Reply message state
  const [replyText, setReplyText] = useState('')
  const [replying, setReplying] = useState(false)

  useEffect(() => {
    if (supplierSession?.access_token) {
      loadDiscrepancies()
    }
  }, [supplierSession])

  async function loadDiscrepancies() {
    setLoading(true)
    try {
      const data = await apiFetch('/api/portal/supplier/discrepancies', {
        headers: { Authorization: `Bearer ${supplierSession.access_token}` },
      })
      setDiscrepancies(data.items || [])
    } catch (err) {
      setFeedback({ type: 'error', message: err.detail || 'Failed to load discrepancies.' })
    } finally {
      setLoading(false)
    }
  }

  async function handleCreateDiscrepancy(e) {
    if (e) e.preventDefault()
    setSubmitting(true)
    setFeedback(null)

    try {
      const payload = {
        po_id: poId,
        asn_id: asnId || null,
        category,
        description: description.trim(),
      }

      await apiFetch('/api/portal/supplier/discrepancies', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${supplierSession.access_token}`,
        },
        body: JSON.stringify(payload),
      }, 'Failed to report discrepancy')

      setFeedback({ type: 'success', message: 'Discrepancy reported successfully. Internal staff will review shortly.' })
      setIsModalOpen(false)
      setPoId('')
      setAsnId('')
      setDescription('')
      loadDiscrepancies()
    } catch (err) {
      setFeedback({ type: 'error', message: err.detail || 'Error submitting discrepancy.' })
    } finally {
      setSubmitting(false)
    }
  }

  async function handleViewDetail(id) {
    try {
      const data = await apiFetch(`/api/portal/supplier/discrepancies/${id}`, {
        headers: { Authorization: `Bearer ${supplierSession.access_token}` },
      })
      setSelectedDiscrepancy(data)
    } catch (err) {
      setFeedback({ type: 'error', message: 'Could not load discrepancy detail.' })
    }
  }

  async function handleSendReply(e) {
    if (e) e.preventDefault()
    if (!replyText.trim() || !selectedDiscrepancy) return
    setReplying(true)

    try {
      await apiFetch(`/api/portal/supplier/discrepancies/${selectedDiscrepancy.id}/messages`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${supplierSession.access_token}`,
        },
        body: JSON.stringify({ message: replyText.trim() }),
      }, 'Failed to send message')

      setReplyText('')
      handleViewDetail(selectedDiscrepancy.id)
    } catch (err) {
      setFeedback({ type: 'error', message: err.detail || 'Could not send message.' })
    } finally {
      setReplying(false)
    }
  }

  return (
    <div className="panel" style={{ padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20, borderBottom: '1px solid var(--navy-800)', paddingBottom: 14 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 10 }}>
            <AlertTriangle size={18} color="var(--amber-400)" /> Delivery Discrepancies &amp; Incident Reports
          </h2>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--slate-400)' }}>
            Report and track delivery issues (shortages, damage, delays). Discrepancy reporting never mutates inventory directly.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button className="btn-sm btn-secondary" onClick={loadDiscrepancies} disabled={loading}>
            <RefreshCw size={13} className={loading ? 'spin' : ''} /> Refresh
          </button>
          <button className="btn-sm btn-primary-sm" onClick={() => setIsModalOpen(true)}>
            <Plus size={14} /> Report Discrepancy
          </button>
        </div>
      </div>

      {feedback && (
        <div className={feedback.type === 'success' ? 'clean-audit-card' : 'error-banner'} style={{ marginBottom: 16 }}>
          {feedback.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}
          <span>{feedback.message}</span>
        </div>
      )}

      {selectedDiscrepancy ? (
        /* Discrepancy Detail & Discussion Thread */
        <div className="panel" style={{ background: 'var(--navy-950)', border: '1px solid var(--navy-800)', padding: 20, borderRadius: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, borderBottom: '1px solid var(--navy-800)', paddingBottom: 12 }}>
            <button className="btn-sm btn-secondary" onClick={() => setSelectedDiscrepancy(null)}>
              <ArrowLeft size={14} /> Back to Discrepancies
            </button>
            <span className={`status-tag status-${selectedDiscrepancy.status}`}>{selectedDiscrepancy.status.toUpperCase()}</span>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 14, marginBottom: 20 }} className="fields-grid">
            <div className="field-cell"><small>CATEGORY</small><strong>{selectedDiscrepancy.category}</strong></div>
            <div className="field-cell"><small>PO NUMBER</small><strong>{selectedDiscrepancy.po_number}</strong></div>
            <div className="field-cell"><small>REPORTED DATE</small><strong>{new Date(selectedDiscrepancy.created_at).toLocaleString()}</strong></div>
          </div>

          <div style={{ background: 'var(--navy-900)', padding: 14, borderRadius: 8, marginBottom: 20, border: '1px solid var(--navy-800)' }}>
            <small style={{ color: 'var(--slate-400)', display: 'block', marginBottom: 4 }}>INITIAL REPORT</small>
            <p style={{ margin: 0, fontSize: 13 }}>{selectedDiscrepancy.description}</p>
          </div>

          {/* Conversation Thread */}
          <h3 style={{ fontSize: 14, fontWeight: 700, margin: '16px 0 10px', display: 'flex', alignItems: 'center', gap: 8 }}>
            <MessageSquare size={16} color="var(--teal-300)" /> Discussion Thread
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 20 }}>
            {selectedDiscrepancy.messages?.length === 0 ? (
              <div style={{ color: 'var(--slate-400)', fontSize: 13, fontStyle: 'italic' }}>No discussion messages yet.</div>
            ) : (
              selectedDiscrepancy.messages?.map((msg) => (
                <div
                  key={msg.id}
                  style={{
                    padding: '10px 14px',
                    borderRadius: 8,
                    background: msg.sender_type === 'supplier' ? 'rgba(20, 184, 166, 0.1)' : 'var(--navy-900)',
                    border: '1px solid ' + (msg.sender_type === 'supplier' ? 'var(--teal-700)' : 'var(--navy-800)'),
                    alignSelf: msg.sender_type === 'supplier' ? 'flex-end' : 'flex-start',
                    maxWidth: '80%',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 4 }}>
                    <strong style={{ fontSize: 12, color: msg.sender_type === 'supplier' ? 'var(--teal-300)' : 'var(--blue-300)' }}>
                      {msg.sender_type.toUpperCase()}
                    </strong>
                    <small style={{ color: 'var(--slate-400)', fontSize: 10 }}>{new Date(msg.created_at).toLocaleString()}</small>
                  </div>
                  <div style={{ fontSize: 13 }}>{msg.message}</div>
                </div>
              ))
            )}
          </div>

          {/* Reply Form (only allowed if not resolved/rejected) */}
          {selectedDiscrepancy.status !== 'resolved' && selectedDiscrepancy.status !== 'rejected' ? (
            <form onSubmit={handleSendReply} style={{ display: 'flex', gap: 10 }}>
              <input
                type="text"
                placeholder="Type a response or clarification..."
                value={replyText}
                onChange={(e) => setReplyText(e.target.value)}
                style={{ flex: 1, padding: '8px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
              />
              <button type="submit" className="primary-button" disabled={replying || !replyText.trim()}>
                <Send size={14} /> Send
              </button>
            </form>
          ) : (
            <div style={{ padding: 10, background: 'var(--navy-900)', borderRadius: 8, color: 'var(--slate-400)', fontSize: 12, textAlign: 'center' }}>
              This discrepancy has been marked as <strong>{selectedDiscrepancy.status.toUpperCase()}</strong>. Discussion is closed.
            </div>
          )}
        </div>
      ) : (
        /* Discrepancies List */
        <div>
          {discrepancies.length === 0 ? (
            <div className="panel" style={{ padding: 40, textAlign: 'center', color: 'var(--slate-400)' }}>
              No discrepancies reported. Everything is running smoothly!
            </div>
          ) : (
            <table className="portal-table" style={{ width: '100%', fontSize: 13 }}>
              <thead>
                <tr style={{ background: 'var(--navy-900)' }}>
                  <th style={{ padding: 10 }}>Category</th>
                  <th style={{ padding: 10 }}>PO #</th>
                  <th style={{ padding: 10 }}>Description</th>
                  <th style={{ padding: 10 }}>Reported Date</th>
                  <th style={{ padding: 10 }}>Status</th>
                  <th style={{ padding: 10, textAlign: 'right' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {discrepancies.map((d) => (
                  <tr key={d.id} style={{ borderBottom: '1px solid var(--navy-800)' }}>
                    <td style={{ padding: 10 }}><strong>{d.category}</strong></td>
                    <td style={{ padding: 10 }}>{d.po_number}</td>
                    <td style={{ padding: 10, maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {d.description}
                    </td>
                    <td style={{ padding: 10 }}>{new Date(d.created_at).toLocaleDateString()}</td>
                    <td style={{ padding: 10 }}><span className={`status-tag status-${d.status}`}>{d.status.toUpperCase()}</span></td>
                    <td style={{ padding: 10, textAlign: 'right' }}>
                      <button className="btn-sm btn-primary-sm" onClick={() => handleViewDetail(d.id)}>
                        View &amp; Thread
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Modal: Report Discrepancy */}
      {isModalOpen && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'grid', placeItems: 'center', zIndex: 1000, padding: 20 }}>
          <div className="panel" style={{ maxWidth: 540, width: '100%', padding: 24, background: 'var(--navy-900)', border: '1px solid var(--amber-500)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
              <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 }}>
                <AlertTriangle size={18} color="var(--amber-400)" /> Report Delivery Discrepancy
              </h3>
              <button onClick={() => setIsModalOpen(false)} style={{ background: 'transparent', border: 'none', color: 'var(--slate-400)', cursor: 'pointer' }}>
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleCreateDiscrepancy} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 4 }}>
                  Related Purchase Order *
                </label>
                <select
                  value={poId}
                  onChange={(e) => setPoId(e.target.value)}
                  required
                  style={{ width: '100%', padding: '8px 12px', borderRadius: 8, background: 'var(--navy-950)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
                >
                  <option value="">-- Choose Purchase Order --</option>
                  {supplierPOs.map((p) => (
                    <option key={p.id} value={p.id}>{p.po_number}</option>
                  ))}
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 4 }}>
                  Discrepancy Category *
                </label>
                <select
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  style={{ width: '100%', padding: '8px 12px', borderRadius: 8, background: 'var(--navy-950)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
                >
                  <option value="short_shipment">Short Shipment (Fewer units received)</option>
                  <option value="damaged_goods">Damaged Goods in Transit</option>
                  <option value="delayed_shipment">Delayed Shipment / Logistics Bottleneck</option>
                  <option value="expected_quantity_discrepancy">Expected Quantity Mismatch</option>
                  <option value="incorrect_product">Incorrect Product / Wrong SKU</option>
                  <option value="missing_documentation">Missing / Incorrect Documentation</option>
                  <option value="other">Other Issue</option>
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 4 }}>
                  Detailed Description *
                </label>
                <textarea
                  rows={4}
                  required
                  placeholder="Provide precise details of the discrepancy, affected batch numbers, or missing items..."
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  style={{ width: '100%', padding: '8px 12px', borderRadius: 8, background: 'var(--navy-950)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
                />
              </div>

              <div style={{ display: 'flex', gap: 10, marginTop: 10 }}>
                <button type="submit" className="primary-button" style={{ flex: 1 }} disabled={submitting}>
                  {submitting ? 'Submitting...' : 'Submit Incident Report'}
                </button>
                <button type="button" className="btn-sm btn-secondary" onClick={() => setIsModalOpen(false)}>
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

// ============================================================================
// 5. INTERNAL STAFF REVIEW CONSOLE
// ============================================================================

export function StaffReviewConsole({ currentRole = 'procurement', currentUser = 'Staff Operator' }) {
  const [activeTab, setActiveTab] = useState('commitments') // 'commitments' | 'asns' | 'documents' | 'discrepancies'
  const [role, setRole] = useState(currentRole)

  // Data states
  const [commitments, setCommitments] = useState([])
  const [asns, setAsns] = useState([])
  const [documents, setDocuments] = useState([])
  const [discrepancies, setDiscrepancies] = useState([])
  const [loading, setLoading] = useState(false)
  const [feedback, setFeedback] = useState(null)

  // Modal / Review action state
  const [actionItem, setActionItem] = useState(null)
  const [actionType, setActionType] = useState('approve') // 'approve' | 'reject' | 'acknowledge' | 'resolve'
  const [reason, setReason] = useState('')
  const [internalNotes, setInternalNotes] = useState('')
  const [supplierResponse, setSupplierResponse] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const staffHeaders = {
    'X-User-Role': role,
    'X-User-Name': currentUser,
  }

  useEffect(() => {
    loadStaffData()
  }, [activeTab, role])

  async function loadStaffData() {
    setLoading(true)
    setFeedback(null)
    try {
      if (activeTab === 'commitments') {
        const data = await apiFetch('/api/portal/admin/commitments?status=pending_review', { headers: staffHeaders })
        setCommitments(data.items || [])
      } else if (activeTab === 'asns') {
        const data = await apiFetch('/api/portal/admin/asns', { headers: staffHeaders })
        setAsns(data.items || [])
      } else if (activeTab === 'documents') {
        const data = await apiFetch('/api/portal/admin/supplier-documents?review_status=pending_review', { headers: staffHeaders })
        setDocuments(data.items || [])
      } else if (activeTab === 'discrepancies') {
        const data = await apiFetch('/api/portal/admin/discrepancies', { headers: staffHeaders })
        setDiscrepancies(data.items || [])
      }
    } catch (err) {
      setFeedback({ type: 'error', message: err.detail || 'Access denied or failed to load staff console queue.' })
    } finally {
      setLoading(false)
    }
  }

  async function handleReviewCommitment(comId, status) {
    setSubmitting(true)
    try {
      await apiFetch(`/api/portal/admin/commitments/${comId}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...staffHeaders },
        body: JSON.stringify({
          action: status,
          internal_reason: reason.trim() || `Reviewed and ${status} by ${currentUser}`,
        }),
      })
      setFeedback({ type: 'success', message: `Commitment successfully ${status}.` })
      setActionItem(null)
      setReason('')
      loadStaffData()
    } catch (err) {
      setFeedback({ type: 'error', message: err.detail || 'Failed to review commitment.' })
    } finally {
      setSubmitting(false)
    }
  }

  async function handleAcknowledgeASN(asnId) {
    setSubmitting(true)
    try {
      await apiFetch(`/api/portal/admin/asns/${asnId}/acknowledge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...staffHeaders },
        body: JSON.stringify({ notes: reason.trim() || 'Acknowledged by warehouse/procurement.' }),
      })
      setFeedback({ type: 'success', message: 'ASN acknowledged successfully.' })
      setActionItem(null)
      setReason('')
      loadStaffData()
    } catch (err) {
      setFeedback({ type: 'error', message: err.detail || 'Failed to acknowledge ASN.' })
    } finally {
      setSubmitting(false)
    }
  }

  async function handleReviewDocument(docId, status) {
    setSubmitting(true)
    try {
      await apiFetch(`/api/portal/admin/supplier-documents/${docId}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...staffHeaders },
        body: JSON.stringify({
          action: status,
          comments: reason.trim() || `Document ${status} by staff.`,
        }),
      })
      setFeedback({ type: 'success', message: `Document marked as ${status}.` })
      setActionItem(null)
      setReason('')
      loadStaffData()
    } catch (err) {
      setFeedback({ type: 'error', message: err.detail || 'Failed to review document.' })
    } finally {
      setSubmitting(false)
    }
  }

  async function handleResolveDiscrepancy(discId, status) {
    setSubmitting(true)
    try {
      await apiFetch(`/api/portal/admin/discrepancies/${discId}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...staffHeaders },
        body: JSON.stringify({
          status,
          internal_notes: internalNotes.trim() || null,
          supplier_response: supplierResponse.trim() || null,
        }),
      })
      setFeedback({ type: 'success', message: `Discrepancy transitioned to ${status}.` })
      setActionItem(null)
      setInternalNotes('')
      setSupplierResponse('')
      loadStaffData()
    } catch (err) {
      setFeedback({ type: 'error', message: err.detail || 'Failed to transition discrepancy.' })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="panel" style={{ padding: 24 }}>
      {/* Console Header Bar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20, borderBottom: '1px solid var(--navy-800)', paddingBottom: 14 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 10 }}>
            <ShieldCheck size={20} color="var(--teal-400)" /> Internal Staff Collaboration Console
          </h2>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--slate-400)' }}>
            Authoritative internal review queues for supplier delivery commitments, ASNs, document approvals, and discrepancy resolutions.
          </p>
        </div>

        {/* Staff Role Emulation Bar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 12, color: 'var(--slate-400)' }}>Active Staff Role:</span>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            style={{ padding: '6px 10px', borderRadius: 6, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 12 }}
          >
            <option value="procurement">Procurement Officer</option>
            <option value="admin">Administrator</option>
            <option value="warehouse">Warehouse Specialist</option>
            <option value="manager">Operations Manager</option>
          </select>
          <button className="btn-sm btn-secondary" onClick={loadStaffData} disabled={loading}>
            <RefreshCw size={13} className={loading ? 'spin' : ''} />
          </button>
        </div>
      </div>

      {feedback && (
        <div className={feedback.type === 'success' ? 'clean-audit-card' : 'error-banner'} style={{ marginBottom: 16 }}>
          {feedback.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}
          <span>{feedback.message}</span>
        </div>
      )}

      {/* Subtab Navigation */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        <button
          className={`btn-sm ${activeTab === 'commitments' ? 'btn-primary-sm' : 'btn-secondary'}`}
          onClick={() => setActiveTab('commitments')}
        >
          <Calendar size={14} /> Pending Commitments
        </button>
        <button
          className={`btn-sm ${activeTab === 'asns' ? 'btn-primary-sm' : 'btn-secondary'}`}
          onClick={() => setActiveTab('asns')}
        >
          <Truck size={14} /> ASNs
        </button>
        <button
          className={`btn-sm ${activeTab === 'documents' ? 'btn-primary-sm' : 'btn-secondary'}`}
          onClick={() => setActiveTab('documents')}
        >
          <FileUp size={14} /> Supplier Documents
        </button>
        <button
          className={`btn-sm ${activeTab === 'discrepancies' ? 'btn-primary-sm' : 'btn-secondary'}`}
          onClick={() => setActiveTab('discrepancies')}
        >
          <AlertTriangle size={14} /> Discrepancies Queue
        </button>
      </div>

      {/* Tab 1: Commitments */}
      {activeTab === 'commitments' && (
        <div>
          {commitments.length === 0 ? (
            <div className="panel" style={{ padding: 30, textAlign: 'center', color: 'var(--slate-400)', background: 'var(--navy-950)' }}>
              No commitments pending internal staff review.
            </div>
          ) : (
            <table className="portal-table" style={{ width: '100%', fontSize: 13 }}>
              <thead>
                <tr style={{ background: 'var(--navy-900)' }}>
                  <th style={{ padding: 10 }}>PO #</th>
                  <th style={{ padding: 10 }}>Supplier</th>
                  <th style={{ padding: 10 }}>Proposed Date</th>
                  <th style={{ padding: 10 }}>Dispatch Ref</th>
                  <th style={{ padding: 10 }}>Comments</th>
                  <th style={{ padding: 10, textAlign: 'right' }}>Review Action</th>
                </tr>
              </thead>
              <tbody>
                {commitments.map((com) => (
                  <tr key={com.id} style={{ borderBottom: '1px solid var(--navy-800)' }}>
                    <td style={{ padding: 10 }}><strong>{com.po_number}</strong></td>
                    <td style={{ padding: 10 }}>{com.supplier_name}</td>
                    <td style={{ padding: 10 }}>{com.proposed_delivery_date || '—'}</td>
                    <td style={{ padding: 10 }}>{com.dispatch_reference || '—'}</td>
                    <td style={{ padding: 10 }}>{com.supplier_comments || '—'}</td>
                    <td style={{ padding: 10, textAlign: 'right' }}>
                      <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                        <button
                          className="btn-sm btn-primary-sm"
                          onClick={() => handleReviewCommitment(com.id, 'approved')}
                          disabled={submitting}
                        >
                          <Check size={13} /> Approve
                        </button>
                        <button
                          className="btn-sm btn-secondary"
                          onClick={() => handleReviewCommitment(com.id, 'rejected')}
                          disabled={submitting}
                          style={{ color: 'var(--rose-400)' }}
                        >
                          <X size={13} /> Reject
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Tab 2: ASNs */}
      {activeTab === 'asns' && (
        <div>
          {asns.length === 0 ? (
            <div className="panel" style={{ padding: 30, textAlign: 'center', color: 'var(--slate-400)', background: 'var(--navy-950)' }}>
              No advance shipment notices in the queue.
            </div>
          ) : (
            <table className="portal-table" style={{ width: '100%', fontSize: 13 }}>
              <thead>
                <tr style={{ background: 'var(--navy-900)' }}>
                  <th style={{ padding: 10 }}>ASN #</th>
                  <th style={{ padding: 10 }}>PO #</th>
                  <th style={{ padding: 10 }}>Supplier</th>
                  <th style={{ padding: 10 }}>Dispatch Date</th>
                  <th style={{ padding: 10 }}>ETA</th>
                  <th style={{ padding: 10 }}>Status</th>
                  <th style={{ padding: 10, textAlign: 'right' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {asns.map((asn) => (
                  <tr key={asn.id} style={{ borderBottom: '1px solid var(--navy-800)' }}>
                    <td style={{ padding: 10 }}><strong>{asn.asn_number}</strong></td>
                    <td style={{ padding: 10 }}>{asn.po_number}</td>
                    <td style={{ padding: 10 }}>{asn.supplier_name}</td>
                    <td style={{ padding: 10 }}>{asn.dispatch_date}</td>
                    <td style={{ padding: 10 }}>{asn.expected_arrival_date}</td>
                    <td style={{ padding: 10 }}><span className={`status-tag status-${asn.status}`}>{asn.status.toUpperCase()}</span></td>
                    <td style={{ padding: 10, textAlign: 'right' }}>
                      {asn.status === 'submitted' && (
                        <button
                          className="btn-sm btn-primary-sm"
                          onClick={() => handleAcknowledgeASN(asn.id)}
                          disabled={submitting}
                        >
                          <Check size={13} /> Acknowledge ASN
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Tab 3: Documents */}
      {activeTab === 'documents' && (
        <div>
          {documents.length === 0 ? (
            <div className="panel" style={{ padding: 30, textAlign: 'center', color: 'var(--slate-400)', background: 'var(--navy-950)' }}>
              No supplier documents pending review.
            </div>
          ) : (
            <table className="portal-table" style={{ width: '100%', fontSize: 13 }}>
              <thead>
                <tr style={{ background: 'var(--navy-900)' }}>
                  <th style={{ padding: 10 }}>Filename</th>
                  <th style={{ padding: 10 }}>Supplier</th>
                  <th style={{ padding: 10 }}>Size</th>
                  <th style={{ padding: 10 }}>Notes</th>
                  <th style={{ padding: 10, textAlign: 'right' }}>Review Action</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((doc) => (
                  <tr key={doc.id} style={{ borderBottom: '1px solid var(--navy-800)' }}>
                    <td style={{ padding: 10 }}><strong>{doc.original_filename}</strong></td>
                    <td style={{ padding: 10 }}>{doc.supplier_name}</td>
                    <td style={{ padding: 10 }}>{(doc.file_size / 1024).toFixed(1)} KB</td>
                    <td style={{ padding: 10 }}>{doc.notes || '—'}</td>
                    <td style={{ padding: 10, textAlign: 'right' }}>
                      <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                        <button
                          className="btn-sm btn-primary-sm"
                          onClick={() => handleReviewDocument(doc.id, 'approved')}
                          disabled={submitting}
                        >
                          <Check size={13} /> Approve
                        </button>
                        <button
                          className="btn-sm btn-secondary"
                          onClick={() => handleReviewDocument(doc.id, 'rejected')}
                          disabled={submitting}
                          style={{ color: 'var(--rose-400)' }}
                        >
                          <X size={13} /> Reject
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Tab 4: Discrepancies */}
      {activeTab === 'discrepancies' && (
        <div>
          {discrepancies.length === 0 ? (
            <div className="panel" style={{ padding: 30, textAlign: 'center', color: 'var(--slate-400)', background: 'var(--navy-950)' }}>
              No discrepancies in the staff review queue.
            </div>
          ) : (
            <table className="portal-table" style={{ width: '100%', fontSize: 13 }}>
              <thead>
                <tr style={{ background: 'var(--navy-900)' }}>
                  <th style={{ padding: 10 }}>Category</th>
                  <th style={{ padding: 10 }}>PO #</th>
                  <th style={{ padding: 10 }}>Supplier</th>
                  <th style={{ padding: 10 }}>Status</th>
                  <th style={{ padding: 10, textAlign: 'right' }}>Resolution Actions</th>
                </tr>
              </thead>
              <tbody>
                {discrepancies.map((disc) => (
                  <tr key={disc.id} style={{ borderBottom: '1px solid var(--navy-800)' }}>
                    <td style={{ padding: 10 }}>
                      <strong>{disc.category}</strong>
                      <div style={{ fontSize: 11, color: 'var(--slate-400)' }}>{disc.description}</div>
                    </td>
                    <td style={{ padding: 10 }}>{disc.po_number}</td>
                    <td style={{ padding: 10 }}>{disc.supplier_name}</td>
                    <td style={{ padding: 10 }}><span className={`status-tag status-${disc.status}`}>{disc.status.toUpperCase()}</span></td>
                    <td style={{ padding: 10, textAlign: 'right' }}>
                      <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                        {disc.status === 'open' && (
                          <button
                            className="btn-sm btn-secondary"
                            onClick={() => handleResolveDiscrepancy(disc.id, 'under_review')}
                            disabled={submitting}
                          >
                            Mark In Review
                          </button>
                        )}
                        {(disc.status === 'open' || disc.status === 'under_review') && (
                          <button
                            className="btn-sm btn-primary-sm"
                            onClick={() => handleResolveDiscrepancy(disc.id, 'resolved')}
                            disabled={submitting}
                          >
                            <Check size={13} /> Resolve
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
