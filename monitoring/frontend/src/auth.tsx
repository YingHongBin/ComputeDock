import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { PropsWithChildren } from 'react'
import { api, csrfHeaders } from './api'
import type { AdminSession } from './types'

interface AuthContextValue {
  session: AdminSession | null
  loading: boolean
  refresh: () => Promise<void>
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: PropsWithChildren) {
  const [session, setSession] = useState<AdminSession | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const { data } = await api.get<AdminSession>('/auth/me')
      setSession(data)
    } catch {
      setSession(null)
    }
  }, [])

  useEffect(() => {
    refresh().finally(() => setLoading(false))
  }, [])

  const value = useMemo<AuthContextValue>(() => ({
    session,
    loading,
    refresh,
    login: async (username, password) => {
      const { data } = await api.post<AdminSession>('/auth/login', { username, password })
      setSession(data)
    },
    logout: async () => {
      if (session) {
        await api.post('/auth/logout', undefined, { headers: csrfHeaders(session.csrf_token) })
      }
      setSession(null)
    },
  }), [loading, refresh, session])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('AuthProvider is missing')
  return value
}
