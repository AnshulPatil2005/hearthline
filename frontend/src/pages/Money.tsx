import { useQuery } from '@tanstack/react-query'
import type { ColDef, ValueFormatterParams } from 'ag-grid-community'
import { AgGridReact } from 'ag-grid-react'
import { useMemo, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type Fund, type LedgerPosting, type LedgerRow } from '../api'
import { money } from '../format'
import { gridTheme } from '../grid'

type Row = Omit<LedgerRow, 'amount' | 'balance'> & { amount: number; balance: number }

const signedMoney = (p: ValueFormatterParams) =>
  p.value == null ? '' : `${p.value > 0 ? '+' : ''}${money(p.value, { cents: true })}`

export default function Money() {
  const { t, i18n } = useTranslation()
  const grid = useRef<AgGridReact<Row>>(null)
  const fund = useQuery({ queryKey: ['fund'], queryFn: () => api<Fund>('/households/me/fund') })
  const ledger = useQuery({ queryKey: ['ledger'], queryFn: () => api<LedgerRow[]>('/households/me/ledger') })
  const rows = useMemo<Row[]>(
    () => (ledger.data ?? []).map((r) => ({ ...r, amount: Number(r.amount), balance: Number(r.balance) })),
    [ledger.data],
  )

  const columnDefs = useMemo<ColDef<Row>[]>(
    () => [
      {
        field: 'created_at',
        headerName: t('money.col.date'),
        cellRenderer: 'agGroupCellRenderer', // expand arrow for the postings detail
        valueFormatter: (p) =>
          p.value
            ? new Date(p.value).toLocaleString(i18n.resolvedLanguage, { dateStyle: 'medium', timeStyle: 'short' })
            : '',
        width: 220,
      },
      {
        field: 'kind',
        headerName: t('money.col.kind'),
        enableRowGroup: true,
        filter: 'agSetColumnFilter',
        valueFormatter: (p) => (p.value ? t(`money.kind.${p.value}`, { defaultValue: p.value }) : ''),
        width: 140,
      },
      { field: 'description', headerName: t('money.col.description'), flex: 1, minWidth: 240 },
      {
        field: 'amount',
        headerName: t('money.col.amount'),
        aggFunc: 'sum',
        valueFormatter: signedMoney,
        cellClassRules: { 'text-sage': (p) => p.value > 0, 'text-danger': (p) => p.value < 0 },
        type: 'rightAligned',
        width: 140,
      },
      {
        field: 'balance',
        headerName: t('money.col.balance'),
        valueFormatter: (p) => (p.value == null ? '' : money(p.value, { cents: true })),
        type: 'rightAligned',
        width: 140,
      },
      { field: 'paypal_ref', headerName: t('money.col.paypalRef'), width: 200, cellClass: 'font-mono text-xs' },
    ],
    [t, i18n.resolvedLanguage],
  )

  const detailCellRendererParams = useMemo(
    () => ({
      detailGridOptions: {
        theme: gridTheme,
        columnDefs: [
          { field: 'account_name', headerName: t('money.col.account'), flex: 1 },
          { field: 'account_code', headerName: t('money.col.accountCode'), flex: 1, cellClass: 'font-mono text-xs' },
          {
            headerName: t('money.col.debit'),
            valueGetter: (p: { data: LedgerPosting }) => (Number(p.data.amount) > 0 ? Number(p.data.amount) : null),
            valueFormatter: (p: ValueFormatterParams) => (p.value == null ? '' : money(p.value, { cents: true })),
            type: 'rightAligned',
          },
          {
            headerName: t('money.col.credit'),
            valueGetter: (p: { data: LedgerPosting }) => (Number(p.data.amount) < 0 ? -Number(p.data.amount) : null),
            valueFormatter: (p: ValueFormatterParams) => (p.value == null ? '' : money(p.value, { cents: true })),
            type: 'rightAligned',
          },
        ],
        domLayout: 'autoHeight',
      },
      getDetailRowData: (p: { data: Row; successCallback: (rows: LedgerPosting[]) => void }) =>
        p.successCallback(p.data.postings),
    }),
    [t],
  )

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-4xl leading-tight tracking-tight text-balance">{t('money.title')}</h1>
          <p className="mt-1 text-ink-soft">{t('money.subtitle')}</p>
        </div>
        <button
          onClick={() => grid.current?.api.exportDataAsExcel({ fileName: 'hearthline-ledger.xlsx' })}
          disabled={!rows.length}
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium hover:bg-sunken disabled:opacity-40"
        >
          {t('money.export')}
        </button>
      </div>

      {fund.data && (
        <dl className="grid gap-x-6 gap-y-5 sm:grid-cols-3">
          {(['donated', 'spent', 'available'] as const).map((k) => (
            <div key={k} className="border-t-2 border-ink pt-2">
              <dt className="kicker text-ink-faint">{t(`registry.fund.${k}`)}</dt>
              <dd className="figure mt-1 text-3xl font-semibold">{money(fund.data[k], { cents: true })}</dd>
            </div>
          ))}
        </dl>
      )}

      {ledger.data && rows.length === 0 ? (
        <p className="rounded-xl border border-dashed border-line px-4 py-10 text-center text-ink-soft">
          {t('money.empty')}
        </p>
      ) : (
        <div className="h-[60vh] min-h-96">
          <AgGridReact<Row>
            ref={grid}
            theme={gridTheme}
            rowData={rows}
            columnDefs={columnDefs}
            getRowId={(p) => String(p.data.id)}
            masterDetail
            detailCellRendererParams={detailCellRendererParams}
            detailRowAutoHeight
            defaultColDef={{ sortable: true, resizable: true }}
            rowGroupPanelShow="always"
            grandTotalRow="bottom"
            suppressAggFuncInHeader
            sideBar={{ toolPanels: ['columns', 'filters'] }}
            cellSelection
            enableCharts
          />
        </div>
      )}
      <p className="text-xs text-ink-faint">{t('money.hint')}</p>
    </div>
  )
}
