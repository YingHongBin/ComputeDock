import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Flex, Form, Input, Typography } from 'antd'
import { useState } from 'react'
import { errorMessage } from '../api'
import { useAuth } from '../auth'
import { useNavigation } from '../routing'

export function LoginPage() {
  const { login } = useAuth()
  const { navigate } = useNavigation()
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const submit = async (value: { username: string; password: string }) => {
    setError('')
    setSubmitting(true)
    try {
      await login(value.username, value.password)
      navigate('/', { replace: true })
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="login-page">
      <Card className="login-card">
        <div className="login-brand">C</div>
        <Typography.Title level={2}>ComputeDock</Typography.Title>
        <Typography.Paragraph type="secondary">算力资源监控管理平台</Typography.Paragraph>
        {error && <Alert type="error" message={error} showIcon className="login-error" />}
        <Form layout="vertical" onFinish={submit} requiredMark={false}>
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} size="large" placeholder="用户名" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} size="large" placeholder="密码" />
          </Form.Item>
          <Button type="primary" htmlType="submit" size="large" block loading={submitting}>登录</Button>
        </Form>
        <Flex justify="space-between" className="login-links">
          <Button type="link" onClick={() => navigate('/register')}>注册账号</Button>
          <Button type="link" onClick={() => navigate('/forgot-password')}>忘记密码</Button>
        </Flex>
      </Card>
    </main>
  )
}
