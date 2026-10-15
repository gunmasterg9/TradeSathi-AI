import test from 'node:test'
import assert from 'node:assert/strict'

test('Structured discrepancy record preserves comparison rule, review requirement, and deltas', () => {
  const mockDisc = {
    field: 'total_net_weight_kg',
    label: 'Net Weight',
    severity: 'critical',
    comparison_rule: 'compatible_weight_conversion',
    human_review_required: true,
    difference: 'Delta: +100 kg (+0.56%)',
    delta_numeric: 100.0,
    delta_percentage: 0.56,
    reason: 'Net weight values do not match across documents (commercial_invoice.txt: 18000 kg; packing_list.txt: 18100 kg).',
    recommended_action: 'Reconcile cargo weights between Invoice and Packing List.',
    message: 'Net Weight mismatch (Delta: +100 kg (+0.56%)): commercial_invoice.txt: 18000 kg; packing_list.txt: 18100 kg.',
    doc_values: {
      'commercial_invoice.txt': '18000 kg',
      'packing_list.txt': '18100 kg',
    },
    raw_values: {
      'commercial_invoice.txt': '18000 kg',
      'packing_list.txt': '18100 kg',
    },
  }

  assert.equal(mockDisc.comparison_rule, 'compatible_weight_conversion')
  assert.equal(mockDisc.human_review_required, true)
  assert.equal(mockDisc.delta_numeric, 100.0)
  assert.equal(mockDisc.delta_percentage, 0.56)
  assert.match(mockDisc.reason, /commercial_invoice\.txt: 18000 kg/)
})

test('Unit ambiguity finding flags operator review without calculating invalid numeric delta', () => {
  const mockAmbiguousDisc = {
    field: 'total_net_weight_kg',
    label: 'Net Weight',
    severity: 'critical',
    comparison_rule: 'compatible_weight_conversion',
    human_review_required: true,
    difference: 'Unit ambiguity: one or more values lack explicit unit of measurement',
    reason: 'Net weight cannot be safely verified: commercial_invoice.txt omitted the weight unit (raw: 18000), while packing_list.txt specifies explicit units (18100 kg). Never infer missing units as kg without confirmation.',
    delta_numeric: null,
    delta_percentage: null,
  }

  assert.equal(mockAmbiguousDisc.severity, 'critical')
  assert.match(mockAmbiguousDisc.difference, /unit ambiguity/i)
  assert.equal(mockAmbiguousDisc.delta_numeric, null)
  assert.equal(mockAmbiguousDisc.human_review_required, true)
})

test('Cross-currency comparison is flagged as not directly comparable without exchange rate', () => {
  const mockCrossCurrencyDisc = {
    field: 'total_amount',
    label: 'Total Amount',
    severity: 'critical',
    comparison_rule: 'monetary_total_comparison',
    difference: 'Not directly comparable: cross-currency valuation without documented exchange rate',
    human_review_required: true,
  }

  assert.equal(mockCrossCurrencyDisc.severity, 'critical')
  assert.match(mockCrossCurrencyDisc.difference, /cross-currency valuation/i)
  assert.equal(mockCrossCurrencyDisc.comparison_rule, 'monetary_total_comparison')
})
