import { useEffect, useState, useMemo } from 'react'
import {
  AlertTriangle,
  Building2,
  Check,
  CheckCircle2,
  ChevronDown,
  Edit,
  Eye,
  Filter,
  History,
  Lock,
  Package,
  Plus,
  RefreshCw,
  Search,
  Shield,
  Trash2,
  Users,
  X,
} from 'lucide-react'
import { apiFetch } from './api'

export default function MasterDataView({ initialTab = 'products', onNavigateShipment }) {
  const [activeSubTab, setActiveSubTab] = useState(initialTab) // 'products' | 'suppliers' | 'customers' | 'audit'
  const [currentRole, setCurrentRole] = useState('admin') // 'admin' | 'procurement' | 'sales' | 'viewer'
  const [operatorName, setOperatorName] = useState('Local Operator')

  // Products State
  const [products, setProducts] = useState([])
  const [prodTotal, setProdTotal] = useState(0)
  const [prodSearch, setProdSearch] = useState('')
  const [prodCategory, setProdCategory] = useState('')
  const [prodActiveFilter, setProdActiveFilter] = useState('all')
  const [prodLoading, setProdLoading] = useState(false)
  const [prodError, setProdError] = useState(null)

  // Suppliers State
  const [suppliers, setSuppliers] = useState([])
  const [supTotal, setSupTotal] = useState(0)
  const [supSearch, setSupSearch] = useState('')
  const [supStatusFilter, setSupStatusFilter] = useState('all')
  const [supLoading, setSupLoading] = useState(false)
  const [supError, setSupError] = useState(null)

  // Customers State
  const [customers, setCustomers] = useState([])
  const [cusTotal, setCusTotal] = useState(0)
  const [cusSearch, setCusSearch] = useState('')
  const [cusTypeFilter, setCusTypeFilter] = useState('all')
  const [cusStatusFilter, setCusStatusFilter] = useState('all')
  const [cusLoading, setCusLoading] = useState(false)
  const [cusError, setCusError] = useState(null)

  // Audit Logs State
  const [auditLogs, setAuditLogs] = useState([])
  const [auditTotal, setAuditTotal] = useState(0)
  const [auditLoading, setAuditLoading] = useState(false)

  // Modals & Forms
  const [isProdModalOpen, setIsProdModalOpen] = useState(false)
  const [editingProd, setEditingProd] = useState(null)
  const [prodForm, setProdForm] = useState(getInitialProdForm())
  const [prodFormLoading, setProdFormLoading] = useState(false)
  const [prodFormError, setProdFormError] = useState(null)

  const [isSupModalOpen, setIsSupModalOpen] = useState(false)
  const [editingSup, setEditingSup] = useState(null)
  const [supForm, setSupForm] = useState(getInitialSupForm())
  const [supFormLoading, setSupFormLoading] = useState(false)
  const [supFormError, setSupFormError] = useState(null)

  const [isCusModalOpen, setIsCusModalOpen] = useState(false)
  const [editingCus, setEditingCus] = useState(null)
  const [cusForm, setCusForm] = useState(getInitialCusForm())
  const [cusFormLoading, setCusFormLoading] = useState(false)
  const [cusFormError, setCusFormError] = useState(null)

  const [deleteConfirmModal, setDeleteConfirmModal] = useState(null) // { type, item }

  function getInitialProdForm() {
    return {
      sku: '',
      name: '',
      description: '',
      category: 'Seafood',
      uom: 'KG',
      purchase_uom: '',
      conversion_factor: 1.0,
      default_purchase_cost: 0,
      default_selling_price: 0,
      currency: 'INR',
      hsn_code: '',
      tax_rate_pct: 5,
      country_of_origin: 'IN',
      net_weight_kg: 0,
      gross_weight_kg: 0,
      barcode: '',
      batch_tracking: false,
      is_active: true,
      notes: '',
    }
  }

  function getInitialSupForm() {
    return {
      code: '',
      name: '',
      legal_name: '',
      tax_id: '',
      country: 'IN',
      state: '',
      address: '',
      contact_person: '',
      email: '',
      phone: '',
      currency: 'INR',
      payment_terms: 'Net 30',
      payment_terms_days: 30,
      bank_name: '',
      bank_account_no: '',
      bank_ifsc_swift: '',
      status: 'active',
      notes: '',
    }
  }

  function getInitialCusForm() {
    return {
      code: '',
      name: '',
      legal_name: '',
      tax_id: '',
      customer_type: 'international',
      country: 'USA',
      destination_port: '',
      billing_address: '',
      shipping_address: '',
      contact_person: '',
      email: '',
      phone: '',
      currency: 'USD',
      payment_terms: 'LC at sight',
      payment_terms_days: 30,
      credit_limit: 100000,
      incoterm_preference: 'CIF',
      status: 'active',
      notes: '',
    }
  }

  // Sync activeSubTab if initialTab changes
  useEffect(() => {
    if (initialTab) {
      setActiveSubTab(initialTab)
    }
  }, [initialTab])

  // Auth headers
  const authHeaders = useMemo(() => ({
    'X-User-Role': currentRole,
    'X-User-Name': operatorName,
  }), [currentRole, operatorName])

  // Data Fetchers
  async function fetchProducts() {
    setProdLoading(true)
    setProdError(null)
    try {
      let query = `?limit=100`
      if (prodSearch.trim()) query += `&search=${encodeURIComponent(prodSearch.trim())}`
      if (prodCategory) query += `&category=${encodeURIComponent(prodCategory)}`
      if (prodActiveFilter !== 'all') query += `&is_active=${prodActiveFilter === 'active'}`

      const res = await apiFetch(`/api/products${query}`, { headers: authHeaders }, 'Failed to fetch products')
      setProducts(res.items || [])
      setProdTotal(res.total || 0)
    } catch (err) {
      setProdError(err.message || 'Error loading products')
    } finally {
      setProdLoading(false)
    }
  }

  async function fetchSuppliers() {
    setSupLoading(true)
    setSupError(null)
    try {
      let query = `?limit=100`
      if (supSearch.trim()) query += `&search=${encodeURIComponent(supSearch.trim())}`
      if (supStatusFilter !== 'all') query += `&status=${encodeURIComponent(supStatusFilter)}`

      const res = await apiFetch(`/api/suppliers${query}`, { headers: authHeaders }, 'Failed to fetch suppliers')
      setSuppliers(res.items || [])
      setSupTotal(res.total || 0)
    } catch (err) {
      setSupError(err.message || 'Error loading suppliers')
    } finally {
      setSupLoading(false)
    }
  }

  async function fetchCustomers() {
    setCusLoading(true)
    setCusError(null)
    try {
      let query = `?limit=100`
      if (cusSearch.trim()) query += `&search=${encodeURIComponent(cusSearch.trim())}`
      if (cusTypeFilter !== 'all') query += `&customer_type=${encodeURIComponent(cusTypeFilter)}`
      if (cusStatusFilter !== 'all') query += `&status=${encodeURIComponent(cusStatusFilter)}`

      const res = await apiFetch(`/api/customers${query}`, { headers: authHeaders }, 'Failed to fetch customers')
      setCustomers(res.items || [])
      setCusTotal(res.total || 0)
    } catch (err) {
      setCusError(err.message || 'Error loading customers')
    } finally {
      setCusLoading(false)
    }
  }

  async function fetchAuditLogs() {
    setAuditLoading(true)
    try {
      const res = await apiFetch('/api/master-data/audit-logs?limit=50', { headers: authHeaders })
      setAuditLogs(res.items || [])
      setAuditTotal(res.total || 0)
    } catch (err) {
      console.error('Failed to load audit logs:', err)
    } finally {
      setAuditLoading(false)
    }
  }

  // Trigger loads based on active subtab
  useEffect(() => {
    if (activeSubTab === 'products') fetchProducts()
    if (activeSubTab === 'suppliers') fetchSuppliers()
    if (activeSubTab === 'customers') fetchCustomers()
    if (activeSubTab === 'audit') fetchAuditLogs()
  }, [activeSubTab, prodSearch, prodCategory, prodActiveFilter, supSearch, supStatusFilter, cusSearch, cusTypeFilter, cusStatusFilter])

  // --- Product Handlers ---
  async function handleSaveProduct(e) {
    e.preventDefault()
    setProdFormLoading(true)
    setProdFormError(null)
    try {
      if (editingProd) {
        await apiFetch(
          `/api/products/${editingProd.id}`,
          {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...authHeaders },
            body: JSON.stringify(prodForm),
          },
          'Failed to update product'
        )
      } else {
        await apiFetch(
          '/api/products',
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...authHeaders },
            body: JSON.stringify(prodForm),
          },
          'Failed to create product'
        )
      }
      setIsProdModalOpen(false)
      fetchProducts()
    } catch (err) {
      setProdFormError(err.message || 'Error saving product')
    } finally {
      setProdFormLoading(false)
    }
  }

  // --- Supplier Handlers ---
  async function handleSaveSupplier(e) {
    e.preventDefault()
    setSupFormLoading(true)
    setSupFormError(null)
    try {
      if (editingSup) {
        await apiFetch(
          `/api/suppliers/${editingSup.id}`,
          {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...authHeaders },
            body: JSON.stringify(supForm),
          },
          'Failed to update supplier'
        )
      } else {
        await apiFetch(
          '/api/suppliers',
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...authHeaders },
            body: JSON.stringify(supForm),
          },
          'Failed to create supplier'
        )
      }
      setIsSupModalOpen(false)
      fetchSuppliers()
    } catch (err) {
      setSupFormError(err.message || 'Error saving supplier')
    } finally {
      setSupFormLoading(false)
    }
  }

  // --- Customer Handlers ---
  async function handleSaveCustomer(e) {
    e.preventDefault()
    setCusFormLoading(true)
    setCusFormError(null)
    try {
      if (editingCus) {
        await apiFetch(
          `/api/customers/${editingCus.id}`,
          {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...authHeaders },
            body: JSON.stringify(cusForm),
          },
          'Failed to update customer'
        )
      } else {
        await apiFetch(
          '/api/customers',
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...authHeaders },
            body: JSON.stringify(cusForm),
          },
          'Failed to create customer'
        )
      }
      setIsCusModalOpen(false)
      fetchCustomers()
    } catch (err) {
      setCusFormError(err.message || 'Error saving customer')
    } finally {
      setCusFormLoading(false)
    }
  }

  // --- Generic Delete Handler ---
  async function handleConfirmDelete() {
    if (!deleteConfirmModal) return
    const { type, item } = deleteConfirmModal
    try {
      let endpoint = ''
      if (type === 'product') endpoint = `/api/products/${item.id}`
      if (type === 'supplier') endpoint = `/api/suppliers/${item.id}`
      if (type === 'customer') endpoint = `/api/customers/${item.id}`

      await apiFetch(
        endpoint,
        {
          method: 'DELETE',
          headers: authHeaders,
        },
        `Failed to delete ${type}`
      )
      setDeleteConfirmModal(null)
      if (type === 'product') fetchProducts()
      if (type === 'supplier') fetchSuppliers()
      if (type === 'customer') fetchCustomers()
    } catch (err) {
      alert(`Delete Error: ${err.message}`)
    }
  }

  return (
    <div className="erp-master-container">
      {/* Top Header & Role Switcher */}
      <div className="erp-header-row">
        <div>
          <div className="eyebrow">EXPORTMATE ERP — PHASE 1</div>
          <h1 className="erp-title">Core Master Data Management</h1>
          <p className="erp-subtitle">
            Authoritative Product Master, Supplier Directory, Customer CRM, and Immutable Audit Log.
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
            title="Switch user role to test access boundaries"
          >
            <option value="admin">Administrator (Full Access)</option>
            <option value="procurement">Procurement (Suppliers & Products)</option>
            <option value="sales">Sales (Customers & Products)</option>
            <option value="viewer">Viewer (Read-Only)</option>
          </select>
          {currentRole === 'viewer' && (
            <span className="badge-readonly"><Lock size={12} /> Read-Only Mode</span>
          )}
        </div>
      </div>

      {/* Subtab Navigation */}
      <div className="erp-subtabs-nav">
        <button
          className={`erp-subtab-btn ${activeSubTab === 'products' ? 'active' : ''}`}
          onClick={() => setActiveSubTab('products')}
        >
          <Package size={16} />
          <span>Products</span>
          {prodTotal > 0 && <span className="erp-count-pill">{prodTotal}</span>}
        </button>

        <button
          className={`erp-subtab-btn ${activeSubTab === 'suppliers' ? 'active' : ''}`}
          onClick={() => setActiveSubTab('suppliers')}
        >
          <Building2 size={16} />
          <span>Suppliers</span>
          {supTotal > 0 && <span className="erp-count-pill">{supTotal}</span>}
        </button>

        <button
          className={`erp-subtab-btn ${activeSubTab === 'customers' ? 'active' : ''}`}
          onClick={() => setActiveSubTab('customers')}
        >
          <Users size={16} />
          <span>Customers &amp; CRM</span>
          {cusTotal > 0 && <span className="erp-count-pill">{cusTotal}</span>}
        </button>

        <button
          className={`erp-subtab-btn ${activeSubTab === 'audit' ? 'active' : ''}`}
          onClick={() => setActiveSubTab('audit')}
        >
          <History size={16} />
          <span>Audit Log</span>
          {auditTotal > 0 && <span className="erp-count-pill">{auditTotal}</span>}
        </button>
      </div>

      {/* ========================================================================= */}
      {/* PRODUCTS TAB */}
      {/* ========================================================================= */}
      {activeSubTab === 'products' && (
        <section className="erp-tab-content">
          <div className="erp-toolbar">
            <div className="erp-search-box">
              <Search size={16} />
              <input
                type="text"
                placeholder="Search by SKU, name, HSN, barcode..."
                value={prodSearch}
                onChange={(e) => setProdSearch(e.target.value)}
              />
              {prodSearch && <button onClick={() => setProdSearch('')} className="btn-clear"><X size={14} /></button>}
            </div>

            <select
              className="erp-filter-select"
              value={prodCategory}
              onChange={(e) => setProdCategory(e.target.value)}
            >
              <option value="">All Categories</option>
              <option value="Seafood">Seafood</option>
              <option value="Spices">Spices</option>
              <option value="Textiles">Textiles</option>
              <option value="Grains">Grains &amp; Pulses</option>
              <option value="General">General Cargo</option>
            </select>

            <select
              className="erp-filter-select"
              value={prodActiveFilter}
              onChange={(e) => setProdActiveFilter(e.target.value)}
            >
              <option value="all">All Status</option>
              <option value="active">Active Only</option>
              <option value="inactive">Inactive Only</option>
            </select>

            <button
              className="btn btn-primary"
              disabled={currentRole === 'viewer'}
              onClick={() => {
                setEditingProd(null)
                setProdForm(getInitialProdForm())
                setProdFormError(null)
                setIsProdModalOpen(true)
              }}
            >
              <Plus size={16} /> Add Product
            </button>
          </div>

          {prodLoading ? (
            <div className="erp-loading-state">
              <RefreshCw size={24} className="spin" />
              <span>Loading products catalog...</span>
            </div>
          ) : prodError ? (
            <div className="erp-error-banner">
              <AlertTriangle size={18} />
              <span>{prodError}</span>
              <button className="btn btn-secondary btn-sm" onClick={fetchProducts}>Retry</button>
            </div>
          ) : products.length === 0 ? (
            <div className="erp-empty-state">
              <Package size={40} className="text-muted" />
              <h3>No products found</h3>
              <p>Add products to enable purchase orders, inventory tracking, and export invoicing.</p>
              {currentRole !== 'viewer' && (
                <button
                  className="btn btn-primary btn-sm"
                  onClick={() => {
                    setEditingProd(null)
                    setProdForm(getInitialProdForm())
                    setIsProdModalOpen(true)
                  }}
                >
                  <Plus size={14} /> Add First Product
                </button>
              )}
            </div>
          ) : (
            <div className="erp-table-responsive">
              <table className="erp-table">
                <thead>
                  <tr>
                    <th>SKU</th>
                    <th>Product Name</th>
                    <th>Category</th>
                    <th>UOM</th>
                    <th>HSN / SAC</th>
                    <th>Cost Price</th>
                    <th>Selling Price</th>
                    <th>Tax Rate</th>
                    <th>Status</th>
                    <th className="text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {products.map((p) => (
                    <tr key={p.id}>
                      <td><span className="erp-sku-pill">{p.sku}</span></td>
                      <td>
                        <strong>{p.name}</strong>
                        {p.description && <div className="sub-text">{p.description}</div>}
                      </td>
                      <td><span className="erp-category-tag">{p.category}</span></td>
                      <td>{p.uom}</td>
                      <td><code>{p.hsn_code || '—'}</code></td>
                      <td>{p.currency} {Number(p.default_purchase_cost).toLocaleString()}</td>
                      <td><strong>{p.currency} {Number(p.default_selling_price).toLocaleString()}</strong></td>
                      <td>{p.tax_rate_pct}%</td>
                      <td>
                        <span className={`erp-status-badge ${p.is_active ? 'badge-active' : 'badge-inactive'}`}>
                          {p.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className="text-right">
                        <button
                          className="btn-icon"
                          title="Edit Product"
                          disabled={currentRole === 'viewer'}
                          onClick={() => {
                            setEditingProd(p)
                            setProdForm({ ...p })
                            setProdFormError(null)
                            setIsProdModalOpen(true)
                          }}
                        >
                          <Edit size={15} />
                        </button>
                        <button
                          className="btn-icon btn-danger"
                          title="Delete Product"
                          disabled={currentRole !== 'admin'}
                          onClick={() => setDeleteConfirmModal({ type: 'product', item: p })}
                        >
                          <Trash2 size={15} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {/* ========================================================================= */}
      {/* SUPPLIERS TAB */}
      {/* ========================================================================= */}
      {activeSubTab === 'suppliers' && (
        <section className="erp-tab-content">
          <div className="erp-toolbar">
            <div className="erp-search-box">
              <Search size={16} />
              <input
                type="text"
                placeholder="Search suppliers by code, name, GSTIN..."
                value={supSearch}
                onChange={(e) => setSupSearch(e.target.value)}
              />
              {supSearch && <button onClick={() => setSupSearch('')} className="btn-clear"><X size={14} /></button>}
            </div>

            <select
              className="erp-filter-select"
              value={supStatusFilter}
              onChange={(e) => setSupStatusFilter(e.target.value)}
            >
              <option value="all">All Status</option>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
              <option value="blocked">Blocked</option>
            </select>

            <button
              className="btn btn-primary"
              disabled={currentRole === 'viewer' || currentRole === 'sales'}
              onClick={() => {
                setEditingSup(null)
                setSupForm(getInitialSupForm())
                setSupFormError(null)
                setIsSupModalOpen(true)
              }}
            >
              <Plus size={16} /> Add Supplier
            </button>
          </div>

          {supLoading ? (
            <div className="erp-loading-state">
              <RefreshCw size={24} className="spin" />
              <span>Loading supplier registry...</span>
            </div>
          ) : supError ? (
            <div className="erp-error-banner">
              <AlertTriangle size={18} />
              <span>{supError}</span>
              <button className="btn btn-secondary btn-sm" onClick={fetchSuppliers}>Retry</button>
            </div>
          ) : suppliers.length === 0 ? (
            <div className="erp-empty-state">
              <Building2 size={40} className="text-muted" />
              <h3>No suppliers registered</h3>
              <p>Register exporters and vendors to manage purchase orders and goods receipt.</p>
              {currentRole !== 'viewer' && currentRole !== 'sales' && (
                <button
                  className="btn btn-primary btn-sm"
                  onClick={() => {
                    setEditingSup(null)
                    setSupForm(getInitialSupForm())
                    setIsSupModalOpen(true)
                  }}
                >
                  <Plus size={14} /> Add First Supplier
                </button>
              )}
            </div>
          ) : (
            <div className="erp-table-responsive">
              <table className="erp-table">
                <thead>
                  <tr>
                    <th>Code</th>
                    <th>Supplier Name</th>
                    <th>GSTIN / Tax ID</th>
                    <th>Country / State</th>
                    <th>Contact Person</th>
                    <th>Email / Phone</th>
                    <th>Payment Terms</th>
                    <th>Status</th>
                    <th className="text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {suppliers.map((s) => (
                    <tr key={s.id}>
                      <td><span className="erp-sku-pill">{s.code}</span></td>
                      <td>
                        <strong>{s.name}</strong>
                        {s.legal_name && s.legal_name !== s.name && <div className="sub-text">{s.legal_name}</div>}
                      </td>
                      <td><code>{s.tax_id || '—'}</code></td>
                      <td>{s.country}{s.state ? `, ${s.state}` : ''}</td>
                      <td>{s.contact_person || '—'}</td>
                      <td>
                        <div>{s.email || '—'}</div>
                        {s.phone && <div className="sub-text">{s.phone}</div>}
                      </td>
                      <td>{s.payment_terms} ({s.payment_terms_days}d)</td>
                      <td>
                        <span className={`erp-status-badge ${s.status === 'active' ? 'badge-active' : s.status === 'blocked' ? 'badge-danger' : 'badge-inactive'}`}>
                          {s.status.toUpperCase()}
                        </span>
                      </td>
                      <td className="text-right">
                        <button
                          className="btn-icon"
                          title="Edit Supplier"
                          disabled={currentRole === 'viewer' || currentRole === 'sales'}
                          onClick={() => {
                            setEditingSup(s)
                            setSupForm({ ...s })
                            setSupFormError(null)
                            setIsSupModalOpen(true)
                          }}
                        >
                          <Edit size={15} />
                        </button>
                        <button
                          className="btn-icon btn-danger"
                          title="Delete Supplier"
                          disabled={currentRole !== 'admin'}
                          onClick={() => setDeleteConfirmModal({ type: 'supplier', item: s })}
                        >
                          <Trash2 size={15} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {/* ========================================================================= */}
      {/* CUSTOMERS & CRM TAB */}
      {/* ========================================================================= */}
      {activeSubTab === 'customers' && (
        <section className="erp-tab-content">
          <div className="erp-toolbar">
            <div className="erp-search-box">
              <Search size={16} />
              <input
                type="text"
                placeholder="Search customers by code, buyer name, port..."
                value={cusSearch}
                onChange={(e) => setCusSearch(e.target.value)}
              />
              {cusSearch && <button onClick={() => setCusSearch('')} className="btn-clear"><X size={14} /></button>}
            </div>

            <select
              className="erp-filter-select"
              value={cusTypeFilter}
              onChange={(e) => setCusTypeFilter(e.target.value)}
            >
              <option value="all">All Customer Types</option>
              <option value="international">Export / International</option>
              <option value="domestic">Domestic</option>
            </select>

            <select
              className="erp-filter-select"
              value={cusStatusFilter}
              onChange={(e) => setCusStatusFilter(e.target.value)}
            >
              <option value="all">All Status</option>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
              <option value="blocked">Blocked</option>
            </select>

            <button
              className="btn btn-primary"
              disabled={currentRole === 'viewer' || currentRole === 'procurement'}
              onClick={() => {
                setEditingCus(null)
                setCusForm(getInitialCusForm())
                setCusFormError(null)
                setIsCusModalOpen(true)
              }}
            >
              <Plus size={16} /> Add Customer
            </button>
          </div>

          {cusLoading ? (
            <div className="erp-loading-state">
              <RefreshCw size={24} className="spin" />
              <span>Loading customer CRM records...</span>
            </div>
          ) : cusError ? (
            <div className="erp-error-banner">
              <AlertTriangle size={18} />
              <span>{cusError}</span>
              <button className="btn btn-secondary btn-sm" onClick={fetchCustomers}>Retry</button>
            </div>
          ) : customers.length === 0 ? (
            <div className="erp-empty-state">
              <Users size={40} className="text-muted" />
              <h3>No customers found</h3>
              <p>Add foreign buyers and domestic clients to link sales orders and shipments.</p>
              {currentRole !== 'viewer' && currentRole !== 'procurement' && (
                <button
                  className="btn btn-primary btn-sm"
                  onClick={() => {
                    setEditingCus(null)
                    setCusForm(getInitialCusForm())
                    setIsCusModalOpen(true)
                  }}
                >
                  <Plus size={14} /> Add First Customer
                </button>
              )}
            </div>
          ) : (
            <div className="erp-table-responsive">
              <table className="erp-table">
                <thead>
                  <tr>
                    <th>Code</th>
                    <th>Customer Name</th>
                    <th>Type</th>
                    <th>Country / Port</th>
                    <th>Contact Person</th>
                    <th>Terms / Currency</th>
                    <th>Credit Limit</th>
                    <th>Status</th>
                    <th className="text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {customers.map((c) => (
                    <tr key={c.id}>
                      <td><span className="erp-sku-pill">{c.code}</span></td>
                      <td>
                        <strong>{c.name}</strong>
                        {c.tax_id && <div className="sub-text">Tax: {c.tax_id}</div>}
                      </td>
                      <td>
                        <span className={`erp-type-pill ${c.customer_type === 'international' ? 'pill-export' : 'pill-domestic'}`}>
                          {c.customer_type === 'international' ? 'Export' : 'Domestic'}
                        </span>
                      </td>
                      <td>
                        <strong>{c.country}</strong>
                        {c.destination_port && <div className="sub-text">{c.destination_port}</div>}
                      </td>
                      <td>
                        <div>{c.contact_person || '—'}</div>
                        {c.email && <div className="sub-text">{c.email}</div>}
                      </td>
                      <td>
                        <div>{c.payment_terms}</div>
                        <div className="sub-text">{c.currency} ({c.incoterm_preference})</div>
                      </td>
                      <td>{c.currency} {Number(c.credit_limit).toLocaleString()}</td>
                      <td>
                        <span className={`erp-status-badge ${c.status === 'active' ? 'badge-active' : c.status === 'blocked' ? 'badge-danger' : 'badge-inactive'}`}>
                          {c.status.toUpperCase()}
                        </span>
                      </td>
                      <td className="text-right">
                        <button
                          className="btn-icon"
                          title="Edit Customer"
                          disabled={currentRole === 'viewer' || currentRole === 'procurement'}
                          onClick={() => {
                            setEditingCus(c)
                            setCusForm({ ...c })
                            setCusFormError(null)
                            setIsCusModalOpen(true)
                          }}
                        >
                          <Edit size={15} />
                        </button>
                        <button
                          className="btn-icon btn-danger"
                          title="Delete Customer"
                          disabled={currentRole !== 'admin'}
                          onClick={() => setDeleteConfirmModal({ type: 'customer', item: c })}
                        >
                          <Trash2 size={15} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {/* ========================================================================= */}
      {/* AUDIT LOG TAB */}
      {/* ========================================================================= */}
      {activeSubTab === 'audit' && (
        <section className="erp-tab-content">
          <div className="erp-toolbar">
            <span className="erp-toolbar-text">
              Showing recent append-only master data modifications. Database trigger guarantees tamper resistance.
            </span>
            <button className="btn btn-secondary btn-sm" onClick={fetchAuditLogs}>
              <RefreshCw size={14} className={auditLoading ? 'spin' : ''} /> Refresh Logs
            </button>
          </div>

          {auditLoading ? (
            <div className="erp-loading-state">
              <RefreshCw size={24} className="spin" />
              <span>Loading audit logs...</span>
            </div>
          ) : auditLogs.length === 0 ? (
            <div className="erp-empty-state">
              <History size={40} className="text-muted" />
              <h3>No audit records yet</h3>
              <p>Create, update, or delete products, suppliers, and customers to generate immutable audit events.</p>
            </div>
          ) : (
            <div className="erp-table-responsive">
              <table className="erp-table">
                <thead>
                  <tr>
                    <th>Timestamp (UTC)</th>
                    <th>Entity Type</th>
                    <th>Entity ID</th>
                    <th>Action</th>
                    <th>Performed By</th>
                    <th>Changes Summary</th>
                  </tr>
                </thead>
                <tbody>
                  {auditLogs.map((log) => (
                    <tr key={log.id}>
                      <td><small>{new Date(log.timestamp).toLocaleString()}</small></td>
                      <td><span className="erp-category-tag">{log.entity_type.toUpperCase()}</span></td>
                      <td><code>{log.entity_id}</code></td>
                      <td>
                        <span className={`erp-action-badge action-${log.action}`}>
                          {log.action.toUpperCase()}
                        </span>
                      </td>
                      <td><strong>{log.performed_by}</strong></td>
                      <td>
                        <pre className="erp-changes-json">{JSON.stringify(log.changes, null, 2)}</pre>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {/* ========================================================================= */}
      {/* MODAL: ADD / EDIT PRODUCT */}
      {/* ========================================================================= */}
      {isProdModalOpen && (
        <div className="modal-backdrop">
          <div className="modal-dialog modal-lg">
            <div className="modal-header">
              <h2>{editingProd ? 'Edit Product Master' : 'Add New Product to Catalog'}</h2>
              <button className="modal-close" onClick={() => setIsProdModalOpen(false)}><X size={18} /></button>
            </div>
            <form onSubmit={handleSaveProduct}>
              <div className="modal-body modal-grid-2">
                <div className="form-group">
                  <label>SKU (Stock Keeping Unit) *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. SKU-SHR-001"
                    value={prodForm.sku}
                    onChange={(e) => setProdForm({ ...prodForm, sku: e.target.value.toUpperCase() })}
                  />
                </div>

                <div className="form-group">
                  <label>Product Name *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Frozen Black Tiger Shrimp 16/20"
                    value={prodForm.name}
                    onChange={(e) => setProdForm({ ...prodForm, name: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>Category</label>
                  <input
                    type="text"
                    placeholder="e.g. Seafood, Spices, Textiles"
                    value={prodForm.category}
                    onChange={(e) => setProdForm({ ...prodForm, category: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>Unit of Measure (UOM) *</label>
                  <select
                    value={prodForm.uom}
                    onChange={(e) => setProdForm({ ...prodForm, uom: e.target.value })}
                  >
                    <option value="PCS">PCS (Pieces)</option>
                    <option value="KG">KG (Kilograms)</option>
                    <option value="MT">MT (Metric Tons)</option>
                    <option value="CTN">CTN (Cartons)</option>
                    <option value="BOX">BOX (Boxes)</option>
                    <option value="LTR">LTR (Liters)</option>
                  </select>
                </div>

                <div className="form-group">
                  <label>HSN / SAC Code</label>
                  <input
                    type="text"
                    placeholder="e.g. 03061720"
                    value={prodForm.hsn_code || ''}
                    onChange={(e) => setProdForm({ ...prodForm, hsn_code: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>GST Tax Rate (%)</label>
                  <select
                    value={prodForm.tax_rate_pct}
                    onChange={(e) => setProdForm({ ...prodForm, tax_rate_pct: parseFloat(e.target.value) })}
                  >
                    <option value="0">0% (Nil / Exempt)</option>
                    <option value="5">5% (Essential Goods)</option>
                    <option value="12">12% (Standard Lower)</option>
                    <option value="18">18% (Standard Rate)</option>
                    <option value="28">28% (Luxury / Demerit)</option>
                  </select>
                </div>

                <div className="form-group">
                  <label>Default Purchase Cost (INR)</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={prodForm.default_purchase_cost}
                    onChange={(e) => setProdForm({ ...prodForm, default_purchase_cost: parseFloat(e.target.value) || 0 })}
                  />
                </div>

                <div className="form-group">
                  <label>Default Selling Price (INR)</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={prodForm.default_selling_price}
                    onChange={(e) => setProdForm({ ...prodForm, default_selling_price: parseFloat(e.target.value) || 0 })}
                  />
                </div>

                <div className="form-group">
                  <label>Net Weight (KG per unit)</label>
                  <input
                    type="number"
                    step="0.001"
                    min="0"
                    value={prodForm.net_weight_kg}
                    onChange={(e) => setProdForm({ ...prodForm, net_weight_kg: parseFloat(e.target.value) || 0 })}
                  />
                </div>

                <div className="form-group">
                  <label>Gross Weight (KG per unit)</label>
                  <input
                    type="number"
                    step="0.001"
                    min="0"
                    value={prodForm.gross_weight_kg}
                    onChange={(e) => setProdForm({ ...prodForm, gross_weight_kg: parseFloat(e.target.value) || 0 })}
                  />
                </div>

                <div className="form-group">
                  <label>Barcode / GTIN</label>
                  <input
                    type="text"
                    placeholder="e.g. 8901234567890"
                    value={prodForm.barcode || ''}
                    onChange={(e) => setProdForm({ ...prodForm, barcode: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>Country of Origin</label>
                  <input
                    type="text"
                    maxLength={3}
                    value={prodForm.country_of_origin}
                    onChange={(e) => setProdForm({ ...prodForm, country_of_origin: e.target.value.toUpperCase() })}
                  />
                </div>

                <div className="form-group modal-col-span-2">
                  <label>Product Description &amp; Specifications</label>
                  <textarea
                    rows={2}
                    placeholder="Enter detailed packaging specs, quality grade, IQF specifications..."
                    value={prodForm.description || ''}
                    onChange={(e) => setProdForm({ ...prodForm, description: e.target.value })}
                  />
                </div>

                <div className="form-group modal-col-span-2 checkbox-row">
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={prodForm.is_active}
                      onChange={(e) => setProdForm({ ...prodForm, is_active: e.target.checked })}
                    />
                    <span>Active in Product Catalog</span>
                  </label>

                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={prodForm.batch_tracking}
                      onChange={(e) => setProdForm({ ...prodForm, batch_tracking: e.target.checked })}
                    />
                    <span>Enable Batch / Lot Tracking</span>
                  </label>
                </div>
              </div>

              {prodFormError && (
                <div className="modal-error-banner">
                  <AlertTriangle size={16} /> <span>{prodFormError}</span>
                </div>
              )}

              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setIsProdModalOpen(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={prodFormLoading}>
                  {prodFormLoading ? 'Saving...' : editingProd ? 'Update Product' : 'Create Product'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL: ADD / EDIT SUPPLIER */}
      {/* ========================================================================= */}
      {isSupModalOpen && (
        <div className="modal-backdrop">
          <div className="modal-dialog modal-lg">
            <div className="modal-header">
              <h2>{editingSup ? 'Edit Supplier' : 'Register New Supplier'}</h2>
              <button className="modal-close" onClick={() => setIsSupModalOpen(false)}><X size={18} /></button>
            </div>
            <form onSubmit={handleSaveSupplier}>
              <div className="modal-body modal-grid-2">
                <div className="form-group">
                  <label>Supplier Code *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. SUP-APEX-001"
                    value={supForm.code}
                    onChange={(e) => setSupForm({ ...supForm, code: e.target.value.toUpperCase() })}
                  />
                </div>

                <div className="form-group">
                  <label>Trade Name *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Apex Seafoods Pvt Ltd"
                    value={supForm.name}
                    onChange={(e) => setSupForm({ ...supForm, name: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>GSTIN / Tax ID</label>
                  <input
                    type="text"
                    placeholder="e.g. 37AAACA1234A1Z5"
                    value={supForm.tax_id || ''}
                    onChange={(e) => setSupForm({ ...supForm, tax_id: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>Country *</label>
                  <input
                    type="text"
                    required
                    value={supForm.country}
                    onChange={(e) => setSupForm({ ...supForm, country: e.target.value.toUpperCase() })}
                  />
                </div>

                <div className="form-group">
                  <label>State / Province</label>
                  <input
                    type="text"
                    placeholder="e.g. Andhra Pradesh"
                    value={supForm.state || ''}
                    onChange={(e) => setSupForm({ ...supForm, state: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>Contact Person</label>
                  <input
                    type="text"
                    placeholder="e.g. K. V. Rao"
                    value={supForm.contact_person || ''}
                    onChange={(e) => setSupForm({ ...supForm, contact_person: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>Email Address</label>
                  <input
                    type="email"
                    placeholder="procurement@apexseafoods.example.com"
                    value={supForm.email || ''}
                    onChange={(e) => setSupForm({ ...supForm, email: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>Phone Number</label>
                  <input
                    type="text"
                    placeholder="+91 891 2555666"
                    value={supForm.phone || ''}
                    onChange={(e) => setSupForm({ ...supForm, phone: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>Payment Terms</label>
                  <input
                    type="text"
                    placeholder="e.g. Net 30, LC at sight, Advance"
                    value={supForm.payment_terms}
                    onChange={(e) => setSupForm({ ...supForm, payment_terms: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>Payment Term Days</label>
                  <input
                    type="number"
                    min="0"
                    value={supForm.payment_terms_days}
                    onChange={(e) => setSupForm({ ...supForm, payment_terms_days: parseInt(e.target.value) || 0 })}
                  />
                </div>

                <div className="form-group">
                  <label>Status</label>
                  <select
                    value={supForm.status}
                    onChange={(e) => setSupForm({ ...supForm, status: e.target.value })}
                  >
                    <option value="active">Active</option>
                    <option value="inactive">Inactive</option>
                    <option value="blocked">Blocked</option>
                  </select>
                </div>

                <div className="form-group">
                  <label>Bank Name</label>
                  <input
                    type="text"
                    placeholder="e.g. State Bank of India"
                    value={supForm.bank_name || ''}
                    onChange={(e) => setSupForm({ ...supForm, bank_name: e.target.value })}
                  />
                </div>

                <div className="form-group modal-col-span-2">
                  <label>Supplier Registered Address</label>
                  <textarea
                    rows={2}
                    placeholder="Full street address, district, postal code..."
                    value={supForm.address || ''}
                    onChange={(e) => setSupForm({ ...supForm, address: e.target.value })}
                  />
                </div>
              </div>

              {supFormError && (
                <div className="modal-error-banner">
                  <AlertTriangle size={16} /> <span>{supFormError}</span>
                </div>
              )}

              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setIsSupModalOpen(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={supFormLoading}>
                  {supFormLoading ? 'Saving...' : editingSup ? 'Update Supplier' : 'Register Supplier'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL: ADD / EDIT CUSTOMER */}
      {/* ========================================================================= */}
      {isCusModalOpen && (
        <div className="modal-backdrop">
          <div className="modal-dialog modal-lg">
            <div className="modal-header">
              <h2>{editingCus ? 'Edit Customer' : 'Add Customer / Foreign Buyer'}</h2>
              <button className="modal-close" onClick={() => setIsCusModalOpen(false)}><X size={18} /></button>
            </div>
            <form onSubmit={handleSaveCustomer}>
              <div className="modal-body modal-grid-2">
                <div className="form-group">
                  <label>Customer Code *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. CUS-PACIFIC-001"
                    value={cusForm.code}
                    onChange={(e) => setCusForm({ ...cusForm, code: e.target.value.toUpperCase() })}
                  />
                </div>

                <div className="form-group">
                  <label>Customer / Buyer Name *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Pacific Cold Storage LLC"
                    value={cusForm.name}
                    onChange={(e) => setCusForm({ ...cusForm, name: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>Customer Type</label>
                  <select
                    value={cusForm.customer_type}
                    onChange={(e) => setCusForm({ ...cusForm, customer_type: e.target.value })}
                  >
                    <option value="international">Export / International Buyer</option>
                    <option value="domestic">Domestic Indian Customer</option>
                  </select>
                </div>

                <div className="form-group">
                  <label>Destination Country *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. USA, UK, JPN, ARE"
                    value={cusForm.country}
                    onChange={(e) => setCusForm({ ...cusForm, country: e.target.value.toUpperCase() })}
                  />
                </div>

                <div className="form-group">
                  <label>Destination Port</label>
                  <input
                    type="text"
                    placeholder="e.g. Long Beach, CA / Rotterdam / Jebel Ali"
                    value={cusForm.destination_port || ''}
                    onChange={(e) => setCusForm({ ...cusForm, destination_port: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>Tax ID / Foreign EIN</label>
                  <input
                    type="text"
                    placeholder="e.g. US-EIN-987654321 or GSTIN"
                    value={cusForm.tax_id || ''}
                    onChange={(e) => setCusForm({ ...cusForm, tax_id: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>Billing Currency</label>
                  <select
                    value={cusForm.currency}
                    onChange={(e) => setCusForm({ ...cusForm, currency: e.target.value })}
                  >
                    <option value="USD">USD (US Dollar)</option>
                    <option value="EUR">EUR (Euro)</option>
                    <option value="GBP">GBP (British Pound)</option>
                    <option value="JPY">JPY (Japanese Yen)</option>
                    <option value="AED">AED (UAE Dirham)</option>
                    <option value="INR">INR (Indian Rupee)</option>
                  </select>
                </div>

                <div className="form-group">
                  <label>Preferred Incoterm</label>
                  <select
                    value={cusForm.incoterm_preference}
                    onChange={(e) => setCusForm({ ...cusForm, incoterm_preference: e.target.value })}
                  >
                    <option value="FOB">FOB (Free on Board)</option>
                    <option value="CIF">CIF (Cost, Insurance &amp; Freight)</option>
                    <option value="CFR">CFR (Cost and Freight)</option>
                    <option value="EXW">EXW (Ex Works)</option>
                    <option value="DDP">DDP (Delivered Duty Paid)</option>
                  </select>
                </div>

                <div className="form-group">
                  <label>Credit Limit ({cusForm.currency})</label>
                  <input
                    type="number"
                    min="0"
                    step="1000"
                    value={cusForm.credit_limit}
                    onChange={(e) => setCusForm({ ...cusForm, credit_limit: parseFloat(e.target.value) || 0 })}
                  />
                </div>

                <div className="form-group">
                  <label>Payment Terms</label>
                  <input
                    type="text"
                    placeholder="e.g. LC at sight, Net 60"
                    value={cusForm.payment_terms}
                    onChange={(e) => setCusForm({ ...cusForm, payment_terms: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>Contact Person</label>
                  <input
                    type="text"
                    placeholder="e.g. Michael Chang"
                    value={cusForm.contact_person || ''}
                    onChange={(e) => setCusForm({ ...cusForm, contact_person: e.target.value })}
                  />
                </div>

                <div className="form-group">
                  <label>Contact Email</label>
                  <input
                    type="email"
                    placeholder="buyer@pacificcold.example.com"
                    value={cusForm.email || ''}
                    onChange={(e) => setCusForm({ ...cusForm, email: e.target.value })}
                  />
                </div>

                <div className="form-group modal-col-span-2">
                  <label>Billing &amp; Delivery Address</label>
                  <textarea
                    rows={2}
                    placeholder="Full corporate billing and dispatch address..."
                    value={cusForm.billing_address || ''}
                    onChange={(e) => setCusForm({ ...cusForm, billing_address: e.target.value })}
                  />
                </div>
              </div>

              {cusFormError && (
                <div className="modal-error-banner">
                  <AlertTriangle size={16} /> <span>{cusFormError}</span>
                </div>
              )}

              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setIsCusModalOpen(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={cusFormLoading}>
                  {cusFormLoading ? 'Saving...' : editingCus ? 'Update Customer' : 'Add Customer'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL: DELETE CONFIRMATION */}
      {/* ========================================================================= */}
      {deleteConfirmModal && (
        <div className="modal-backdrop">
          <div className="modal-dialog modal-sm">
            <div className="modal-header">
              <h2>Confirm Deletion</h2>
              <button className="modal-close" onClick={() => setDeleteConfirmModal(null)}><X size={18} /></button>
            </div>
            <div className="modal-body">
              <p>
                Are you sure you want to delete this {deleteConfirmModal.type}:{' '}
                <strong>{deleteConfirmModal.item.name || deleteConfirmModal.item.sku || deleteConfirmModal.item.code}</strong>?
              </p>
              <p className="sub-text text-danger">This action will be permanently recorded in the immutable ERP audit log.</p>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setDeleteConfirmModal(null)}>Cancel</button>
              <button className="btn btn-danger" onClick={handleConfirmDelete}>Confirm Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
