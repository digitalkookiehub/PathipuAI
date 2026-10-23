import { createContext, useContext } from 'react'
import type { AuthStatus } from './api'

export interface AuthContextValue {
  /** null until the first answer from the server arrives */
  status: AuthStatus | null
  refresh: () => Promise<void>
  signOut: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (value === null) throw new Error('useAuth must be used inside AuthProvider')
  return value
}
