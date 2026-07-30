import { describe, expect, it } from 'vitest'
import { missingAreas } from './GpuChart'
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

