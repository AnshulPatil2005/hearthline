import { useQueryClient } from '@tanstack/react-query'
import type {
  CellValueChangedEvent,
  ColDef,
  GetContextMenuItems,
  ICellRendererParams,
  ValueFormatterParams,
} from 'ag-grid-community'
import { AgGridReact } from 'ag-grid-react'
import { forwardRef, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { api, CATEGORIES, mediaUrl, type EvidenceLevel, type Item } from '../api'
import { money } from '../format'
import { gridTheme } from '../grid'
import { toRow, type Row } from '../rows'

const EVIDENCE_TINT: Record<EvidenceLevel, string> = {
  pre_disaster_scan: 'bg-sage-soft text-sage',
  photo: 'bg-sunken text-ink',
  receipt: 'bg-sunken text-ink',
  memory: 'bg-amber-soft text-amber',
}

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
    <div className={rows.length > 25 ? 'h-[70vh]' : ''}>
      <AgGridReact<Row>
        ref={ref}
        theme={gridTheme}
        rowData={rows}
        columnDefs={columnDefs}
        getRowId={(p) => String(p.data.id)}
        domLayout={rows.length > 25 ? 'normal' : 'autoHeight'}
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
  )
})

export default InventoryGrid
