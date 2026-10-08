import type { Role } from './api'

export const STAFF_ROLES: Role[] = ['reviewer', 'supervisor', 'org_admin']

const HOME: Partial<Record<Role, string>> = { household: '/home', contractor: '/contractor', org_admin: '/command' }

export const homePathFor = (role: Role) => HOME[role] ?? (STAFF_ROLES.includes(role) ? '/review' : '/workspace')
