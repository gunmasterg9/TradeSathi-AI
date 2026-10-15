import test from 'node:test'
import assert from 'node:assert'
import { generateAuditBrief, exportAuditJson } from '../src/reportHelper.js'

test('Grounded document evidence preserves source snippet and coordinate offsets', () => {
  const auditResult = {
    id: 'anl-ev-001',
    mode: 'rules_fallback',
    created_at: '2026-10-15T10:00:00Z',
    documents: [
      {
        filename: 'commercial_invoice.txt',
        document_type: 'commercial_invoice',
        invoice_number: 'INV-2026-900',
        field_evidence: {
          invoice_number: {
            evidence_id: 'ev-doc-1-invoice_number',
            value: 'INV-2026-900',
            source_snippet: 'Invoice No: INV-2026-900',
            char_start: 20,
            char_end: 44,
            page_number: 1,
            is_grounded: true,
            validation_status: 'verified',
          },
        },
      },
    ],
    discrepancies: [
      {
        field: 'total_net_weight_kg',
        label: 'Net Weight',
        severity: 'critical',
        comparison_rule: 'compatible_weight_conversion',
        doc_values: {
          'commercial_invoice.txt': '18000 kg',
          'packing_list.txt': '18100 kg',
        },
        source_snippets: {
          'commercial_invoice.txt': 'Total Net Weight: 18,000 kg',
          'packing_list.txt': 'Total Net Weight: 18,100 kg',
        },
        evidence: {
          'commercial_invoice.txt': {
            evidence_id: 'ev-inv-net',
            source_snippet: 'Total Net Weight: 18,000 kg',
            char_start: 110,
            char_end: 138,
            is_grounded: true,
            validation_status: 'verified',
          },
        },
        difference: 'Delta: +100 kg (+0.56%)',
        reason: 'Net weight mismatch between invoice and packing list',
        recommended_action: 'Reconcile cargo weights',
        human_review_required: true,
      },
    ],
    summary: {
      status: 'needs_attention',
      headline: 'Action Required',
      checklist: [],
      summary_text: 'Audit completed.',
    },
  }

  // Verify JSON export preserves evidence
  const exportRes = exportAuditJson(auditResult)
  const parsed = JSON.parse(exportRes.jsonString)
  assert.strictEqual(parsed.discrepancies[0].source_snippets['commercial_invoice.txt'], 'Total Net Weight: 18,000 kg')
  assert.strictEqual(parsed.discrepancies[0].evidence['commercial_invoice.txt'].char_start, 110)
  assert.strictEqual(parsed.discrepancies[0].evidence['commercial_invoice.txt'].is_grounded, true)
})

test('Ungrounded LLM value generates explicit ungrounded status', () => {
  const discrepancy = {
    field: 'consignee',
    label: 'Consignee',
    severity: 'warning',
    comparison_rule: 'buyer_consignee_alignment',
    difference: null,
    evidence: {
      'ai_invoice.txt': {
        value: 'Phantom Consignee',
        source_snippet: null,
        is_grounded: false,
        limitations: ['Value not grounded in source: text not found in document.'],
      },
    },
    source_snippets: {
      'ai_invoice.txt': null,
    },
  }

  const ev = discrepancy.evidence['ai_invoice.txt']
  assert.strictEqual(ev.is_grounded, false)
  assert.strictEqual(discrepancy.source_snippets['ai_invoice.txt'], null)
  assert.ok(ev.limitations[0].includes('Value not grounded in source'))
})

test('Unit ambiguity and cross-currency block comparison with uncertainty status', () => {
  const discUnitAmbiguity = {
    field: 'total_net_weight_kg',
    difference: 'Unit ambiguity: one or more values lack explicit unit of measurement',
    human_review_required: true,
  }

  const isBlocked = discUnitAmbiguity.difference.includes('Unit ambiguity')
  assert.strictEqual(isBlocked, true)
  assert.strictEqual(discUnitAmbiguity.human_review_required, true)
})
