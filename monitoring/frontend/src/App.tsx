import { ConfigProvider, Spin, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { useEffect } from 'react'
import { useAuth } from './auth'
import { AppShell } from './components/AppShell'
import { EmailVerificationPage } from './pages/EmailVerificationPage'
import { ForgotPasswordPage } from './pages/ForgotPasswordPage'
import { HistoryContainerPage } from './pages/HistoryContainerPage'
import { HistoryPage } from './pages/HistoryPage'
import { LoginPage } from './pages/LoginPage'
import { OverviewPage } from './pages/OverviewPage'
import { ProjectsPage } from './pages/ProjectsPage'
import { RegisterPage } from './pages/RegisterPage'
import { ResendVerificationPage } from './pages/ResendVerificationPage'
import { ResourceDetailPage } from './pages/ResourceDetailPage'
import { RequestsPage } from './pages/RequestsPage'
import { ResetPasswordPage } from './pages/ResetPasswordPage'
import { SettingsPage } from './pages/SettingsPage'
import { UsersPage } from './pages/UsersPage'
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
  else if (path === '/register') page = <RegisterPage />
  else if (path === '/resend-verification') page = <ResendVerificationPage />
  else if (path === '/forgot-password') page = <ForgotPasswordPage />
  else if (path === '/reset-password') page = <ResetPasswordPage />
  else if (path === '/verify-email') page = <EmailVerificationPage />
  else if (path === '/verify-new-email') page = <EmailVerificationPage emailChange />
  else if (!session) page = <Redirect to="/login" />
  else if (path === '/') page = <AppShell><OverviewPage /></AppShell>
  else if (path === '/requests') page = <AppShell><RequestsPage /></AppShell>
  else if (path === '/users') page = session.role === 'admin' ? <AppShell><UsersPage /></AppShell> : <Redirect to="/" />
  else if (path === '/projects') page = session.role === 'admin' ? <AppShell><ProjectsPage /></AppShell> : <Redirect to="/" />
  else if (path === '/history/users') page = session.role === 'admin' ? <AppShell><HistoryPage mode="users" /></AppShell> : <Redirect to="/" />
  else if (path === '/history/projects') page = session.role === 'admin' ? <AppShell><HistoryPage mode="projects" /></AppShell> : <Redirect to="/" />
  else if (path === '/settings') page = session.role === 'admin' ? <AppShell><SettingsPage /></AppShell> : <Redirect to="/" />
  else {
    const resourceMatch = path.match(/^\/resources\/([0-9a-f-]+)$/i)
    const historyMatch = path.match(/^\/history\/containers\/([0-9a-f-]+)$/i)
    if (resourceMatch) page = <AppShell><ResourceDetailPage resourceId={resourceMatch[1]} /></AppShell>
    else if (historyMatch && session.role === 'admin') page = <AppShell><HistoryContainerPage containerId={historyMatch[1]} /></AppShell>
    else page = <Redirect to="/" />
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
