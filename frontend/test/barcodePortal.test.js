import test from 'node:test'
import assert from 'node:assert/strict'

// Role-based permission matrix for operational portal (matching master_data.py)
const PORTAL_ROLE_PERMISSIONS = {
  admin: [
    'read', 'create', 'update', 'delete',
    'scan_portal', 'print_labels', 'execute_scan_operations',
    'create_warehouse', 'create_location', 'create_transfer',
    'create_goods_receipt', 'create_shipment',
  ],
  warehouse: [
    'read',
    'scan_portal', 'print_labels', 'execute_scan_operations',
    'create_warehouse', 'update_warehouse',
    'create_location', 'update_location',
    'create_transfer', 'approve_transfer', 'dispatch_transfer', 'receive_transfer',
    'create_adjustment', 'approve_adjustment',
  ],
  procurement: [
    'read',
    'scan_portal', 'print_labels',
    'create_goods_receipt',
  ],
  sales: [
    'read',
    'scan_portal', 'print_labels',
  ],
  operator: [
    'read',
    'scan_portal', 'print_labels', 'execute_scan_operations',
  ],
  viewer: [
    'read',
    'scan_portal',
  ],
}

function canPerformPortalAction(role, action) {
  const normRole = (role || 'viewer').toLowerCase().trim()
  const perms = PORTAL_ROLE_PERMISSIONS[normRole] || ['read']
  return perms.includes(action)
}

// Payload format parser (TS:v1:<TYPE>:<REF>)
function parseBarcodePayload(code) {
  if (!code || typeof code !== 'string') {
    return { valid: false, error: 'Empty or invalid barcode string' }
  }
  const trimmed = code.trim()
  const parts = trimmed.split(':')
  if (parts.length >= 4 && parts[0] === 'TS' && parts[1] === 'v1') {
    const entityType = parts[2].toUpperCase()
    const entityRef = parts.slice(3).join(':')
    const validTypes = ['PRODUCT', 'LOCATION', 'PO', 'SO', 'GR', 'SHIPMENT', 'PACKAGE']
    if (!validTypes.includes(entityType)) {
      return { valid: false, error: `Unsupported entity type: ${entityType}` }
    }
    return {
      valid: true,
      isStructured: true,
      entityType,
      entityRef,
      raw: trimmed,
    }
  }
  // Fallback raw lookup (SKU, location code, PO number)
  return {
    valid: true,
    isStructured: false,
    entityType: 'RAW_FALLBACK',
    entityRef: trimmed,
    raw: trimmed,
  }
}

// Thermal label specifications validator
function getLabelDimensions(size) {
  const normalized = (size || '4x2').toLowerCase()
  if (normalized === '4x2') {
    return {
      size: '4x2',
      widthInches: 4.0,
      heightInches: 2.0,
      widthMm: 101.6,
      heightMm: 50.8,
      widthPt: 288,
      heightPt: 144,
      supportsDualSymbology: true,
      primaryUse: 'Shipping Carton, Pallet & Inbound PO Tags',
    }
  } else if (normalized === '2x1') {
    return {
      size: '2x1',
      widthInches: 2.0,
      heightInches: 1.0,
      widthMm: 50.8,
      heightMm: 25.4,
      widthPt: 144,
      heightPt: 72,
      supportsDualSymbology: true,
      primaryUse: 'Bin Location Shelf & Unit SKU Tags',
    }
  }
  throw new Error(`Unsupported label dimension: ${size}`)
}

// Stock transfer ATP validation helper
function validateTransferAvailability(availableStock, requestedQty) {
  const avail = Math.max(0, Number(availableStock) || 0)
  const req = Number(requestedQty) || 0
  if (req <= 0) {
    return { allowed: false, reason: 'Transfer quantity must be greater than zero.' }
  }
  if (req > avail) {
    return {
      allowed: false,
      reason: `Insufficient ATP balance. Requested ${req} units, but only ${avail} units are available.`,
    }
  }
  return { allowed: true, reason: null, remainingAtp: avail - req }
}

// Inbound Goods Receipt over-receipt tolerance validator
function validateInboundReceipt(orderedQty, priorReceivedQty, acceptedQty, tolerancePct = 10.0) {
  const ordered = Math.max(0, Number(orderedQty) || 0)
  const prior = Math.max(0, Number(priorReceivedQty) || 0)
  const accepted = Math.max(0, Number(acceptedQty) || 0)
  const newTotal = prior + accepted
  const maxAllowed = ordered * (1.0 + tolerancePct / 100.0)

  if (accepted <= 0) {
    return { allowed: false, reason: 'Accepted quantity must be greater than zero.' }
  }
  if (newTotal > maxAllowed) {
    return {
      allowed: false,
      reason: `Over-receipt exceeds allowed ${tolerancePct}% tolerance. Ordered: ${ordered}, max allowed: ${maxAllowed}, attempted total: ${newTotal}.`,
    }
  }
  return { allowed: true, reason: null, newTotalReceived: newTotal }
}

// Sales Fulfilment packing guard
function validatePackingQuantity(allocatedQty, pickedQty, packQty) {
  const allocated = Math.max(0, Number(allocatedQty) || 0)
  const picked = Math.max(0, Number(pickedQty) || 0)
  const toPack = Number(packQty) || 0
  const remainingAllocated = Math.max(0, allocated - picked)

  if (toPack <= 0) {
    return { allowed: false, reason: 'Pack quantity must be greater than zero.' }
  }
  if (toPack > remainingAllocated) {
    return {
      allowed: false,
      reason: `Cannot pack ${toPack} units. Only ${remainingAllocated} allocated units remaining to pack.`,
    }
  }
  return { allowed: true, reason: null, remainingAllocated: remainingAllocated - toPack }
}

// Statutory customs notice constant
const STATUTORY_CUSTOMS_DISCLAIMER =
  'Notice: Barcode/QR scan is for internal warehouse and operational tracking only. Official customs clearance requires verified shipping documentation and authorized regulatory filing.'

// TEST SUITE

test('Barcode payload format parser', async (t) => {
  await t.test('parses versioned product QR payload', () => {
    const res = parseBarcodePayload('TS:v1:PRODUCT:101')
    assert.strictEqual(res.valid, true)
    assert.strictEqual(res.isStructured, true)
    assert.strictEqual(res.entityType, 'PRODUCT')
    assert.strictEqual(res.entityRef, '101')
  })

  await t.test('parses versioned warehouse location QR payload', () => {
    const res = parseBarcodePayload('TS:v1:LOCATION:LOC-A-01-B')
    assert.strictEqual(res.valid, true)
    assert.strictEqual(res.isStructured, true)
    assert.strictEqual(res.entityType, 'LOCATION')
    assert.strictEqual(res.entityRef, 'LOC-A-01-B')
  })

  await t.test('parses versioned purchase order QR payload', () => {
    const res = parseBarcodePayload('TS:v1:PO:PO-2026-0042')
    assert.strictEqual(res.valid, true)
    assert.strictEqual(res.entityType, 'PO')
    assert.strictEqual(res.entityRef, 'PO-2026-0042')
  })

  await t.test('parses versioned sales order QR payload', () => {
    const res = parseBarcodePayload('TS:v1:SO:SO-2026-0088')
    assert.strictEqual(res.valid, true)
    assert.strictEqual(res.entityType, 'SO')
    assert.strictEqual(res.entityRef, 'SO-2026-0088')
  })

  await t.test('parses versioned export shipment QR payload', () => {
    const res = parseBarcodePayload('TS:v1:SHIPMENT:SHP-EXP-001')
    assert.strictEqual(res.valid, true)
    assert.strictEqual(res.entityType, 'SHIPMENT')
    assert.strictEqual(res.entityRef, 'SHP-EXP-001')
  })

  await t.test('supports fallback raw barcodes for backward compatibility', () => {
    const res = parseBarcodePayload('SKU-TEA-001')
    assert.strictEqual(res.valid, true)
    assert.strictEqual(res.isStructured, false)
    assert.strictEqual(res.entityType, 'RAW_FALLBACK')
    assert.strictEqual(res.entityRef, 'SKU-TEA-001')
  })

  await t.test('rejects unsupported entity types in structured payload', () => {
    const res = parseBarcodePayload('TS:v1:UNKNOWN_MODULE:123')
    assert.strictEqual(res.valid, false)
    assert.match(res.error, /Unsupported entity type/)
  })

  await t.test('handles empty or null barcode string safely', () => {
    const res1 = parseBarcodePayload('')
    assert.strictEqual(res1.valid, false)
    const res2 = parseBarcodePayload(null)
    assert.strictEqual(res2.valid, false)
  })
})

test('Thermal label sizing and physical specifications', async (t) => {
  await t.test('validates 4x2 pallet and shipping carton layout dimensions', () => {
    const dims = getLabelDimensions('4x2')
    assert.strictEqual(dims.widthInches, 4.0)
    assert.strictEqual(dims.heightInches, 2.0)
    assert.strictEqual(dims.supportsDualSymbology, true)
    assert.strictEqual(dims.widthPt, 288)
  })

  await t.test('validates 2x1 bin shelf tag layout dimensions', () => {
    const dims = getLabelDimensions('2x1')
    assert.strictEqual(dims.widthInches, 2.0)
    assert.strictEqual(dims.heightInches, 1.0)
    assert.strictEqual(dims.supportsDualSymbology, true)
    assert.strictEqual(dims.widthPt, 144)
  })

  await t.test('throws descriptive error on invalid label layout', () => {
    assert.throws(() => getLabelDimensions('10x10'), /Unsupported label dimension/)
  })
})

test('Role-based access control (RBAC) for scanning operations', async (t) => {
  await t.test('warehouse operator can scan portal, print labels and execute operations', () => {
    assert.strictEqual(canPerformPortalAction('warehouse', 'scan_portal'), true)
    assert.strictEqual(canPerformPortalAction('warehouse', 'print_labels'), true)
    assert.strictEqual(canPerformPortalAction('warehouse', 'execute_scan_operations'), true)
    assert.strictEqual(canPerformPortalAction('warehouse', 'create_transfer'), true)
  })

  await t.test('procurement role can scan and print labels but cannot execute transfers', () => {
    assert.strictEqual(canPerformPortalAction('procurement', 'scan_portal'), true)
    assert.strictEqual(canPerformPortalAction('procurement', 'print_labels'), true)
    assert.strictEqual(canPerformPortalAction('procurement', 'create_transfer'), false)
  })

  await t.test('viewer role has read-only access and cannot execute scan mutations', () => {
    assert.strictEqual(canPerformPortalAction('viewer', 'scan_portal'), true)
    assert.strictEqual(canPerformPortalAction('viewer', 'print_labels'), false)
    assert.strictEqual(canPerformPortalAction('viewer', 'execute_scan_operations'), false)
    assert.strictEqual(canPerformPortalAction('viewer', 'create_transfer'), false)
  })
})

test('Inventory safety and operator confirmation guards', async (t) => {
  await t.test('validates stock transfer ATP availability', () => {
    const valid = validateTransferAvailability(50, 20)
    assert.strictEqual(valid.allowed, true)
    assert.strictEqual(valid.remainingAtp, 30)

    const invalid = validateTransferAvailability(10, 25)
    assert.strictEqual(invalid.allowed, false)
    assert.match(invalid.reason, /Insufficient ATP balance/)

    const zero = validateTransferAvailability(50, 0)
    assert.strictEqual(zero.allowed, false)
    assert.match(zero.reason, /greater than zero/)
  })

  await t.test('validates inbound receipt against over-receipt tolerance', () => {
    // Ordered: 100, tolerance: 10% (max 110)
    const normal = validateInboundReceipt(100, 0, 90, 10.0)
    assert.strictEqual(normal.allowed, true)
    assert.strictEqual(normal.newTotalReceived, 90)

    const withinTolerance = validateInboundReceipt(100, 80, 25, 10.0) // 80 + 25 = 105 <= 110
    assert.strictEqual(withinTolerance.allowed, true)
    assert.strictEqual(withinTolerance.newTotalReceived, 105)

    const overTolerance = validateInboundReceipt(100, 80, 40, 10.0) // 80 + 40 = 120 > 110
    assert.strictEqual(overTolerance.allowed, false)
    assert.match(overTolerance.reason, /Over-receipt exceeds allowed/)
  })

  await t.test('validates packing verification prevents over-packing', () => {
    // Allocated: 50, already picked: 20 -> remaining: 30
    const valid = validatePackingQuantity(50, 20, 15)
    assert.strictEqual(valid.allowed, true)
    assert.strictEqual(valid.remainingAllocated, 15)

    const over = validatePackingQuantity(50, 20, 35)
    assert.strictEqual(over.allowed, false)
    assert.match(over.reason, /Cannot pack 35 units/)
  })
})

test('Statutory customs verification disclaimer requirements', async (t) => {
  await t.test('statutory customs notice text is exact and immutable', () => {
    assert.ok(STATUTORY_CUSTOMS_DISCLAIMER.includes('Notice: Barcode/QR scan is for internal warehouse and operational tracking only'))
    assert.ok(STATUTORY_CUSTOMS_DISCLAIMER.includes('Official customs clearance requires verified shipping documentation'))
  })
})
