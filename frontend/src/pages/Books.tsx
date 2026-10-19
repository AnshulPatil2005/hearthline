import { useQuery } from '@tanstack/react-query'
import type { ColDef, ValueFormatterParams } from 'ag-grid-community'
import { AgGridReact } from 'ag-grid-react'
import { useMemo, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type BooksLine, type BooksReport, type PayPalBalance } from '../api'
import { money, parseTime } from '../format'
import { gridTheme } from '../grid'

type Row = Omit<BooksLine, 'amount'> & { amount: number; id: number }

const TONE: Record<BooksLine['status'], string> = {
  matched: 'bg-sage-soft text-sage',
  amount_differs: 'bg-danger-soft text-danger',
  not_in_books: 'bg-danger-soft text-danger',
  missing_at_paypal: 'bg-danger-soft text-danger',
  waiting: 'bg-amber-soft text-amber',
  info: 'bg-sunken text-ink-soft',
}
const NEEDS_A_LOOK: BooksLine['status'][] = ['amount_differs', 'not_in_books', 'missing_at_paypal']

/**
 * The relief fund's books against PayPal's own records (Transaction Search, through APIMatic's PayPal SDK): every
 * payout traced to a decision people approved, every payment received found in the ledger.
 */
export default function Books() {
  const { t, i18n } = useTranslation()
  const grid = useRef<AgGridReact<Row>>(null)
  const balance = useQuery({
    queryKey: ['paypal-balance'],
    queryFn: () => api<PayPalBalance>('/command/books/balance'),
  })
  const report = useQuery({ queryKey: ['books'], queryFn: () => api<BooksReport>('/command/books/reconcile') })
  const when = (iso: string | null, withTime = true) =>
    iso
      ? parseTime(iso).toLocaleString(i18n.resolvedLanguage, {
          dateStyle: 'medium',
          ...(withTime ? { timeStyle: 'short' } : {}),
        })
      : '—'
  const rows = useMemo<Row[]>(
    () => (report.data?.lines ?? []).map((l, i) => ({ ...l, amount: Number(l.amount), id: i })),
    [report.data],
  )
  const columnDefs = useMemo<ColDef<Row>[]>(
    () => [
      {
        field: 'at',
        headerName: t('books.col.when'),
        valueFormatter: (p) => when(p.value),
        sort: 'desc',
        width: 190,
      },
      {
        field: 'status',
        headerName: t('books.col.status'),
        filter: 'agSetColumnFilter',
        filterParams: { valueFormatter: (p: ValueFormatterParams) => t(`books.status.${p.value}`) },
        cellRenderer: (p: { value: BooksLine['status'] }) => (
          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${TONE[p.value]}`}>
            {t(`books.status.${p.value}`)}
          </span>
        ),
        width: 190,
      },
      {
        field: 'direction',
        headerName: t('books.col.direction'),
        filter: 'agSetColumnFilter',
        valueFormatter: (p) => t(`books.direction.${p.value}`),
        width: 130,
      },
      {
        field: 'amount',
        headerName: t('books.col.amount'),
        type: 'rightAligned',
        valueFormatter: (p) => (p.value == null ? '' : `${p.value > 0 ? '+' : ''}${money(p.value, { cents: true })}`),
        cellClassRules: { 'text-sage': (p) => p.value > 0, 'text-danger': (p) => p.value < 0 },
        width: 130,
      },
      {
        field: 'hearthline',
        headerName: t('books.col.hearthline'),
        flex: 1,
        minWidth: 240,
        tooltipField: 'hearthline',
      },
      { field: 'note', headerName: t('books.col.note'), flex: 1, minWidth: 220, tooltipField: 'note' },
      { field: 'paypal_id', headerName: t('books.col.paypalId'), width: 190, cellClass: 'font-mono text-xs' },
    ],
    // `when` only depends on the language
    [t, i18n.resolvedLanguage],
  )
  const r = report.data
  const needsLook = r ? NEEDS_A_LOOK.reduce((n, s) => n + r.counts[s], 0) : 0
  const failed = report.error ?? balance.error

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">{t('books.title')}</h1>
          <p className="mt-1 max-w-3xl text-ink-soft">{t('books.subtitle')}</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => {
              void balance.refetch()
              void report.refetch()
            }}
            disabled={report.isFetching}
            className="rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-sunken disabled:opacity-40"
          >
            {report.isFetching ? t('books.checking') : t('books.check')}
          </button>
          <button
            onClick={() => grid.current?.api.exportDataAsExcel({ fileName: 'hearthline-books-vs-paypal.xlsx' })}
            disabled={!rows.length}
            className="rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-sunken disabled:opacity-40"
          >
            {t('books.export')}
          </button>
        </div>
      </div>

      {failed && (
        <p className="rounded-lg bg-danger-soft px-4 py-3 text-danger">
          {failed instanceof ApiError ? failed.message : t('errors.generic')}
        </p>
      )}

      <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-xl border border-line bg-surface p-4 shadow-sm">
          <dt className="text-sm text-ink-soft">{t('books.balance')}</dt>
          <dd className="text-2xl font-semibold tabular-nums">
            {balance.data ? money(balance.data.available, { cents: true }) : '—'}
          </dd>
          <dd className="text-xs text-ink-faint">{t('books.asOf', { when: when(balance.data?.as_of ?? null) })}</dd>
        </div>
        <div className="rounded-xl border border-line bg-surface p-4 shadow-sm">
          <dt className="text-sm text-ink-soft">{t('books.matched')}</dt>
          <dd className="text-2xl font-semibold tabular-nums text-sage">{r ? r.counts.matched : '—'}</dd>
          <dd className="text-xs text-ink-faint">
            {r ? t('books.flows', { in: money(r.paypal_in), out: money(r.paypal_out) }) : ''}
          </dd>
        </div>
        <div className="rounded-xl border border-line bg-surface p-4 shadow-sm">
          <dt className="text-sm text-ink-soft">{t('books.needsLook')}</dt>
          <dd className={`text-2xl font-semibold tabular-nums ${needsLook ? 'text-danger' : ''}`}>
            {r ? needsLook : '—'}
          </dd>
          <dd className="text-xs text-ink-faint">{r ? t('books.waiting', { count: r.counts.waiting }) : ''}</dd>
        </div>
        <div className="rounded-xl border border-line bg-surface p-4 shadow-sm">
          <dt className="text-sm text-ink-soft">{t('books.window')}</dt>
          <dd className="text-lg font-semibold">{r ? when(r.start, false) : '—'}</dd>
          <dd className="text-xs text-ink-faint">
            {t('books.refreshed', { when: when(r?.paypal_refreshed_at ?? null) })}
          </dd>
        </div>
      </dl>

      <div className="h-[55vh] min-h-96">
        <AgGridReact<Row>
          ref={grid}
          theme={gridTheme}
          rowData={rows}
          columnDefs={columnDefs}
          getRowId={(p) => String(p.data.id)}
          defaultColDef={{ sortable: true, resizable: true }}
          loading={report.isPending}
          overlayNoRowsTemplate={t('books.empty')}
        />
      </div>
      <p className="text-xs text-ink-faint">{t('books.hint')}</p>
    </div>
  )
}
