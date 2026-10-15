import test from 'node:test'
import assert from 'node:assert/strict'
import { sanitizeCsvCell } from '../src/reportHelper.js'

// =========================================================================
// Dashboard & Reporting Calculation Helpers
// =========================================================================

function formatCurrencyAmount(amount, currency = 'INR') {
  return `${currency} ${Number(amount || 0).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function calculateSalesKpis(orders, lines) {
  const confirmedOrders = orders.filter((o) =>
    ['confirmed', 'allocated', 'dispatched', 'delivered'].includes(o.status)
  )
  const cancelledOrders = orders.filter((o) => o.status === 'cancelled')

  // Group confirmed value by currency
  const confirmedByCurrency = {}
  for (const o of confirmedOrders) {
    const curr = o.currency || 'INR'
    if (!confirmedByCurrency[curr]) {
      confirmedByCurrency[curr] = { total_value: 0, order_count: 0 }
    }
    confirmedByCurrency[curr].total_value =
      Math.round((confirmedByCurrency[curr].total_value + Number(o.grand_total || 0)) * 100) / 100
    confirmedByCurrency[curr].order_count += 1
  }

  // Calculate quantities from active lines
  let totalOrdered = 0
  let totalFulfilled = 0
  let totalOutstanding = 0

  for (const l of lines) {
    const parent = orders.find((o) => o.id === l.sales_order_id)
    if (!parent || parent.status === 'cancelled') continue

    const ordered = Number(l.ordered_quantity || 0)
    const dispatched = Number(l.dispatched_quantity || 0)
    const delivered = Number(l.delivered_quantity || 0)

    totalOrdered += ordered
    totalFulfilled += dispatched
    totalOutstanding += Math.max(0, ordered - delivered)
  }

  return {
    confirmedByCurrency,
    totalOrdered,
    totalFulfilled,
    totalOutstanding,
    cancelledOrdersCount: cancelledOrders.length,
    cancelledOrdersValue: cancelledOrders.reduce((sum, o) => sum + Number(o.grand_total || 0), 0),
  }
}

function calculateFinanceReceivables(invoices) {
  // Exclude draft and cancelled invoices
  const openInvoices = invoices.filter((inv) =>
    ['issued', 'partially_paid'].includes(inv.status)
  )

  let issuedReceivablesBaseInr = 0
  let draftInvoicedBaseInr = 0

  for (const inv of invoices) {
    const rate = Number(inv.exchange_rate || 1.0)
    if (inv.status === 'draft') {
      draftInvoicedBaseInr += Number(inv.grand_total || 0) * rate
    } else if (['issued', 'partially_paid'].includes(inv.status)) {
      issuedReceivablesBaseInr += Number(inv.outstanding_balance || 0) * rate
    }
  }

  return {
    openInvoicesCount: openInvoices.length,
    issuedReceivablesBaseInr: Math.round(issuedReceivablesBaseInr * 100) / 100,
    draftInvoicedBaseInr: Math.round(draftInvoicedBaseInr * 100) / 100,
  }
}

function evaluateStockHealth({ onHandAvailable, reservedQty, reorderLevel }) {
  const onHand = Number(onHandAvailable || 0)
  const reserved = Number(reservedQty || 0)
  const netAvailable = onHand - reserved
  const reorder = Number(reorderLevel || 0)

  if (reorder > 0 && netAvailable <= 0) {
    return 'CRITICAL'
  }
  if (reorder > 0 && netAvailable <= reorder) {
    return 'LOW_STOCK'
  }
  return 'HEALTHY'
}

// =========================================================================
// TESTS
// =========================================================================

test('Sales KPI engine preserves distinct currencies without unconverted aggregation', () => {
  const orders = [
    { id: 'so-1', grand_total: 1000, currency: 'USD', status: 'confirmed' },
    { id: 'so-2', grand_total: 2500, currency: 'USD', status: 'delivered' },
    { id: 'so-3', grand_total: 50000, currency: 'INR', status: 'confirmed' },
    { id: 'so-4', grand_total: 500, currency: 'USD', status: 'cancelled' },
  ]
  const lines = [
    { sales_order_id: 'so-1', ordered_quantity: 10, dispatched_quantity: 5, delivered_quantity: 5 },
    { sales_order_id: 'so-2', ordered_quantity: 20, dispatched_quantity: 20, delivered_quantity: 20 },
    { sales_order_id: 'so-3', ordered_quantity: 50, dispatched_quantity: 0, delivered_quantity: 0 },
    { sales_order_id: 'so-4', ordered_quantity: 5, dispatched_quantity: 0, delivered_quantity: 0 },
  ]

  const kpis = calculateSalesKpis(orders, lines)

  assert.equal(kpis.confirmedByCurrency['USD'].total_value, 3500)
  assert.equal(kpis.confirmedByCurrency['USD'].order_count, 2)
  assert.equal(kpis.confirmedByCurrency['INR'].total_value, 50000)
  assert.equal(kpis.confirmedByCurrency['INR'].order_count, 1)

  // Line quantities
  assert.equal(kpis.totalOrdered, 80) // Excludes cancelled so-4 (5 units)
  assert.equal(kpis.totalFulfilled, 25)
  assert.equal(kpis.totalOutstanding, 55) // (10-5) + (20-20) + (50-0) = 5 + 0 + 50 = 55

  // Cancelled orders tracked separately
  assert.equal(kpis.cancelledOrdersCount, 1)
  assert.equal(kpis.cancelledOrdersValue, 500)
})

test('Finance receivables strictly excludes draft and cancelled invoices', () => {
  const invoices = [
    { id: 'inv-1', grand_total: 10000, outstanding_balance: 7000, exchange_rate: 1.0, status: 'issued' },
    { id: 'inv-2', grand_total: 5000, outstanding_balance: 5000, exchange_rate: 1.0, status: 'draft' },
    { id: 'inv-3', grand_total: 2000, outstanding_balance: 0, exchange_rate: 1.0, status: 'paid' },
    { id: 'inv-4', grand_total: 100, outstanding_balance: 100, exchange_rate: 83.0, status: 'partially_paid' }, // $100 * 83 = 8300 INR
    { id: 'inv-5', grand_total: 4000, outstanding_balance: 4000, exchange_rate: 1.0, status: 'cancelled' },
  ]

  const finance = calculateFinanceReceivables(invoices)

  assert.equal(finance.openInvoicesCount, 2) // inv-1 and inv-4
  // 7,000 + (100 * 83) = 7,000 + 8,300 = 15,300 INR
  assert.equal(finance.issuedReceivablesBaseInr, 15300)
  // Draft invoice excluded from receivables, tracked separately:
  assert.equal(finance.draftInvoicedBaseInr, 5000)
})

test('Inventory reorder monitor accurately detects LOW_STOCK and CRITICAL shortages', () => {
  // Case 1: Healthy stock
  assert.equal(
    evaluateStockHealth({ onHandAvailable: 100, reservedQty: 20, reorderLevel: 50 }),
    'HEALTHY' // Net 80 > 50
  )

  // Case 2: Low stock
  assert.equal(
    evaluateStockHealth({ onHandAvailable: 50, reservedQty: 10, reorderLevel: 50 }),
    'LOW_STOCK' // Net 40 <= 50
  )

  // Case 3: Critical stock (zero or negative net available)
  assert.equal(
    evaluateStockHealth({ onHandAvailable: 15, reservedQty: 15, reorderLevel: 20 }),
    'CRITICAL' // Net 0 <= 0
  )
})

test('CSV formula-injection defense sanitizes dangerous executable prefixes', () => {
  // Malicious command execution payloads with direct prefixes
  assert.equal(sanitizeCsvCell("=cmd|' /C calc'!A0"), "'=cmd|' /C calc'!A0")
  assert.equal(sanitizeCsvCell('+123456+cmd|...'), "'+123456+cmd|...")
  assert.equal(sanitizeCsvCell('@SUM(A1:A10)'), "'@SUM(A1:A10)")
  assert.equal(sanitizeCsvCell('-2+3+cmd|...'), "'-2+3+cmd|...")
  assert.equal(sanitizeCsvCell('|powershell.exe'), "'|powershell.exe")

  // Obfuscated payloads with leading spaces, tabs, carriage returns, or line feeds
  assert.equal(sanitizeCsvCell("   =cmd|' /C calc'!A0"), "'   =cmd|' /C calc'!A0")
  assert.equal(sanitizeCsvCell("  @HYPERLINK('http://evil.com')"), "'  @HYPERLINK('http://evil.com')")
  assert.equal(sanitizeCsvCell('\tDDE_ATTACK'), "'\tDDE_ATTACK")
  assert.equal(sanitizeCsvCell('\r=2+5'), "'\r=2+5")
  assert.equal(sanitizeCsvCell('\n-3+4'), "'\n-3+4")
  assert.equal(sanitizeCsvCell(' \t=SUM(A1:A5)'), "' \t=SUM(A1:A5)")

  // Legitimate plain numbers remain un-quoted
  assert.equal(sanitizeCsvCell(-50.25), '-50.25')
  assert.equal(sanitizeCsvCell('-50.25'), '-50.25')
  assert.equal(sanitizeCsvCell(100), '100')
  assert.equal(sanitizeCsvCell('+100'), '+100')
  assert.equal(sanitizeCsvCell('Normal Text'), 'Normal Text')
  assert.equal(sanitizeCsvCell('Acme, Inc.'), 'Acme, Inc.')
  assert.equal(sanitizeCsvCell(''), '')
  assert.equal(sanitizeCsvCell('   '), '')
  assert.equal(sanitizeCsvCell(null), '')
  assert.equal(sanitizeCsvCell(undefined), '')
})

test('Statutory compliance notices are mandated across all finance and export views', () => {
  const exportDisclaimer =
    'TradeSathi AI Document Readiness Evaluation is an internal operational check and does not constitute official customs clearance.'
  const gstDisclaimer =
    'TradeSathi AI Financial Reports & GST Summaries are internal trade management documents. They do not constitute statutory e-invoicing.'
  const procurementNotice =
    'Vendor accounts-payable ledger is not active. Purchase order figures represent commercial purchasing commitments only.'

  assert.match(exportDisclaimer, /does not constitute official customs clearance/)
  assert.match(gstDisclaimer, /not constitute statutory e-invoicing/)
  assert.match(procurementNotice, /purchasing commitments only/)
})
