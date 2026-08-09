import { Alert, Button, Card, Spin, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { api, errorMessage } from '../api'
import { useAuth } from '../auth'
import { useNavigation } from '../routing'

export function EmailVerificationPage({ emailChange = false }: { emailChange?: boolean }) {
  const { navigate } = useNavigation()
  const { refresh } = useAuth()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const token = new URLSearchParams(window.location.search).get('token') ?? ''

  useEffect(() => {
    if (!token) { setError('验证链接缺少 Token'); setLoading(false); return }
    api.post(emailChange ? '/auth/email/change-confirm' : '/auth/verify-email', { token })
      .then(() => emailChange ? refresh() : undefined)
      .catch((requestError) => setError(errorMessage(requestError)))
      .finally(() => setLoading(false))
  }, [emailChange, token])

  return (
    <main className="login-page">
      <Card className="login-card">
        <Typography.Title level={2}>邮箱验证</Typography.Title>
        {loading ? <Spin /> : error
          ? <>
              <Alert type="error" showIcon message={error} />
              {!emailChange && <Button type="link" block onClick={() => navigate('/resend-verification')}>重新发送验证邮件</Button>}
            </>
          : <Alert type="success" showIcon message={emailChange ? '新邮箱已绑定。' : '邮箱已验证，注册申请已提交管理员审核。'} />}
        <Button block className="form-footer-button" onClick={() => navigate(emailChange ? '/' : '/login')}>
          {emailChange ? '返回平台' : '返回登录'}
        </Button>
      </Card>
    </main>
  )
}
