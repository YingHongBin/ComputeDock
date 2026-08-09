import { Alert, Button, Card, Form, Input, Typography } from 'antd'
import { useState } from 'react'
import { api, errorMessage } from '../api'
import { useNavigation } from '../routing'

export function RegisterPage() {
  const { navigate } = useNavigation()
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [sent, setSent] = useState(false)

  const submit = async (values: Record<string, string>) => {
    setSubmitting(true)
    setError('')
    try {
      await api.post('/auth/register', values)
      setSent(true)
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
        <Typography.Title level={2}>注册 ComputeDock</Typography.Title>
        <Typography.Paragraph type="secondary">验证邮箱后，注册申请将交由管理员审核。</Typography.Paragraph>
        {sent ? (
          <>
            <Alert type="success" showIcon message="验证邮件已发送，请在 24 小时内完成验证。" />
            <Button type="link" block onClick={() => navigate('/resend-verification')}>没有收到？重新发送</Button>
            <Button block className="form-footer-button" onClick={() => navigate('/login')}>返回登录</Button>
          </>
        ) : (
          <Form layout="vertical" onFinish={submit} requiredMark={false}>
            {error && <Alert type="error" showIcon message={error} className="login-error" />}
            <Form.Item name="username" label="用户名" rules={[{ required: true, whitespace: true }]}>
              <Input maxLength={100} autoComplete="username" />
            </Form.Item>
            <Form.Item name="full_name" label="姓名" rules={[{ required: true, whitespace: true }]}>
              <Input maxLength={200} />
            </Form.Item>
            <Form.Item name="email" label="邮箱" rules={[{ required: true }, { type: 'email' }]}>
              <Input maxLength={320} autoComplete="email" />
            </Form.Item>
            <Form.Item name="password" label="密码" rules={[{ required: true }, { min: 12, message: '至少 12 个字符' }]}>
              <Input.Password autoComplete="new-password" />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={submitting}>提交注册</Button>
            <Button type="link" block onClick={() => navigate('/login')}>已有账号，返回登录</Button>
          </Form>
        )}
      </Card>
    </main>
  )
}
