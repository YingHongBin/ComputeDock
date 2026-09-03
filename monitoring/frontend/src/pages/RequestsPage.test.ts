import { describe, expect, it } from 'vitest'
import type { ComputeRequestChangeData, ComputeRequestData } from '../types'
import { pendingApplications, requestsForTab } from './RequestsPage'

function request(
  id: string,
  approvalStatus: ComputeRequestData['approval_status'],
  createdAt: string,
  reviewedAt: string | null = null,
): ComputeRequestData {
  return {
    id,
    applicant_id: 'applicant-id',
    applicant_username: 'applicant',
    applicant_name: 'Applicant',
    project_id: 'project-id',
    project_name: 'Squad',
    resource_id: 'resource-id',
    resource_name: 'Resource',
    gpu_count: 2,
    duration_days: 7,
    approval_status: approvalStatus,
    runtime_status: null,
    actual_gpu_count: 0,
    over_quota: false,
    reviewer_name: null,
    review_comment: null,
    created_at: createdAt,
    reviewed_at: reviewedAt,
    token: null,
    started_at: null,
    expires_at: null,
    changes: [],
  }
}

function change(id: string, createdAt: string) {
  return {
    id,
    change_type: 'expand',
    approval_status: 'pending',
    amount: 2,
    before_value: 2,
    after_value: 4,
    created_at: createdAt,
  } as ComputeRequestChangeData
}

describe('requestsForTab', () => {
  const requests = [
    request('pending-new', 'pending', '2026-08-02T00:00:00Z'),
    request('approved-old', 'approved', '2026-08-01T00:00:00Z', '2026-08-03T00:00:00Z'),
    request('rejected', 'rejected', '2026-08-01T00:00:00Z', '2026-08-05T00:00:00Z'),
    request('pending-old', 'pending', '2026-08-01T00:00:00Z'),
    request('approved-new', 'approved', '2026-08-02T00:00:00Z', '2026-08-04T00:00:00Z'),
  ]

  it('shows pending requests in first-in-first-out order', () => {
    expect(requestsForTab(requests, 'pending').map((item) => item.id)).toEqual([
      'pending-old',
      'pending-new',
    ])
  })

  it('mixes pending changes with main requests in first-in-first-out order', () => {
    const approved = request('approved-with-change', 'approved', '2026-07-01T00:00:00Z')
    approved.changes = [change('pending-change', '2026-08-01T12:00:00Z')]

    expect(pendingApplications([...requests, approved]).map((item) => item.id)).toEqual([
      'request:pending-old',
      'change:pending-change',
      'request:pending-new',
    ])
  })

  it('shows completed reviews with the latest review first', () => {
    expect(requestsForTab(requests, 'approved').map((item) => item.id)).toEqual([
      'approved-new',
      'approved-old',
    ])
    expect(requestsForTab(requests, 'rejected').map((item) => item.id)).toEqual(['rejected'])
  })
})
