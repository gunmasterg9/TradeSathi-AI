import test from 'node:test'
import assert from 'node:assert/strict'

// Role permission matrix for warehouse & inventory management (matching backend master_data.ROLE_PERMISSIONS)
const ROLE_PERMISSIONS = {
  admin: [
    'read', 'create', 'update', 'delete',
    'create_warehouse', 'update_warehouse', 'delete_warehouse',
    'create_location', 'update_location', 'delete_location',
    'create_transfer', 'approve_transfer', 'dispatch_transfer', 'receive_transfer', 'cancel_transfer',
    'create_adjustment', 'approve_adjustment',
    'create_reservation', 'release_reservation', 'consume_reservation',
  ],
  warehouse: [
    'read',
    'create_warehouse', 'update_warehouse',
    'create_location', 'update_location',
    'create_transfer', 'approve_transfer', 'dispatch_transfer', 'receive_transfer', 'cancel_transfer',
    'create_adjustment', 'approve_adjustment',
    'create_reservation', 'consume_reservation',
  ],
  procurement: [
    'read',
    'create_transfer',
    'create_reservation', 'release_reservation',
  ],
  sales: [
    'read',
    'create_reservation', 'release_reservation',
  ],
  viewer: [
    'read',
  ],
}

function canPerformWarehouseAction(role, action) {
  const normalized = (role || 'viewer').toLowerCase().trim()
  const perms = ROLE_PERMISSIONS[normalized] || ['read']
  return perms.includes(action)
}

function calculateAvailableToPromise(availableOnHand, activeReservations) {
  const avail = Math.max(0, Number(availableOnHand) || 0)
  const res = Math.max(0, Number(activeReservations) || 0)
  return Math.max(0, Math.round((avail - res) * 1000) / 1000)
}

function validateWarehouseDeactivation(onHandStock, activeReservationsCount) {
  const stock = Number(onHandStock) || 0
  const res = Number(activeReservationsCount) || 0
  if (stock > 0 || res > 0) {
    return {
      allowed: false,
      reason: `Cannot deactivate warehouse with active stock (${stock} units) or active reservations (${res}).`,
    }
  }
  return { allowed: true, reason: null }
}

function reconcileTransferQuantities(dispatchedQty, receivedQty, damagedQty) {
  const disp = Number(dispatchedQty) || 0
  const rec = Number(receivedQty) || 0
  const dmg = Number(damagedQty) || 0

  if (rec < 0 || dmg < 0) {
    return { valid: false, error: 'Quantities cannot be negative' }
  }
  if (rec + dmg > disp) {
    return { valid: false, error: 'Received and damaged sum cannot exceed dispatched quantity' }
  }

  const shortage = Math.round((disp - (rec + dmg)) * 1000) / 1000
  const hasDiscrepancy = (dmg > 0 || shortage > 0)

  return {
    valid: true,
    dispatched: disp,
    received: rec,
    damaged: dmg,
    shortage: shortage,
    hasDiscrepancy: hasDiscrepancy,
    finalStatus: hasDiscrepancy ? 'discrepancy' : 'received',
  }
}

function calculateAdjustmentVariance(systemQty, countedQty) {
  const sys = Number(systemQty) || 0
  const counted = Number(countedQty) || 0
  if (counted < 0) {
    return { valid: false, error: 'Counted quantity cannot be negative' }
  }
  const variance = Math.round((counted - sys) * 1000) / 1000
  return {
    valid: true,
    systemQuantity: sys,
    countedQuantity: counted,
    variance: variance,
    isWriteOff: variance < 0,
    isSurplus: variance > 0,
  }
}

// Tests
test('Available to Promise (ATP): Deducts active reservations from available on-hand stock', () => {
  // Available 100, Reserved 35 -> ATP = 65
  const atp1 = calculateAvailableToPromise(100, 35)
  assert.equal(atp1, 65)

  // Over-reserved condition floors to 0
  const atp2 = calculateAvailableToPromise(20, 25)
  assert.equal(atp2, 0)
})

test('Safe Warehouse Deactivation: Blocks deactivation when warehouse has active stock or reservations', () => {
  const check1 = validateWarehouseDeactivation(50, 0)
  assert.equal(check1.allowed, false)
  assert.match(check1.reason, /active stock/)

  const check2 = validateWarehouseDeactivation(0, 2)
  assert.equal(check2.allowed, false)
  assert.match(check2.reason, /active reservations/)

  const check3 = validateWarehouseDeactivation(0, 0)
  assert.equal(check3.allowed, true)
})

test('Stock Transfer Reconciliation: Full receipt without damage has 0 shortage and received status', () => {
  const res = reconcileTransferQuantities(50, 50, 0)
  assert.equal(res.valid, true)
  assert.equal(res.shortage, 0)
  assert.equal(res.hasDiscrepancy, false)
  assert.equal(res.finalStatus, 'received')
})

test('Stock Transfer Reconciliation: Partial delivery with damage and shortage flags discrepancy status', () => {
  // Dispatched 50, Received 42, Damaged 5 -> Shortage = 3
  const res = reconcileTransferQuantities(50, 42, 5)
  assert.equal(res.valid, true)
  assert.equal(res.shortage, 3)
  assert.equal(res.hasDiscrepancy, true)
  assert.equal(res.finalStatus, 'discrepancy')
})

test('Stock Transfer Validation: Rejects receiving more than dispatched quantity', () => {
  const res = reconcileTransferQuantities(30, 25, 10) // 25 + 10 = 35 > 30
  assert.equal(res.valid, false)
  assert.match(res.error, /cannot exceed dispatched/)
})

test('Inventory Adjustment Variance: Correctly evaluates difference and write-off vs surplus', () => {
  // System 50, Counted 48 -> -2 write-off
  const adj1 = calculateAdjustmentVariance(50, 48)
  assert.equal(adj1.valid, true)
  assert.equal(adj1.variance, -2)
  assert.equal(adj1.isWriteOff, true)
  assert.equal(adj1.isSurplus, false)

  // System 40, Counted 45 -> +5 surplus
  const adj2 = calculateAdjustmentVariance(40, 45)
  assert.equal(adj2.valid, true)
  assert.equal(adj2.variance, 5)
  assert.equal(adj2.isWriteOff, false)
  assert.equal(adj2.isSurplus, true)
})

test('Role Permissions: Warehouse role can manage transfers, adjustments, and warehouses', () => {
  assert.equal(canPerformWarehouseAction('warehouse', 'create_transfer'), true)
  assert.equal(canPerformWarehouseAction('warehouse', 'dispatch_transfer'), true)
  assert.equal(canPerformWarehouseAction('warehouse', 'receive_transfer'), true)
  assert.equal(canPerformWarehouseAction('warehouse', 'create_adjustment'), true)
  assert.equal(canPerformWarehouseAction('warehouse', 'approve_adjustment'), true)
})

test('Role Permissions: Sales role can create/release reservations but cannot dispatch transfers', () => {
  assert.equal(canPerformWarehouseAction('sales', 'create_reservation'), true)
  assert.equal(canPerformWarehouseAction('sales', 'release_reservation'), true)
  assert.equal(canPerformWarehouseAction('sales', 'dispatch_transfer'), false)
  assert.equal(canPerformWarehouseAction('sales', 'approve_adjustment'), false)
})

test('Role Permissions: Viewer is strictly read-only', () => {
  assert.equal(canPerformWarehouseAction('viewer', 'read'), true)
  assert.equal(canPerformWarehouseAction('viewer', 'create_warehouse'), false)
  assert.equal(canPerformWarehouseAction('viewer', 'create_transfer'), false)
  assert.equal(canPerformWarehouseAction('viewer', 'create_reservation'), false)
})
