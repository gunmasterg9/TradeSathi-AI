import test from 'node:test'
import assert from 'node:assert/strict'

// =========================================================================
// GST Calculation Framework Helper Functions
// =========================================================================

function calculateGstTax({
  taxableAmount,
  taxRatePct,
  supplyType,
  taxTreatment = 'taxable',
  exportSupplyType = null,
}) {
  const taxable = Number(taxableAmount) || 0
  const rate = Number(taxRatePct) || 0

  if (taxTreatment === 'exempt' || taxTreatment === 'nil_rated' || taxTreatment === 'non_gst') {
    return {
      cgst_rate: 0,
      cgst_amount: 0,
      sgst_rate: 0,
      sgst_amount: 0,
      igst_rate: 0,
      igst_amount: 0,
      tax_amount: 0,
      line_total: Math.round(taxable * 100) / 100,
    }
  }

  if (supplyType === 'export') {
    if (exportSupplyType === 'lut_bond') {
      return {
        cgst_rate: 0,
        cgst_amount: 0,
        sgst_rate: 0,
        sgst_amount: 0,
        igst_rate: 0,
        igst_amount: 0,
        tax_amount: 0,
        line_total: Math.round(taxable * 100) / 100,
      }
    } else {
      // Export with IGST payment
      const igstAmount = Math.round(taxable * (rate / 100) * 100) / 100
      return {
        cgst_rate: 0,
        cgst_amount: 0,
        sgst_rate: 0,
        sgst_amount: 0,
        igst_rate: rate,
        igst_amount: igstAmount,
        tax_amount: igstAmount,
        line_total: Math.round((taxable + igstAmount) * 100) / 100,
      }
    }
  }

  if (supplyType === 'intra_state') {
    const halfRate = rate / 2
    const cgstAmount = Math.round(taxable * (halfRate / 100) * 100) / 100
    const sgstAmount = Math.round(taxable * (halfRate / 100) * 100) / 100
    const totalTax = Math.round((cgstAmount + sgstAmount) * 100) / 100
    return {
      cgst_rate: halfRate,
      cgst_amount: cgstAmount,
      sgst_rate: halfRate,
      sgst_amount: sgstAmount,
      igst_rate: 0,
      igst_amount: 0,
      tax_amount: totalTax,
      line_total: Math.round((taxable + totalTax) * 100) / 100,
    }
  }

  if (supplyType === 'inter_state') {
    const igstAmount = Math.round(taxable * (rate / 100) * 100) / 100
    return {
      cgst_rate: 0,
      cgst_amount: 0,
      sgst_rate: 0,
      sgst_amount: 0,
      igst_rate: rate,
      igst_amount: igstAmount,
      tax_amount: igstAmount,
      line_total: Math.round((taxable + igstAmount) * 100) / 100,
    }
  }

  throw new Error(`Unknown supply type: ${supplyType}`)
}

// =========================================================================
// Multi-Currency & FX Calculations
// =========================================================================

function calculateBaseInr(amount, exchangeRate) {
  const a = Number(amount) || 0
  const rate = Number(exchangeRate) || 1.0
  return Math.round(a * rate * 100) / 100
}

function calculateRealizedFxDiff({
  allocatedAmount,
  invoiceExchangeRate,
  paymentExchangeRate,
}) {
  const alloc = Number(allocatedAmount) || 0
  const invRate = Number(invoiceExchangeRate) || 1.0
  const payRate = Number(paymentExchangeRate) || 1.0

  const invInr = Math.round(alloc * invRate * 100) / 100
  const payInr = Math.round(alloc * payRate * 100) / 100
  // realized diff = payment INR - invoice INR
  return Math.round((payInr - invInr) * 100) / 100
}

// =========================================================================
// Cumulative Invoiced Quantity Guard
// =========================================================================

function validateCumulativeInvoicing(lines, orderLineLimits) {
  for (const line of lines) {
    if (!line.sales_order_line_id) continue
    const limit = orderLineLimits[line.sales_order_line_id]
    if (!limit) continue

    const previouslyInvoiced = limit.invoiced_qty || 0
    const orderedQty = limit.ordered_qty || 0
    const remainingInvoiceable = Math.max(0, orderedQty - previouslyInvoiced)

    if (line.quantity > remainingInvoiceable) {
      return {
        valid: false,
        error: `Quantity ${line.quantity} exceeds remaining invoiceable quantity ${remainingInvoiceable} for line ${line.sales_order_line_id}`,
      }
    }
  }
  return { valid: true }
}

// =========================================================================
// Receivables Aging Categorization
// =========================================================================

function categorizeAgingBucket(dueDateStr, asOfDateStr) {
  const dueDate = new Date(dueDateStr)
  const asOf = new Date(asOfDateStr)
  const diffTime = asOf.getTime() - dueDate.getTime()
  const daysOverdue = Math.floor(diffTime / (1000 * 60 * 60 * 24))

  if (daysOverdue <= 0) return 'current'
  if (daysOverdue <= 30) return 'days_0_30'
  if (daysOverdue <= 60) return 'days_31_60'
  if (daysOverdue <= 90) return 'days_61_90'
  return 'days_90_plus'
}

// =========================================================================
// TESTS
// =========================================================================

test('GST Intra-state supply applies CGST and SGST equally, IGST is 0', () => {
  const res = calculateGstTax({
    taxableAmount: 10000,
    taxRatePct: 18,
    supplyType: 'intra_state',
  })

  assert.equal(res.cgst_rate, 9)
  assert.equal(res.cgst_amount, 900)
  assert.equal(res.sgst_rate, 9)
  assert.equal(res.sgst_amount, 900)
  assert.equal(res.igst_rate, 0)
  assert.equal(res.igst_amount, 0)
  assert.equal(res.tax_amount, 1800)
  assert.equal(res.line_total, 11800)
})

test('GST Inter-state supply applies IGST only, CGST and SGST are 0', () => {
  const res = calculateGstTax({
    taxableAmount: 50000,
    taxRatePct: 12,
    supplyType: 'inter_state',
  })

  assert.equal(res.cgst_rate, 0)
  assert.equal(res.cgst_amount, 0)
  assert.equal(res.sgst_rate, 0)
  assert.equal(res.sgst_amount, 0)
  assert.equal(res.igst_rate, 12)
  assert.equal(res.igst_amount, 6000)
  assert.equal(res.tax_amount, 6000)
  assert.equal(res.line_total, 56000)
})

test('GST Mutual Exclusion: CGST/SGST and IGST are never applied together', () => {
  const intra = calculateGstTax({
    taxableAmount: 1000,
    taxRatePct: 18,
    supplyType: 'intra_state',
  })
  assert.ok(intra.cgst_amount > 0 && intra.sgst_amount > 0 && intra.igst_amount === 0)

  const inter = calculateGstTax({
    taxableAmount: 1000,
    taxRatePct: 18,
    supplyType: 'inter_state',
  })
  assert.ok(inter.igst_amount > 0 && inter.cgst_amount === 0 && inter.sgst_amount === 0)
})

test('GST Export under LUT/Bond is zero-rated with zero tax', () => {
  const res = calculateGstTax({
    taxableAmount: 15000,
    taxRatePct: 18,
    supplyType: 'export',
    exportSupplyType: 'lut_bond',
  })

  assert.equal(res.cgst_amount, 0)
  assert.equal(res.sgst_amount, 0)
  assert.equal(res.igst_amount, 0)
  assert.equal(res.tax_amount, 0)
  assert.equal(res.line_total, 15000)
})

test('GST Export with payment of tax applies IGST only', () => {
  const res = calculateGstTax({
    taxableAmount: 20000,
    taxRatePct: 18,
    supplyType: 'export',
    exportSupplyType: 'with_igst',
  })

  assert.equal(res.cgst_amount, 0)
  assert.equal(res.sgst_amount, 0)
  assert.equal(res.igst_amount, 3600)
  assert.equal(res.tax_amount, 3600)
  assert.equal(res.line_total, 23600)
})

test('Multi-currency conversion to base INR snapshot', () => {
  const usdAmount = 2500.50
  const exchangeRate = 83.25
  const baseInr = calculateBaseInr(usdAmount, exchangeRate)

  assert.equal(baseInr, 208166.63)
})

test('Realized exchange difference calculation on foreign currency settlement', () => {
  // Invoice: $1,000 @ 83.00 = INR 83,000
  // Payment: $1,000 @ 83.50 = INR 83,500
  // FX gain: +500 INR
  const fxGain = calculateRealizedFxDiff({
    allocatedAmount: 1000,
    invoiceExchangeRate: 83.00,
    paymentExchangeRate: 83.50,
  })
  assert.equal(fxGain, 500)

  // FX loss: $1,000 @ 82.50 vs 83.00 = -500 INR
  const fxLoss = calculateRealizedFxDiff({
    allocatedAmount: 1000,
    invoiceExchangeRate: 83.00,
    paymentExchangeRate: 82.50,
  })
  assert.equal(fxLoss, -500)
})

test('Cumulative invoicing guard blocks over-invoicing beyond order quantity', () => {
  const limits = {
    'line-001': { ordered_qty: 100, invoiced_qty: 70 },
  }

  // Attempting to invoice 30 (exact remaining) -> VALID
  const check1 = validateCumulativeInvoicing(
    [{ sales_order_line_id: 'line-001', quantity: 30 }],
    limits
  )
  assert.equal(check1.valid, true)

  // Attempting to invoice 31 -> INVALID (exceeds remaining 30)
  const check2 = validateCumulativeInvoicing(
    [{ sales_order_line_id: 'line-001', quantity: 31 }],
    limits
  )
  assert.equal(check2.valid, false)
  assert.match(check2.error, /exceeds remaining invoiceable quantity/)
})

test('Receivables aging bucket categorization correctly sorts overdue days', () => {
  const asOf = '2026-10-15'

  assert.equal(categorizeAgingBucket('2026-10-20', asOf), 'current') // Not due yet
  assert.equal(categorizeAgingBucket('2026-10-10', asOf), 'days_0_30') // 5 days overdue
  assert.equal(categorizeAgingBucket('2026-09-01', asOf), 'days_31_60') // 44 days overdue
  assert.equal(categorizeAgingBucket('2026-07-20', asOf), 'days_61_90') // 87 days overdue
  assert.equal(categorizeAgingBucket('2026-05-01', asOf), 'days_90_plus') // 167 days overdue
})

test('Separation of duties requires different users for creation and approval', () => {
  const invoice = {
    created_by: 'usr-analyst-1',
    status: 'draft',
  }

  function canApprove(invoice, currentUser) {
    if (invoice.created_by === currentUser.id) {
      return { allowed: false, reason: 'Separation of duties: creator cannot approve own invoice' }
    }
    return { allowed: true }
  }

  const selfApprove = canApprove(invoice, { id: 'usr-analyst-1' })
  assert.equal(selfApprove.allowed, false)

  const peerApprove = canApprove(invoice, { id: 'usr-manager-2' })
  assert.equal(peerApprove.allowed, true)
})
