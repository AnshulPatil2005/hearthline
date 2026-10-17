import { useQuery, useQueryClient } from '@tanstack/react-query'
import type {
  ColDef,
  GetRowIdParams,
  GridApi,
  GridState,
  ICellRendererParams,
  IServerSideDatasource,
  SetFilterValuesFuncParams,
  ValueFormatterParams,
} from 'ag-grid-community'
import { AgGridReact } from 'ag-grid-react'
import { useCallback, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, downloadFile, type CommandRow, type CommandSummary, type DamageLevel } from '../api'
import { AidBatchPanel } from '../components/AidBatchPanel'
import { AidBatches } from '../components/AidBatches'
import { AskGrid } from '../components/AskGrid'
import { Stat } from '../components/Milestones'
import { money } from '../format'
import { gridTheme } from '../grid'

const DAMAGE_TONE: Record<DamageLevel, string> = {
  destroyed: 'bg-danger-soft text-danger',
  major: 'bg-amber-soft text-amber',
  minor: 'bg-sunken text-ink',
  affected: 'bg-sunken text-ink-soft',
  unknown: 'bg-sunken text-ink-faint',
}

const cssColor = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

/** Set filter values come from the server, because the browser only ever holds one block of rows. */
const serverValues = (field: string) => (params: SetFilterValuesFuncParams) => {
  api<unknown[]>(`/command/households/values/${field}`)
    .then((values) => params.success(values.map((v) => (typeof v === 'number' ? String(v) : v)) as string[]))
    .catch(() => params.success([]))
}

export default function CommandCenter() {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const gridApi = useRef<GridApi<CommandRow> | null>(null)
  const initialState = useRef<GridState | null>(null)
  const [matching, setMatching] = useState<number | null>(null)
  const [batching, setBatching] = useState(false)
  const summary = useQuery({ queryKey: ['command-summary'], queryFn: () => api<CommandSummary>('/command/summary') })

  const datasource = useMemo<IServerSideDatasource<CommandRow>>(
    () => ({
      getRows: (params) => {
        api<{ rows: CommandRow[]; lastRow: number; matching: number }>('/command/households/rows', {
          method: 'POST',
          body: JSON.stringify(params.request),
        })
          .then(({ rows, lastRow, matching }) => {
            if (params.request.groupKeys.length === 0) setMatching(matching)
            params.success({ rowData: rows, rowCount: lastRow })
          })
          .catch(() => params.fail())
      },
    }),
    [],
  )

  const moneyCell = (p: ValueFormatterParams) => (p.value === null || p.value === undefined ? '' : money(p.value))
  const columnDefs = useMemo<ColDef<CommandRow>[]>(
    () => [
      { field: 'name', headerName: t('command.col.household'), width: 190, filter: 'agTextColumnFilter' },
      {
        field: 'damage_level',
        headerName: t('command.col.damage'),
        width: 140,
        enableRowGroup: true,
        filter: 'agSetColumnFilter',
        filterParams: {
          values: serverValues('damage_level'),
          valueFormatter: (p: ValueFormatterParams) => t(`command.damage.${p.value}`),
        },
        valueFormatter: (p) => (p.value ? t(`command.damage.${p.value}`) : ''),
        cellRenderer: (p: ICellRendererParams<CommandRow>) =>
          p.value ? (
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${DAMAGE_TONE[p.value as DamageLevel]}`}>
              {t(`command.damage.${p.value}`)}
            </span>
          ) : null,
      },
      {
        field: 'verification_level',
        headerName: t('command.col.level'),
        width: 115,
        enableRowGroup: true,
        filter: 'agSetColumnFilter',
        filterParams: {
          values: serverValues('verification_level'),
          valueFormatter: (p: ValueFormatterParams) => t(`command.level`, { level: p.value }),
        },
        valueFormatter: (p) => (p.value === null || p.value === undefined ? '' : t('command.level', { level: p.value })),
      },
      {
        field: 'unmet_need',
        headerName: t('command.col.unmet'),
        width: 150,
        type: 'rightAligned',
        sort: 'desc',
        filter: 'agNumberColumnFilter',
        enableValue: true,
        aggFunc: 'sum',
        enableCellChangeFlash: true,
        valueFormatter: moneyCell,
        cellClass: ['ag-right-aligned-cell', 'font-semibold'],
      },
      {
        field: 'help_received',
        headerName: t('command.col.help'),
        width: 150,
        type: 'rightAligned',
        filter: 'agNumberColumnFilter',
        enableValue: true,
        aggFunc: 'sum',
        enableCellChangeFlash: true,
        valueFormatter: moneyCell,
      },
      {
        field: 'help_trend',
        headerName: t('command.col.trend'),
        width: 140,
        sortable: false,
        cellRenderer: 'agSparklineCellRenderer',
        cellRendererParams: {
          sparklineOptions: { type: 'bar', direction: 'vertical', fill: cssColor('--sage'), padding: { top: 6, bottom: 6 } },
        },
      },
      {
        field: 'estimated_loss',
        headerName: t('command.col.loss'),
        width: 150,
        type: 'rightAligned',
        filter: 'agNumberColumnFilter',
        enableValue: true,
        aggFunc: 'sum',
        valueFormatter: moneyCell,
      },
      {
        field: 'needs',
        headerName: t('command.col.needs'),
        width: 260,
        sortable: false,
        filter: 'agSetColumnFilter',
        filterParams: {
          values: serverValues('needs'),
          valueFormatter: (p: ValueFormatterParams) => t(`command.need.${p.value}`, { defaultValue: p.value }),
        },
        valueFormatter: (p) =>
          Array.isArray(p.value) ? p.value.map((n: string) => t(`command.need.${n}`, { defaultValue: n })).join(', ') : '',
      },
      {
        field: 'household_size',
        headerName: t('command.col.size'),
        width: 110,
        enableRowGroup: true,
        filter: 'agNumberColumnFilter',
        type: 'rightAligned',
      },
      {
        field: 'payout_ready',
        headerName: t('command.col.paypal'),
        width: 115,
        enableRowGroup: true,
        filter: 'agSetColumnFilter',
        filterParams: {
          values: [true, false],
          valueFormatter: (p: ValueFormatterParams) => (p.value === true || p.value === 'true' ? t('command.yes') : t('command.no')),
        },
        valueFormatter: (p) => (p.value === true ? t('command.yes') : p.value === false ? t('command.no') : ''),
      },
      { field: 'address_line', headerName: t('command.col.address'), width: 180, filter: 'agTextColumnFilter' },
      {
        field: 'street',
        headerName: t('command.col.street'),
        hide: true,
        enableRowGroup: true,
        filter: 'agSetColumnFilter',
        filterParams: { values: serverValues('street') },
      },
      {
        field: 'registered',
        headerName: t('command.col.registered'),
        width: 140,
        filter: 'agDateColumnFilter',
        valueFormatter: (p) =>
          p.value ? new Date(p.value).toLocaleDateString(i18n.resolvedLanguage, { month: 'short', day: 'numeric' }) : '',
      },
    ],
    [i18n.resolvedLanguage, t],
  )

  // Stable props: a new object on every render makes AG Grid rebuild its columns (and close open filters).
  const defaultColDef = useMemo<ColDef>(() => ({ sortable: true, resizable: true, suppressHeaderMenuButton: true }), [])
  const autoGroupColumnDef = useMemo<ColDef<CommandRow>>(
    () => ({ headerName: t('command.col.group'), minWidth: 230, pinned: 'left' }),
    [t],
  )
  const sideBar = useMemo(() => ({ toolPanels: ['columns', 'filters'] }), [])
  const getChildCount = useCallback((data: { childCount?: number } | undefined) => data?.childCount ?? 0, [])

  const getRowId = useCallback((p: GetRowIdParams<CommandRow>) => {
    const groupCols = p.api.getRowGroupColumns()
    if (p.level < groupCols.length) {
      const field = groupCols[p.level].getColDef().field as keyof CommandRow
      return ['group', ...(p.parentKeys ?? []), String(p.data[field])].join('|')
    }
    return String(p.data.id)
  }, [])

  const refresh = () => {
    gridApi.current?.refreshServerSide({ purge: false })
    void queryClient.invalidateQueries({ queryKey: ['command-summary'] })
  }

  const s = summary.data
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">{t('command.title')}</h1>
          <p className="mt-1 text-ink-soft">{t('command.subtitle')}</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setBatching((b) => !b)}
            className="rounded-lg bg-ember px-3 py-1.5 text-sm font-medium text-on-ember"
          >
            {t('command.batch.open')}
          </button>
          <button
            onClick={() => void downloadFile('/command/reports/grant.pdf', 'hearthline-grant-report.pdf')}
            className="rounded-lg border border-line px-3 py-1.5 text-sm text-ink-soft hover:bg-sunken"
          >
            {t('command.grantReport')}
          </button>
          <button onClick={refresh} className="rounded-lg border border-line px-3 py-1.5 text-sm text-ink-soft hover:bg-sunken">
            {t('command.refresh')}
          </button>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <Stat label={t('command.stat.households')} value={s ? s.households.toLocaleString(i18n.resolvedLanguage) : '…'} />
        <Stat label={t('command.stat.destroyed')} value={s ? s.destroyed.toLocaleString(i18n.resolvedLanguage) : '…'} />
        <Stat label={t('command.stat.verified')} value={s ? s.verified.toLocaleString(i18n.resolvedLanguage) : '…'} />
        <Stat label={t('command.stat.help')} value={s ? money(s.help_received) : '…'} />
        <Stat label={t('command.stat.unmet')} value={s ? money(s.unmet_need) : '…'} />
      </div>
      {batching && (
        <AidBatchPanel
          filterModel={() => gridApi.current?.getFilterModel() ?? {}}
          onCreated={() => void queryClient.invalidateQueries({ queryKey: ['aid-batches'] })}
        />
      )}
      <AskGrid grid={() => gridApi.current} initial={() => initialState.current} />
      <p className="text-sm text-ink-soft" aria-live="polite">
        {matching !== null && t('command.matching', { count: matching, n: matching.toLocaleString(i18n.resolvedLanguage) })}
      </p>
      <div className="h-[calc(100svh-22rem)] min-h-[30rem]">
        <AgGridReact<CommandRow>
          theme={gridTheme}
          rowModelType="serverSide"
          serverSideDatasource={datasource}
          cacheBlockSize={100}
          columnDefs={columnDefs}
          defaultColDef={defaultColDef}
          autoGroupColumnDef={autoGroupColumnDef}
          getRowId={getRowId}
          getChildCount={getChildCount}
          rowGroupPanelShow="always"
          suppressAggFuncInHeader
          sideBar={sideBar}
          onGridReady={(e) => {
            gridApi.current = e.api
            initialState.current = e.api.getState()
          }}
        />
      </div>
      <p className="text-xs text-ink-faint">{t('command.hint')}</p>
      <AidBatches onPaid={refresh} />
    </div>
  )
}
