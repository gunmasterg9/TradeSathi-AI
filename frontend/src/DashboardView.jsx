import { useEffect, useState, useMemo } from 'react'
import {
  AlertCircle,
  AlertTriangle,
  ArrowDownToLine,
  ArrowUpRight,
  BarChart3,
  Boxes,
  Building2,
  Calendar,
  CheckCircle2,
  Clock,
  CreditCard,
  DollarSign,
  Download,
  Eye,
  FileCheck2,
  FileSpreadsheet,
  FileText,
  Filter,
  History,
  Info,
  LayoutDashboard,
  Lock,
  Package,
  RefreshCw,
  Search,
  Shield,
  ShieldAlert,
  Ship,
  ShoppingBag,
  ShoppingCart,
  SlidersHorizontal,
  TrendingUp,
  Truck,
  Users,
  Warehouse,
  X,
  XCircle,
} from 'lucide-react'
import { apiFetch, API_BASE } from './api'

export default function DashboardView() {
  const [activeTab, setActiveTab] = useState('overview') // 'overview' | 'sales' | 'finance' | 'inventory' | 'exports'
  const [currentRole, setCurrentRole] = useState('admin')
  const [operatorEmail, setOperatorEmail] = useState('admin@tradesathi.local')

  const authHeaders = useMemo(
    () => ({
      'X-User-Role': currentRole,
      'X-User-Email': operatorEmail,
      'X-User-Id': operatorEmail.split('@')[0],
    }),
    [currentRole, operatorEmail]
  )

  // Filters State
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [selectedCurrency, setSelectedCurrency] = useState('')
  const [selectedCustomer, setSelectedCustomer] = useState('')

  // KPI & Detail Data
  const [kpis, setKpis] = useState(null)
  const [kpisLoading, setKpisLoading] = useState(false)
  const [kpisError, setKpisError] = useState(null)

  // Detailed Reports State
  const [salesReport, setSalesReport] = useState(null)
  const [salesLoading, setSalesLoading] = useState(false)
  const [financeReport, setFinanceReport] = useState(null)
  const [financeLoading, setFinanceLoading] = useState(false)
  const [inventoryReport, setInventoryReport] = useState(null)
  const [inventoryLoading, setInventoryLoading] = useState(false)
  const [exportsReport, setExportsReport] = useState(null)
  const [exportsLoading, setExportsLoading] = useState(false)

  // CSV Export Modal / Status
  const [exportingCsv, setExportingCsv] = useState(false)
  const [csvStatusMessage, setCsvStatusMessage] = useState(null)

  // -------------------------------------------------------------
  // Data Fetching: KPIs
  // -------------------------------------------------------------
  const fetchKpis = async () => {
    setKpisLoading(true)
    setKpisError(null)
    try {
      const params = new URLSearchParams()
      if (startDate) params.append('start_date', startDate)
      if (endDate) params.append('end_date', endDate)
      if (selectedCurrency) params.append('currency', selectedCurrency)
      if (selectedCustomer) params.append('customer_id', selectedCustomer)

      const url = `/api/reports/dashboard-kpis${params.toString() ? '?' + params.toString() : ''}`
      const res = await apiFetch(url, { headers: authHeaders })
      setKpis(res)
    } catch (err) {
      setKpisError(err.message || 'Failed to load dashboard KPIs')
    } finally {
      setKpisLoading(false)
    }
  }

  // -------------------------------------------------------------
  // Data Fetching: Sales Report
  // -------------------------------------------------------------
  const fetchSalesReport = async () => {
    setSalesLoading(true)
    try {
      const params = new URLSearchParams()
      if (startDate) params.append('start_date', startDate)
      if (endDate) params.append('end_date', endDate)
      if (selectedCurrency) params.append('currency', selectedCurrency)
      if (selectedCustomer) params.append('customer_id', selectedCustomer)

      const res = await apiFetch(`/api/reports/sales?${params.toString()}`, { headers: authHeaders })
      setSalesReport(res)
    } catch (err) {
      console.error('Failed to load sales report', err)
    } finally {
      setSalesLoading(false)
    }
  }

  // -------------------------------------------------------------
  // Data Fetching: Finance Report
  // -------------------------------------------------------------
  const fetchFinanceReport = async () => {
    setFinanceLoading(true)
    try {
      const params = new URLSearchParams()
      if (startDate) params.append('start_date', startDate)
      if (endDate) params.append('end_date', endDate)
      if (selectedCurrency) params.append('currency', selectedCurrency)
      if (selectedCustomer) params.append('customer_id', selectedCustomer)

      const res = await apiFetch(`/api/reports/finance?${params.toString()}`, { headers: authHeaders })
      setFinanceReport(res)
    } catch (err) {
      console.error('Failed to load finance report', err)
      setFinanceReport({ error: err.message || 'Access restricted' })
    } finally {
      setFinanceLoading(false)
    }
  }

  // -------------------------------------------------------------
  // Data Fetching: Inventory Report
  // -------------------------------------------------------------
  const fetchInventoryReport = async () => {
    setInventoryLoading(true)
    try {
      const res = await apiFetch('/api/reports/inventory', { headers: authHeaders })
      setInventoryReport(res)
    } catch (err) {
      console.error('Failed to load inventory report', err)
    } finally {
      setInventoryLoading(false)
    }
  }

  // -------------------------------------------------------------
  // Data Fetching: Exports Report
  // -------------------------------------------------------------
  const fetchExportsReport = async () => {
    setExportsLoading(true)
    try {
      const res = await apiFetch('/api/reports/exports', { headers: authHeaders })
      setExportsReport(res)
    } catch (err) {
      console.error('Failed to load exports report', err)
    } finally {
      setExportsLoading(false)
    }
  }

  // Initial and reactive fetch
  useEffect(() => {
    fetchKpis()
  }, [authHeaders, startDate, endDate, selectedCurrency, selectedCustomer])

  useEffect(() => {
    if (activeTab === 'sales') fetchSalesReport()
    if (activeTab === 'finance') fetchFinanceReport()
    if (activeTab === 'inventory') fetchInventoryReport()
    if (activeTab === 'exports') fetchExportsReport()
  }, [activeTab, authHeaders, startDate, endDate, selectedCurrency, selectedCustomer])

  // -------------------------------------------------------------
  // CSV Export Trigger
  // -------------------------------------------------------------
  const handleExportCsv = async (reportType) => {
    setExportingCsv(true)
    setCsvStatusMessage(null)
    try {
      const params = new URLSearchParams({ report_type: reportType })
      if (startDate) params.append('start_date', startDate)
      if (endDate) params.append('end_date', endDate)
      if (selectedCurrency) params.append('currency', selectedCurrency)
      if (selectedCustomer) params.append('customer_id', selectedCustomer)

      const response = await fetch(`${API_BASE}/api/reports/export-csv?${params.toString()}`, {
        headers: authHeaders,
      })

      if (!response.ok) {
        const text = await response.text()
        throw new Error(text || `Export failed with HTTP ${response.status}`)
      }

      const blob = await response.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `tradesathi_${reportType}_${new Date().toISOString().slice(0, 10)}.csv`
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)

      setCsvStatusMessage(`Successfully exported ${reportType}.csv (formula-sanitized)`)
      setTimeout(() => setCsvStatusMessage(null), 4000)
    } catch (err) {
      setCsvStatusMessage(`Export failed: ${err.message}`)
      setTimeout(() => setCsvStatusMessage(null), 5000)
    } finally {
      setExportingCsv(false)
    }
  }

  // Helper formatting
  const fmtInr = (val) =>
    new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 2,
    }).format(Number(val) || 0)

  const fmtQty = (val) =>
    new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(Number(val) || 0)

  return (
    <div className="invoicing-container">
      {/* =========================================================
          Top Control & Role Simulation Header
          ========================================================= */}
      <div className="invoicing-header">
        <div>
          <div className="view-eyebrow">
            <LayoutDashboard size={14} /> EXECUTIVE DASHBOARD &amp; ENTERPRISE REPORTING
          </div>
          <h2>Executive Intelligence Hub</h2>
          <p className="view-subtext">
            Authoritative transactional metrics across Sales, Procurement, Inventory, Finance, and Export Operations.
          </p>
        </div>

        {/* Role Simulator Pill */}
        <div className="role-simulator-bar">
          <span className="role-label">
            <Shield size={14} /> Active Persona:
          </span>
          <select
            className="role-select"
            value={currentRole}
            onChange={(e) => {
              const r = e.target.value
              setCurrentRole(r)
              setOperatorEmail(`${r}@tradesathi.local`)
            }}
          >
            <option value="admin">Administrator (Full Access)</option>
            <option value="manager">Finance &amp; Ops Manager</option>
            <option value="sales">Sales Executive</option>
            <option value="procurement">Procurement Officer</option>
            <option value="warehouse">Warehouse Manager</option>
            <option value="operator">Local Operator</option>
            <option value="viewer">Auditor Viewer (Restricted)</option>
          </select>
        </div>
      </div>

      {/* =========================================================
          Global Filter & Action Bar
          ========================================================= */}
      <div className="filter-card">
        <div className="filter-row">
          <div className="filter-group">
            <label>
              <Calendar size={13} /> Start Date
            </label>
            <input
              type="date"
              className="filter-input"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </div>

          <div className="filter-group">
            <label>
              <Calendar size={13} /> End Date
            </label>
            <input
              type="date"
              className="filter-input"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </div>

          <div className="filter-group">
            <label>
              <DollarSign size={13} /> Currency
            </label>
            <select
              className="filter-input"
              value={selectedCurrency}
              onChange={(e) => setSelectedCurrency(e.target.value)}
            >
              <option value="">All Currencies</option>
              <option value="INR">INR — Indian Rupee</option>
              <option value="USD">USD — US Dollar</option>
              <option value="EUR">EUR — Euro</option>
              <option value="GBP">GBP — British Pound</option>
            </select>
          </div>

          <div className="filter-actions">
            <button className="btn-secondary" onClick={fetchKpis} disabled={kpisLoading}>
              <RefreshCw size={14} className={kpisLoading ? 'spin' : ''} /> Refresh
            </button>
            {(startDate || endDate || selectedCurrency) && (
              <button
                className="btn-ghost"
                onClick={() => {
                  setStartDate('')
                  setEndDate('')
                  setSelectedCurrency('')
                  setSelectedCustomer('')
                }}
              >
                Clear
              </button>
            )}
          </div>

          {/* CSV Export Dropdown */}
          <div className="export-menu-wrapper" style={{ marginLeft: 'auto' }}>
            <div className="dropdown">
              <button className="btn-primary" disabled={exportingCsv}>
                <Download size={14} /> {exportingCsv ? 'Exporting...' : 'Export CSV'}
              </button>
              <div className="dropdown-menu">
                <button onClick={() => handleExportCsv('sales_orders')}>Sales Orders Register</button>
                <button onClick={() => handleExportCsv('invoices')}>Invoices Register</button>
                <button onClick={() => handleExportCsv('receivables_aging')}>Receivables Aging</button>
                <button onClick={() => handleExportCsv('inventory_balances')}>Inventory Balances</button>
                <button onClick={() => handleExportCsv('export_shipments')}>Export Shipments Register</button>
              </div>
            </div>
          </div>
        </div>

        {csvStatusMessage && (
          <div
            className={`toast-alert ${
              csvStatusMessage.includes('failed') ? 'toast-error' : 'toast-success'
            }`}
          >
            {csvStatusMessage}
          </div>
        )}
      </div>

      {/* =========================================================
          Tab Navigation
          ========================================================= */}
      <div className="invoicing-tabs">
        <button
          className={`tab-btn ${activeTab === 'overview' ? 'active' : ''}`}
          onClick={() => setActiveTab('overview')}
        >
          <LayoutDashboard size={15} /> Executive Overview
        </button>
        <button
          className={`tab-btn ${activeTab === 'sales' ? 'active' : ''}`}
          onClick={() => setActiveTab('sales')}
        >
          <ShoppingBag size={15} /> Sales &amp; Fulfilment
        </button>
        <button
          className={`tab-btn ${activeTab === 'finance' ? 'active' : ''}`}
          onClick={() => setActiveTab('finance')}
        >
          <CreditCard size={15} /> Finance &amp; Receivables
        </button>
        <button
          className={`tab-btn ${activeTab === 'inventory' ? 'active' : ''}`}
          onClick={() => setActiveTab('inventory')}
        >
          <Boxes size={15} /> Inventory &amp; Reorders
        </button>
        <button
          className={`tab-btn ${activeTab === 'exports' ? 'active' : ''}`}
          onClick={() => setActiveTab('exports')}
        >
          <Ship size={15} /> Export Operations
        </button>
      </div>

      {/* =========================================================
          TAB 1: EXECUTIVE OVERVIEW
          ========================================================= */}
      {activeTab === 'overview' && (
        <div className="dashboard-content">
          {kpisLoading && !kpis ? (
            <div className="loading-state">
              <RefreshCw size={24} className="spin" />
              <span>Compiling executive transactional metrics...</span>
            </div>
          ) : kpisError ? (
            <div className="error-card">
              <AlertCircle size={20} />
              <span>{kpisError}</span>
              <button className="btn-secondary" onClick={fetchKpis}>
                Retry
              </button>
            </div>
          ) : kpis ? (
            <>
              {/* Top Sales & Financial KPI Grid */}
              <div className="kpi-grid-4">
                {/* 1. Confirmed Sales */}
                <div className="metric-card">
                  <div className="metric-header">
                    <span className="metric-title">CONFIRMED SALES VALUE</span>
                    <span className="icon-pill icon-blue">
                      <ShoppingBag size={16} />
                    </span>
                  </div>
                  <div className="metric-value">
                    {Object.keys(kpis.sales.confirmed_orders_by_currency).length === 0 ? (
                      '0.00'
                    ) : (
                      Object.entries(kpis.sales.confirmed_orders_by_currency).map(
                        ([curr, val]) => (
                          <div key={curr} className="currency-line">
                            <span className="curr-tag">{curr}</span>{' '}
                            {new Intl.NumberFormat().format(val.total_value)}
                          </div>
                        )
                      )
                    )}
                  </div>
                  <div className="metric-footer">
                    <span>
                      Ordered: <strong>{fmtQty(kpis.sales.total_ordered_qty)}</strong> units
                    </span>
                    <span className="bullet">•</span>
                    <span>
                      Fulfilled: <strong>{fmtQty(kpis.sales.fulfilled_qty)}</strong>
                    </span>
                  </div>
                </div>

                {/* 2. Outstanding Receivables */}
                <div className="metric-card">
                  <div className="metric-header">
                    <span className="metric-title">OUTSTANDING RECEIVABLES</span>
                    <span className="icon-pill icon-amber">
                      <CreditCard size={16} />
                    </span>
                  </div>
                  {kpis.finance.restricted ? (
                    <div className="restricted-badge">
                      <Lock size={14} /> Manager Restricted
                    </div>
                  ) : (
                    <>
                      <div className="metric-value highlight-amber">
                        {fmtInr(kpis.finance.issued_receivables_base_inr)}
                      </div>
                      <div className="metric-footer">
                        <span>
                          Open Invoices: <strong>{kpis.finance.open_invoices_count}</strong>
                        </span>
                        <span className="bullet">•</span>
                        <span>
                          Draft Excluded: {fmtInr(kpis.finance.draft_invoiced_base_inr)}
                        </span>
                      </div>
                    </>
                  )}
                </div>

                {/* 3. Collected Cash & Credits */}
                <div className="metric-card">
                  <div className="metric-header">
                    <span className="metric-title">COLLECTED PAYMENTS</span>
                    <span className="icon-pill icon-green">
                      <DollarSign size={16} />
                    </span>
                  </div>
                  {kpis.finance.restricted ? (
                    <div className="restricted-badge">
                      <Lock size={14} /> Manager Restricted
                    </div>
                  ) : (
                    <>
                      <div className="metric-value highlight-green">
                        {fmtInr(kpis.finance.collected_payments_base_inr)}
                      </div>
                      <div className="metric-footer">
                        <span>
                          Unallocated Credits: {fmtInr(kpis.finance.unallocated_credits_base_inr)}
                        </span>
                        <span className="bullet">•</span>
                        <span>
                          Payments: <strong>{kpis.finance.payments_count}</strong>
                        </span>
                      </div>
                    </>
                  )}
                </div>

                {/* 4. Realized FX & Credit Notes */}
                <div className="metric-card">
                  <div className="metric-header">
                    <span className="metric-title">CREDIT NOTES &amp; FX DIFF</span>
                    <span className="icon-pill icon-purple">
                      <TrendingUp size={16} />
                    </span>
                  </div>
                  {kpis.finance.restricted ? (
                    <div className="restricted-badge">
                      <Lock size={14} /> Manager Restricted
                    </div>
                  ) : (
                    <>
                      <div className="metric-value">
                        {fmtInr(kpis.finance.credit_notes_base_inr)}
                      </div>
                      <div className="metric-footer">
                        <span>
                          Realized FX:{' '}
                          <strong
                            className={
                              kpis.finance.realized_fx_diff_inr >= 0
                                ? 'text-green'
                                : 'text-red'
                            }
                          >
                            {fmtInr(kpis.finance.realized_fx_diff_inr)}
                          </strong>
                        </span>
                        <span className="bullet">•</span>
                        <span>Notes: {kpis.finance.credit_notes_count}</span>
                      </div>
                    </>
                  )}
                </div>
              </div>

              {/* Second Row: Operations & Compliance (Inventory, Procurement, Exports) */}
              <div className="kpi-grid-3" style={{ marginTop: '1.25rem' }}>
                {/* Inventory Health */}
                <div className="card-box">
                  <div className="card-header-clean">
                    <div>
                      <h4>Inventory Stock Health</h4>
                      <p className="card-sub">Available vs Reserved &amp; Reorders</p>
                    </div>
                    <span className="icon-pill icon-blue">
                      <Boxes size={16} />
                    </span>
                  </div>

                  <div className="status-bars-group">
                    <div className="status-bar-row">
                      <span>Available on Hand</span>
                      <strong>{fmtQty(kpis.inventory.available_qty)} PCS</strong>
                    </div>
                    <div className="status-bar-row">
                      <span>Reserved for Orders</span>
                      <strong className="text-amber">
                        {fmtQty(kpis.inventory.reserved_qty)} PCS ({kpis.inventory.active_reservations_count} active)
                      </strong>
                    </div>
                    <div className="status-bar-row">
                      <span>Quarantined / Inspection</span>
                      <strong className="text-purple">
                        {fmtQty(kpis.inventory.quarantined_qty)} PCS
                      </strong>
                    </div>
                    <div className="status-bar-row">
                      <span>In-Transit Transfers</span>
                      <strong>{fmtQty(kpis.inventory.in_transit_qty)} PCS</strong>
                    </div>
                  </div>

                  {kpis.inventory.low_stock_products_count > 0 && (
                    <div className="warning-banner" style={{ marginTop: '1rem' }}>
                      <AlertTriangle size={15} />
                      <span>
                        <strong>{kpis.inventory.low_stock_products_count}</strong> products below reorder threshold
                      </span>
                    </div>
                  )}
                </div>

                {/* Procurement Commitments */}
                <div className="card-box">
                  <div className="card-header-clean">
                    <div>
                      <h4>Procurement Commitments</h4>
                      <p className="card-sub">Purchase Orders &amp; Receipts</p>
                    </div>
                    <span className="icon-pill icon-purple">
                      <ShoppingCart size={16} />
                    </span>
                  </div>

                  <div className="metric-block">
                    <span className="metric-label">ACTIVE PO COMMITMENTS</span>
                    <div className="metric-currency-stack">
                      {Object.keys(kpis.procurement.active_commitments_by_currency).length === 0 ? (
                        <div className="empty-subtext">No active PO commitments</div>
                      ) : (
                        Object.entries(kpis.procurement.active_commitments_by_currency).map(
                          ([curr, data]) => (
                            <div key={curr} className="currency-line">
                              <span className="curr-tag">{curr}</span>{' '}
                              {new Intl.NumberFormat().format(data.commitment_value)}{' '}
                              <span className="count-pill">({data.po_count} POs)</span>
                            </div>
                          )
                        )
                      )}
                    </div>
                  </div>

                  <div className="status-bar-row" style={{ marginTop: '0.75rem' }}>
                    <span>Pending Quantities Awaiting Receipt</span>
                    <strong>{fmtQty(kpis.procurement.pending_receipt_qty)} units</strong>
                  </div>

                  <div className="disclaimer-callout" style={{ marginTop: '0.75rem' }}>
                    <Info size={13} />
                    <span>{kpis.procurement.supplier_balance_notice}</span>
                  </div>
                </div>

                {/* Export Operations Status */}
                <div className="card-box">
                  <div className="card-header-clean">
                    <div>
                      <h4>Export Operations Readiness</h4>
                      <p className="card-sub">Shipments &amp; Compliance Pipeline</p>
                    </div>
                    <span className="icon-pill icon-green">
                      <Ship size={16} />
                    </span>
                  </div>

                  <div className="status-bars-group">
                    <div className="status-bar-row">
                      <span>Total Active Shipments</span>
                      <strong>{kpis.exports.total_shipments_count}</strong>
                    </div>
                    <div className="status-bar-row">
                      <span>Document Review Backlog</span>
                      <strong className="text-amber">
                        {kpis.exports.document_backlog_count} items pending
                      </strong>
                    </div>
                    <div className="status-bar-row">
                      <span>Blocked Readiness</span>
                      <strong
                        className={
                          kpis.exports.blocked_shipments_count > 0 ? 'text-red' : 'text-green'
                        }
                      >
                        {kpis.exports.blocked_shipments_count} shipments
                      </strong>
                    </div>
                  </div>

                  <div className="compliance-notice-box" style={{ marginTop: '1rem' }}>
                    <ShieldAlert size={14} />
                    <span>{kpis.exports.compliance_disclaimer}</span>
                  </div>
                </div>
              </div>
            </>
          ) : null}
        </div>
      )}

      {/* =========================================================
          TAB 2: SALES & FULFILMENT DRILL-DOWN
          ========================================================= */}
      {activeTab === 'sales' && (
        <div className="tab-section">
          {salesLoading ? (
            <div className="loading-state">
              <RefreshCw size={24} className="spin" />
              <span>Loading sales order register...</span>
            </div>
          ) : salesReport ? (
            <div className="table-card">
              <div className="card-header-clean">
                <div>
                  <h4>Confirmed Sales Orders Register</h4>
                  <p className="card-sub">Total {salesReport.total_records} records found</p>
                </div>
              </div>

              <div className="table-responsive">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Order #</th>
                      <th>Customer</th>
                      <th>Date</th>
                      <th>Currency</th>
                      <th>Subtotal</th>
                      <th>Tax</th>
                      <th>Grand Total</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {salesReport.orders.length === 0 ? (
                      <tr>
                        <td colSpan="8" className="empty-td">
                          No matching sales orders found.
                        </td>
                      </tr>
                    ) : (
                      salesReport.orders.map((o) => (
                        <tr key={o.id}>
                          <td className="font-mono font-bold">{o.order_number}</td>
                          <td>{o.customer_name}</td>
                          <td>{o.order_date}</td>
                          <td>
                            <span className="curr-tag">{o.currency}</span>
                          </td>
                          <td>{new Intl.NumberFormat().format(o.subtotal)}</td>
                          <td>{new Intl.NumberFormat().format(o.tax_total)}</td>
                          <td className="font-bold">
                            {new Intl.NumberFormat().format(o.grand_total)}
                          </td>
                          <td>
                            <span className={`status-pill status-${o.status}`}>
                              {o.status}
                            </span>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}
        </div>
      )}

      {/* =========================================================
          TAB 3: FINANCE & RECEIVABLES DRILL-DOWN
          ========================================================= */}
      {activeTab === 'finance' && (
        <div className="tab-section">
          {financeLoading ? (
            <div className="loading-state">
              <RefreshCw size={24} className="spin" />
              <span>Loading finance &amp; aging ledger...</span>
            </div>
          ) : financeReport && financeReport.error ? (
            <div className="permission-card">
              <Lock size={28} />
              <h4>Permission Denied</h4>
              <p>
                Financial reports and receivables aging require Manager or Administrator authorization.
              </p>
              <button
                className="btn-secondary"
                onClick={() => {
                  setCurrentRole('manager')
                  setOperatorEmail('manager@tradesathi.local')
                }}
              >
                Switch to Manager Persona
              </button>
            </div>
          ) : financeReport ? (
            <>
              {/* Statutory Notice */}
              <div className="disclaimer-callout">
                <Info size={14} />
                <span>{financeReport.statutory_notice}</span>
              </div>

              {/* Receivables Aging Buckets Summary */}
              {financeReport.receivables_aging && (
                <div className="aging-buckets-container" style={{ marginTop: '1rem' }}>
                  <h4>Receivables Aging Analysis (Base INR)</h4>
                  <div className="aging-grid">
                    <div className="aging-bucket">
                      <span className="bucket-title">Current (Not Due)</span>
                      <strong className="text-green">
                        {fmtInr(financeReport.receivables_aging.buckets.current)}
                      </strong>
                    </div>
                    <div className="aging-bucket">
                      <span className="bucket-title">1 - 30 Days</span>
                      <strong>{fmtInr(financeReport.receivables_aging.buckets.days_1_30)}</strong>
                    </div>
                    <div className="aging-bucket">
                      <span className="bucket-title">31 - 60 Days</span>
                      <strong className="text-amber">
                        {fmtInr(financeReport.receivables_aging.buckets.days_31_60)}
                      </strong>
                    </div>
                    <div className="aging-bucket">
                      <span className="bucket-title">61 - 90 Days</span>
                      <strong className="text-amber">
                        {fmtInr(financeReport.receivables_aging.buckets.days_61_90)}
                      </strong>
                    </div>
                    <div className="aging-bucket">
                      <span className="bucket-title">90+ Days Overdue</span>
                      <strong className="text-red">
                        {fmtInr(financeReport.receivables_aging.buckets.days_90_plus)}
                      </strong>
                    </div>
                  </div>
                </div>
              )}

              {/* Invoices Table */}
              <div className="table-card" style={{ marginTop: '1.25rem' }}>
                <div className="card-header-clean">
                  <div>
                    <h4>Customer Invoices Register</h4>
                    <p className="card-sub">Total {financeReport.total_invoices} invoices</p>
                  </div>
                </div>

                <div className="table-responsive">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Invoice #</th>
                        <th>Customer</th>
                        <th>Invoice Date</th>
                        <th>Due Date</th>
                        <th>Currency</th>
                        <th>Grand Total</th>
                        <th>Base INR</th>
                        <th>Amount Paid</th>
                        <th>Balance Due</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {financeReport.invoices.length === 0 ? (
                        <tr>
                          <td colSpan="10" className="empty-td">
                            No invoices recorded yet.
                          </td>
                        </tr>
                      ) : (
                        financeReport.invoices.map((inv) => (
                          <tr key={inv.id}>
                            <td className="font-mono font-bold">{inv.invoice_number}</td>
                            <td>{inv.customer_name}</td>
                            <td>{inv.invoice_date}</td>
                            <td>{inv.due_date}</td>
                            <td>
                              <span className="curr-tag">{inv.currency}</span>
                            </td>
                            <td>{new Intl.NumberFormat().format(inv.grand_total)}</td>
                            <td>{fmtInr(inv.grand_total_base_inr)}</td>
                            <td>{new Intl.NumberFormat().format(inv.amount_paid)}</td>
                            <td
                              className={
                                inv.balance_due > 0 ? 'text-amber font-bold' : 'text-green'
                              }
                            >
                              {new Intl.NumberFormat().format(inv.balance_due)}
                            </td>
                            <td>
                              <span className={`status-pill status-${inv.status}`}>
                                {inv.status}
                              </span>
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          ) : null}
        </div>
      )}

      {/* =========================================================
          TAB 4: INVENTORY DRILL-DOWN
          ========================================================= */}
      {activeTab === 'inventory' && (
        <div className="tab-section">
          {inventoryLoading ? (
            <div className="loading-state">
              <RefreshCw size={24} className="spin" />
              <span>Loading inventory balances and warehouse summaries...</span>
            </div>
          ) : inventoryReport ? (
            <>
              {/* Warehouse Summaries */}
              <div className="warehouse-summary-grid">
                {inventoryReport.warehouse_summary.map((wh) => (
                  <div key={wh.warehouse_id} className="wh-card">
                    <div className="wh-header">
                      <Warehouse size={16} />
                      <span className="wh-name">{wh.warehouse_name}</span>
                      <span className="wh-code">({wh.warehouse_code})</span>
                    </div>
                    <div className="wh-body">
                      <span>Total Stock: {fmtQty(wh.total_on_hand_qty)} PCS</span>
                      <span>Total Value: {fmtInr(wh.total_stock_value)}</span>
                    </div>
                  </div>
                ))}
              </div>

              {/* Product Inventory Table */}
              <div className="table-card" style={{ marginTop: '1.25rem' }}>
                <div className="card-header-clean">
                  <div>
                    <h4>Product Inventory &amp; Stock Health</h4>
                    <p className="card-sub">
                      Reorder level comparison and available to promise
                    </p>
                  </div>
                </div>

                <div className="table-responsive">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>SKU</th>
                        <th>Product Name</th>
                        <th>Category</th>
                        <th>UOM</th>
                        <th>On Hand</th>
                        <th>Reserved</th>
                        <th>Net Available</th>
                        <th>Reorder Level</th>
                        <th>Quarantined</th>
                        <th>Health Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {inventoryReport.products.length === 0 ? (
                        <tr>
                          <td colSpan="10" className="empty-td">
                            No products found.
                          </td>
                        </tr>
                      ) : (
                        inventoryReport.products.map((p) => (
                          <tr key={p.product_id}>
                            <td className="font-mono font-bold">{p.sku}</td>
                            <td>{p.name}</td>
                            <td>{p.category}</td>
                            <td>{p.uom}</td>
                            <td>{fmtQty(p.on_hand_available)}</td>
                            <td className="text-amber">{fmtQty(p.reserved_qty)}</td>
                            <td className="font-bold">{fmtQty(p.net_available_qty)}</td>
                            <td>{fmtQty(p.reorder_level)}</td>
                            <td>{fmtQty(p.quarantined_qty)}</td>
                            <td>
                              <span className={`health-badge badge-${p.stock_health}`}>
                                {p.stock_health}
                              </span>
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          ) : null}
        </div>
      )}

      {/* =========================================================
          TAB 5: EXPORT OPERATIONS DRILL-DOWN
          ========================================================= */}
      {activeTab === 'exports' && (
        <div className="tab-section">
          {exportsLoading ? (
            <div className="loading-state">
              <RefreshCw size={24} className="spin" />
              <span>Loading export shipment register...</span>
            </div>
          ) : exportsReport ? (
            <>
              <div className="compliance-notice-box">
                <ShieldAlert size={14} />
                <span>{exportsReport.compliance_disclaimer}</span>
              </div>

              {/* Blocked Shipments Callout */}
              {exportsReport.blocked_shipments.length > 0 && (
                <div className="error-card" style={{ marginTop: '1rem' }}>
                  <AlertCircle size={20} />
                  <div>
                    <strong>
                      {exportsReport.blocked_shipments.length} Export Shipments Currently Blocked
                    </strong>
                    <p className="card-sub">
                      Missing mandatory customs documents or unresolved discrepancy findings require review.
                    </p>
                  </div>
                </div>
              )}

              {/* Shipments Table */}
              <div className="table-card" style={{ marginTop: '1.25rem' }}>
                <div className="card-header-clean">
                  <div>
                    <h4>Export Shipments Register</h4>
                    <p className="card-sub">Total {exportsReport.total_shipments} shipments</p>
                  </div>
                </div>

                <div className="table-responsive">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Reference</th>
                        <th>Exporter</th>
                        <th>Consignee</th>
                        <th>Destination</th>
                        <th>Mode</th>
                        <th>Workflow Stage</th>
                        <th>Readiness Status</th>
                        <th>Est. Departure</th>
                        <th>Gross Wt (KG)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {exportsReport.shipments.length === 0 ? (
                        <tr>
                          <td colSpan="9" className="empty-td">
                            No export shipments recorded yet.
                          </td>
                        </tr>
                      ) : (
                        exportsReport.shipments.map((s) => (
                          <tr key={s.id}>
                            <td className="font-mono font-bold">{s.reference}</td>
                            <td>{s.exporter_name}</td>
                            <td>{s.consignee_name}</td>
                            <td>
                              <span className="flag-tag">{s.destination_country}</span>
                            </td>
                            <td>{s.transport_mode}</td>
                            <td>
                              <span className={`status-pill status-${s.workflow_status}`}>
                                {s.workflow_status}
                              </span>
                            </td>
                            <td>
                              <span
                                className={`readiness-pill readiness-${s.readiness_status}`}
                              >
                                {s.readiness_status}
                              </span>
                            </td>
                            <td>{s.estimated_departure_date || '—'}</td>
                            <td>{new Intl.NumberFormat().format(s.gross_weight_kg)}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          ) : null}
        </div>
      )}
    </div>
  )
}
