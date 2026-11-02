import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError, downloadFile, type DisputeAction, type DisputeDetail, type DisputeRow } from '../api'
import { AskPayPal } from '../components/AskPayPal'
import { money, parseTime } from '../format'

// The PayPal action behind each answer: PayPal's links on the dispute say which ones are possible right now.
const PAYPAL_ACTION: Record<DisputeAction, string> = {
  message: 'send_message',
  evidence: 'provide_evidence',
  refund: 'accept_claim',
}
const ORDER: DisputeAction[] = ['message', 'evidence', 'refund']
// Dates as the server writes them in its records (the disaster area's time zone).
const SITE_TIME_ZONE = 'America/Los_Angeles'

function daysLeft(iso: string | null): number | null {
  if (!iso) return null
  return Math.ceil((parseTime(iso).getTime() - Date.now()) / 86_400_000)
}

function StatusPill({ row }: { row: DisputeRow }) {
  const { t } = useTranslation()
  const done = row.status === 'RESOLVED' || row.decision === 'evidence_sent' || row.decision === 'refunded'
  const tone = done ? 'bg-sunken text-ink-soft' : row.decision ? 'bg-sage-soft text-sage' : 'bg-amber-soft text-amber'
  const label = row.decision ? t(`disputes.decision.${row.decision}`) : t('disputes.needsAnswer')
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}>{label}</span>
}

function Due({ iso }: { iso: string | null }) {
  const { t } = useTranslation()
  const left = daysLeft(iso)
  if (left === null) return null
  return (
    <span className={left <= 5 ? 'text-danger' : 'text-ink-faint'}>
      {left < 0 ? t('disputes.overdue') : t('disputes.dueIn', { count: left })}
    </span>
  )
}

function Detail({ id, onChanged }: { id: number; onChanged: () => void }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const key = ['dispute', id]
  const detail = useQuery({
    queryKey: key,
    queryFn: () => api<DisputeDetail>(`/command/disputes/${id}`),
  })
  const [note, setNote] = useState('')
  const [confirmRefund, setConfirmRefund] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const d = detail.data
  const open = d && d.status !== 'RESOLVED' && d.decision !== 'evidence_sent' && d.decision !== 'refunded'

  const draft = useMutation({
    mutationFn: (again: boolean) =>
      api<DisputeDetail>(`/command/disputes/${id}/draft${again ? '?again=true' : ''}`, { method: 'POST' }),
    onSuccess: (r) => {
      queryClient.setQueryData(key, r)
      setNote(r.draft ?? '')
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('errors.generic')),
  })
  const respond = useMutation({
    mutationFn: (action: DisputeAction) =>
      api<DisputeDetail>(`/command/disputes/${id}/respond`, {
        method: 'POST',
        body: JSON.stringify({ action, note }),
      }),
    onSuccess: (r) => {
      queryClient.setQueryData(key, r)
      setConfirmRefund(false)
      setError(null)
      onChanged()
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('errors.generic')),
  })

  // Open a dispute: show its draft, or ask the Funds agent for one.
  const { mutate: makeDraft } = draft
  useEffect(() => {
    setConfirmRefund(false)
    setError(null)
    if (!d) return
    setNote(d.draft ?? '')
    if (!d.draft && d.status !== 'RESOLVED' && !d.decision) makeDraft(false)
    // once per dispute opened, not on every refetch
  }, [d?.id])

  if (!d) return <div className="h-64 animate-pulse rounded-xl bg-sunken" />
  const allowed = ORDER.filter((a) => d.demo || d.actions.includes(PAYPAL_ACTION[a]))
  const when = (iso: string) =>
    parseTime(iso).toLocaleDateString(i18n.resolvedLanguage, {
      dateStyle: 'medium',
      timeZone: SITE_TIME_ZONE,
    })

  return (
    <article className="space-y-5 panel p-5">
      <header className="space-y-1">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="font-mono text-ink-faint">{d.paypal_dispute_id}</span>
          <span className="rounded-full bg-sunken px-2 py-0.5 text-ink-soft">
            {t(`disputes.stage.${d.stage}`, { defaultValue: d.stage })}
          </span>
          <StatusPill row={d} />
          {d.demo && <span className="rounded-full bg-sunken px-2 py-0.5 text-ink-faint">{t('disputes.demo')}</span>}
        </div>
        <h2 className="text-xl font-semibold">{d.subject}</h2>
        <p className="text-sm text-ink-soft">
          {money(d.amount, { cents: true })} · {t(`disputes.reason.${d.reason}`, { defaultValue: d.reason_text })}
          {d.respond_by && open && (
            <>
              {' · '}
              <Due iso={d.respond_by} />
            </>
          )}
        </p>
      </header>

      {d.payer_message && (
        <blockquote className="rounded-lg border-l-4 border-amber bg-amber-soft/50 px-4 py-3 text-sm">
          <p className="kicker text-ink-faint">{t('disputes.payerSays')}</p>
          <p className="mt-1">“{d.payer_message}”</p>
        </blockquote>
      )}

      <section className="grid gap-5 md:grid-cols-2">
        <div>
          <h3 className="text-sm font-semibold">{t('disputes.records')}</h3>
          <dl className="mt-2 space-y-1.5 text-sm">
            {d.facts.map((f) => (
              <div key={f.label} className="grid grid-cols-[6.5rem_1fr] gap-2">
                <dt className="text-ink-faint">{f.label}</dt>
                <dd>{f.value}</dd>
              </div>
            ))}
          </dl>
        </div>
        <div>
          <h3 className="text-sm font-semibold">{t('disputes.timeline')}</h3>
          <ol className="mt-2 space-y-1.5 border-l border-line pl-3 text-sm">
            {d.timeline.map((e) => (
              <li key={e.at + e.what}>
                <span className="text-ink-faint">{when(e.at)}</span> · {e.what}
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="rounded-lg bg-sunken px-4 py-3 text-sm">
        <p className="kicker text-ink-faint">{t('disputes.rules')}</p>
        <p className="mt-1">
          <span className="font-semibold">
            {t(`disputes.action.${d.recommended}`, {
              amount: money(d.amount, { cents: true }),
            })}
          </span>
          {' — '}
          {d.because}
        </p>
        {d.recommended === 'evidence' && (
          <p className="mt-1 text-xs text-ink-soft">
            {t('disputes.evidenceType', {
              type: d.evidence_type.replaceAll('_', ' ').toLowerCase(),
            })}
            {d.tracking.map((x) => ` · ${x.carrier_name} ${x.tracking_number}`)}
          </p>
        )}
      </section>

      {open ? (
        <section className="space-y-3">
          {d.decision === 'message_sent' && (
            <p className="text-sm font-semibold text-sage">
              {t('disputes.done.message_sent', {
                name: d.decided_by ?? '—',
                date: d.decided_at ? when(d.decided_at) : '',
              })}
            </p>
          )}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <label htmlFor="dispute-note" className="text-sm font-semibold">
              {t('disputes.response')}
            </label>
            <span className="text-xs text-ink-faint">
              {draft.isPending
                ? t('disputes.drafting')
                : d.draft
                  ? d.draft_by_ai
                    ? t('disputes.byAgent')
                    : t('disputes.byTemplate')
                  : null}
            </span>
          </div>
          <textarea
            id="dispute-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={7}
            maxLength={2000}
            disabled={draft.isPending}
            className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm leading-relaxed disabled:opacity-60"
          />
          <div className="flex flex-wrap items-center gap-2">
            {allowed.map((a) =>
              a === 'refund' && confirmRefund ? (
                <span
                  key={a}
                  className="flex items-center gap-2 rounded-lg bg-danger-soft px-3 py-1.5 text-sm text-danger"
                >
                  {t('disputes.confirmRefund', {
                    amount: money(d.amount, { cents: true }),
                  })}
                  <button
                    onClick={() => respond.mutate('refund')}
                    disabled={respond.isPending}
                    className="rounded-md bg-danger px-2 py-0.5 font-medium text-white"
                  >
                    {t('disputes.confirm')}
                  </button>
                  <button onClick={() => setConfirmRefund(false)} className="underline">
                    {t('disputes.cancel')}
                  </button>
                </span>
              ) : (
                <button
                  key={a}
                  onClick={() => (a === 'refund' ? setConfirmRefund(true) : respond.mutate(a))}
                  disabled={respond.isPending || draft.isPending || note.trim().length < 20}
                  className={
                    a === d.recommended
                      ? 'rounded-lg bg-ember px-3 py-1.5 text-sm font-medium text-on-ember disabled:opacity-40'
                      : 'rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-sunken disabled:opacity-40'
                  }
                >
                  {t(`disputes.action.${a}`, {
                    amount: money(d.amount, { cents: true }),
                  })}
                </button>
              ),
            )}
            <button
              onClick={() => draft.mutate(true)}
              disabled={draft.isPending}
              className="ml-auto text-sm text-ink-soft underline-offset-2 hover:underline disabled:opacity-40"
            >
              {t('disputes.redraft')}
            </button>
            <button
              onClick={() =>
                void downloadFile(`/command/disputes/${id}/evidence.pdf`, `hearthline-${d.paypal_dispute_id}.pdf`)
              }
              className="text-sm text-ink-soft underline-offset-2 hover:underline"
            >
              {t('disputes.pdf')}
            </button>
          </div>
          <p className="text-xs text-ink-faint">{t('disputes.humanNote')}</p>
        </section>
      ) : (
        <section className="space-y-2 text-sm">
          <p className="font-semibold text-sage">
            {d.decision
              ? t(`disputes.done.${d.decision}`, {
                  name: d.decided_by ?? '—',
                  date: d.decided_at ? when(d.decided_at) : '',
                })
              : t('disputes.resolved', { outcome: d.outcome ?? '—' })}
          </p>
          {d.draft && <p className="whitespace-pre-line rounded-lg bg-sunken px-4 py-3 text-ink-soft">{d.draft}</p>}
        </section>
      )}
      {error && <p className="text-sm text-danger">{error}</p>}
    </article>
  )
}

/** Staff answer PayPal disputes about donations and gift cards. Rules recommend, the Funds agent drafts, a person decides. */
export default function Disputes() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const list = useQuery({
    queryKey: ['disputes'],
    queryFn: () => api<DisputeRow[]>('/command/disputes'),
  })
  const [selected, setSelected] = useState<number | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const rows = list.data ?? []
  const current = selected ?? rows.find((r) => !r.decision && r.status !== 'RESOLVED')?.id ?? rows[0]?.id ?? null
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['disputes'] })
  const sync = useMutation({
    mutationFn: () => api<{ seen: number }>('/command/disputes/sync', { method: 'POST' }),
    onSuccess: (r) => {
      setNotice(t('disputes.synced', { count: r.seen }))
      refresh()
    },
    onError: (e) => setNotice(e instanceof ApiError ? e.message : t('errors.generic')),
  })
  const waiting = rows.filter((r) => !r.decision && r.status !== 'RESOLVED')

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-4xl leading-tight tracking-tight text-balance">{t('disputes.title')}</h1>
          <p className="mt-1 max-w-3xl text-ink-soft">{t('disputes.subtitle')}</p>
        </div>
        <div className="flex items-center gap-3">
          {notice && <span className="text-sm text-ink-soft">{notice}</span>}
          <button
            onClick={() => sync.mutate()}
            disabled={sync.isPending}
            className="rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-sunken disabled:opacity-40"
          >
            {sync.isPending ? t('disputes.syncing') : t('disputes.sync')}
          </button>
        </div>
      </div>

      {!list.isSuccess ? (
        <div className="h-64 animate-pulse rounded-xl bg-sunken" />
      ) : rows.length === 0 ? (
        <p className="rounded-xl border border-dashed border-line p-8 text-center text-ink-soft">
          {t('disputes.none')}
        </p>
      ) : (
        <div className="grid items-start gap-6 lg:grid-cols-[22rem_1fr]">
          <div className="space-y-2">
            <p className="text-sm text-ink-soft">
              {t('disputes.waiting', { count: waiting.length })} ·{' '}
              {money(
                waiting.reduce((sum, r) => sum + Number(r.amount), 0),
                { cents: true },
              )}
            </p>
            <ul className="space-y-2">
              {rows.map((r) => (
                <li key={r.id}>
                  <button
                    onClick={() => setSelected(r.id)}
                    aria-current={r.id === current}
                    className={`w-full rounded-xl border p-3 text-left text-sm shadow-sm transition ${
                      r.id === current ? 'border-ember bg-surface' : 'border-line bg-surface hover:bg-sunken'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="font-medium">{r.subject}</span>
                      <span className="tabular-nums font-semibold">{money(r.amount, { cents: true })}</span>
                    </div>
                    <p className="mt-0.5 text-ink-soft">
                      {t(`disputes.reason.${r.reason}`, {
                        defaultValue: r.reason_text,
                      })}
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                      <StatusPill row={r} />
                      {!r.decision && r.status !== 'RESOLVED' && <Due iso={r.respond_by} />}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          {current !== null && <Detail key={current} id={current} onChanged={refresh} />}
        </div>
      )}

      <AskPayPal />
    </div>
  )
}
