import { Alert, Card, Empty, Space, Tag, Typography } from 'antd'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import type { GpuChartSeries } from '../types'

interface Props {
  series: GpuChartSeries
  removedAt: string | null
}

export function missingAreas(series: GpuChartSeries, removedAt: string | null) {
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
    areas.push([{ xAxis: start }, { xAxis: series.points.at(-1)!.time }])
  }
  return areas
}

export function GpuChart({ series, removedAt }: Props) {
  if (!series.points.length) return <Empty description="当前范围没有数据" />
  const option = {
    animation: false,
    grid: { left: 64, right: 64, top: 54, bottom: 48 },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: number | null) => value === null ? '--' : String(value),
    },
    legend: { data: ['显存使用', 'GPU 利用率'] },
    xAxis: {
      type: 'time',
      axisLabel: { formatter: (value: number) => dayjs(value).format('MM-DD HH:mm') },
    },
    yAxis: [
      { type: 'value', name: '显存 GiB', min: 0 },
      { type: 'value', name: '利用率 %', min: 0, max: 100 },
    ],
    series: [
      {
        name: '显存使用',
        type: 'line',
        yAxisIndex: 0,
        showSymbol: false,
        connectNulls: false,
        data: series.points.map((point) => [
          point.time,
          point.memory_used === null ? null : Number((point.memory_used / 1024).toFixed(3)),
        ]),
        lineStyle: { width: 2, color: '#2563eb' },
        itemStyle: { color: '#2563eb' },
        markArea: {
          silent: true,
          itemStyle: { color: 'rgba(248, 113, 113, 0.14)' },
          data: missingAreas(series, removedAt),
        },
        markLine: {
          silent: true,
          symbol: 'none',
          data: [
            { xAxis: series.first_reported_at, label: { formatter: '首次上报' }, lineStyle: { color: '#16a34a' } },
            ...(removedAt ? [{ xAxis: removedAt, label: { formatter: '已移除' }, lineStyle: { color: '#64748b' } }] : []),
          ],
        },
      },
      {
        name: 'GPU 利用率',
        type: 'line',
        yAxisIndex: 1,
        showSymbol: false,
        connectNulls: false,
        data: series.points.map((point) => [point.time, point.utilization]),
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
