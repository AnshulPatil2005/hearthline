import { useMutation, useQuery } from '@tanstack/react-query'
import type { ColDef, ICellRendererParams } from 'ag-grid-community'
import { AgGridReact } from 'ag-grid-react'
import { useCallback, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type AidBatch, type AidBatchItem } from '../api'
import { money } from '../format'
import { gridTheme } from '../grid'

const STATUS_TONE: Record<AidBatch['status'], string> = {
  awaiting_approval: 'bg-amber-soft text-amber',
  sent: 'bg-sage-soft text-sage',
  rejected: 'bg-sunken text-ink-soft',
  failed: 'bg-danger-soft text-danger',
}

type Props = { onPaid: () => void }

/** Batches of cash aid. A different person from the one who prepared a batch approves or rejects it. */
export function AidBatches({ onPaid }: Props) {
  const { t } = useTranslation()
  const batches = useQuery({ queryKey: ['aid-batches'], queryFn: () => api<AidBatch[]>('/command/batches') })
  const [rejecting, setRejecting] = useState<AidBatch | null>(null)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)

  const act = useMutation({
    mutationFn: ({ batch, action }: { batch: AidBatch; action: 'approve' | 'reject' | 'refresh' }) =>
      api<AidBatch>(`/command/batches/${batch.id}/${action}`, {
        method: 'POST',
        body: action === 'reject' ? JSON.stringify({ reason }) : undefined,
      }),
    onSuccess: (b) => {
      setError(b.error)
      setRejecting(null)
      setReason('')
      void batches.refetch()
      if (b.status === 'sent') onPaid()
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('errors.generic')),
  })

  const statusLabel = useCallback(
    (s: string) => t(`command.batch.itemStatus.${s}`, { defaultValue: s.toLowerCase() }),
    [t],
  )
  const columnDefs = useMemo<ColDef<AidBatch>[]>(
    () => [
      { field: 'id', headerName: '#', width: 100, cellRenderer: 'agGroupCellRenderer' },
      { field: 'title', headerName: t('command.batch.col.title'), flex: 1, minWidth: 180 },
      {
        field: 'status',
        headerName: t('command.batch.col.status'),
        width: 170,
        cellRenderer: (p: ICellRendererParams<AidBatch>) =>
          p.data ? (
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_TONE[p.data.status]}`}>
              {t(`command.batch.status.${p.data.status}`)}
            </span>
          ) : null,
      },
      { field: 'households', headerName: t('command.batch.col.households'), width: 120, type: 'rightAligned' },
      {
        field: 'total_amount',
        headerName: t('command.batch.col.total'),
        width: 130,
        type: 'rightAligned',
        valueFormatter: (p) => money(p.value),
      },
      {
        colId: 'people',
        headerName: t('command.batch.col.people'),
        width: 220,
        valueGetter: (p) =>
          p.data
            ? p.data.decided_by
              ? t('command.batch.preparedApproved', { a: p.data.created_by, b: p.data.decided_by })
              : t('command.batch.prepared', { a: p.data.created_by })
            : '',
      },
      {
        colId: 'progress',
        headerName: t('command.batch.col.paypal'),
        width: 180,
        valueGetter: (p) =>
          p.data
            ? Object.entries(p.data.status_counts)
                .map(([s, n]) => `${statusLabel(s)} ${n}`)
                .join(' · ')
            : '',
      },
      {
        colId: 'actions',
        headerName: '',
        width: 230,
        pinned: 'right',
        sortable: false,
        cellRenderer: (p: ICellRendererParams<AidBatch>) => {
          const b = p.data
          if (!b) return null
          const busy = act.isPending
          return (
            <div className="flex h-full items-center gap-2">
              {b.can_decide && (
                <>
                  <button
                    onClick={() => act.mutate({ batch: b, action: 'approve' })}
                    disabled={busy}
                    className="rounded-md bg-ember px-2.5 py-1 text-xs font-medium text-on-ember disabled:opacity-40"
                  >
                    {b.status === 'failed' ? t('command.batch.retry') : t('command.batch.approve')}
                  </button>
                  <button
                    onClick={() => setRejecting(b)}
                    disabled={busy}
                    className="rounded-md border border-line px-2.5 py-1 text-xs hover:bg-sunken"
                  >
                    {t('command.batch.reject')}
                  </button>
                </>
              )}
              {b.status === 'awaiting_approval' && !b.can_decide && (
                <span className="text-xs text-ink-faint">{t('command.batch.needsSomeoneElse')}</span>
              )}
              {b.status === 'sent' && (
                <button
                  onClick={() => act.mutate({ batch: b, action: 'refresh' })}
                  disabled={busy}
                  className="rounded-md border border-line px-2.5 py-1 text-xs hover:bg-sunken"
                >
                  {t('command.batch.checkPaypal')}
                </button>
              )}
            </div>
          )
        },
      },
    ],
    [act, statusLabel, t],
  )

  const detailColumns = useMemo<ColDef<AidBatchItem>[]>(
    () => [
      { field: 'household_name', headerName: t('command.col.household'), flex: 1 },
      {
        field: 'damage_level',
        headerName: t('command.col.damage'),
        width: 140,
        valueFormatter: (p) => t(`command.damage.${p.value}`),
      },
      { field: 'amount', headerName: t('command.batch.col.amount'), width: 120, type: 'rightAligned', valueFormatter: (p) => money(p.value) },
      { field: 'receiver', headerName: t('command.col.paypal'), width: 230 },
      { field: 'status', headerName: t('command.batch.col.status'), width: 140, valueFormatter: (p) => statusLabel(p.value) },
      {
        field: 'note',
        headerName: t('command.batch.col.note'),
        width: 220,
        valueFormatter: (p) => (p.value ? t(`command.batch.reason.${p.value}`, { defaultValue: p.value }) : ''),
      },
    ],
    [statusLabel, t],
  )

  if (!batches.data?.length) return null
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">{t('command.batch.listTitle')}</h2>
      <AgGridReact<AidBatch>
        theme={gridTheme}
        rowData={batches.data}
        columnDefs={columnDefs}
        getRowId={(p) => String(p.data.id)}
        domLayout="autoHeight"
        rowHeight={48}
        masterDetail
        detailRowAutoHeight
        detailCellRendererParams={{
          detailGridOptions: {
            columnDefs: detailColumns,
            defaultColDef: { sortable: true, resizable: true, suppressHeaderMenuButton: true },
            domLayout: 'autoHeight',
            pagination: true,
            paginationPageSize: 10,
            paginationPageSizeSelector: [10, 25, 50],
          },
          getDetailRowData: (params: { data: AidBatch; successCallback: (rows: AidBatchItem[]) => void }) =>
            params.successCallback(params.data.items ?? []),
        }}
        defaultColDef={{ sortable: true, resizable: true, suppressHeaderMenuButton: true }}
      />
      {rejecting && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg bg-sunken p-3 text-sm">
          <span>{t('command.batch.rejectWhy', { id: rejecting.id })}</span>
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="min-w-64 flex-1 rounded-lg border border-line bg-surface px-3 py-1.5"
          />
          <button
            onClick={() => act.mutate({ batch: rejecting, action: 'reject' })}
            disabled={reason.trim().length < 5 || act.isPending}
            className="rounded-lg bg-danger px-3 py-1.5 font-medium text-white disabled:opacity-40"
          >
            {t('command.batch.reject')}
          </button>
          <button onClick={() => setRejecting(null)} className="px-2 text-ink-soft">
            {t('command.batch.cancel')}
          </button>
        </div>
      )}
      {error && <p className="text-sm text-danger">{error}</p>}
    </section>
  )
}
