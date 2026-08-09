import { ArrowLeftOutlined, DeleteOutlined, EditOutlined, PauseCircleOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { App, Button, Card, Empty, Flex, Segmented, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useEffect, useMemo, useState } from 'react'
import { api, csrfHeaders, errorMessage } from '../api'
import { useAuth } from '../auth'
import { GpuChart } from '../components/GpuChart'
import { ResourceEditor } from '../components/ResourceEditor'
import { useNavigation } from '../routing'
import type { ChartRange, ChartResponse, ContainerSummary, ResourceCardData, ResourceInput } from '../types'

const rangeOptions = [
  { label: '近 1 小时', value: '1h' },
  { label: '近 6 小时', value: '6h' },
  { label: '近 1 天', value: '1d' },
  { label: '近 7 天', value: '7d' },
]

function usage(value: number | null) {
  return value === null ? '--' : `${value.toFixed(1)}%`
}

export function ResourceDetailPage({ resourceId }: { resourceId: string }) {
  const { session } = useAuth()
  const { message, modal } = App.useApp()
  const { navigate } = useNavigation()
  const [resource, setResource] = useState<ResourceCardData | null>(null)
  const [containers, setContainers] = useState<ContainerSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [range, setRange] = useState<ChartRange>('1h')
  const [chart, setChart] = useState<ChartResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [chartLoading, setChartLoading] = useState(false)
  const [editorOpen, setEditorOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const loadPage = async () => {
    setLoading(true)
    try {
      const [resourceResponse, containerResponse] = await Promise.all([
        api.get<ResourceCardData>(`/resources/${resourceId}`),
        api.get<ContainerSummary[]>(`/resources/${resourceId}/containers`),
      ])
      setResource(resourceResponse.data)
      setContainers(containerResponse.data)
      setSelectedId((current) => current && containerResponse.data.some((item) => item.id === current)
        ? current
        : containerResponse.data[0]?.id ?? null)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void loadPage() }, [resourceId])

  useEffect(() => {
    if (!selectedId) { setChart(null); return }
    setChartLoading(true)
    api.get<ChartResponse>(`/resources/${resourceId}/containers/${selectedId}/chart`, { params: { range } })
      .then(({ data }) => setChart(data))
      .catch((error) => message.error(errorMessage(error)))
      .finally(() => setChartLoading(false))
  }, [range, resourceId, selectedId])

  const removeContainer = (container: ContainerSummary) => {
    if (!session) return
    modal.confirm({
      title: `移除容器“${container.name}”？`,
      content: '再次收到同名 Agent 上报时，系统会创建新的容器实例。',
      okText: '确认移除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        await api.delete(`/resources/${resourceId}/containers/${container.id}`, { headers: csrfHeaders(session.csrf_token) })
        setChart(null)
        await loadPage()
      },
    })
  }

  const saveResource = async (value: ResourceInput) => {
    if (!session) return
    setSubmitting(true)
    try {
      const { data } = await api.put<ResourceCardData>(`/resources/${resourceId}`, value, {
        headers: csrfHeaders(session.csrf_token),
      })
      setResource(data)
      setEditorOpen(false)
      message.success('算力资源已更新')
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSubmitting(false)
    }
  }

  const toggleResource = async () => {
    if (!session || session.role !== 'admin' || !resource) return
    const action = resource.status === 'active' ? 'disable' : 'enable'
    try {
      const { data } = await api.post<ResourceCardData>(`/resources/${resourceId}/${action}`, undefined, {
        headers: csrfHeaders(session.csrf_token),
      })
      setResource(data)
      message.success(resource.status === 'active' ? '算力资源已禁用' : '算力资源已启用')
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  const columns = useMemo<ColumnsType<ContainerSummary>>(() => [
    {
      title: '容器名称',
      dataIndex: 'name',
      fixed: 'left',
      width: 140,
      render: (name, row) => (
        <div className="container-name-cell">
          <Typography.Text strong>{name}</Typography.Text>
          {row.generation > 1 && <Tag>第 {row.generation} 代</Tag>}
        </div>
      ),
    },
    { title: '状态', dataIndex: 'status', width: 90, render: (status) => status === 'online' ? <Tag color="success">在线</Tag> : <Tag>失联</Tag> },
    { title: '最后上报', dataIndex: 'last_received_at', width: 170, render: (value) => dayjs(value).format('YYYY-MM-DD HH:mm:ss') },
    { title: '分配显卡', dataIndex: 'allocated_gpu_count', width: 100 },
    { title: '近 1 小时', dataIndex: 'utilization_1h', width: 100, render: usage },
    { title: '近 6 小时', dataIndex: 'utilization_6h', width: 100, render: usage },
    { title: '近 1 天', dataIndex: 'utilization_1d', width: 100, render: usage },
    { title: '近 7 天', dataIndex: 'utilization_7d', width: 100, render: usage },
    ...(session?.role === 'admin' ? [{ title: '操作', width: 80, render: (_: unknown, row: ContainerSummary) => <Button danger type="text" icon={<DeleteOutlined />} onClick={(event) => { event.stopPropagation(); removeContainer(row) }}>移除</Button> }] : []),
  ], [session?.role])

  return (
    <section>
      <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>返回概览</Button>
      <Flex justify="space-between" align="end" className="page-heading detail-heading">
        <div>
          <Typography.Title level={2}>{resource?.name ?? '算力资源详情'}</Typography.Title>
          {resource && <Typography.Text type="secondary">{resource.gpu_model} · 总计 {resource.gpu_count} 张 · 已分配 {resource.allocated_gpu_count} 张</Typography.Text>}
        </div>
        {session?.role === 'admin' && <Space>
          <Button icon={<EditOutlined />} disabled={!resource} onClick={() => setEditorOpen(true)}>
            编辑资源
          </Button>
          <Button
            icon={resource?.status === 'active' ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
            disabled={!resource || loading}
            onClick={() => void toggleResource()}
          >
            {resource?.status === 'active' ? '禁用资源' : '启用资源'}
          </Button>
        </Space>}
      </Flex>
      <Card title="容器" className="section-card">
        <Table
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={containers}
          pagination={false}
          scroll={{ x: 980 }}
          rowClassName={(row) => row.id === selectedId ? 'selected-row' : ''}
          onRow={(row) => ({ onClick: () => setSelectedId(row.id) })}
        />
      </Card>
      <Flex justify="space-between" align="center" className="chart-heading">
        <div>
          <Typography.Title level={3}>GPU 使用趋势</Typography.Title>
          <Typography.Text type="secondary">{chart?.container_name ?? '请先选择容器'}</Typography.Text>
        </div>
        <Segmented value={range} options={rangeOptions} onChange={(value) => setRange(value as ChartRange)} />
      </Flex>
      {!selectedId ? <Empty description="暂无容器数据" /> : (
        <Card loading={chartLoading} className="chart-container">
          {chart && chart.series.length ? (
            <Space direction="vertical" size="large" className="full-width">
              {chart.series.map((item) => (
                <GpuChart
                  key={item.gpuid}
                  series={item}
                  removedAt={chart.instance_removed_at}
                  windowStart={chart.window_start}
                  windowEnd={chart.window_end}
                  bucketSeconds={chart.bucket_seconds}
                />
              ))}
            </Space>
          ) : !chartLoading && <Empty description="当前范围没有 GPU 数据" />}
        </Card>
      )}
      <ResourceEditor
        open={editorOpen}
        resource={resource}
        submitting={submitting}
        onCancel={() => setEditorOpen(false)}
        onSubmit={saveResource}
      />
    </section>
  )
}
