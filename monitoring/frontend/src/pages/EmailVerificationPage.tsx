import { Alert, Button, Card, Spin, Typography } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { api, errorMessage } from '../api'
import { useAuth } from '../auth'
import { useNavigation } from '../routing'

export function EmailVerificationPage() {
  const { navigate } = useNavigation()
  const { refresh } = useAuth()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const submittedToken = useRef('')
  const token = new URLSearchParams(window.location.search).get('token') ?? ''

  useEffect(() => {
    if (!token) { setError('验证链接缺少 Token'); setLoading(false); return }
    if (submittedToken.current === token) return
    submittedToken.current = token
    setLoading(true)
    setError('')
    api.post('/auth/email/change-confirm', { token })
      .then(() => refresh())
      .catch((requestError) => setError(errorMessage(requestError)))
      .finally(() => setLoading(false))
  }, [refresh, token])

  return (
    <main className="login-page">
      <Card className="login-card">
        <Typography.Title level={2}>邮箱验证</Typography.Title>
        {loading ? <Spin /> : error
          ? <>
              <Alert type="error" showIcon message={error} />
            </>
          : <Alert type="success" showIcon message="邮箱已验证，可用于找回密码。" />}
        <Button block className="form-footer-button" onClick={() => navigate('/')}>
          返回平台
        </Button>
      </Card>
    </main>
  )
}
