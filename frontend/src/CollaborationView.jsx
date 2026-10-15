import { useEffect, useState, useMemo } from 'react'
import {
  AlertTriangle,
  ArrowLeft,
  Bell,
  Building2,
  Calendar,
  Check,
  CheckCircle2,
  Clock,
  Copy,
  Download,
  Eye,
  FileCheck2,
  FileText,
  KeyRound,
  Lock,
  LogOut,
  Mail,
  MessageSquare,
  Package,
  Receipt,
  RefreshCw,
  Search,
  Send,
  ShieldAlert,
  ShieldCheck,
  ShoppingBag,
  ShoppingCart,
  Trash2,
  Truck,
  UserCheck,
  UserPlus,
  Users,
  X,
  XCircle,
} from 'lucide-react'
import { apiFetch, API_BASE } from './api'
import {
  SupplierCommitmentsSection,
  SupplierASNsSection,
  SupplierDocumentsSection,
  SupplierDiscrepanciesSection,
  StaffReviewConsole,
} from './CollaborationPhase9B'
import {
  CustomerThreadsSection,
  CustomerDocumentRequestsSection,
  CustomerNotificationsSection,
  StaffCustomerCollaborationConsole,
} from './CollaborationPhase9C'

export default function CollaborationView({ initialSubTab = 'supplier' }) {
  // Top-level View Mode: 'supplier' | 'customer' | 'admin_invitations' | 'staff_review'
  const [activePortal, setActivePortal] = useState(initialSubTab)

  // Staff Review Portal Perspective: 'supplier' | 'customer'
  const [staffReviewPortal, setStaffReviewPortal] = useState('supplier')

  // Phase 9B Supplier Sub-tab: 'pos' | 'commitments' | 'asns' | 'documents' | 'discrepancies'
  const [supplierSubTab, setSupplierSubTab] = useState('pos')

  // Portal Authentication State (Stored per portal type in local state/session)
  const [supplierSession, setSupplierSession] = useState(() => {
    try {
      return JSON.parse(sessionStorage.getItem('tradesathi_supplier_session')) || null
    } catch {
      return null
    }
  })

  const [customerSession, setCustomerSession] = useState(() => {
    try {
      return JSON.parse(sessionStorage.getItem('tradesathi_customer_session')) || null
    } catch {
      return null
    }
  })

  // Auth / Activation Screen Mode: 'login' | 'activate'
  const [authMode, setAuthMode] = useState('login')
  const [loginUsername, setLoginUsername] = useState('')
  const [loginPassword, setLoginPassword] = useState('')
  const [authError, setAuthError] = useState(null)
  const [authSuccess, setAuthSuccess] = useState(null)
  const [authLoading, setAuthLoading] = useState(false)

  // Activation Form State
  const [invitationTokenInput, setInvitationTokenInput] = useState('')
  const [verifiedInvitation, setVerifiedInvitation] = useState(null)
  const [activateUsername, setActivateUsername] = useState('')
  const [activatePassword, setActivatePassword] = useState('')

  // Supplier Portal State
  const [supplierPOs, setSupplierPOs] = useState([])
  const [supplierTotalPOs, setSupplierTotalPOs] = useState(0)
  const [supplierSearch, setSupplierSearch] = useState('')
  const [supplierStatusFilter, setSupplierStatusFilter] = useState('')
  const [selectedPO, setSelectedPO] = useState(null)
  const [supplierLoading, setSupplierLoading] = useState(false)
  const [supplierError, setSupplierError] = useState(null)

  // PO Acknowledgement Form State
  const [ackAction, setAckAction] = useState('accept') // 'accept' | 'reject' | 'request_clarification'
  const [ackComments, setAckComments] = useState('')
  const [ackProposedDate, setAckProposedDate] = useState('')
  const [ackLoading, setAckLoading] = useState(false)
  const [ackFeedback, setAckFeedback] = useState(null)

  // Customer Portal State
  const [customerTab, setCustomerTab] = useState('orders') // 'orders' | 'invoices' | 'shipments'
  const [customerSOs, setCustomerSOs] = useState([])
  const [selectedSO, setSelectedSO] = useState(null)
  const [customerInvoices, setCustomerInvoices] = useState([])
  const [selectedInvoice, setSelectedInvoice] = useState(null)
  const [customerShipments, setCustomerShipments] = useState([])
  const [customerLoading, setCustomerLoading] = useState(false)
  const [customerError, setCustomerError] = useState(null)

  // Internal Admin Invitations Management State
  const [invitationsList, setInvitationsList] = useState([])
  const [portalUsersList, setPortalUsersList] = useState([])
  const [suppliersMaster, setSuppliersMaster] = useState([])
  const [customersMaster, setCustomersMaster] = useState([])
  const [adminLoading, setAdminLoading] = useState(false)
  const [adminError, setAdminError] = useState(null)
  const [adminSuccess, setAdminSuccess] = useState(null)
  const [isInviteModalOpen, setIsInviteModalOpen] = useState(false)
  const [inviteFormData, setInviteFormData] = useState({
    account_type: 'supplier',
    organization_id: '',
    email: '',
    notes: '',
    expires_in_days: 7,
  })
  const [generatedInvite, setGeneratedInvite] = useState(null)

  // Persist sessions
  useEffect(() => {
    if (supplierSession) {
      sessionStorage.setItem('tradesathi_supplier_session', JSON.stringify(supplierSession))
    } else {
      sessionStorage.removeItem('tradesathi_supplier_session')
    }
  }, [supplierSession])

  useEffect(() => {
    if (customerSession) {
      sessionStorage.setItem('tradesathi_customer_session', JSON.stringify(customerSession))
    } else {
      sessionStorage.removeItem('tradesathi_customer_session')
    }
  }, [customerSession])

  // ==========================================
  // Auth & Activation Handlers
  // ==========================================

  async function handleLogin(e) {
    if (e) e.preventDefault()
    setAuthError(null)
    setAuthLoading(true)
    try {
      const data = await apiFetch('/api/portal/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: loginUsername, password: loginPassword }),
      }, 'Login failed')

      if (data?.user?.account_type === 'supplier') {
        setSupplierSession(data)
        setActivePortal('supplier')
      } else if (data?.user?.account_type === 'customer') {
        setCustomerSession(data)
        setActivePortal('customer')
      }
      setLoginPassword('')
      setAuthSuccess(`Welcome, ${data.user.username}! Signed in to ${data.user.organization_name}.`)
    } catch (err) {
      setAuthError(err.detail || err.message || 'Invalid credentials or inactive account.')
    } finally {
      setAuthLoading(false)
    }
  }

  function handleLogout(type) {
    const session = type === 'supplier' ? supplierSession : customerSession
    if (session?.access_token) {
      apiFetch('/api/portal/auth/logout', {
        method: 'POST',
        headers: { Authorization: `Bearer ${session.access_token}` },
      }).catch(() => {})
    }
    if (type === 'supplier') {
      setSupplierSession(null)
      setSelectedPO(null)
    } else {
      setCustomerSession(null)
      setSelectedSO(null)
      setSelectedInvoice(null)
    }
    setAuthSuccess('Successfully logged out.')
  }

  async function handleVerifyInvitation(token) {
    const raw = (token || invitationTokenInput).trim()
    if (!raw) return
    setAuthError(null)
    setAuthLoading(true)
    try {
      const data = await apiFetch('/api/portal/invitations/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ invitation_token: raw }),
      }, 'Invalid invitation')
      setVerifiedInvitation(data)
      setAuthSuccess(`Invitation verified for ${data.organization_name} (${data.account_type.toUpperCase()}). Please create your username and password below.`)
    } catch (err) {
      setVerifiedInvitation(null)
      setAuthError(err.detail || 'Invalid or expired invitation token.')
    } finally {
      setAuthLoading(false)
    }
  }

  async function handleActivateAccount(e) {
    if (e) e.preventDefault()
    setAuthError(null)
    setAuthLoading(true)
    try {
      const data = await apiFetch('/api/portal/invitations/accept', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          invitation_token: invitationTokenInput.trim(),
          username: activateUsername.trim(),
          password: activatePassword,
        }),
      }, 'Account activation failed')

      if (data?.user?.account_type === 'supplier') {
        setSupplierSession(data)
        setActivePortal('supplier')
      } else {
        setCustomerSession(data)
        setActivePortal('customer')
      }
      setAuthMode('login')
      setVerifiedInvitation(null)
      setInvitationTokenInput('')
      setActivatePassword('')
      setAuthSuccess(`Account activated successfully! Logged in as ${data.user.username}.`)
    } catch (err) {
      setAuthError(err.detail || err.message || 'Activation failed.')
    } finally {
      setAuthLoading(false)
    }
  }

  // ==========================================
  // Supplier Portal Handlers
  // ==========================================

  async function fetchSupplierPurchaseOrders() {
    if (!supplierSession?.access_token) return
    setSupplierLoading(true)
    setSupplierError(null)
    try {
      const params = new URLSearchParams()
      if (supplierSearch.trim()) params.append('search', supplierSearch.trim())
      if (supplierStatusFilter.trim()) params.append('status', supplierStatusFilter.trim())
      const data = await apiFetch(`/api/portal/supplier/purchase-orders?${params.toString()}`, {
        headers: { Authorization: `Bearer ${supplierSession.access_token}` },
      }, 'Failed to load purchase orders')
      setSupplierPOs(data.items || [])
      setSupplierTotalPOs(data.total || 0)
    } catch (err) {
      if (err.status === 401) {
        handleLogout('supplier')
        setAuthError('Session expired. Please log in again.')
      } else {
        setSupplierError(err.detail || 'Could not retrieve purchase orders.')
      }
    } finally {
      setSupplierLoading(false)
    }
  }

  async function fetchPODetail(poId) {
    if (!supplierSession?.access_token) return
    setSupplierLoading(true)
    setSupplierError(null)
    try {
      const data = await apiFetch(`/api/portal/supplier/purchase-orders/${poId}`, {
        headers: { Authorization: `Bearer ${supplierSession.access_token}` },
      }, 'Failed to retrieve PO details')
      setSelectedPO(data)
      setAckComments('')
      setAckProposedDate('')
      setAckFeedback(null)
    } catch (err) {
      setSupplierError(err.detail || 'Could not load order details.')
    } finally {
      setSupplierLoading(false)
    }
  }

  async function handleSubmitAcknowledgement(e) {
    if (e) e.preventDefault()
    if (!selectedPO || !supplierSession?.access_token) return
    setAckLoading(true)
    setAckFeedback(null)
    try {
      const payload = {
        action: ackAction,
        supplier_comments: ackComments.trim() || null,
        proposed_delivery_date: ackProposedDate || null,
        idempotency_key: `ACK-${selectedPO.id}-${Date.now()}`,
      }
      const data = await apiFetch(`/api/portal/supplier/purchase-orders/${selectedPO.id}/acknowledge`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${supplierSession.access_token}`,
        },
        body: JSON.stringify(payload),
      }, 'Acknowledgement failed')

      setAckFeedback({
        type: 'success',
        message: `Order ${selectedPO.po_number} successfully acknowledged (${ackAction.toUpperCase()}).`,
      })
      fetchPODetail(selectedPO.id)
      fetchSupplierPurchaseOrders()
    } catch (err) {
      setAckFeedback({
        type: 'error',
        message: err.detail || 'Failed to submit acknowledgement.',
      })
    } finally {
      setAckLoading(false)
    }
  }

  // ==========================================
  // Customer Portal Handlers
  // ==========================================

  async function fetchCustomerSalesOrders() {
    if (!customerSession?.access_token) return
    setCustomerLoading(true)
    setCustomerError(null)
    try {
      const data = await apiFetch('/api/portal/customer/sales-orders', {
        headers: { Authorization: `Bearer ${customerSession.access_token}` },
      }, 'Failed to retrieve sales orders')
      setCustomerSOs(data.items || [])
    } catch (err) {
      if (err.status === 401) {
        handleLogout('customer')
        setAuthError('Session expired. Please log in again.')
      } else {
        setCustomerError(err.detail || 'Could not retrieve sales orders.')
      }
    } finally {
      setCustomerLoading(false)
    }
  }

  async function fetchCustomerSODetail(soId) {
    if (!customerSession?.access_token) return
    setCustomerLoading(true)
    setCustomerError(null)
    try {
      const data = await apiFetch(`/api/portal/customer/sales-orders/${soId}`, {
        headers: { Authorization: `Bearer ${customerSession.access_token}` },
      }, 'Failed to retrieve sales order details')
      setSelectedSO(data)
    } catch (err) {
      setCustomerError(err.detail || 'Could not load order details.')
    } finally {
      setCustomerLoading(false)
    }
  }

  async function fetchCustomerInvoices() {
    if (!customerSession?.access_token) return
    setCustomerLoading(true)
    setCustomerError(null)
    try {
      const data = await apiFetch('/api/portal/customer/invoices', {
        headers: { Authorization: `Bearer ${customerSession.access_token}` },
      }, 'Failed to retrieve invoices')
      setCustomerInvoices(data.items || [])
    } catch (err) {
      setCustomerError(err.detail || 'Could not retrieve invoices.')
    } finally {
      setCustomerLoading(false)
    }
  }

  async function fetchCustomerShipments() {
    if (!customerSession?.access_token) return
    setCustomerLoading(true)
    setCustomerError(null)
    try {
      const data = await apiFetch('/api/portal/customer/shipments', {
        headers: { Authorization: `Bearer ${customerSession.access_token}` },
      }, 'Failed to retrieve shipments')
      setCustomerShipments(data.items || [])
    } catch (err) {
      setCustomerError(err.detail || 'Could not retrieve shipments.')
    } finally {
      setCustomerLoading(false)
    }
  }

  async function downloadAuthorizedDocument(docId, filename, token) {
    try {
      const res = await fetch(`${API_BASE}/api/portal/documents/${docId}/download`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}))
        throw new Error(errJson.detail || `Download failed with HTTP ${res.status}`)
      }
      const blob = await res.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename || `document_${docId}`
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch (err) {
      alert(`Could not download document: ${err.message}`)
    }
  }

  // ==========================================
  // Internal Staff Partner Management
  // ==========================================

  async function fetchAdminInvitations() {
    setAdminLoading(true)
    try {
      const data = await apiFetch('/api/portal/admin/invitations', {}, 'Failed to load invitations')
      setInvitationsList(data.items || [])
    } catch (err) {
      setAdminError(err.detail || 'Could not retrieve invitations.')
    } finally {
      setAdminLoading(false)
    }
  }

  async function fetchAdminUsers() {
    try {
      const data = await apiFetch('/api/portal/admin/users', {}, 'Failed to load portal users')
      setPortalUsersList(data.items || [])
    } catch {}
  }

  async function fetchMasterOrganizations() {
    try {
      const [sups, custs] = await Promise.all([
        apiFetch('/api/suppliers', {}, 'Failed to load suppliers'),
        apiFetch('/api/customers', {}, 'Failed to load customers'),
      ])
      setSuppliersMaster(sups.items || [])
      setCustomersMaster(custs.items || [])
    } catch {}
  }

  async function handleCreateInvitation(e) {
    if (e) e.preventDefault()
    setAdminError(null)
    setAdminLoading(true)
    try {
      const data = await apiFetch('/api/portal/admin/invitations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(inviteFormData),
      }, 'Failed to create invitation')

      setGeneratedInvite(data)
      setAdminSuccess(`Invitation generated successfully for ${data.organization_name}!`)
      fetchAdminInvitations()
      setIsInviteModalOpen(false)
    } catch (err) {
      setAdminError(err.detail || 'Failed to generate invitation.')
    } finally {
      setAdminLoading(false)
    }
  }

  async function handleRevokeInvitation(invId) {
    if (!confirm('Are you sure you want to revoke this invitation? The link will immediately stop working.')) return
    try {
      await apiFetch(`/api/portal/admin/invitations/${invId}/revoke`, { method: 'POST' }, 'Revoke failed')
      fetchAdminInvitations()
    } catch (err) {
      alert(err.detail || 'Could not revoke invitation.')
    }
  }

  async function handleDeactivatePortalUser(userId, username) {
    if (!confirm(`Are you sure you want to deactivate external user "${username}"? All active bearer tokens will be revoked immediately.`)) return
    try {
      await apiFetch(`/api/portal/admin/users/${userId}/deactivate`, { method: 'POST' }, 'Deactivation failed')
      fetchAdminUsers()
    } catch (err) {
      alert(err.detail || 'Could not deactivate user.')
    }
  }

  // Initial Load Effects
  useEffect(() => {
    if (activePortal === 'supplier' && supplierSession) {
      fetchSupplierPurchaseOrders()
    } else if (activePortal === 'customer' && customerSession) {
      if (customerTab === 'orders') fetchCustomerSalesOrders()
      else if (customerTab === 'invoices') fetchCustomerInvoices()
      else if (customerTab === 'shipments') fetchCustomerShipments()
    } else if (activePortal === 'admin_invitations') {
      fetchAdminInvitations()
      fetchAdminUsers()
      fetchMasterOrganizations()
    }
  }, [activePortal, supplierSession, customerSession, customerTab])

  return (
    <div className="portal-container" style={{ padding: '24px 32px' }}>
      {/* Top Header Banner */}
      <div className="portal-header-bar" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24, borderBottom: '1px solid var(--navy-800)', paddingBottom: 16 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ background: 'linear-gradient(135deg, #0d9488, #3b82f6)', padding: '6px 12px', borderRadius: 8, color: '#fff', fontSize: 13, fontWeight: 700, letterSpacing: 0.5 }}>
              PHASE 9A COLLABORATION
            </span>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800 }}>External Partner Portals &amp; Security</h1>
          </div>
          <p style={{ margin: '4px 0 0', color: 'var(--slate-400)', fontSize: 13 }}>
            Authoritative, isolated portals for external suppliers and customers with strict IDOR defenses.
          </p>
        </div>

        {/* Portal Switcher Tabs */}
        <div style={{ display: 'flex', gap: 8, background: 'var(--navy-900)', padding: 4, borderRadius: 10, border: '1px solid var(--navy-800)' }}>
          <button
            className={`btn-sm ${activePortal === 'supplier' ? 'btn-primary-sm' : 'btn-secondary'}`}
            onClick={() => setActivePortal('supplier')}
          >
            <ShoppingCart size={14} />
            <span>Supplier Portal</span>
            {supplierSession && <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#10b981', display: 'inline-block' }} />}
          </button>
          <button
            className={`btn-sm ${activePortal === 'customer' ? 'btn-primary-sm' : 'btn-secondary'}`}
            onClick={() => setActivePortal('customer')}
          >
            <Users size={14} />
            <span>Customer Portal</span>
            {customerSession && <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#10b981', display: 'inline-block' }} />}
          </button>
          <button
            className={`btn-sm ${activePortal === 'admin_invitations' ? 'btn-primary-sm' : 'btn-secondary'}`}
            onClick={() => setActivePortal('admin_invitations')}
          >
            <KeyRound size={14} />
            <span>Internal Invitation Manager</span>
          </button>
          <button
            className={`btn-sm ${activePortal === 'staff_review' ? 'btn-primary-sm' : 'btn-secondary'}`}
            onClick={() => setActivePortal('staff_review')}
          >
            <ShieldCheck size={14} />
            <span>Staff Review Console</span>
          </button>
        </div>
      </div>

      {/* Global Banner Messages */}
      {authSuccess && (
        <div className="clean-audit-card" style={{ marginBottom: 20, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <CheckCircle2 size={18} color="var(--emerald-400)" />
            <span>{authSuccess}</span>
          </div>
          <button onClick={() => setAuthSuccess(null)} style={{ background: 'transparent', border: 'none', color: 'var(--slate-400)', cursor: 'pointer' }}>
            <X size={16} />
          </button>
        </div>
      )}

      {authError && (
        <div className="error-banner" style={{ marginBottom: 20, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <ShieldAlert size={18} color="var(--rose-400)" />
            <span>{authError}</span>
          </div>
          <button onClick={() => setAuthError(null)} style={{ background: 'transparent', border: 'none', color: 'var(--slate-400)', cursor: 'pointer' }}>
            <X size={16} />
          </button>
        </div>
      )}

      {/* ========================================================
          1. SUPPLIER PORTAL PERSPECTIVE
          ======================================================== */}
      {activePortal === 'supplier' && (
        <div>
          {!supplierSession ? (
            /* Unauthenticated Supplier View: Login / Activation */
            <div className="panel" style={{ maxWidth: 460, margin: '40px auto', padding: 28 }}>
              <div style={{ textAlign: 'center', marginBottom: 24 }}>
                <div style={{ width: 48, height: 48, borderRadius: 12, background: 'rgba(20, 184, 166, 0.15)', color: 'var(--teal-300)', display: 'grid', placeItems: 'center', margin: '0 auto 12px' }}>
                  <ShoppingCart size={24} />
                </div>
                <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>Supplier Portal Sign In</h2>
                <p style={{ margin: '4px 0 0', color: 'var(--slate-400)', fontSize: 13 }}>
                  Access purchase orders, submit acknowledgements, and track receipts.
                </p>
              </div>

              <div style={{ display: 'flex', borderBottom: '1px solid var(--navy-800)', marginBottom: 20 }}>
                <button
                  style={{ flex: 1, padding: '10px 0', background: 'transparent', border: 'none', borderBottom: authMode === 'login' ? '2px solid var(--teal-400)' : 'none', color: authMode === 'login' ? '#fff' : 'var(--slate-400)', fontWeight: 600, cursor: 'pointer' }}
                  onClick={() => setAuthMode('login')}
                >
                  Sign In
                </button>
                <button
                  style={{ flex: 1, padding: '10px 0', background: 'transparent', border: 'none', borderBottom: authMode === 'activate' ? '2px solid var(--teal-400)' : 'none', color: authMode === 'activate' ? '#fff' : 'var(--slate-400)', fontWeight: 600, cursor: 'pointer' }}
                  onClick={() => setAuthMode('activate')}
                >
                  Activate Account
                </button>
              </div>

              {authMode === 'login' ? (
                <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  <div>
                    <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>Username or Email</label>
                    <input
                      type="text"
                      className="form-control"
                      placeholder="e.g. supplier_user"
                      value={loginUsername}
                      onChange={(e) => setLoginUsername(e.target.value)}
                      required
                      style={{ width: '100%', padding: '10px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff' }}
                    />
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>Password</label>
                    <input
                      type="password"
                      className="form-control"
                      placeholder="••••••••"
                      value={loginPassword}
                      onChange={(e) => setLoginPassword(e.target.value)}
                      required
                      style={{ width: '100%', padding: '10px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff' }}
                    />
                  </div>
                  <button
                    type="submit"
                    className="primary-button"
                    disabled={authLoading}
                    style={{ marginTop: 8 }}
                  >
                    {authLoading ? 'Signing in...' : 'Sign In to Supplier Portal'}
                  </button>
                </form>
              ) : (
                /* Activation with Invitation Token */
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  <div>
                    <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>Invitation Token</label>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <input
                        type="text"
                        placeholder="Paste single-use invitation token..."
                        value={invitationTokenInput}
                        onChange={(e) => setInvitationTokenInput(e.target.value)}
                        style={{ flex: 1, padding: '10px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff' }}
                      />
                      <button
                        type="button"
                        className="btn-sm btn-secondary"
                        onClick={() => handleVerifyInvitation()}
                        disabled={authLoading || !invitationTokenInput.trim()}
                      >
                        Verify
                      </button>
                    </div>
                  </div>

                  {verifiedInvitation && (
                    <form onSubmit={handleActivateAccount} style={{ display: 'flex', flexDirection: 'column', gap: 14, marginTop: 8 }}>
                      <div className="clean-audit-card" style={{ padding: 12 }}>
                        <div style={{ fontSize: 12, color: 'var(--slate-400)' }}>VERIFIED ORGANIZATION</div>
                        <strong style={{ fontSize: 14 }}>{verifiedInvitation.organization_name}</strong>
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>Choose Username</label>
                        <input
                          type="text"
                          placeholder="e.g. alpha_procurement_lead"
                          value={activateUsername}
                          onChange={(e) => setActivateUsername(e.target.value)}
                          required
                          style={{ width: '100%', padding: '10px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff' }}
                        />
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>Create Strong Password (min 8 chars)</label>
                        <input
                          type="password"
                          placeholder="••••••••"
                          value={activatePassword}
                          onChange={(e) => setActivatePassword(e.target.value)}
                          required
                          minLength={8}
                          style={{ width: '100%', padding: '10px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff' }}
                        />
                      </div>
                      <button type="submit" className="primary-button" disabled={authLoading}>
                        {authLoading ? 'Activating...' : 'Activate & Enter Portal'}
                      </button>
                    </form>
                  )}
                </div>
              )}
            </div>
          ) : (
            /* Authenticated Supplier Dashboard */
            <div>
              {/* Supplier Identity Top Bar */}
              <div className="panel" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 20px', marginBottom: 20 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                  <div style={{ width: 36, height: 36, borderRadius: '50%', background: 'rgba(20, 184, 166, 0.2)', color: 'var(--teal-300)', display: 'grid', placeItems: 'center', fontWeight: 700 }}>
                    {supplierSession.user.organization_name.slice(0, 2).toUpperCase()}
                  </div>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <strong style={{ fontSize: 15 }}>{supplierSession.user.organization_name}</strong>
                      <span className="provenance-pill status-ready" style={{ fontSize: 11 }}>VERIFIED SUPPLIER</span>
                    </div>
                    <small style={{ color: 'var(--slate-400)' }}>
                      Signed in as <strong>{supplierSession.user.username}</strong> ({supplierSession.user.email})
                    </small>
                  </div>
                </div>

                <div style={{ display: 'flex', gap: 10 }}>
                  <button className="btn-sm btn-secondary" onClick={fetchSupplierPurchaseOrders} disabled={supplierLoading}>
                    <RefreshCw size={13} className={supplierLoading ? 'spin' : ''} /> Refresh
                  </button>
                  <button className="btn-sm btn-secondary" onClick={() => handleLogout('supplier')} style={{ color: 'var(--rose-400)' }}>
                    <LogOut size={13} /> Sign Out
                  </button>
                </div>
              </div>

              {/* Supplier Subtabs Navigation (Phase 9B) */}
              <div style={{ display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap' }}>
                <button
                  className={`btn-sm ${supplierSubTab === 'pos' ? 'btn-primary-sm' : 'btn-secondary'}`}
                  onClick={() => { setSupplierSubTab('pos'); setSelectedPO(null); }}
                >
                  <ShoppingCart size={14} /> Orders &amp; Acknowledgements
                </button>
                <button
                  className={`btn-sm ${supplierSubTab === 'commitments' ? 'btn-primary-sm' : 'btn-secondary'}`}
                  onClick={() => setSupplierSubTab('commitments')}
                >
                  <Calendar size={14} /> Delivery Commitments
                </button>
                <button
                  className={`btn-sm ${supplierSubTab === 'asns' ? 'btn-primary-sm' : 'btn-secondary'}`}
                  onClick={() => setSupplierSubTab('asns')}
                >
                  <Truck size={14} /> Advance Shipment Notices (ASN)
                </button>
                <button
                  className={`btn-sm ${supplierSubTab === 'documents' ? 'btn-primary-sm' : 'btn-secondary'}`}
                  onClick={() => setSupplierSubTab('documents')}
                >
                  <FileText size={14} /> Document Submissions
                </button>
                <button
                  className={`btn-sm ${supplierSubTab === 'discrepancies' ? 'btn-primary-sm' : 'btn-secondary'}`}
                  onClick={() => setSupplierSubTab('discrepancies')}
                >
                  <AlertTriangle size={14} /> Delivery Discrepancies
                </button>
              </div>

              {/* Subtab 1: Purchase Orders & Acknowledgement */}
              {supplierSubTab === 'pos' && (
                <div>
                  {/* Purchase Order Detail View vs Orders List */}
                  {selectedPO ? (
                    /* PO Detail View with Acknowledgement Form */
                    <div className="panel" style={{ padding: 24 }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20, borderBottom: '1px solid var(--navy-800)', paddingBottom: 14 }}>
                    <button className="btn-sm btn-secondary" onClick={() => setSelectedPO(null)}>
                      <ArrowLeft size={14} /> Back to Purchase Orders
                    </button>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <span style={{ fontSize: 12, color: 'var(--slate-400)' }}>PO ACKNOWLEDGEMENT:</span>
                      <span className={`status-tag status-${selectedPO.supplier_ack_status || 'unacknowledged'}`}>
                        {(selectedPO.supplier_ack_status || 'unacknowledged').toUpperCase()}
                      </span>
                    </div>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16, marginBottom: 24 }} className="fields-grid">
                    <div className="field-cell">
                      <small>PO NUMBER</small>
                      <strong>{selectedPO.po_number}</strong>
                    </div>
                    <div className="field-cell">
                      <small>ORDER DATE</small>
                      <strong>{selectedPO.order_date}</strong>
                    </div>
                    <div className="field-cell">
                      <small>EXPECTED DELIVERY</small>
                      <strong>{selectedPO.expected_delivery_date || 'Not specified'}</strong>
                    </div>
                    <div className="field-cell">
                      <small>PAYMENT TERMS</small>
                      <strong>{selectedPO.payment_terms || 'Net 30'}</strong>
                    </div>
                    <div className="field-cell">
                      <small>GRAND TOTAL</small>
                      <strong style={{ color: 'var(--teal-300)' }}>
                        {selectedPO.currency} {Number(selectedPO.grand_total).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                      </strong>
                    </div>
                  </div>

                  {/* PO Line Items */}
                  <h3 style={{ fontSize: 15, fontWeight: 700, margin: '20px 0 10px' }}>Ordered Items</h3>
                  <div style={{ overflowX: 'auto', marginBottom: 28 }}>
                    <table className="portal-table" style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
                      <thead>
                        <tr style={{ background: 'var(--navy-900)', borderBottom: '1px solid var(--navy-800)' }}>
                          <th style={{ padding: 10 }}>SKU</th>
                          <th style={{ padding: 10 }}>Product Name</th>
                          <th style={{ padding: 10 }}>UOM</th>
                          <th style={{ padding: 10, textAlign: 'right' }}>Ordered Qty</th>
                          <th style={{ padding: 10, textAlign: 'right' }}>Unit Price</th>
                          <th style={{ padding: 10, textAlign: 'right' }}>Line Total</th>
                          <th style={{ padding: 10, textAlign: 'right' }}>Received Qty</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedPO.items?.map((item) => (
                          <tr key={item.id} style={{ borderBottom: '1px solid var(--navy-800)' }}>
                            <td style={{ padding: 10 }}><code>{item.sku}</code></td>
                            <td style={{ padding: 10 }}>{item.product_name}</td>
                            <td style={{ padding: 10 }}>{item.uom}</td>
                            <td style={{ padding: 10, textAlign: 'right', fontWeight: 700 }}>{item.ordered_qty}</td>
                            <td style={{ padding: 10, textAlign: 'right' }}>{Number(item.unit_price).toFixed(2)}</td>
                            <td style={{ padding: 10, textAlign: 'right', fontWeight: 700 }}>{Number(item.line_total).toFixed(2)}</td>
                            <td style={{ padding: 10, textAlign: 'right', color: item.received_qty > 0 ? 'var(--emerald-400)' : 'var(--slate-400)' }}>
                              {item.received_qty}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {/* Controlled Supplier Acknowledgement Section */}
                  <div className="panel" style={{ background: 'var(--navy-950)', border: '1px solid var(--navy-800)', padding: 20, borderRadius: 10, marginBottom: 24 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                      <CheckCircle2 size={18} color="var(--teal-400)" />
                      <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Supplier Order Acknowledgement</h3>
                    </div>
                    <p style={{ margin: '0 0 16px', fontSize: 13, color: 'var(--slate-400)' }}>
                      Formally accept, reject, or request clarification on this purchase order. This creates an immutable external audit record without mutating inventory or internal terms.
                    </p>

                    {ackFeedback && (
                      <div className={ackFeedback.type === 'success' ? 'clean-audit-card' : 'error-banner'} style={{ marginBottom: 14 }}>
                        {ackFeedback.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}
                        <span>{ackFeedback.message}</span>
                      </div>
                    )}

                    <form onSubmit={handleSubmitAcknowledgement} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                      <div>
                        <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 8 }}>Acknowledgement Action</label>
                        <div style={{ display: 'flex', gap: 10 }}>
                          <button
                            type="button"
                            className={`btn-sm ${ackAction === 'accept' ? 'btn-primary-sm' : 'btn-secondary'}`}
                            onClick={() => setAckAction('accept')}
                            style={{ flex: 1, padding: 10, borderColor: ackAction === 'accept' ? 'var(--emerald-500)' : undefined }}
                          >
                            <Check size={14} /> Accept Order
                          </button>
                          <button
                            type="button"
                            className={`btn-sm ${ackAction === 'request_clarification' ? 'btn-primary-sm' : 'btn-secondary'}`}
                            onClick={() => setAckAction('request_clarification')}
                            style={{ flex: 1, padding: 10, borderColor: ackAction === 'request_clarification' ? 'var(--amber-500)' : undefined }}
                          >
                            <Clock size={14} /> Request Clarification
                          </button>
                          <button
                            type="button"
                            className={`btn-sm ${ackAction === 'reject' ? 'btn-primary-sm' : 'btn-secondary'}`}
                            onClick={() => setAckAction('reject')}
                            style={{ flex: 1, padding: 10, borderColor: ackAction === 'reject' ? 'var(--rose-500)' : undefined }}
                          >
                            <XCircle size={14} /> Reject Order
                          </button>
                        </div>
                      </div>

                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 200px', gap: 14 }}>
                        <div>
                          <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>
                            Supplier Notes &amp; Comments <span style={{ color: 'var(--slate-400)' }}>({ackComments.length}/1000)</span>
                          </label>
                          <textarea
                            rows={3}
                            placeholder="Add notes, clarifications, or batch dispatch details..."
                            value={ackComments}
                            onChange={(e) => setAckComments(e.target.value.slice(0, 1000))}
                            style={{ width: '100%', padding: '8px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
                          />
                        </div>
                        <div>
                          <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>Proposed Delivery Date</label>
                          <input
                            type="date"
                            value={ackProposedDate}
                            onChange={(e) => setAckProposedDate(e.target.value)}
                            style={{ width: '100%', padding: '8px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
                          />
                        </div>
                      </div>

                      <button
                        type="submit"
                        className="primary-button"
                        disabled={ackLoading}
                        style={{ alignSelf: 'flex-start', minWidth: 200 }}
                      >
                        {ackLoading ? 'Submitting Acknowledgement...' : 'Submit Acknowledgement'}
                      </button>
                    </form>
                  </div>

                  {/* Past Acknowledgement Audit Trail */}
                  {selectedPO.acknowledgement_history?.length > 0 && (
                    <div style={{ marginTop: 20 }}>
                      <h4 style={{ fontSize: 14, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 10 }}>Immutable Acknowledgement Audit History</h4>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                        {selectedPO.acknowledgement_history.map((ack) => (
                          <div key={ack.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', background: 'var(--navy-900)', borderRadius: 8, border: '1px solid var(--navy-800)' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                              <span className={`status-tag status-${ack.action}`}>{ack.action.toUpperCase()}</span>
                              <span style={{ fontSize: 13 }}>{ack.supplier_comments || 'No comments recorded'}</span>
                            </div>
                            <div style={{ fontSize: 12, color: 'var(--slate-400)' }}>
                              by <strong>{ack.portal_username}</strong> on {new Date(ack.created_at).toLocaleString()}
                              {ack.proposed_delivery_date && ` • Proposed Delivery: ${ack.proposed_delivery_date}`}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                /* POs List Table */
                <div className="panel" style={{ padding: 20 }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, gap: 12, flexWrap: 'wrap' }}>
                    <div style={{ display: 'flex', gap: 10, flex: 1, maxWidth: 500 }}>
                      <div style={{ position: 'relative', flex: 1 }}>
                        <Search size={14} style={{ position: 'absolute', left: 10, top: 11, color: 'var(--slate-400)' }} />
                        <input
                          type="text"
                          placeholder="Search PO Number..."
                          value={supplierSearch}
                          onChange={(e) => setSupplierSearch(e.target.value)}
                          onKeyDown={(e) => e.key === 'Enter' && fetchSupplierPurchaseOrders()}
                          style={{ width: '100%', padding: '8px 12px 8px 32px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
                        />
                      </div>
                      <select
                        value={supplierStatusFilter}
                        onChange={(e) => {
                          setSupplierStatusFilter(e.target.value)
                          fetchSupplierPurchaseOrders()
                        }}
                        style={{ padding: '8px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff', fontSize: 13 }}
                      >
                        <option value="">All Statuses</option>
                        <option value="submitted">Submitted</option>
                        <option value="approved">Approved</option>
                        <option value="cancelled">Cancelled</option>
                      </select>
                    </div>

                    <span style={{ fontSize: 13, color: 'var(--slate-400)' }}>
                      Total Orders: <strong>{supplierTotalPOs}</strong>
                    </span>
                  </div>

                  {supplierLoading ? (
                    <div className="loading-card" style={{ padding: 40, textAlign: 'center' }}>
                      <RefreshCw size={28} className="spin" style={{ margin: '0 auto 10px' }} />
                      <p>Loading purchase orders...</p>
                    </div>
                  ) : supplierPOs.length === 0 ? (
                    <div className="empty-results-card" style={{ padding: 40, textAlign: 'center' }}>
                      <ShoppingCart size={40} style={{ margin: '0 auto 10px', color: 'var(--slate-400)' }} />
                      <p>No purchase orders found for your organization.</p>
                    </div>
                  ) : (
                    <table className="portal-table" style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
                      <thead>
                        <tr style={{ background: 'var(--navy-900)', borderBottom: '1px solid var(--navy-800)' }}>
                          <th style={{ padding: 10 }}>PO Number</th>
                          <th style={{ padding: 10 }}>Order Date</th>
                          <th style={{ padding: 10 }}>Expected Delivery</th>
                          <th style={{ padding: 10 }}>Grand Total</th>
                          <th style={{ padding: 10 }}>Internal Status</th>
                          <th style={{ padding: 10 }}>Your Ack</th>
                          <th style={{ padding: 10, textAlign: 'right' }}>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {supplierPOs.map((po) => (
                          <tr key={po.id} style={{ borderBottom: '1px solid var(--navy-800)' }}>
                            <td style={{ padding: 10 }}>
                              <strong style={{ color: 'var(--teal-300)' }}>{po.po_number}</strong>
                              <div style={{ fontSize: 11, color: 'var(--slate-400)' }}>{po.item_count} line items</div>
                            </td>
                            <td style={{ padding: 10 }}>{po.order_date}</td>
                            <td style={{ padding: 10 }}>{po.expected_delivery_date || '—'}</td>
                            <td style={{ padding: 10, fontWeight: 700 }}>
                              {po.currency} {Number(po.grand_total).toFixed(2)}
                            </td>
                            <td style={{ padding: 10 }}>
                              <span className={`status-tag status-${po.status}`}>{po.status.toUpperCase()}</span>
                            </td>
                            <td style={{ padding: 10 }}>
                              <span className={`status-tag status-${po.supplier_ack_status || 'unacknowledged'}`}>
                                {(po.supplier_ack_status || 'unacknowledged').toUpperCase()}
                              </span>
                            </td>
                            <td style={{ padding: 10, textAlign: 'right' }}>
                              <button className="btn-sm btn-primary-sm" onClick={() => fetchPODetail(po.id)}>
                                View &amp; Acknowledge
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}
                </div>
              )}

              {/* Subtab 2: Delivery Commitments */}
              {supplierSubTab === 'commitments' && (
                <SupplierCommitmentsSection
                  supplierSession={supplierSession}
                  supplierPOs={supplierPOs}
                  onRefreshPOs={fetchSupplierPurchaseOrders}
                />
              )}

              {/* Subtab 3: Advance Shipment Notices */}
              {supplierSubTab === 'asns' && (
                <SupplierASNsSection
                  supplierSession={supplierSession}
                  supplierPOs={supplierPOs}
                />
              )}

              {/* Subtab 4: Document Submissions */}
              {supplierSubTab === 'documents' && (
                <SupplierDocumentsSection
                  supplierSession={supplierSession}
                  supplierPOs={supplierPOs}
                />
              )}

              {/* Subtab 5: Delivery Discrepancies */}
              {supplierSubTab === 'discrepancies' && (
                <SupplierDiscrepanciesSection
                  supplierSession={supplierSession}
                  supplierPOs={supplierPOs}
                />
              )}
            </div>
          )}
        </div>
      )}

      {/* ========================================================
          2. CUSTOMER PORTAL PERSPECTIVE (READ-ONLY)
          ======================================================== */}
      {activePortal === 'customer' && (
        <div>
          {!customerSession ? (
            /* Unauthenticated Customer View: Login / Activation */
            <div className="panel" style={{ maxWidth: 460, margin: '40px auto', padding: 28 }}>
              <div style={{ textAlign: 'center', marginBottom: 24 }}>
                <div style={{ width: 48, height: 48, borderRadius: 12, background: 'rgba(59, 130, 246, 0.15)', color: 'var(--blue-400)', display: 'grid', placeItems: 'center', margin: '0 auto 12px' }}>
                  <Users size={24} />
                </div>
                <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>Customer Portal Sign In</h2>
                <p style={{ margin: '4px 0 0', color: 'var(--slate-400)', fontSize: 13 }}>
                  Track sales orders, view dispatches, inspect invoices, and download shared documents.
                </p>
              </div>

              <div style={{ display: 'flex', borderBottom: '1px solid var(--navy-800)', marginBottom: 20 }}>
                <button
                  style={{ flex: 1, padding: '10px 0', background: 'transparent', border: 'none', borderBottom: authMode === 'login' ? '2px solid var(--blue-400)' : 'none', color: authMode === 'login' ? '#fff' : 'var(--slate-400)', fontWeight: 600, cursor: 'pointer' }}
                  onClick={() => setAuthMode('login')}
                >
                  Sign In
                </button>
                <button
                  style={{ flex: 1, padding: '10px 0', background: 'transparent', border: 'none', borderBottom: authMode === 'activate' ? '2px solid var(--blue-400)' : 'none', color: authMode === 'activate' ? '#fff' : 'var(--slate-400)', fontWeight: 600, cursor: 'pointer' }}
                  onClick={() => setAuthMode('activate')}
                >
                  Activate Account
                </button>
              </div>

              {authMode === 'login' ? (
                <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  <div>
                    <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>Username or Email</label>
                    <input
                      type="text"
                      placeholder="e.g. customer_lead"
                      value={loginUsername}
                      onChange={(e) => setLoginUsername(e.target.value)}
                      required
                      style={{ width: '100%', padding: '10px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff' }}
                    />
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>Password</label>
                    <input
                      type="password"
                      placeholder="••••••••"
                      value={loginPassword}
                      onChange={(e) => setLoginPassword(e.target.value)}
                      required
                      style={{ width: '100%', padding: '10px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff' }}
                    />
                  </div>
                  <button type="submit" className="primary-button" disabled={authLoading} style={{ marginTop: 8 }}>
                    {authLoading ? 'Signing in...' : 'Sign In to Customer Portal'}
                  </button>
                </form>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  <div>
                    <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>Invitation Token</label>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <input
                        type="text"
                        placeholder="Paste single-use invitation token..."
                        value={invitationTokenInput}
                        onChange={(e) => setInvitationTokenInput(e.target.value)}
                        style={{ flex: 1, padding: '10px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff' }}
                      />
                      <button
                        type="button"
                        className="btn-sm btn-secondary"
                        onClick={() => handleVerifyInvitation()}
                        disabled={authLoading || !invitationTokenInput.trim()}
                      >
                        Verify
                      </button>
                    </div>
                  </div>

                  {verifiedInvitation && (
                    <form onSubmit={handleActivateAccount} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                      <div className="clean-audit-card" style={{ padding: 12 }}>
                        <div style={{ fontSize: 12, color: 'var(--slate-400)' }}>CUSTOMER ORGANIZATION</div>
                        <strong>{verifiedInvitation.organization_name}</strong>
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>Choose Username</label>
                        <input
                          type="text"
                          placeholder="e.g. global_procurement_user"
                          value={activateUsername}
                          onChange={(e) => setActivateUsername(e.target.value)}
                          required
                          style={{ width: '100%', padding: '10px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff' }}
                        />
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>Password (min 8 chars)</label>
                        <input
                          type="password"
                          placeholder="••••••••"
                          value={activatePassword}
                          onChange={(e) => setActivatePassword(e.target.value)}
                          required
                          minLength={8}
                          style={{ width: '100%', padding: '10px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff' }}
                        />
                      </div>
                      <button type="submit" className="primary-button" disabled={authLoading}>
                        Activate Account
                      </button>
                    </form>
                  )}
                </div>
              )}
            </div>
          ) : (
            /* Authenticated Customer Portal */
            <div>
              {/* Customer Top Bar */}
              <div className="panel" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 20px', marginBottom: 20 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                  <div style={{ width: 36, height: 36, borderRadius: '50%', background: 'rgba(59, 130, 246, 0.2)', color: 'var(--blue-400)', display: 'grid', placeItems: 'center', fontWeight: 700 }}>
                    {customerSession.user.organization_name.slice(0, 2).toUpperCase()}
                  </div>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <strong style={{ fontSize: 15 }}>{customerSession.user.organization_name}</strong>
                      <span className="provenance-pill status-ready" style={{ fontSize: 11 }}>VERIFIED CUSTOMER</span>
                    </div>
                    <small style={{ color: 'var(--slate-400)' }}>
                      Signed in as <strong>{customerSession.user.username}</strong> ({customerSession.user.email})
                    </small>
                  </div>
                </div>

                <div style={{ display: 'flex', gap: 10 }}>
                  <button className="btn-sm btn-secondary" onClick={() => handleLogout('customer')} style={{ color: 'var(--rose-400)' }}>
                    <LogOut size={13} /> Sign Out
                  </button>
                </div>
              </div>

              {/* Sub-Tabs: Sales Orders, Inquiries, Document Requests, Notifications, Invoices, Shipments */}
              <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
                <button
                  className={`btn-sm ${customerTab === 'orders' ? 'btn-primary-sm' : 'btn-secondary'}`}
                  onClick={() => {
                    setCustomerTab('orders')
                    setSelectedSO(null)
                  }}
                >
                  <ShoppingBag size={14} /> Sales Orders
                </button>
                <button
                  className={`btn-sm ${customerTab === 'threads' ? 'btn-primary-sm' : 'btn-secondary'}`}
                  onClick={() => setCustomerTab('threads')}
                >
                  <MessageSquare size={14} /> Order Inquiries
                </button>
                <button
                  className={`btn-sm ${customerTab === 'doc_requests' ? 'btn-primary-sm' : 'btn-secondary'}`}
                  onClick={() => setCustomerTab('doc_requests')}
                >
                  <FileText size={14} /> Document Requests
                </button>
                <button
                  className={`btn-sm ${customerTab === 'notifications' ? 'btn-primary-sm' : 'btn-secondary'}`}
                  onClick={() => setCustomerTab('notifications')}
                >
                  <Bell size={14} /> Notifications
                </button>
                <button
                  className={`btn-sm ${customerTab === 'invoices' ? 'btn-primary-sm' : 'btn-secondary'}`}
                  onClick={() => {
                    setCustomerTab('invoices')
                    setSelectedInvoice(null)
                  }}
                >
                  <Receipt size={14} /> Issued Invoices
                </button>
                <button
                  className={`btn-sm ${customerTab === 'shipments' ? 'btn-primary-sm' : 'btn-secondary'}`}
                  onClick={() => setCustomerTab('shipments')}
                >
                  <Truck size={14} /> Export Shipments &amp; Tracking
                </button>
              </div>

              {/* Sub-Tab 1: Sales Orders */}
              {customerTab === 'orders' && (
                selectedSO ? (
                  /* Sales Order Detail */
                  <div className="panel" style={{ padding: 24 }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
                      <button className="btn-sm btn-secondary" onClick={() => setSelectedSO(null)}>
                        <ArrowLeft size={14} /> Back to Sales Orders
                      </button>
                      <span className={`status-tag status-${selectedSO.status}`}>{selectedSO.status.toUpperCase()}</span>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16, marginBottom: 24 }} className="fields-grid">
                      <div className="field-cell">
                        <small>ORDER NUMBER</small>
                        <strong>{selectedSO.order_number}</strong>
                      </div>
                      <div className="field-cell">
                        <small>ORDER DATE</small>
                        <strong>{selectedSO.order_date}</strong>
                      </div>
                      <div className="field-cell">
                        <small>REQUESTED DELIVERY</small>
                        <strong>{selectedSO.requested_delivery_date || 'Standard'}</strong>
                      </div>
                      <div className="field-cell">
                        <small>TOTAL VALUE</small>
                        <strong style={{ color: 'var(--blue-400)' }}>
                          {selectedSO.currency} {Number(selectedSO.grand_total).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                        </strong>
                      </div>
                    </div>

                    {/* Order Line Items */}
                    <h3 style={{ fontSize: 15, fontWeight: 700, margin: '20px 0 10px' }}>Order Lines &amp; Fulfilment Progress</h3>
                    <div style={{ overflowX: 'auto', marginBottom: 24 }}>
                      <table className="portal-table" style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
                        <thead>
                          <tr style={{ background: 'var(--navy-900)', borderBottom: '1px solid var(--navy-800)' }}>
                            <th style={{ padding: 10 }}>SKU</th>
                            <th style={{ padding: 10 }}>Product Name</th>
                            <th style={{ padding: 10, textAlign: 'right' }}>Ordered</th>
                            <th style={{ padding: 10, textAlign: 'right' }}>Allocated</th>
                            <th style={{ padding: 10, textAlign: 'right' }}>Picked</th>
                            <th style={{ padding: 10, textAlign: 'right' }}>Dispatched</th>
                            <th style={{ padding: 10, textAlign: 'right' }}>Delivered</th>
                          </tr>
                        </thead>
                        <tbody>
                          {selectedSO.items?.map((item) => (
                            <tr key={item.id} style={{ borderBottom: '1px solid var(--navy-800)' }}>
                              <td style={{ padding: 10 }}><code>{item.product_sku}</code></td>
                              <td style={{ padding: 10 }}>{item.product_name}</td>
                              <td style={{ padding: 10, textAlign: 'right', fontWeight: 700 }}>{item.ordered_quantity}</td>
                              <td style={{ padding: 10, textAlign: 'right' }}>{item.allocated_quantity}</td>
                              <td style={{ padding: 10, textAlign: 'right' }}>{item.picked_quantity}</td>
                              <td style={{ padding: 10, textAlign: 'right', color: item.dispatched_quantity > 0 ? 'var(--emerald-400)' : undefined }}>
                                {item.dispatched_quantity}
                              </td>
                              <td style={{ padding: 10, textAlign: 'right', color: item.delivered_quantity > 0 ? 'var(--emerald-400)' : undefined }}>
                                {item.delivered_quantity}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>

                    {/* Dispatches & Tracking */}
                    {selectedSO.dispatches?.length > 0 && (
                      <div style={{ marginBottom: 24 }}>
                        <h3 style={{ fontSize: 15, fontWeight: 700, margin: '20px 0 10px' }}>Dispatches &amp; Carrier Tracking</h3>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                          {selectedSO.dispatches.map((disp) => (
                            <div key={disp.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', background: 'var(--navy-900)', borderRadius: 8, border: '1px solid var(--navy-800)' }}>
                              <div>
                                <strong style={{ color: 'var(--blue-400)' }}>{disp.dispatch_number}</strong>
                                <span style={{ marginLeft: 10, fontSize: 13, color: 'var(--slate-300)' }}>
                                  Carrier: <strong>{disp.carrier || 'Standard Freight'}</strong> • Tracking: <code>{disp.tracking_reference || 'Pending'}</code>
                                </span>
                              </div>
                              <span className={`status-tag status-${disp.status}`}>{disp.status.toUpperCase()}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Shared Documents */}
                    <div>
                      <h3 style={{ fontSize: 15, fontWeight: 700, margin: '20px 0 10px' }}>Approved Commercial Documents</h3>
                      {selectedSO.shared_documents?.length === 0 ? (
                        <p style={{ fontSize: 13, color: 'var(--slate-400)' }}>No documents currently shared for this order.</p>
                      ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                          {selectedSO.shared_documents.map((doc) => (
                            <div key={doc.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', background: 'var(--navy-900)', borderRadius: 8, border: '1px solid var(--navy-800)' }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                <FileText size={16} color="var(--blue-400)" />
                                <div>
                                  <strong style={{ fontSize: 13 }}>{doc.clean_filename || doc.original_filename}</strong>
                                  <span style={{ marginLeft: 8, fontSize: 11, color: 'var(--slate-400)' }}>
                                    ({(doc.file_size / 1024).toFixed(1)} KB)
                                  </span>
                                </div>
                              </div>
                              <button
                                className="btn-sm btn-secondary"
                                onClick={() => downloadAuthorizedDocument(doc.id, doc.clean_filename, customerSession.access_token)}
                              >
                                <Download size={13} /> Download
                              </button>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  /* Sales Orders List */
                  <div className="panel" style={{ padding: 20 }}>
                    <h3 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 14px' }}>Your Sales Orders</h3>
                    {customerLoading ? (
                      <div className="loading-card" style={{ padding: 40, textAlign: 'center' }}>
                        <RefreshCw size={28} className="spin" style={{ margin: '0 auto 10px' }} />
                        <p>Loading sales orders...</p>
                      </div>
                    ) : customerSOs.length === 0 ? (
                      <div className="empty-results-card" style={{ padding: 40, textAlign: 'center' }}>
                        <ShoppingBag size={40} style={{ margin: '0 auto 10px', color: 'var(--slate-400)' }} />
                        <p>No orders registered for your organization.</p>
                      </div>
                    ) : (
                      <table className="portal-table" style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
                        <thead>
                          <tr style={{ background: 'var(--navy-900)', borderBottom: '1px solid var(--navy-800)' }}>
                            <th style={{ padding: 10 }}>Order Number</th>
                            <th style={{ padding: 10 }}>Order Date</th>
                            <th style={{ padding: 10 }}>Requested Delivery</th>
                            <th style={{ padding: 10 }}>Total Value</th>
                            <th style={{ padding: 10 }}>Status</th>
                            <th style={{ padding: 10, textAlign: 'right' }}>Actions</th>
                          </tr>
                        </thead>
                        <tbody>
                          {customerSOs.map((so) => (
                            <tr key={so.id} style={{ borderBottom: '1px solid var(--navy-800)' }}>
                              <td style={{ padding: 10 }}>
                                <strong style={{ color: 'var(--blue-400)' }}>{so.order_number}</strong>
                                <div style={{ fontSize: 11, color: 'var(--slate-400)' }}>{so.item_count} items</div>
                              </td>
                              <td style={{ padding: 10 }}>{so.order_date}</td>
                              <td style={{ padding: 10 }}>{so.requested_delivery_date || 'Standard'}</td>
                              <td style={{ padding: 10, fontWeight: 700 }}>
                                {so.currency} {Number(so.grand_total).toFixed(2)}
                              </td>
                              <td style={{ padding: 10 }}>
                                <span className={`status-tag status-${so.status}`}>{so.status.toUpperCase()}</span>
                              </td>
                              <td style={{ padding: 10, textAlign: 'right' }}>
                                <button className="btn-sm btn-primary-sm" onClick={() => fetchCustomerSODetail(so.id)}>
                                  View Details &amp; Tracking
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

              {/* Sub-Tab 2: Issued Invoices */}
              {customerTab === 'invoices' && (
                <div className="panel" style={{ padding: 20 }}>
                  <h3 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 14px' }}>Issued Invoices &amp; Balances</h3>
                  {customerLoading ? (
                    <div className="loading-card" style={{ padding: 40, textAlign: 'center' }}>
                      <RefreshCw size={28} className="spin" style={{ margin: '0 auto 10px' }} />
                      <p>Loading invoices...</p>
                    </div>
                  ) : customerInvoices.length === 0 ? (
                    <div className="empty-results-card" style={{ padding: 40, textAlign: 'center' }}>
                      <Receipt size={40} style={{ margin: '0 auto 10px', color: 'var(--slate-400)' }} />
                      <p>No issued invoices found for your account.</p>
                    </div>
                  ) : (
                    <table className="portal-table" style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
                      <thead>
                        <tr style={{ background: 'var(--navy-900)', borderBottom: '1px solid var(--navy-800)' }}>
                          <th style={{ padding: 10 }}>Invoice Number</th>
                          <th style={{ padding: 10 }}>Invoice Date</th>
                          <th style={{ padding: 10 }}>Due Date</th>
                          <th style={{ padding: 10, textAlign: 'right' }}>Grand Total</th>
                          <th style={{ padding: 10, textAlign: 'right' }}>Amount Paid</th>
                          <th style={{ padding: 10, textAlign: 'right' }}>Balance Due</th>
                          <th style={{ padding: 10 }}>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {customerInvoices.map((inv) => (
                          <tr key={inv.id} style={{ borderBottom: '1px solid var(--navy-800)' }}>
                            <td style={{ padding: 10 }}>
                              <strong style={{ color: 'var(--teal-300)' }}>{inv.invoice_number}</strong>
                            </td>
                            <td style={{ padding: 10 }}>{inv.invoice_date}</td>
                            <td style={{ padding: 10 }}>{inv.due_date}</td>
                            <td style={{ padding: 10, textAlign: 'right', fontWeight: 700 }}>
                              {inv.currency} {Number(inv.grand_total).toFixed(2)}
                            </td>
                            <td style={{ padding: 10, textAlign: 'right', color: 'var(--emerald-400)' }}>
                              {inv.currency} {Number(inv.amount_paid).toFixed(2)}
                            </td>
                            <td style={{ padding: 10, textAlign: 'right', fontWeight: 700, color: inv.outstanding_balance > 0 ? 'var(--amber-400)' : 'var(--slate-400)' }}>
                              {inv.currency} {Number(inv.outstanding_balance).toFixed(2)}
                            </td>
                            <td style={{ padding: 10 }}>
                              <span className={`status-tag status-${inv.status}`}>{inv.status.toUpperCase()}</span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}

              {/* Sub-Tab 3: Shipments Tracking */}
              {customerTab === 'shipments' && (
                <div className="panel" style={{ padding: 20 }}>
                  <h3 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 14px' }}>Export Shipments &amp; Transit Status</h3>
                  {customerLoading ? (
                    <div className="loading-card" style={{ padding: 40, textAlign: 'center' }}>
                      <RefreshCw size={28} className="spin" style={{ margin: '0 auto 10px' }} />
                      <p>Loading export shipments...</p>
                    </div>
                  ) : customerShipments.length === 0 ? (
                    <div className="empty-results-card" style={{ padding: 40, textAlign: 'center' }}>
                      <Truck size={40} style={{ margin: '0 auto 10px', color: 'var(--slate-400)' }} />
                      <p>No active export shipments found.</p>
                    </div>
                  ) : (
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 16 }}>
                      {customerShipments.map((shp) => (
                        <div key={shp.id} className="panel" style={{ padding: 16, background: 'var(--navy-900)', border: '1px solid var(--navy-800)' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                            <strong style={{ color: 'var(--teal-300)', fontSize: 15 }}>{shp.reference}</strong>
                            <span className={`status-tag status-${shp.status}`}>{shp.status.toUpperCase()}</span>
                          </div>
                          <div style={{ fontSize: 13, color: 'var(--slate-300)', display: 'flex', flexDirection: 'column', gap: 6 }}>
                            <div>Destination: <strong>{shp.destination_port || shp.destination_country}</strong></div>
                            <div>Carrier: <strong>{shp.carrier_name || 'Ocean Freight'}</strong> {shp.vessel_name && `(${shp.vessel_name})`}</div>
                            <div>Readiness: <span className="provenance-pill status-ready">{shp.readiness_status}</span></div>
                            {shp.bill_of_lading_no && <div>B/L: <code>{shp.bill_of_lading_no}</code></div>}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Sub-Tab 4: Customer Order Inquiries & Messages */}
              {customerTab === 'threads' && (
                <CustomerThreadsSection
                  customerSession={customerSession}
                  customerSOs={customerSOs}
                />
              )}

              {/* Sub-Tab 5: Customer Document Requests */}
              {customerTab === 'doc_requests' && (
                <CustomerDocumentRequestsSection
                  customerSession={customerSession}
                  customerSOs={customerSOs}
                />
              )}

              {/* Sub-Tab 6: Customer Notifications */}
              {customerTab === 'notifications' && (
                <CustomerNotificationsSection
                  customerSession={customerSession}
                />
              )}
            </div>
          )}
        </div>
      )}

      {/* ========================================================
          3. INTERNAL STAFF INVITATION & ACCESS MANAGER
          ======================================================== */}
      {activePortal === 'admin_invitations' && (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
            <div>
              <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>Collaboration Accounts &amp; Invitations</h2>
              <p style={{ margin: '4px 0 0', color: 'var(--slate-400)', fontSize: 13 }}>
                Generate expiring, single-use invitation tokens bound server-side to active suppliers and customers.
              </p>
            </div>
            <button className="primary-button" onClick={() => setIsInviteModalOpen(true)}>
              <UserPlus size={15} /> Issue New Partner Invitation
            </button>
          </div>

          {generatedInvite && (
            <div className="clean-audit-card" style={{ padding: 18, marginBottom: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                <CheckCircle2 size={18} color="var(--emerald-400)" />
                <strong>Invitation Generated for {generatedInvite.organization_name}</strong>
              </div>
              <p style={{ fontSize: 13, margin: '0 0 10px', color: 'var(--slate-300)' }}>
                Share this single-use registration token with the partner. It expires on {new Date(generatedInvite.expires_at).toLocaleString()}.
              </p>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, background: 'var(--navy-950)', padding: '10px 14px', borderRadius: 8 }}>
                <code style={{ fontSize: 13, color: 'var(--teal-300)', flex: 1, wordBreak: 'break-all' }}>
                  {generatedInvite.invitation_token}
                </code>
                <button
                  className="btn-sm btn-secondary"
                  onClick={() => {
                    navigator.clipboard.writeText(generatedInvite.invitation_token)
                    alert('Invitation token copied to clipboard!')
                  }}
                >
                  <Copy size={13} /> Copy Token
                </button>
              </div>
            </div>
          )}

          {/* Table of Issued Invitations */}
          <div className="panel" style={{ padding: 20, marginBottom: 24 }}>
            <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 14px' }}>Active &amp; Historical Invitations</h3>
            {adminLoading ? (
              <p>Loading invitations...</p>
            ) : invitationsList.length === 0 ? (
              <p style={{ color: 'var(--slate-400)', fontSize: 13 }}>No invitations generated yet.</p>
            ) : (
              <table className="portal-table" style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
                <thead>
                  <tr style={{ background: 'var(--navy-900)', borderBottom: '1px solid var(--navy-800)' }}>
                    <th style={{ padding: 10 }}>Type</th>
                    <th style={{ padding: 10 }}>Organization</th>
                    <th style={{ padding: 10 }}>Email</th>
                    <th style={{ padding: 10 }}>Invited By</th>
                    <th style={{ padding: 10 }}>Status</th>
                    <th style={{ padding: 10 }}>Expires</th>
                    <th style={{ padding: 10, textAlign: 'right' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {invitationsList.map((inv) => (
                    <tr key={inv.id} style={{ borderBottom: '1px solid var(--navy-800)' }}>
                      <td style={{ padding: 10 }}>
                        <span className={`provenance-pill status-${inv.account_type === 'supplier' ? 'ready' : 'info'}`}>
                          {inv.account_type.toUpperCase()}
                        </span>
                      </td>
                      <td style={{ padding: 10 }}><strong>{inv.organization_name}</strong></td>
                      <td style={{ padding: 10 }}>{inv.email}</td>
                      <td style={{ padding: 10 }}>{inv.invited_by}</td>
                      <td style={{ padding: 10 }}>
                        <span className={`status-tag status-${inv.status}`}>{inv.status.toUpperCase()}</span>
                      </td>
                      <td style={{ padding: 10 }}>{new Date(inv.expires_at).toLocaleDateString()}</td>
                      <td style={{ padding: 10, textAlign: 'right' }}>
                        {inv.status === 'pending' && (
                          <button
                            className="btn-sm btn-secondary"
                            onClick={() => handleRevokeInvitation(inv.id)}
                            style={{ color: 'var(--rose-400)' }}
                          >
                            Revoke
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Registered External Portal Users Table */}
          <div className="panel" style={{ padding: 20 }}>
            <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 14px' }}>Registered External Portal Accounts</h3>
            {portalUsersList.length === 0 ? (
              <p style={{ color: 'var(--slate-400)', fontSize: 13 }}>No external users registered yet.</p>
            ) : (
              <table className="portal-table" style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
                <thead>
                  <tr style={{ background: 'var(--navy-900)', borderBottom: '1px solid var(--navy-800)' }}>
                    <th style={{ padding: 10 }}>Username</th>
                    <th style={{ padding: 10 }}>Email</th>
                    <th style={{ padding: 10 }}>Organization</th>
                    <th style={{ padding: 10 }}>Type</th>
                    <th style={{ padding: 10 }}>Status</th>
                    <th style={{ padding: 10, textAlign: 'right' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {portalUsersList.map((u) => (
                    <tr key={u.id} style={{ borderBottom: '1px solid var(--navy-800)' }}>
                      <td style={{ padding: 10 }}><code>{u.username}</code></td>
                      <td style={{ padding: 10 }}>{u.email}</td>
                      <td style={{ padding: 10 }}><strong>{u.organization_name}</strong></td>
                      <td style={{ padding: 10 }}>
                        <span className={`provenance-pill status-${u.account_type === 'supplier' ? 'ready' : 'info'}`}>
                          {u.account_type.toUpperCase()}
                        </span>
                      </td>
                      <td style={{ padding: 10 }}>
                        <span className={`status-tag status-${u.is_active ? 'ready' : 'cancelled'}`}>
                          {u.is_active ? 'ACTIVE' : 'DEACTIVATED'}
                        </span>
                      </td>
                      <td style={{ padding: 10, textAlign: 'right' }}>
                        {u.is_active ? (
                          <button
                            className="btn-sm btn-secondary"
                            onClick={() => handleDeactivatePortalUser(u.id, u.username)}
                            style={{ color: 'var(--rose-400)' }}
                          >
                            Deactivate Account
                          </button>
                        ) : (
                          <span style={{ fontSize: 12, color: 'var(--slate-400)' }}>Access Revoked</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Issue Invitation Modal */}
          {isInviteModalOpen && (
            <div className="modal-backdrop" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'grid', placeItems: 'center', zIndex: 100 }}>
              <div className="panel" style={{ width: '100%', maxWidth: 480, padding: 24 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
                  <h3 style={{ margin: 0, fontSize: 17, fontWeight: 700 }}>Issue Partner Portal Invitation</h3>
                  <button onClick={() => setIsInviteModalOpen(false)} style={{ background: 'transparent', border: 'none', color: '#fff', cursor: 'pointer' }}>
                    <X size={18} />
                  </button>
                </div>

                <form onSubmit={handleCreateInvitation} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  <div>
                    <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>Partner Type</label>
                    <select
                      value={inviteFormData.account_type}
                      onChange={(e) => setInviteFormData({ ...inviteFormData, account_type: e.target.value, organization_id: '' })}
                      style={{ width: '100%', padding: '10px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff' }}
                    >
                      <option value="supplier">Supplier</option>
                      <option value="customer">Customer</option>
                    </select>
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>
                      Target {inviteFormData.account_type === 'supplier' ? 'Supplier' : 'Customer'} Organization
                    </label>
                    <select
                      value={inviteFormData.organization_id}
                      onChange={(e) => {
                        const orgId = e.target.value
                        let defaultEmail = ''
                        if (inviteFormData.account_type === 'supplier') {
                          defaultEmail = suppliersMaster.find((s) => s.id === orgId)?.email || ''
                        } else {
                          defaultEmail = customersMaster.find((c) => c.id === orgId)?.email || ''
                        }
                        setInviteFormData({ ...inviteFormData, organization_id: orgId, email: defaultEmail })
                      }}
                      required
                      style={{ width: '100%', padding: '10px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff' }}
                    >
                      <option value="">-- Select Master Organization --</option>
                      {inviteFormData.account_type === 'supplier'
                        ? suppliersMaster.map((s) => (
                            <option key={s.id} value={s.id}>{s.name} ({s.code})</option>
                          ))
                        : customersMaster.map((c) => (
                            <option key={c.id} value={c.id}>{c.name} ({c.code})</option>
                          ))}
                    </select>
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>Invited Contact Email</label>
                    <input
                      type="email"
                      value={inviteFormData.email}
                      onChange={(e) => setInviteFormData({ ...inviteFormData, email: e.target.value })}
                      required
                      placeholder="partner@organization.com"
                      style={{ width: '100%', padding: '10px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff' }}
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--slate-300)', marginBottom: 6 }}>Expiry Window (Days)</label>
                    <input
                      type="number"
                      min={1}
                      max={30}
                      value={inviteFormData.expires_in_days}
                      onChange={(e) => setInviteFormData({ ...inviteFormData, expires_in_days: Number(e.target.value) })}
                      style={{ width: '100%', padding: '10px 12px', borderRadius: 8, background: 'var(--navy-900)', border: '1px solid var(--navy-700)', color: '#fff' }}
                    />
                  </div>

                  <div style={{ display: 'flex', gap: 10, marginTop: 10 }}>
                    <button type="submit" className="primary-button" style={{ flex: 1 }} disabled={adminLoading}>
                      {adminLoading ? 'Generating...' : 'Generate Single-Use Invitation'}
                    </button>
                    <button type="button" className="btn-sm btn-secondary" onClick={() => setIsInviteModalOpen(false)}>
                      Cancel
                    </button>
                  </div>
                </form>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ========================================================
          4. INTERNAL STAFF REVIEW CONSOLE (PHASE 9B & 9C)
          ======================================================== */}
      {activePortal === 'staff_review' && (
        <div>
          <div style={{ display: 'flex', gap: 10, marginBottom: 20, borderBottom: '1px solid var(--navy-800)', paddingBottom: 12 }}>
            <button
              className={`btn-sm ${staffReviewPortal === 'supplier' ? 'btn-primary-sm' : 'btn-secondary'}`}
              onClick={() => setStaffReviewPortal('supplier')}
            >
              <ShoppingCart size={14} /> Supplier Operations Review (Phase 9B)
            </button>
            <button
              className={`btn-sm ${staffReviewPortal === 'customer' ? 'btn-primary-sm' : 'btn-secondary'}`}
              onClick={() => setStaffReviewPortal('customer')}
            >
              <Users size={14} /> Customer Collaboration &amp; Document Requests (Phase 9C)
            </button>
          </div>

          {staffReviewPortal === 'supplier' ? (
            <StaffReviewConsole />
          ) : (
            <StaffCustomerCollaborationConsole />
          )}
        </div>
      )}
    </div>
  )
}
