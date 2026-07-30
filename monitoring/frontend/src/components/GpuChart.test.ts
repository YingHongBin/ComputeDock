import { describe, expect, it } from 'vitest'
import { fillMissingPoints, memoryUtilization, missingAreas, removalMarkLines } from './GpuChart'
import type { GpuChartSeries } from '../types'

const series: GpuChartSeries = {
  gpuid: 'GPU-1',
  shared: false,
  first_reported_at: '2026-01-01T00:00:30Z',
  last_reported_at: '2026-01-01T00:04:00Z',
  points: [
    { time: '2026-01-01T00:00:00Z', memory_used: null, memory_total: null, utilization: null },
    { time: '2026-01-01T00:01:00Z', memory_used: 0, memory_total: 1024, utilization: 0 },
    { time: '2026-01-01T00:02:00Z', memory_used: null, memory_total: null, utilization: null },
    { time: '2026-01-01T00:03:00Z', memory_used: null, memory_total: null, utilization: null },
    { time: '2026-01-01T00:04:00Z', memory_used: 1, memory_total: 1024, utilization: 1 },
  ],
}

describe('missingAreas', () => {
  it('treats zero as data and only marks lifecycle gaps', () => {
    expect(missingAreas(series, null)).toEqual([
      [{ xAxis: '2026-01-01T00:02:00Z' }, { xAxis: '2026-01-01T00:04:00Z' }],
    ])
  })
})

describe('fillMissingPoints', () => {
  it('fills absent buckets with null and preserves actual database points', () => {
    const actual = series.points[1]
    const points = fillMissingPoints(
      [actual],
      '2026-01-01T00:00:00Z',
      '2026-01-01T00:03:00Z',
      60,
    )

    expect(points).toHaveLength(3)
    expect(points[0].utilization).toBeNull()
    expect(points[1]).toBe(actual)
    expect(points[2].utilization).toBeNull()
  })
})

describe('memoryUtilization', () => {
  it('calculates memory usage as a percentage', () => {
    expect(memoryUtilization({
      time: '2026-01-01T00:00:00Z',
      memory_used: 6144,
      memory_total: 24576,
      utilization: 50,
    })).toBe(25)
  })

  it('returns null without a valid total', () => {
    expect(memoryUtilization({
      time: '2026-01-01T00:00:00Z',
      memory_used: 0,
      memory_total: 0,
      utilization: 0,
    })).toBeNull()
  })
})

describe('removalMarkLines', () => {
  it('shows the removal marker inside the selected window', () => {
    const removedAt = '2026-01-01T00:30:00Z'
    const lines = removalMarkLines(
      removedAt,
      '2026-01-01T00:00:00Z',
      '2026-01-01T01:00:00Z',
    )

    expect(lines).toHaveLength(1)
    expect(lines[0].xAxis).toBe(removedAt)
  })

  it('does not create a marker without a removal time', () => {
    expect(removalMarkLines(
      null,
      '2026-01-01T00:00:00Z',
      '2026-01-01T01:00:00Z',
    )).toEqual([])
  })
})
