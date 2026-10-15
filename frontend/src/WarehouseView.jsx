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
  Warehouse as WarehouseIcon,
  X,
  XCircle,
} from 'lucide-react'
import { apiFetch } from './api'

export default function WarehouseView({ initialTab = 'balances' }) {
  const [activeTab, setActiveTab] = useState(initialTab) // 'balances' | 'warehouses' | 'transfers' | 'adjustments' | 'reservations' | 'reconciliation'
  const [currentRole, setCurrentRole] = useState('admin') // 'admin' | 'warehouse' | 'procurement' | 'sales' | 'viewer'
  const [operatorName, setOperatorName] = useState('Local Operator')

  const authHeaders = useMemo(
    () => ({
      'X-User-Role': currentRole,
      'X-User-Name': operatorName,
    }),
    [currentRole, operatorName]
  )

  // Master Data caches
  const [productsList, setProductsList] = useState([])
  const [warehousesList, setWarehousesList] = useState([])
  const [locationsList, setLocationsList] = useState([])

  // Balances & ATP State
  const [balances, setBalances] = useState([])
  const [balancesLoading, setBalancesLoading] = useState(false)
  const [balanceSearch, setBalanceSearch] = useState('')
  const [lowStockFilter, setLowStockFilter] = useState(false)

  // Warehouses & Locations State
  const [warehouses, setWarehouses] = useState([])
  const [warehousesLoading, setWarehousesLoading] = useState(false)
  const [isWhModalOpen, setIsWhModalOpen] = useState(false)
  const [isLocModalOpen, setIsLocModalOpen] = useState(false)
  const [selectedWhForLoc, setSelectedWhForLoc] = useState(null)
  const [whFormError, setWhFormError] = useState(null)
  const [locFormError, setLocFormError] = useState(null)

  // Transfers State
  const [transfers, setTransfers] = useState([])
  const [transfersLoading, setTransfersLoading] = useState(false)
  const [transferStatusFilter, setTransferStatusFilter] = useState('all')
  const [isTransferModalOpen, setIsTransferModalOpen] = useState(false)
  const [isReceiveModalOpen, setIsReceiveModalOpen] = useState(false)
  const [selectedTransferForReceive, setSelectedTransferForReceive] = useState(null)
  const [transferFormError, setTransferFormError] = useState(null)
  const [receiveFormError, setReceiveFormError] = useState(null)

  // Adjustments State
  const [adjustments, setAdjustments] = useState([])
  const [adjustmentsLoading, setAdjustmentsLoading] = useState(false)
  const [isAdjModalOpen, setIsAdjModalOpen] = useState(false)
  const [adjFormError, setAdjFormError] = useState(null)

  // Reservations State
  const [reservations, setReservations] = useState([])
  const [reservationsLoading, setReservationsLoading] = useState(false)
  const [isResModalOpen, setIsResModalOpen] = useState(false)
  const [resFormError, setResFormError] = useState(null)

  // Reconciliation State
  const [reconciliation, setReconciliation] = useState(null)
  const [reconciliationLoading, setReconciliationLoading] = useState(false)

  // Form payloads
  const [newWh, setNewWh] = useState({ code: '', name: '', address: '', city: '', country: 'IN' })
  const [newLoc, setNewLoc] = useState({ warehouse_id: '', location_code: '', zone: '', rack: '', shelf: '', bin: '' })
  const [newTransfer, setNewTransfer] = useState({
    source_warehouse_id: '',
    source_location_id: '',
    dest_warehouse_id: '',
    dest_location_id: '',
    notes: '',
    items: [{ product_id: '', requested_quantity: 1 }],
  })
  const [receivePayload, setReceivePayload] = useState({ items: [], notes: '' })
  const [newAdj, setNewAdj] = useState({
    product_id: '',
    warehouse_id: '',
    stock_type: 'available',
    system_quantity: 0,
    counted_quantity: 0,
    reason_code: 'PHYSICAL_COUNT',
    notes: '',
  })
  const [newRes, setNewRes] = useState({
    product_id: '',
    warehouse_id: '',
    quantity: 1,
    reference_type: 'sales_order',
    reference_id: '',
    notes: '',
  })

  // Permission helpers
  const canManageWarehouses = ['admin', 'warehouse'].includes(currentRole)
  const canManageTransfers = ['admin', 'warehouse', 'procurement'].includes(currentRole)
  const canDispatchReceive = ['admin', 'warehouse'].includes(currentRole)
  const canCreateAdjustments = ['admin', 'warehouse'].includes(currentRole)
  const canApproveAdjustments = ['admin', 'warehouse'].includes(currentRole)
  const canManageReservations = ['admin', 'sales', 'procurement'].includes(currentRole)
  const canConsumeReservations = ['admin', 'warehouse'].includes(currentRole)

  // Fetch initial master data
  useEffect(() => {
    fetchProducts()
    fetchWarehouses()
    fetchLocations()
  }, [])

  useEffect(() => {
    if (activeTab === 'balances') fetchBalances()
    if (activeTab === 'warehouses') {
      fetchWarehouses()
      fetchLocations()
    }
    if (activeTab === 'transfers') fetchTransfers()
    if (activeTab === 'adjustments') fetchAdjustments()
    if (activeTab === 'reservations') fetchReservations()
    if (activeTab === 'reconciliation') fetchReconciliation()
  }, [activeTab, lowStockFilter, transferStatusFilter])

  async function fetchProducts() {
    try {
      const res = await apiFetch('/api/products?limit=100', { headers: authHeaders }, 'Failed to fetch products')
      setProductsList(res.items || [])
    } catch (e) {
      console.error(e)
    }
  }

  async function fetchWarehouses() {
    setWarehousesLoading(true)
    try {
      const res = await apiFetch('/api/warehouses', { headers: authHeaders }, 'Failed to fetch warehouses')
      setWarehouses(res.items || [])
      setWarehousesList(res.items || [])
    } catch (e) {
      console.error(e)
    } finally {
      setWarehousesLoading(false)
    }
  }

  async function fetchLocations() {
    try {
      const res = await apiFetch('/api/warehouse-locations', { headers: authHeaders }, 'Failed to fetch locations')
      setLocationsList(res.items || [])
    } catch (e) {
      console.error(e)
    }
  }

  async function fetchBalances() {
    setBalancesLoading(true)
    try {
      const query = lowStockFilter ? '?is_low_stock=true' : ''
      const res = await apiFetch(`/api/inventory/reports/balances${query}`, { headers: authHeaders }, 'Failed to fetch balances')
      setBalances(res.items || [])
    } catch (e) {
      console.error(e)
    } finally {
      setBalancesLoading(false)
    }
  }

  async function fetchTransfers() {
    setTransfersLoading(true)
    try {
      const query = transferStatusFilter !== 'all' ? `?status=${transferStatusFilter}` : ''
      const res = await apiFetch(`/api/inventory/transfers${query}`, { headers: authHeaders }, 'Failed to fetch transfers')
      setTransfers(res.items || [])
    } catch (e) {
      console.error(e)
    } finally {
      setTransfersLoading(false)
    }
  }

  async function fetchAdjustments() {
    setAdjustmentsLoading(true)
    try {
      const res = await apiFetch('/api/inventory/adjustments', { headers: authHeaders }, 'Failed to fetch adjustments')
      setAdjustments(res.items || [])
    } catch (e) {
      console.error(e)
    } finally {
      setAdjustmentsLoading(false)
    }
  }

  async function fetchReservations() {
    setReservationsLoading(true)
    try {
      const res = await apiFetch('/api/inventory/reservations', { headers: authHeaders }, 'Failed to fetch reservations')
      setReservations(res.items || [])
    } catch (e) {
      console.error(e)
    } finally {
      setReservationsLoading(false)
    }
  }

  async function fetchReconciliation() {
    setReconciliationLoading(true)
    try {
      const res = await apiFetch('/api/inventory/reports/reconciliation', { headers: authHeaders }, 'Failed to fetch reconciliation')
      setReconciliation(res)
    } catch (e) {
      console.error(e)
    } finally {
      setReconciliationLoading(false)
    }
  }

  // --- Actions ---

  async function handleCreateWarehouse(e) {
    e.preventDefault()
    setWhFormError(null)
    try {
      await apiFetch(
        '/api/warehouses',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...authHeaders },
          body: JSON.stringify(newWh),
        },
        'Failed to create warehouse'
      )
      setIsWhModalOpen(false)
      setNewWh({ code: '', name: '', address: '', city: '', country: 'IN' })
      fetchWarehouses()
    } catch (err) {
      setWhFormError(err.message)
    }
  }

  async function handleCreateLocation(e) {
    e.preventDefault()
    setLocFormError(null)
    try {
      await apiFetch(
        '/api/warehouse-locations',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...authHeaders },
          body: JSON.stringify(newLoc),
        },
        'Failed to create storage location'
      )
      setIsLocModalOpen(false)
      setNewLoc({ warehouse_id: '', location_code: '', zone: '', rack: '', shelf: '', bin: '' })
      fetchLocations()
    } catch (err) {
      setLocFormError(err.message)
    }
  }

  async function handleDeactivateWarehouse(wh) {
    if (!window.confirm(`Are you sure you want to ${wh.is_active ? 'deactivate' : 'activate'} warehouse ${wh.code}?`)) return
    try {
      await apiFetch(
        `/api/warehouses/${wh.id}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', ...authHeaders },
          body: JSON.stringify({ is_active: !wh.is_active }),
        },
        'Failed to update warehouse status'
      )
      fetchWarehouses()
    } catch (err) {
      alert(`Deactivation Blocked: ${err.message}`)
    }
  }

  async function handleCreateTransfer(e) {
    e.preventDefault()
    setTransferFormError(null)
    try {
      await apiFetch(
        '/api/inventory/transfers',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...authHeaders },
          body: JSON.stringify(newTransfer),
        },
        'Failed to create stock transfer'
      )
      setIsTransferModalOpen(false)
      fetchTransfers()
    } catch (err) {
      setTransferFormError(err.message)
    }
  }

  async function handleApproveTransfer(transferId) {
    try {
      await apiFetch(`/api/inventory/transfers/${transferId}/approve`, { method: 'POST', headers: authHeaders }, 'Failed to approve transfer')
      fetchTransfers()
    } catch (err) {
      alert(err.message)
    }
  }

  async function handleDispatchTransfer(transferId) {
    if (!window.confirm('Dispatch transfer? This will deduct available stock and record in-transit stock.')) return
    try {
      await apiFetch(`/api/inventory/transfers/${transferId}/dispatch`, { method: 'POST', headers: authHeaders }, 'Failed to dispatch transfer')
      fetchTransfers()
    } catch (err) {
      alert(`Dispatch Error: ${err.message}`)
    }
  }

  function openReceiveModal(trf) {
    setSelectedTransferForReceive(trf)
    setReceivePayload({
      items: trf.items.map((i) => ({
        item_id: i.id,
        received_quantity: i.dispatched_quantity,
        damaged_quantity: 0,
        discrepancy_reason: '',
      })),
      notes: '',
    })
    setIsReceiveModalOpen(true)
  }

  async function handleReceiveTransfer(e) {
    e.preventDefault()
    setReceiveFormError(null)
    try {
      await apiFetch(
        `/api/inventory/transfers/${selectedTransferForReceive.id}/receive`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...authHeaders },
          body: JSON.stringify(receivePayload),
        },
        'Failed to receive transfer'
      )
      setIsReceiveModalOpen(false)
      fetchTransfers()
      fetchBalances()
    } catch (err) {
      setReceiveFormError(err.message)
    }
  }

  async function handleCreateAdjustment(e) {
    e.preventDefault()
    setAdjFormError(null)
    try {
      await apiFetch(
        '/api/inventory/adjustments',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...authHeaders },
          body: JSON.stringify(newAdj),
        },
        'Failed to record physical count adjustment'
      )
      setIsAdjModalOpen(false)
      fetchAdjustments()
    } catch (err) {
      setAdjFormError(err.message)
    }
  }

  async function handleApproveAdjustment(adjId) {
    if (!window.confirm('Approve adjustment and post compensating movement to stock ledger?')) return
    try {
      await apiFetch(`/api/inventory/adjustments/${adjId}/approve`, { method: 'POST', headers: authHeaders }, 'Failed to approve adjustment')
      fetchAdjustments()
      fetchBalances()
    } catch (err) {
      alert(`Approval Error: ${err.message}`)
    }
  }

  async function handleCreateReservation(e) {
    e.preventDefault()
    setResFormError(null)
    try {
      await apiFetch(
        '/api/inventory/reservations',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...authHeaders },
          body: JSON.stringify(newRes),
        },
        'Failed to create stock reservation'
      )
      setIsResModalOpen(false)
      fetchReservations()
      fetchBalances()
    } catch (err) {
      setResFormError(err.message)
    }
  }

  async function handleReleaseReservation(resId) {
    try {
      await apiFetch(`/api/inventory/reservations/${resId}/release`, { method: 'POST', headers: authHeaders }, 'Failed to release reservation')
      fetchReservations()
      fetchBalances()
    } catch (err) {
      alert(err.message)
    }
  }

  async function handleConsumeReservation(resId) {
    if (!window.confirm('Consume reservation? This will deduct the physical stock from inventory.')) return
    try {
      await apiFetch(`/api/inventory/reservations/${resId}/consume`, { method: 'POST', headers: authHeaders }, 'Failed to consume reservation')
      fetchReservations()
      fetchBalances()
    } catch (err) {
      alert(`Consumption Error: ${err.message}`)
    }
  }

  // Filter balances
  const filteredBalances = useMemo(() => {
    return balances.filter((b) => {
      const matchSearch =
        b.sku.toLowerCase().includes(balanceSearch.toLowerCase()) ||
        b.product_name.toLowerCase().includes(balanceSearch.toLowerCase())
      return matchSearch
    })
  }, [balances, balanceSearch])

  return (
    <div className="erp-master-container">
      {/* Top Header & Role Switcher */}
      <div className="erp-header-row">
        <div>
          <div className="eyebrow">EXPORTMATE ERP — PHASE 3</div>
          <h1 className="erp-title">Warehouse & Inventory Management</h1>
          <p className="erp-subtitle">
            Storage Locations, Inter-Hub Transfers, Physical Adjustments, and Available-to-Promise (ATP).
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
            <option value="admin">Admin (Full Access)</option>
            <option value="warehouse">Warehouse (Operations & Logistics)</option>
            <option value="procurement">Procurement (POs & Reservations)</option>
            <option value="sales">Sales (Reservations & CRM)</option>
            <option value="viewer">Viewer (Read-Only)</option>
          </select>
          <span className="rbac-hint">Server-enforced RBAC</span>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div className="erp-tabs-row">
        <button
          className={`erp-tab-btn ${activeTab === 'balances' ? 'active' : ''}`}
          onClick={() => setActiveTab('balances')}
        >
          <Boxes size={16} />
          <span>Stock Balances &amp; ATP</span>
        </button>
        <button
          className={`erp-tab-btn ${activeTab === 'warehouses' ? 'active' : ''}`}
          onClick={() => setActiveTab('warehouses')}
        >
          <WarehouseIcon size={16} />
          <span>Warehouses &amp; Locations</span>
        </button>
        <button
          className={`erp-tab-btn ${activeTab === 'transfers' ? 'active' : ''}`}
          onClick={() => setActiveTab('transfers')}
        >
          <Truck size={16} />
          <span>Stock Transfers</span>
        </button>
        <button
          className={`erp-tab-btn ${activeTab === 'adjustments' ? 'active' : ''}`}
          onClick={() => setActiveTab('adjustments')}
        >
          <FileCheck size={16} />
          <span>Stock Counts &amp; Adjustments</span>
        </button>
        <button
          className={`erp-tab-btn ${activeTab === 'reservations' ? 'active' : ''}`}
          onClick={() => setActiveTab('reservations')}
        >
          <Lock size={16} />
          <span>Reservations</span>
        </button>
        <button
          className={`erp-tab-btn ${activeTab === 'reconciliation' ? 'active' : ''}`}
          onClick={() => setActiveTab('reconciliation')}
        >
          <CheckCircle2 size={16} />
          <span>Ledger Reconciliation</span>
        </button>
      </div>

      {/* TAB 1: STOCK BALANCES & ATP */}
      {activeTab === 'balances' && (
        <div className="erp-content-section">
          <div className="erp-table-toolbar">
            <div className="erp-search-box">
              <Search size={16} />
              <input
                type="text"
                placeholder="Search SKU, Product Name..."
                value={balanceSearch}
                onChange={(e) => setBalanceSearch(e.target.value)}
              />
            </div>
            <div className="erp-filter-row">
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={lowStockFilter}
                  onChange={(e) => setLowStockFilter(e.target.checked)}
                />
                <span>Low Stock Only</span>
              </label>
              <button className="erp-btn secondary" onClick={fetchBalances}>
                <RefreshCw size={14} /> Refresh
              </button>
            </div>
          </div>

          <div className="erp-table-card">
            <table className="erp-data-table">
              <thead>
                <tr>
                  <th>SKU / Product</th>
                  <th>UOM</th>
                  <th>On-Hand Total</th>
                  <th>Available</th>
                  <th>Reserved</th>
                  <th>Available to Promise (ATP)</th>
                  <th>In-Transit</th>
                  <th>Quarantined</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {balancesLoading ? (
                  <tr>
                    <td colSpan={9} className="erp-empty-state">Loading stock balances...</td>
                  </tr>
                ) : filteredBalances.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="erp-empty-state">No stock balances found.</td>
                  </tr>
                ) : (
                  filteredBalances.map((b) => (
                    <tr key={b.product_id}>
                      <td>
                        <strong>{b.sku}</strong>
                        <div className="erp-subtext">{b.product_name}</div>
                      </td>
                      <td>{b.uom}</td>
                      <td><strong>{b.on_hand_qty}</strong></td>
                      <td><span className="text-success">{b.available_qty}</span></td>
                      <td>{b.reserved_qty > 0 ? <span className="text-warning">{b.reserved_qty}</span> : '0'}</td>
                      <td>
                        <strong className={b.available_to_promise <= 10 ? 'text-danger' : 'text-primary'}>
                          {b.available_to_promise}
                        </strong>
                      </td>
                      <td>{b.in_transit_qty > 0 ? <span className="text-accent">{b.in_transit_qty}</span> : '0'}</td>
                      <td>{b.quarantined_qty > 0 ? <span className="text-warning">{b.quarantined_qty}</span> : '0'}</td>
                      <td>
                        {b.is_low_stock ? (
                          <span className="erp-badge danger">Low Stock</span>
                        ) : (
                          <span className="erp-badge success">Optimal</span>
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

      {/* TAB 2: WAREHOUSES & LOCATIONS */}
      {activeTab === 'warehouses' && (
        <div className="erp-content-section">
          <div className="erp-table-toolbar">
            <div className="toolbar-left">
              <h2>Hubs &amp; Storage Locations</h2>
            </div>
            <div className="toolbar-right">
              {canManageWarehouses && (
                <>
                  <button className="erp-btn primary" onClick={() => setIsWhModalOpen(true)}>
                    <Plus size={16} /> New Warehouse
                  </button>
                  <button className="erp-btn secondary" onClick={() => setIsLocModalOpen(true)}>
                    <Plus size={16} /> New Location
                  </button>
                </>
              )}
            </div>
          </div>

          <div className="warehouses-grid">
            {warehouses.map((wh) => {
              const whLocs = locationsList.filter((l) => l.warehouse_id === wh.id)
              return (
                <div key={wh.id} className={`warehouse-card ${!wh.is_active ? 'inactive' : ''}`}>
                  <div className="wh-card-head">
                    <div>
                      <span className="wh-code">{wh.code}</span>
                      <h3 className="wh-name">{wh.name}</h3>
                      <div className="wh-meta">{wh.city ? `${wh.city}, ` : ''}{wh.country}</div>
                    </div>
                    <div>
                      <span className={`erp-badge ${wh.is_active ? 'success' : 'neutral'}`}>
                        {wh.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </div>
                  </div>

                  <div className="wh-locations-box">
                    <div className="wh-loc-header">
                      <span>STORAGE LOCATIONS ({whLocs.length})</span>
                    </div>
                    {whLocs.length === 0 ? (
                      <div className="wh-empty-loc">No specific storage bins configured.</div>
                    ) : (
                      <div className="loc-tags-grid">
                        {whLocs.map((loc) => (
                          <span key={loc.id} className="loc-tag">
                            <strong>{loc.location_code}</strong>
                            {loc.zone && <small> ({loc.zone})</small>}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="wh-card-foot">
                    {canManageWarehouses && (
                      <button
                        className="erp-btn text-btn"
                        onClick={() => handleDeactivateWarehouse(wh)}
                      >
                        {wh.is_active ? 'Deactivate Warehouse' : 'Reactivate'}
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* TAB 3: STOCK TRANSFERS */}
      {activeTab === 'transfers' && (
        <div className="erp-content-section">
          <div className="erp-table-toolbar">
            <div className="erp-filter-row">
              <span className="filter-label">Status:</span>
              <select
                value={transferStatusFilter}
                onChange={(e) => setTransferStatusFilter(e.target.value)}
                className="erp-select"
              >
                <option value="all">All Transfers</option>
                <option value="draft">Draft</option>
                <option value="approved">Approved</option>
                <option value="dispatched">In-Transit (Dispatched)</option>
                <option value="received">Received</option>
                <option value="discrepancy">Discrepancy / Shortage</option>
                <option value="cancelled">Cancelled</option>
              </select>
            </div>
            <div>
              {canManageTransfers && (
                <button className="erp-btn primary" onClick={() => setIsTransferModalOpen(true)}>
                  <Plus size={16} /> New Stock Transfer
                </button>
              )}
            </div>
          </div>

          <div className="erp-table-card">
            <table className="erp-data-table">
              <thead>
                <tr>
                  <th>Transfer #</th>
                  <th>Source Hub</th>
                  <th>Destination Hub</th>
                  <th>Items</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {transfersLoading ? (
                  <tr>
                    <td colSpan={7} className="erp-empty-state">Loading transfers...</td>
                  </tr>
                ) : transfers.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="erp-empty-state">No stock transfers found.</td>
                  </tr>
                ) : (
                  transfers.map((t) => (
                    <tr key={t.id}>
                      <td><strong>{t.transfer_number}</strong></td>
                      <td>{t.source_warehouse_code}</td>
                      <td>{t.dest_warehouse_code}</td>
                      <td>
                        {t.items.map((i) => (
                          <div key={i.id} className="transfer-item-line">
                            {i.sku}: Req {i.requested_quantity}
                            {i.dispatched_quantity > 0 && ` | Disp ${i.dispatched_quantity}`}
                            {i.received_quantity > 0 && ` | Recv ${i.received_quantity}`}
                            {i.damaged_quantity > 0 && <span className="text-warning"> (Dmg: {i.damaged_quantity})</span>}
                            {i.shortage_quantity > 0 && <span className="text-danger"> (Short: {i.shortage_quantity})</span>}
                          </div>
                        ))}
                      </td>
                      <td>
                        <span className={`erp-badge ${
                          t.status === 'received' ? 'success' :
                          t.status === 'dispatched' ? 'accent' :
                          t.status === 'discrepancy' ? 'warning' :
                          t.status === 'approved' ? 'primary' : 'neutral'
                        }`}>
                          {t.status.toUpperCase()}
                        </span>
                      </td>
                      <td>{t.created_at.slice(0, 10)}</td>
                      <td>
                        <div className="table-actions">
                          {t.status === 'draft' && canManageTransfers && (
                            <button
                              className="erp-btn table-action-btn"
                              onClick={() => handleApproveTransfer(t.id)}
                            >
                              Approve
                            </button>
                          )}
                          {t.status === 'approved' && canDispatchReceive && (
                            <button
                              className="erp-btn table-action-btn primary"
                              onClick={() => handleDispatchTransfer(t.id)}
                            >
                              Dispatch
                            </button>
                          )}
                          {t.status === 'dispatched' && canDispatchReceive && (
                            <button
                              className="erp-btn table-action-btn success"
                              onClick={() => openReceiveModal(t)}
                            >
                              Receive
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

      {/* TAB 4: ADJUSTMENTS & PHYSICAL COUNTS */}
      {activeTab === 'adjustments' && (
        <div className="erp-content-section">
          <div className="erp-table-toolbar">
            <h2>Inventory Adjustments &amp; Cycle Counts</h2>
            {canCreateAdjustments && (
              <button className="erp-btn primary" onClick={() => setIsAdjModalOpen(true)}>
                <Plus size={16} /> New Physical Count / Adjustment
              </button>
            )}
          </div>

          <div className="erp-table-card">
            <table className="erp-data-table">
              <thead>
                <tr>
                  <th>Adjustment #</th>
                  <th>Product</th>
                  <th>Warehouse</th>
                  <th>Stock Type</th>
                  <th>System Qty</th>
                  <th>Counted Qty</th>
                  <th>Variance</th>
                  <th>Reason</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {adjustmentsLoading ? (
                  <tr>
                    <td colSpan={10} className="erp-empty-state">Loading adjustments...</td>
                  </tr>
                ) : adjustments.length === 0 ? (
                  <tr>
                    <td colSpan={10} className="erp-empty-state">No adjustments found.</td>
                  </tr>
                ) : (
                  adjustments.map((a) => (
                    <tr key={a.id}>
                      <td><strong>{a.adjustment_number}</strong></td>
                      <td>{a.sku}</td>
                      <td>{a.warehouse_code}</td>
                      <td>{a.stock_type}</td>
                      <td>{a.system_quantity}</td>
                      <td>{a.counted_quantity}</td>
                      <td>
                        <strong className={a.difference_quantity < 0 ? 'text-danger' : 'text-success'}>
                          {a.difference_quantity > 0 ? `+${a.difference_quantity}` : a.difference_quantity}
                        </strong>
                      </td>
                      <td><span className="erp-badge neutral">{a.reason_code}</span></td>
                      <td>
                        <span className={`erp-badge ${a.status === 'approved' ? 'success' : 'warning'}`}>
                          {a.status.toUpperCase()}
                        </span>
                      </td>
                      <td>
                        {a.status === 'pending' && canApproveAdjustments && (
                          <button
                            className="erp-btn table-action-btn primary"
                            onClick={() => handleApproveAdjustment(a.id)}
                          >
                            Approve &amp; Post
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

      {/* TAB 5: RESERVATIONS */}
      {activeTab === 'reservations' && (
        <div className="erp-content-section">
          <div className="erp-table-toolbar">
            <h2>Stock Reservations (Available-To-Promise Allocation)</h2>
            {canManageReservations && (
              <button className="erp-btn primary" onClick={() => setIsResModalOpen(true)}>
                <Plus size={16} /> New Reservation
              </button>
            )}
          </div>

          <div className="erp-table-card">
            <table className="erp-data-table">
              <thead>
                <tr>
                  <th>Reservation #</th>
                  <th>SKU / Product</th>
                  <th>Warehouse</th>
                  <th>Quantity</th>
                  <th>Reference</th>
                  <th>Status</th>
                  <th>Reserved By</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {reservationsLoading ? (
                  <tr>
                    <td colSpan={8} className="erp-empty-state">Loading reservations...</td>
                  </tr>
                ) : reservations.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="erp-empty-state">No reservations found.</td>
                  </tr>
                ) : (
                  reservations.map((r) => (
                    <tr key={r.id}>
                      <td><strong>{r.reservation_number}</strong></td>
                      <td>{r.sku}</td>
                      <td>{r.warehouse_code}</td>
                      <td><strong>{r.quantity} {r.uom}</strong></td>
                      <td>{r.reference_type} {r.reference_id && `(${r.reference_id})`}</td>
                      <td>
                        <span className={`erp-badge ${
                          r.status === 'active' ? 'primary' :
                          r.status === 'consumed' ? 'success' : 'neutral'
                        }`}>
                          {r.status.toUpperCase()}
                        </span>
                      </td>
                      <td>{r.reserved_by}</td>
                      <td>
                        <div className="table-actions">
                          {r.status === 'active' && canManageReservations && (
                            <button
                              className="erp-btn table-action-btn"
                              onClick={() => handleReleaseReservation(r.id)}
                            >
                              Release
                            </button>
                          )}
                          {r.status === 'active' && canConsumeReservations && (
                            <button
                              className="erp-btn table-action-btn success"
                              onClick={() => handleConsumeReservation(r.id)}
                            >
                              Consume
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

      {/* TAB 6: RECONCILIATION */}
      {activeTab === 'reconciliation' && (
        <div className="erp-content-section">
          <div className="erp-table-toolbar">
            <h2>Stock Ledger vs Balance Sheet Audit</h2>
            <button className="erp-btn secondary" onClick={fetchReconciliation}>
              <RefreshCw size={14} /> Re-verify Integrity
            </button>
          </div>

          {reconciliationLoading ? (
            <div className="erp-empty-state">Verifying ledger mathematical consistency...</div>
          ) : !reconciliation ? (
            <div className="erp-empty-state">No reconciliation audit available.</div>
          ) : (
            <div>
              <div className={`reconciliation-banner ${reconciliation.is_fully_reconciled ? 'passed' : 'failed'}`}>
                {reconciliation.is_fully_reconciled ? (
                  <>
                    <CheckCircle2 size={24} className="text-success" />
                    <div>
                      <strong>All Ledger Movements Reconciled (100% Consistent)</strong>
                      <p>Authoritative append-only movement logs exactly match current stock on-hand balances with 0 discrepancy.</p>
                    </div>
                  </>
                ) : (
                  <>
                    <AlertTriangle size={24} className="text-danger" />
                    <div>
                      <strong>Discrepancies Detected ({reconciliation.discrepancies_found})</strong>
                      <p>Discrepancies found between movement logs and balance records. Review table below.</p>
                    </div>
                  </>
                )}
              </div>

              <div className="erp-table-card">
                <table className="erp-data-table">
                  <thead>
                    <tr>
                      <th>SKU</th>
                      <th>Stock Type</th>
                      <th>Balance On-Hand</th>
                      <th>Sum of Movements (Ledger)</th>
                      <th>Discrepancy</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reconciliation.items.map((itm, idx) => (
                      <tr key={idx}>
                        <td><strong>{itm.sku}</strong></td>
                        <td>{itm.stock_type}</td>
                        <td>{itm.balance_on_hand}</td>
                        <td>{itm.ledger_sum_qty}</td>
                        <td>
                          <span className={itm.discrepancy === 0 ? 'text-success' : 'text-danger'}>
                            {itm.discrepancy}
                          </span>
                        </td>
                        <td>
                          <span className={`erp-badge ${itm.is_reconciled ? 'success' : 'danger'}`}>
                            {itm.is_reconciled ? 'RECONCILED' : 'DISCREPANCY'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* MODAL: CREATE WAREHOUSE */}
      {isWhModalOpen && (
        <div className="erp-modal-overlay">
          <div className="erp-modal-card">
            <div className="erp-modal-header">
              <h3>Create Warehouse Hub</h3>
              <button className="erp-close-btn" onClick={() => setIsWhModalOpen(false)}><X size={18} /></button>
            </div>
            {whFormError && <div className="erp-form-error">{whFormError}</div>}
            <form onSubmit={handleCreateWarehouse}>
              <div className="erp-form-group">
                <label>Warehouse Code *</label>
                <input
                  type="text"
                  placeholder="WH-KOCHI-01"
                  required
                  value={newWh.code}
                  onChange={(e) => setNewWh({ ...newWh, code: e.target.value.toUpperCase() })}
                />
              </div>
              <div className="erp-form-group">
                <label>Warehouse Name *</label>
                <input
                  type="text"
                  placeholder="Kochi Coastal Terminal Hub"
                  required
                  value={newWh.name}
                  onChange={(e) => setNewWh({ ...newWh, name: e.target.value })}
                />
              </div>
              <div className="erp-form-group">
                <label>City &amp; Address</label>
                <input
                  type="text"
                  placeholder="Willingdon Island Port Area, Kochi"
                  value={newWh.address}
                  onChange={(e) => setNewWh({ ...newWh, address: e.target.value })}
                />
              </div>
              <div className="erp-modal-footer">
                <button type="button" className="erp-btn secondary" onClick={() => setIsWhModalOpen(false)}>Cancel</button>
                <button type="submit" className="erp-btn primary">Save Warehouse</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: CREATE LOCATION */}
      {isLocModalOpen && (
        <div className="erp-modal-overlay">
          <div className="erp-modal-card">
            <div className="erp-modal-header">
              <h3>Create Storage Location</h3>
              <button className="erp-close-btn" onClick={() => setIsLocModalOpen(false)}><X size={18} /></button>
            </div>
            {locFormError && <div className="erp-form-error">{locFormError}</div>}
            <form onSubmit={handleCreateLocation}>
              <div className="erp-form-group">
                <label>Parent Warehouse *</label>
                <select
                  required
                  value={newLoc.warehouse_id}
                  onChange={(e) => setNewLoc({ ...newLoc, warehouse_id: e.target.value })}
                >
                  <option value="">Select Warehouse...</option>
                  {warehousesList.map((w) => (
                    <option key={w.id} value={w.id}>{w.code} - {w.name}</option>
                  ))}
                </select>
              </div>
              <div className="erp-form-group">
                <label>Location Code *</label>
                <input
                  type="text"
                  placeholder="COLD-A-01"
                  required
                  value={newLoc.location_code}
                  onChange={(e) => setNewLoc({ ...newLoc, location_code: e.target.value.toUpperCase() })}
                />
              </div>
              <div className="erp-form-row">
                <div className="erp-form-group">
                  <label>Zone</label>
                  <input
                    type="text"
                    placeholder="Cold Storage"
                    value={newLoc.zone}
                    onChange={(e) => setNewLoc({ ...newLoc, zone: e.target.value })}
                  />
                </div>
                <div className="erp-form-group">
                  <label>Rack / Shelf</label>
                  <input
                    type="text"
                    placeholder="R1-S2"
                    value={newLoc.rack}
                    onChange={(e) => setNewLoc({ ...newLoc, rack: e.target.value })}
                  />
                </div>
              </div>
              <div className="erp-modal-footer">
                <button type="button" className="erp-btn secondary" onClick={() => setIsLocModalOpen(false)}>Cancel</button>
                <button type="submit" className="erp-btn primary">Save Location</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: CREATE TRANSFER */}
      {isTransferModalOpen && (
        <div className="erp-modal-overlay">
          <div className="erp-modal-card">
            <div className="erp-modal-header">
              <h3>Create Inter-Hub Stock Transfer</h3>
              <button className="erp-close-btn" onClick={() => setIsTransferModalOpen(false)}><X size={18} /></button>
            </div>
            {transferFormError && <div className="erp-form-error">{transferFormError}</div>}
            <form onSubmit={handleCreateTransfer}>
              <div className="erp-form-row">
                <div className="erp-form-group">
                  <label>Source Warehouse *</label>
                  <select
                    required
                    value={newTransfer.source_warehouse_id}
                    onChange={(e) => setNewTransfer({ ...newTransfer, source_warehouse_id: e.target.value })}
                  >
                    <option value="">Select Source...</option>
                    {warehousesList.map((w) => (
                      <option key={w.id} value={w.id}>{w.code} - {w.name}</option>
                    ))}
                  </select>
                </div>
                <div className="erp-form-group">
                  <label>Destination Warehouse *</label>
                  <select
                    required
                    value={newTransfer.dest_warehouse_id}
                    onChange={(e) => setNewTransfer({ ...newTransfer, dest_warehouse_id: e.target.value })}
                  >
                    <option value="">Select Destination...</option>
                    {warehousesList.map((w) => (
                      <option key={w.id} value={w.id}>{w.code} - {w.name}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="erp-form-group">
                <label>Product *</label>
                <select
                  required
                  value={newTransfer.items[0]?.product_id || ''}
                  onChange={(e) => {
                    const itms = [...newTransfer.items]
                    itms[0] = { ...itms[0], product_id: e.target.value }
                    setNewTransfer({ ...newTransfer, items: itms })
                  }}
                >
                  <option value="">Select Product...</option>
                  {productsList.map((p) => (
                    <option key={p.id} value={p.id}>{p.sku} - {p.name}</option>
                  ))}
                </select>
              </div>

              <div className="erp-form-group">
                <label>Transfer Quantity *</label>
                <input
                  type="number"
                  min="0.1"
                  step="0.1"
                  required
                  value={newTransfer.items[0]?.requested_quantity || 1}
                  onChange={(e) => {
                    const itms = [...newTransfer.items]
                    itms[0] = { ...itms[0], requested_quantity: parseFloat(e.target.value) || 0 }
                    setNewTransfer({ ...newTransfer, items: itms })
                  }}
                />
              </div>

              <div className="erp-form-group">
                <label>Transfer Notes</label>
                <input
                  type="text"
                  placeholder="Transport logistics reference..."
                  value={newTransfer.notes}
                  onChange={(e) => setNewTransfer({ ...newTransfer, notes: e.target.value })}
                />
              </div>

              <div className="erp-modal-footer">
                <button type="button" className="erp-btn secondary" onClick={() => setIsTransferModalOpen(false)}>Cancel</button>
                <button type="submit" className="erp-btn primary">Create Transfer</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: RECEIVE TRANSFER */}
      {isReceiveModalOpen && selectedTransferForReceive && (
        <div className="erp-modal-overlay">
          <div className="erp-modal-card">
            <div className="erp-modal-header">
              <h3>Receive Transfer {selectedTransferForReceive.transfer_number}</h3>
              <button className="erp-close-btn" onClick={() => setIsReceiveModalOpen(false)}><X size={18} /></button>
            </div>
            {receiveFormError && <div className="erp-form-error">{receiveFormError}</div>}
            <form onSubmit={handleReceiveTransfer}>
              {receivePayload.items.map((itm, idx) => {
                const orig = selectedTransferForReceive.items.find((i) => i.id === itm.item_id)
                return (
                  <div key={itm.item_id} className="receive-item-block">
                    <h4>{orig?.sku} — Dispatched: {orig?.dispatched_quantity}</h4>
                    <div className="erp-form-row">
                      <div className="erp-form-group">
                        <label>Accepted Qty</label>
                        <input
                          type="number"
                          step="0.1"
                          min="0"
                          value={itm.received_quantity}
                          onChange={(e) => {
                            const updated = [...receivePayload.items]
                            updated[idx].received_quantity = parseFloat(e.target.value) || 0
                            setReceivePayload({ ...receivePayload, items: updated })
                          }}
                        />
                      </div>
                      <div className="erp-form-group">
                        <label>Damaged Qty</label>
                        <input
                          type="number"
                          step="0.1"
                          min="0"
                          value={itm.damaged_quantity}
                          onChange={(e) => {
                            const updated = [...receivePayload.items]
                            updated[idx].damaged_quantity = parseFloat(e.target.value) || 0
                            setReceivePayload({ ...receivePayload, items: updated })
                          }}
                        />
                      </div>
                    </div>
                    {itm.damaged_quantity > 0 && (
                      <div className="erp-form-group">
                        <label>Damage Reason *</label>
                        <input
                          type="text"
                          required
                          placeholder="e.g. Broken seal, melted cartons"
                          value={itm.discrepancy_reason || ''}
                          onChange={(e) => {
                            const updated = [...receivePayload.items]
                            updated[idx].discrepancy_reason = e.target.value
                            setReceivePayload({ ...receivePayload, items: updated })
                          }}
                        />
                      </div>
                    )}
                  </div>
                )
              })}
              <div className="erp-modal-footer">
                <button type="button" className="erp-btn secondary" onClick={() => setIsReceiveModalOpen(false)}>Cancel</button>
                <button type="submit" className="erp-btn primary">Post Destination Receipt</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: CREATE ADJUSTMENT */}
      {isAdjModalOpen && (
        <div className="erp-modal-overlay">
          <div className="erp-modal-card">
            <div className="erp-modal-header">
              <h3>Record Physical Stock Count / Adjustment</h3>
              <button className="erp-close-btn" onClick={() => setIsAdjModalOpen(false)}><X size={18} /></button>
            </div>
            {adjFormError && <div className="erp-form-error">{adjFormError}</div>}
            <form onSubmit={handleCreateAdjustment}>
              <div className="erp-form-group">
                <label>Warehouse *</label>
                <select
                  required
                  value={newAdj.warehouse_id}
                  onChange={(e) => setNewAdj({ ...newAdj, warehouse_id: e.target.value })}
                >
                  <option value="">Select Warehouse...</option>
                  {warehousesList.map((w) => (
                    <option key={w.id} value={w.id}>{w.code} - {w.name}</option>
                  ))}
                </select>
              </div>
              <div className="erp-form-group">
                <label>Product *</label>
                <select
                  required
                  value={newAdj.product_id}
                  onChange={(e) => setNewAdj({ ...newAdj, product_id: e.target.value })}
                >
                  <option value="">Select Product...</option>
                  {productsList.map((p) => (
                    <option key={p.id} value={p.id}>{p.sku} - {p.name}</option>
                  ))}
                </select>
              </div>
              <div className="erp-form-row">
                <div className="erp-form-group">
                  <label>Physical Counted Quantity *</label>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    required
                    value={newAdj.counted_quantity}
                    onChange={(e) => setNewAdj({ ...newAdj, counted_quantity: parseFloat(e.target.value) || 0 })}
                  />
                </div>
                <div className="erp-form-group">
                  <label>Reason Code *</label>
                  <select
                    value={newAdj.reason_code}
                    onChange={(e) => setNewAdj({ ...newAdj, reason_code: e.target.value })}
                  >
                    <option value="PHYSICAL_COUNT">Annual / Cycle Physical Count</option>
                    <option value="DAMAGE_WRITE_OFF">Damage Write-off</option>
                    <option value="EXPIRY">Expired Shelf-Life</option>
                    <option value="CORRECTION">Ledger Audit Correction</option>
                  </select>
                </div>
              </div>
              <div className="erp-form-group">
                <label>Supporting Notes / Audit Reference</label>
                <input
                  type="text"
                  placeholder="Cycle count sheet ref..."
                  value={newAdj.notes}
                  onChange={(e) => setNewAdj({ ...newAdj, notes: e.target.value })}
                />
              </div>
              <div className="erp-modal-footer">
                <button type="button" className="erp-btn secondary" onClick={() => setIsAdjModalOpen(false)}>Cancel</button>
                <button type="submit" className="erp-btn primary">Record Adjustment</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: CREATE RESERVATION */}
      {isResModalOpen && (
        <div className="erp-modal-overlay">
          <div className="erp-modal-card">
            <div className="erp-modal-header">
              <h3>Create Stock Reservation</h3>
              <button className="erp-close-btn" onClick={() => setIsResModalOpen(false)}><X size={18} /></button>
            </div>
            {resFormError && <div className="erp-form-error">{resFormError}</div>}
            <form onSubmit={handleCreateReservation}>
              <div className="erp-form-group">
                <label>Warehouse *</label>
                <select
                  required
                  value={newRes.warehouse_id}
                  onChange={(e) => setNewRes({ ...newRes, warehouse_id: e.target.value })}
                >
                  <option value="">Select Warehouse...</option>
                  {warehousesList.map((w) => (
                    <option key={w.id} value={w.id}>{w.code} - {w.name}</option>
                  ))}
                </select>
              </div>
              <div className="erp-form-group">
                <label>Product *</label>
                <select
                  required
                  value={newRes.product_id}
                  onChange={(e) => setNewRes({ ...newRes, product_id: e.target.value })}
                >
                  <option value="">Select Product...</option>
                  {productsList.map((p) => (
                    <option key={p.id} value={p.id}>{p.sku} - {p.name}</option>
                  ))}
                </select>
              </div>
              <div className="erp-form-row">
                <div className="erp-form-group">
                  <label>Reservation Quantity *</label>
                  <input
                    type="number"
                    step="0.1"
                    min="0.1"
                    required
                    value={newRes.quantity}
                    onChange={(e) => setNewRes({ ...newRes, quantity: parseFloat(e.target.value) || 0 })}
                  />
                </div>
                <div className="erp-form-group">
                  <label>Order Reference / Customer</label>
                  <input
                    type="text"
                    placeholder="SO-2026-0042"
                    value={newRes.reference_id}
                    onChange={(e) => setNewRes({ ...newRes, reference_id: e.target.value })}
                  />
                </div>
              </div>
              <div className="erp-modal-footer">
                <button type="button" className="erp-btn secondary" onClick={() => setIsResModalOpen(false)}>Cancel</button>
                <button type="submit" className="erp-btn primary">Reserve Stock</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
