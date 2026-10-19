import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColDef } from 'ag-grid-community'
import { AgGridReact } from 'ag-grid-react'
import { useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams } from 'react-router'
import { api, ApiError, mediaUrl, type ClaimItem, type ClaimPacket } from '../api'
import { PayButtons } from '../components/PayButtons'
import { PublicFrame } from '../components/PublicFrame'
import { money, parseTime } from '../format'
import { gridTheme } from '../grid'
import { usePayPalCheckout, type Method } from '../usePayPalCheckout'

type Row = Omit<ClaimItem, 'value'> & { value: number }

const EVIDENCE_TONE: Record<ClaimItem['evidence'], string> = {
  pre_disaster_scan: 'bg-sage-soft text-sage',
  receipt: 'bg-sage-soft text-sage',
  photo: 'bg-amber-soft text-amber',
  memory: 'bg-sunken text-ink-soft',
}

function Figure({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4 shadow-sm">
      <dt className="text-sm text-ink-soft">{label}</dt>
      <dd className={`text-2xl font-semibold tabular-nums ${strong ? 'text-ember' : ''}`}>{value}</dd>
    </div>
  )
}

/** The adjuster pays the claim: decides the amount, then pays with the insurer's PayPal account. */
function PayClaim({ token, packet, onPaid }: { token: string; packet: ClaimPacket; onPaid: (p: ClaimPacket) => void }) {
  const { t } = useTranslation()
  const [adjuster, setAdjuster] = useState('')
  const [amount, setAmount] = useState(packet.estimate)
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  const checkout = usePayPalCheckout(async () => {
    onPaid(await api<ClaimPacket>(`/claims/${token}/capture`, { method: 'POST' }))
  })
  const valid = adjuster.trim().length >= 2 && Number(amount) > 0 && Number(amount) <= Number(packet.inventory_value)

  function pay(method: Method) {
    setError(null)
    const order = api<{ order_id: string }>(`/claims/${token}/order`, {
      method: 'POST',
      body: JSON.stringify({ amount, adjuster_name: adjuster, note }),
    })
      .then((r) => ({ orderId: r.order_id }))
      .catch((e: unknown) => {
        setError(e instanceof ApiError ? e.message : t('errors.generic'))
        throw e
      })
    checkout.start(method, order)
  }

  return (
    <section className="rounded-xl border border-line bg-surface p-5 shadow-sm">
      <h2 className="text-lg font-semibold">{t('claimView.payTitle')}</h2>
      <p className="mt-1 text-sm text-ink-soft">{t('claimView.payBody')}</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <label className="text-sm">
          <span className="text-ink-soft">{t('claimView.adjuster')}</span>
          <input
            value={adjuster}
            onChange={(e) => setAdjuster(e.target.value)}
            maxLength={120}
            className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2"
          />
        </label>
        <label className="text-sm">
          <span className="text-ink-soft">{t('claimView.amount')}</span>
          <input
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            type="number"
            min={1}
            step="0.01"
            max={packet.inventory_value}
            className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2 tabular-nums"
          />
        </label>
        <label className="text-sm sm:col-span-2">
          <span className="text-ink-soft">{t('claimView.note')}</span>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={500}
            className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2"
          />
        </label>
      </div>
      <PayButtons checkout={checkout} disabled={!valid} onPay={pay} />
      {error && <p className="mt-2 text-sm text-danger">{error}</p>}
      <p className="mt-3 text-xs text-ink-faint">{t('claimView.where')}</p>
    </section>
  )
}

export default function ClaimView() {
  const { t, i18n } = useTranslation()
  const { token = '' } = useParams()
  const queryClient = useQueryClient()
  const grid = useRef<AgGridReact<Row>>(null)
  const claim = useQuery({ queryKey: ['claim-packet', token], queryFn: () => api<ClaimPacket>(`/claims/${token}`) })
  const p = claim.data
  const date = (iso: string | null) =>
    iso ? parseTime(iso).toLocaleDateString(i18n.resolvedLanguage, { dateStyle: 'medium' }) : '—'
  const rows = useMemo<Row[]>(() => (p?.items ?? []).map((i) => ({ ...i, value: Number(i.value) })), [p])
  const columnDefs = useMemo<ColDef<Row>[]>(
    () => [
      { field: 'room', headerName: t('claimView.col.room'), filter: 'agSetColumnFilter', width: 150 },
      { field: 'name', headerName: t('claimView.col.item'), flex: 1, minWidth: 220, tooltipField: 'name' },
      { field: 'quantity', headerName: t('claimView.col.qty'), width: 80, type: 'rightAligned' },
      {
        field: 'value',
        headerName: t('claimView.col.value'),
        width: 130,
        type: 'rightAligned',
        aggFunc: 'sum',
        valueFormatter: (v) => (v.value == null ? '' : money(v.value, { cents: true })),
      },
      {
        field: 'evidence',
        headerName: t('claimView.col.evidence'),
        filter: 'agSetColumnFilter',
        width: 290,
        cellRenderer: (v: { value: ClaimItem['evidence']; data: Row }) =>
          v.data ? (
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${EVIDENCE_TONE[v.value]}`}>
              {t(`claimView.evidence.${v.value}`, { date: date(v.data.recorded_at) })}
            </span>
          ) : null,
      },
      {
        field: 'sub_limit',
        headerName: t('claimView.col.subLimit'),
        width: 200,
        valueFormatter: (v) => v.value ?? '',
        tooltipField: 'sub_limit',
      },
      {
        field: 'photo_url',
        headerName: t('claimView.col.photo'),
        width: 100,
        cellRenderer: (v: { value: string | null }) =>
          v.value ? (
            <a href={mediaUrl(v.value) ?? '#'} target="_blank" rel="noreferrer" className="text-ember hover:underline">
              {t('claimView.view')}
            </a>
          ) : null,
      },
    ],
    // `date` follows the language
    [t, i18n.resolvedLanguage],
  )
  const cut = p ? p.sub_limits.reduce((sum, s) => sum + Number(s.over_by), 0) : 0

  return (
    <PublicFrame wide>
      {claim.isPending && <div className="h-64 animate-pulse rounded-xl bg-sunken" />}
      {claim.isError && (
        <p className="rounded-lg bg-danger-soft px-4 py-3 text-danger">
          {claim.error instanceof ApiError ? claim.error.message : t('errors.generic')}
        </p>
      )}
      {p && (
        <div className="space-y-6">
          <header>
            <p className="text-sm font-medium uppercase tracking-wide text-ember">
              {t('claimView.eyebrow', { insurer: p.insurer })}
            </p>
            <h1 className="mt-1 text-3xl font-semibold tracking-tight">{p.policyholder}</h1>
            <p className="mt-1 text-ink-soft">
              {p.address}
              {p.policy_number && ` · ${t('claimView.policy', { number: p.policy_number })}`}
            </p>
            <p className="text-sm text-ink-faint">
              {t('claimView.loss', { date: date(p.loss_date), disaster: p.disaster ?? '—' })}
            </p>
          </header>

          {p.status === 'paid' && (
            <p role="status" className="rounded-xl border border-sage/40 bg-sage-soft px-5 py-4 text-sage">
              <span className="text-lg font-semibold">
                {t('claimView.paid', { amount: money(p.approved_amount, { cents: true }), date: date(p.paid_at) })}
              </span>{' '}
              {p.payout_status === 'sent' ? t('claimView.passedOn') : t('claimView.heldNote')}
            </p>
          )}

          <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Figure label={t('claimView.inventory', { count: p.items.length })} value={money(p.inventory_value)} />
            <Figure label={t('claimView.subLimitsCut')} value={cut ? `−${money(cut)}` : money(0)} />
            <Figure
              label={t('claimView.limitAndDeductible')}
              value={`${p.contents_limit ? money(p.contents_limit) : '—'} · −${money(p.deductible ?? 0)}`}
            />
            <Figure label={t('claimView.estimate')} value={money(p.estimate, { cents: true })} strong />
          </dl>

          <div className="flex flex-wrap items-end justify-between gap-2">
            <p className="max-w-3xl text-sm text-ink-soft">{t('claimView.itemsNote')}</p>
            <button
              onClick={() =>
                grid.current?.api.exportDataAsExcel({ fileName: `claim-${p.policy_number ?? 'contents'}.xlsx` })
              }
              className="rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-sunken"
            >
              {t('claimView.export')}
            </button>
          </div>
          <div className="h-[55vh] min-h-80">
            <AgGridReact<Row>
              ref={grid}
              theme={gridTheme}
              rowData={rows}
              columnDefs={columnDefs}
              defaultColDef={{ sortable: true, resizable: true }}
              grandTotalRow="bottom"
              suppressAggFuncInHeader
            />
          </div>

          {p.sub_limits.length > 0 && (
            <ul className="space-y-1 text-sm">
              {p.sub_limits.map((s) => (
                <li key={s.what} className="rounded-lg bg-sunken px-3 py-2">
                  {t('claimView.subLimitLine', {
                    what: s.what,
                    value: money(s.items_value),
                    limit: money(s.limit),
                    over: money(s.over_by),
                  })}
                </li>
              ))}
            </ul>
          )}

          {p.status === 'submitted' && (
            <PayClaim
              token={token}
              packet={p}
              onPaid={(paid) => void queryClient.setQueryData(['claim-packet', token], paid)}
            />
          )}
        </div>
      )}
    </PublicFrame>
  )
}
