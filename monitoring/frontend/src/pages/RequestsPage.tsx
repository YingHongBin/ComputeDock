import { CopyOutlined, PlusOutlined } from '@ant-design/icons'
import { App, Button, Card, Flex, Form, Input, InputNumber, Modal, Select, Space, Table, Tag, Typography } from 'antd'
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

const changeLabels = { extend: '延时', expand: '扩容', release: '释放' }

type ReviewTarget = { request: ComputeRequestData; change?: ComputeRequestChangeData }

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
  const [busy, setBusy] = useState(false)
  const [requestForm] = Form.useForm()
  const [changeForm] = Form.useForm()
  const [reviewForm] = Form.useForm()

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

  const acceptUsageNotice = () => {
    if (noticeCountdown > 0) return
    setNoticeOpen(false)
    setRequestOpen(true)
  }

  const availableProjects = projects.filter((project) =>
    project.status === 'active' && project.members.some((member) => member.username === session?.username))
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

  const columns = useMemo<ColumnsType<ComputeRequestData>>(() => [
    { title: '申请人', dataIndex: 'applicant_name', width: 120 },
    { title: '项目', dataIndex: 'project_name', width: 150 },
    { title: '算力资源', dataIndex: 'resource_name', width: 150 },
    { title: 'GPU', dataIndex: 'gpu_count', width: 80, render: (value, row) => <span>{value} 张{row.over_quota && <Tag color="error" className="inline-tag">超额 {row.actual_gpu_count}</Tag>}</span> },
    { title: '天数', dataIndex: 'duration_days', width: 80 },
    { title: '审批', dataIndex: 'approval_status', width: 100, render: (value: keyof typeof approvalLabels) => <Tag color={approvalLabels[value][1]}>{approvalLabels[value][0]}</Tag> },
    { title: '运行', dataIndex: 'runtime_status', width: 110, render: (value: keyof typeof runtimeLabels | null) => value ? <Tag color={runtimeLabels[value][1]}>{runtimeLabels[value][0]}</Tag> : '--' },
    { title: '到期时间', dataIndex: 'expires_at', width: 170, render: (value) => value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '--' },
    {
      title: '操作', width: 230, fixed: 'right', render: (_, row) => (
        <Space wrap>
          {session?.role === 'admin' && row.approval_status === 'pending' && (
            <Button size="small" type="primary" onClick={() => setReviewTarget({ request: row })}>审核</Button>
          )}
          {session?.role === 'admin' && row.token && (
            <Button size="small" icon={<CopyOutlined />} onClick={() => void copyToken(row.token!)}>复制 Token</Button>
          )}
          {row.applicant_username === session?.username && row.approval_status === 'approved' && row.runtime_status !== 'not_started' && row.runtime_status !== 'expired' && !row.changes.some((item) => item.approval_status === 'pending') && (
            <Button size="small" onClick={() => setChangeTarget(row)}>申请变更</Button>
          )}
        </Space>
      ),
    },
  ], [session])

  return (
    <section>
      <Flex justify="space-between" align="center" className="page-heading">
        <div>
          <Typography.Title level={2}>算力申请</Typography.Title>
          <Typography.Text type="secondary">申请 GPU 资源，并跟踪延时、扩容和释放审核。</Typography.Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={showUsageNotice} disabled={!availableProjects.length || !availableResources.length}>新建申请</Button>
      </Flex>
      <Card>
        <Table
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={requests}
          scroll={{ x: 1200 }}
          expandable={{
            expandedRowRender: (row) => row.changes.length ? (
              <Space direction="vertical" className="full-width">
                {row.changes.map((change) => (
                  <Flex key={change.id} gap={12} align="center" wrap>
                    <Tag>{changeLabels[change.change_type]}</Tag>
                    <span>{change.before_value} → {change.after_value}</span>
                    <Tag color={approvalLabels[change.approval_status][1]}>{approvalLabels[change.approval_status][0]}</Tag>
                    {change.review_comment && <Typography.Text type="secondary">{change.review_comment}</Typography.Text>}
                    {session?.role === 'admin' && change.approval_status === 'pending' && (
                      <Button size="small" type="primary" onClick={() => setReviewTarget({ request: row, change })}>审核变更</Button>
                    )}
                  </Flex>
                ))}
              </Space>
            ) : <Typography.Text type="secondary">暂无变更记录</Typography.Text>,
          }}
        />
      </Card>

      <Modal
        title="算力资源使用须知"
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
          <Form.Item name="project_id" label="所属项目" rules={[{ required: true }]}>
            <Select options={availableProjects.map((item) => ({ value: item.id, label: item.name }))} />
          </Form.Item>
          <Form.Item name="resource_id" label="算力资源" rules={[{ required: true }]}>
            <Select options={availableResources.map((item) => ({ value: item.id, label: `${item.name} · ${item.gpu_model} · ${item.gpu_count} 张` }))} />
          </Form.Item>
          <Form.Item name="gpu_count" label="需要 GPU 数量" rules={[{ required: true }]}>
            <InputNumber min={1} precision={0} className="full-width" />
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
        <Form form={changeForm} layout="vertical" onFinish={submitChange} preserve={false}>
          <Form.Item name="change_type" label="变更类型" rules={[{ required: true }]}>
            <Select options={[{ value: 'extend', label: '延时' }, { value: 'expand', label: '扩容' }, { value: 'release', label: '释放部分算力' }]} />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(previous, current) => previous.change_type !== current.change_type}>
            {({ getFieldValue }) => (
              <Form.Item name="amount" label="增加天数或 GPU 数量" rules={[{ required: true }]}>
                <InputNumber min={1} max={getFieldValue('change_type') === 'extend' ? 14 : undefined} precision={0} className="full-width" />
              </Form.Item>
            )}
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="审核" open={!!reviewTarget} onCancel={() => setReviewTarget(null)} onOk={() => reviewForm.submit()} confirmLoading={busy} destroyOnHidden>
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
