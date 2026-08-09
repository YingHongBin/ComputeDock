import { ArrowLeftOutlined } from '@ant-design/icons'
import { App, Button, Card, Empty, Space, Spin, Typography } from 'antd'
import ReactECharts from 'echarts-for-react'
import dayjs from 'dayjs'
import { useEffect, useState } from 'react'
import { api, errorMessage } from '../api'
import type { HistoryContainerChartData } from '../types'

export function HistoryContainerPage({ containerId }: { containerId: string }) {
  const { message } = App.useApp()
  const [data, setData] = useState<HistoryContainerChartData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<HistoryContainerChartData>(`/history/containers/${containerId}/chart`)
      .then((response) => setData(response.data))
      .catch((error) => message.error(errorMessage(error)))
      .finally(() => setLoading(false))
  }, [containerId])

  if (loading) return <Spin />
  return (
    <section>
      <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => window.history.back()}>返回</Button>
      <div className="page-heading">
        <Typography.Title level={2}>{data?.container_name ?? '历史容器'}</Typography.Title>
        {data && <Typography.Text type="secondary">首次上报 {dayjs(data.first_reported_at).format('YYYY-MM-DD HH:mm:ss')} · 移除 {dayjs(data.removed_at).format('YYYY-MM-DD HH:mm:ss')}</Typography.Text>}
      </div>
      {!data?.series.length ? <Empty description="暂无已聚合的小时数据" /> : (
        <Space direction="vertical" size="large" className="full-width">
          {data.series.map((series) => {
            const option = {
              animation: false,
              grid: { left: 32, right: 32, top: 76, bottom: 32, containLabel: true },
              tooltip: { trigger: 'axis' },
              legend: { top: 8, data: ['平均 GPU 利用率', '峰值 GPU 利用率', '平均显存使用率', '峰值显存使用率'] },
              xAxis: { type: 'time', axisLabel: { formatter: (value: number) => dayjs(value).format('MM-DD HH:mm') } },
              yAxis: { type: 'value', name: '使用率 %', min: 0, max: 100 },
              series: [
                { name: '平均 GPU 利用率', type: 'line', showSymbol: false, data: series.points.map((point) => [point.time, point.utilization_avg]) },
                { name: '峰值 GPU 利用率', type: 'line', showSymbol: false, lineStyle: { type: 'dashed' }, data: series.points.map((point) => [point.time, point.utilization_max]) },
                { name: '平均显存使用率', type: 'line', showSymbol: false, data: series.points.map((point) => [point.time, Number((point.memory_used_avg / point.memory_total * 100).toFixed(2))]) },
                { name: '峰值显存使用率', type: 'line', showSymbol: false, lineStyle: { type: 'dashed' }, data: series.points.map((point) => [point.time, Number((point.memory_used_max / point.memory_total * 100).toFixed(2))]) },
              ],
            }
            return <Card key={series.gpuid} title={series.gpuid}><ReactECharts option={option} style={{ height: 390 }} notMerge /></Card>
          })}
        </Space>
      )}
    </section>
  )
}
