import test from 'node:test'
import assert from 'node:assert/strict'

// Role permission matrix for procurement & inventory (matching backend master_data.ROLE_PERMISSIONS)
const ROLE_PERMISSIONS = {
  admin: [
    'read', 'create', 'update', 'delete',
    'create_po', 'update_po', 'approve_po', 'cancel_po',
    'create_gr', 'post_gr',
    'create_product', 'update_product', 'delete_product',
    'create_supplier', 'update_supplier', 'delete_supplier',
    'create_customer', 'update_customer', 'delete_customer',
  ],
  procurement: [
    'read',
    'create_po', 'update_po', 'approve_po', 'cancel_po',
    'create_product', 'update_product',
    'create_supplier', 'update_supplier',
  ],
  warehouse: [
    'read',
    'create_gr', 'post_gr',
  ],
  sales: [
    'read',
    'create_product', 'update_product',
    'create_customer', 'update_customer',
  ],
  viewer: [
    'read',
  ],
}

function canPerformProcurementAction(role, action) {
  const normalized = (role || 'viewer').toLowerCase().trim()
  const perms = ROLE_PERMISSIONS[normalized] || ['read']
  return perms.includes(action)
}

function calculateLineTotal(qty, unitPrice, taxRatePercent = 0) {
  const subtotal = Math.round((Number(qty || 0) * Number(unitPrice || 0)) * 100) / 100
  const tax = Math.round((subtotal * (Number(taxRatePercent || 0) / 100)) * 100) / 100
  const total = Math.round((subtotal + tax) * 100) / 100
  return { subtotal, tax, total }
}

function calculateOrderTotals(lines) {
  let subtotal = 0
  let tax = 0
  for (const line of lines) {
    const calc = calculateLineTotal(line.ordered_quantity, line.unit_price, line.tax_rate)
    subtotal += calc.subtotal
    tax += calc.tax
  }
  subtotal = Math.round(subtotal * 100) / 100
  tax = Math.round(tax * 100) / 100
  const grandTotal = Math.round((subtotal + tax) * 100) / 100
  return { subtotal, tax, grandTotal }
}

function validateGoodsReceiptInspection(receivedQty, acceptedQty, rejectedQty, quarantinedQty, rejectionReason = '') {
  const rec = Number(receivedQty) || 0
  const acc = Number(acceptedQty) || 0
  const rej = Number(rejectedQty) || 0
  const qua = Number(quarantinedQty) || 0

  if (rec <= 0) {
    return { valid: false, error: 'Received quantity must be positive' }
  }
  if (acc < 0 || rej < 0 || qua < 0) {
    return { valid: false, error: 'Accepted, rejected, and quarantined quantities cannot be negative' }
  }
  if (Math.round((acc + rej + qua) * 1000) !== Math.round(rec * 1000)) {
    return { valid: false, error: `Sum of accepted (${acc}), rejected (${rej}), and quarantined (${qua}) must equal received (${rec})` }
  }
  if (rej > 0 && !rejectionReason.trim()) {
    return { valid: false, error: 'Rejection reason is required when items are rejected' }
  }
  return { valid: true, error: null }
}

function validateOverReceipt(orderedQty, previouslyReceivedQty, newReceivedQty, tolerancePercent = 0) {
  const ordered = Number(orderedQty) || 0
  const prev = Number(previouslyReceivedQty) || 0
  const newRec = Number(newReceivedQty) || 0
  const maxAllowed = Math.round(ordered * (1 + (tolerancePercent / 100)) * 1000) / 1000
  const totalReceived = Math.round((prev + newRec) * 1000) / 1000

  if (totalReceived > maxAllowed) {
    return {
      allowed: false,
      remaining: Math.max(0, ordered - prev),
      exceededBy: Math.round((totalReceived - maxAllowed) * 1000) / 1000,
    }
  }
  return {
    allowed: true,
    remaining: Math.max(0, ordered - totalReceived),
    exceededBy: 0,
  }
}

// Tests
test('Role Permissions: Procurement role can create, update, approve POs but cannot post GRs', () => {
  assert.equal(canPerformProcurementAction('procurement', 'create_po'), true)
  assert.equal(canPerformProcurementAction('procurement', 'approve_po'), true)
  assert.equal(canPerformProcurementAction('procurement', 'create_gr'), false)
  assert.equal(canPerformProcurementAction('procurement', 'post_gr'), false)
})

test('Role Permissions: Warehouse role can create and post GRs but cannot approve POs', () => {
  assert.equal(canPerformProcurementAction('warehouse', 'create_gr'), true)
  assert.equal(canPerformProcurementAction('warehouse', 'post_gr'), true)
  assert.equal(canPerformProcurementAction('warehouse', 'create_po'), false)
  assert.equal(canPerformProcurementAction('warehouse', 'approve_po'), false)
})

test('Role Permissions: Viewer is strictly read-only', () => {
  assert.equal(canPerformProcurementAction('viewer', 'read'), true)
  assert.equal(canPerformProcurementAction('viewer', 'create_po'), false)
  assert.equal(canPerformProcurementAction('viewer', 'create_gr'), false)
  assert.equal(canPerformProcurementAction('viewer', 'post_gr'), false)
})

test('PO Line calculation: Correct subtotal, tax, and line total with 2 decimal precision', () => {
  // 10 units @ 125.50 with 18% tax
  const res = calculateLineTotal(10, 125.50, 18)
  assert.equal(res.subtotal, 1255.00)
  assert.equal(res.tax, 225.90)
  assert.equal(res.total, 1480.90)
})

test('PO Line calculation: Zero tax rate produces tax of 0.00', () => {
  const res = calculateLineTotal(5, 200, 0)
  assert.equal(res.subtotal, 1000.00)
  assert.equal(res.tax, 0.00)
  assert.equal(res.total, 1000.00)
})

test('PO Order Totals: Multi-line summation with mixed taxes', () => {
  const lines = [
    { ordered_quantity: 10, unit_price: 100, tax_rate: 18 },  // 1000 + 180 = 1180
    { ordered_quantity: 5, unit_price: 50, tax_rate: 5 },     // 250 + 12.50 = 262.50
    { ordered_quantity: 2, unit_price: 300, tax_rate: 0 },    // 600 + 0 = 600
  ]
  const totals = calculateOrderTotals(lines)
  assert.equal(totals.subtotal, 1850.00)
  assert.equal(totals.tax, 192.50)
  assert.equal(totals.grandTotal, 2042.50)
})

test('Goods Receipt Inspection: Valid distribution across accepted, rejected, quarantined', () => {
  const res = validateGoodsReceiptInspection(100, 80, 10, 10, 'Damaged outer packaging')
  assert.equal(res.valid, true)
  assert.equal(res.error, null)
})

test('Goods Receipt Inspection: Fails if sum does not match received quantity', () => {
  const res = validateGoodsReceiptInspection(100, 80, 10, 5, 'Damaged')
  assert.equal(res.valid, false)
  assert.match(res.error, /Sum of accepted/)
})

test('Goods Receipt Inspection: Fails if rejected quantity > 0 but reason is omitted', () => {
  const res = validateGoodsReceiptInspection(50, 40, 10, 0, '')
  assert.equal(res.valid, false)
  assert.match(res.error, /Rejection reason is required/)
})

test('Over-Receipt Prevention: Blocks receiving beyond remaining order quantity without tolerance', () => {
  // Ordered 100, 70 already received. Client attempts to receive 35.
  const check = validateOverReceipt(100, 70, 35, 0)
  assert.equal(check.allowed, false)
  assert.equal(check.remaining, 30)
  assert.equal(check.exceededBy, 5)
})

test('Over-Receipt Prevention: Allows receiving within exact remaining quantity', () => {
  // Ordered 100, 70 already received. Client receives exactly 30.
  const check = validateOverReceipt(100, 70, 30, 0)
  assert.equal(check.allowed, true)
  assert.equal(check.remaining, 0)
  assert.equal(check.exceededBy, 0)
})

test('Over-Receipt Prevention: Configured tolerance permits audited overage within threshold', () => {
  // Ordered 100, 0 received, 5% tolerance allows up to 105.
  const check1 = validateOverReceipt(100, 0, 104, 5)
  assert.equal(check1.allowed, true)

  const check2 = validateOverReceipt(100, 0, 106, 5)
  assert.equal(check2.allowed, false)
  assert.equal(check2.exceededBy, 1)
})
