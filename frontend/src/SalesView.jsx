import { useEffect, useState, useMemo } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  Boxes,
  Building2,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock,
  Eye,
  FileCheck2,
  FileText,
  Filter,
  History,
  Lock,
  Package,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Shield,
  ShoppingBag,
  Truck,
  Warehouse as WarehouseIcon,
  X,
  XCircle,
} from 'lucide-react'
import { apiFetch } from './api'

export default function SalesView({ initialTab = 'orders' }) {
  const [activeTab, setActiveTab] = useState(initialTab) // 'orders' | 'quotations' | 'picking' | 'dispatches' | 'returns'
  const [currentRole, setCurrentRole] = useState('admin')
  const [operatorName, setOperatorName] = useState('Local Operator')

  const authHeaders = useMemo(
    () => ({
      'X-User-Role': currentRole,
      'X-User-Name': operatorName,
    }),
    [currentRole, operatorName]
  )

  // Master Data caches
  const [customersList, setCustomersList] = useState([])
  const [productsList, setProductsList] = useState([])
  const [warehousesList, setWarehousesList] = useState([])

  // State: Sales Orders
  const [salesOrders, setSalesOrders] = useState([])
  const [ordersLoading, setOrdersLoading] = useState(false)
  const [orderSearch, setOrderSearch] = useState('')
  const [orderStatusFilter, setOrderStatusFilter] = useState('all')
  const [selectedOrder, setSelectedOrder] = useState(null)
  const [isNewOrderModalOpen, setIsNewOrderModalOpen] = useState(false)
  const [orderFormError, setOrderFormError] = useState(null)

  // State: Quotations
  const [quotations, setQuotations] = useState([])
  const [quotationsLoading, setQuotationsLoading] = useState(false)
  const [quotationSearch, setQuotationSearch] = useState('')
  const [isNewQuoModalOpen, setIsNewQuoModalOpen] = useState(false)
  const [quoFormError, setQuoFormError] = useState(null)

  // State: Picking
  const [pickLists, setPickLists] = useState([])
  const [pickingLoading, setPickingLoading] = useState(false)
  const [isNewPickModalOpen, setIsNewPickModalOpen] = useState(false)
  const [selectedPickListToComplete, setSelectedPickListToComplete] = useState(null)
  const [pickFormError, setPickFormError] = useState(null)

  // State: Dispatches
  const [dispatches, setDispatches] = useState([])
  const [dispatchesLoading, setDispatchesLoading] = useState(false)
  const [isNewDispatchModalOpen, setIsNewDispatchModalOpen] = useState(false)
  const [selectedDispatchForDelivery, setSelectedDispatchForDelivery] = useState(null)
  const [dispatchFormError, setDispatchFormError] = useState(null)

  // State: Returns
  const [returns, setReturns] = useState([])
  const [returnsLoading, setReturnsLoading] = useState(false)
  const [isNewReturnModalOpen, setIsNewReturnModalOpen] = useState(false)
  const [selectedReturnToProcess, setSelectedReturnToProcess] = useState(null)
  const [returnFormError, setReturnFormError] = useState(null)

  // Feedback notifications
  const [feedback, setFeedback] = useState(null)

  const showFeedback = (type, message) => {
    setFeedback({ type, message })
    setTimeout(() => setFeedback(null), 5000)
  }

  // Load master data caches
  useEffect(() => {
    const fetchMasterData = async () => {
      try {
        const [cRes, pRes, wRes] = await Promise.all([
          apiFetch('/api/customers?limit=200', { headers: authHeaders }),
          apiFetch('/api/products?limit=200', { headers: authHeaders }),
          apiFetch('/api/warehouses', { headers: authHeaders }),
        ])
        if (cRes.ok) {
          const cData = await cRes.json()
          setCustomersList(cData.items || [])
        }
        if (pRes.ok) {
          const pData = await pRes.json()
          setProductsList(pData.items || [])
        }
        if (wRes.ok) {
          const wData = await wRes.json()
          setWarehousesList(wData || [])
        }
      } catch (err) {
        console.error('Failed to load master data for sales:', err)
      }
    }
    fetchMasterData()
  }, [authHeaders])

  // Fetch Sales Orders
  const fetchOrders = async () => {
    setOrdersLoading(true)
    try {
      const statusParam = orderStatusFilter !== 'all' ? `&status=${orderStatusFilter}` : ''
      const res = await apiFetch(`/api/sales-orders?limit=100${statusParam}`, { headers: authHeaders })
      if (res.ok) {
        const data = await res.json()
        setSalesOrders(data.items || [])
      }
    } catch (err) {
      console.error('Failed to fetch sales orders:', err)
    } finally {
      setOrdersLoading(false)
    }
  }

  // Fetch Quotations
  const fetchQuotations = async () => {
    setQuotationsLoading(true)
    try {
      const res = await apiFetch('/api/quotations?limit=100', { headers: authHeaders })
      if (res.ok) {
        const data = await res.json()
        setQuotations(data.items || [])
      }
    } catch (err) {
      console.error('Failed to fetch quotations:', err)
    } finally {
      setQuotationsLoading(false)
    }
  }

  // Fetch Pick Lists
  const fetchPickLists = async () => {
    setPickingLoading(true)
    try {
      const res = await apiFetch('/api/sales-pick-lists', { headers: authHeaders })
      if (res.ok) {
        const data = await res.json()
        setPickLists(data || [])
      }
    } catch (err) {
      console.error('Failed to fetch pick lists:', err)
    } finally {
      setPickingLoading(false)
    }
  }

  // Fetch Dispatches
  const fetchDispatches = async () => {
    setDispatchesLoading(true)
    try {
      const res = await apiFetch('/api/sales-dispatches', { headers: authHeaders })
      if (res.ok) {
        const data = await res.json()
        setDispatches(data || [])
      }
    } catch (err) {
      console.error('Failed to fetch dispatches:', err)
    } finally {
      setDispatchesLoading(false)
    }
  }

  // Fetch Returns
  const fetchReturns = async () => {
    setReturnsLoading(true)
    try {
      const res = await apiFetch('/api/sales-returns', { headers: authHeaders })
      if (res.ok) {
        const data = await res.json()
        setReturns(data || [])
      }
    } catch (err) {
      console.error('Failed to fetch returns:', err)
    } finally {
      setReturnsLoading(false)
    }
  }

  useEffect(() => {
    if (activeTab === 'orders') fetchOrders()
    if (activeTab === 'quotations') fetchQuotations()
    if (activeTab === 'picking') fetchPickLists()
    if (activeTab === 'dispatches') fetchDispatches()
    if (activeTab === 'returns') fetchReturns()
  }, [activeTab, orderStatusFilter])

  // Handlers for Order Lifecycle
  const handleConfirmOrder = async (orderId) => {
    try {
      const res = await apiFetch(`/api/sales-orders/${orderId}/confirm`, {
        method: 'POST',
        headers: authHeaders,
      })
      if (res.ok) {
        showFeedback('success', 'Sales order confirmed successfully.')
        fetchOrders()
        if (selectedOrder?.id === orderId) {
          const updated = await res.json()
          setSelectedOrder(updated)
        }
      } else {
        const err = await res.json()
        showFeedback('error', err.detail || 'Failed to confirm order.')
      }
    } catch (err) {
      showFeedback('error', err.message)
    }
  }

  const handleAllocateOrder = async (orderId, warehouseId) => {
    try {
      const res = await apiFetch(`/api/sales-orders/${orderId}/allocate`, {
        method: 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify({ warehouse_id: warehouseId || 'wh-main' }),
      })
      if (res.ok) {
        showFeedback('success', 'Inventory reserved via Phase 3 ATP engine.')
        fetchOrders()
        if (selectedOrder?.id === orderId) {
          const updated = await res.json()
          setSelectedOrder(updated)
        }
      } else {
        const err = await res.json()
        showFeedback('error', err.detail || 'Allocation failed: Insufficient ATP.')
      }
    } catch (err) {
      showFeedback('error', err.message)
    }
  }

  const handleCancelOrder = async (orderId) => {
    if (!window.confirm('Cancel this sales order? All active inventory reservations will be released.')) return
    try {
      const res = await apiFetch(`/api/sales-orders/${orderId}/cancel`, {
        method: 'POST',
        headers: authHeaders,
      })
      if (res.ok) {
        showFeedback('success', 'Sales order cancelled and reservations released.')
        fetchOrders()
        if (selectedOrder?.id === orderId) {
          const updated = await res.json()
          setSelectedOrder(updated)
        }
      } else {
        const err = await res.json()
        showFeedback('error', err.detail || 'Failed to cancel order.')
      }
    } catch (err) {
      showFeedback('error', err.message)
    }
  }

  const handlePackOrder = async (orderId) => {
    try {
      const res = await apiFetch(`/api/sales-orders/${orderId}/pack`, {
        method: 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes: 'Packed and ready for dispatch' }),
      })
      if (res.ok) {
        showFeedback('success', 'Sales order packed successfully.')
        fetchOrders()
        if (selectedOrder?.id === orderId) {
          const updated = await res.json()
          setSelectedOrder(updated)
        }
      } else {
        const err = await res.json()
        showFeedback('error', err.detail || 'Packing failed.')
      }
    } catch (err) {
      showFeedback('error', err.message)
    }
  }

  // Handlers for Quotations
  const handleSendQuotation = async (quoId) => {
    try {
      const res = await apiFetch(`/api/quotations/${quoId}/send`, { method: 'POST', headers: authHeaders })
      if (res.ok) {
        showFeedback('success', 'Quotation sent to customer.')
        fetchQuotations()
      } else {
        const err = await res.json()
        showFeedback('error', err.detail || 'Failed to send quotation.')
      }
    } catch (err) {
      showFeedback('error', err.message)
    }
  }

  const handleAcceptQuotation = async (quoId) => {
    try {
      const res = await apiFetch(`/api/quotations/${quoId}/accept`, { method: 'POST', headers: authHeaders })
      if (res.ok) {
        showFeedback('success', 'Quotation accepted by customer.')
        fetchQuotations()
      } else {
        const err = await res.json()
        showFeedback('error', err.detail || 'Failed to accept quotation.')
      }
    } catch (err) {
      showFeedback('error', err.message)
    }
  }

  const handleConvertQuotation = async (quoId) => {
    try {
      const res = await apiFetch(`/api/quotations/${quoId}/convert`, {
        method: 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify({ payment_terms: 'Net 30' }),
      })
      if (res.ok) {
        showFeedback('success', 'Quotation successfully converted to Sales Order.')
        fetchQuotations()
        setActiveTab('orders')
      } else {
        const err = await res.json()
        showFeedback('error', err.detail || 'Conversion failed.')
      }
    } catch (err) {
      showFeedback('error', err.message)
    }
  }

  // Status Badge Helper
  const renderStatusBadge = (status) => {
    const s = (status || '').toLowerCase()
    let badgeClass = 'secondary'
    if (['confirmed', 'allocated', 'completed', 'delivered', 'accepted', 'processed'].includes(s)) badgeClass = 'success'
    if (['picking', 'packed', 'dispatched', 'in_transit', 'sent'].includes(s)) badgeClass = 'warning'
    if (['cancelled', 'rejected'].includes(s)) badgeClass = 'danger'
    return <span className={`erp-badge ${badgeClass}`}>{status?.toUpperCase()}</span>
  }

  return (
    <div className="erp-master-container">
      {/* Header Row with RBAC Selector */}
      <div className="erp-header-row">
        <div>
          <div className="eyebrow">EXPORTMATE ERP — PHASE 4</div>
          <h1 className="erp-title">Sales Orders &amp; Commercial Fulfilment</h1>
          <p className="erp-subtitle">
            Quotations, sales order entry, ATP reservations, picking, packing, dispatch, delivery tracking, and returns.
          </p>
        </div>
        <div className="erp-rbac-badge-bar">
          <Shield size={16} className="text-accent" />
          <span className="rbac-label">Active Role:</span>
          <select
            className="rbac-select"
            value={currentRole}
            onChange={(e) => setCurrentRole(e.target.value)}
          >
            <option value="admin">Administrator (Full Access)</option>
            <option value="sales">Sales Officer (Orders &amp; Quotations)</option>
            <option value="warehouse">Warehouse Operator (Fulfillment)</option>
            <option value="procurement">Procurement (Read-Only)</option>
            <option value="viewer">Viewer (Auditor / Read-Only)</option>
          </select>
          <span className="rbac-hint">Server-enforced RBAC</span>
        </div>
      </div>

      {/* Global Feedback Banner */}
      {feedback && (
        <div className={`erp-alert-banner ${feedback.type}`}>
          {feedback.type === 'error' ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
          <span>{feedback.message}</span>
          <button className="close-btn" onClick={() => setFeedback(null)}>
            <X size={14} />
          </button>
        </div>
      )}

      {/* Navigation Tabs */}
      <div className="erp-tabs-row">
        <button
          className={`erp-tab-btn ${activeTab === 'orders' ? 'active' : ''}`}
          onClick={() => setActiveTab('orders')}
        >
          <ShoppingBag size={16} />
          <span>Sales Orders</span>
          <span className="count-pill">{salesOrders.length}</span>
        </button>
        <button
          className={`erp-tab-btn ${activeTab === 'quotations' ? 'active' : ''}`}
          onClick={() => setActiveTab('quotations')}
        >
          <FileCheck2 size={16} />
          <span>Quotations</span>
          <span className="count-pill">{quotations.length}</span>
        </button>
        <button
          className={`erp-tab-btn ${activeTab === 'picking' ? 'active' : ''}`}
          onClick={() => setActiveTab('picking')}
        >
          <Package size={16} />
          <span>Picking &amp; Packing</span>
          <span className="count-pill">{pickLists.length}</span>
        </button>
        <button
          className={`erp-tab-btn ${activeTab === 'dispatches' ? 'active' : ''}`}
          onClick={() => setActiveTab('dispatches')}
        >
          <Truck size={16} />
          <span>Commercial Dispatches</span>
          <span className="count-pill">{dispatches.length}</span>
        </button>
        <button
          className={`erp-tab-btn ${activeTab === 'returns' ? 'active' : ''}`}
          onClick={() => setActiveTab('returns')}
        >
          <RotateCcw size={16} />
          <span>Sales Returns</span>
          <span className="count-pill">{returns.length}</span>
        </button>
      </div>

      {/* TAB 1: SALES ORDERS */}
      {activeTab === 'orders' && (
        <div className="erp-content-section">
          <div className="erp-table-toolbar">
            <div className="erp-search-box">
              <Search size={16} className="search-icon" />
              <input
                type="text"
                placeholder="Search orders by number or customer..."
                value={orderSearch}
                onChange={(e) => setOrderSearch(e.target.value)}
              />
            </div>
            <div className="erp-filter-row">
              <span className="filter-label">Status:</span>
              <select
                className="filter-select"
                value={orderStatusFilter}
                onChange={(e) => setOrderStatusFilter(e.target.value)}
              >
                <option value="all">All Statuses</option>
                <option value="draft">Draft</option>
                <option value="confirmed">Confirmed</option>
                <option value="allocated">Allocated</option>
                <option value="picking">Picking</option>
                <option value="packed">Packed</option>
                <option value="dispatched">Dispatched</option>
                <option value="delivered">Delivered</option>
                <option value="cancelled">Cancelled</option>
              </select>
              <button className="erp-btn secondary" onClick={fetchOrders}>
                <RefreshCw size={14} /> Refresh
              </button>
              {['admin', 'sales'].includes(currentRole) && (
                <button className="erp-btn primary" onClick={() => setIsNewOrderModalOpen(true)}>
                  <Plus size={14} /> New Sales Order
                </button>
              )}
            </div>
          </div>

          <div className="erp-table-card">
            <table className="erp-data-table">
              <thead>
                <tr>
                  <th>Order Number</th>
                  <th>Customer Snapshot</th>
                  <th>Order Date</th>
                  <th>Delivery Date</th>
                  <th>Subtotal</th>
                  <th>Grand Total</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {ordersLoading ? (
                  <tr>
                    <td colSpan={8} className="erp-empty-state">Loading sales orders...</td>
                  </tr>
                ) : salesOrders.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="erp-empty-state">No sales orders found.</td>
                  </tr>
                ) : (
                  salesOrders
                    .filter(
                      (o) =>
                        o.order_number?.toLowerCase().includes(orderSearch.toLowerCase()) ||
                        o.customer_name?.toLowerCase().includes(orderSearch.toLowerCase())
                    )
                    .map((o) => (
                      <tr key={o.id}>
                        <td>
                          <strong>{o.order_number}</strong>
                          {o.quotation_id && <div className="erp-subtext">Quo: {o.quotation_id}</div>}
                        </td>
                        <td>
                          <div>{o.customer_name}</div>
                          <div className="erp-subtext">{o.customer_code} • {o.contact_email || 'No email'}</div>
                        </td>
                        <td>{o.order_date}</td>
                        <td>{o.requested_delivery_date || '—'}</td>
                        <td>${o.subtotal.toFixed(2)}</td>
                        <td>
                          <strong>${o.grand_total.toFixed(2)} {o.currency}</strong>
                        </td>
                        <td>{renderStatusBadge(o.status)}</td>
                        <td>
                          <button
                            className="erp-btn secondary text-btn"
                            onClick={() => setSelectedOrder(o)}
                          >
                            <Eye size={14} /> View Details
                          </button>
                        </td>
                      </tr>
                    ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 2: QUOTATIONS */}
      {activeTab === 'quotations' && (
        <div className="erp-content-section">
          <div className="erp-table-toolbar">
            <div className="erp-search-box">
              <Search size={16} className="search-icon" />
              <input
                type="text"
                placeholder="Search quotations..."
                value={quotationSearch}
                onChange={(e) => setQuotationSearch(e.target.value)}
              />
            </div>
            <div className="erp-filter-row">
              <button className="erp-btn secondary" onClick={fetchQuotations}>
                <RefreshCw size={14} /> Refresh
              </button>
              {['admin', 'sales'].includes(currentRole) && (
                <button className="erp-btn primary" onClick={() => setIsNewQuoModalOpen(true)}>
                  <Plus size={14} /> New Customer Quotation
                </button>
              )}
            </div>
          </div>

          <div className="erp-table-card">
            <table className="erp-data-table">
              <thead>
                <tr>
                  <th>Quotation Number</th>
                  <th>Customer Snapshot</th>
                  <th>Date</th>
                  <th>Valid Until</th>
                  <th>Grand Total</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {quotationsLoading ? (
                  <tr>
                    <td colSpan={7} className="erp-empty-state">Loading quotations...</td>
                  </tr>
                ) : quotations.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="erp-empty-state">No quotations found.</td>
                  </tr>
                ) : (
                  quotations
                    .filter(
                      (q) =>
                        q.quotation_number?.toLowerCase().includes(quotationSearch.toLowerCase()) ||
                        q.customer_name?.toLowerCase().includes(quotationSearch.toLowerCase())
                    )
                    .map((q) => (
                      <tr key={q.id}>
                        <td><strong>{q.quotation_number}</strong></td>
                        <td>
                          <div>{q.customer_name}</div>
                          <div className="erp-subtext">{q.customer_code}</div>
                        </td>
                        <td>{q.quotation_date}</td>
                        <td>{q.valid_until || '—'}</td>
                        <td><strong>${q.grand_total.toFixed(2)} {q.currency}</strong></td>
                        <td>{renderStatusBadge(q.status)}</td>
                        <td>
                          <div className="erp-actions-cell">
                            {q.status === 'draft' && ['admin', 'sales'].includes(currentRole) && (
                              <button
                                className="erp-btn secondary text-btn"
                                onClick={() => handleSendQuotation(q.id)}
                              >
                                Send
                              </button>
                            )}
                            {['draft', 'sent'].includes(q.status) && ['admin', 'sales'].includes(currentRole) && (
                              <button
                                className="erp-btn success text-btn"
                                onClick={() => handleAcceptQuotation(q.id)}
                              >
                                Accept
                              </button>
                            )}
                            {['draft', 'sent', 'accepted'].includes(q.status) && ['admin', 'sales'].includes(currentRole) && (
                              <button
                                className="erp-btn primary text-btn"
                                onClick={() => handleConvertQuotation(q.id)}
                              >
                                Convert to Order
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 3: PICKING & PACKING */}
      {activeTab === 'picking' && (
        <div className="erp-content-section">
          <div className="erp-table-toolbar">
            <div className="toolbar-left">
              <h3>Authoritative Picking Lists</h3>
              <p className="erp-subtext">Pick only allocated &amp; reserved inventory. Records short picks with discrepancies.</p>
            </div>
            <div className="erp-filter-row">
              <button className="erp-btn secondary" onClick={fetchPickLists}>
                <RefreshCw size={14} /> Refresh
              </button>
              {['admin', 'warehouse'].includes(currentRole) && (
                <button className="erp-btn primary" onClick={() => setIsNewPickModalOpen(true)}>
                  <Plus size={14} /> Generate Pick List
                </button>
              )}
            </div>
          </div>

          <div className="erp-table-card">
            <table className="erp-data-table">
              <thead>
                <tr>
                  <th>Pick List #</th>
                  <th>Order Number</th>
                  <th>Warehouse</th>
                  <th>Assigned Picker</th>
                  <th>Items Count</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {pickingLoading ? (
                  <tr>
                    <td colSpan={7} className="erp-empty-state">Loading pick lists...</td>
                  </tr>
                ) : pickLists.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="erp-empty-state">No pick lists created yet.</td>
                  </tr>
                ) : (
                  pickLists.map((p) => (
                    <tr key={p.id}>
                      <td><strong>{p.pick_list_number}</strong></td>
                      <td>{p.order_number}</td>
                      <td>{p.warehouse_code}</td>
                      <td>{p.assigned_picker || 'Unassigned'}</td>
                      <td>{p.items?.length || 0} line(s)</td>
                      <td>{renderStatusBadge(p.status)}</td>
                      <td>
                        {p.status === 'pending' && ['admin', 'warehouse'].includes(currentRole) && (
                          <button
                            className="erp-btn primary text-btn"
                            onClick={() => setSelectedPickListToComplete(p)}
                          >
                            Complete Pick
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
      )}

      {/* TAB 4: COMMERCIAL DISPATCHES */}
      {activeTab === 'dispatches' && (
        <div className="erp-content-section">
          <div className="erp-table-toolbar">
            <div className="toolbar-left">
              <h3>Commercial Dispatches &amp; Exactly-Once Ledger Deduction</h3>
              <p className="erp-subtext">Deducts physical on-hand stock and consumes reservations upon dispatch.</p>
            </div>
            <div className="erp-filter-row">
              <button className="erp-btn secondary" onClick={fetchDispatches}>
                <RefreshCw size={14} /> Refresh
              </button>
              {['admin', 'warehouse'].includes(currentRole) && (
                <button className="erp-btn primary" onClick={() => setIsNewDispatchModalOpen(true)}>
                  <Plus size={14} /> Dispatch Fulfilment
                </button>
              )}
            </div>
          </div>

          <div className="erp-table-card">
            <table className="erp-data-table">
              <thead>
                <tr>
                  <th>Dispatch #</th>
                  <th>Sales Order #</th>
                  <th>Warehouse</th>
                  <th>Carrier &amp; Tracking</th>
                  <th>Dispatch Date</th>
                  <th>Status</th>
                  <th>Delivery Date</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {dispatchesLoading ? (
                  <tr>
                    <td colSpan={8} className="erp-empty-state">Loading dispatches...</td>
                  </tr>
                ) : dispatches.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="erp-empty-state">No commercial dispatches posted yet.</td>
                  </tr>
                ) : (
                  dispatches.map((d) => (
                    <tr key={d.id}>
                      <td><strong>{d.dispatch_number}</strong></td>
                      <td>{d.order_number}</td>
                      <td>{d.warehouse_code}</td>
                      <td>
                        <div>{d.carrier_name || 'Direct / Courier'}</div>
                        <div className="erp-subtext">{d.tracking_number || 'No tracking ref'}</div>
                      </td>
                      <td>{d.dispatch_date}</td>
                      <td>{renderStatusBadge(d.status)}</td>
                      <td>{d.delivery_date || 'In transit'}</td>
                      <td>
                        {d.status === 'dispatched' && ['admin', 'warehouse'].includes(currentRole) && (
                          <button
                            className="erp-btn success text-btn"
                            onClick={() => setSelectedDispatchForDelivery(d)}
                          >
                            Confirm Delivery
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
      )}

      {/* TAB 5: SALES RETURNS */}
      {activeTab === 'returns' && (
        <div className="erp-content-section">
          <div className="erp-table-toolbar">
            <div className="toolbar-left">
              <h3>Sales Returns &amp; Quarantined Segregation</h3>
              <p className="erp-subtext">Returns foundation with strict segregation: quarantined/rejected stock is never made available.</p>
            </div>
            <div className="erp-filter-row">
              <button className="erp-btn secondary" onClick={fetchReturns}>
                <RefreshCw size={14} /> Refresh
              </button>
              {['admin', 'sales'].includes(currentRole) && (
                <button className="erp-btn primary" onClick={() => setIsNewReturnModalOpen(true)}>
                  <Plus size={14} /> Record Customer Return
                </button>
              )}
            </div>
          </div>

          <div className="erp-table-card">
            <table className="erp-data-table">
              <thead>
                <tr>
                  <th>Return #</th>
                  <th>Order #</th>
                  <th>Customer</th>
                  <th>Return Date</th>
                  <th>Reason</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {returnsLoading ? (
                  <tr>
                    <td colSpan={7} className="erp-empty-state">Loading sales returns...</td>
                  </tr>
                ) : returns.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="erp-empty-state">No returns recorded.</td>
                  </tr>
                ) : (
                  returns.map((r) => (
                    <tr key={r.id}>
                      <td><strong>{r.return_number}</strong></td>
                      <td>{r.order_number}</td>
                      <td>{r.customer_name}</td>
                      <td>{r.return_date}</td>
                      <td>{r.reason}</td>
                      <td>{renderStatusBadge(r.status)}</td>
                      <td>
                        {r.status === 'received' && ['admin', 'warehouse'].includes(currentRole) && (
                          <button
                            className="erp-btn primary text-btn"
                            onClick={() => setSelectedReturnToProcess(r)}
                          >
                            Inspect &amp; Restock
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
      )}

      {/* MODAL: ORDER DETAILS & LIFECYCLE CONTROLS */}
      {selectedOrder && (
        <div className="erp-modal-backdrop">
          <div className="erp-modal-card large">
            <div className="erp-modal-head">
              <div>
                <h2>{selectedOrder.order_number}</h2>
                <div className="erp-subtext">Customer Snapshot: {selectedOrder.customer_name} ({selectedOrder.customer_code})</div>
              </div>
              <button className="close-btn" onClick={() => setSelectedOrder(null)}>
                <X size={18} />
              </button>
            </div>
            <div className="erp-modal-body">
              {/* Snapshot metadata */}
              <div className="erp-meta-grid">
                <div>
                  <span className="meta-label">Billing Address:</span>
                  <p>{selectedOrder.billing_address || '—'}</p>
                </div>
                <div>
                  <span className="meta-label">Shipping Address:</span>
                  <p>{selectedOrder.shipping_address || '—'}</p>
                </div>
                <div>
                  <span className="meta-label">Currency &amp; Terms:</span>
                  <p>{selectedOrder.currency} • {selectedOrder.payment_terms || 'Net 30'}</p>
                </div>
                <div>
                  <span className="meta-label">Status:</span>
                  <p>{renderStatusBadge(selectedOrder.status)}</p>
                </div>
              </div>

              {/* Order Lines Breakdown */}
              <h3>Line Items &amp; Fulfilment Quantities</h3>
              <table className="erp-data-table">
                <thead>
                  <tr>
                    <th>Product / SKU</th>
                    <th>Ordered</th>
                    <th>Allocated</th>
                    <th>Picked</th>
                    <th>Dispatched</th>
                    <th>Delivered</th>
                    <th>Unit Price</th>
                    <th>Disc %</th>
                    <th>Tax %</th>
                    <th>Line Total</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedOrder.items?.map((it) => (
                    <tr key={it.id}>
                      <td>
                        <strong>{it.sku}</strong>
                        <div className="erp-subtext">{it.product_name}</div>
                      </td>
                      <td><strong>{it.ordered_quantity} {it.uom}</strong></td>
                      <td>
                        <span className={it.allocated_quantity >= it.ordered_quantity ? 'text-success' : 'text-warning'}>
                          {it.allocated_quantity}
                        </span>
                      </td>
                      <td>{it.picked_quantity}</td>
                      <td>{it.dispatched_quantity}</td>
                      <td>{it.delivered_quantity}</td>
                      <td>${it.unit_price.toFixed(2)}</td>
                      <td>{it.discount_pct}%</td>
                      <td>{it.tax_rate_pct}%</td>
                      <td><strong>${it.line_total.toFixed(2)}</strong></td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {/* Server-calculated Totals */}
              <div className="erp-totals-card">
                <div>Subtotal: <strong>${selectedOrder.subtotal?.toFixed(2)}</strong></div>
                <div>Discount: <strong className="text-danger">-${selectedOrder.discount_total?.toFixed(2)}</strong></div>
                <div>Tax Total: <strong>+${selectedOrder.tax_total?.toFixed(2)}</strong></div>
                <div className="grand-total-row">Grand Total: <span>${selectedOrder.grand_total?.toFixed(2)} {selectedOrder.currency}</span></div>
              </div>

              {/* Lifecycle Actions */}
              <div className="erp-actions-row">
                {selectedOrder.status === 'draft' && ['admin', 'sales'].includes(currentRole) && (
                  <button className="erp-btn primary" onClick={() => handleConfirmOrder(selectedOrder.id)}>
                    <Check size={14} /> Confirm Sales Order
                  </button>
                )}
                {['confirmed', 'allocated'].includes(selectedOrder.status) && ['admin', 'sales', 'warehouse'].includes(currentRole) && (
                  <button className="erp-btn secondary" onClick={() => handleAllocateOrder(selectedOrder.id, 'wh-main')}>
                    <Lock size={14} /> Allocate Stock (ATP Check)
                  </button>
                )}
                {['picking', 'allocated'].includes(selectedOrder.status) && ['admin', 'warehouse'].includes(currentRole) && (
                  <button className="erp-btn secondary" onClick={() => handlePackOrder(selectedOrder.id)}>
                    <Package size={14} /> Complete Packing
                  </button>
                )}
                {!['dispatched', 'delivered', 'cancelled'].includes(selectedOrder.status) && ['admin', 'sales'].includes(currentRole) && (
                  <button className="erp-btn danger" onClick={() => handleCancelOrder(selectedOrder.id)}>
                    <XCircle size={14} /> Cancel Order &amp; Release Stock
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* MODAL: NEW SALES ORDER */}
      {isNewOrderModalOpen && (
        <NewSalesOrderModal
          customers={customersList}
          products={productsList}
          authHeaders={authHeaders}
          onClose={() => setIsNewOrderModalOpen(false)}
          onSuccess={() => {
            setIsNewOrderModalOpen(false)
            showFeedback('success', 'Sales order created in draft state.')
            fetchOrders()
          }}
        />
      )}

      {/* MODAL: NEW QUOTATION */}
      {isNewQuoModalOpen && (
        <NewQuotationModal
          customers={customersList}
          products={productsList}
          authHeaders={authHeaders}
          onClose={() => setIsNewQuoModalOpen(false)}
          onSuccess={() => {
            setIsNewQuoModalOpen(false)
            showFeedback('success', 'Customer quotation created.')
            fetchQuotations()
          }}
        />
      )}

      {/* MODAL: COMPLETE PICK LIST */}
      {selectedPickListToComplete && (
        <CompletePickModal
          pickList={selectedPickListToComplete}
          authHeaders={authHeaders}
          onClose={() => setSelectedPickListToComplete(null)}
          onSuccess={() => {
            setSelectedPickListToComplete(null)
            showFeedback('success', 'Pick list completed and recorded to sales order.')
            fetchPickLists()
            fetchOrders()
          }}
        />
      )}

      {/* MODAL: NEW DISPATCH */}
      {isNewDispatchModalOpen && (
        <NewDispatchModal
          orders={salesOrders.filter((o) => ['packed', 'picking', 'allocated'].includes(o.status))}
          warehouses={warehousesList}
          authHeaders={authHeaders}
          onClose={() => setIsNewDispatchModalOpen(false)}
          onSuccess={() => {
            setIsNewDispatchModalOpen(false)
            showFeedback('success', 'Commercial dispatch completed & inventory movements posted.')
            fetchDispatches()
            fetchOrders()
          }}
        />
      )}

      {/* MODAL: CONFIRM DELIVERY */}
      {selectedDispatchForDelivery && (
        <DeliverDispatchModal
          dispatch={selectedDispatchForDelivery}
          authHeaders={authHeaders}
          onClose={() => setSelectedDispatchForDelivery(null)}
          onSuccess={() => {
            setSelectedDispatchForDelivery(null)
            showFeedback('success', 'Delivery confirmed and order status updated.')
            fetchDispatches()
            fetchOrders()
          }}
        />
      )}

      {/* MODAL: PROCESS RETURN */}
      {selectedReturnToProcess && (
        <ProcessReturnModal
          salesReturn={selectedReturnToProcess}
          authHeaders={authHeaders}
          onClose={() => setSelectedReturnToProcess(null)}
          onSuccess={() => {
            setSelectedReturnToProcess(null)
            showFeedback('success', 'Sales return processed with segregated inventory postings.')
            fetchReturns()
          }}
        />
      )}
    </div>
  )
}


// --- SUBCOMPONENT: NEW SALES ORDER MODAL ---
function NewSalesOrderModal({ customers, products, authHeaders, onClose, onSuccess }) {
  const [customerId, setCustomerId] = useState(customers[0]?.id || '')
  const [currency, setCurrency] = useState('USD')
  const [paymentTerms, setPaymentTerms] = useState('Net 30')
  const [reqDeliveryDate, setReqDeliveryDate] = useState('')
  const [notes, setNotes] = useState('')
  const [lines, setLines] = useState([
    { product_id: products[0]?.id || '', ordered_quantity: 10, unit_price: 100, discount_pct: 0, tax_rate_pct: 5 },
  ])
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const handleAddLine = () => {
    setLines([...lines, { product_id: products[0]?.id || '', ordered_quantity: 1, unit_price: 0, discount_pct: 0, tax_rate_pct: 0 }])
  }

  const handleRemoveLine = (idx) => {
    setLines(lines.filter((_, i) => i !== idx))
  }

  const updateLine = (idx, field, val) => {
    const next = [...lines]
    next[idx][field] = val
    if (field === 'product_id') {
      const p = products.find((prod) => prod.id === val)
      if (p) {
        next[idx].unit_price = p.default_selling_price || 0
        next[idx].tax_rate_pct = p.tax_rate_pct || 0
      }
    }
    setLines(next)
  }

  const totals = useMemo(() => {
    let sub = 0
    let disc = 0
    let tax = 0
    let grand = 0
    lines.forEach((l) => {
      const lineSub = Number(l.ordered_quantity) * Number(l.unit_price)
      const lineDisc = lineSub * (Number(l.discount_pct) / 100)
      const taxable = lineSub - lineDisc
      const lineTax = taxable * (Number(l.tax_rate_pct) / 100)
      sub += lineSub
      disc += lineDisc
      tax += lineTax
      grand += taxable + lineTax
    })
    return { sub, disc, tax, grand }
  }, [lines])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const payload = {
        customer_id: customerId,
        currency,
        payment_terms: paymentTerms,
        requested_delivery_date: reqDeliveryDate || null,
        notes: notes || null,
        items: lines.map((l) => ({
          product_id: l.product_id,
          ordered_quantity: Number(l.ordered_quantity),
          unit_price: Number(l.unit_price),
          discount_pct: Number(l.discount_pct),
          tax_rate_pct: Number(l.tax_rate_pct),
        })),
      }
      const res = await apiFetch('/api/sales-orders', {
        method: 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (res.ok) {
        onSuccess()
      } else {
        const err = await res.json()
        setError(err.detail || 'Failed to create sales order.')
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="erp-modal-backdrop">
      <div className="erp-modal-card large">
        <div className="erp-modal-head">
          <h2>Create New Sales Order</h2>
          <button className="close-btn" onClick={onClose}><X size={18} /></button>
        </div>
        <form onSubmit={handleSubmit} className="erp-modal-body">
          {error && <div className="erp-alert-banner error">{error}</div>}
          <div className="erp-form-grid">
            <div className="form-group">
              <label>Customer *</label>
              <select value={customerId} onChange={(e) => setCustomerId(e.target.value)} required>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>{c.name} ({c.code})</option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label>Currency</label>
              <select value={currency} onChange={(e) => setCurrency(e.target.value)}>
                <option value="USD">USD ($)</option>
                <option value="INR">INR (₹)</option>
                <option value="EUR">EUR (€)</option>
              </select>
            </div>
            <div className="form-group">
              <label>Payment Terms</label>
              <input value={paymentTerms} onChange={(e) => setPaymentTerms(e.target.value)} />
            </div>
            <div className="form-group">
              <label>Requested Delivery Date</label>
              <input type="date" value={reqDeliveryDate} onChange={(e) => setReqDeliveryDate(e.target.value)} />
            </div>
          </div>

          <h3>Order Line Items</h3>
          <table className="erp-data-table">
            <thead>
              <tr>
                <th>Product</th>
                <th>Qty</th>
                <th>Unit Price ($)</th>
                <th>Disc %</th>
                <th>Tax %</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((l, idx) => (
                <tr key={idx}>
                  <td>
                    <select value={l.product_id} onChange={(e) => updateLine(idx, 'product_id', e.target.value)}>
                      {products.map((p) => (
                        <option key={p.id} value={p.id}>{p.sku} — {p.name}</option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input type="number" step="any" min="0.01" value={l.ordered_quantity} onChange={(e) => updateLine(idx, 'ordered_quantity', e.target.value)} required />
                  </td>
                  <td>
                    <input type="number" step="any" min="0" value={l.unit_price} onChange={(e) => updateLine(idx, 'unit_price', e.target.value)} required />
                  </td>
                  <td>
                    <input type="number" step="any" min="0" max="100" value={l.discount_pct} onChange={(e) => updateLine(idx, 'discount_pct', e.target.value)} />
                  </td>
                  <td>
                    <input type="number" step="any" min="0" value={l.tax_rate_pct} onChange={(e) => updateLine(idx, 'tax_rate_pct', e.target.value)} />
                  </td>
                  <td>
                    {lines.length > 1 && (
                      <button type="button" className="erp-btn danger text-btn" onClick={() => handleRemoveLine(idx)}>
                        Remove
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button type="button" className="erp-btn secondary" onClick={handleAddLine}><Plus size={14} /> Add Line Item</button>

          <div className="erp-totals-card">
            <div>Subtotal: <strong>${totals.sub.toFixed(2)}</strong></div>
            <div>Discount: <strong>-${totals.disc.toFixed(2)}</strong></div>
            <div>Tax: <strong>+${totals.tax.toFixed(2)}</strong></div>
            <div className="grand-total-row">Estimated Grand Total: <span>${totals.grand.toFixed(2)} {currency}</span></div>
          </div>

          <div className="form-group">
            <label>Order Notes</label>
            <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Special delivery instructions, packaging requirements..." />
          </div>

          <div className="erp-modal-foot">
            <button type="button" className="erp-btn secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="erp-btn primary" disabled={submitting}>
              {submitting ? 'Creating Order...' : 'Create Sales Order'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}


// --- SUBCOMPONENT: NEW QUOTATION MODAL ---
function NewQuotationModal({ customers, products, authHeaders, onClose, onSuccess }) {
  const [customerId, setCustomerId] = useState(customers[0]?.id || '')
  const [currency, setCurrency] = useState('USD')
  const [validUntil, setValidUntil] = useState('')
  const [notes, setNotes] = useState('')
  const [lines, setLines] = useState([
    { product_id: products[0]?.id || '', quantity: 10, unit_price: 100, discount_pct: 0, tax_rate_pct: 5 },
  ])
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const payload = {
        customer_id: customerId,
        currency,
        valid_until: validUntil || null,
        notes: notes || null,
        items: lines.map((l) => ({
          product_id: l.product_id,
          quantity: Number(l.quantity),
          unit_price: Number(l.unit_price),
          discount_pct: Number(l.discount_pct),
          tax_rate_pct: Number(l.tax_rate_pct),
        })),
      }
      const res = await apiFetch('/api/quotations', {
        method: 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (res.ok) {
        onSuccess()
      } else {
        const err = await res.json()
        setError(err.detail || 'Failed to create quotation.')
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="erp-modal-backdrop">
      <div className="erp-modal-card large">
        <div className="erp-modal-head">
          <h2>Create Customer Quotation</h2>
          <button className="close-btn" onClick={onClose}><X size={18} /></button>
        </div>
        <form onSubmit={handleSubmit} className="erp-modal-body">
          {error && <div className="erp-alert-banner error">{error}</div>}
          <div className="erp-form-grid">
            <div className="form-group">
              <label>Customer *</label>
              <select value={customerId} onChange={(e) => setCustomerId(e.target.value)} required>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>{c.name} ({c.code})</option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label>Currency</label>
              <select value={currency} onChange={(e) => setCurrency(e.target.value)}>
                <option value="USD">USD ($)</option>
                <option value="INR">INR (₹)</option>
              </select>
            </div>
            <div className="form-group">
              <label>Valid Until Date</label>
              <input type="date" value={validUntil} onChange={(e) => setValidUntil(e.target.value)} />
            </div>
          </div>
          <div className="erp-modal-foot">
            <button type="button" className="erp-btn secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="erp-btn primary" disabled={submitting}>
              {submitting ? 'Submitting...' : 'Save Quotation (Draft)'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}


// --- SUBCOMPONENT: COMPLETE PICK MODAL ---
function CompletePickModal({ pickList, authHeaders, onClose, onSuccess }) {
  const [items, setItems] = useState(
    pickList.items.map((it) => ({
      pick_item_id: it.id,
      sku: it.sku,
      product_name: it.product_name,
      reserved_quantity: it.reserved_quantity,
      picked_quantity: it.reserved_quantity,
      short_picked_quantity: 0,
      short_pick_reason: '',
    }))
  )
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const handleItemChange = (idx, field, val) => {
    const next = [...items]
    next[idx][field] = val
    if (field === 'picked_quantity') {
      const picked = Number(val)
      const resv = next[idx].reserved_quantity
      next[idx].short_picked_quantity = Math.max(0, resv - picked)
    }
    setItems(next)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const payload = {
        items: items.map((it) => ({
          pick_item_id: it.pick_item_id,
          picked_quantity: Number(it.picked_quantity),
          short_picked_quantity: Number(it.short_picked_quantity),
          short_pick_reason: it.short_pick_reason || null,
        })),
      }
      const res = await apiFetch(`/api/sales-pick-lists/${pickList.id}/complete`, {
        method: 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (res.ok) {
        onSuccess()
      } else {
        const err = await res.json()
        setError(err.detail || 'Failed to complete pick list.')
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="erp-modal-backdrop">
      <div className="erp-modal-card large">
        <div className="erp-modal-head">
          <h2>Complete Pick List {pickList.pick_list_number}</h2>
          <button className="close-btn" onClick={onClose}><X size={18} /></button>
        </div>
        <form onSubmit={handleSubmit} className="erp-modal-body">
          {error && <div className="erp-alert-banner error">{error}</div>}
          <table className="erp-data-table">
            <thead>
              <tr>
                <th>Product</th>
                <th>Reserved Qty</th>
                <th>Picked Qty</th>
                <th>Short Qty</th>
                <th>Short Pick Exception Reason</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it, idx) => (
                <tr key={it.pick_item_id}>
                  <td><strong>{it.sku}</strong> - {it.product_name}</td>
                  <td>{it.reserved_quantity}</td>
                  <td>
                    <input
                      type="number"
                      step="any"
                      min="0"
                      max={it.reserved_quantity}
                      value={it.picked_quantity}
                      onChange={(e) => handleItemChange(idx, 'picked_quantity', e.target.value)}
                      required
                    />
                  </td>
                  <td>{it.short_picked_quantity}</td>
                  <td>
                    <input
                      type="text"
                      placeholder="e.g. damaged stock, bin mismatch"
                      value={it.short_pick_reason}
                      onChange={(e) => handleItemChange(idx, 'short_pick_reason', e.target.value)}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="erp-modal-foot">
            <button type="button" className="erp-btn secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="erp-btn primary" disabled={submitting}>
              {submitting ? 'Completing...' : 'Confirm Pick Completion'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}


// --- SUBCOMPONENT: NEW DISPATCH MODAL ---
function NewDispatchModal({ orders, warehouses, authHeaders, onClose, onSuccess }) {
  const [orderId, setOrderId] = useState(orders[0]?.id || '')
  const [warehouseId, setWarehouseId] = useState(warehouses[0]?.id || 'wh-main')
  const [carrier, setCarrier] = useState('')
  const [trackingNumber, setTrackingNumber] = useState('')
  const [vehicleNo, setVehicleNo] = useState('')
  const [packageCount, setPackageCount] = useState(1)
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const selectedOrderObj = useMemo(() => orders.find((o) => o.id === orderId), [orders, orderId])

  const [quantities, setQuantities] = useState({})

  useEffect(() => {
    if (selectedOrderObj) {
      const q = {}
      selectedOrderObj.items.forEach((it) => {
        const remaining = Math.max(0, it.ordered_quantity - it.dispatched_quantity)
        q[it.id] = remaining
      })
      setQuantities(q)
    }
  }, [selectedOrderObj])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const itemsToDispatch = Object.entries(quantities)
        .filter(([_, qty]) => Number(qty) > 0)
        .map(([itemId, qty]) => ({
          order_item_id: itemId,
          quantity_dispatched: Number(qty),
        }))

      if (itemsToDispatch.length === 0) {
        setError('Please specify at least one positive quantity to dispatch.')
        setSubmitting(false)
        return
      }

      const payload = {
        sales_order_id: orderId,
        warehouse_id: warehouseId,
        carrier_name: carrier || null,
        tracking_number: trackingNumber || null,
        vehicle_number: vehicleNo || null,
        package_count: Number(packageCount) || 1,
        items: itemsToDispatch,
      }

      const res = await apiFetch('/api/sales-dispatches', {
        method: 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (res.ok) {
        onSuccess()
      } else {
        const err = await res.json()
        setError(err.detail || 'Dispatch failed.')
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="erp-modal-backdrop">
      <div className="erp-modal-card large">
        <div className="erp-modal-head">
          <h2>Create Commercial Dispatch &amp; Fulfilment</h2>
          <button className="close-btn" onClick={onClose}><X size={18} /></button>
        </div>
        <form onSubmit={handleSubmit} className="erp-modal-body">
          {error && <div className="erp-alert-banner error">{error}</div>}
          <div className="erp-form-grid">
            <div className="form-group">
              <label>Sales Order *</label>
              <select value={orderId} onChange={(e) => setOrderId(e.target.value)} required>
                {orders.map((o) => (
                  <option key={o.id} value={o.id}>{o.order_number} — {o.customer_name} ({o.status})</option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label>Dispatch Warehouse *</label>
              <select value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)} required>
                {warehouses.map((w) => (
                  <option key={w.id} value={w.id}>{w.name} ({w.code})</option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label>Carrier Name</label>
              <input value={carrier} onChange={(e) => setCarrier(e.target.value)} placeholder="e.g. Maersk, DHL, BlueDart" />
            </div>
            <div className="form-group">
              <label>Tracking Number</label>
              <input value={trackingNumber} onChange={(e) => setTrackingNumber(e.target.value)} />
            </div>
            <div className="form-group">
              <label>Vehicle / Container No</label>
              <input value={vehicleNo} onChange={(e) => setVehicleNo(e.target.value)} />
            </div>
            <div className="form-group">
              <label>Package Count</label>
              <input type="number" min="1" value={packageCount} onChange={(e) => setPackageCount(e.target.value)} />
            </div>
          </div>

          <h3>Line Items to Dispatch</h3>
          <table className="erp-data-table">
            <thead>
              <tr>
                <th>Product</th>
                <th>Ordered</th>
                <th>Dispatched So Far</th>
                <th>Remaining</th>
                <th>Quantity to Dispatch Now</th>
              </tr>
            </thead>
            <tbody>
              {selectedOrderObj?.items.map((it) => {
                const rem = Math.max(0, it.ordered_quantity - it.dispatched_quantity)
                return (
                  <tr key={it.id}>
                    <td><strong>{it.sku}</strong> - {it.product_name}</td>
                    <td>{it.ordered_quantity} {it.uom}</td>
                    <td>{it.dispatched_quantity}</td>
                    <td><strong>{rem}</strong></td>
                    <td>
                      <input
                        type="number"
                        step="any"
                        min="0"
                        max={rem}
                        value={quantities[it.id] ?? rem}
                        onChange={(e) => setQuantities({ ...quantities, [it.id]: e.target.value })}
                        required
                      />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>

          <div className="erp-modal-foot">
            <button type="button" className="erp-btn secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="erp-btn primary" disabled={submitting}>
              {submitting ? 'Posting Dispatch...' : 'Confirm Dispatch & Deduct Stock'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}


// --- SUBCOMPONENT: CONFIRM DELIVERY MODAL ---
function DeliverDispatchModal({ dispatch, authHeaders, onClose, onSuccess }) {
  const [deliveryDate, setDeliveryDate] = useState(new Date().toISOString().slice(0, 10))
  const [deliveredBy, setDeliveredBy] = useState('Local Courier')
  const [notes, setNotes] = useState('')
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const payload = {
        delivery_date: deliveryDate,
        delivered_by: deliveredBy,
        notes: notes || null,
        items: dispatch.items.map((it) => ({
          dispatch_item_id: it.id,
          quantity_delivered: it.quantity_dispatched,
        })),
      }
      const res = await apiFetch(`/api/sales-dispatches/${dispatch.id}/deliver`, {
        method: 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (res.ok) {
        onSuccess()
      } else {
        const err = await res.json()
        setError(err.detail || 'Delivery confirmation failed.')
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="erp-modal-backdrop">
      <div className="erp-modal-card">
        <div className="erp-modal-head">
          <h2>Confirm Delivery for {dispatch.dispatch_number}</h2>
          <button className="close-btn" onClick={onClose}><X size={18} /></button>
        </div>
        <form onSubmit={handleSubmit} className="erp-modal-body">
          {error && <div className="erp-alert-banner error">{error}</div>}
          <div className="form-group">
            <label>Delivery Date</label>
            <input type="date" value={deliveryDate} onChange={(e) => setDeliveryDate(e.target.value)} required />
          </div>
          <div className="form-group">
            <label>Delivered By / Recipient</label>
            <input value={deliveredBy} onChange={(e) => setDeliveredBy(e.target.value)} required />
          </div>
          <div className="form-group">
            <label>Delivery Notes</label>
            <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Signed POD received, cargo received in good order..." />
          </div>
          <div className="erp-modal-foot">
            <button type="button" className="erp-btn secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="erp-btn primary" disabled={submitting}>
              {submitting ? 'Saving...' : 'Confirm Delivery'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}


// --- SUBCOMPONENT: PROCESS RETURN MODAL ---
function ProcessReturnModal({ salesReturn, authHeaders, onClose, onSuccess }) {
  const [items, setItems] = useState(
    salesReturn.items.map((it) => ({
      order_item_id: it.order_item_id,
      sku: it.sku,
      returned_quantity: it.returned_quantity,
      accepted_quantity: it.returned_quantity,
      quarantined_quantity: 0,
      rejected_quantity: 0,
      inspection_notes: '',
    }))
  )
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const handleQtyChange = (idx, field, val) => {
    const next = [...items]
    next[idx][field] = Number(val)
    setItems(next)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const payload = {
        items: items.map((it) => ({
          order_item_id: it.order_item_id,
          returned_quantity: it.returned_quantity,
          accepted_quantity: Number(it.accepted_quantity),
          quarantined_quantity: Number(it.quarantined_quantity),
          rejected_quantity: Number(it.rejected_quantity),
          inspection_notes: it.inspection_notes || null,
        })),
      }
      const res = await apiFetch(`/api/sales-returns/${salesReturn.id}/process`, {
        method: 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (res.ok) {
        onSuccess()
      } else {
        const err = await res.json()
        setError(err.detail || 'Processing return failed.')
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="erp-modal-backdrop">
      <div className="erp-modal-card large">
        <div className="erp-modal-head">
          <h2>Inspect &amp; Process Return {salesReturn.return_number}</h2>
          <button className="close-btn" onClick={onClose}><X size={18} /></button>
        </div>
        <form onSubmit={handleSubmit} className="erp-modal-body">
          {error && <div className="erp-alert-banner error">{error}</div>}
          <p className="erp-subtext">
            Accepted units are returned to available inventory. Quarantined and rejected units are strictly segregated in non-available balances.
          </p>
          <table className="erp-data-table">
            <thead>
              <tr>
                <th>Product</th>
                <th>Returned Qty</th>
                <th>Accepted (Available)</th>
                <th>Quarantined</th>
                <th>Rejected</th>
                <th>Inspection Notes</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it, idx) => (
                <tr key={idx}>
                  <td><strong>{it.sku}</strong></td>
                  <td>{it.returned_quantity}</td>
                  <td>
                    <input
                      type="number"
                      step="any"
                      min="0"
                      value={it.accepted_quantity}
                      onChange={(e) => handleQtyChange(idx, 'accepted_quantity', e.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      step="any"
                      min="0"
                      value={it.quarantined_quantity}
                      onChange={(e) => handleQtyChange(idx, 'quarantined_quantity', e.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      step="any"
                      min="0"
                      value={it.rejected_quantity}
                      onChange={(e) => handleQtyChange(idx, 'rejected_quantity', e.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      type="text"
                      placeholder="e.g. sealed packaging intact"
                      value={it.inspection_notes}
                      onChange={(e) => {
                        const next = [...items]
                        next[idx].inspection_notes = e.target.value
                        setItems(next)
                      }}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="erp-modal-foot">
            <button type="button" className="erp-btn secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="erp-btn primary" disabled={submitting}>
              {submitting ? 'Processing...' : 'Post Return Movements'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
