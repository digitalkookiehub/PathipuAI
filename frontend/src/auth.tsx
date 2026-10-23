import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api, UNAUTHORIZED_EVENT } from './api'
import type { AuthStatus } from './api'
import { AuthContext } from './authState'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus | null>(null)

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.authStatus())
    } catch {
      // The server is unreachable: show the sign-in page rather than a blank screen.
      setStatus({ auth_required: true, authenticated: false, username: null, setup_required: false })
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  // Any request answered with "please sign in" (for example after the session expired) returns to the sign-in page.
  useEffect(() => {
    const onUnauthorized = () =>
      setStatus((current) => (current === null ? current : { ...current, authenticated: false, username: null }))
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  }, [])

  const signOut = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      await refresh()
    }
  }, [refresh])

  const value = useMemo(() => ({ status, refresh, signOut }), [status, refresh, signOut])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
