import { CopyOutlined, PlusOutlined } from '@ant-design/icons'
import { Alert, App, Button, Card, Flex, Form, Input, InputNumber, Modal, Select, Space, Table, Tabs, Tag, Tooltip, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useEffect, useMemo, useState } from 'react'
import { api, csrfHeaders, errorMessage } from '../api'
import { useAuth } from '../auth'
import type { ComputeRequestChangeData, ComputeRequestData, ProjectData, ResourceCardData } from '../types'

const approvalLabels = {
  pending: ['申请中', 'processing'],
  approved: ['已通过', 'success'],
  rejected: ['已拒绝', 'error'],
} as const

const runtimeLabels = {
  not_started: ['未启动', 'default'],
  running: ['运行中', 'success'],
  expiring: ['即将到期', 'warning'],
  expired: ['已到期', 'error'],
} as const

const changeLabels = { extend: '延时', expand: 'GPU 扩容', release: 'GPU 释放', cpu: 'CPU 调整', memory: '内存调整' }
const pendingTypeLabels = { new: '新申请', ...changeLabels }

type ReviewTarget = { request: ComputeRequestData; change?: ComputeRequestChangeData }
type ApprovalStatus = ComputeRequestData['approval_status']
type PendingApplicationType = 'new' | ComputeRequestChangeData['change_type']

export interface PendingApplication {
  id: string
  type: PendingApplicationType
  request: ComputeRequestData
  change?: ComputeRequestChangeData
  created_at: string
}

const identityColumns: ColumnsType<ComputeRequestData> = [
  { title: '申请人', dataIndex: 'applicant_name', width: 120 },
  { title: 'Squad', dataIndex: 'project_name', width: 150 },
  { title: '算力资源', dataIndex: 'resource_name', width: 150 },
]

export function requestsForTab(requests: ComputeRequestData[], activeTab: ApprovalStatus) {
  return requests
    .filter((request) => request.approval_status === activeTab)
    .sort((left, right) => {
      if (activeTab === 'pending') {
        return dayjs(left.created_at).valueOf() - dayjs(right.created_at).valueOf()
      }
      const leftReviewedAt = left.reviewed_at ?? left.created_at
      const rightReviewedAt = right.reviewed_at ?? right.created_at
      return dayjs(rightReviewedAt).valueOf() - dayjs(leftReviewedAt).valueOf()
    })
}

export function pendingApplications(requests: ComputeRequestData[]): PendingApplication[] {
  return requests
    .flatMap((request) => [
      ...(request.approval_status === 'pending' ? [{
        id: `request:${request.id}`,
        type: 'new' as const,
        request,
        created_at: request.created_at,
      }] : []),
      ...request.changes
        .filter((change) => change.approval_status === 'pending')
        .map((change) => ({
          id: `change:${change.id}`,
          type: change.change_type,
          request,
          change,
          created_at: change.created_at,
        })),
    ])
    .sort((left, right) => dayjs(left.created_at).valueOf() - dayjs(right.created_at).valueOf())
}

export function quotaText(total: number, reserved: number, unit: string) {
  const remaining = Math.max(total - reserved, 0)
  const over = Math.max(reserved - total, 0)
  return `剩余 ${remaining} ${unit} / 总计 ${total} ${unit}${over ? `，已超配 ${over} ${unit}` : ''}`
}

function requestContent(request: ComputeRequestData) {
  return `${request.gpu_count} 张 GPU / ${request.cpu_cores} 核 CPU / ${request.memory_gib} GiB 内存 / ${request.duration_days} 天`
}

function changeContent(change: ComputeRequestChangeData) {
  if (change.change_type === 'cpu' || change.change_type === 'memory') {
    const label = change.change_type === 'cpu' ? 'CPU（核）' : '内存（GiB）'
    return `${label} ${change.before_value} → ${change.after_value}`
  }
  if (change.change_type === 'extend') {
    return `使用天数 ${change.before_value} → ${change.after_value}（增加 ${change.amount} 天）`
  }
  if (change.change_type === 'expand') {
    return `GPU ${change.before_value} → ${change.after_value}（增加 ${change.amount} 张）`
  }
  return `GPU ${change.before_value} → ${change.after_value}（释放 ${change.amount} 张）`
}

export function RequestsPage() {
  const { session } = useAuth()
  const { message } = App.useApp()
  const [requests, setRequests] = useState<ComputeRequestData[]>([])
  const [projects, setProjects] = useState<ProjectData[]>([])
  const [resources, setResources] = useState<ResourceCardData[]>([])
  const [loading, setLoading] = useState(true)
  const [noticeOpen, setNoticeOpen] = useState(false)
  const [noticeCountdown, setNoticeCountdown] = useState(3)
  const [requestOpen, setRequestOpen] = useState(false)
  const [changeTarget, setChangeTarget] = useState<ComputeRequestData | null>(null)
  const [reviewTarget, setReviewTarget] = useState<ReviewTarget | null>(null)
  const [activeTab, setActiveTab] = useState<ApprovalStatus>('pending')
  const [busy, setBusy] = useState(false)
  const [requestForm] = Form.useForm()
  const [changeForm] = Form.useForm()
  const [reviewForm] = Form.useForm()
  const selectedResourceId = Form.useWatch('resource_id', requestForm)
  const requestedGpu = Form.useWatch('gpu_count', requestForm)
  const requestedCpu = Form.useWatch('cpu_cores', requestForm)
  const requestedMemory = Form.useWatch('memory_gib', requestForm)
  const selectedResource = resources.find((item) => item.id === selectedResourceId)
  const exceedsRemaining = selectedResource && (
    requestedGpu > selectedResource.remaining_gpu_count ||
    requestedCpu > selectedResource.remaining_cpu_cores ||
    requestedMemory > selectedResource.remaining_memory_gib
  )

  const load = async () => {
    setLoading(true)
    try {
      const [requestResponse, projectResponse, resourceResponse] = await Promise.all([
        api.get<ComputeRequestData[]>('/compute-requests'),
        api.get<ProjectData[]>('/projects', { params: { include_disabled: false } }),
        api.get<ResourceCardData[]>('/resources'),
      ])
      setRequests(requestResponse.data)
      setProjects(projectResponse.data)
      setResources(resourceResponse.data)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  useEffect(() => {
    if (!noticeOpen || noticeCountdown <= 0) return
    const timer = window.setTimeout(() => setNoticeCountdown((value) => value - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [noticeOpen, noticeCountdown])

  const showUsageNotice = () => {
    setNoticeCountdown(3)
    setNoticeOpen(true)
  }

  const acceptUsageNotice = async () => {
    if (noticeCountdown > 0) return
    try {
      const response = await api.get<ResourceCardData[]>('/resources')
      setResources(response.data)
      setNoticeOpen(false)
      setRequestOpen(true)
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  const availableProjects = projects.filter((project) => project.status === 'active')
  const availableResources = resources.filter((resource) => resource.status === 'active')

  const submitRequest = async (values: Record<string, unknown>) => {
    if (!session) return
    setBusy(true)
    try {
      await api.post('/compute-requests', values, { headers: csrfHeaders(session.csrf_token) })
      message.success('算力申请已提交')
      setRequestOpen(false)
      requestForm.resetFields()
      await load()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const submitChange = async (values: Record<string, unknown>) => {
    if (!session || !changeTarget) return
    setBusy(true)
    try {
      await api.post(`/compute-requests/${changeTarget.id}/changes`, values, {
        headers: csrfHeaders(session.csrf_token),
      })
      message.success('变更申请已提交')
      setChangeTarget(null)
      changeForm.resetFields()
      await load()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const submitReview = async (values: { decision: 'approved' | 'rejected'; comment?: string }) => {
    if (!session || !reviewTarget) return
    setBusy(true)
    try {
      const endpoint = reviewTarget.change
        ? `/compute-requests/${reviewTarget.request.id}/changes/${reviewTarget.change.id}/review`
        : `/compute-requests/${reviewTarget.request.id}/review`
      await api.post(endpoint, values, { headers: csrfHeaders(session.csrf_token) })
      message.success(values.decision === 'approved' ? '审核已通过' : '审核已拒绝')
      setReviewTarget(null)
      reviewForm.resetFields()
      await load()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const copyToken = async (token: string) => {
    try {
      await navigator.clipboard.writeText(token)
      message.success('Token 已复制')
    } catch {
      message.error('Token 复制失败')
    }
  }

  const pendingColumns = useMemo<ColumnsType<PendingApplication>>(() => [
    { title: '申请类型', dataIndex: 'type', width: 100, render: (value: PendingApplicationType) => <Tag>{pendingTypeLabels[value]}</Tag> },
    { title: '申请人', width: 120, render: (_, row) => row.request.applicant_name },
    { title: 'Squad', width: 150, render: (_, row) => row.request.project_name },
    { title: '算力资源', width: 150, render: (_, row) => row.request.resource_name },
    { title: '申请内容', width: 260, render: (_, row) => row.change ? changeContent(row.change) : requestContent(row.request) },
    { title: '提交时间', dataIndex: 'created_at', width: 170, render: (value) => dayjs(value).format('YYYY-MM-DD HH:mm') },
    ...(session?.role === 'admin' ? [{
      title: '操作', width: 100, fixed: 'right' as const, render: (_: unknown, row: PendingApplication) => (
        <Button size="small" type="primary" onClick={() => setReviewTarget({ request: row.request, change: row.change })}>审核</Button>
      ),
    }] : []),
  ], [session?.role])

  const approvedColumns = useMemo<ColumnsType<ComputeRequestData>>(() => [
    ...identityColumns,
    { title: 'GPU', dataIndex: 'gpu_count', width: 80, render: (value, row) => <span>{value} 张{row.over_quota && <Tag color="error" className="inline-tag">超额 {row.actual_gpu_count}</Tag>}</span> },
    { title: 'CPU（核）', dataIndex: 'cpu_cores', width: 100 },
    { title: '内存（GiB）', dataIndex: 'memory_gib', width: 110 },
    { title: '使用天数', dataIndex: 'duration_days', width: 100, render: (value) => `${value} 天` },
    { title: '运行', dataIndex: 'runtime_status', width: 110, render: (value: keyof typeof runtimeLabels | null) => value ? <Tag color={runtimeLabels[value][1]}>{runtimeLabels[value][0]}</Tag> : '--' },
    { title: '首次上报时间', dataIndex: 'started_at', width: 170, render: (value) => value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '--' },
    { title: '到期时间', dataIndex: 'expires_at', width: 170, render: (value) => value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '--' },
    {
      title: '操作', width: 230, fixed: 'right', render: (_, row) => (
        <Space wrap>
          {session?.role === 'admin' && row.token && (
            <Button size="small" icon={<CopyOutlined />} onClick={() => void copyToken(row.token!)}>复制 Token</Button>
          )}
          {row.applicant_username === session?.username && row.runtime_status !== 'expired' && !row.changes.some((item) => item.approval_status === 'pending') && (
            <Button size="small" onClick={() => setChangeTarget(row)}>申请变更</Button>
          )}
        </Space>
      ),
    },
  ], [session])

  const rejectedColumns = useMemo<ColumnsType<ComputeRequestData>>(() => [
    ...identityColumns,
    { title: '申请 GPU 数量', dataIndex: 'gpu_count', width: 120, render: (value) => `${value} 张` },
    { title: 'CPU（核）', dataIndex: 'cpu_cores', width: 100 },
    { title: '内存（GiB）', dataIndex: 'memory_gib', width: 110 },
    { title: '申请天数', dataIndex: 'duration_days', width: 100, render: (value) => `${value} 天` },
    { title: '提交时间', dataIndex: 'created_at', width: 170, render: (value) => dayjs(value).format('YYYY-MM-DD HH:mm') },
    { title: '审核人', dataIndex: 'reviewer_name', width: 120, render: (value) => value || '--' },
    {
      title: '拒绝说明',
      dataIndex: 'review_comment',
      width: 260,
      render: (value) => value ? (
        <Tooltip title={value}>
          <span className="request-review-comment">{value}</span>
        </Tooltip>
      ) : '--',
    },
    { title: '拒绝时间', dataIndex: 'reviewed_at', width: 170, render: (value) => value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '--' },
  ], [])

  const visibleRequests = useMemo(() => requestsForTab(requests, activeTab), [activeTab, requests])
  const pendingItems = useMemo(() => pendingApplications(requests), [requests])

  const reviewedColumns = activeTab === 'approved' ? approvedColumns : rejectedColumns

  return (
    <section>
      <Flex justify="space-between" align="center" className="page-heading">
        <div>
          <Typography.Title level={2}>算力申请</Typography.Title>
          <Typography.Text type="secondary">申请 GPU、CPU 和内存，并跟踪使用期限与资源调整审批。</Typography.Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={showUsageNotice} disabled={!availableProjects.length || !availableResources.length}>新建申请</Button>
      </Flex>
      <Card>
        <Tabs
          activeKey={activeTab}
          onChange={(key) => setActiveTab(key as ApprovalStatus)}
          items={[
            { key: 'pending', label: '申请中' },
            { key: 'approved', label: '已通过' },
            { key: 'rejected', label: '已拒绝' },
          ]}
        />
        {activeTab === 'pending' ? (
          <Table
            key="pending"
            rowKey="id"
            loading={loading}
            columns={pendingColumns}
            dataSource={pendingItems}
            scroll={{ x: 1000 }}
          />
        ) : (
          <Table
            key={activeTab}
            rowKey="id"
            loading={loading}
            columns={reviewedColumns}
            dataSource={visibleRequests}
            scroll={{ x: 1200 }}
            expandable={activeTab === 'approved' ? {
              rowExpandable: (row) => row.changes.length > 0,
              expandedRowRender: (row) => row.changes.length ? (
                <Space direction="vertical" className="full-width">
                  {row.changes.map((change) => (
                    <Flex key={change.id} gap={12} align="center" wrap>
                      <Tag>{changeLabels[change.change_type]}</Tag>
                      <span>{changeContent(change)}</span>
                      <Tag color={approvalLabels[change.approval_status][1]}>{approvalLabels[change.approval_status][0]}</Tag>
                      {change.review_comment && <Typography.Text type="secondary">{change.review_comment}</Typography.Text>}
                    </Flex>
                  ))}
                </Space>
              ) : <Typography.Text type="secondary">暂无变更记录</Typography.Text>,
            } : undefined}
          />
        )}
      </Card>

      <Modal
        title="算力资源使用须知"
        focusTriggerAfterClose={false}
        open={noticeOpen}
        onCancel={() => setNoticeOpen(false)}
        onOk={acceptUsageNotice}
        okButtonProps={{ disabled: noticeCountdown > 0 }}
        okText={noticeCountdown > 0 ? `请阅读（${noticeCountdown} 秒）` : '我已阅读，继续申请'}
        cancelText="取消"
        destroyOnHidden
      >
        <ol className="usage-notice-list">
          <li>算力申请原则上按照提交顺序依次审批；如遇论文 rebuttal 等紧急情况，请联系管理员说明。</li>
          <li>每次申请的使用时间不得超过 14 天。</li>
          <li>用户目录为持久化挂载目录，请将代码、数据和运行环境等内容统一存放在用户目录下。</li>
          <li>长时间未使用的算力资源会被系统记录，并可能被关停；如仍有使用需求，请重新提交申请。</li>
        </ol>
      </Modal>

      <Modal title="新建算力申请" open={requestOpen} onCancel={() => setRequestOpen(false)} onOk={() => requestForm.submit()} confirmLoading={busy} destroyOnHidden>
        <Form form={requestForm} layout="vertical" onFinish={submitRequest} preserve={false}>
          <Form.Item name="project_id" label="所属Squad" rules={[{ required: true }]}>
            <Select options={availableProjects.map((item) => ({ value: item.id, label: item.name }))} />
          </Form.Item>
          <Form.Item name="resource_id" label="算力资源" rules={[{ required: true }]}>
            <Select options={availableResources.map((item) => ({ value: item.id, label: `${item.name} · ${item.gpu_model} · ${item.gpu_count} 张` }))}
              onChange={(id) => {
                const resource = resources.find((item) => item.id === id)
                requestForm.setFieldsValue({ cpu_cores: resource?.default_cpu_cores, memory_gib: resource?.default_memory_gib })
              }} />
          </Form.Item>
          {selectedResource?.description?.trim() && <Alert type="info" showIcon style={{ marginBottom: 16 }} title="资源说明" description={
            <div style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 200, overflowY: 'auto' }}>{selectedResource.description}</div>
          } />}
          {selectedResource && <Alert type="info" showIcon style={{ marginBottom: 16 }} title="当前申请剩余额度" description={
            <Space direction="vertical" size={0}>
              <span>GPU：{quotaText(selectedResource.gpu_count, selectedResource.reserved_gpu_count, '张')}</span>
              <span>CPU：{quotaText(selectedResource.cpu_cores, selectedResource.reserved_cpu_cores, '核')}</span>
              <span>内存：{quotaText(selectedResource.memory_gib, selectedResource.reserved_memory_gib, 'GiB')}</span>
              <span>按已批准且未到期的申请计算，包含尚未启动的申请。</span>
            </Space>
          } />}
          {exceedsRemaining && <Alert type="warning" showIcon title="申请超过当前剩余额度，仍可提交，由管理员审批。" style={{ marginBottom: 16 }} />}
          <Form.Item name="gpu_count" label="需要 GPU 数量" extra="填写 0 表示仅申请 CPU 和内存" rules={[{ required: true, type: 'integer', min: 0, max: selectedResource?.gpu_count }]}>
            <InputNumber min={0} precision={0} className="full-width" />
          </Form.Item>
          <Form.Item name="cpu_cores" label="需要 CPU 核心数（逻辑核心）" rules={[{ required: true, type: 'integer', min: 1, max: selectedResource?.cpu_cores }]}>
            <InputNumber min={1} max={selectedResource?.cpu_cores} precision={0} className="full-width" />
          </Form.Item>
          <Form.Item name="memory_gib" label="需要内存（GiB）" rules={[{ required: true, type: 'integer', min: 1, max: selectedResource?.memory_gib }]}>
            <InputNumber min={1} max={selectedResource?.memory_gib} precision={0} className="full-width" />
          </Form.Item>
          <Form.Item
            name="duration_days"
            label="需要天数"
            rules={[
              { required: true, message: '请填写需要天数' },
              { type: 'number', min: 1, max: 14, message: '使用时长仅限1-14 天' },
            ]}
          >
            <InputNumber min={1} max={14} precision={0} className="full-width" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="申请变更" open={!!changeTarget} onCancel={() => setChangeTarget(null)} onOk={() => changeForm.submit()} confirmLoading={busy} destroyOnHidden>
        {changeTarget && <Typography.Paragraph type="secondary">
          当前获批：{requestContent(changeTarget)}。CPU、内存填写调整后的总量；审批通过后，已有容器需由管理员同步调整配置。
        </Typography.Paragraph>}
        <Form form={changeForm} layout="vertical" onFinish={submitChange} preserve={false}>
          <Form.Item name="change_type" label="变更类型" rules={[{ required: true }]}>
            <Select options={Object.entries(changeLabels).filter(([value]) => changeTarget?.runtime_status !== 'not_started' || value === 'cpu' || value === 'memory').map(([value, label]) => ({ value, label }))} onChange={() => changeForm.setFieldValue('amount', undefined)} />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(previous, current) => previous.change_type !== current.change_type}>
            {({ getFieldValue }) => (
              <Form.Item name="amount" label={getFieldValue('change_type') === 'cpu' ? '调整后的 CPU 总核心数' : getFieldValue('change_type') === 'memory' ? '调整后的内存总量（GiB）' : getFieldValue('change_type') === 'extend' ? '增加天数' : '增加或释放 GPU 张数'} rules={[{ required: true }]}>
                <InputNumber min={1} max={getFieldValue('change_type') === 'extend' ? 14 : undefined} precision={0} className="full-width" />
              </Form.Item>
            )}
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={reviewTarget?.change ? `审核${changeLabels[reviewTarget.change.change_type]}申请` : '审核算力申请'}
        open={!!reviewTarget}
        onCancel={() => setReviewTarget(null)}
        onOk={() => reviewForm.submit()}
        confirmLoading={busy}
        destroyOnHidden
      >
        {reviewTarget && (
          <Flex vertical gap={4} className="review-target-summary">
            <Typography.Text type="secondary">
              {reviewTarget.request.applicant_name} · {reviewTarget.request.project_name} · {reviewTarget.request.resource_name}
            </Typography.Text>
            <Typography.Text strong>
              {reviewTarget.change ? changeContent(reviewTarget.change) : requestContent(reviewTarget.request)}
            </Typography.Text>
          </Flex>
        )}
        <Form form={reviewForm} layout="vertical" onFinish={submitReview} preserve={false} initialValues={{ decision: 'approved' }}>
          <Form.Item name="decision" label="审核结果" rules={[{ required: true }]}>
            <Select options={[{ value: 'approved', label: '通过' }, { value: 'rejected', label: '拒绝' }]} />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(previous, current) => previous.decision !== current.decision}>
            {({ getFieldValue }) => (
              <Form.Item name="comment" label="审核意见" rules={getFieldValue('decision') === 'rejected' ? [{ required: true, whitespace: true }] : []}>
                <Input.TextArea rows={4} maxLength={4000} />
              </Form.Item>
            )}
          </Form.Item>
        </Form>
      </Modal>
    </section>
  )
}
