import { describe, expect, it } from 'vitest'
import type { ComputeRequestData } from '../types'
import { requestsForTab } from './RequestsPage'

function request(
  id: string,
  approvalStatus: ComputeRequestData['approval_status'],
  createdAt: string,
  reviewedAt: string | null = null,
) {
  return {
    id,
    approval_status: approvalStatus,
    created_at: createdAt,
    reviewed_at: reviewedAt,
  } as ComputeRequestData
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

  it('shows completed reviews with the latest review first', () => {
    expect(requestsForTab(requests, 'approved').map((item) => item.id)).toEqual([
      'approved-new',
      'approved-old',
    ])
    expect(requestsForTab(requests, 'rejected').map((item) => item.id)).toEqual(['rejected'])
  })
})
