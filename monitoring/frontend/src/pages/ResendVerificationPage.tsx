import { Alert, Button, Card, Form, Input, Typography } from 'antd'
import { useState } from 'react'
import { api, errorMessage } from '../api'
import { useNavigation } from '../routing'

export function ResendVerificationPage() {
  const { navigate } = useNavigation()
  const [sent, setSent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (values: { identity: string }) => {
    setBusy(true)
    setError('')
    try {
      await api.post('/auth/registration/resend', values)
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
        <Typography.Title level={2}>重新发送验证邮件</Typography.Title>
        {sent ? (
          <Alert type="success" showIcon message="如果注册申请仍待验证，新的验证邮件已经发送，旧链接已失效。" />
        ) : (
          <Form layout="vertical" onFinish={submit}>
            {error && <Alert type="error" showIcon message={error} className="login-error" />}
            <Form.Item name="identity" label="用户名或邮箱" rules={[{ required: true, whitespace: true }]}>
              <Input maxLength={320} autoComplete="username" />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={busy}>重新发送</Button>
          </Form>
        )}
        <Button type="link" block className="form-footer-button" onClick={() => navigate('/login')}>返回登录</Button>
      </Card>
    </main>
  )
}
