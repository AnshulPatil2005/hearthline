import type { Role } from './api'

export const homePathFor = (role: Role) => (role === 'household' ? '/home' : '/workspace')
