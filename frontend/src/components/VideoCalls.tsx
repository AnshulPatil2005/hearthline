import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, ApiError } from '../api'

export type Call = {
  id: number
  case_id: number
  reviewer_name: string
  household_name: string
  starts_at: string
  ends_at: string
  status: 'scheduled' | 'completed' | 'cancelled'
}

function defaultSlot(): string {
  const d = new Date(Date.now() + 24 * 3600 * 1000)
  d.setMinutes(0, 0, 0)
  d.setHours(10)
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}

/** Reviewer side of a case: book the video-verification call and mark it done. */
export default function VideoCalls({ caseId, canBook }: { caseId: number; canBook: boolean }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const [when, setWhen] = useState(defaultSlot)
  const [error, setError] = useState<string | null>(null)
  const calls = useQuery({
    queryKey: ['calls', caseId],
    queryFn: () => api<Call[]>(`/review/cases/${caseId}/appointments`),
  })
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['calls', caseId] })
    void queryClient.invalidateQueries({ queryKey: ['case', String(caseId)] })
  }
  const book = useMutation({
    mutationFn: () =>
      api(`/review/cases/${caseId}/appointments`, {
        method: 'POST',
        body: JSON.stringify({ starts_at: new Date(when).toISOString() }),
      }),
    onSuccess: refresh,
    onError: (e) => setError(e instanceof ApiError ? e.message : t('errors.generic')),
  })
  const complete = useMutation({
    mutationFn: (id: number) => api(`/review/appointments/${id}/complete`, { method: 'POST' }),
    onSuccess: refresh,
  })
  const fmt = (iso: string) =>
    new Date(iso).toLocaleString(i18n.resolvedLanguage, {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    })

  return (
    <div className="space-y-3 text-sm">
      <ul className="space-y-2">
        {calls.data
          ?.filter((c) => c.status !== 'cancelled')
          .map((c) => (
            <li key={c.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-sunken px-3 py-2">
              <span>
                {fmt(c.starts_at)} · {c.reviewer_name}
              </span>
              {c.status === 'completed' ? (
                <span className="font-medium text-sage">{t('calls.completed')}</span>
              ) : (
                canBook && (
                  <button
                    onClick={() => complete.mutate(c.id)}
                    className="rounded-md border border-line bg-surface px-2 py-1 hover:bg-paper"
                  >
                    {t('calls.markDone')}
                  </button>
                )
              )}
            </li>
          ))}
        {calls.data?.length === 0 && <li className="text-ink-faint">{t('calls.none')}</li>}
      </ul>
      {canBook && (
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="datetime-local"
            value={when}
            onChange={(e) => setWhen(e.target.value)}
            className="rounded-lg border border-line bg-surface px-2 py-1.5"
            aria-label={t('calls.when')}
          />
          <button
            onClick={() => book.mutate()}
            disabled={book.isPending}
            className="rounded-lg bg-ember px-3 py-1.5 font-medium text-on-ember disabled:opacity-40"
          >
            {t('calls.book')}
          </button>
          <Link to="/review/calendar" className="text-ember hover:underline">
            {t('calls.openCalendar')}
          </Link>
        </div>
      )}
      {error && <p className="text-danger">{error}</p>}
    </div>
  )
}
