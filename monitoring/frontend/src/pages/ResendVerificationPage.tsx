import { Alert, Button, Card, Typography } from 'antd'
import { useNavigation } from '../routing'

export function ResendVerificationPage() {
  const { navigate } = useNavigation()
  return (
    <main className="login-page">
      <Card className="login-card">
        <Typography.Title level={2}>注册无需验证邮箱</Typography.Title>
        <Alert type="info" showIcon message="注册已改为管理员审核，无需验证邮箱。历史待验证申请也可直接审核，请等待管理员审核，无需重新注册。" />
        <Button type="primary" block className="form-footer-button" onClick={() => navigate('/register')}>前往注册</Button>
        <Button type="link" block onClick={() => navigate('/login')}>返回登录</Button>
      </Card>
    </main>
  )
}
