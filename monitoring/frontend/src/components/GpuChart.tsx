import { Alert, Card, Space, Tag, Typography } from 'antd'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import type { ChartPoint, GpuChartSeries } from '../types'

interface Props {
  series: GpuChartSeries
  removedAt: string | null
  windowStart: string
  windowEnd: string
  bucketSeconds: number
}

export function fillMissingPoints(
  points: ChartPoint[],
  windowStart: string,
  windowEnd: string,
  bucketSeconds: number,
) {
  const existing = new Map(points.map((point) => [dayjs(point.time).valueOf(), point]))
  const completed: ChartPoint[] = []
  const end = dayjs(windowEnd).valueOf()
  const step = bucketSeconds * 1000
  for (let cursor = dayjs(windowStart).valueOf(); cursor < end; cursor += step) {
    completed.push(existing.get(cursor) ?? {
      time: new Date(cursor).toISOString(),
      memory_used: null,
      memory_total: null,
      utilization: null,
    })
  }
  return completed
}

export function missingAreas(series: GpuChartSeries, removedAt: string | null, windowEnd?: string) {
  const areas: Array<Array<{ xAxis: string }>> = []
  let start: string | null = null
  for (const point of series.points) {
    const insideLifecycle = dayjs(point.time).isAfter(series.first_reported_at) &&
      (!removedAt || dayjs(point.time).isBefore(removedAt))
    const missing = insideLifecycle && point.utilization === null
    if (missing && start === null) start = point.time
    if (!missing && start !== null) {
      areas.push([{ xAxis: start }, { xAxis: point.time }])
      start = null
    }
  }
  if (start !== null && series.points.length) {
    areas.push([{ xAxis: start }, { xAxis: windowEnd ?? series.points.at(-1)!.time }])
  }
  return areas
}

function insideWindow(time: string, windowStart: string, windowEnd: string) {
  const value = dayjs(time).valueOf()
  return value >= dayjs(windowStart).valueOf() && value < dayjs(windowEnd).valueOf()
}

export function removalMarkLines(
  removedAt: string | null,
  windowStart: string,
  windowEnd: string,
) {
  return [
    ...(removedAt && insideWindow(removedAt, windowStart, windowEnd)
      ? [{ xAxis: removedAt, label: { formatter: '已移除' }, lineStyle: { color: '#64748b' } }]
      : []),
  ]
}

export function memoryUtilization(point: ChartPoint) {
  if (point.memory_used === null || point.memory_total === null || point.memory_total <= 0) {
    return null
  }
  return Number(((point.memory_used / point.memory_total) * 100).toFixed(2))
}

export function GpuChart({ series, removedAt, windowStart, windowEnd, bucketSeconds }: Props) {
  const completedSeries = {
    ...series,
    points: fillMissingPoints(series.points, windowStart, windowEnd, bucketSeconds),
  }
  const showSinglePoint = series.points.length === 1
  const markLines = removalMarkLines(removedAt, windowStart, windowEnd)
  const option = {
    animation: false,
    grid: { left: 32, right: 32, top: 76, bottom: 32, containLabel: true },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: number | null) => value === null ? '--' : `${value}%`,
    },
    legend: { top: 8, data: ['显存使用率', 'GPU 利用率'] },
    xAxis: {
      type: 'time',
      min: windowStart,
      max: windowEnd,
      axisLabel: { margin: 14, formatter: (value: number) => dayjs(value).format('MM-DD HH:mm') },
    },
    yAxis: {
      type: 'value',
      name: '使用率 %',
      min: 0,
      max: 100,
    },
    series: [
      {
        name: '显存使用率',
        type: 'line',
        showSymbol: showSinglePoint,
        symbolSize: 7,
        connectNulls: false,
        data: completedSeries.points.map((point) => [
          point.time,
          memoryUtilization(point),
        ]),
        lineStyle: { width: 2, color: '#2563eb' },
        itemStyle: { color: '#2563eb' },
        markArea: {
          silent: true,
          itemStyle: { color: 'rgba(248, 113, 113, 0.14)' },
          data: missingAreas(completedSeries, removedAt, windowEnd),
        },
        markLine: {
          silent: true,
          symbol: 'none',
          data: markLines,
        },
      },
      {
        name: 'GPU 利用率',
        type: 'line',
        showSymbol: showSinglePoint,
        symbolSize: 7,
        connectNulls: false,
        data: completedSeries.points.map((point) => [point.time, point.utilization]),
        lineStyle: { width: 2, color: '#f59e0b' },
        itemStyle: { color: '#f59e0b' },
      },
    ],
  }

  return (
    <Card className="gpu-chart-card">
      <Space direction="vertical" size="small" className="full-width">
        <Space wrap>
          <Typography.Text strong>{series.gpuid}</Typography.Text>
          {series.shared && <Tag color="gold">共享 GPU</Tag>}
        </Space>
        {series.shared && (
          <Alert type="warning" showIcon message="该数据属于整张 GPU，无法归因到单个容器。" />
        )}
        <ReactECharts option={option} style={{ height: 360 }} notMerge />
      </Space>
    </Card>
  )
}
