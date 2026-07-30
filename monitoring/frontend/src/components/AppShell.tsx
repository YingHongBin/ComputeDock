import { LogoutOutlined } from '@ant-design/icons'
import { App, Button, Form, Input, Layout, Modal, Space, Typography } from 'antd'
import { useState } from 'react'
import type { PropsWithChildren } from 'react'
import { api, csrfHeaders } from '../api'
import { useAuth } from '../auth'
import { useNavigation } from '../routing'

export function AppShell({ children }: PropsWithChildren) {
  const { session, logout } = useAuth()
  const { message } = App.useApp()
  const { navigate } = useNavigation()
  const [passwordOpen, setPasswordOpen] = useState(false)
  const [passwordBusy, setPasswordBusy] = useState(false)
  const [passwordForm] = Form.useForm()

  const handleLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  const changePassword = async (values: { current_password: string; new_password: string }) => {
    setPasswordBusy(true)
    try {
      await api.post('/auth/password', values, {
        headers: csrfHeaders(session?.csrf_token ?? ''),
      })
      message.success('密码已修改')
      passwordForm.resetFields()
      setPasswordOpen(false)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '密码修改失败')
    } finally {
      setPasswordBusy(false)
    }
  }

  return (
    <Layout className="app-layout">
      <Layout.Header className="app-header">
        <Space size="middle">
          <div className="brand-mark">C</div>
          <Typography.Title level={4} className="brand-title">ComputeDock 算力监控</Typography.Title>
        </Space>
        <Space>
          <Typography.Text className="header-user">{session?.username}</Typography.Text>
          <Button type="text" onClick={() => setPasswordOpen(true)}>修改密码</Button>
          <Button type="text" icon={<LogoutOutlined />} onClick={handleLogout}>退出</Button>
        </Space>
      </Layout.Header>
      <Layout.Content className="app-content">{children}</Layout.Content>
      <Modal
        title="修改管理员密码"
        open={passwordOpen}
        onCancel={() => setPasswordOpen(false)}
        onOk={() => passwordForm.submit()}
        confirmLoading={passwordBusy}
        destroyOnClose
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
    </Layout>
  )
}
