import { LogoutOutlined } from '@ant-design/icons'
import { Button, Layout, Space, Typography } from 'antd'
import type { PropsWithChildren } from 'react'
import { useAuth } from '../auth'
import { useNavigation } from '../routing'
import { EmailVerificationPrompt } from './EmailVerificationPrompt'

export function AppShell({ children }: PropsWithChildren) {
  const { session, logout } = useAuth()
  const { navigate, path } = useNavigation()

  const handleLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  const navigation = [
    { path: '/', label: '算力资源' },
    { path: '/requests', label: '算力申请' },
    ...(session?.role === 'admin' ? [
      { path: '/users', label: '用户管理' },
      { path: '/projects', label: 'Squad管理' },
      { path: '/history/users', label: '用户历史' },
      { path: '/history/projects', label: 'Squad历史' },
      { path: '/settings', label: '设置' },
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
          <Button type="text" icon={<LogoutOutlined />} onClick={handleLogout}>退出</Button>
        </Space>
      </Layout.Header>
      <Layout.Content className="app-content">
        <EmailVerificationPrompt />
        {children}
      </Layout.Content>
    </Layout>
  )
}
