import type { ReactNode } from 'react'
import { Navigate } from 'react-router'
import type { Role } from './api'
import { useAuth } from './auth'
import { Shell } from './components/Shell'
import { homePathFor } from './paths'

export function RequireAuth({ children, role, wide }: { children: ReactNode; role?: Role; wide?: boolean }) {
  const { user, loading } = useAuth()
  if (loading) return <div className="grid min-h-svh place-items-center text-ink-faint">…</div>
  if (!user) return <Navigate to="/login" replace />
  if (role && user.role !== role) return <Navigate to={homePathFor(user.role)} replace />
  return <Shell wide={wide}>{children}</Shell>
}

export function HomeRedirect() {
  const { user, loading } = useAuth()
  if (loading) return null
  return <Navigate to={user ? homePathFor(user.role) : '/login'} replace />
}
