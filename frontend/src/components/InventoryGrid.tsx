import { useQueryClient } from '@tanstack/react-query'
import type {
  CellValueChangedEvent,
  ChartRef,
  ColDef,
  GetContextMenuItems,
  GridApi,
  ICellRendererParams,
  ValueFormatterParams,
} from 'ag-grid-community'
import { AgGridReact } from 'ag-grid-react'
import { forwardRef, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, CATEGORIES, mediaUrl, type EvidenceLevel, type Item } from '../api'
import { money } from '../format'
import { chartColors, gridTheme } from '../grid'
import { toRow, type Row } from '../rows'
import { BuiltWith } from './Showcase'

const EVIDENCE_TINT: Record<EvidenceLevel, string> = {
  pre_disaster_scan: 'bg-sage-soft text-sage',
  photo: 'bg-sunken text-ink',
  receipt: 'bg-sunken text-ink',
  memory: 'bg-amber-soft text-amber',
}

const CATEGORY_ORDER: readonly string[] = CATEGORIES

const EDITABLE: Record<string, keyof Item> = {
  name: 'name',
  category: 'category',
  quantity: 'quantity',
  unit_price: 'unit_price',
  confirmed: 'confirmed',
}

function PhotoCell({ value }: ICellRendererParams<Row, string | null>) {
  const src = mediaUrl(value ?? null)
  return src ? <img src={src} alt="" loading="lazy" className="my-1 h-9 w-12 rounded object-cover" /> : null
}

function PriceCell({ data, valueFormatted }: ICellRendererParams<Row, number | null>) {
  if (!data) return null
  return (
    <div className="flex h-full flex-col items-end justify-center leading-tight">
      <span>{valueFormatted}</span>
      {data.price_low != null && (
        <span className="text-xs text-ink-faint">
          {money(data.price_low)}–{money(data.price_high)}
        </span>
      )}
    </div>
  )
}

function MatchCell({ data }: ICellRendererParams<Row>) {
  if (!data?.match_url) return null
  return (
    <a
      href={data.match_url}
      target="_blank"
      rel="noreferrer"
      title={data.match_title ?? ''}
      className="text-ember hover:underline"
    >
      {data.retailer} ↗
    </a>
  )
}

type Props = { rows: Row[]; onChanged: () => void; onError: (message: string) => void }

const moneyCell = (p: ValueFormatterParams) =>
  p.value === null || p.value === undefined ? '' : money(p.value, { cents: true })

const InventoryGrid = forwardRef<AgGridReact<Row>, Props>(function InventoryGrid({ rows, onChanged, onError }, ref) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  // "By category" pivots the same rows (rooms down, kinds of item across) and charts the pivot: what each room held
  const [view, setView] = useState<'items' | 'category'>('items')
  const gridApi = useRef<GridApi<Row> | null>(null)
  const chartBox = useRef<HTMLDivElement>(null)
  const chart = useRef<ChartRef | undefined>(undefined)
  const colors = useMemo(
    () => ({
      ...chartColors(),
      chartThemeOverrides: {
        bar: {
          axes: {
            'grouped-category': { label: { rotation: 0 } },
            number: { label: { formatter: ({ value }: { value: number }) => money(value) } },
          },
        },
      },
    }),
    [],
  )

  useEffect(() => {
    const api = gridApi.current
    if (!api) return
    api.applyColumnState({ state: [{ colId: 'category', pivot: view === 'category' }] })
    api.setGridOption('pivotMode', view === 'category')
    if (view === 'category' && chartBox.current) {
      chart.current = api.createPivotChart({ chartType: 'stackedColumn', chartContainer: chartBox.current })
    }
    return () => {
      chart.current?.destroyChart()
      chart.current = undefined
    }
  }, [view])

  const columnDefs = useMemo<ColDef<Row>[]>(
    () => [
      { field: 'photo_url', headerName: '', width: 60, cellRenderer: PhotoCell, sortable: false },
      { field: 'room_name', headerName: t('inventory.col.room'), rowGroup: true, hide: true },
      {
        field: 'name',
        headerName: t('inventory.col.item'),
        editable: true,
        flex: 1,
        minWidth: 200,
        tooltipField: 'name',
      },
      {
        field: 'category',
        headerName: t('inventory.col.category'),
        editable: true,
        cellEditor: 'agSelectCellEditor',
        cellEditorParams: { values: [...CATEGORIES] },
        valueFormatter: (p) => (p.value ? t(`inventory.category.${p.value}`, { defaultValue: p.value }) : ''),
        filter: 'agSetColumnFilter',
        width: 145,
        enablePivot: true,
        pivotComparator: (a: string, b: string) => CATEGORY_ORDER.indexOf(a) - CATEGORY_ORDER.indexOf(b),
      },
      {
        field: 'quantity',
        headerName: t('inventory.col.qty'),
        editable: true,
        cellEditor: 'agNumberCellEditor',
        cellEditorParams: { min: 1, precision: 0 },
        width: 68,
      },
      {
        field: 'unit_price',
        headerName: t('inventory.col.unitPrice'),
        editable: true,
        cellEditor: 'agNumberCellEditor',
        cellEditorParams: { min: 0, precision: 2 },
        valueFormatter: moneyCell,
        cellRenderer: PriceCell,
        headerTooltip: t('inventory.col.range'),
        width: 130,
        type: 'rightAligned',
      },
      {
        colId: 'total',
        headerName: t('inventory.col.total'),
        valueGetter: (p) => (p.data ? (p.data.unit_price ?? 0) * p.data.quantity : undefined),
        aggFunc: 'sum',
        valueFormatter: moneyCell,
        width: 120,
        type: 'rightAligned',
        cellClass: 'font-semibold',
      },
      {
        field: 'evidence_level',
        headerName: t('inventory.col.evidence'),
        width: 150,
        filter: 'agSetColumnFilter',
        cellRenderer: ({ value }: ICellRendererParams<Row, EvidenceLevel>) =>
          value ? (
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${EVIDENCE_TINT[value]}`}>
              {t(`inventory.evidence.${value}`)}
            </span>
          ) : null,
      },
      { colId: 'match', headerName: t('inventory.col.match'), cellRenderer: MatchCell, width: 124, sortable: false },
      { field: 'confirmed', headerName: t('inventory.col.confirmed'), editable: true, width: 104 },
    ],
    [t],
  )

  async function onCellValueChanged(e: CellValueChangedEvent<Row>) {
    const field = e.colDef.field && EDITABLE[e.colDef.field]
    if (!field || !e.data || e.newValue === e.oldValue) return
    try {
      const saved = await api<Item>(`/items/${e.data.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ [field]: e.newValue }),
      })
      e.node.setData(toRow(saved))
      // The page's item list feeds the grid: keep it in step, or its next render puts the old value back
      queryClient.setQueryData<Item[]>(['items'], (old) => old?.map((i) => (i.id === saved.id ? saved : i)))
      void queryClient.invalidateQueries({ queryKey: ['inventory-summary'] })
      onChanged()
    } catch {
      e.node.setDataValue(e.colDef.field!, e.oldValue)
      onError(t('inventory.saveFailed'))
    }
  }

  const getContextMenuItems: GetContextMenuItems<Row> = (params) => {
    const row = params.node?.data
    return [
      ...(row
        ? [
            {
              name: t('inventory.delete'),
              action: async () => {
                await api(`/items/${row.id}`, { method: 'DELETE' })
                params.api.applyTransaction({ remove: [row] })
                queryClient.setQueryData<Item[]>(['items'], (old) => old?.filter((i) => i.id !== row.id))
                void queryClient.invalidateQueries({ queryKey: ['inventory-summary'] })
                onChanged()
              },
            },
            'separator' as const,
          ]
        : []),
      'copy',
      'excelExport',
    ]
  }

  return (
    // Short lists size to their rows; long ones scroll inside the grid so rendering stays fast.
    <>
      <div role="group" aria-label={t('inventory.view.label')} className="mb-2 flex gap-1 text-sm">
        {(['items', 'category'] as const).map((v) => (
          <button
            key={v}
            onClick={() => setView(v)}
            aria-pressed={view === v}
            className={`rounded-md border px-3 py-1 ${view === v ? 'border-ink bg-ink text-paper' : 'border-line hover:bg-sunken'}`}
          >
            {t(`inventory.view.${v}`)}
          </button>
        ))}
      </div>
      <div className={rows.length > 25 && view === 'items' ? 'h-[70vh]' : ''}>
        <AgGridReact<Row>
          ref={ref}
          onGridReady={(e) => (gridApi.current = e.api)}
          enableCharts
          cellSelection
          {...colors}
          removePivotHeaderRowWhenSingleValueColumn
          processPivotResultColDef={(col) => {
            const key = col.pivotKeys?.[0]
            if (key) col.headerName = t(`inventory.category.${key}`, { defaultValue: key })
          }}
          theme={gridTheme}
          rowData={rows}
          columnDefs={columnDefs}
          getRowId={(p) => String(p.data.id)}
          domLayout={rows.length > 25 && view === 'items' ? 'normal' : 'autoHeight'}
          defaultColDef={{ sortable: true, resizable: true, suppressHeaderMenuButton: true }}
          autoGroupColumnDef={{ headerName: t('inventory.col.room'), minWidth: 150 }}
          tooltipShowDelay={400}
          groupDefaultExpanded={1}
          grandTotalRow="bottom"
          suppressAggFuncInHeader
          stopEditingWhenCellsLoseFocus
          getContextMenuItems={getContextMenuItems}
          onCellValueChanged={(e) => void onCellValueChanged(e)}
          rowHeight={48}
        />
      </div>
      {view === 'category' && (
        <figure className="mt-3">
          <figcaption className="kicker text-ink-faint">{t('inventory.view.chartTitle')}</figcaption>
          <div ref={chartBox} className="h-80" />
        </figure>
      )}
      <BuiltWith
        name="AG Grid Enterprise"
        what="row grouping by room · pivot mode and a pivot chart (AG Charts) · inline editing · Excel export · prices from Channel3"
      />
    </>
  )
})

export default InventoryGrid
