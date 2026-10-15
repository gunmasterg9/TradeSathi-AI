import test from 'node:test'
import assert from 'node:assert/strict'

// Role permission matrix definition matching backend
const ROLE_PERMISSIONS = {
  admin: ['read', 'create', 'update', 'delete'],
  procurement: ['read', 'create_product', 'update_product', 'create_supplier', 'update_supplier'],
  sales: ['read', 'create_product', 'update_product', 'create_customer', 'update_customer'],
  warehouse: ['read'],
  viewer: ['read'],
}

function canPerformAction(role, action) {
  const normalized = (role || 'admin').toLowerCase().trim()
  const perms = ROLE_PERMISSIONS[normalized] || ['read']
  if (perms.includes('create') && action.startsWith('create_')) return true
  if (perms.includes('update') && action.startsWith('update_')) return true
  return perms.includes(action)
}

function normalizeSku(sku) {
  if (!sku || typeof sku !== 'string') return ''
  return sku.trim().toUpperCase()
}

function calculateGrossMargin(purchaseCost, sellingPrice) {
  if (!sellingPrice || sellingPrice <= 0) return 0
  const margin = ((sellingPrice - purchaseCost) / sellingPrice) * 100
  return Math.round(margin * 100) / 100
}

test('Role-Based Access Control: Admin has full access to all master data actions', () => {
  assert.equal(canPerformAction('admin', 'create_product'), true)
  assert.equal(canPerformAction('admin', 'delete'), true)
  assert.equal(canPerformAction('admin', 'update_supplier'), true)
})

test('Role-Based Access Control: Viewer role is strictly read-only', () => {
  assert.equal(canPerformAction('viewer', 'read'), true)
  assert.equal(canPerformAction('viewer', 'create_product'), false)
  assert.equal(canPerformAction('viewer', 'update_supplier'), false)
  assert.equal(canPerformAction('viewer', 'delete'), false)
})

test('Role-Based Access Control: Procurement can manage suppliers and products but cannot delete', () => {
  assert.equal(canPerformAction('procurement', 'create_supplier'), true)
  assert.equal(canPerformAction('procurement', 'create_product'), true)
  assert.equal(canPerformAction('procurement', 'create_customer'), false)
  assert.equal(canPerformAction('procurement', 'delete'), false)
})

test('Role-Based Access Control: Sales can manage customers and products but cannot delete', () => {
  assert.equal(canPerformAction('sales', 'create_customer'), true)
  assert.equal(canPerformAction('sales', 'create_product'), true)
  assert.equal(canPerformAction('sales', 'create_supplier'), false)
  assert.equal(canPerformAction('sales', 'delete'), false)
})

test('Product Master SKU normalization strips leading/trailing spaces and forces uppercase', () => {
  assert.equal(normalizeSku('  sku-bt-shrimp-001  '), 'SKU-BT-SHRIMP-001')
  assert.equal(normalizeSku('sku-plain'), 'SKU-PLAIN')
  assert.equal(normalizeSku(null), '')
})

test('Master data gross margin calculation correctly evaluates profit margin percentage', () => {
  // Cost 650, Price 950 -> (950 - 650) / 950 = 31.58%
  const margin = calculateGrossMargin(650, 950)
  assert.equal(margin, 31.58)

  // Zero selling price returns 0% safely without division by zero crash
  assert.equal(calculateGrossMargin(500, 0), 0)
})
