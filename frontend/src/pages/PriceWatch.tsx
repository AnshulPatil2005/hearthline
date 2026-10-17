import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColDef, ICellRendererParams } from 'ag-grid-community'
import { AgGridReact } from 'ag-grid-react'
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type PriceWatchReport, type PriceWatchRow } from '../api'
import { useAuth } from '../auth'
import { PublicFrame } from '../components/PublicFrame'
import { money } from '../format'
import { gridTheme } from '../grid'

const STATUS_TONE: Record<PriceWatchRow['status'], string> = {
  gouging: 'bg-danger-soft text-danger',
  ok: 'bg-sage-soft text-sage',
  no_baseline: 'bg-sunken text-ink-soft',
  unknown: 'bg-sunken text-ink-faint',
}

const cssColor = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

/** Public report: essential prices around the disaster compared with what they cost before it. */
export default function PriceWatch() {
  const { t, i18n } = useTranslation()
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const report = useQuery({ queryKey: ['price-watch'], queryFn: () => api<PriceWatchReport>('/price-watch') })
  const refresh = useMutation({
    mutationFn: () => api<{ refreshed: number }>('/command/price-watch/refresh', { method: 'POST' }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['price-watch'] }),
  })
  const limit = report.data?.event.limit_percent ?? 10

  const columns = useMemo<ColDef<PriceWatchRow>[]>(
    () => [
      { field: 'title', headerName: t('priceWatch.col.item'), flex: 1, minWidth: 220, filter: 'agTextColumnFilter' },
      { field: 'seller', headerName: t('priceWatch.col.seller'), width: 190, filter: 'agSetColumnFilter' },
      {
        field: 'category',
        headerName: t('priceWatch.col.category'),
        width: 160,
        filter: 'agSetColumnFilter',
        valueFormatter: (p) => t(`priceWatch.category.${p.value}`, { defaultValue: p.value }),
      },
      {
        field: 'baseline_price',
        headerName: t('priceWatch.col.before'),
        width: 120,
        type: 'rightAligned',
        valueFormatter: (p) => (p.value ? money(p.value, { cents: true }) : '—'),
      },
      {
        field: 'current_price',
        headerName: t('priceWatch.col.now'),
        width: 120,
        type: 'rightAligned',
        valueFormatter: (p) => (p.value ? money(p.value, { cents: true }) : '—'),
      },
      {
        field: 'markup_percent',
        headerName: t('priceWatch.col.change'),
        width: 135,
        type: 'rightAligned',
        sort: 'desc',
        filter: 'agNumberColumnFilter',
        valueFormatter: (p) => {
          if (p.value === null || p.value === undefined) return '—'
          const v = Number(p.value)
          return `${v > 0 ? '+' : ''}${Math.abs(v) >= 10 ? Math.round(v) : v.toFixed(1)}%`
        },
        // Conditional formatting: over the legal limit is red, within it green.
        cellClassRules: {
          'text-danger font-semibold': (p) => p.value !== null && p.value > limit,
          'text-sage': (p) => p.value !== null && p.value <= limit,
        },
      },
      {
        field: 'history',
        headerName: t('priceWatch.col.trend'),
        width: 150,
        sortable: false,
        cellRenderer: 'agSparklineCellRenderer',
        cellRendererParams: {
          sparklineOptions: { type: 'line', stroke: cssColor('--ember'), strokeWidth: 2, padding: { top: 6, bottom: 6 } },
        },
      },
      {
        field: 'status',
        headerName: t('priceWatch.col.status'),
        width: 150,
        filter: 'agSetColumnFilter',
        valueFormatter: (p) => t(`priceWatch.status.${p.value}`),
        cellRenderer: (p: ICellRendererParams<PriceWatchRow>) =>
          p.data ? (
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_TONE[p.data.status]}`}>
              {t(`priceWatch.status.${p.data.status}`)}
            </span>
          ) : null,
      },
      {
        field: 'source',
        headerName: t('priceWatch.col.source'),
        width: 170,
        filter: 'agSetColumnFilter',
        valueFormatter: (p) => t(`priceWatch.source.${p.value}`),
      },
    ],
    [limit, t],
  )

  const e = report.data?.event
  const rows = report.data?.rows ?? []
  const flagged = rows.filter((r) => r.status === 'gouging').length
  const date = (d: string) => new Date(d).toLocaleDateString(i18n.resolvedLanguage, { month: 'long', day: 'numeric', year: 'numeric' })
  return (
    <PublicFrame wide>
      <div className="space-y-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">{t('priceWatch.title')}</h1>
            {e && (
              <p className="mt-1 max-w-3xl text-ink-soft">
                {t('priceWatch.subtitle', { event: e.name, declared: date(e.declared_at), until: date(e.protection_until), limit })}
              </p>
            )}
          </div>
          {user && ['org_admin', 'supervisor'].includes(user.role) && (
            <button
              onClick={() => refresh.mutate()}
              disabled={refresh.isPending}
              className="rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-sunken disabled:opacity-40"
            >
              {refresh.isPending ? t('priceWatch.refreshing') : t('priceWatch.refresh')}
            </button>
          )}
        </div>
        {e && (
          <p className={`rounded-lg px-4 py-3 text-sm ${flagged ? 'bg-danger-soft text-danger' : 'bg-sage-soft text-sage'}`}>
            {t('priceWatch.summary', { count: flagged, total: rows.length, limit })}
            {!e.protection_active && ` ${t('priceWatch.inactive')}`}
          </p>
        )}
        <div className="h-[34rem]">
          <AgGridReact<PriceWatchRow>
            theme={gridTheme}
            rowData={rows}
            columnDefs={columns}
            getRowId={(p) => String(p.data.id)}
            defaultColDef={{ sortable: true, resizable: true, suppressHeaderMenuButton: true }}
            loading={report.isPending}
          />
        </div>
        <p className="text-xs text-ink-faint">{t('priceWatch.note')}</p>
      </div>
    </PublicFrame>
  )
}
