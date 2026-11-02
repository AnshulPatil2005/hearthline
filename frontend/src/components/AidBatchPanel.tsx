import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type AidBatch, type BatchPreview, type FundsCheck } from '../api'
import { money, parseTime } from '../format'

const LEVELS = ['destroyed', 'major', 'minor', 'affected'] as const
const DEFAULTS: Record<(typeof LEVELS)[number], string> = {
  destroyed: '1000',
  major: '750',
  minor: '400',
  affected: '200',
}

// Filter keys are field names; most match the column label keys.
const COL: Record<string, string> = {
  name: 'household',
  address_line: 'address',
  damage_level: 'damage',
  verification_level: 'level',
  household_size: 'size',
  estimated_loss: 'loss',
  help_received: 'help',
  unmet_need: 'unmet',
  payout_ready: 'paypal',
}

type Props = {
  /** The households grid's current filter: the batch covers exactly the households in view. */
  filterModel: () => Record<string, unknown>
  onCreated: () => void
}

/** Whether PayPal's latest balance covers the batch (payouts fail when it doesn't). The balance can lag 3 hours. */
function FundsLine({ check, total }: { check: FundsCheck; total: string }) {
  const { t, i18n } = useTranslation()
  if (check.error || check.available === null) {
    return <p className="mt-2 text-ink-faint">{t('command.batch.balanceUnknown')}</p>
  }
  const asOf = check.as_of
    ? parseTime(check.as_of).toLocaleTimeString(i18n.resolvedLanguage, { hour: 'numeric', minute: '2-digit' })
    : '—'
  return check.covers ? (
    <p className="mt-2 text-sage">
      {t('command.batch.balanceCovers', { balance: money(check.available), time: asOf })}
    </p>
  ) : (
    <p className="mt-2 font-medium text-danger">
      {t('command.batch.balanceShort', { balance: money(check.available), time: asOf, total: money(total) })}
    </p>
  )
}

export function AidBatchPanel({ filterModel, onCreated }: Props) {
  const { t, i18n } = useTranslation()
  const [amounts, setAmounts] = useState(DEFAULTS)
  const [title, setTitle] = useState(() =>
    t('command.batch.defaultTitle', {
      date: new Date().toLocaleDateString(i18n.resolvedLanguage, { month: 'short', day: 'numeric' }),
    }),
  )
  const [preview, setPreview] = useState<BatchPreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const body = () => ({ filter_model: filterModel(), amounts })
  const onError = (e: Error) => setError(e instanceof ApiError ? e.message : t('errors.generic'))

  const check = useMutation({
    mutationFn: () => api<BatchPreview>('/command/batches/preview', { method: 'POST', body: JSON.stringify(body()) }),
    onSuccess: (p) => {
      setPreview(p)
      setError(null)
    },
    onError,
  })
  const create = useMutation({
    mutationFn: () => api<AidBatch>('/command/batches', { method: 'POST', body: JSON.stringify({ ...body(), title }) }),
    onSuccess: () => {
      setPreview(null)
      setError(null)
      onCreated()
    },
    onError,
  })

  const filters = Object.keys(filterModel())
  return (
    <section className="panel p-5">
      <h2 className="font-semibold">{t('command.batch.title')}</h2>
      <p className="mt-1 text-sm text-ink-soft">{t('command.batch.intro')}</p>
      <p className="mt-2 text-xs text-ink-faint">
        {filters.length
          ? t('command.batch.scopeFiltered', {
              columns: filters.map((f) => t(`command.col.${COL[f] ?? f}`)).join(', '),
            })
          : t('command.batch.scopeAll')}
      </p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_repeat(4,8rem)]">
        <label className="text-sm">
          <span className="text-ink-soft">{t('command.batch.name')}</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2"
          />
        </label>
        {LEVELS.map((level) => (
          <label key={level} className="text-sm">
            <span className="text-ink-soft">{t(`command.damage.${level}`)}</span>
            <span className="mt-1 flex items-center gap-1 rounded-lg border border-line bg-surface px-3 py-2">
              $
              <input
                type="number"
                min={0}
                max={5000}
                value={amounts[level]}
                onChange={(e) => {
                  setAmounts((a) => ({ ...a, [level]: e.target.value }))
                  setPreview(null)
                }}
                className="w-full bg-transparent outline-none"
              />
            </span>
          </label>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          onClick={() => check.mutate()}
          disabled={check.isPending}
          className="rounded-lg border border-line px-3 py-1.5 text-sm font-medium hover:bg-sunken disabled:opacity-40"
        >
          {t('command.batch.preview')}
        </button>
        {preview && preview.households > 0 && !preview.too_many && (
          <button
            onClick={() => create.mutate()}
            disabled={create.isPending || title.trim().length < 3}
            className="rounded-lg bg-ember px-3 py-1.5 text-sm font-medium text-on-ember disabled:opacity-40"
          >
            {t('command.batch.create', { count: preview.households, total: money(preview.total) })}
          </button>
        )}
      </div>
      {preview && (
        <div className="mt-4 grid gap-4 rounded-lg bg-sunken p-4 text-sm md:grid-cols-2">
          <div>
            <p className="font-medium">
              {t('command.batch.willPay', {
                count: preview.households,
                n: preview.households.toLocaleString(i18n.resolvedLanguage),
                total: money(preview.total),
              })}
            </p>
            <ul className="mt-2 space-y-0.5 text-ink-soft">
              {Object.entries(preview.by_damage).map(([level, d]) => (
                <li key={level}>
                  {t(`command.damage.${level}`)}: {d.households.toLocaleString(i18n.resolvedLanguage)} ·{' '}
                  {money(d.amount)}
                </li>
              ))}
            </ul>
            {preview.too_many && <p className="mt-2 text-danger">{t('command.batch.tooMany')}</p>}
            {preview.paypal_balance && <FundsLine check={preview.paypal_balance} total={preview.total} />}
          </div>
          <div>
            <p className="font-medium">{t('command.batch.leftOut')}</p>
            {Object.keys(preview.excluded).length === 0 ? (
              <p className="mt-2 text-ink-soft">{t('command.batch.noneLeftOut')}</p>
            ) : (
              <ul className="mt-2 space-y-0.5 text-ink-soft">
                {Object.entries(preview.excluded).map(([reason, n]) => (
                  <li key={reason}>
                    {t(`command.batch.reason.${reason}`)}: {n.toLocaleString(i18n.resolvedLanguage)}
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-2 text-xs text-ink-faint">{t('command.batch.secondPerson')}</p>
          </div>
        </div>
      )}
      {error && <p className="mt-2 text-sm text-danger">{error}</p>}
    </section>
  )
}
