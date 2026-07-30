import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { PropsWithChildren } from 'react'

interface NavigateOptions {
  replace?: boolean
}

interface NavigationContextValue {
  path: string
  navigate: (path: string, options?: NavigateOptions) => void
}

const NavigationContext = createContext<NavigationContextValue | null>(null)

export function NavigationProvider({ children }: PropsWithChildren) {
  const [path, setPath] = useState(window.location.pathname)

  useEffect(() => {
    const update = () => setPath(window.location.pathname)
    window.addEventListener('popstate', update)
    return () => window.removeEventListener('popstate', update)
  }, [])

  const navigate = useCallback((nextPath: string, options?: NavigateOptions) => {
    if (options?.replace) window.history.replaceState(null, '', nextPath)
    else window.history.pushState(null, '', nextPath)
    setPath(nextPath)
  }, [])

  const value = useMemo(() => ({ path, navigate }), [navigate, path])
  return <NavigationContext.Provider value={value}>{children}</NavigationContext.Provider>
}

export function useNavigation() {
  const value = useContext(NavigationContext)
  if (!value) throw new Error('NavigationProvider is missing')
  return value
}

