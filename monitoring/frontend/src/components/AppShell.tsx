import { LogoutOutlined, MailOutlined } from '@ant-design/icons'
import { Alert, App, Button, Form, Input, Layout, Modal, Space, Typography } from 'antd'
import { useState } from 'react'
import type { PropsWithChildren } from 'react'
import { api, csrfHeaders, errorMessage } from '../api'
import { useAuth } from '../auth'
import { useNavigation } from '../routing'

export function AppShell({ children }: PropsWithChildren) {
  const { session, logout } = useAuth()
  const { message } = App.useApp()
  const { navigate, path } = useNavigation()
  const [passwordOpen, setPasswordOpen] = useState(false)
  const [emailOpen, setEmailOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [passwordForm] = Form.useForm()
  const [emailForm] = Form.useForm()

  const handleLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  const changePassword = async (values: { current_password: string; new_password: string }) => {
    setBusy(true)
    try {
      await api.post('/auth/password', values, {
        headers: csrfHeaders(session?.csrf_token ?? ''),
      })
      message.success('密码已修改')
      passwordForm.resetFields()
      setPasswordOpen(false)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const changeEmail = async (values: { current_password: string; new_email: string }) => {
    setBusy(true)
    try {
      await api.post('/auth/email/change-request', values, {
        headers: csrfHeaders(session?.csrf_token ?? ''),
      })
      message.success('验证邮件已发送到新邮箱')
      emailForm.resetFields()
      setEmailOpen(false)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const navigation = [
    { path: '/', label: '算力资源' },
    { path: '/requests', label: '算力申请' },
    ...(session?.role === 'admin' ? [
      { path: '/users', label: '用户管理' },
      { path: '/projects', label: '项目管理' },
      { path: '/history/users', label: '用户历史' },
      { path: '/history/projects', label: '项目历史' },
    ] : []),
  ]

  return (
    <Layout className="app-layout">
      <Layout.Header className="app-header">
        <Space size="middle" className="brand-area">
          <div className="brand-mark">C</div>
          <Typography.Title level={4} className="brand-title">ComputeDock</Typography.Title>
        </Space>
        <Space className="app-nav" size={2}>
          {navigation.map((item) => (
            <Button
              key={item.path}
              type={path === item.path ? 'primary' : 'text'}
              onClick={() => navigate(item.path)}
            >
              {item.label}
            </Button>
          ))}
        </Space>
        <Space className="account-actions">
          <Typography.Text className="header-user">{session?.full_name}</Typography.Text>
          <Button type="text" icon={<MailOutlined />} onClick={() => setEmailOpen(true)}>邮箱</Button>
          <Button type="text" onClick={() => setPasswordOpen(true)}>密码</Button>
          <Button type="text" icon={<LogoutOutlined />} onClick={handleLogout}>退出</Button>
        </Space>
      </Layout.Header>
      <Layout.Content className="app-content">
        {session?.must_bind_email && (
          <Alert
            type="warning"
            showIcon
            message="请绑定并验证邮箱，以接收审核、密码重置和到期通知。"
            action={<Button size="small" onClick={() => setEmailOpen(true)}>绑定邮箱</Button>}
            className="profile-alert"
          />
        )}
        {children}
      </Layout.Content>
      <Modal
        title="修改密码"
        open={passwordOpen}
        onCancel={() => setPasswordOpen(false)}
        onOk={() => passwordForm.submit()}
        confirmLoading={busy}
        destroyOnHidden
      >
        <Form form={passwordForm} layout="vertical" onFinish={changePassword} preserve={false}>
          <Form.Item name="current_password" label="当前密码" rules={[{ required: true }]}>
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Form.Item name="new_password" label="新密码" rules={[{ required: true }, { min: 12, message: '至少 12 个字符' }]}>
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title="更换绑定邮箱"
        open={emailOpen}
        onCancel={() => setEmailOpen(false)}
        onOk={() => emailForm.submit()}
        confirmLoading={busy}
        destroyOnHidden
      >
        <Form form={emailForm} layout="vertical" onFinish={changeEmail} preserve={false}>
          <Form.Item name="current_password" label="当前密码" rules={[{ required: true }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item name="new_email" label="新邮箱" rules={[{ required: true }, { type: 'email' }]}>
            <Input autoComplete="email" />
          </Form.Item>
        </Form>
      </Modal>
    </Layout>
  )
}
