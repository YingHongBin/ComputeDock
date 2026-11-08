import { describe, expect, it } from 'vitest'
import type { ComputeRequestChangeData, ComputeRequestData } from '../types'
import { changeContent, pendingApplications, requestsForTab } from './RequestsPage'

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
    cpu_cores: 8,
    memory_gib: 32,
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
    change_type: 'config',
    approval_status: 'pending',
    days_delta: null,
    reviewer_name: null,
    review_comment: null,
    reviewed_at: null,
    before_value: { gpu_count: 2, cpu_cores: 8, memory_gib: 32 },
    after_value: { gpu_count: 4, cpu_cores: 16, memory_gib: 64 },
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


it('describes time reductions and the complete configuration change', () => {
  const config = change('c', '2026-11-07T00:00:00Z')
  expect(changeContent(config)).toBe('GPU 2 → 4 张 / CPU 8 → 16 核 / 内存 32 → 64 GiB')
  expect(changeContent({ ...config, change_type: 'time', days_delta: -2,
    before_value: { duration_days: 7 }, after_value: { duration_days: 5 },
  })).toBe('使用天数 7 → 5（减少 2 天）')
})
