import { useEffect, useState } from 'react'
import {
  AlertTriangle,
  ArrowLeft,
  Building2,
  Calendar,
  Check,
  CheckCircle2,
  Clock,
  Download,
  Eye,
  FileCheck2,
  FileText,
  Filter,
  Lock,
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
  X,
  XCircle,
} from 'lucide-react'
import { apiFetch, API_BASE } from './api'

// Helper for authorized document downloads
async function downloadAuthorizedDocument(docId, filename, token) {
  try {
    const res = await fetch(`${API_BASE}/api/portal/documents/${docId}/download`, {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      alert(err.detail || 'Failed to download document or access revoked.')
      return
    }
    const blob = await res.blob()
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename || `document_${docId}.pdf`
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.URL.revokeObjectURL(url)
  } catch (err) {
    alert(`Download error: ${err.message}`)
  }
}

// ============================================================================
// 1. CUSTOMER ORDER COMMUNICATION THREADS SECTION
// ============================================================================

export function CustomerThreadsSection({ customerSession, customerSOs }) {
  const [threads, setThreads] = useState([])
  const [selectedThread, setSelectedThread] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [feedback, setFeedback] = useState(null)

  // New Thread Form Modal
  const [isNewThreadOpen, setIsNewThreadOpen] = useState(false)
  const [selectedSOId, setSelectedSOId] = useState('')
  const [subject, setSubject] = useState('')
  const [initialMessage, setInitialMessage] = useState('')
  const [submittingThread, setSubmittingThread] = useState(false)

  // Reply state
  const [replyText, setReplyText] = useState('')
  const [submittingReply, setSubmittingReply] = useState(false)

  // Load threads
  useEffect(() => {
    if (!customerSession?.access_token) return
    loadThreads()
  }, [customerSession])

  async function loadThreads() {
    setLoading(true)
    setError(null)
    try {
      // Gather threads across all customer sales orders
      const allThreads = []
      for (const so of customerSOs || []) {
        try {
          const res = await apiFetch(`/api/portal/customer/sales-orders/${so.id}/threads`, {
            headers: { Authorization: `Bearer ${customerSession.access_token}` },
          })
          if (res?.items) {
            allThreads.push(...res.items)
          }
        } catch {
          // ignore single order fetch failure
        }
      }
      setThreads(allThreads)
    } catch (err) {
      setError(err.message || 'Failed to load order threads.')
    } finally {
      setLoading(false)
    }
  }

  async function openThreadDetail(threadId) {
    setLoading(true)
    try {
      const detail = await apiFetch(`/api/portal/customer/threads/${threadId}`, {
        headers: { Authorization: `Bearer ${customerSession.access_token}` },
      })
      setSelectedThread(detail)
    } catch (err) {
      setError(err.message || 'Failed to load thread details.')
    } finally {
      setLoading(false)
    }
  }

  async function handleCreateThread(e) {
    e.preventDefault()
    if (!selectedSOId) {
      alert('Please select a sales order.')
      return
    }
    setSubmittingThread(true)
    setFeedback(null)
    try {
      const res = await apiFetch(`/api/portal/customer/sales-orders/${selectedSOId}/threads`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${customerSession.access_token}` },
        body: JSON.stringify({
          subject: subject.trim(),
          initial_message: initialMessage.trim(),
        }),
      })
      setFeedback({ type: 'success', message: 'Thread created successfully.' })
      setIsNewThreadOpen(false)
      setSubject('')
      setInitialMessage('')
      loadThreads()
      if (res?.id) {
        openThreadDetail(res.id)
      }
    } catch (err) {
      setFeedback({ type: 'error', message: err.message || 'Failed to create thread.' })
    } finally {
      setSubmittingThread(false)
    }
  }

  async function handleSendReply(e) {
    e.preventDefault()
    if (!replyText.trim() || !selectedThread) return
    setSubmittingReply(true)
    try {
      await apiFetch(`/api/portal/customer/threads/${selectedThread.id}/messages`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${customerSession.access_token}` },
        body: JSON.stringify({ message: replyText.trim() }),
      })
      setReplyText('')
      openThreadDetail(selectedThread.id)
    } catch (err) {
      alert(err.message || 'Failed to send message.')
    } finally {
      setSubmittingReply(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Header Bar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>Order Inquiries &amp; Messages</h2>
          <p style={{ fontSize: 13, color: 'var(--slate-400)', margin: '4px 0 0' }}>
            Communicate securely with internal trade staff regarding order progress, delivery, and documentation.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn-sm btn-secondary" onClick={loadThreads} disabled={loading}>
            <RefreshCw size={13} className={loading ? 'spin' : ''} /> Refresh
          </button>
          <button className="btn-sm btn-primary-sm" onClick={() => setIsNewThreadOpen(true)}>
            <Plus size={14} /> New Inquiry
          </button>
        </div>
      </div>

      {feedback && (
        <div style={{
          padding: '10px 14px',
          borderRadius: 8,
          background: feedback.type === 'error' ? 'rgba(239, 68, 68, 0.15)' : 'rgba(16, 185, 129, 0.15)',
          border: `1px solid ${feedback.type === 'error' ? 'var(--red-500)' : 'var(--emerald-500)'}`,
          color: feedback.type === 'error' ? 'var(--red-400)' : 'var(--emerald-400)',
          fontSize: 13,
        }}>
          {feedback.message}
        </div>
      )}

      {selectedThread ? (
        /* Conversation View */
        <div className="panel" style={{ padding: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--navy-800)', paddingBottom: 14, marginBottom: 16 }}>
            <button className="btn-sm btn-secondary" onClick={() => setSelectedThread(null)}>
              <ArrowLeft size={14} /> Back to Threads
            </button>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 16, fontWeight: 700 }}>{selectedThread.subject}</div>
              <div style={{ fontSize: 12, color: 'var(--slate-400)' }}>
                Order: <strong>{selectedThread.order_number}</strong> • Status: <span className={`status-tag status-${selectedThread.status}`}>{selectedThread.status.toUpperCase()}</span>
              </div>
            </div>
          </div>

          {/* Message History Stream */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxHeight: 420, overflowY: 'auto', paddingRight: 8, marginBottom: 20 }}>
            {selectedThread.messages?.map((msg) => {
              const isCustomer = msg.sender_type === 'customer'
              return (
                <div
                  key={msg.id}
                  style={{
                    alignSelf: isCustomer ? 'flex-end' : 'flex-start',
                    maxWidth: '75%',
                    background: isCustomer ? 'var(--blue-600)' : 'var(--navy-900)',
                    border: `1px solid ${isCustomer ? 'var(--blue-500)' : 'var(--navy-700)'}`,
                    borderRadius: 10,
                    padding: '10px 14px',
                    color: '#fff',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, marginBottom: 4, fontSize: 11, opacity: 0.85 }}>
                    <strong>{isCustomer ? 'You (Customer)' : (msg.sender_name || 'TradeSathi Staff')}</strong>
                    <span>{new Date(msg.created_at).toLocaleString()}</span>
                  </div>
                  <div style={{ fontSize: 13, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                    {msg.message}
                  </div>
                </div>
              )
            })}
          </div>

          {/* Reply Form */}
          {selectedThread.status !== 'closed' ? (
            <form onSubmit={handleSendReply} style={{ display: 'flex', gap: 8 }}>
              <input
                type="text"
                placeholder="Type your reply here..."
                value={replyText}
                onChange={(e) => setReplyText(e.target.value)}
                maxLength={2000}
                style={{ flex: 1, padding: '10px 14px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
              />
              <button type="submit" className="btn-sm btn-primary-sm" disabled={submittingReply || !replyText.trim()}>
                <Send size={14} /> Send Reply
              </button>
            </form>
          ) : (
            <div style={{ textAlign: 'center', padding: 12, background: 'var(--navy-950)', borderRadius: 8, color: 'var(--slate-400)', fontSize: 13 }}>
              This communication thread has been marked as closed.
            </div>
          )}
        </div>
      ) : (
        /* Threads List */
        <div className="panel" style={{ padding: 16 }}>
          {threads.length === 0 ? (
            <div style={{ padding: 32, textAlign: 'center', color: 'var(--slate-400)', fontSize: 13 }}>
              No inquiries found. Click "New Inquiry" to ask a question regarding an order.
            </div>
          ) : (
            <table className="portal-table" style={{ width: '100%', fontSize: 13 }}>
              <thead>
                <tr style={{ background: 'var(--navy-900)' }}>
                  <th style={{ padding: 10 }}>Subject</th>
                  <th style={{ padding: 10 }}>Order #</th>
                  <th style={{ padding: 10 }}>Status</th>
                  <th style={{ padding: 10 }}>Last Activity</th>
                  <th style={{ padding: 10, textAlign: 'right' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {threads.map((t) => (
                  <tr key={t.id} style={{ borderBottom: '1px solid var(--navy-800)' }}>
                    <td style={{ padding: 10 }}>
                      <strong style={{ color: 'var(--blue-400)' }}>{t.subject}</strong>
                    </td>
                    <td style={{ padding: 10 }}>{t.order_number}</td>
                    <td style={{ padding: 10 }}>
                      <span className={`status-tag status-${t.status}`}>{t.status.toUpperCase()}</span>
                    </td>
                    <td style={{ padding: 10, fontSize: 12, color: 'var(--slate-400)' }}>
                      {new Date(t.last_message_at || t.updated_at).toLocaleString()}
                    </td>
                    <td style={{ padding: 10, textAlign: 'right' }}>
                      <button className="btn-sm btn-secondary" onClick={() => openThreadDetail(t.id)}>
                        <MessageSquare size={13} /> View Thread
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* New Thread Modal */}
      {isNewThreadOpen && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0, 0, 0, 0.75)', display: 'flex', alignItems: 'center',
          justifyContent: 'center', zIndex: 1000,
        }}>
          <div className="panel" style={{ width: 520, maxWidth: '90%', padding: 24, background: 'var(--navy-950)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h3 style={{ fontSize: 16, fontWeight: 700, margin: 0 }}>Start Order Inquiry Thread</h3>
              <button onClick={() => setIsNewThreadOpen(false)} style={{ background: 'transparent', border: 'none', color: '#fff', cursor: 'pointer' }}>
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleCreateThread} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>Related Sales Order</label>
                <select
                  value={selectedSOId}
                  onChange={(e) => setSelectedSOId(e.target.value)}
                  required
                  style={{ width: '100%', padding: '10px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff' }}
                >
                  <option value="">-- Select Sales Order --</option>
                  {customerSOs?.map((so) => (
                    <option key={so.id} value={so.id}>
                      {so.order_number} ({so.currency} {Number(so.grand_total).toFixed(2)})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>Inquiry Subject</label>
                <input
                  type="text"
                  placeholder="e.g. Delivery Schedule Confirmation"
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  minLength={3}
                  maxLength={200}
                  required
                  style={{ width: '100%', padding: '10px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>Initial Message</label>
                <textarea
                  rows={4}
                  placeholder="Please state your inquiry or clarification..."
                  value={initialMessage}
                  onChange={(e) => setInitialMessage(e.target.value)}
                  minLength={1}
                  maxLength={2000}
                  required
                  style={{ width: '100%', padding: '10px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff' }}
                />
              </div>

              <div style={{ display: 'flex', gap: 10, marginTop: 10 }}>
                <button type="submit" className="primary-button" style={{ flex: 1 }} disabled={submittingThread}>
                  {submittingThread ? 'Submitting...' : 'Submit Inquiry'}
                </button>
                <button type="button" className="btn-sm btn-secondary" onClick={() => setIsNewThreadOpen(false)}>
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
// 2. CUSTOMER DOCUMENT REQUESTS SECTION
// ============================================================================

export function CustomerDocumentRequestsSection({ customerSession, customerSOs }) {
  const [requests, setRequests] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [feedback, setFeedback] = useState(null)

  // Request modal
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [selectedSOId, setSelectedSOId] = useState('')
  const [category, setCategory] = useState('commercial_invoice')
  const [message, setMessage] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const CATEGORIES = [
    { value: 'commercial_invoice', label: 'Commercial Invoice' },
    { value: 'packing_list', label: 'Packing List' },
    { value: 'shipping_bill', label: 'Shipping Bill' },
    { value: 'bill_of_lading', label: 'Bill of Lading' },
    { value: 'certificate_of_origin', label: 'Certificate of Origin' },
    { value: 'quality_certificate', label: 'Quality Certificate' },
    { value: 'inspection_certificate', label: 'Inspection Certificate' },
    { value: 'other', label: 'Other Document' },
  ]

  useEffect(() => {
    if (!customerSession?.access_token) return
    loadRequests()
  }, [customerSession])

  async function loadRequests() {
    setLoading(true)
    setError(null)
    try {
      const res = await apiFetch('/api/portal/customer/document-requests', {
        headers: { Authorization: `Bearer ${customerSession.access_token}` },
      })
      setRequests(res?.items || [])
    } catch (err) {
      setError(err.message || 'Failed to load document requests.')
    } finally {
      setLoading(false)
    }
  }

  async function handleCreateRequest(e) {
    e.preventDefault()
    if (!selectedSOId) {
      alert('Please select a sales order.')
      return
    }
    setSubmitting(true)
    setFeedback(null)
    try {
      await apiFetch(`/api/portal/customer/sales-orders/${selectedSOId}/document-requests`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${customerSession.access_token}` },
        body: JSON.stringify({
          category,
          message: message.trim() || undefined,
        }),
      })
      setFeedback({ type: 'success', message: 'Document request submitted successfully.' })
      setIsModalOpen(false)
      setMessage('')
      loadRequests()
    } catch (err) {
      setFeedback({ type: 'error', message: err.message || 'Failed to submit document request.' })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Header Bar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>Customer Document Requests</h2>
          <p style={{ fontSize: 13, color: 'var(--slate-400)', margin: '4px 0 0' }}>
            Request stamped commercial invoices, certificates of origin, packing lists, and export declarations.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn-sm btn-secondary" onClick={loadRequests} disabled={loading}>
            <RefreshCw size={13} className={loading ? 'spin' : ''} /> Refresh
          </button>
          <button className="btn-sm btn-primary-sm" onClick={() => setIsModalOpen(true)}>
            <Plus size={14} /> Request Document
          </button>
        </div>
      </div>

      {feedback && (
        <div style={{
          padding: '10px 14px',
          borderRadius: 8,
          background: feedback.type === 'error' ? 'rgba(239, 68, 68, 0.15)' : 'rgba(16, 185, 129, 0.15)',
          border: `1px solid ${feedback.type === 'error' ? 'var(--red-500)' : 'var(--emerald-500)'}`,
          color: feedback.type === 'error' ? 'var(--red-400)' : 'var(--emerald-400)',
          fontSize: 13,
        }}>
          {feedback.message}
        </div>
      )}

      {/* Requests Table */}
      <div className="panel" style={{ padding: 16 }}>
        {requests.length === 0 ? (
          <div style={{ padding: 32, textAlign: 'center', color: 'var(--slate-400)', fontSize: 13 }}>
            No document requests recorded. Click "Request Document" to request a certified document.
          </div>
        ) : (
          <table className="portal-table" style={{ width: '100%', fontSize: 13 }}>
            <thead>
              <tr style={{ background: 'var(--navy-900)' }}>
                <th style={{ padding: 10 }}>Request #</th>
                <th style={{ padding: 10 }}>Order #</th>
                <th style={{ padding: 10 }}>Document Category</th>
                <th style={{ padding: 10 }}>Status</th>
                <th style={{ padding: 10 }}>Requested At</th>
                <th style={{ padding: 10, textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {requests.map((r) => (
                <tr key={r.id} style={{ borderBottom: '1px solid var(--navy-800)' }}>
                  <td style={{ padding: 10 }}>
                    <strong>{r.request_number}</strong>
                    {r.message && <div style={{ fontSize: 11, color: 'var(--slate-400)' }}>{r.message}</div>}
                  </td>
                  <td style={{ padding: 10 }}>{r.order_number}</td>
                  <td style={{ padding: 10 }}>
                    <span style={{ textTransform: 'capitalize' }}>{r.document_category?.replace(/_/g, ' ')}</span>
                  </td>
                  <td style={{ padding: 10 }}>
                    <span className={`status-tag status-${r.status}`}>{r.status.toUpperCase()}</span>
                    {r.staff_decision_notes && (
                      <div style={{ fontSize: 11, color: 'var(--slate-400)', marginTop: 2 }}>{r.staff_decision_notes}</div>
                    )}
                  </td>
                  <td style={{ padding: 10, fontSize: 12, color: 'var(--slate-400)' }}>
                    {new Date(r.created_at).toLocaleDateString()}
                  </td>
                  <td style={{ padding: 10, textAlign: 'right' }}>
                    {r.status === 'fulfilled' && r.fulfilled_document_id ? (
                      <button
                        className="btn-sm btn-primary-sm"
                        onClick={() => downloadAuthorizedDocument(r.fulfilled_document_id, r.fulfilled_filename, customerSession.access_token)}
                      >
                        <Download size={13} /> Download File
                      </button>
                    ) : (
                      <span style={{ fontSize: 12, color: 'var(--slate-500)' }}>
                        {r.status === 'rejected' ? 'Request Rejected' : 'Pending Review'}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* New Document Request Modal */}
      {isModalOpen && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0, 0, 0, 0.75)', display: 'flex', alignItems: 'center',
          justifyContent: 'center', zIndex: 1000,
        }}>
          <div className="panel" style={{ width: 500, maxWidth: '90%', padding: 24, background: 'var(--navy-950)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h3 style={{ fontSize: 16, fontWeight: 700, margin: 0 }}>Request Certified Document</h3>
              <button onClick={() => setIsModalOpen(false)} style={{ background: 'transparent', border: 'none', color: '#fff', cursor: 'pointer' }}>
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleCreateRequest} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>Related Sales Order</label>
                <select
                  value={selectedSOId}
                  onChange={(e) => setSelectedSOId(e.target.value)}
                  required
                  style={{ width: '100%', padding: '10px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff' }}
                >
                  <option value="">-- Select Sales Order --</option>
                  {customerSOs?.map((so) => (
                    <option key={so.id} value={so.id}>
                      {so.order_number} ({so.currency} {Number(so.grand_total).toFixed(2)})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>Document Category</label>
                <select
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  style={{ width: '100%', padding: '10px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff' }}
                >
                  {CATEGORIES.map((cat) => (
                    <option key={cat.value} value={cat.value}>{cat.label}</option>
                  ))}
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>Requirement Notes &amp; Justification</label>
                <textarea
                  rows={3}
                  placeholder="e.g. Stamped certificate of origin required for customs clearance at destination port."
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  maxLength={1000}
                  style={{ width: '100%', padding: '10px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff' }}
                />
              </div>

              <div style={{ display: 'flex', gap: 10, marginTop: 10 }}>
                <button type="submit" className="primary-button" style={{ flex: 1 }} disabled={submitting}>
                  {submitting ? 'Submitting Request...' : 'Submit Document Request'}
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
// 3. CUSTOMER NOTIFICATIONS SECTION
// ============================================================================

export function CustomerNotificationsSection({ customerSession }) {
  const [notifications, setNotifications] = useState([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!customerSession?.access_token) return
    loadNotifications()
  }, [customerSession])

  async function loadNotifications() {
    setLoading(true)
    try {
      const res = await apiFetch('/api/portal/customer/notifications', {
        headers: { Authorization: `Bearer ${customerSession.access_token}` },
      })
      setNotifications(res?.items || [])
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }

  async function markRead(notifId) {
    try {
      await apiFetch(`/api/portal/customer/notifications/${notifId}/read`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${customerSession.access_token}` },
      })
      setNotifications((prev) =>
        prev.map((n) => (n.id === notifId ? { ...n, is_read: 1 } : n))
      )
    } catch {
      // ignore
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>Collaboration Notifications</h2>
          <p style={{ fontSize: 13, color: 'var(--slate-400)', margin: '4px 0 0' }}>
            Real-time updates regarding staff replies, document approvals, and dispatch progress.
          </p>
        </div>
        <button className="btn-sm btn-secondary" onClick={loadNotifications} disabled={loading}>
          <RefreshCw size={13} className={loading ? 'spin' : ''} /> Refresh
        </button>
      </div>

      <div className="panel" style={{ padding: 16 }}>
        {notifications.length === 0 ? (
          <div style={{ padding: 32, textAlign: 'center', color: 'var(--slate-400)', fontSize: 13 }}>
            No notifications available.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {notifications.map((n) => (
              <div
                key={n.id}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '12px 16px',
                  background: n.is_read ? 'var(--navy-900)' : 'rgba(59, 130, 246, 0.1)',
                  border: `1px solid ${n.is_read ? 'var(--navy-800)' : 'var(--blue-500)'}`,
                  borderRadius: 8,
                }}
              >
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <strong>{n.title}</strong>
                    {!n.is_read && (
                      <span style={{ fontSize: 10, padding: '2px 6px', background: 'var(--blue-500)', color: '#fff', borderRadius: 4 }}>
                        NEW
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--slate-300)', marginTop: 2 }}>{n.message}</div>
                  <div style={{ fontSize: 11, color: 'var(--slate-400)', marginTop: 4 }}>
                    {new Date(n.created_at).toLocaleString()}
                  </div>
                </div>

                {!n.is_read && (
                  <button className="btn-sm btn-secondary" onClick={() => markRead(n.id)}>
                    <Check size={13} /> Mark Read
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ============================================================================
// 4. INTERNAL STAFF REVIEW CONSOLE (PHASE 9C ADDITIONS)
// ============================================================================

export function StaffCustomerCollaborationConsole() {
  const [subTab, setSubTab] = useState('threads') // 'threads' | 'document_requests' | 'doc_sharing'
  const [threads, setThreads] = useState([])
  const [selectedThread, setSelectedThread] = useState(null)
  const [docRequests, setDocRequests] = useState([])
  const [selectedDocRequest, setSelectedDocRequest] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [feedback, setFeedback] = useState(null)

  // Staff Thread reply
  const [staffReplyText, setStaffReplyText] = useState('')
  const [isInternalNote, setIsInternalNote] = useState(false)
  const [submittingReply, setSubmittingReply] = useState(false)

  // Review modal
  const [isReviewModalOpen, setIsReviewModalOpen] = useState(false)
  const [reviewAction, setReviewAction] = useState('fulfilled')
  const [selectedFulfillDocId, setSelectedFulfillDocId] = useState('')
  const [reviewNotes, setReviewNotes] = useState('')
  const [submittingReview, setSubmittingReview] = useState(false)

  useEffect(() => {
    if (subTab === 'threads') loadAdminThreads()
    else if (subTab === 'document_requests') loadAdminDocRequests()
  }, [subTab])

  async function loadAdminThreads() {
    setLoading(true)
    try {
      const res = await apiFetch('/api/portal/admin/customer-threads')
      setThreads(res?.items || [])
    } catch (err) {
      setError(err.message || 'Failed to load customer threads.')
    } finally {
      setLoading(false)
    }
  }

  async function loadAdminDocRequests() {
    setLoading(true)
    try {
      const res = await apiFetch('/api/portal/admin/customer-document-requests')
      setDocRequests(res?.items || [])
    } catch (err) {
      setError(err.message || 'Failed to load document requests.')
    } finally {
      setLoading(false)
    }
  }

  async function openAdminThreadDetail(threadId) {
    setLoading(true)
    try {
      const detail = await apiFetch(`/api/portal/admin/customer-threads/${threadId}`)
      setSelectedThread(detail)
    } catch (err) {
      alert(err.message || 'Failed to load thread.')
    } finally {
      setLoading(false)
    }
  }

  async function handleSendStaffMessage(e) {
    e.preventDefault()
    if (!staffReplyText.trim() || !selectedThread) return
    setSubmittingReply(true)
    try {
      await apiFetch(`/api/portal/admin/customer-threads/${selectedThread.id}/messages`, {
        method: 'POST',
        body: JSON.stringify({
          message: staffReplyText.trim(),
          is_internal_note: isInternalNote,
        }),
      })
      setStaffReplyText('')
      setIsInternalNote(false)
      openAdminThreadDetail(selectedThread.id)
    } catch (err) {
      alert(err.message || 'Failed to post staff message.')
    } finally {
      setSubmittingReply(false)
    }
  }

  async function openDocRequestModal(dreqId) {
    setLoading(true)
    try {
      const detail = await apiFetch(`/api/portal/admin/customer-document-requests/${dreqId}`)
      setSelectedDocRequest(detail)
      setIsReviewModalOpen(true)
      setSelectedFulfillDocId(detail.eligible_documents?.[0]?.id || '')
      setReviewNotes('')
    } catch (err) {
      alert(err.message || 'Failed to load document request details.')
    } finally {
      setLoading(false)
    }
  }

  async function handleReviewSubmit(e) {
    e.preventDefault()
    if (!selectedDocRequest) return
    if (reviewAction === 'fulfilled' && !selectedFulfillDocId) {
      alert('Please select an eligible document to fulfill this request.')
      return
    }
    setSubmittingReview(true)
    try {
      await apiFetch(`/api/portal/admin/customer-document-requests/${selectedDocRequest.id}/review`, {
        method: 'POST',
        body: JSON.stringify({
          status: reviewAction,
          fulfilled_document_id: reviewAction === 'fulfilled' ? selectedFulfillDocId : undefined,
          review_notes: reviewNotes.trim() || undefined,
        }),
      })
      setIsReviewModalOpen(false)
      loadAdminDocRequests()
      alert('Document request reviewed successfully.')
    } catch (err) {
      alert(err.message || 'Failed to review document request.')
    } finally {
      setSubmittingReview(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Sub-nav */}
      <div style={{ display: 'flex', gap: 8, borderBottom: '1px solid var(--navy-800)', paddingBottom: 12 }}>
        <button
          className={`btn-sm ${subTab === 'threads' ? 'btn-primary-sm' : 'btn-secondary'}`}
          onClick={() => { setSubTab('threads'); setSelectedThread(null); }}
        >
          <MessageSquare size={14} /> Customer Threads
        </button>
        <button
          className={`btn-sm ${subTab === 'document_requests' ? 'btn-primary-sm' : 'btn-secondary'}`}
          onClick={() => { setSubTab('document_requests'); }}
        >
          <FileText size={14} /> Document Request Queue
        </button>
      </div>

      {subTab === 'threads' && (
        selectedThread ? (
          <div className="panel" style={{ padding: 20 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--navy-800)', paddingBottom: 14, marginBottom: 16 }}>
              <button className="btn-sm btn-secondary" onClick={() => setSelectedThread(null)}>
                <ArrowLeft size={14} /> Back to Customer Threads
              </button>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 16, fontWeight: 700 }}>{selectedThread.subject}</div>
                <div style={{ fontSize: 12, color: 'var(--slate-400)' }}>
                  Customer: <strong>{selectedThread.customer_name}</strong> • Order: <strong>{selectedThread.order_number}</strong>
                </div>
              </div>
            </div>

            {/* Messages */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxHeight: 420, overflowY: 'auto', paddingRight: 8, marginBottom: 20 }}>
              {selectedThread.messages?.map((msg) => {
                const isInternal = msg.is_internal_note === 1
                const isCustomer = msg.sender_type === 'customer'
                return (
                  <div
                    key={msg.id}
                    style={{
                      alignSelf: isCustomer ? 'flex-start' : 'flex-end',
                      maxWidth: '75%',
                      background: isInternal ? 'rgba(245, 158, 11, 0.15)' : (isCustomer ? 'var(--navy-900)' : 'var(--blue-600)'),
                      border: `1px solid ${isInternal ? 'var(--amber-500)' : (isCustomer ? 'var(--navy-700)' : 'var(--blue-500)')}`,
                      borderRadius: 10,
                      padding: '10px 14px',
                      color: '#fff',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, marginBottom: 4, fontSize: 11, opacity: 0.85 }}>
                      <strong style={{ color: isInternal ? 'var(--amber-400)' : undefined }}>
                        {isInternal ? '🔒 Staff Internal Note (Confidential)' : (isCustomer ? `${msg.sender_name} (Customer)` : `${msg.sender_name} (Staff)`)}
                      </strong>
                      <span>{new Date(msg.created_at).toLocaleString()}</span>
                    </div>
                    <div style={{ fontSize: 13, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                      {msg.message}
                    </div>
                  </div>
                )
              })}
            </div>

            {/* Post message */}
            <form onSubmit={handleSendStaffMessage} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', gap: 8 }}>
                <input
                  type="text"
                  placeholder="Type staff response or internal note..."
                  value={staffReplyText}
                  onChange={(e) => setStaffReplyText(e.target.value)}
                  style={{ flex: 1, padding: '10px 14px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
                />
                <button type="submit" className="btn-sm btn-primary-sm" disabled={submittingReply || !staffReplyText.trim()}>
                  <Send size={14} /> Send
                </button>
              </div>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--amber-400)', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={isInternalNote}
                  onChange={(e) => setIsInternalNote(e.target.checked)}
                />
                Private Internal Note (Hidden from Customer)
              </label>
            </form>
          </div>
        ) : (
          <div className="panel" style={{ padding: 16 }}>
            {threads.length === 0 ? (
              <div style={{ padding: 32, textAlign: 'center', color: 'var(--slate-400)', fontSize: 13 }}>
                No customer threads in the queue.
              </div>
            ) : (
              <table className="portal-table" style={{ width: '100%', fontSize: 13 }}>
                <thead>
                  <tr style={{ background: 'var(--navy-900)' }}>
                    <th style={{ padding: 10 }}>Subject</th>
                    <th style={{ padding: 10 }}>Customer</th>
                    <th style={{ padding: 10 }}>Order #</th>
                    <th style={{ padding: 10 }}>Status</th>
                    <th style={{ padding: 10 }}>Last Message</th>
                    <th style={{ padding: 10, textAlign: 'right' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {threads.map((t) => (
                    <tr key={t.id} style={{ borderBottom: '1px solid var(--navy-800)' }}>
                      <td style={{ padding: 10 }}>
                        <strong style={{ color: 'var(--blue-400)' }}>{t.subject}</strong>
                      </td>
                      <td style={{ padding: 10 }}>{t.customer_name}</td>
                      <td style={{ padding: 10 }}>{t.order_number}</td>
                      <td style={{ padding: 10 }}><span className={`status-tag status-${t.status}`}>{t.status.toUpperCase()}</span></td>
                      <td style={{ padding: 10, fontSize: 12, color: 'var(--slate-400)' }}>{new Date(t.last_message_at).toLocaleString()}</td>
                      <td style={{ padding: 10, textAlign: 'right' }}>
                        <button className="btn-sm btn-secondary" onClick={() => openAdminThreadDetail(t.id)}>
                          <MessageSquare size={13} /> View Thread
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )
      )}

      {subTab === 'document_requests' && (
        <div className="panel" style={{ padding: 16 }}>
          {docRequests.length === 0 ? (
            <div style={{ padding: 32, textAlign: 'center', color: 'var(--slate-400)', fontSize: 13 }}>
              No document requests pending review.
            </div>
          ) : (
            <table className="portal-table" style={{ width: '100%', fontSize: 13 }}>
              <thead>
                <tr style={{ background: 'var(--navy-900)' }}>
                  <th style={{ padding: 10 }}>Request #</th>
                  <th style={{ padding: 10 }}>Customer</th>
                  <th style={{ padding: 10 }}>Order #</th>
                  <th style={{ padding: 10 }}>Category</th>
                  <th style={{ padding: 10 }}>Status</th>
                  <th style={{ padding: 10, textAlign: 'right' }}>Review Action</th>
                </tr>
              </thead>
              <tbody>
                {docRequests.map((r) => (
                  <tr key={r.id} style={{ borderBottom: '1px solid var(--navy-800)' }}>
                    <td style={{ padding: 10 }}>
                      <strong>{r.request_number}</strong>
                      {r.message && <div style={{ fontSize: 11, color: 'var(--slate-400)' }}>{r.message}</div>}
                    </td>
                    <td style={{ padding: 10 }}>{r.customer_name}</td>
                    <td style={{ padding: 10 }}>{r.order_number}</td>
                    <td style={{ padding: 10 }}>{r.document_category?.replace(/_/g, ' ')}</td>
                    <td style={{ padding: 10 }}><span className={`status-tag status-${r.status}`}>{r.status.toUpperCase()}</span></td>
                    <td style={{ padding: 10, textAlign: 'right' }}>
                      <button className="btn-sm btn-primary-sm" onClick={() => openDocRequestModal(r.id)}>
                        <FileCheck2 size={13} /> Review &amp; Fulfill
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Review Modal */}
      {isReviewModalOpen && selectedDocRequest && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0, 0, 0, 0.75)', display: 'flex', alignItems: 'center',
          justifyContent: 'center', zIndex: 1000,
        }}>
          <div className="panel" style={{ width: 540, maxWidth: '90%', padding: 24, background: 'var(--navy-950)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h3 style={{ fontSize: 16, fontWeight: 700, margin: 0 }}>Review Customer Document Request</h3>
              <button onClick={() => setIsReviewModalOpen(false)} style={{ background: 'transparent', border: 'none', color: '#fff', cursor: 'pointer' }}>
                <X size={18} />
              </button>
            </div>

            <div style={{ padding: 12, background: 'var(--navy-900)', borderRadius: 8, fontSize: 12, color: 'var(--slate-300)', marginBottom: 14 }}>
              <div>Request: <strong>{selectedDocRequest.request_number}</strong> ({selectedDocRequest.document_category})</div>
              <div>Customer: <strong>{selectedDocRequest.customer_name}</strong> • Order: <strong>{selectedDocRequest.order_number}</strong></div>
              {selectedDocRequest.message && <div style={{ marginTop: 4 }}>Note: <em>"{selectedDocRequest.message}"</em></div>}
            </div>

            <form onSubmit={handleReviewSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>Action</label>
                <select
                  value={reviewAction}
                  onChange={(e) => setReviewAction(e.target.value)}
                  style={{ width: '100%', padding: '10px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff' }}
                >
                  <option value="fulfilled">Fulfill &amp; Share Document with Customer</option>
                  <option value="under_review">Mark Under Review</option>
                  <option value="rejected">Reject Request</option>
                </select>
              </div>

              {reviewAction === 'fulfilled' && (
                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>
                    Select Eligible Document to Share
                  </label>
                  {selectedDocRequest.eligible_documents?.length === 0 ? (
                    <div style={{ fontSize: 12, color: 'var(--amber-400)', padding: 8, background: 'rgba(245, 158, 11, 0.1)', borderRadius: 6 }}>
                      No documents currently attached to this order or shipment. Please upload the certified document in Document Management first.
                    </div>
                  ) : (
                    <select
                      value={selectedFulfillDocId}
                      onChange={(e) => setSelectedFulfillDocId(e.target.value)}
                      required
                      style={{ width: '100%', padding: '10px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff' }}
                    >
                      {selectedDocRequest.eligible_documents?.map((d) => (
                        <option key={d.id} value={d.id}>
                          {d.original_filename} ({d.document_type}) • {d.shared_with_customer ? 'Shared' : 'Private'}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
              )}

              <div>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>Decision Commentary</label>
                <textarea
                  rows={3}
                  placeholder="Commentary or explanation provided to the customer..."
                  value={reviewNotes}
                  onChange={(e) => setReviewNotes(e.target.value)}
                  maxLength={1000}
                  style={{ width: '100%', padding: '10px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff' }}
                />
              </div>

              <div style={{ display: 'flex', gap: 10, marginTop: 10 }}>
                <button type="submit" className="primary-button" style={{ flex: 1 }} disabled={submittingReview}>
                  {submittingReview ? 'Updating...' : 'Submit Decision'}
                </button>
                <button type="button" className="btn-sm btn-secondary" onClick={() => setIsReviewModalOpen(false)}>
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
