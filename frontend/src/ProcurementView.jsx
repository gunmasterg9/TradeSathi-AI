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
  FileCheck,
  Filter,
  History,
  Lock,
  Package,
  Plus,
  RefreshCw,
  Search,
  Shield,
  Truck,
  X,
  XCircle,
} from 'lucide-react'
import { apiFetch } from './api'

export default function ProcurementView({ onNavigateShipment }) {
  const [activeTab, setActiveTab] = useState('orders') // 'orders' | 'receipts' | 'inventory'
  const [currentRole, setCurrentRole] = useState('admin') // 'admin' | 'procurement' | 'warehouse' | 'sales' | 'viewer'
  const [operatorName, setOperatorName] = useState('Local Operator')

  // Auth headers
  const authHeaders = useMemo(
    () => ({
      'X-User-Role': currentRole,
      'X-User-Name': operatorName,
    }),
    [currentRole, operatorName]
  )

  // Master Data Cache
  const [suppliersList, setSuppliersList] = useState([])
  const [productsList, setProductsList] = useState([])

  // Purchase Orders State
  const [orders, setOrders] = useState([])
  const [ordersTotal, setOrdersTotal] = useState(0)
  const [orderSearch, setOrderSearch] = useState('')
  const [orderStatusFilter, setOrderStatusFilter] = useState('all')
  const [ordersLoading, setOrdersLoading] = useState(false)
  const [ordersError, setOrdersError] = useState(null)

  // Goods Receipts State
  const [receipts, setReceipts] = useState([])
  const [receiptsTotal, setReceiptsTotal] = useState(0)
  const [receiptSearch, setReceiptSearch] = useState('')
  const [receiptStatusFilter, setReceiptStatusFilter] = useState('all')
  const [receiptsLoading, setReceiptsLoading] = useState(false)
  const [receiptsError, setReceiptsError] = useState(null)

  // Inventory State
  const [inventoryBalances, setInventoryBalances] = useState([])
  const [inventoryMovements, setInventoryMovements] = useState([])
  const [inventoryLoading, setInventoryLoading] = useState(false)
  const [stockTypeFilter, setStockTypeFilter] = useState('all')

  // Modals
  const [isPoModalOpen, setIsPoModalOpen] = useState(false)
  const [selectedPoForView, setSelectedPoForView] = useState(null)
  const [poForm, setPoForm] = useState(getInitialPoForm())
  const [poFormLoading, setPoFormLoading] = useState(false)
  const [poFormError, setPoFormError] = useState(null)

  const [isGrModalOpen, setIsGrModalOpen] = useState(false)
  const [grForm, setGrForm] = useState(getInitialGrForm())
  const [grFormLoading, setGrFormLoading] = useState(false)
  const [grFormError, setGrFormError] = useState(null)
  const [selectedPoForGr, setSelectedPoForGr] = useState(null)

  const [confirmActionModal, setConfirmActionModal] = useState(null) // { action, po, gr }

  function getInitialPoForm() {
    return {
      po_number: `PO-${new Date().getFullYear()}-${Math.floor(1000 + Math.random() * 9000)}`,
      supplier_id: '',
      order_date: new Date().toISOString().split('T')[0],
      expected_delivery_date: '',
      currency: 'INR',
      payment_terms: 'Net 30',
      notes: '',
      items: [
        {
          product_id: '',
          ordered_qty: 10,
          unit_price: 0,
          tax_rate_pct: 5,
        },
      ],
    }
  }

  function getInitialGrForm() {
    return {
      receipt_number: `GR-${new Date().getFullYear()}-${Math.floor(1000 + Math.random() * 9000)}`,
      idempotency_key: `idemp-gr-${Date.now()}-${Math.random().toString(36).substring(2, 8)}`,
      po_id: '',
      receipt_date: new Date().toISOString().split('T')[0],
      notes: '',
      items: [],
    }
  }

  // Load suppliers and products on mount
  useEffect(() => {
    async function loadMasterData() {
      try {
        const [supRes, prodRes] = await Promise.all([
          apiFetch('/api/suppliers?limit=100', { headers: authHeaders }, 'Failed loading suppliers'),
          apiFetch('/api/products?limit=100&is_active=true', { headers: authHeaders }, 'Failed loading products'),
        ])
        setSuppliersList(supRes.items || [])
        setProductsList(prodRes.items || [])
      } catch (err) {
        console.error('Error loading master data references:', err)
      }
    }
    loadMasterData()
  }, [])

  // Fetch Orders
  async function fetchOrders() {
    setOrdersLoading(true)
    setOrdersError(null)
    try {
      let query = `?limit=100`
      if (orderSearch.trim()) query += `&search=${encodeURIComponent(orderSearch.trim())}`
      if (orderStatusFilter !== 'all') query += `&status=${encodeURIComponent(orderStatusFilter)}`

      const res = await apiFetch(`/api/purchase-orders${query}`, { headers: authHeaders }, 'Failed to fetch POs')
      setOrders(res.items || [])
      setOrdersTotal(res.total || 0)
    } catch (err) {
      setOrdersError(err.message || 'Error loading purchase orders')
    } finally {
      setOrdersLoading(false)
    }
  }

  // Fetch Receipts
  async function fetchReceipts() {
    setReceiptsLoading(true)
    setReceiptsError(null)
    try {
      let query = `?limit=100`
      if (receiptSearch.trim()) query += `&search=${encodeURIComponent(receiptSearch.trim())}`
      if (receiptStatusFilter !== 'all') query += `&status=${encodeURIComponent(receiptStatusFilter)}`

      const res = await apiFetch(`/api/goods-receipts${query}`, { headers: authHeaders }, 'Failed to fetch receipts')
      setReceipts(res.items || [])
      setReceiptsTotal(res.total || 0)
    } catch (err) {
      setReceiptsError(err.message || 'Error loading receipts')
    } finally {
      setReceiptsLoading(false)
    }
  }

  // Fetch Inventory
  async function fetchInventory() {
    setInventoryLoading(true)
    try {
      const q = stockTypeFilter !== 'all' ? `?stock_type=${stockTypeFilter}` : ''
      const [balRes, movRes] = await Promise.all([
        apiFetch(`/api/inventory/balances${q}`, { headers: authHeaders }, 'Failed to fetch balances'),
        apiFetch(`/api/inventory/movements?limit=100`, { headers: authHeaders }, 'Failed to fetch movements'),
      ])
      setInventoryBalances(balRes.items || [])
      setInventoryMovements(movRes.items || [])
    } catch (err) {
      console.error('Error loading inventory:', err)
    } finally {
      setInventoryLoading(false)
    }
  }

  useEffect(() => {
    if (activeTab === 'orders') fetchOrders()
    if (activeTab === 'receipts') fetchReceipts()
    if (activeTab === 'inventory') fetchInventory()
  }, [activeTab, orderSearch, orderStatusFilter, receiptSearch, receiptStatusFilter, stockTypeFilter])

  // --- Purchase Order Form Helpers ---
  function handlePoLineChange(index, field, value) {
    const updated = [...poForm.items]
    updated[index] = { ...updated[index], [field]: value }

    // If product changed, auto-populate unit price from master catalog
    if (field === 'product_id') {
      const found = productsList.find((p) => p.id === value)
      if (found) {
        updated[index].unit_price = found.default_purchase_cost || 0
        updated[index].tax_rate_pct = found.tax_rate_pct || 0
      }
    }
    setPoForm({ ...poForm, items: updated })
  }

  function addPoLine() {
    setPoForm({
      ...poForm,
      items: [
        ...poForm.items,
        {
          product_id: '',
          ordered_qty: 10,
          unit_price: 0,
          tax_rate_pct: 5,
        },
      ],
    })
  }

  function removePoLine(index) {
    if (poForm.items.length <= 1) return
    const updated = poForm.items.filter((_, i) => i !== index)
    setPoForm({ ...poForm, items: updated })
  }

  // Calculated PO totals
  const poComputedTotals = useMemo(() => {
    let subtotal = 0
    let taxTotal = 0
    poForm.items.forEach((item) => {
      const qty = parseFloat(item.ordered_qty) || 0
      const price = parseFloat(item.unit_price) || 0
      const taxRate = parseFloat(item.tax_rate_pct) || 0
      const lineTotal = qty * price
      subtotal += lineTotal
      taxTotal += lineTotal * (taxRate / 100.0)
    })
    return {
      subtotal: Math.round(subtotal * 100) / 100,
      taxTotal: Math.round(taxTotal * 100) / 100,
      grandTotal: Math.round((subtotal + taxTotal) * 100) / 100,
    }
  }, [poForm.items])

  async function handleSavePo(e) {
    e.preventDefault()
    setPoFormLoading(true)
    setPoFormError(null)
    try {
      await apiFetch(
        '/api/purchase-orders',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...authHeaders },
          body: JSON.stringify(poForm),
        },
        'Failed to create purchase order'
      )
      setIsPoModalOpen(false)
      fetchOrders()
    } catch (err) {
      setPoFormError(err.message || 'Error creating purchase order')
    } finally {
      setPoFormLoading(false)
    }
  }

  // PO Actions: Submit, Approve, Cancel
  async function handlePoAction(poId, actionName) {
    try {
      await apiFetch(
        `/api/purchase-orders/${poId}/${actionName}`,
        {
          method: 'POST',
          headers: authHeaders,
        },
        `Failed to ${actionName} PO`
      )
      setConfirmActionModal(null)
      fetchOrders()
      if (selectedPoForView && selectedPoForView.id === poId) {
        const refreshed = await apiFetch(`/api/purchase-orders/${poId}`, { headers: authHeaders })
        setSelectedPoForView(refreshed)
      }
    } catch (err) {
      alert(`Error: ${err.message}`)
    }
  }

  // Open GR creation modal for a specific PO
  function openCreateGrModal(po) {
    setSelectedPoForGr(po)
    const grLines = po.items.map((poi) => {
      const remaining = Math.max(0, poi.ordered_qty - poi.received_qty)
      return {
        po_item_id: poi.id,
        sku: poi.sku,
        product_name: poi.product_name,
        uom: poi.uom,
        ordered_qty: poi.ordered_qty,
        previously_received: poi.received_qty,
        remaining_qty: remaining,
        received_qty: remaining, // default to remaining
        accepted_qty: remaining,
        rejected_qty: 0,
        quarantined_qty: 0,
        inspection_notes: '',
        rejection_reason: '',
      }
    })

    setGrForm({
      ...getInitialGrForm(),
      po_id: po.id,
      items: grLines,
    })
    setIsGrModalOpen(true)
  }

  function handleGrLineChange(index, field, value) {
    const updated = [...grForm.items]
    updated[index] = { ...updated[index], [field]: value }

    // Auto-balance accepted_qty if received_qty changes
    if (field === 'received_qty') {
      const rec = parseFloat(value) || 0
      updated[index].accepted_qty = rec
      updated[index].rejected_qty = 0
      updated[index].quarantined_qty = 0
    }
    setGrForm({ ...grForm, items: updated })
  }

  async function handleSaveGr(e) {
    e.preventDefault()
    setGrFormLoading(true)
    setGrFormError(null)

    // Pre-validate quantities on client
    for (let i = 0; i < grForm.items.length; i++) {
      const item = grForm.items[i]
      const rec = parseFloat(item.received_qty) || 0
      const acc = parseFloat(item.accepted_qty) || 0
      const rej = parseFloat(item.rejected_qty) || 0
      const quar = parseFloat(item.quarantined_qty) || 0

      if (rec <= 0) {
        setGrFormError(`Line ${i + 1} (${item.sku}): received quantity must be > 0.`)
        setGrFormLoading(false)
        return
      }
      if (Math.round((acc + rej + quar) * 1000) !== Math.round(rec * 1000)) {
        setGrFormError(
          `Line ${i + 1} (${item.sku}): Accepted (${acc}) + Rejected (${rej}) + Quarantined (${quar}) must equal Received (${rec}).`
        )
        setGrFormLoading(false)
        return
      }
      if (rec > item.remaining_qty) {
        setGrFormError(
          `Line ${i + 1} (${item.sku}): Received (${rec}) exceeds remaining ordered balance (${item.remaining_qty}). Over-receipt is prohibited.`
        )
        setGrFormLoading(false)
        return
      }
    }

    try {
      const payload = {
        receipt_number: grForm.receipt_number,
        idempotency_key: grForm.idempotency_key,
        po_id: grForm.po_id,
        receipt_date: grForm.receipt_date,
        notes: grForm.notes,
        items: grForm.items.map((itm) => ({
          po_item_id: itm.po_item_id,
          received_qty: parseFloat(itm.received_qty) || 0,
          accepted_qty: parseFloat(itm.accepted_qty) || 0,
          rejected_qty: parseFloat(itm.rejected_qty) || 0,
          quarantined_qty: parseFloat(itm.quarantined_qty) || 0,
          inspection_notes: itm.inspection_notes || null,
          rejection_reason: itm.rejection_reason || null,
        })),
      }

      await apiFetch(
        '/api/goods-receipts',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...authHeaders },
          body: JSON.stringify(payload),
        },
        'Failed to record goods receipt'
      )
      setIsGrModalOpen(false)
      fetchReceipts()
      fetchOrders()
    } catch (err) {
      setGrFormError(err.message || 'Error recording goods receipt')
    } finally {
      setGrFormLoading(false)
    }
  }

  // Post Goods Receipt to Inventory
  async function handlePostGr(receiptId) {
    const postKey = `post-key-${receiptId}-${Date.now()}`
    try {
      const res = await apiFetch(
        `/api/goods-receipts/${receiptId}/post?idempotency_key=${postKey}`,
        {
          method: 'POST',
          headers: authHeaders,
        },
        'Failed to post goods receipt to inventory'
      )
      alert(res.message || 'Receipt posted to inventory!')
      setConfirmActionModal(null)
      fetchReceipts()
      fetchInventory()
    } catch (err) {
      alert(`Posting Error: ${err.message}`)
    }
  }

  return (
    <div className="erp-master-container">
      {/* Top Header & Role Switcher */}
      <div className="erp-header-row">
        <div>
          <div className="eyebrow">EXPORTMATE ERP — PHASE 2</div>
          <h1 className="erp-title">Procurement & Goods Receipt</h1>
          <p className="erp-subtitle">
            Purchase Orders, QA Receiving Inspection, and Real-Time Inventory Stock Ledger.
          </p>
        </div>

        {/* RBAC Simulator Bar */}
        <div className="erp-rbac-badge-bar">
          <Shield size={16} className="text-accent" />
          <span className="rbac-label">Active Role:</span>
          <select
            className="rbac-select"
            value={currentRole}
            onChange={(e) => setCurrentRole(e.target.value)}
            title="Switch user role to test permissions"
          >
            <option value="admin">Administrator (Full Access & Approvals)</option>
            <option value="procurement">Procurement (Create/Submit POs & GRs)</option>
            <option value="warehouse">Warehouse (Receiving, QA & Posting)</option>
            <option value="sales">Sales (Read-Only)</option>
            <option value="viewer">Viewer (Read-Only)</option>
          </select>
          {currentRole === 'viewer' && (
            <span className="badge-readonly">
              <Lock size={12} /> Read-Only
            </span>
          )}
        </div>
      </div>

      {/* Primary Subtabs Navigation */}
      <div className="erp-subtabs-nav">
        <button
          className={`erp-subtab-btn ${activeTab === 'orders' ? 'active' : ''}`}
          onClick={() => setActiveTab('orders')}
        >
          <FileCheck size={16} />
          <span>Purchase Orders</span>
          {ordersTotal > 0 && <span className="erp-count-pill">{ordersTotal}</span>}
        </button>

        <button
          className={`erp-subtab-btn ${activeTab === 'receipts' ? 'active' : ''}`}
          onClick={() => setActiveTab('receipts')}
        >
          <Truck size={16} />
          <span>Goods Receipts</span>
          {receiptsTotal > 0 && <span className="erp-count-pill">{receiptsTotal}</span>}
        </button>

        <button
          className={`erp-subtab-btn ${activeTab === 'inventory' ? 'active' : ''}`}
          onClick={() => setActiveTab('inventory')}
        >
          <Boxes size={16} />
          <span>Inventory Ledger</span>
          {inventoryBalances.length > 0 && (
            <span className="erp-count-pill">{inventoryBalances.length}</span>
          )}
        </button>
      </div>

      {/* ========================================================================= */}
      {/* 1. PURCHASE ORDERS TAB */}
      {/* ========================================================================= */}
      {activeTab === 'orders' && (
        <div className="erp-tab-pane">
          <div className="erp-actions-bar">
            <div className="erp-search-group">
              <Search size={16} className="search-icon" />
              <input
                type="text"
                placeholder="Search PO number or notes..."
                value={orderSearch}
                onChange={(e) => setOrderSearch(e.target.value)}
                className="erp-search-input"
              />
            </div>

            <div className="erp-filter-group">
              <Filter size={16} className="filter-icon" />
              <select
                value={orderStatusFilter}
                onChange={(e) => setOrderStatusFilter(e.target.value)}
                className="erp-filter-select"
              >
                <option value="all">All Statuses</option>
                <option value="draft">Draft</option>
                <option value="submitted">Submitted</option>
                <option value="approved">Approved</option>
                <option value="partially_received">Partially Received</option>
                <option value="fully_received">Fully Received</option>
                <option value="cancelled">Cancelled</option>
              </select>
            </div>

            <div className="erp-buttons-group">
              <button onClick={fetchOrders} className="btn-secondary" title="Refresh orders">
                <RefreshCw size={14} />
              </button>
              {['admin', 'procurement'].includes(currentRole) && (
                <button
                  onClick={() => {
                    setPoForm(getInitialPoForm())
                    setPoFormError(null)
                    setIsPoModalOpen(true)
                  }}
                  className="btn-primary"
                >
                  <Plus size={16} /> New Purchase Order
                </button>
              )}
            </div>
          </div>

          {ordersError && (
            <div className="erp-error-banner">
              <AlertTriangle size={16} /> {ordersError}
            </div>
          )}

          {ordersLoading ? (
            <div className="erp-loading-state">Loading Purchase Orders...</div>
          ) : orders.length === 0 ? (
            <div className="erp-empty-state">
              <FileCheck size={48} className="empty-icon" />
              <h3>No Purchase Orders Found</h3>
              <p>Create your first purchase order to initiate procurement and goods receiving.</p>
            </div>
          ) : (
            <div className="erp-table-responsive">
              <table className="erp-table">
                <thead>
                  <tr>
                    <th>PO Number</th>
                    <th>Supplier</th>
                    <th>Order Date</th>
                    <th>Delivery Date</th>
                    <th>Total Value</th>
                    <th>Receiving Progress</th>
                    <th>Status</th>
                    <th style={{ textAlign: 'right' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {orders.map((po) => {
                    const totalOrdered = po.items.reduce((acc, i) => acc + i.ordered_qty, 0)
                    const totalReceived = po.items.reduce((acc, i) => acc + i.received_qty, 0)
                    const pct = totalOrdered > 0 ? Math.min(100, Math.round((totalReceived / totalOrdered) * 100)) : 0

                    return (
                      <tr key={po.id}>
                        <td>
                          <strong>{po.po_number}</strong>
                          <div className="cell-subtext">{po.items.length} line items</div>
                        </td>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <Building2 size={14} className="text-muted" />
                            <span>{po.supplier_name || po.supplier_id}</span>
                          </div>
                        </td>
                        <td>{po.order_date}</td>
                        <td>{po.expected_delivery_date || '—'}</td>
                        <td>
                          <strong>
                            {po.currency} {po.grand_total.toLocaleString()}
                          </strong>
                          <div className="cell-subtext">Tax: {po.tax_total.toLocaleString()}</div>
                        </td>
                        <td style={{ minWidth: '130px' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginBottom: '2px' }}>
                            <span>{totalReceived} / {totalOrdered}</span>
                            <span>{pct}%</span>
                          </div>
                          <div style={{ background: 'var(--border-color)', borderRadius: '4px', height: '6px', overflow: 'hidden' }}>
                            <div style={{ width: `${pct}%`, background: pct === 100 ? '#10b981' : '#3b82f6', height: '100%' }} />
                          </div>
                        </td>
                        <td>
                          <span className={`status-pill status-${po.status}`}>
                            {po.status.replace('_', ' ')}
                          </span>
                        </td>
                        <td style={{ textAlign: 'right' }}>
                          <div className="action-buttons-cell">
                            <button
                              onClick={() => setSelectedPoForView(po)}
                              className="btn-action-icon"
                              title="View PO Details"
                            >
                              <Eye size={15} />
                            </button>

                            {/* Receiving Action */}
                            {['approved', 'partially_received'].includes(po.status) &&
                              ['admin', 'procurement', 'warehouse'].includes(currentRole) && (
                                <button
                                  onClick={() => openCreateGrModal(po)}
                                  className="btn-action-icon btn-action-success"
                                  title="Receive Goods"
                                >
                                  <Truck size={15} />
                                </button>
                              )}

                            {/* Submit */}
                            {po.status === 'draft' && ['admin', 'procurement'].includes(currentRole) && (
                              <button
                                onClick={() => handlePoAction(po.id, 'submit')}
                                className="btn-action-sm btn-action-blue"
                              >
                                Submit
                              </button>
                            )}

                            {/* Approve */}
                            {['draft', 'submitted'].includes(po.status) && currentRole === 'admin' && (
                              <button
                                onClick={() => handlePoAction(po.id, 'approve')}
                                className="btn-action-sm btn-action-success"
                              >
                                Approve
                              </button>
                            )}

                            {/* Cancel */}
                            {['draft', 'submitted', 'approved'].includes(po.status) &&
                              ['admin', 'procurement'].includes(currentRole) && (
                                <button
                                  onClick={() => setConfirmActionModal({ action: 'cancel', po })}
                                  className="btn-action-icon btn-action-danger"
                                  title="Cancel PO"
                                >
                                  <XCircle size={15} />
                                </button>
                              )}
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ========================================================================= */}
      {/* 2. GOODS RECEIPTS TAB */}
      {/* ========================================================================= */}
      {activeTab === 'receipts' && (
        <div className="erp-tab-pane">
          <div className="erp-actions-bar">
            <div className="erp-search-group">
              <Search size={16} className="search-icon" />
              <input
                type="text"
                placeholder="Search receipt number or notes..."
                value={receiptSearch}
                onChange={(e) => setReceiptSearch(e.target.value)}
                className="erp-search-input"
              />
            </div>

            <div className="erp-filter-group">
              <Filter size={16} className="filter-icon" />
              <select
                value={receiptStatusFilter}
                onChange={(e) => setReceiptStatusFilter(e.target.value)}
                className="erp-filter-select"
              >
                <option value="all">All Statuses</option>
                <option value="draft">Draft / Inspected</option>
                <option value="posted">Posted to Ledger</option>
              </select>
            </div>

            <div className="erp-buttons-group">
              <button onClick={fetchReceipts} className="btn-secondary" title="Refresh receipts">
                <RefreshCw size={14} />
              </button>
            </div>
          </div>

          {receiptsError && (
            <div className="erp-error-banner">
              <AlertTriangle size={16} /> {receiptsError}
            </div>
          )}

          {receiptsLoading ? (
            <div className="erp-loading-state">Loading Goods Receipts...</div>
          ) : receipts.length === 0 ? (
            <div className="erp-empty-state">
              <Truck size={48} className="empty-icon" />
              <h3>No Goods Receipts Recorded</h3>
              <p>Goods receipts are created against approved Purchase Orders from the Purchase Orders tab.</p>
            </div>
          ) : (
            <div className="erp-table-responsive">
              <table className="erp-table">
                <thead>
                  <tr>
                    <th>Receipt #</th>
                    <th>PO Reference</th>
                    <th>Supplier</th>
                    <th>Receipt Date</th>
                    <th>QA Quantities (Acc / Quar / Rej)</th>
                    <th>Status</th>
                    <th style={{ textAlign: 'right' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {receipts.map((gr) => {
                    const accTotal = gr.items.reduce((acc, i) => acc + i.accepted_qty, 0)
                    const quarTotal = gr.items.reduce((acc, i) => acc + i.quarantined_qty, 0)
                    const rejTotal = gr.items.reduce((acc, i) => acc + i.rejected_qty, 0)

                    return (
                      <tr key={gr.id}>
                        <td>
                          <strong>{gr.receipt_number}</strong>
                          <div className="cell-subtext">{gr.received_by}</div>
                        </td>
                        <td>
                          <strong>{gr.po_number || gr.po_id}</strong>
                        </td>
                        <td>{gr.supplier_name || gr.supplier_id}</td>
                        <td>{gr.receipt_date}</td>
                        <td>
                          <div style={{ display: 'flex', gap: '6px' }}>
                            <span className="badge-qty-acc" title="Accepted Stock">
                              {accTotal} acc
                            </span>
                            {quarTotal > 0 && (
                              <span className="badge-qty-quar" title="Quarantined Stock">
                                {quarTotal} quar
                              </span>
                            )}
                            {rejTotal > 0 && (
                              <span className="badge-qty-rej" title="Rejected Stock">
                                {rejTotal} rej
                              </span>
                            )}
                          </div>
                        </td>
                        <td>
                          <span className={`status-pill status-${gr.status}`}>
                            {gr.status === 'posted' ? 'Posted to Ledger' : 'Draft / QA'}
                          </span>
                        </td>
                        <td style={{ textAlign: 'right' }}>
                          <div className="action-buttons-cell">
                            {gr.status !== 'posted' && ['admin', 'warehouse'].includes(currentRole) && (
                              <button
                                onClick={() => setConfirmActionModal({ action: 'post', gr })}
                                className="btn-action-sm btn-action-success"
                                title="Post to inventory ledger"
                              >
                                Post to Stock
                              </button>
                            )}
                            {gr.status === 'posted' && (
                              <span className="badge-success-outline">
                                <Check size={12} /> Posted
                              </span>
                            )}
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ========================================================================= */}
      {/* 3. INVENTORY LEDGER TAB */}
      {/* ========================================================================= */}
      {activeTab === 'inventory' && (
        <div className="erp-tab-pane">
          <div className="erp-actions-bar">
            <div className="erp-filter-group">
              <Filter size={16} className="filter-icon" />
              <select
                value={stockTypeFilter}
                onChange={(e) => setStockTypeFilter(e.target.value)}
                className="erp-filter-select"
              >
                <option value="all">All Stock Types</option>
                <option value="available">Available Inventory Only</option>
                <option value="quarantined">Quarantined Stock Only</option>
                <option value="rejected">Rejected Stock Only</option>
              </select>
            </div>

            <div className="erp-buttons-group">
              <button onClick={fetchInventory} className="btn-secondary" title="Refresh stock">
                <RefreshCw size={14} />
              </button>
            </div>
          </div>

          <h3 className="section-title">Current Stock Balances</h3>
          {inventoryLoading ? (
            <div className="erp-loading-state">Loading stock balances...</div>
          ) : inventoryBalances.length === 0 ? (
            <div className="erp-empty-state">
              <Boxes size={48} className="empty-icon" />
              <h3>Inventory Ledger Empty</h3>
              <p>Once goods receipts are posted to inventory, physical on-hand balances will appear here.</p>
            </div>
          ) : (
            <div className="erp-table-responsive" style={{ marginBottom: '24px' }}>
              <table className="erp-table">
                <thead>
                  <tr>
                    <th>Product SKU</th>
                    <th>Product Name</th>
                    <th>Stock Type</th>
                    <th>On-Hand Quantity</th>
                    <th>Total Inventory Valuation</th>
                    <th>Last Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {inventoryBalances.map((b) => (
                    <tr key={`${b.product_id}-${b.stock_type}`}>
                      <td>
                        <strong>{b.sku}</strong>
                      </td>
                      <td>{b.product_name || '—'}</td>
                      <td>
                        <span className={`badge-stock-${b.stock_type}`}>
                          {b.stock_type.toUpperCase()}
                        </span>
                      </td>
                      <td>
                        <strong style={{ fontSize: '15px' }}>{b.on_hand_qty.toLocaleString()}</strong>
                      </td>
                      <td>
                        <strong>INR {b.total_value.toLocaleString()}</strong>
                      </td>
                      <td className="cell-subtext">{b.updated_at.replace('T', ' ').slice(0, 19)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h3 className="section-title" style={{ marginTop: '24px' }}>
            Append-Only Stock Movements History
          </h3>
          {inventoryMovements.length === 0 ? (
            <p className="cell-subtext">No stock movement entries recorded yet.</p>
          ) : (
            <div className="erp-table-responsive">
              <table className="erp-table">
                <thead>
                  <tr>
                    <th>Movement #</th>
                    <th>Movement Type</th>
                    <th>Reference</th>
                    <th>SKU</th>
                    <th>Quantity</th>
                    <th>Stock Type</th>
                    <th>Unit Cost</th>
                    <th>Actor</th>
                    <th>Timestamp</th>
                  </tr>
                </thead>
                <tbody>
                  {inventoryMovements.slice(0, 30).map((m) => (
                    <tr key={m.id}>
                      <td>
                        <strong>{m.movement_number}</strong>
                      </td>
                      <td>
                        <span className="badge-readonly">{m.movement_type}</span>
                      </td>
                      <td>{m.notes || m.reference_doc_id}</td>
                      <td>
                        <strong>{m.sku}</strong>
                      </td>
                      <td>
                        <strong style={{ color: m.quantity > 0 ? '#10b981' : '#ef4444' }}>
                          {m.quantity > 0 ? `+${m.quantity}` : m.quantity}
                        </strong>
                      </td>
                      <td>
                        <span className={`badge-stock-${m.stock_type}`}>{m.stock_type}</span>
                      </td>
                      <td>INR {m.unit_cost.toLocaleString()}</td>
                      <td>{m.performed_by}</td>
                      <td className="cell-subtext">{m.created_at.replace('T', ' ').slice(0, 19)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL: NEW PURCHASE ORDER */}
      {/* ========================================================================= */}
      {isPoModalOpen && (
        <div className="erp-modal-overlay">
          <div className="erp-modal" style={{ maxWidth: '850px' }}>
            <div className="erp-modal-header">
              <h2>Create Purchase Order</h2>
              <button onClick={() => setIsPoModalOpen(false)} className="btn-close">
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleSavePo}>
              <div className="erp-modal-body">
                {poFormError && (
                  <div className="erp-error-banner">
                    <AlertTriangle size={16} /> {poFormError}
                  </div>
                )}

                <div className="form-grid">
                  <div className="form-group">
                    <label>PO Number *</label>
                    <input
                      type="text"
                      required
                      value={poForm.po_number}
                      onChange={(e) => setPoForm({ ...poForm, po_number: e.target.value })}
                    />
                  </div>

                  <div className="form-group">
                    <label>Supplier *</label>
                    <select
                      required
                      value={poForm.supplier_id}
                      onChange={(e) => setPoForm({ ...poForm, supplier_id: e.target.value })}
                    >
                      <option value="">Select Supplier...</option>
                      {suppliersList.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.code} — {s.name} ({s.country})
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="form-group">
                    <label>Order Date *</label>
                    <input
                      type="date"
                      required
                      value={poForm.order_date}
                      onChange={(e) => setPoForm({ ...poForm, order_date: e.target.value })}
                    />
                  </div>

                  <div className="form-group">
                    <label>Expected Delivery Date</label>
                    <input
                      type="date"
                      value={poForm.expected_delivery_date}
                      onChange={(e) => setPoForm({ ...poForm, expected_delivery_date: e.target.value })}
                    />
                  </div>

                  <div className="form-group">
                    <label>Currency</label>
                    <input
                      type="text"
                      value={poForm.currency}
                      onChange={(e) => setPoForm({ ...poForm, currency: e.target.value.toUpperCase() })}
                    />
                  </div>

                  <div className="form-group">
                    <label>Payment Terms</label>
                    <input
                      type="text"
                      value={poForm.payment_terms}
                      onChange={(e) => setPoForm({ ...poForm, payment_terms: e.target.value })}
                    />
                  </div>
                </div>

                <div className="form-group" style={{ marginTop: '12px' }}>
                  <label>Notes / Instructions</label>
                  <textarea
                    rows={2}
                    value={poForm.notes}
                    onChange={(e) => setPoForm({ ...poForm, notes: e.target.value })}
                  />
                </div>

                {/* Line Items Section */}
                <div style={{ marginTop: '20px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                    <h4 style={{ margin: 0 }}>Order Line Items</h4>
                    <button type="button" onClick={addPoLine} className="btn-secondary" style={{ padding: '4px 10px' }}>
                      <Plus size={14} /> Add Line
                    </button>
                  </div>

                  <table className="erp-table" style={{ fontSize: '13px' }}>
                    <thead>
                      <tr>
                        <th style={{ width: '40%' }}>Product *</th>
                        <th style={{ width: '18%' }}>Quantity *</th>
                        <th style={{ width: '18%' }}>Unit Price ({poForm.currency}) *</th>
                        <th style={{ width: '14%' }}>Tax Rate %</th>
                        <th style={{ width: '10%' }}>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {poForm.items.map((item, idx) => (
                        <tr key={idx}>
                          <td>
                            <select
                              required
                              value={item.product_id}
                              onChange={(e) => handlePoLineChange(idx, 'product_id', e.target.value)}
                              style={{ width: '100%', padding: '6px' }}
                            >
                              <option value="">Select Product...</option>
                              {productsList.map((p) => (
                                <option key={p.id} value={p.id}>
                                  {p.sku} — {p.name} ({p.uom})
                                </option>
                              ))}
                            </select>
                          </td>
                          <td>
                            <input
                              type="number"
                              step="any"
                              min="0.01"
                              required
                              value={item.ordered_qty}
                              onChange={(e) => handlePoLineChange(idx, 'ordered_qty', e.target.value)}
                              style={{ width: '100%', padding: '6px' }}
                            />
                          </td>
                          <td>
                            <input
                              type="number"
                              step="any"
                              min="0"
                              required
                              value={item.unit_price}
                              onChange={(e) => handlePoLineChange(idx, 'unit_price', e.target.value)}
                              style={{ width: '100%', padding: '6px' }}
                            />
                          </td>
                          <td>
                            <input
                              type="number"
                              step="any"
                              min="0"
                              max="100"
                              value={item.tax_rate_pct}
                              onChange={(e) => handlePoLineChange(idx, 'tax_rate_pct', e.target.value)}
                              style={{ width: '100%', padding: '6px' }}
                            />
                          </td>
                          <td>
                            {poForm.items.length > 1 && (
                              <button
                                type="button"
                                onClick={() => removePoLine(idx)}
                                className="btn-action-icon btn-action-danger"
                              >
                                <X size={14} />
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>

                  {/* Summary Box */}
                  <div
                    style={{
                      background: 'var(--bg-card-secondary, #1e293b)',
                      padding: '12px 16px',
                      borderRadius: '6px',
                      marginTop: '12px',
                      display: 'flex',
                      justifyContent: 'flex-end',
                      gap: '24px',
                    }}
                  >
                    <div>
                      <span className="cell-subtext">Subtotal:</span>{' '}
                      <strong>
                        {poForm.currency} {poComputedTotals.subtotal.toLocaleString()}
                      </strong>
                    </div>
                    <div>
                      <span className="cell-subtext">Tax:</span>{' '}
                      <strong>
                        {poForm.currency} {poComputedTotals.taxTotal.toLocaleString()}
                      </strong>
                    </div>
                    <div>
                      <span className="cell-subtext">Grand Total:</span>{' '}
                      <strong style={{ color: '#10b981', fontSize: '15px' }}>
                        {poForm.currency} {poComputedTotals.grandTotal.toLocaleString()}
                      </strong>
                    </div>
                  </div>
                </div>
              </div>

              <div className="erp-modal-footer">
                <button type="button" onClick={() => setIsPoModalOpen(false)} className="btn-secondary">
                  Cancel
                </button>
                <button type="submit" disabled={poFormLoading} className="btn-primary">
                  {poFormLoading ? 'Creating...' : 'Create Purchase Order'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL: VIEW PO DETAILS */}
      {/* ========================================================================= */}
      {selectedPoForView && (
        <div className="erp-modal-overlay">
          <div className="erp-modal" style={{ maxWidth: '800px' }}>
            <div className="erp-modal-header">
              <h2>Purchase Order: {selectedPoForView.po_number}</h2>
              <button onClick={() => setSelectedPoForView(null)} className="btn-close">
                <X size={18} />
              </button>
            </div>

            <div className="erp-modal-body">
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(4, 1fr)',
                  gap: '12px',
                  marginBottom: '16px',
                  background: 'var(--bg-card-secondary, #1e293b)',
                  padding: '12px',
                  borderRadius: '6px',
                }}
              >
                <div>
                  <span className="cell-subtext">Supplier</span>
                  <div>
                    <strong>{selectedPoForView.supplier_name}</strong>
                  </div>
                </div>
                <div>
                  <span className="cell-subtext">Order Date</span>
                  <div>{selectedPoForView.order_date}</div>
                </div>
                <div>
                  <span className="cell-subtext">Grand Total</span>
                  <div>
                    <strong>
                      {selectedPoForView.currency} {selectedPoForView.grand_total.toLocaleString()}
                    </strong>
                  </div>
                </div>
                <div>
                  <span className="cell-subtext">Status</span>
                  <div>
                    <span className={`status-pill status-${selectedPoForView.status}`}>
                      {selectedPoForView.status}
                    </span>
                  </div>
                </div>
              </div>

              <h4 style={{ margin: '16px 0 8px 0' }}>Line Items & Receiving Status</h4>
              <table className="erp-table" style={{ fontSize: '13px' }}>
                <thead>
                  <tr>
                    <th>SKU / Product</th>
                    <th>Ordered Qty</th>
                    <th>Received Qty</th>
                    <th>Unit Price</th>
                    <th>Line Total</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedPoForView.items.map((itm) => (
                    <tr key={itm.id}>
                      <td>
                        <strong>{itm.sku}</strong> — {itm.product_name}
                      </td>
                      <td>
                        {itm.ordered_qty} {itm.uom}
                      </td>
                      <td>
                        <strong style={{ color: itm.received_qty >= itm.ordered_qty ? '#10b981' : '#f59e0b' }}>
                          {itm.received_qty} {itm.uom}
                        </strong>
                      </td>
                      <td>
                        {selectedPoForView.currency} {itm.unit_price.toLocaleString()}
                      </td>
                      <td>
                        <strong>
                          {selectedPoForView.currency} {itm.line_total.toLocaleString()}
                        </strong>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="erp-modal-footer">
              <button onClick={() => setSelectedPoForView(null)} className="btn-secondary">
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL: NEW GOODS RECEIPT */}
      {/* ========================================================================= */}
      {isGrModalOpen && selectedPoForGr && (
        <div className="erp-modal-overlay">
          <div className="erp-modal" style={{ maxWidth: '900px' }}>
            <div className="erp-modal-header">
              <h2>Goods Receipt for PO: {selectedPoForGr.po_number}</h2>
              <button onClick={() => setIsGrModalOpen(false)} className="btn-close">
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleSaveGr}>
              <div className="erp-modal-body">
                {grFormError && (
                  <div className="erp-error-banner">
                    <AlertTriangle size={16} /> {grFormError}
                  </div>
                )}

                <div className="form-grid">
                  <div className="form-group">
                    <label>Receipt Number *</label>
                    <input
                      type="text"
                      required
                      value={grForm.receipt_number}
                      onChange={(e) => setGrForm({ ...grForm, receipt_number: e.target.value })}
                    />
                  </div>

                  <div className="form-group">
                    <label>Receipt Date *</label>
                    <input
                      type="date"
                      required
                      value={grForm.receipt_date}
                      onChange={(e) => setGrForm({ ...grForm, receipt_date: e.target.value })}
                    />
                  </div>

                  <div className="form-group">
                    <label>Idempotency Key (Audit Reference)</label>
                    <input type="text" readOnly disabled value={grForm.idempotency_key} />
                  </div>
                </div>

                <div style={{ marginTop: '16px' }}>
                  <h4>Receiving & Quality Inspection Split</h4>
                  <p className="cell-subtext">
                    Specify accepted quantity for available stock, quarantined quantity for QA holding, and rejected
                    quantity with reasons.
                  </p>

                  <table className="erp-table" style={{ fontSize: '12px' }}>
                    <thead>
                      <tr>
                        <th>Product</th>
                        <th>Remaining</th>
                        <th>Received *</th>
                        <th>Accepted (Stock)</th>
                        <th>Quarantined</th>
                        <th>Rejected</th>
                        <th>Rejection Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {grForm.items.map((item, idx) => (
                        <tr key={idx}>
                          <td>
                            <strong>{item.sku}</strong>
                            <div className="cell-subtext">{item.product_name}</div>
                          </td>
                          <td>
                            <strong>
                              {item.remaining_qty} {item.uom}
                            </strong>
                          </td>
                          <td>
                            <input
                              type="number"
                              step="any"
                              min="0"
                              max={item.remaining_qty}
                              required
                              value={item.received_qty}
                              onChange={(e) => handleGrLineChange(idx, 'received_qty', e.target.value)}
                              style={{ width: '80px', padding: '4px' }}
                            />
                          </td>
                          <td>
                            <input
                              type="number"
                              step="any"
                              min="0"
                              value={item.accepted_qty}
                              onChange={(e) => handleGrLineChange(idx, 'accepted_qty', e.target.value)}
                              style={{ width: '80px', padding: '4px' }}
                            />
                          </td>
                          <td>
                            <input
                              type="number"
                              step="any"
                              min="0"
                              value={item.quarantined_qty}
                              onChange={(e) => handleGrLineChange(idx, 'quarantined_qty', e.target.value)}
                              style={{ width: '80px', padding: '4px' }}
                            />
                          </td>
                          <td>
                            <input
                              type="number"
                              step="any"
                              min="0"
                              value={item.rejected_qty}
                              onChange={(e) => handleGrLineChange(idx, 'rejected_qty', e.target.value)}
                              style={{ width: '80px', padding: '4px' }}
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              placeholder="Reason if rejected..."
                              value={item.rejection_reason}
                              onChange={(e) => handleGrLineChange(idx, 'rejection_reason', e.target.value)}
                              style={{ width: '100%', padding: '4px' }}
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="erp-modal-footer">
                <button type="button" onClick={() => setIsGrModalOpen(false)} className="btn-secondary">
                  Cancel
                </button>
                <button type="submit" disabled={grFormLoading} className="btn-primary">
                  {grFormLoading ? 'Recording...' : 'Record Goods Receipt'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL: CONFIRM ACTION (POST / CANCEL) */}
      {/* ========================================================================= */}
      {confirmActionModal && (
        <div className="erp-modal-overlay">
          <div className="erp-modal" style={{ maxWidth: '450px' }}>
            <div className="erp-modal-header">
              <h2>Confirm Action</h2>
              <button onClick={() => setConfirmActionModal(null)} className="btn-close">
                <X size={18} />
              </button>
            </div>
            <div className="erp-modal-body">
              {confirmActionModal.action === 'post' && (
                <div>
                  <p>
                    Are you sure you want to post Goods Receipt{' '}
                    <strong>{confirmActionModal.gr.receipt_number}</strong> to the Inventory Stock Ledger?
                  </p>
                  <p className="cell-subtext" style={{ color: '#f59e0b' }}>
                    Warning: Inventory ledger movements are append-only and strictly immutable. Once posted, stock will
                    be updated immediately.
                  </p>
                </div>
              )}

              {confirmActionModal.action === 'cancel' && (
                <div>
                  <p>
                    Are you sure you want to cancel Purchase Order{' '}
                    <strong>{confirmActionModal.po.po_number}</strong>?
                  </p>
                  <p className="cell-subtext">
                    This action will mark the purchase order as cancelled. Orders with recorded goods receipts cannot be
                    cancelled.
                  </p>
                </div>
              )}
            </div>

            <div className="erp-modal-footer">
              <button onClick={() => setConfirmActionModal(null)} className="btn-secondary">
                No, Back
              </button>
              {confirmActionModal.action === 'post' && (
                <button onClick={() => handlePostGr(confirmActionModal.gr.id)} className="btn-primary">
                  Confirm & Post to Stock
                </button>
              )}
              {confirmActionModal.action === 'cancel' && (
                <button
                  onClick={() => handlePoAction(confirmActionModal.po.id, 'cancel')}
                  className="btn-danger"
                >
                  Confirm Cancellation
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
