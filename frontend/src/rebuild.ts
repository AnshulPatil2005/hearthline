import type { Milestone, Project } from './api'

export const dateRange = (m: Pick<Milestone, 'start_date' | 'end_date'>, locale?: string) => {
  const fmt = (d: string) => new Date(d).toLocaleDateString(locale, { month: 'short', day: 'numeric' })
  return `${fmt(m.start_date)} – ${fmt(m.end_date)}`
}

export const paidOut = (p: Project) =>
  p.milestones.filter((m) => m.status === 'paid').reduce((sum, m) => sum + Number(m.amount), 0)
