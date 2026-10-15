import test from 'node:test'
import assert from 'node:assert/strict'
import {
  normalizeDimensionToMeters,
  normalizeWeightToKg,
  convertKgToLb,
  convertCbmToCuft,
  calculateCargoLine,
  calculateCargoAggregate,
  estimateContainerCapacity,
  generateCargoCsv,
} from '../src/cbmHelper.js'

test('Normalizes dimensions to meters correctly', () => {
  assert.equal(normalizeDimensionToMeters(100, 'cm'), 1.0)
  assert.equal(normalizeDimensionToMeters(1000, 'mm'), 1.0)
  assert.equal(normalizeDimensionToMeters(1, 'm'), 1.0)
  assert.ok(Math.abs(normalizeDimensionToMeters(1, 'inch') - 0.0254) < 1e-6)
  assert.ok(Math.abs(normalizeDimensionToMeters(1, 'feet') - 0.3048) < 1e-6)
})

test('Rejects invalid, zero, or negative dimensions', () => {
  assert.throws(() => normalizeDimensionToMeters(0, 'cm'), /positive finite/)
  assert.throws(() => normalizeDimensionToMeters(-10, 'cm'), /positive finite/)
  assert.throws(() => normalizeDimensionToMeters(NaN, 'cm'), /positive finite/)
})

test('Weight conversions between kg and lb', () => {
  const kg = 100
  const lb = convertKgToLb(kg)
  assert.ok(Math.abs(lb - 220.46226218) < 1e-5)
  assert.ok(Math.abs(normalizeWeightToKg(lb, 'lb') - 100) < 1e-5)
})

test('CBM conversion to cubic feet', () => {
  const cbm = 1.0
  const cuft = convertCbmToCuft(cbm)
  assert.ok(Math.abs(cuft - 35.3146667) < 1e-5)
})

test('Single carton calculation: 60x40x30 cm, 12 kg, qty 10, divisor 6000', () => {
  const line = {
    description: 'Carton Test',
    length: 60,
    width: 40,
    height: 30,
    dimension_unit: 'cm',
    gross_weight_per_pkg: 12,
    weight_unit: 'kg',
    quantity: 10,
  }
  const result = calculateCargoLine(line, 6000)
  assert.ok(Math.abs(result.cbm_per_pkg - 0.072) < 1e-6)
  assert.ok(Math.abs(result.total_cbm - 0.72) < 1e-6)
  assert.equal(result.total_gross_weight_kg, 120)
  assert.equal(result.volumetric_weight_kg, 120)
})

test('Aggregate cargo lines calculation and chargeable weight', () => {
  const lines = [
    {
      description: 'Carton A',
      length: 60,
      width: 40,
      height: 30,
      dimension_unit: 'cm',
      gross_weight_per_pkg: 10,
      weight_unit: 'kg',
      quantity: 5,
    },
    {
      description: 'Carton B',
      length: 50,
      width: 50,
      height: 50,
      dimension_unit: 'cm',
      gross_weight_per_pkg: 15,
      weight_unit: 'kg',
      quantity: 2,
    },
  ]
  const agg = calculateCargoAggregate(lines, 'air', 5000)
  assert.equal(agg.total_packages, 7)
  assert.ok(agg.total_cbm > 0)
  assert.ok(agg.chargeable_weight_kg >= agg.total_gross_weight_kg)
})

test('Container capacity estimator geometric grid and volume limit', () => {
  const est20ft = estimateContainerCapacity(0.6, 0.4, 0.3, 12, 0.85)
  assert.ok(est20ft.estimated_units_by_volume > 0)
  assert.ok(est20ft.estimated_units_by_grid > 0)
  assert.ok(est20ft.does_fit_geometrically)
  assert.equal(est20ft.payload_feasibility, 'Unknown')
})

test('CSV export generator produces expected format with header and totals', () => {
  const agg = calculateCargoAggregate([
    {
      description: 'Standard Box',
      sku: 'SKU-001',
      length: 50,
      width: 40,
      height: 30,
      dimension_unit: 'cm',
      gross_weight_per_pkg: 10,
      weight_unit: 'kg',
      quantity: 4,
    },
  ])
  const csv = generateCargoCsv(agg, 'Test Order')
  assert.match(csv, /Standard Box/)
  assert.match(csv, /SKU-001/)
  assert.match(csv, /TOTALS \/ AGGREGATE/)
})
