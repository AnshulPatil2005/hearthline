import { useQuery } from '@tanstack/react-query'
import type { AgGridReact } from 'ag-grid-react'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type InventorySummary, type Item } from '../api'
import InventoryGrid from '../components/InventoryGrid'
import { toRow, type Row } from '../rows'
import ScanPanel from '../components/ScanPanel'
import { money } from '../format'

const EXPORT_COLUMNS = ['room_name', 'name', 'category', 'quantity', 'unit_price', 'total', 'evidence_level', 'match', 'confirmed']

export default function Inventory() {
  const { t } = useTranslation()
  const gridRef = useRef<AgGridReact<Row>>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const items = useQuery({ queryKey: ['items'], queryFn: () => api<Item[]>('/households/me/items') })
  const summary = useQuery({
    queryKey: ['inventory-summary'],
    queryFn: () => api<InventorySummary>('/households/me/inventory-summary'),
  })

  function exportClaim() {
    gridRef.current?.api.exportDataAsExcel({
      fileName: 'hearthline-contents-claim.xlsx',
      sheetName: t('inventory.exportSheet'),
      columnKeys: EXPORT_COLUMNS,
      processCellCallback: (p) => (p.column.getColId() === 'match' ? (p.node?.data?.match_url ?? '') : p.value),
    })
  }

  const unconfirmed = summary.data ? summary.data.item_count - summary.data.confirmed_count : 0

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">{t('inventory.title')}</h1>
          <p className="mt-1 text-ink-soft">{t('inventory.subtitle')}</p>
        </div>
        {summary.data && (
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span className="rounded-full bg-sunken px-3 py-1">
              {t('inventory.summary.total')} <strong className="tabular-nums">{money(summary.data.total_value)}</strong>
            </span>
            <span className="rounded-full bg-sunken px-3 py-1">{t('rooms.items', { count: summary.data.item_count })}</span>
            {unconfirmed > 0 && (
              <span className="rounded-full bg-amber-soft px-3 py-1 text-amber">
                {t('inventory.summary.unconfirmed', { count: unconfirmed })}
              </span>
            )}
            <button
              onClick={exportClaim}
              disabled={!items.data?.length}
              className="rounded-lg border border-line bg-surface px-3 py-1.5 font-medium hover:bg-sunken disabled:opacity-40"
            >
              {t('inventory.exportClaim')}
            </button>
          </div>
        )}
      </div>

      <ScanPanel />

      {notice && (
        <p role="status" className="rounded-lg bg-danger-soft px-4 py-2 text-sm text-danger">
          {notice}
        </p>
      )}

      {items.isError ? (
        <p role="alert" className="rounded-lg bg-danger-soft px-4 py-3 text-danger">
          {t('errors.generic')}
        </p>
      ) : items.data && items.data.length === 0 ? (
        <p className="rounded-xl border border-dashed border-line px-4 py-10 text-center text-ink-soft">{t('inventory.empty')}</p>
      ) : (
        <>
          <InventoryGrid
            ref={gridRef}
            rows={(items.data ?? []).map(toRow)}
            onChanged={() => setNotice(null)}
            onError={setNotice}
          />
          <p className="text-xs text-ink-faint">{t('inventory.hint')}</p>
        </>
      )}
    </div>
  )
}
