import { useEffect, useState, useMemo } from 'react'
import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  Banknote,
  Building2,
  Calendar,
  CheckCircle2,
  Clock,
  CreditCard,
  DollarSign,
  Download,
  Eye,
  FileCheck2,
  FileMinus,
  FilePlus,
  FileSpreadsheet,
  FileText,
  Filter,
  History,
  Info,
  Lock,
  Plus,
  Printer,
  Receipt,
  RefreshCw,
  Search,
  Shield,
  ShieldAlert,
  SlidersHorizontal,
  Trash2,
  UserCheck,
  Users,
  X,
  XCircle,
} from 'lucide-react'
import { apiFetch } from './api'

export default function InvoicingView() {
  const [activeTab, setActiveTab] = useState('invoices') // 'invoices' | 'payments' | 'credit_notes' | 'aging' | 'gst_summary'
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

  // Master Data caches
  const [customers, setCustomers] = useState([])
  const [products, setProducts] = useState([])

  // Invoices state
  const [invoices, setInvoices] = useState([])
  const [invoicesLoading, setInvoicesLoading] = useState(false)
  const [invoiceSearch, setInvoiceSearch] = useState('')
  const [invoiceStatusFilter, setInvoiceStatusFilter] = useState('all')
  const [selectedInvoice, setSelectedInvoice] = useState(null)
  const [isNewInvoiceModalOpen, setIsNewInvoiceModalOpen] = useState(false)

  // Payments state
  const [payments, setPayments] = useState([])
  const [paymentsLoading, setPaymentsLoading] = useState(false)
  const [isRecordPaymentModalOpen, setIsRecordPaymentModalOpen] = useState(false)
  const [isAllocateModalOpen, setIsAllocateModalOpen] = useState(false)
  const [selectedPaymentForAlloc, setSelectedPaymentForAlloc] = useState(null)
  const [allocInvoiceId, setAllocInvoiceId] = useState('')
  const [allocAmount, setAllocAmount] = useState('')

  // Credit Notes state
  const [creditNotes, setCreditNotes] = useState([])
  const [creditNotesLoading, setCreditNotesLoading] = useState(false)
  const [isNewCreditNoteModalOpen, setIsNewCreditNoteModalOpen] = useState(false)

  // Reports state
  const [agingReport, setAgingReport] = useState(null)
  const [agingLoading, setAgingLoading] = useState(false)
  const [gstReport, setGstReport] = useState(null)
  const [gstLoading, setGstLoading] = useState(false)

  // Notifications
  const [errorMessage, setErrorMessage] = useState(null)
  const [successMessage, setSuccessMessage] = useState(null)

  // New Invoice Form
  const [newInvoiceForm, setNewInvoiceForm] = useState({
    customer_id: '',
    place_of_supply: '19-West Bengal',
    invoice_date: new Date().toISOString().slice(0, 10),
    due_date: new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10),
    currency: 'INR',
    exchange_rate: 1.0,
    tax_scheme: 'GST',
    lut_bond_number: '',
    payment_terms: 'Net 30',
    notes: '',
    items: [
      {
        product_id: '',
        product_sku: '',
        description: '',
        hsn_code: '',
        uom: 'PCS',
        quantity: 1,
        unit_price: 0,
        discount_pct: 0,
        tax_classification: 'taxable',
        gst_rate_pct: 18.0,
      },
    ],
  })

  // New Payment Form
  const [newPaymentForm, setNewPaymentForm] = useState({
    customer_id: '',
    payment_date: new Date().toISOString().slice(0, 10),
    payment_method: 'bank_transfer',
    reference_number: '',
    currency: 'INR',
    exchange_rate: 1.0,
    amount: '',
    notes: '',
  })

  // New Credit Note Form
  const [newCreditNoteForm, setNewCreditNoteForm] = useState({
    invoice_id: '',
    reason: 'goods_return',
    notes: '',
    items: [
      {
        product_sku: '',
        description: '',
        quantity: 1,
        unit_price: 0,
        gst_rate_pct: 0,
      },
    ],
  })

  useEffect(() => {
    fetchCustomers()
    fetchProducts()
    fetchInvoices()
  }, [])

  useEffect(() => {
    if (activeTab === 'invoices') fetchInvoices()
    else if (activeTab === 'payments') fetchPayments()
    else if (activeTab === 'credit_notes') fetchCreditNotes()
    else if (activeTab === 'aging') fetchAgingReport()
    else if (activeTab === 'gst_summary') fetchGstReport()
  }, [activeTab])

  // Clear messages
  useEffect(() => {
    if (successMessage) {
      const t = setTimeout(() => setSuccessMessage(null), 5000)
      return () => clearTimeout(t)
    }
  }, [successMessage])

  async function fetchCustomers() {
    try {
      const data = await apiFetch('/api/customers', { headers: authHeaders }, 'Failed to fetch customers')
      setCustomers(data || [])
      if (data?.length > 0 && !newInvoiceForm.customer_id) {
        setNewInvoiceForm((f) => ({ ...f, customer_id: data[0].id }))
        setNewPaymentForm((f) => ({ ...f, customer_id: data[0].id }))
      }
    } catch (err) {
      console.error(err)
    }
  }

  async function fetchProducts() {
    try {
      const data = await apiFetch('/api/products', { headers: authHeaders }, 'Failed to fetch products')
      setProducts(data || [])
    } catch (err) {
      console.error(err)
    }
  }

  async function fetchInvoices() {
    setInvoicesLoading(true)
    setErrorMessage(null)
    try {
      const data = await apiFetch('/api/finance/invoices', { headers: authHeaders }, 'Failed to fetch invoices')
      setInvoices(data || [])
    } catch (err) {
      setErrorMessage(err.message)
    } finally {
      setInvoicesLoading(false)
    }
  }

  async function fetchInvoiceDetail(id) {
    try {
      const data = await apiFetch(`/api/finance/invoices/${id}`, { headers: authHeaders }, 'Failed to fetch invoice detail')
      setSelectedInvoice(data)
    } catch (err) {
      setErrorMessage(err.message)
    }
  }

  async function fetchPayments() {
    setPaymentsLoading(true)
    try {
      const data = await apiFetch('/api/finance/payments', { headers: authHeaders }, 'Failed to fetch payments')
      setPayments(data || [])
    } catch (err) {
      setErrorMessage(err.message)
    } finally {
      setPaymentsLoading(false)
    }
  }

  async function fetchCreditNotes() {
    setCreditNotesLoading(true)
    try {
      const data = await apiFetch('/api/finance/credit-notes', { headers: authHeaders }, 'Failed to fetch credit notes')
      setCreditNotes(data || [])
    } catch (err) {
      setErrorMessage(err.message)
    } finally {
      setCreditNotesLoading(false)
    }
  }

  async function fetchAgingReport() {
    setAgingLoading(true)
    try {
      const data = await apiFetch('/api/finance/reports/receivables-aging', { headers: authHeaders }, 'Failed to fetch aging')
      setAgingReport(data)
    } catch (err) {
      setErrorMessage(err.message)
    } finally {
      setAgingLoading(false)
    }
  }

  async function fetchGstReport() {
    setGstLoading(true)
    try {
      const data = await apiFetch('/api/finance/reports/gst-outward', { headers: authHeaders }, 'Failed to fetch GST report')
      setGstReport(data)
    } catch (err) {
      setErrorMessage(err.message)
    } finally {
      setGstLoading(false)
    }
  }

  // Invoice Handlers
  async function handleCreateInvoice(e) {
    e.preventDefault()
    setErrorMessage(null)
    try {
      const payload = {
        ...newInvoiceForm,
        exchange_rate: Number(newInvoiceForm.exchange_rate) || 1.0,
        items: newInvoiceForm.items.map((it) => ({
          ...it,
          quantity: Number(it.quantity) || 1,
          unit_price: Number(it.unit_price) || 0,
          discount_pct: Number(it.discount_pct) || 0,
          gst_rate_pct: Number(it.gst_rate_pct) || 0,
        })),
      }

      const created = await apiFetch(
        '/api/finance/invoices',
        {
          method: 'POST',
          headers: { ...authHeaders, 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
        'Failed to create invoice'
      )
      setSuccessMessage(`Invoice ${created.invoice_number} created in draft state.`)
      setIsNewInvoiceModalOpen(false)
      fetchInvoices()
      fetchInvoiceDetail(created.id)
    } catch (err) {
      setErrorMessage(err.message)
    }
  }

  async function handleStatusTransition(invoiceId, targetStatus) {
    setErrorMessage(null)
    try {
      const updated = await apiFetch(
        `/api/finance/invoices/${invoiceId}/status`,
        {
          method: 'POST',
          headers: { ...authHeaders, 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: targetStatus, reason: `Status updated by ${operatorEmail}` }),
        },
        'Failed to update invoice status'
      )
      setSuccessMessage(`Invoice ${updated.invoice_number} marked as ${updated.status}.`)
      fetchInvoiceDetail(invoiceId)
      fetchInvoices()
    } catch (err) {
      setErrorMessage(err.message)
    }
  }

  // Payment Handlers
  async function handleRecordPayment(e) {
    e.preventDefault()
    setErrorMessage(null)
    try {
      const payload = {
        ...newPaymentForm,
        amount: Number(newPaymentForm.amount),
        exchange_rate: Number(newPaymentForm.exchange_rate) || 1.0,
      }
      const created = await apiFetch(
        '/api/finance/payments',
        {
          method: 'POST',
          headers: { ...authHeaders, 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
        'Failed to record payment'
      )
      setSuccessMessage(`Payment ${created.payment_number} recorded. Available for allocation: ${created.currency} ${created.unallocated_amount}.`)
      setIsRecordPaymentModalOpen(false)
      fetchPayments()
    } catch (err) {
      setErrorMessage(err.message)
    }
  }

  async function handleAllocatePayment(e) {
    e.preventDefault()
    if (!selectedPaymentForAlloc || !allocInvoiceId || !allocAmount) return
    setErrorMessage(null)
    try {
      await apiFetch(
        `/api/finance/payments/${selectedPaymentForAlloc.id}/allocate`,
        {
          method: 'POST',
          headers: { ...authHeaders, 'Content-Type': 'application/json' },
          body: JSON.stringify({ invoice_id: allocInvoiceId, amount: Number(allocAmount) }),
        },
        'Failed to allocate payment'
      )
      setSuccessMessage('Payment allocated successfully to invoice.')
      setIsAllocateModalOpen(false)
      fetchPayments()
      if (selectedInvoice?.id === allocInvoiceId) {
        fetchInvoiceDetail(allocInvoiceId)
      }
    } catch (err) {
      setErrorMessage(err.message)
    }
  }

  // Credit Note Handlers
  async function handleCreateCreditNote(e) {
    e.preventDefault()
    setErrorMessage(null)
    try {
      const payload = {
        ...newCreditNoteForm,
        items: newCreditNoteForm.items.map((it) => ({
          ...it,
          quantity: Number(it.quantity) || 1,
          unit_price: Number(it.unit_price) || 0,
          gst_rate_pct: Number(it.gst_rate_pct) || 0,
        })),
      }
      const created = await apiFetch(
        '/api/finance/credit-notes',
        {
          method: 'POST',
          headers: { ...authHeaders, 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
        'Failed to issue credit note'
      )
      setSuccessMessage(`Credit Note ${created.credit_note_number} issued for ${created.currency} ${created.grand_total}.`)
      setIsNewCreditNoteModalOpen(false)
      fetchCreditNotes()
      if (selectedInvoice?.id === newCreditNoteForm.invoice_id) {
        fetchInvoiceDetail(newCreditNoteForm.invoice_id)
      }
    } catch (err) {
      setErrorMessage(err.message)
    }
  }

  const filteredInvoices = useMemo(() => {
    return invoices.filter((inv) => {
      const matchesSearch =
        (inv.invoice_number || '').toLowerCase().includes(invoiceSearch.toLowerCase()) ||
        (inv.customer_name || '').toLowerCase().includes(invoiceSearch.toLowerCase()) ||
        (inv.place_of_supply || '').toLowerCase().includes(invoiceSearch.toLowerCase())
      const matchesStatus = invoiceStatusFilter === 'all' || inv.status === invoiceStatusFilter
      return matchesSearch && matchesStatus
    })
  }, [invoices, invoiceSearch, invoiceStatusFilter])

  return (
    <div className="invoicing-view p-6 bg-slate-900 text-slate-100 min-h-screen">
      {/* Header & Subtitle */}
      <div className="flex flex-wrap items-center justify-between pb-6 border-b border-slate-800 gap-4">
        <div>
          <div className="flex items-center gap-3">
            <Receipt className="w-8 h-8 text-emerald-400" />
            <h1 className="text-2xl font-bold tracking-tight text-white">Commercial Invoicing & Indian GST Billing</h1>
            <span className="text-xs uppercase px-2.5 py-0.5 rounded-full font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              Phase 6
            </span>
          </div>
          <p className="text-sm text-slate-400 mt-1">
            Compliant Indian GST invoicing (CGST+SGST / IGST / LUT Zero-Rated), multi-currency, payment allocation, and aging.
          </p>
        </div>

        {/* Role & Context Selector */}
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
            className="bg-slate-900 border border-slate-700 text-xs rounded-lg px-2.5 py-1.5 text-slate-200 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          >
            <option value="admin">Role: Admin</option>
            <option value="manager">Role: Manager</option>
            <option value="operator">Role: Operator</option>
            <option value="sales">Role: Sales</option>
            <option value="viewer">Role: Viewer (Read-only)</option>
          </select>
        </div>
      </div>

      {/* Navigation Sub-Tabs */}
      <div className="flex items-center gap-2 mt-6 border-b border-slate-800 pb-3 flex-wrap">
        <button
          onClick={() => {
            setActiveTab('invoices')
            setSelectedInvoice(null)
          }}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition ${
            activeTab === 'invoices'
              ? 'bg-emerald-600 text-white shadow-lg shadow-emerald-600/20'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          <FileText className="w-4 h-4" />
          Customer Invoices ({invoices.length})
        </button>

        <button
          onClick={() => setActiveTab('payments')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition ${
            activeTab === 'payments'
              ? 'bg-emerald-600 text-white shadow-lg shadow-emerald-600/20'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          <Banknote className="w-4 h-4" />
          Payments & Allocation ({payments.length})
        </button>

        <button
          onClick={() => setActiveTab('credit_notes')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition ${
            activeTab === 'credit_notes'
              ? 'bg-emerald-600 text-white shadow-lg shadow-emerald-600/20'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          <FileMinus className="w-4 h-4" />
          Credit Notes ({creditNotes.length})
        </button>

        <button
          onClick={() => setActiveTab('aging')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition ${
            activeTab === 'aging'
              ? 'bg-emerald-600 text-white shadow-lg shadow-emerald-600/20'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          <Clock className="w-4 h-4" />
          Receivables & Aging
        </button>

        <button
          onClick={() => setActiveTab('gst_summary')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition ${
            activeTab === 'gst_summary'
              ? 'bg-emerald-600 text-white shadow-lg shadow-emerald-600/20'
              : 'bg-slate-800 text-slate-400 hover:text-white'
          }`}
        >
          <FileSpreadsheet className="w-4 h-4" />
          GST Outward Supplies (GSTR-1)
        </button>
      </div>

      {/* Notifications */}
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

      {/* ======================================================== */}
      {/* TAB 1: INVOICES LIST & DETAIL VIEW */}
      {/* ======================================================== */}
      {activeTab === 'invoices' && !selectedInvoice && (
        <div className="mt-6 space-y-4">
          {/* Controls bar */}
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3 flex-1 min-w-[300px]">
              <div className="relative flex-1">
                <Search className="w-4 h-4 absolute left-3 top-3 text-slate-400" />
                <input
                  type="text"
                  placeholder="Search by invoice #, customer name, POS state..."
                  value={invoiceSearch}
                  onChange={(e) => setInvoiceSearch(e.target.value)}
                  className="w-full bg-slate-800/80 border border-slate-700/80 rounded-xl pl-9 pr-4 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500"
                />
              </div>

              <div className="flex items-center gap-2 bg-slate-800/80 border border-slate-700/80 rounded-xl px-3 py-2">
                <Filter className="w-4 h-4 text-slate-400" />
                <select
                  value={invoiceStatusFilter}
                  onChange={(e) => setInvoiceStatusFilter(e.target.value)}
                  className="bg-transparent text-sm text-slate-200 focus:outline-none"
                >
                  <option value="all">All Statuses</option>
                  <option value="draft">Draft</option>
                  <option value="approved">Approved</option>
                  <option value="issued">Issued / Unpaid</option>
                  <option value="partially_paid">Partially Paid</option>
                  <option value="paid">Paid</option>
                  <option value="overdue">Overdue</option>
                  <option value="credited">Credited</option>
                  <option value="cancelled">Cancelled</option>
                </select>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={fetchInvoices}
                disabled={invoicesLoading}
                className="p-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition"
                title="Refresh invoices"
              >
                <RefreshCw className={`w-4 h-4 ${invoicesLoading ? 'animate-spin' : ''}`} />
              </button>

              <button
                onClick={() => setIsNewInvoiceModalOpen(true)}
                disabled={currentRole === 'viewer'}
                className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-xl text-sm font-semibold shadow-lg shadow-emerald-600/20 transition"
              >
                <Plus className="w-4 h-4" />
                <span>Create New Invoice</span>
              </button>
            </div>
          </div>

          {/* Invoices Table */}
          <div className="border border-slate-800 rounded-2xl bg-slate-800/40 backdrop-blur overflow-hidden shadow-xl">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-slate-800/80 text-xs uppercase tracking-wider text-slate-400 border-b border-slate-700/80">
                  <tr>
                    <th className="px-6 py-4">Invoice #</th>
                    <th className="px-6 py-4">Date / Due</th>
                    <th className="px-6 py-4">Customer</th>
                    <th className="px-6 py-4">Place of Supply</th>
                    <th className="px-6 py-4">Tax Scheme</th>
                    <th className="px-6 py-4">Grand Total</th>
                    <th className="px-6 py-4">Outstanding</th>
                    <th className="px-6 py-4">Status</th>
                    <th className="px-6 py-4 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/80">
                  {invoicesLoading && invoices.length === 0 ? (
                    <tr>
                      <td colSpan="9" className="px-6 py-12 text-center text-slate-400">
                        <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-emerald-400" />
                        Loading commercial invoices...
                      </td>
                    </tr>
                  ) : filteredInvoices.length === 0 ? (
                    <tr>
                      <td colSpan="9" className="px-6 py-12 text-center text-slate-400">
                        No customer invoices found matching criteria.
                      </td>
                    </tr>
                  ) : (
                    filteredInvoices.map((inv) => (
                      <tr key={inv.id} className="hover:bg-slate-800/60 transition group">
                        <td className="px-6 py-4 font-mono font-medium text-white flex items-center gap-2">
                          <Receipt className="w-4 h-4 text-emerald-400" />
                          <span>{inv.invoice_number}</span>
                        </td>
                        <td className="px-6 py-4 text-slate-300">
                          <div>{inv.invoice_date}</div>
                          <div className="text-xs text-slate-500">Due: {inv.due_date}</div>
                        </td>
                        <td className="px-6 py-4 text-slate-200 font-medium">{inv.customer_name}</td>
                        <td className="px-6 py-4 text-slate-400 text-xs">{inv.place_of_supply}</td>
                        <td className="px-6 py-4">
                          <span className="px-2 py-0.5 rounded text-[10px] uppercase font-mono bg-slate-800 border border-slate-700 text-slate-300">
                            {inv.tax_scheme}
                          </span>
                        </td>
                        <td className="px-6 py-4 font-mono font-bold text-white">
                          {inv.currency} {inv.grand_total?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                        </td>
                        <td className="px-6 py-4 font-mono">
                          <span
                            className={
                              inv.outstanding_balance > 0 ? 'text-amber-400 font-bold' : 'text-emerald-400'
                            }
                          >
                            {inv.currency} {inv.outstanding_balance?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                          </span>
                        </td>
                        <td className="px-6 py-4">
                          <InvoiceStatusBadge status={inv.status} />
                        </td>
                        <td className="px-6 py-4 text-right">
                          <button
                            onClick={() => fetchInvoiceDetail(inv.id)}
                            className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-emerald-400 hover:text-white rounded-lg text-xs font-medium border border-slate-700 transition"
                          >
                            View &rarr;
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
      )}

      {/* Invoice Detail Workspace */}
      {activeTab === 'invoices' && selectedInvoice && (
        <div className="mt-6 space-y-6">
          {/* Top Bar with Status Controls */}
          <div className="flex flex-wrap items-center justify-between gap-4 bg-slate-800/80 p-4 rounded-2xl border border-slate-700/80">
            <div className="flex items-center gap-4">
              <button
                onClick={() => setSelectedInvoice(null)}
                className="px-3 py-2 rounded-xl bg-slate-700/60 hover:bg-slate-700 text-slate-300 text-xs font-semibold flex items-center gap-1.5 transition"
              >
                &larr; Back to Invoices
              </button>
              <div>
                <div className="flex items-center gap-3">
                  <h2 className="text-xl font-bold text-white font-mono">{selectedInvoice.invoice_number}</h2>
                  <InvoiceStatusBadge status={selectedInvoice.status} />
                  {selectedInvoice.is_posted === 1 && (
                    <span className="px-2 py-0.5 rounded text-[10px] bg-sky-500/10 text-sky-400 border border-sky-500/20 font-semibold">
                      Posted / Locked
                    </span>
                  )}
                </div>
                <div className="text-xs text-slate-400 mt-1 flex items-center gap-4">
                  <span>Customer: <strong>{selectedInvoice.customer_name}</strong></span>
                  <span>Date: <strong>{selectedInvoice.invoice_date}</strong></span>
                  <span>Due: <strong>{selectedInvoice.due_date}</strong></span>
                </div>
              </div>
            </div>

            {/* Actions for Status Lifecycle */}
            <div className="flex items-center gap-2 flex-wrap">
              {selectedInvoice.status === 'draft' && (
                <>
                  <button
                    onClick={() => handleStatusTransition(selectedInvoice.id, 'approved')}
                    disabled={currentRole === 'viewer'}
                    className="px-3 py-1.5 bg-sky-600 hover:bg-sky-500 text-white rounded-lg text-xs font-semibold"
                  >
                    Approve Invoice
                  </button>
                  <button
                    onClick={() => handleStatusTransition(selectedInvoice.id, 'issued')}
                    disabled={currentRole === 'viewer'}
                    className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold shadow"
                  >
                    Issue / Post Invoice
                  </button>
                </>
              )}

              {selectedInvoice.status === 'approved' && (
                <button
                  onClick={() => handleStatusTransition(selectedInvoice.id, 'issued')}
                  disabled={currentRole === 'viewer'}
                  className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold shadow"
                >
                  Issue Invoice
                </button>
              )}

              {['draft', 'approved', 'issued'].includes(selectedInvoice.status) && selectedInvoice.amount_paid === 0 && (
                <button
                  onClick={() => {
                    const r = window.prompt('Enter cancellation reason:')
                    if (r) handleStatusTransition(selectedInvoice.id, 'cancelled')
                  }}
                  disabled={currentRole === 'viewer'}
                  className="px-3 py-1.5 bg-rose-600/80 hover:bg-rose-600 text-white rounded-lg text-xs font-semibold"
                >
                  Cancel Invoice
                </button>
              )}

              <button
                onClick={() => window.print()}
                className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg text-xs font-semibold flex items-center gap-1.5"
              >
                <Printer className="w-3.5 h-3.5" />
                Print / Export
              </button>
            </div>
          </div>

          {/* Statutory Compliance Notice Banner */}
          <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-200 text-xs flex items-start gap-3">
            <Info className="w-5 h-5 flex-shrink-0 text-amber-400 mt-0.5" />
            <div>
              <strong className="block text-amber-300 font-semibold mb-0.5">STATUTORY BILLING NOTICE</strong>
              {selectedInvoice.statutory_notice}
            </div>
          </div>

          {/* Invoice Summary Details */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="bg-slate-800/40 p-4 rounded-xl border border-slate-700/80">
              <span className="text-xs text-slate-400 block font-medium">Grand Total</span>
              <span className="text-xl font-bold font-mono text-white mt-1 block">
                {selectedInvoice.currency} {selectedInvoice.grand_total?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </span>
              {selectedInvoice.currency !== 'INR' && (
                <span className="text-xs text-slate-400 font-mono mt-0.5 block">
                  ≈ INR {selectedInvoice.base_grand_total?.toLocaleString()} (Rate: {selectedInvoice.exchange_rate})
                </span>
              )}
            </div>

            <div className="bg-slate-800/40 p-4 rounded-xl border border-slate-700/80">
              <span className="text-xs text-slate-400 block font-medium">Outstanding Balance</span>
              <span
                className={`text-xl font-bold font-mono mt-1 block ${
                  selectedInvoice.outstanding_balance > 0 ? 'text-amber-400' : 'text-emerald-400'
                }`}
              >
                {selectedInvoice.currency} {selectedInvoice.outstanding_balance?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </span>
              <span className="text-xs text-slate-500 mt-0.5 block">
                Paid: {selectedInvoice.currency} {selectedInvoice.amount_paid?.toLocaleString()}
              </span>
            </div>

            <div className="bg-slate-800/40 p-4 rounded-xl border border-slate-700/80">
              <span className="text-xs text-slate-400 block font-medium">Place of Supply</span>
              <span className="text-sm font-bold text-white mt-1 block">{selectedInvoice.place_of_supply}</span>
              <span className="text-xs text-slate-500 mt-0.5 block">Tax Scheme: {selectedInvoice.tax_scheme}</span>
            </div>

            <div className="bg-slate-800/40 p-4 rounded-xl border border-slate-700/80">
              <span className="text-xs text-slate-400 block font-medium">Seller / Customer GSTIN</span>
              <span className="text-xs text-slate-300 font-mono mt-1 block">Seller: {selectedInvoice.supplier_tax_id}</span>
              <span className="text-xs text-slate-400 font-mono mt-0.5 block">
                Buyer: {selectedInvoice.customer_tax_id || 'Unregistered / Export'}
              </span>
            </div>
          </div>

          {/* Line Items Table with GST Breakdown */}
          <div className="bg-slate-800/40 border border-slate-700/80 rounded-2xl p-6 backdrop-blur space-y-4">
            <h3 className="text-sm font-bold text-white uppercase tracking-wider flex items-center gap-2 border-b border-slate-700/60 pb-3">
              <FileSpreadsheet className="w-4 h-4 text-emerald-400" />
              Invoice Line Items & GST Breakdown
            </h3>

            <div className="border border-slate-800 rounded-xl overflow-hidden bg-slate-900/60">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-800/80 uppercase text-slate-400">
                  <tr>
                    <th className="px-4 py-3">SKU & Description</th>
                    <th className="px-4 py-3">HSN/SAC</th>
                    <th className="px-4 py-3 text-right">Qty</th>
                    <th className="px-4 py-3 text-right">Unit Price</th>
                    <th className="px-4 py-3 text-right">Taxable</th>
                    <th className="px-4 py-3 text-right">CGST</th>
                    <th className="px-4 py-3 text-right">SGST</th>
                    <th className="px-4 py-3 text-right">IGST</th>
                    <th className="px-4 py-3 text-right">Line Total</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {selectedInvoice.items?.map((it) => (
                    <tr key={it.id} className="hover:bg-slate-800/40">
                      <td className="px-4 py-3">
                        <span className="font-mono font-medium text-white block">{it.product_sku}</span>
                        <span className="text-slate-400 text-[11px]">{it.description}</span>
                      </td>
                      <td className="px-4 py-3 font-mono text-slate-400">{it.hsn_code || '—'}</td>
                      <td className="px-4 py-3 text-right font-mono text-slate-200">
                        {it.quantity} {it.uom}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-slate-200">
                        {it.unit_price?.toFixed(2)}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-slate-100 font-semibold">
                        {it.taxable_amount?.toFixed(2)}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-slate-300">
                        {it.cgst_amount > 0 ? `${it.cgst_amount.toFixed(2)} (${it.cgst_rate_pct}%)` : '—'}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-slate-300">
                        {it.sgst_amount > 0 ? `${it.sgst_amount.toFixed(2)} (${it.sgst_rate_pct}%)` : '—'}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-slate-300">
                        {it.igst_amount > 0 ? `${it.igst_amount.toFixed(2)} (${it.igst_rate_pct}%)` : '—'}
                      </td>
                      <td className="px-4 py-3 text-right font-mono font-bold text-white">
                        {it.line_total?.toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot className="bg-slate-800/60 font-mono text-xs border-t border-slate-700">
                  <tr>
                    <td colSpan="4" className="px-4 py-2 text-right uppercase text-slate-400">Totals:</td>
                    <td className="px-4 py-2 text-right text-slate-200 font-bold">{selectedInvoice.subtotal?.toFixed(2)}</td>
                    <td className="px-4 py-2 text-right text-slate-300">{selectedInvoice.cgst_total?.toFixed(2)}</td>
                    <td className="px-4 py-2 text-right text-slate-300">{selectedInvoice.sgst_total?.toFixed(2)}</td>
                    <td className="px-4 py-2 text-right text-slate-300">{selectedInvoice.igst_total?.toFixed(2)}</td>
                    <td className="px-4 py-2 text-right text-emerald-400 font-bold">{selectedInvoice.grand_total?.toFixed(2)}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>

          {/* Payment Allocations & Credit Notes for this Invoice */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="bg-slate-800/40 border border-slate-700/80 rounded-2xl p-6 backdrop-blur space-y-3">
              <h4 className="text-sm font-bold text-white flex items-center gap-2 border-b border-slate-700/60 pb-3">
                <Banknote className="w-4 h-4 text-emerald-400" />
                Payments Allocated to this Invoice
              </h4>
              <div className="space-y-2">
                {!selectedInvoice.allocations || selectedInvoice.allocations.length === 0 ? (
                  <div className="text-slate-500 text-xs py-4 text-center">No payment allocations recorded.</div>
                ) : (
                  selectedInvoice.allocations.map((a) => (
                    <div key={a.id} className="p-3 bg-slate-900/60 rounded-xl border border-slate-800 text-xs flex justify-between items-center">
                      <div>
                        <span className="font-mono font-bold text-white block">{a.payment_number}</span>
                        <span className="text-slate-400 text-[11px]">
                          {a.payment_method?.toUpperCase()} • Ref: {a.reference_number || 'N/A'}
                        </span>
                      </div>
                      <span className="font-mono font-bold text-emerald-400">
                        +{selectedInvoice.currency} {a.allocated_amount?.toFixed(2)}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>

            <div className="bg-slate-800/40 border border-slate-700/80 rounded-2xl p-6 backdrop-blur space-y-3">
              <h4 className="text-sm font-bold text-white flex items-center gap-2 border-b border-slate-700/60 pb-3">
                <FileMinus className="w-4 h-4 text-amber-400" />
                Credit Notes Deducted
              </h4>
              <div className="space-y-2">
                {!selectedInvoice.credit_notes || selectedInvoice.credit_notes.length === 0 ? (
                  <div className="text-slate-500 text-xs py-4 text-center">No credit notes issued.</div>
                ) : (
                  selectedInvoice.credit_notes.map((c) => (
                    <div key={c.id} className="p-3 bg-slate-900/60 rounded-xl border border-slate-800 text-xs flex justify-between items-center">
                      <div>
                        <span className="font-mono font-bold text-white block">{c.credit_note_number}</span>
                        <span className="text-slate-400 text-[11px] capitalize">{c.reason?.replace(/_/g, ' ')}</span>
                      </div>
                      <span className="font-mono font-bold text-rose-400">
                        -{selectedInvoice.currency} {c.grand_total?.toFixed(2)}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* TAB 2: PAYMENTS LIST & ALLOCATION */}
      {/* ======================================================== */}
      {activeTab === 'payments' && (
        <div className="mt-6 space-y-4">
          <div className="flex justify-between items-center">
            <h3 className="text-base font-bold text-white">Recorded Customer Payments</h3>
            <button
              onClick={() => setIsRecordPaymentModalOpen(true)}
              disabled={currentRole === 'viewer'}
              className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-sm font-semibold shadow"
            >
              <Plus className="w-4 h-4" />
              <span>Record New Payment</span>
            </button>
          </div>

          <div className="border border-slate-800 rounded-2xl bg-slate-800/40 overflow-hidden shadow-xl">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-800/80 text-xs uppercase text-slate-400 border-b border-slate-700/80">
                <tr>
                  <th className="px-6 py-4">Payment #</th>
                  <th className="px-6 py-4">Date</th>
                  <th className="px-6 py-4">Customer</th>
                  <th className="px-6 py-4">Method & Ref</th>
                  <th className="px-6 py-4">Total Amount</th>
                  <th className="px-6 py-4">Allocated</th>
                  <th className="px-6 py-4">Unallocated Balance</th>
                  <th className="px-6 py-4 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {paymentsLoading ? (
                  <tr>
                    <td colSpan="8" className="px-6 py-8 text-center text-slate-500">Loading payments...</td>
                  </tr>
                ) : payments.length === 0 ? (
                  <tr>
                    <td colSpan="8" className="px-6 py-8 text-center text-slate-500">No customer payments recorded yet.</td>
                  </tr>
                ) : (
                  payments.map((p) => (
                    <tr key={p.id} className="hover:bg-slate-800/60">
                      <td className="px-6 py-4 font-mono font-medium text-white">{p.payment_number}</td>
                      <td className="px-6 py-4 text-slate-300">{p.payment_date}</td>
                      <td className="px-6 py-4 text-white font-medium">{p.customer_name}</td>
                      <td className="px-6 py-4 text-slate-400 text-xs">
                        <span className="uppercase font-semibold text-slate-300 block">{p.payment_method?.replace(/_/g, ' ')}</span>
                        {p.reference_number && <span>Ref: {p.reference_number}</span>}
                      </td>
                      <td className="px-6 py-4 font-mono font-bold text-white">
                        {p.currency} {p.amount?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                      </td>
                      <td className="px-6 py-4 font-mono text-slate-300">
                        {p.currency} {p.allocated_amount?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                      </td>
                      <td className="px-6 py-4 font-mono">
                        <span className={p.unallocated_amount > 0 ? 'text-amber-400 font-bold' : 'text-slate-500'}>
                          {p.currency} {p.unallocated_amount?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-right">
                        {p.unallocated_amount > 0 && (
                          <button
                            onClick={() => {
                              setSelectedPaymentForAlloc(p)
                              setAllocAmount(p.unallocated_amount.toString())
                              setIsAllocateModalOpen(true)
                            }}
                            disabled={currentRole === 'viewer'}
                            className="px-3 py-1.5 bg-sky-600 hover:bg-sky-500 text-white rounded-lg text-xs font-semibold"
                          >
                            Allocate to Invoice &rarr;
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

      {/* ======================================================== */}
      {/* TAB 3: CREDIT NOTES LIST */}
      {/* ======================================================== */}
      {activeTab === 'credit_notes' && (
        <div className="mt-6 space-y-4">
          <div className="flex justify-between items-center">
            <h3 className="text-base font-bold text-white">Issued Customer Credit Notes</h3>
            <button
              onClick={() => setIsNewCreditNoteModalOpen(true)}
              disabled={currentRole === 'viewer'}
              className="flex items-center gap-2 px-4 py-2 bg-amber-600 hover:bg-amber-500 text-white rounded-xl text-sm font-semibold shadow"
            >
              <Plus className="w-4 h-4" />
              <span>Issue Credit Note</span>
            </button>
          </div>

          <div className="border border-slate-800 rounded-2xl bg-slate-800/40 overflow-hidden shadow-xl">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-800/80 text-xs uppercase text-slate-400 border-b border-slate-700/80">
                <tr>
                  <th className="px-6 py-4">Credit Note #</th>
                  <th className="px-6 py-4">Date</th>
                  <th className="px-6 py-4">Customer</th>
                  <th className="px-6 py-4">Reason</th>
                  <th className="px-6 py-4">Subtotal</th>
                  <th className="px-6 py-4">GST Reversed</th>
                  <th className="px-6 py-4">Grand Total</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {creditNotesLoading ? (
                  <tr>
                    <td colSpan="7" className="px-6 py-8 text-center text-slate-500">Loading credit notes...</td>
                  </tr>
                ) : creditNotes.length === 0 ? (
                  <tr>
                    <td colSpan="7" className="px-6 py-8 text-center text-slate-500">No credit notes issued.</td>
                  </tr>
                ) : (
                  creditNotes.map((crn) => (
                    <tr key={crn.id} className="hover:bg-slate-800/60">
                      <td className="px-6 py-4 font-mono font-medium text-white">{crn.credit_note_number}</td>
                      <td className="px-6 py-4 text-slate-300">{crn.credit_note_date}</td>
                      <td className="px-6 py-4 text-white font-medium">{crn.customer_name}</td>
                      <td className="px-6 py-4 text-slate-300 capitalize text-xs">{crn.reason?.replace(/_/g, ' ')}</td>
                      <td className="px-6 py-4 font-mono text-slate-300">
                        {crn.currency} {crn.subtotal?.toFixed(2)}
                      </td>
                      <td className="px-6 py-4 font-mono text-slate-300">
                        {crn.currency} {crn.tax_total?.toFixed(2)}
                      </td>
                      <td className="px-6 py-4 font-mono font-bold text-rose-400">
                        {crn.currency} {crn.grand_total?.toFixed(2)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* TAB 4: RECEIVABLES & AGING REPORT */}
      {/* ======================================================== */}
      {activeTab === 'aging' && agingReport && (
        <div className="mt-6 space-y-6">
          <div className="flex justify-between items-center border-b border-slate-800 pb-4">
            <div>
              <h3 className="text-base font-bold text-white">Accounts Receivable Aging Analysis</h3>
              <p className="text-xs text-slate-400">Outstanding balances bucketed by days past payment due date.</p>
            </div>
            <span className="text-xs text-slate-400 font-mono">As of: {agingReport.as_of_date}</span>
          </div>

          {/* Aging Buckets Cards */}
          <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
            <div className="bg-slate-800/40 p-4 rounded-xl border border-slate-700/80">
              <span className="text-xs text-slate-400 block font-medium">Total Receivables</span>
              <span className="text-lg font-bold font-mono text-white mt-1 block">
                INR {agingReport.total_receivables_inr?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </span>
            </div>

            <div className="bg-emerald-500/10 p-4 rounded-xl border border-emerald-500/20">
              <span className="text-xs text-emerald-400 block font-medium">Current (Not Overdue)</span>
              <span className="text-lg font-bold font-mono text-emerald-300 mt-1 block">
                INR {agingReport.buckets?.current?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </span>
            </div>

            <div className="bg-amber-500/10 p-4 rounded-xl border border-amber-500/20">
              <span className="text-xs text-amber-400 block font-medium">1 – 30 Days Overdue</span>
              <span className="text-lg font-bold font-mono text-amber-300 mt-1 block">
                INR {agingReport.buckets?.days_1_30?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </span>
            </div>

            <div className="bg-orange-500/10 p-4 rounded-xl border border-orange-500/20">
              <span className="text-xs text-orange-400 block font-medium">31 – 60 Days Overdue</span>
              <span className="text-lg font-bold font-mono text-orange-300 mt-1 block">
                INR {agingReport.buckets?.days_31_60?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </span>
            </div>

            <div className="bg-rose-500/10 p-4 rounded-xl border border-rose-500/20">
              <span className="text-xs text-rose-400 block font-medium">90+ Days Overdue</span>
              <span className="text-lg font-bold font-mono text-rose-300 mt-1 block">
                INR {agingReport.buckets?.days_90_plus?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </span>
            </div>
          </div>

          {/* Customer Aging Breakdown Table */}
          <div className="border border-slate-800 rounded-2xl bg-slate-800/40 overflow-hidden shadow-xl">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-800/80 uppercase text-slate-400 border-b border-slate-700">
                <tr>
                  <th className="px-6 py-4">Customer Name</th>
                  <th className="px-6 py-4 text-right">Invoices</th>
                  <th className="px-6 py-4 text-right">Current</th>
                  <th className="px-6 py-4 text-right">1-30 Days</th>
                  <th className="px-6 py-4 text-right">31-60 Days</th>
                  <th className="px-6 py-4 text-right">61-90 Days</th>
                  <th className="px-6 py-4 text-right">90+ Days</th>
                  <th className="px-6 py-4 text-right">Total Outstanding</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {agingReport.customers?.length === 0 ? (
                  <tr>
                    <td colSpan="8" className="px-6 py-8 text-center text-slate-500">No overdue receivables found.</td>
                  </tr>
                ) : (
                  agingReport.customers?.map((c) => (
                    <tr key={c.customer_id} className="hover:bg-slate-800/60 font-mono">
                      <td className="px-6 py-4 font-sans font-medium text-white">{c.customer_name}</td>
                      <td className="px-6 py-4 text-right text-slate-400">{c.invoices_count}</td>
                      <td className="px-6 py-4 text-right text-emerald-400">{c.current?.toFixed(2)}</td>
                      <td className="px-6 py-4 text-right text-amber-400">{c.days_1_30?.toFixed(2)}</td>
                      <td className="px-6 py-4 text-right text-orange-400">{c.days_31_60?.toFixed(2)}</td>
                      <td className="px-6 py-4 text-right text-rose-300">{c.days_61_90?.toFixed(2)}</td>
                      <td className="px-6 py-4 text-right text-rose-500 font-bold">{c.days_90_plus?.toFixed(2)}</td>
                      <td className="px-6 py-4 text-right font-bold text-white">{c.total_outstanding_inr?.toFixed(2)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* TAB 5: GST OUTWARD SUPPLIES SUMMARY (GSTR-1) */}
      {/* ======================================================== */}
      {activeTab === 'gst_summary' && gstReport && (
        <div className="mt-6 space-y-6">
          <div className="flex justify-between items-center border-b border-slate-800 pb-4">
            <div>
              <h3 className="text-base font-bold text-white">GST Outward Supplies Statement (GSTR-1 Preparation)</h3>
              <p className="text-xs text-slate-400">Classified by intra-state, inter-state, and export tax treatments.</p>
            </div>
            <div className="text-xs text-emerald-400 font-bold font-mono">
              Total Tax Liability: INR {gstReport.total_tax_liability_inr?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </div>
          </div>

          <div className="p-4 rounded-xl bg-slate-800/60 border border-slate-700 text-xs text-slate-300 flex items-start gap-2">
            <Info className="w-4 h-4 text-emerald-400 flex-shrink-0 mt-0.5" />
            <span>{gstReport.statutory_notice}</span>
          </div>

          {/* GSTR-1 Breakdown Cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="bg-slate-800/40 p-5 rounded-2xl border border-slate-700/80 space-y-2">
              <span className="text-xs uppercase tracking-wider text-slate-400 block font-semibold">
                B2B Intra-State (West Bengal)
              </span>
              <div className="text-lg font-bold font-mono text-white">
                Taxable: INR {gstReport.b2b_intra_state?.taxable_value?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </div>
              <div className="text-xs text-slate-300 font-mono space-y-0.5">
                <div>CGST: INR {gstReport.b2b_intra_state?.cgst?.toFixed(2)}</div>
                <div>SGST: INR {gstReport.b2b_intra_state?.sgst?.toFixed(2)}</div>
              </div>
            </div>

            <div className="bg-slate-800/40 p-5 rounded-2xl border border-slate-700/80 space-y-2">
              <span className="text-xs uppercase tracking-wider text-slate-400 block font-semibold">
                B2B Inter-State Supplies
              </span>
              <div className="text-lg font-bold font-mono text-white">
                Taxable: INR {gstReport.b2b_inter_state?.taxable_value?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </div>
              <div className="text-xs text-slate-300 font-mono">
                <div>IGST: INR {gstReport.b2b_inter_state?.igst?.toFixed(2)}</div>
              </div>
            </div>

            <div className="bg-slate-800/40 p-5 rounded-2xl border border-slate-700/80 space-y-2">
              <span className="text-xs uppercase tracking-wider text-slate-400 block font-semibold">
                Zero-Rated Export Supplies (LUT)
              </span>
              <div className="text-lg font-bold font-mono text-white">
                FOB Value: INR {gstReport.export_supplies_under_lut?.taxable_value?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </div>
              <div className="text-xs text-emerald-400 font-mono">Tax Payable: INR 0.00 (LUT Bond)</div>
            </div>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* MODAL: Create New Invoice */}
      {/* ======================================================== */}
      {isNewInvoiceModalOpen && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl max-w-3xl w-full p-6 shadow-2xl space-y-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <Receipt className="w-5 h-5 text-emerald-400" />
                Create Customer Invoice & Indian GST Billing
              </h3>
              <button onClick={() => setIsNewInvoiceModalOpen(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreateInvoice} className="space-y-4 text-xs">
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="block text-slate-400 mb-1 font-medium">Select Customer *</label>
                  <select
                    value={newInvoiceForm.customer_id}
                    onChange={(e) => setNewInvoiceForm({ ...newInvoiceForm, customer_id: e.target.value })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                  >
                    {customers.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name} ({c.code})
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-slate-400 mb-1 font-medium">Place of Supply (State) *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. 19-West Bengal or 27-Maharashtra"
                    value={newInvoiceForm.place_of_supply}
                    onChange={(e) => setNewInvoiceForm({ ...newInvoiceForm, place_of_supply: e.target.value })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                  />
                </div>

                <div>
                  <label className="block text-slate-400 mb-1 font-medium">Tax Scheme</label>
                  <select
                    value={newInvoiceForm.tax_scheme}
                    onChange={(e) => setNewInvoiceForm({ ...newInvoiceForm, tax_scheme: e.target.value })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                  >
                    <option value="GST">Standard GST (Intra/Inter)</option>
                    <option value="EXPORT_LUT">Export under LUT (Zero Tax)</option>
                    <option value="EXPORT_ZERO_RATED">Export with IGST Payment</option>
                    <option value="EXEMPT">Exempt / Nil-Rated Supply</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-4 gap-4">
                <div>
                  <label className="block text-slate-400 mb-1 font-medium">Invoice Date</label>
                  <input
                    type="date"
                    required
                    value={newInvoiceForm.invoice_date}
                    onChange={(e) => setNewInvoiceForm({ ...newInvoiceForm, invoice_date: e.target.value })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                  />
                </div>

                <div>
                  <label className="block text-slate-400 mb-1 font-medium">Due Date</label>
                  <input
                    type="date"
                    required
                    value={newInvoiceForm.due_date}
                    onChange={(e) => setNewInvoiceForm({ ...newInvoiceForm, due_date: e.target.value })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                  />
                </div>

                <div>
                  <label className="block text-slate-400 mb-1 font-medium">Currency</label>
                  <select
                    value={newInvoiceForm.currency}
                    onChange={(e) =>
                      setNewInvoiceForm({
                        ...newInvoiceForm,
                        currency: e.target.value,
                        exchange_rate: e.target.value === 'INR' ? 1.0 : newInvoiceForm.exchange_rate,
                      })
                    }
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                  >
                    <option value="INR">INR — Indian Rupee</option>
                    <option value="USD">USD — US Dollar</option>
                    <option value="EUR">EUR — Euro</option>
                    <option value="AED">AED — UAE Dirham</option>
                    <option value="GBP">GBP — British Pound</option>
                  </select>
                </div>

                <div>
                  <label className="block text-slate-400 mb-1 font-medium">Exchange Rate to INR</label>
                  <input
                    type="number"
                    step="0.01"
                    disabled={newInvoiceForm.currency === 'INR'}
                    value={newInvoiceForm.exchange_rate}
                    onChange={(e) => setNewInvoiceForm({ ...newInvoiceForm, exchange_rate: e.target.value })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white disabled:opacity-50"
                  />
                </div>
              </div>

              {/* Line Items */}
              <div className="border border-slate-800 rounded-xl p-4 bg-slate-800/40 space-y-3">
                <div className="flex justify-between items-center">
                  <span className="font-semibold text-white uppercase text-[11px] tracking-wider">Line Items</span>
                  <button
                    type="button"
                    onClick={() =>
                      setNewInvoiceForm({
                        ...newInvoiceForm,
                        items: [
                          ...newInvoiceForm.items,
                          {
                            product_id: '',
                            product_sku: '',
                            description: '',
                            hsn_code: '',
                            uom: 'PCS',
                            quantity: 1,
                            unit_price: 0,
                            discount_pct: 0,
                            tax_classification: 'taxable',
                            gst_rate_pct: 18.0,
                          },
                        ],
                      })
                    }
                    className="px-2 py-1 bg-slate-700 hover:bg-slate-600 text-white rounded text-[11px]"
                  >
                    + Add Line
                  </button>
                </div>

                {newInvoiceForm.items.map((it, idx) => (
                  <div key={idx} className="grid grid-cols-7 gap-2 items-center bg-slate-900/60 p-2.5 rounded-lg border border-slate-800">
                    <div className="col-span-2">
                      <input
                        type="text"
                        placeholder="SKU"
                        required
                        value={it.product_sku}
                        onChange={(e) => {
                          const items = [...newInvoiceForm.items]
                          items[idx].product_sku = e.target.value
                          setNewInvoiceForm({ ...newInvoiceForm, items })
                        }}
                        className="w-full bg-slate-800 border border-slate-700 rounded p-1.5 text-white"
                      />
                      <input
                        type="text"
                        placeholder="Description"
                        required
                        value={it.description}
                        onChange={(e) => {
                          const items = [...newInvoiceForm.items]
                          items[idx].description = e.target.value
                          setNewInvoiceForm({ ...newInvoiceForm, items })
                        }}
                        className="w-full bg-slate-800 border border-slate-700 rounded p-1.5 text-slate-300 mt-1"
                      />
                    </div>

                    <div>
                      <input
                        type="text"
                        placeholder="HSN"
                        value={it.hsn_code}
                        onChange={(e) => {
                          const items = [...newInvoiceForm.items]
                          items[idx].hsn_code = e.target.value
                          setNewInvoiceForm({ ...newInvoiceForm, items })
                        }}
                        className="w-full bg-slate-800 border border-slate-700 rounded p-1.5 text-white"
                      />
                    </div>

                    <div>
                      <input
                        type="number"
                        placeholder="Qty"
                        required
                        min="0.1"
                        step="0.1"
                        value={it.quantity}
                        onChange={(e) => {
                          const items = [...newInvoiceForm.items]
                          items[idx].quantity = e.target.value
                          setNewInvoiceForm({ ...newInvoiceForm, items })
                        }}
                        className="w-full bg-slate-800 border border-slate-700 rounded p-1.5 text-white font-mono"
                      />
                    </div>

                    <div>
                      <input
                        type="number"
                        placeholder="Price"
                        required
                        min="0"
                        step="0.01"
                        value={it.unit_price}
                        onChange={(e) => {
                          const items = [...newInvoiceForm.items]
                          items[idx].unit_price = e.target.value
                          setNewInvoiceForm({ ...newInvoiceForm, items })
                        }}
                        className="w-full bg-slate-800 border border-slate-700 rounded p-1.5 text-white font-mono"
                      />
                    </div>

                    <div>
                      <select
                        value={it.gst_rate_pct}
                        onChange={(e) => {
                          const items = [...newInvoiceForm.items]
                          items[idx].gst_rate_pct = Number(e.target.value)
                          setNewInvoiceForm({ ...newInvoiceForm, items })
                        }}
                        className="w-full bg-slate-800 border border-slate-700 rounded p-1.5 text-white font-mono"
                      >
                        <option value="0">0%</option>
                        <option value="5">5%</option>
                        <option value="12">12%</option>
                        <option value="18">18%</option>
                        <option value="28">28%</option>
                      </select>
                    </div>

                    <div className="text-right">
                      {newInvoiceForm.items.length > 1 && (
                        <button
                          type="button"
                          onClick={() => {
                            const items = newInvoiceForm.items.filter((_, i) => i !== idx)
                            setNewInvoiceForm({ ...newInvoiceForm, items })
                          }}
                          className="text-rose-400 hover:text-rose-200"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setIsNewInvoiceModalOpen(false)}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl font-semibold shadow"
                >
                  Create Invoice Draft
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* MODAL: Record Payment */}
      {/* ======================================================== */}
      {isRecordPaymentModalOpen && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl max-w-md w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <Banknote className="w-5 h-5 text-emerald-400" />
                Record Customer Payment
              </h3>
              <button onClick={() => setIsRecordPaymentModalOpen(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleRecordPayment} className="space-y-4 text-xs">
              <div>
                <label className="block text-slate-400 mb-1 font-medium">Customer *</label>
                <select
                  value={newPaymentForm.customer_id}
                  onChange={(e) => setNewPaymentForm({ ...newPaymentForm, customer_id: e.target.value })}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                >
                  {customers.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-slate-400 mb-1 font-medium">Payment Date *</label>
                  <input
                    type="date"
                    required
                    value={newPaymentForm.payment_date}
                    onChange={(e) => setNewPaymentForm({ ...newPaymentForm, payment_date: e.target.value })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1 font-medium">Payment Method *</label>
                  <select
                    value={newPaymentForm.payment_method}
                    onChange={(e) => setNewPaymentForm({ ...newPaymentForm, payment_method: e.target.value })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                  >
                    <option value="bank_transfer">Bank Transfer (NEFT/RTGS)</option>
                    <option value="wire_swift">Wire / SWIFT</option>
                    <option value="letter_of_credit">Letter of Credit (LC)</option>
                    <option value="cheque">Cheque</option>
                    <option value="upi">UPI / Digital</option>
                    <option value="cash">Cash</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-slate-400 mb-1 font-medium">Amount *</label>
                  <input
                    type="number"
                    step="0.01"
                    required
                    placeholder="0.00"
                    value={newPaymentForm.amount}
                    onChange={(e) => setNewPaymentForm({ ...newPaymentForm, amount: e.target.value })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white font-mono"
                  />
                </div>
                <div>
                  <label className="block text-slate-400 mb-1 font-medium">Currency</label>
                  <select
                    value={newPaymentForm.currency}
                    onChange={(e) => setNewPaymentForm({ ...newPaymentForm, currency: e.target.value })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                  >
                    <option value="INR">INR</option>
                    <option value="USD">USD</option>
                    <option value="EUR">EUR</option>
                    <option value="AED">AED</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-slate-400 mb-1 font-medium">Reference Number (UTR / LC / Cheque)</label>
                <input
                  type="text"
                  placeholder="e.g. UTR-HDFC20261014881"
                  value={newPaymentForm.reference_number}
                  onChange={(e) => setNewPaymentForm({ ...newPaymentForm, reference_number: e.target.value })}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                />
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setIsRecordPaymentModalOpen(false)}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl font-semibold shadow"
                >
                  Confirm Payment
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* MODAL: Allocate Payment to Invoice */}
      {/* ======================================================== */}
      {isAllocateModalOpen && selectedPaymentForAlloc && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl max-w-md w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <CreditCard className="w-5 h-5 text-sky-400" />
                Allocate Payment {selectedPaymentForAlloc.payment_number}
              </h3>
              <button onClick={() => setIsAllocateModalOpen(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-3 bg-slate-800/80 rounded-xl text-xs space-y-1">
              <div>Customer: <strong>{selectedPaymentForAlloc.customer_name}</strong></div>
              <div>
                Available to Allocate:{' '}
                <strong className="text-emerald-400 font-mono">
                  {selectedPaymentForAlloc.currency} {selectedPaymentForAlloc.unallocated_amount?.toFixed(2)}
                </strong>
              </div>
            </div>

            <form onSubmit={handleAllocatePayment} className="space-y-4 text-xs">
              <div>
                <label className="block text-slate-400 mb-1 font-medium">Select Invoice with Outstanding Balance</label>
                <select
                  value={allocInvoiceId}
                  onChange={(e) => setAllocInvoiceId(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                >
                  <option value="">-- Choose Invoice --</option>
                  {invoices
                    .filter((inv) => inv.customer_id === selectedPaymentForAlloc.customer_id && inv.outstanding_balance > 0)
                    .map((inv) => (
                      <option key={inv.id} value={inv.id}>
                        {inv.invoice_number} (Outstanding: {inv.currency} {inv.outstanding_balance?.toFixed(2)})
                      </option>
                    ))}
                </select>
              </div>

              <div>
                <label className="block text-slate-400 mb-1 font-medium">Allocation Amount</label>
                <input
                  type="number"
                  step="0.01"
                  required
                  value={allocAmount}
                  onChange={(e) => setAllocAmount(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white font-mono"
                />
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setIsAllocateModalOpen(false)}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!allocInvoiceId || !allocAmount}
                  className="px-4 py-2 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white rounded-xl font-semibold shadow"
                >
                  Allocate Funds
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* MODAL: Issue Credit Note */}
      {/* ======================================================== */}
      {isNewCreditNoteModalOpen && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <FileMinus className="w-5 h-5 text-amber-400" />
                Issue Customer Credit Note
              </h3>
              <button onClick={() => setIsNewCreditNoteModalOpen(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreateCreditNote} className="space-y-4 text-xs">
              <div>
                <label className="block text-slate-400 mb-1 font-medium">Select Target Invoice</label>
                <select
                  value={newCreditNoteForm.invoice_id}
                  onChange={(e) => {
                    const inv = invoices.find((i) => i.id === e.target.value)
                    setNewCreditNoteForm({
                      ...newCreditNoteForm,
                      invoice_id: e.target.value,
                      items: [
                        {
                          product_sku: inv?.items?.[0]?.product_sku || 'CREDIT-ADJ',
                          description: 'Credit adjustment for invoice ' + (inv?.invoice_number || ''),
                          quantity: 1,
                          unit_price: 0,
                          gst_rate_pct: 0,
                        },
                      ],
                    })
                  }}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                >
                  <option value="">-- Choose Invoice --</option>
                  {invoices
                    .filter((inv) => ['issued', 'partially_paid', 'paid'].includes(inv.status))
                    .map((inv) => (
                      <option key={inv.id} value={inv.id}>
                        {inv.invoice_number} — {inv.customer_name} (Total: {inv.currency} {inv.grand_total?.toFixed(2)})
                      </option>
                    ))}
                </select>
              </div>

              <div>
                <label className="block text-slate-400 mb-1 font-medium">Reason for Credit Note</label>
                <select
                  value={newCreditNoteForm.reason}
                  onChange={(e) => setNewCreditNoteForm({ ...newCreditNoteForm, reason: e.target.value })}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white"
                >
                  <option value="goods_return">Goods Return / Rejection</option>
                  <option value="pricing_error">Pricing Error Correction</option>
                  <option value="discount_adjustment">Post-sale Discount / Rebate</option>
                  <option value="defective_goods">Defective / Damaged Cargo</option>
                  <option value="other">Other Commercial Adjustment</option>
                </select>
              </div>

              <div>
                <label className="block text-slate-400 mb-1 font-medium">Credit Amount</label>
                <input
                  type="number"
                  step="0.01"
                  required
                  placeholder="0.00"
                  value={newCreditNoteForm.items[0]?.unit_price}
                  onChange={(e) => {
                    const items = [...newCreditNoteForm.items]
                    items[0].unit_price = e.target.value
                    setNewCreditNoteForm({ ...newCreditNoteForm, items })
                  }}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg p-2.5 text-white font-mono"
                />
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setIsNewCreditNoteModalOpen(false)}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!newCreditNoteForm.invoice_id}
                  className="px-4 py-2 bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white rounded-xl font-semibold shadow"
                >
                  Confirm Credit Note
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

function InvoiceStatusBadge({ status }) {
  const styles = {
    draft: 'bg-slate-500/10 text-slate-400 border-slate-500/20',
    approved: 'bg-sky-500/10 text-sky-400 border-sky-500/20',
    issued: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20',
    partially_paid: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
    paid: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
    overdue: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
    credited: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
    cancelled: 'bg-slate-600/20 text-slate-400 border-slate-600/30',
  }
  return (
    <span className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold capitalize border ${styles[status] || styles.draft}`}>
      {status?.replace(/_/g, ' ') || 'draft'}
    </span>
  )
}
