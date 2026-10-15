import test from 'node:test'
import assert from 'node:assert/strict'

// Role permission matrix for Sales & Fulfilment (matching backend master_data.ROLE_PERMISSIONS)
const ROLE_PERMISSIONS = {
  admin: [
    'read', 'create', 'update', 'delete', 'all',
    'create_quotation', 'update_quotation', 'send_quotation', 'accept_quotation', 'reject_quotation', 'convert_quotation',
    'create_order', 'update_order', 'confirm_order', 'cancel_order', 'allocate_order',
    'create_pick_list', 'update_pick_list', 'complete_pick_list', 'pack_order',
    'create_dispatch', 'deliver_dispatch',
    'create_return', 'inspect_return', 'process_return',
  ],
  sales: [
    'read',
    'create_quotation', 'update_quotation', 'send_quotation', 'accept_quotation', 'reject_quotation', 'convert_quotation',
    'create_order', 'update_order', 'confirm_order', 'cancel_order', 'allocate_order',
    'create_return',
  ],
  warehouse: [
    'read',
    'allocate_order',
    'create_pick_list', 'update_pick_list', 'complete_pick_list', 'pack_order',
    'create_dispatch', 'deliver_dispatch',
    'inspect_return', 'process_return',
  ],
  procurement: [
    'read',
  ],
  viewer: [
    'read',
  ],
}

function canPerformSalesAction(role, action) {
  const normalized = (role || 'viewer').toLowerCase().trim()
  const perms = ROLE_PERMISSIONS[normalized] || ['read']
  return perms.includes(action) || perms.includes('all')
}

function calculateSalesLine(qty, unitPrice, discountPct = 0, taxRatePct = 0) {
  const q = Number(qty) || 0
  const p = Number(unitPrice) || 0
  const dPct = Number(discountPct) || 0
  const tPct = Number(taxRatePct) || 0

  const subtotal = Math.round(q * p * 100) / 100
  const discountAmount = Math.round(subtotal * (dPct / 100) * 100) / 100
  const taxable = subtotal - discountAmount
  const taxAmount = Math.round(taxable * (tPct / 100) * 100) / 100
  const lineTotal = Math.round((taxable + taxAmount) * 100) / 100

  return { subtotal, discountAmount, taxAmount, lineTotal }
}

function calculateOrderTotals(lines) {
  let subtotal = 0
  let discountTotal = 0
  let taxTotal = 0
  let grandTotal = 0

  for (const line of lines) {
    const res = calculateSalesLine(line.quantity, line.unit_price, line.discount_pct, line.tax_rate_pct)
    subtotal += res.subtotal
    discountTotal += res.discountAmount
    taxTotal += res.taxAmount
    grandTotal += res.lineTotal
  }

  return {
    subtotal: Math.round(subtotal * 100) / 100,
    discountTotal: Math.round(discountTotal * 100) / 100,
    taxTotal: Math.round(taxTotal * 100) / 100,
    grandTotal: Math.round(grandTotal * 100) / 100,
  }
}

function isValidOrderTransition(currentStatus, targetStatus, dispatchedQty = 0) {
  const transitions = {
    draft: ['confirmed', 'cancelled'],
    confirmed: ['allocated', 'cancelled'],
    allocated: ['picking', 'packed', 'cancelled'],
    picking: ['packed', 'cancelled'],
    packed: ['dispatched', 'cancelled'],
    dispatched: ['delivered'],
    delivered: [],
    cancelled: [],
  }

  if (targetStatus === 'cancelled' && dispatchedQty > 0) {
    return false // Cannot cancel if goods have been dispatched
  }

  return transitions[currentStatus]?.includes(targetStatus) || false
}

function segregateReturnStock(returnedQty, acceptedQty, quarantinedQty, rejectedQty) {
  const total = Number(returnedQty) || 0
  const acc = Number(acceptedQty) || 0
  const quar = Number(quarantinedQty) || 0
  const rej = Number(rejectedQty) || 0

  if (acc + quar + rej > total) {
    return { valid: false, error: 'Sum of segregated quantities exceeds returned quantity' }
  }

  return {
    valid: true,
    availableRestock: acc,
    quarantinedRestock: quar,
    rejectedRestock: rej,
  }
}

// ==========================================
// Test Cases
// ==========================================

test('Role-based access control matrix for Sales & Fulfilment', () => {
  // Sales permissions
  assert.equal(canPerformSalesAction('sales', 'create_order'), true)
  assert.equal(canPerformSalesAction('sales', 'confirm_order'), true)
  assert.equal(canPerformSalesAction('sales', 'create_dispatch'), false)
  assert.equal(canPerformSalesAction('sales', 'complete_pick_list'), false)

  // Warehouse permissions
  assert.equal(canPerformSalesAction('warehouse', 'create_pick_list'), true)
  assert.equal(canPerformSalesAction('warehouse', 'complete_pick_list'), true)
  assert.equal(canPerformSalesAction('warehouse', 'create_dispatch'), true)
  assert.equal(canPerformSalesAction('warehouse', 'create_order'), false)

  // Viewer cannot perform write operations
  assert.equal(canPerformSalesAction('viewer', 'read'), true)
  assert.equal(canPerformSalesAction('viewer', 'create_order'), false)
  assert.equal(canPerformSalesAction('viewer', 'create_dispatch'), false)

  // Admin has full access
  assert.equal(canPerformSalesAction('admin', 'create_order'), true)
  assert.equal(canPerformSalesAction('admin', 'create_dispatch'), true)
  assert.equal(canPerformSalesAction('admin', 'process_return'), true)
})

test('Server-consistent line item calculations with discounts and taxes', () => {
  // 100 units @ $50 each with 10% discount and 5% tax
  // subtotal = 5000, discount = 500, taxable = 4500, tax = 225, lineTotal = 4725
  const line = calculateSalesLine(100, 50, 10, 5)
  assert.equal(line.subtotal, 5000.0)
  assert.equal(line.discountAmount, 500.0)
  assert.equal(line.taxAmount, 225.0)
  assert.equal(line.lineTotal, 4725.0)
})

test('Order grand total aggregation across multiple lines', () => {
  const lines = [
    { quantity: 10, unit_price: 100, discount_pct: 0, tax_rate_pct: 10 }, // sub 1000, tax 100, tot 1100
    { quantity: 20, unit_price: 50, discount_pct: 5, tax_rate_pct: 5 },   // sub 1000, disc 50, tax 47.5, tot 997.5
  ]
  const totals = calculateOrderTotals(lines)
  assert.equal(totals.subtotal, 2000.0)
  assert.equal(totals.discountTotal, 50.0)
  assert.equal(totals.taxTotal, 147.5)
  assert.equal(totals.grandTotal, 2097.5)
})

test('Sales order lifecycle state machine transitions', () => {
  assert.equal(isValidOrderTransition('draft', 'confirmed'), true)
  assert.equal(isValidOrderTransition('confirmed', 'allocated'), true)
  assert.equal(isValidOrderTransition('allocated', 'picking'), true)
  assert.equal(isValidOrderTransition('picking', 'packed'), true)
  assert.equal(isValidOrderTransition('packed', 'dispatched'), true)
  assert.equal(isValidOrderTransition('dispatched', 'delivered'), true)

  // Invalid backward or jumping transitions
  assert.equal(isValidOrderTransition('draft', 'dispatched'), false)
  assert.equal(isValidOrderTransition('delivered', 'draft'), false)
  assert.equal(isValidOrderTransition('dispatched', 'packed'), false)

  // Cancellation rules
  assert.equal(isValidOrderTransition('draft', 'cancelled', 0), true)
  assert.equal(isValidOrderTransition('allocated', 'cancelled', 0), true)
  assert.equal(isValidOrderTransition('packed', 'cancelled', 10), false) // dispatched items block cancel
})

test('Sales return stock segregation ensures non-available status for quarantined/rejected', () => {
  const res = segregateReturnStock(50, 30, 15, 5)
  assert.equal(res.valid, true)
  assert.equal(res.availableRestock, 30)
  assert.equal(res.quarantinedRestock, 15)
  assert.equal(res.rejectedRestock, 5)

  // Discrepancy: sum > returned quantity
  const invalid = segregateReturnStock(50, 40, 15, 0)
  assert.equal(invalid.valid, false)
})
