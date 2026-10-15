import test from 'node:test'
import assert from 'node:assert/strict'
import { exportAuditJson, generateAuditBrief } from '../src/reportHelper.js'

test('Milestone 2E.4: exportAuditJson preserves human resolution and decision audit trail', () => {
  const audit = {
    id: 'anl-rev-exp-01',
    created_at: '2026-10-13T12:00:00Z',
    status: 'ready_for_review',
    headline: 'All critical discrepancies resolved by operator',
    discrepancies: [
      {
        id: 'fnd-net_weight-1',
        field: 'net_weight',
        severity: 'critical',
        message: 'Net Weight mismatch (+100 kg)',
        review_status: 'resolved',
        resolution: {
          resolved_at: '2026-10-13T12:05:00Z',
          resolved_by: 'Supervisor Rahul',
          reason: 'Weighbridge calibrated certificate #401 confirms 18,000 kg',
          supporting_evidence: ['ev-weight-inv', 'slip_401.pdf'],
          corrected_value: 18000,
          corrected_unit: 'kg',
        },
        review_history: [
          {
            id: 'rev-01',
            previous_state: 'pending_review',
            new_state: 'in_review',
            reviewer: 'Operator Gautam',
            timestamp: '2026-10-13T12:01:00Z',
            notes: 'Physical tally in progress',
          },
          {
            id: 'rev-02',
            previous_state: 'in_review',
            new_state: 'resolved',
            reviewer: 'Supervisor Rahul',
            timestamp: '2026-10-13T12:05:00Z',
            reason: 'Weighbridge calibrated certificate #401 confirms 18,000 kg',
            supporting_evidence: ['ev-weight-inv', 'slip_401.pdf'],
            corrected_value: 18000,
            corrected_unit: 'kg',
          },
        ],
      },
    ],
  }

  const exportRes = exportAuditJson(audit)
  assert.ok(exportRes.jsonString)
  const parsed = JSON.parse(exportRes.jsonString)

  assert.equal(parsed.id, 'anl-rev-exp-01')
  assert.equal(parsed.discrepancies[0].review_status, 'resolved')
  assert.equal(parsed.discrepancies[0].resolution.resolved_by, 'Supervisor Rahul')
  assert.equal(parsed.discrepancies[0].review_history.length, 2)
  assert.equal(parsed.discrepancies[0].review_history[0].new_state, 'in_review')
  assert.equal(parsed.discrepancies[0].review_history[1].new_state, 'resolved')
})

test('Milestone 2E.4: generateAuditBrief highlights human review decisions beside machine findings', () => {
  const audit = {
    id: 'anl-brief-01',
    created_at: '2026-10-13T12:00:00Z',
    status: 'ready_for_review',
    headline: 'Resolved reconciliation findings',
    documents: [{ filename: 'inv.txt' }, { filename: 'pkg.txt' }],
    discrepancies: [
      {
        id: 'fnd-1',
        field: 'net_weight',
        severity: 'critical',
        message: 'Net Weight mismatch (+100 kg)',
        review_status: 'resolved',
        resolution: {
          resolved_by: 'Supervisor Rahul',
          reason: 'Weighbridge certificate #401',
        },
      },
      {
        id: 'fnd-2',
        field: 'hs_code',
        severity: 'warning',
        message: 'HS Code format warning',
        review_status: 'acknowledged',
      },
    ],
  }

  const brief = generateAuditBrief(audit)
  assert.ok(brief.includes('DISCREPANCIES & HUMAN VERIFICATION ACTIONS:'))
  assert.ok(brief.includes('Net Weight mismatch (+100 kg)'))
})
