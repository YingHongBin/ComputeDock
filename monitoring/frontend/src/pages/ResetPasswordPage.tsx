import { Alert, Button, Card, Form, Input, Typography } from 'antd'
import { useState } from 'react'
import { api, errorMessage } from '../api'
import { useNavigation } from '../routing'

export function ResetPasswordPage() {
  const { navigate } = useNavigation()
  const token = new URLSearchParams(window.location.search).get('token') ?? ''
  const [done, setDone] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (values: { new_password: string }) => {
    setBusy(true)
    setError('')
    try {
      await api.post('/auth/password/reset', { token, ...values })
      setDone(true)
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="login-page">
      <Card className="login-card">
        <Typography.Title level={2}>设置新密码</Typography.Title>
        {error && <Alert type="error" showIcon message={error} className="login-error" />}
        {done ? (
          <>
            <Alert type="success" showIcon message="密码已重置，请重新登录。" />
            <Button block className="form-footer-button" onClick={() => navigate('/login')}>前往登录</Button>
          </>
        ) : (
          <Form layout="vertical" onFinish={submit}>
            <Form.Item name="new_password" label="新密码" rules={[{ required: true }, { min: 12, message: '至少 12 个字符' }]}>
              <Input.Password autoComplete="new-password" />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={busy} disabled={!token}>重置密码</Button>
          </Form>
        )}
      </Card>
    </main>
  )
}
