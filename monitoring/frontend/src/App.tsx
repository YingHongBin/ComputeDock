import { ConfigProvider, Spin, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { useEffect } from 'react'
import { useAuth } from './auth'
import { AppShell } from './components/AppShell'
import { LoginPage } from './pages/LoginPage'
import { OverviewPage } from './pages/OverviewPage'
import { ResourceDetailPage } from './pages/ResourceDetailPage'
import { useNavigation } from './routing'

function Redirect({ to }: { to: string }) {
  const { navigate } = useNavigation()
  useEffect(() => navigate(to, { replace: true }), [navigate, to])
  return null
}

export default function App() {
  const { session, loading } = useAuth()
  const { path } = useNavigation()
  let page
  if (loading) page = <div className="fullscreen-spin"><Spin size="large" /></div>
  else if (path === '/login') page = session ? <Redirect to="/" /> : <LoginPage />
  else if (!session) page = <Redirect to="/login" />
  else if (path === '/') page = <AppShell><OverviewPage /></AppShell>
  else {
    const match = path.match(/^\/resources\/([0-9a-f-]+)$/i)
    page = match
      ? <AppShell><ResourceDetailPage resourceId={match[1]} /></AppShell>
      : <Redirect to="/" />
  }

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: { colorPrimary: '#2563eb', borderRadius: 10, colorBgLayout: '#f5f7fb' },
      }}
    >
      {page}
    </ConfigProvider>
  )
}
