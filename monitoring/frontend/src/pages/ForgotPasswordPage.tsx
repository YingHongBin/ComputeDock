import { Alert, Button, Card, Form, Input, Typography } from 'antd'
import { useState } from 'react'
import { api, errorMessage } from '../api'
import { useNavigation } from '../routing'

export function ForgotPasswordPage() {
  const { navigate } = useNavigation()
  const [sent, setSent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (values: { identity: string }) => {
    setBusy(true)
    setError('')
    try {
      await api.post('/auth/password/reset-request', values)
      setSent(true)
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="login-page">
      <Card className="login-card">
        <div className="login-brand">C</div>
        <Typography.Title level={2}>重置密码</Typography.Title>
        {sent ? (
          <Alert type="success" showIcon message="如果账户存在且邮箱已验证，重置邮件已经发送。" />
        ) : (
          <Form layout="vertical" onFinish={submit}>
            {error && <Alert type="error" showIcon message={error} className="login-error" />}
            <Form.Item name="identity" label="用户名或邮箱" rules={[{ required: true }]}>
              <Input autoComplete="username" />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={busy}>发送重置邮件</Button>
          </Form>
        )}
        <Button type="link" block className="form-footer-button" onClick={() => navigate('/login')}>返回登录</Button>
      </Card>
    </main>
  )
}
