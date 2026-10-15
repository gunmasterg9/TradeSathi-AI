import test from 'node:test'
import assert from 'node:assert/strict'
import { generateAuditBrief, exportAuditJson, HUMAN_REVIEW_DISCLAIMER } from '../src/reportHelper.js'

test('generateAuditBrief creates complete brief with shipment ref and disclaimer', () => {
  const historicalAudit = {
    id: 'anl-hist-101',
    created_at: '2026-10-12T14:30:00Z',
    mode: 'rules_fallback',
    model: null,
    shipment_reference: 'SHP-2026-EXPORT-99',
    summary: {
      status: 'needs_attention',
      headline: 'Reconciliation detected HS code variance',
      documents_received: ['commercial_invoice.txt', 'packing_list.txt'],
      summary_text: 'Tariff code mismatch requires broker validation.',
      checklist: [
        { id: 'chk-customs', status: 'needs_review', title: 'Customs & Port Routing', detail: 'HS code 0303.89 vs 0303.89.10' },
      ],
    },
    discrepancies: [
      {
        field: 'hs_code',
        label: 'HS Code',
        severity: 'warning',
        message: 'commercial_invoice: 0303.89 vs packing_list: 0303.89.10',
        recommended_action: 'Align with 8-digit tariff schedule before declaration.',
      },
    ],
  }

  const brief = generateAuditBrief(historicalAudit)

  // Verify ID and status
  assert.match(brief, /=== TRADESATHI AI SHIPMENT AUDIT BRIEF ===/)
  assert.match(brief, /ID: anl-hist-101/)
  assert.match(brief, /Status: NEEDS_ATTENTION/)
  // Verify shipment reference and timestamp
  assert.match(brief, /Shipment Reference: SHP-2026-EXPORT-99/)
  assert.match(brief, /Audit Timestamp: 2026-10-12T14:30:00Z/)
  // Verify checklist and discrepancy
  assert.match(brief, /Customs & Port Routing/)
  assert.match(brief, /Align with 8-digit tariff schedule/)
  // Verify disclaimer explicitly forbids statutory customs clearance representation
  assert.match(brief, /not a statutory customs clearance or legal certification/)
  assert.match(brief, /Human sign-off required prior to customs lodgement/)
})

test('generateAuditBrief handles standalone audit with clean fallback scope', () => {
  const standaloneAudit = {
    id: 'anl-standalone-88',
    mode: 'ollama',
    model: 'qwen2.5',
    summary: {
      status: 'ready_for_review',
      headline: 'Clean trade audit',
      documents_received: ['doc1.txt'],
      summary_text: 'All matching.',
      checklist: [],
    },
    discrepancies: [],
  }

  const brief = generateAuditBrief(standaloneAudit)
  assert.match(brief, /Scope: Standalone Audit/)
  assert.match(brief, /Mode: ollama \(qwen2.5\)/)
  assert.match(brief, /Status: READY_FOR_REVIEW/)
})

test('exportAuditJson accurately isolates selected historical audit without data loss', () => {
  const selectedAudit = {
    id: 'anl-hist-selected',
    created_at: '2026-10-11T09:00:00Z',
    shipment_id: 'shp-12345',
    shipment_reference: 'SHP-IN-2026-001',
    mode: 'rules_fallback',
    summary: { status: 'needs_attention', headline: 'Selected Historical Audit' },
    discrepancies: [{ field: 'total_gross_weight_kg', difference: '+50 kg' }],
    documents: [{ filename: 'packing_list.txt', total_gross_weight_kg: 19500 }],
  }

  const exportResult = exportAuditJson(selectedAudit)
  assert.ok(exportResult)
  assert.equal(exportResult.filename, 'tradesathi-audit-anl-hist-selected.json')

  const parsed = JSON.parse(exportResult.jsonString)
  assert.equal(parsed.id, 'anl-hist-selected')
  assert.equal(parsed.shipment_reference, 'SHP-IN-2026-001')
  assert.equal(parsed.discrepancies[0].difference, '+50 kg')
  assert.equal(parsed.documents[0].total_gross_weight_kg, 19500)
})

test('exportAuditJson returns null on null input safely', () => {
  assert.equal(exportAuditJson(null), null)
})
