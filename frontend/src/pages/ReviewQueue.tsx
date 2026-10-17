import { useQuery } from '@tanstack/react-query'
import type { ColDef, ICellRendererParams } from 'ag-grid-community'
import { AgGridReact } from 'ag-grid-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { api, type QueueRow } from '../api'
import { useAuth } from '../auth'
import RiskBadge from '../components/RiskBadge'
import { money } from '../format'
import { gridTheme } from '../grid'

export default function ReviewQueue() {
  const { t, i18n } = useTranslation()
  const { user } = useAuth()
  const navigate = useNavigate()
  const [mineOnly, setMineOnly] = useState(true)
  const queue = useQuery({ queryKey: ['review-queue'], queryFn: () => api<QueueRow[]>('/review/queue') })
  const rows = useMemo(() => (queue.data ?? []).filter((r) => !mineOnly || r.awaiting_me), [queue.data, mineOnly])
  const waiting = queue.data?.filter((r) => r.awaiting_me).length ?? 0

  const columnDefs = useMemo<ColDef<QueueRow>[]>(
    () => [
      { field: 'id', headerName: '#', width: 70 },
      {
        field: 'risk_tier',
        headerName: t('review.col.risk'),
        width: 150,
        sort: 'desc',
        comparator: (_a, _b, na, nb) => (na.data?.risk_score ?? 0) - (nb.data?.risk_score ?? 0),
        cellRenderer: (p: ICellRendererParams<QueueRow>) =>
          p.data ? <RiskBadge tier={p.data.risk_tier} score={p.data.risk_score} /> : null,
        filter: 'agSetColumnFilter',
      },
      { field: 'household_name', headerName: t('review.col.household'), flex: 1, minWidth: 180 },
      {
        field: 'kind',
        headerName: t('review.col.kind'),
        width: 170,
        valueFormatter: (p) => (p.value ? t(`review.kind.${p.value}`) : ''),
        filter: 'agSetColumnFilter',
      },
      {
        field: 'amount_requested',
        headerName: t('review.col.amount'),
        width: 120,
        type: 'rightAligned',
        valueFormatter: (p) => (Number(p.value) ? money(p.value) : '—'),
      },
      { field: 'flag_count', headerName: t('review.col.flags'), width: 90 },
      {
        colId: 'reviews',
        headerName: t('review.col.reviews'),
        width: 110,
        valueGetter: (p) => (p.data ? `${p.data.reviews_done} / ${p.data.required_reviews}` : ''),
      },
      {
        field: 'video_call_required',
        headerName: t('review.col.video'),
        width: 100,
        valueFormatter: (p) => (p.value ? t('review.yes') : ''),
      },
      {
        field: 'status',
        headerName: t('review.col.status'),
        width: 140,
        valueFormatter: (p) => (p.value ? t(`review.status.${p.value}`) : ''),
        filter: 'agSetColumnFilter',
      },
      {
        field: 'created_at',
        headerName: t('review.col.waiting'),
        width: 140,
        valueFormatter: (p) =>
          p.value
            ? new Date(p.value).toLocaleDateString(i18n.resolvedLanguage, { month: 'short', day: 'numeric' })
            : '',
      },
    ],
    [t, i18n.resolvedLanguage],
  )

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">{t('review.queueTitle')}</h1>
          <p className="mt-1 text-ink-soft">{t('review.queueSubtitle', { name: user?.name.split(' ')[0] })}</p>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={mineOnly}
            onChange={(e) => setMineOnly(e.target.checked)}
            className="size-4 accent-[var(--ember)]"
          />
          {t('review.mineOnly', { count: waiting })}
        </label>
      </div>
      <div className={rows.length > 15 ? 'h-[65vh]' : ''}>
        <AgGridReact<QueueRow>
          theme={gridTheme}
          rowData={rows}
          columnDefs={columnDefs}
          getRowId={(p) => String(p.data.id)}
          domLayout={rows.length > 15 ? 'normal' : 'autoHeight'}
          defaultColDef={{ sortable: true, resizable: true, suppressHeaderMenuButton: true }}
          onRowClicked={(e) => e.data && navigate(`/review/cases/${e.data.id}`)}
          rowClass="cursor-pointer"
          overlayNoRowsTemplate={t('review.empty')}
          loading={queue.isPending}
        />
      </div>
      <p className="text-xs text-ink-faint">{t('review.queueHint')}</p>
    </div>
  )
}
