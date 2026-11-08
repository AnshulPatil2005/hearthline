import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, ApiError, sessionEnded, tokenStore, type User } from './api'

type AuthState = {
  user: User | null
  loading: boolean
  signInAsPersona: (userId: number) => Promise<User>
  signOut: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(() => tokenStore.get() !== null)

  useEffect(() => {
    if (!tokenStore.get()) return
    api<User>('/me')
      .then(setUser)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) tokenStore.set(null)
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(
    () =>
      sessionEnded.listen(() => {
        queryClient.clear()
        setUser(null)
      }),
    [queryClient],
  )

  const signInAsPersona = useCallback(
    async (userId: number) => {
      const res = await api<{ token: string; user: User }>('/auth/demo-login', {
        method: 'POST',
        body: JSON.stringify({ user_id: userId }),
      })
      tokenStore.set(res.token)
      queryClient.clear()
      setUser(res.user)
      return res.user
    },
    [queryClient],
  )

  const signOut = useCallback(() => {
    tokenStore.set(null)
    queryClient.clear()
    setUser(null)
  }, [queryClient])

  return <AuthContext.Provider value={{ user, loading, signInAsPersona, signOut }}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
