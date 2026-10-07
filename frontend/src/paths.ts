import type { Role } from './api'

export const STAFF_ROLES: Role[] = ['reviewer', 'supervisor', 'org_admin']

export const homePathFor = (role: Role) =>
  role === 'household' ? '/home' : STAFF_ROLES.includes(role) ? '/review' : '/workspace'
