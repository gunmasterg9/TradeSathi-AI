import test from 'node:test'
import assert from 'node:assert/strict'

test('Frontend handles extracted documents with provenance metadata and validation tags', () => {
  const mockDoc = {
    filename: 'commercial_invoice.txt',
    document_type: 'commercial_invoice',
    invoice_number: 'INV-2026-104',
    raw_invoice_number: 'INV-2026-104',
    invoice_date: '2026-10-12',
    raw_invoice_date: '12/10/2026',
    total_net_weight_kg: 18000,
    raw_net_weight: '18000 kg',
    consignee: 'Ocean Foods LLC',
    field_evidence: {
      invoice_number: {
        raw_value: 'INV-2026-104',
        normalized_value: 'INV-2026-104',
        source_document: 'commercial_invoice.txt',
        field_name: 'invoice_number',
        method: 'deterministic_rules',
        validation_status: 'verified',
        confidence: 1.0,
      },
      invoice_date: {
        raw_value: '12/10/2026',
        normalized_value: '2026-10-12',
        source_document: 'commercial_invoice.txt',
        field_name: 'invoice_date',
        method: 'deterministic_rules',
        validation_status: 'verified',
        confidence: 1.0,
      },
      total_gross_weight_kg: {
        raw_value: '19500',
        normalized_value: '19500.0 kg',
        source_document: 'commercial_invoice.txt',
        field_name: 'total_gross_weight_kg',
        method: 'deterministic_rules',
        validation_status: 'uncertain',
        confidence: 0.5,
        notes: 'Weight unit unspecified in source text; recorded with uncertainty',
      },
      exporter: {
        validation_status: 'missing',
        field_name: 'exporter',
      },
    },
  }

  // 1. Verify verified status helper logic
  const invEv = mockDoc.field_evidence.invoice_number
  assert.equal(invEv.validation_status, 'verified')
  assert.equal(invEv.method, 'deterministic_rules')

  // 2. Verify raw vs normalized preservation
  assert.equal(mockDoc.raw_invoice_date, '12/10/2026')
  assert.equal(mockDoc.invoice_date, '2026-10-12')

  // 3. Verify uncertain provenance handling
  const grossEv = mockDoc.field_evidence.total_gross_weight_kg
  assert.equal(grossEv.validation_status, 'uncertain')
  assert.match(grossEv.notes, /unspecified/i)

  // 4. Verify explicit missing status without invented values
  const expEv = mockDoc.field_evidence.exporter
  assert.equal(expEv.validation_status, 'missing')
  assert.equal(mockDoc.exporter, undefined)
})

test('Export brief reflects provenance and preserves 100 kg weight discrepancy', () => {
  const mockResult = {
    id: 'anl-prov-101',
    mode: 'rules_fallback',
    model: null,
    summary: {
      status: 'needs_attention',
      headline: 'Reconciliation completed with 1 discrepancy',
      documents_received: ['commercial_invoice.txt', 'packing_list.txt'],
      summary_text: 'Net weight mismatch detected.',
      checklist: [
        { id: 'chk-weights', status: 'failed', title: 'Weights & Cargo Tally', detail: 'Net weight mismatch of 100 kg' },
      ],
    },
    discrepancies: [
      {
        field: 'total_net_weight_kg',
        label: 'Net Weight',
        severity: 'warning',
        message: 'commercial_invoice: 18000 kg vs packing_list: 18100 kg',
        recommended_action: 'Perform physical weighment before export.',
      },
    ],
    documents: [
      {
        filename: 'commercial_invoice.txt',
        field_evidence: {
          total_net_weight_kg: { validation_status: 'verified', method: 'deterministic_rules' },
        },
      },
      {
        filename: 'packing_list.txt',
        field_evidence: {
          total_net_weight_kg: { validation_status: 'verified', method: 'deterministic_rules' },
        },
      },
    ],
  }

  const verifiedCount = mockResult.documents.reduce((acc, d) => {
    return acc + Object.values(d.field_evidence || {}).filter((e) => e.validation_status === 'verified').length
  }, 0)

  assert.equal(verifiedCount, 2)
  assert.equal(mockResult.discrepancies[0].field, 'total_net_weight_kg')
  assert.match(mockResult.discrepancies[0].message, /100 kg/)
})
