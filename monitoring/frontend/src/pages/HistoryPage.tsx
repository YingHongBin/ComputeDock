import { Card, Empty, Select, Space, Table, Tabs, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useEffect, useMemo, useState } from 'react'
import { App } from 'antd'
import { api, errorMessage } from '../api'
import { useNavigation } from '../routing'
import type { ComputeRequestData, HistoryContainerData, ProjectData, UserData } from '../types'

function formatDuration(seconds: number | null): string {
  if (seconds === null) return '--'
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return `${days} 天 ${hours} 小时 ${minutes} 分钟`
}

function formatPercent(value: number | null): string {
  return value === null ? '--' : `${value.toFixed(2)}%`
}

export function HistoryPage({ mode }: { mode: 'users' | 'projects' }) {
  const { message } = App.useApp()
  const { navigate } = useNavigation()
  const [entities, setEntities] = useState<Array<{ value: string; label: string }>>([])
  const [selected, setSelected] = useState<string>()
  const [requests, setRequests] = useState<ComputeRequestData[]>([])
  const [containers, setContainers] = useState<HistoryContainerData[]>([])
  const [requestStatus, setRequestStatus] = useState<string>()
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setSelected(undefined)
    setRequests([])
    setContainers([])
    const endpoint = mode === 'users' ? '/users' : '/projects?include_disabled=true'
    api.get<UserData[] | ProjectData[]>(endpoint)
      .then(({ data }) => setEntities(mode === 'users'
        ? (data as UserData[]).map((item) => ({ value: item.id, label: `${item.full_name} (${item.username})` }))
        : (data as ProjectData[]).map((item) => ({ value: item.id, label: item.name }))))
      .catch((error) => message.error(errorMessage(error)))
  }, [mode])

  useEffect(() => {
    if (!selected) return
    setLoading(true)
    const key = mode === 'users' ? 'applicant_id' : 'project_id'
    Promise.all([
      api.get<ComputeRequestData[]>('/compute-requests', { params: { [key]: selected } }),
      api.get<HistoryContainerData[]>('/history/containers', { params: { [mode === 'users' ? 'user_id' : 'project_id']: selected, container_status: 'removed', limit: 500 } }),
    ]).then(([requestResponse, containerResponse]) => {
      setRequests(requestResponse.data)
      setContainers(containerResponse.data)
    }).catch((error) => message.error(errorMessage(error))).finally(() => setLoading(false))
  }, [mode, selected])

  const visibleRequests = useMemo(() => requestStatus ? requests.filter((item) => item.approval_status === requestStatus) : requests, [requestStatus, requests])

  const requestColumns: ColumnsType<ComputeRequestData> = [
    { title: '申请人', dataIndex: 'applicant_name' },
    { title: 'Squad', dataIndex: 'project_name' },
    { title: '资源', dataIndex: 'resource_name' },
    { title: 'GPU', dataIndex: 'gpu_count', width: 80 },
    { title: '天数', dataIndex: 'duration_days', width: 80 },
    { title: '审批', dataIndex: 'approval_status', render: (value) => <Tag color={value === 'approved' ? 'success' : value === 'pending' ? 'processing' : 'error'}>{value === 'approved' ? '已通过' : value === 'pending' ? '申请中' : '已拒绝'}</Tag> },
    { title: '提交时间', dataIndex: 'created_at', render: (value) => dayjs(value).format('YYYY-MM-DD HH:mm') },
  ]

  const containerColumns: ColumnsType<HistoryContainerData> = [
    { title: 'Squad', dataIndex: 'project_name' },
    { title: '申请人', dataIndex: 'applicant_name' },
    { title: '内部容器', dataIndex: 'name', render: (value, row) => <Space>{value}{row.generation > 1 && <Tag>第 {row.generation} 代</Tag>}</Space> },
    { title: '资源', dataIndex: 'resource_name' },
    { title: '首次上报', dataIndex: 'first_reported_at', render: (value) => dayjs(value).format('YYYY-MM-DD HH:mm') },
    { title: '移除时间', dataIndex: 'removed_at', render: (value) => value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '--' },
    {
      title: '使用时长',
      dataIndex: 'usage_duration_seconds',
      render: (value, row) => row.usage_summary_status === 'pending' ? <Tag color="processing">统计中</Tag> : formatDuration(value),
    },
    { title: '实际 GPU', dataIndex: 'usage_gpu_count', render: (value, row) => row.usage_summary_status === 'pending' ? '--' : value ?? '--' },
    {
      title: 'GPU 使用率（平均 / 峰值）',
      render: (_, row) => row.usage_summary_status === 'pending' ? '--' : `${formatPercent(row.usage_gpu_utilization_avg)} / ${formatPercent(row.usage_gpu_utilization_max)}`,
    },
    {
      title: '显存使用率（平均 / 峰值）',
      render: (_, row) => row.usage_summary_status === 'pending' ? '--' : `${formatPercent(row.usage_memory_utilization_avg)} / ${formatPercent(row.usage_memory_utilization_max)}`,
    },
  ]

  return (
    <section>
      <div className="page-heading">
        <Typography.Title level={2}>{mode === 'users' ? '用户历史' : 'Squad历史'}</Typography.Title>
        <Typography.Text type="secondary">查看历史算力申请、容器及容器趋势，不统计卡天。</Typography.Text>
      </div>
      <Card className="section-card">
        <Select
          className="history-entity-select"
          showSearch
          optionFilterProp="label"
          placeholder={mode === 'users' ? '选择用户' : '选择Squad'}
          options={entities}
          value={selected}
          onChange={setSelected}
        />
      </Card>
      {!selected ? <Empty description="请先选择查询对象" /> : (
        <Card>
          <Tabs items={[
            {
              key: 'requests', label: `算力申请 (${visibleRequests.length})`, children: <>
                <Select allowClear placeholder="审批状态" className="history-filter" value={requestStatus} onChange={setRequestStatus} options={[{ value: 'pending', label: '申请中' }, { value: 'approved', label: '已通过' }, { value: 'rejected', label: '已拒绝' }]} />
                <Table rowKey="id" loading={loading} columns={requestColumns} dataSource={visibleRequests} scroll={{ x: 900 }} />
              </>,
            },
            {
              key: 'containers', label: `历史容器 (${containers.length})`, children: <>
                <Table
                  rowKey="id"
                  loading={loading}
                  columns={containerColumns}
                  dataSource={containers}
                  scroll={{ x: 1600 }}
                  onRow={(row) => ({
                    onClick: () => navigate(`/history/containers/${row.id}`),
                  })}
                  rowClassName="clickable-row"
                />
              </>,
            },
          ]} />
        </Card>
      )}
    </section>
  )
}
