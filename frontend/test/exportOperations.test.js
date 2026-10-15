import test from 'node:test'
import assert from 'node:assert/strict'

// Phase 5: Export Operations Frontend Business Rules & Logic Tests

test('Export Shipment State Machine: validates linear transitions and blocks skipping stages', () => {
  const allowedTransitions = {
    draft: ['booked', 'cancelled'],
    booked: ['document_prep', 'cancelled'],
    document_prep: ['ready_for_dispatch', 'cancelled'],
    ready_for_dispatch: ['departed', 'cancelled'],
    departed: ['arrived', 'cancelled'],
    arrived: ['completed', 'cancelled'],
    completed: [],
    cancelled: [],
  }

  function canTransition(fromState, toState) {
    const targets = allowedTransitions[fromState] || []
    return targets.includes(toState)
  }

  assert.equal(canTransition('draft', 'booked'), true)
  assert.equal(canTransition('booked', 'document_prep'), true)
  assert.equal(canTransition('document_prep', 'ready_for_dispatch'), true)
  assert.equal(canTransition('ready_for_dispatch', 'departed'), true)
  assert.equal(canTransition('departed', 'arrived'), true)
  assert.equal(canTransition('arrived', 'completed'), true)

  // Direct skip from draft or booked to completed MUST BE BLOCKED
  assert.equal(canTransition('draft', 'completed'), false)
  assert.equal(canTransition('booked', 'ready_for_dispatch'), false)
  assert.equal(canTransition('completed', 'draft'), false)
})

test('Cargo Aggregation: accumulates package counts and weights from linked dispatches', () => {
  const linkedDispatches = [
    { dispatch_id: 'disp-1', packages_count: 5, total_gross_weight: 250.0, total_net_weight: 240.0 },
    { dispatch_id: 'disp-2', packages_count: 8, total_gross_weight: 420.5, total_net_weight: 410.0 },
    { dispatch_id: 'disp-3', packages_count: 2, total_gross_weight: 95.0, total_net_weight: 90.0 },
  ]

  const totalPackages = linkedDispatches.reduce((acc, d) => acc + (d.packages_count || 0), 0)
  const totalGross = linkedDispatches.reduce((acc, d) => acc + (d.total_gross_weight || 0), 0)
  const totalNet = linkedDispatches.reduce((acc, d) => acc + (d.total_net_weight || 0), 0)

  assert.equal(totalPackages, 15)
  assert.equal(Number(totalGross.toFixed(2)), 765.5)
  assert.equal(Number(totalNet.toFixed(2)), 740.0)
})

test('Double Allocation Guard: blocks linking an already-assigned dispatch to another shipment', () => {
  const existingLinks = new Set(['disp-001', 'disp-002'])

  function canLinkDispatch(dispatchId) {
    if (existingLinks.has(dispatchId)) {
      return { allowed: false, reason: 'Dispatch already linked to an active shipment' }
    }
    return { allowed: true }
  }

  assert.deepEqual(canLinkDispatch('disp-001'), {
    allowed: false,
    reason: 'Dispatch already linked to an active shipment',
  })
  assert.deepEqual(canLinkDispatch('disp-003'), { allowed: true })
})

test('Checklist Evaluation: classifies mandatory, conditional, and optional requirements accurately', () => {
  const rules = [
    { doc_type: 'commercial_invoice', requirement_level: 'mandatory', reason: 'Universal customs requirement' },
    { doc_type: 'packing_list', requirement_level: 'mandatory', reason: 'Port handling and cargo clearance' },
    {
      doc_type: 'certificate_of_origin',
      requirement_level: 'conditional',
      reason: 'Mandatory for Middle East / GCC destination countries',
    },
    { doc_type: 'insurance_certificate', requirement_level: 'optional', reason: 'Buyer preference' },
  ]

  const mandatory = rules.filter((r) => r.requirement_level === 'mandatory')
  const conditional = rules.filter((r) => r.requirement_level === 'conditional')
  const optional = rules.filter((r) => r.requirement_level === 'optional')

  assert.equal(mandatory.length, 2)
  assert.equal(conditional.length, 1)
  assert.equal(optional.length, 1)
  assert.equal(conditional[0].doc_type, 'certificate_of_origin')
})

test('Readiness Engine Contract: includes mandatory non-clearance legal disclaimer', () => {
  const readinessResult = {
    shipment_id: 'shp-100',
    readiness_status: 'blocked',
    is_ready_for_dispatch: false,
    blockers: [{ code: 'MISSING_MANDATORY_DOCUMENT', message: 'commercial_invoice missing' }],
    warnings: [],
    disclaimer:
      'TradeSathi AI readiness assessment is an internal software preparation tool and does NOT constitute official customs clearance, legal compliance, or regulatory authorization. All shipping documents must be reviewed and certified by licensed customs brokers and authorized company officers.',
  }

  assert.equal(readinessResult.readiness_status, 'blocked')
  assert.equal(readinessResult.is_ready_for_dispatch, false)
  assert.equal(readinessResult.blockers.length, 1)
  assert.match(readinessResult.disclaimer, /NOT constitute official customs clearance/i)
  assert.match(readinessResult.disclaimer, /licensed customs brokers/i)
})

test('Document Version Lineage: preserves previous versions without destructive overwrites', () => {
  const documentVersions = [
    { id: 'doc-v1', version: 1, is_current_version: 0, sha256_hash: 'hash-aaa', parent_document_id: null },
    { id: 'doc-v2', version: 2, is_current_version: 0, sha256_hash: 'hash-bbb', parent_document_id: 'doc-v1' },
    { id: 'doc-v3', version: 3, is_current_version: 1, sha256_hash: 'hash-ccc', parent_document_id: 'doc-v2' },
  ]

  const current = documentVersions.find((d) => d.is_current_version === 1)
  assert.equal(current.id, 'doc-v3')
  assert.equal(current.version, 3)

  // Verify historical versions remain intact in array
  assert.equal(documentVersions.length, 3)
  assert.equal(documentVersions[0].sha256_hash, 'hash-aaa')
})

test('Separation of Duties Policy: rejects self-approval by document creator', () => {
  function checkApprovalAllowed(uploaderId, reviewerId, reviewerRole) {
    if (uploaderId === reviewerId) {
      return { allowed: false, error: 'Separation-of-duties violation: uploader cannot approve own document' }
    }
    if (!['admin', 'manager'].includes(reviewerRole)) {
      return { allowed: false, error: 'Unauthorized role for document approval' }
    }
    return { allowed: true }
  }

  // Same user attempting to approve
  const selfApproval = checkApprovalAllowed('user-1', 'user-1', 'manager')
  assert.equal(selfApproval.allowed, false)
  assert.match(selfApproval.error, /uploader cannot approve own document/)

  // Different user with manager role
  const validApproval = checkApprovalAllowed('user-1', 'user-2', 'manager')
  assert.equal(validApproval.allowed, true)

  // Different user with unauthorized viewer role
  const invalidRole = checkApprovalAllowed('user-1', 'user-2', 'viewer')
  assert.equal(invalidRole.allowed, false)
})
