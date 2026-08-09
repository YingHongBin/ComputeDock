import { App, Button, Card, Form, Input, Modal, Select, Space, Table, Tabs, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useEffect, useState } from 'react'
import { api, csrfHeaders, errorMessage } from '../api'
import { useAuth } from '../auth'
import type { RegistrationData, UserData } from '../types'

export function UsersPage() {
  const { session } = useAuth()
  const { message } = App.useApp()
  const [users, setUsers] = useState<UserData[]>([])
  const [registrations, setRegistrations] = useState<RegistrationData[]>([])
  const [reviewTarget, setReviewTarget] = useState<RegistrationData | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [reviewForm] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try {
      const [userResponse, registrationResponse] = await Promise.all([
        api.get<UserData[]>('/users'),
        api.get<RegistrationData[]>('/users/registrations'),
      ])
      setUsers(userResponse.data)
      setRegistrations(registrationResponse.data)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  const updateUser = async (user: UserData, changes: Partial<Pick<UserData, 'role' | 'status'>>) => {
    if (!session) return
    try {
      await api.patch(`/users/${user.id}`, changes, { headers: csrfHeaders(session.csrf_token) })
      message.success('用户已更新')
      await load()
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  const resetPassword = async (user: UserData) => {
    if (!session) return
    try {
      await api.post(`/users/${user.id}/password-reset`, undefined, { headers: csrfHeaders(session.csrf_token) })
      message.success('密码重置邮件已发送')
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  const review = async (values: { decision: 'approved' | 'rejected'; comment?: string }) => {
    if (!session || !reviewTarget) return
    setBusy(true)
    try {
      await api.post(`/users/registrations/${reviewTarget.id}/review`, values, { headers: csrfHeaders(session.csrf_token) })
      message.success('注册申请已审核')
      setReviewTarget(null)
      reviewForm.resetFields()
      await load()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const userColumns: ColumnsType<UserData> = [
    { title: '用户名', dataIndex: 'username' },
    { title: '姓名', dataIndex: 'full_name' },
    { title: '邮箱', dataIndex: 'email', render: (value, row) => value ? <Space>{value}{!row.email_verified_at && <Tag>未验证</Tag>}</Space> : '--' },
    { title: '角色', dataIndex: 'role', render: (value) => value === 'admin' ? <Tag color="purple">管理员</Tag> : <Tag>普通用户</Tag> },
    { title: '状态', dataIndex: 'status', render: (value) => value === 'active' ? <Tag color="success">正常</Tag> : <Tag color="error">已禁用</Tag> },
    {
      title: '操作', width: 300, render: (_, row) => (
        <Space wrap>
          <Button size="small" disabled={row.username === session?.username} onClick={() => void updateUser(row, { status: row.status === 'active' ? 'disabled' : 'active' })}>{row.status === 'active' ? '禁用' : '启用'}</Button>
          <Button size="small" disabled={row.username === session?.username} onClick={() => void updateUser(row, { role: row.role === 'admin' ? 'user' : 'admin' })}>{row.role === 'admin' ? '降为普通用户' : '设为管理员'}</Button>
          <Button size="small" onClick={() => void resetPassword(row)}>发送重置邮件</Button>
        </Space>
      ),
    },
  ]

  const registrationColumns: ColumnsType<RegistrationData> = [
    { title: '用户名', dataIndex: 'username' },
    { title: '姓名', dataIndex: 'full_name' },
    { title: '邮箱', dataIndex: 'email' },
    { title: '提交时间', dataIndex: 'created_at', render: (value) => dayjs(value).format('YYYY-MM-DD HH:mm') },
    { title: '状态', dataIndex: 'status', render: (value) => <Tag color={value === 'pending' ? 'processing' : value === 'approved' ? 'success' : 'error'}>{value === 'pending' ? '待审核' : value === 'approved' ? '已通过' : '已拒绝'}</Tag> },
    { title: '审核意见', dataIndex: 'review_comment', render: (value) => value || '--' },
    { title: '操作', width: 100, render: (_, row) => row.status === 'pending' ? <Button type="primary" size="small" onClick={() => setReviewTarget(row)}>审核</Button> : null },
  ]

  return (
    <section>
      <div className="page-heading">
        <Typography.Title level={2}>用户管理</Typography.Title>
        <Typography.Text type="secondary">审核注册、管理角色与账户状态。</Typography.Text>
      </div>
      <Card>
        <Tabs items={[
          { key: 'users', label: '正式用户', children: <Table rowKey="id" loading={loading} columns={userColumns} dataSource={users} scroll={{ x: 1000 }} /> },
          { key: 'registrations', label: `注册审核 (${registrations.filter((item) => item.status === 'pending').length})`, children: <Table rowKey="id" loading={loading} columns={registrationColumns} dataSource={registrations} scroll={{ x: 900 }} /> },
        ]} />
      </Card>
      <Modal title="审核注册申请" open={!!reviewTarget} onCancel={() => setReviewTarget(null)} onOk={() => reviewForm.submit()} confirmLoading={busy} destroyOnHidden>
        <Form form={reviewForm} layout="vertical" onFinish={review} initialValues={{ decision: 'approved' }} preserve={false}>
          <Form.Item name="decision" label="审核结果" rules={[{ required: true }]}>
            <Select options={[{ value: 'approved', label: '通过' }, { value: 'rejected', label: '拒绝' }]} />
          </Form.Item>
          <Form.Item noStyle shouldUpdate>
            {({ getFieldValue }) => <Form.Item name="comment" label="审核意见" rules={getFieldValue('decision') === 'rejected' ? [{ required: true, whitespace: true }] : []}><Input.TextArea rows={4} /></Form.Item>}
          </Form.Item>
        </Form>
      </Modal>
    </section>
  )
}
