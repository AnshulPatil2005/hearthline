import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColDef, ICellRendererParams } from 'ag-grid-community'
import { AgGridReact } from 'ag-grid-react'
import { useCallback, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, ApiError, type DisasterEvent, type DisasterZone, type FemaDeclaration, type NwsWarning } from '../api'
import { ZoneShape } from '../components/ZoneShape'
import { parseTime } from '../format'
import { gridTheme } from '../grid'

type Tab = 'fema' | 'nws'
type Picked = { tab: 'fema'; row: FemaDeclaration } | { tab: 'nws'; row: NwsWarning }

const errorText = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback)

function useDate() {
  const { i18n } = useTranslation()
  const lang = i18n.resolvedLanguage
  return useCallback(
    (s: string, time = false) =>
      parseTime(s).toLocaleString(lang, time ? { dateStyle: 'medium', timeStyle: 'short' } : { dateStyle: 'medium' }),
    [lang],
  )
}

function SourceBadge({ e }: { e: DisasterEvent }) {
  const { t } = useTranslation()
  const tone = e.is_fictional ? 'bg-sunken text-ink-soft' : 'bg-danger-soft text-danger'
  const code = e.source === 'fema' ? (e.external_id ?? '') : ''
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}>
      {t(`disasters.source.${e.source}`, { code })}
    </span>
  )
}

function EventCard({ e }: { e: DisasterEvent }) {
  const { t } = useTranslation()
  const date = useDate()
  const queryClient = useQueryClient()
  const close = useMutation({
    mutationFn: () => api<DisasterEvent>(`/command/disasters/${e.id}/close`, { method: 'POST' }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['disasters'] })
      void queryClient.invalidateQueries({ queryKey: ['rapid-aid'] })
    },
  })
  return (
    <li
      className={`flex gap-4 rounded-xl border border-line bg-surface p-4 shadow-sm ${e.status === 'active' ? '' : 'border-dashed'}`}
    >
      <ZoneShape zone={e.zone} label={t('disasters.zoneOf', { name: e.name })} className="h-24 w-24 shrink-0" />
      <div className="min-w-0 flex-1 space-y-1">
        <p className="font-medium">{e.name}</p>
        <p className="flex flex-wrap items-center gap-2 text-xs text-ink-faint">
          <SourceBadge e={e} />
          <span>{t(`disasters.kind.${e.kind}`, { defaultValue: e.kind })}</span>
          <span>· {date(e.declared_at)}</span>
        </p>
        <p className="text-sm text-ink-soft">
          {t('disasters.households', { count: e.households, n: e.households.toLocaleString() })}
          {e.opened_by && ` · ${t('disasters.openedBy', { name: e.opened_by })}`}
        </p>
        {e.status !== 'active' ? (
          <p className="text-xs font-medium text-ink-faint">{t('disasters.closed')}</p>
        ) : (
          !e.is_fictional && (
            <button
              onClick={() => close.mutate()}
              disabled={close.isPending}
              className="text-sm text-ink-soft hover:underline disabled:opacity-40"
            >
              {t('disasters.close')}
            </button>
          )
        )}
        {close.isError && <p className="text-sm text-danger">{errorText(close.error, t('errors.generic'))}</p>}
      </div>
    </li>
  )
}

function Preview({ picked, onOpened }: { picked: Picked; onOpened: (e: DisasterEvent) => void }) {
  const { t } = useTranslation()
  const date = useDate()
  const zoneUrl =
    picked.tab === 'fema'
      ? `/command/disasters/fema/${picked.row.number}/zone`
      : `/command/disasters/nws/zone?alert_id=${encodeURIComponent(picked.row.id)}`
  const zone = useQuery({
    queryKey: ['disaster-zone', zoneUrl],
    queryFn: () => api<DisasterZone>(zoneUrl),
    staleTime: 10 * 60_000,
    retry: false,
  })
  const open = useMutation({
    mutationFn: () =>
      picked.tab === 'fema'
        ? api<DisasterEvent>(`/command/disasters/fema/${picked.row.number}`, { method: 'POST' })
        : api<DisasterEvent>('/command/disasters/nws', {
            method: 'POST',
            body: JSON.stringify({ alert_id: picked.row.id }),
          }),
    onSuccess: onOpened,
  })
  const title = picked.tab === 'fema' ? `${picked.row.title} (${picked.row.state})` : picked.row.event
  const opened = picked.row.opened_event_id !== null
  return (
    <section
      aria-labelledby="preview-title"
      className="space-y-3 rounded-xl border border-line bg-surface p-4 shadow-sm"
    >
      <div>
        <h3 id="preview-title" className="font-semibold">
          {title}
        </h3>
        {picked.tab === 'fema' ? (
          <p className="text-xs text-ink-faint">
            {picked.row.code} · {picked.row.incident} ·{' '}
            {t('disasters.declared', { date: date(picked.row.declared_at) })}
          </p>
        ) : (
          <p className="text-xs text-ink-faint">
            {picked.row.severity} · {t('disasters.sent', { date: date(picked.row.sent, true) })}
            {picked.row.expires && ` · ${t('disasters.expires', { date: date(picked.row.expires, true) })}`}
          </p>
        )}
      </div>
      {zone.isPending && (
        <div className="h-56 animate-pulse rounded-lg bg-sunken" aria-label={t('disasters.loadingZone')} />
      )}
      {zone.isError && <p className="text-sm text-danger">{errorText(zone.error, t('errors.generic'))}</p>}
      {zone.data && (
        <>
          <ZoneShape zone={zone.data.zone} label={t('disasters.zoneOf', { name: title })} className="h-56 w-full" />
          <p className="text-sm">
            {t('disasters.inside', { count: zone.data.households, n: zone.data.households.toLocaleString() })}
          </p>
        </>
      )}
      <p className="text-sm text-ink-soft">
        {picked.tab === 'fema'
          ? t('disasters.areas', { count: picked.row.areas.length, areas: picked.row.areas.slice(0, 6).join(', ') })
          : picked.row.area}
      </p>
      {picked.tab === 'fema' && picked.row.unmapped.length > 0 && (
        <p className="text-xs text-ink-faint">{t('disasters.unmapped', { areas: picked.row.unmapped.join(', ') })}</p>
      )}
      <p className="text-xs text-ink-soft">
        {picked.tab === 'fema' || picked.row.first_72_hours ? t('disasters.willPropose') : t('disasters.wontPropose')}
      </p>
      {opened ? (
        <p className="text-sm font-medium text-sage">{t('disasters.alreadyOpen')}</p>
      ) : (
        <button
          onClick={() => open.mutate()}
          disabled={open.isPending || !zone.data}
          className="rounded-lg bg-ember px-3 py-1.5 text-sm font-medium text-on-ember disabled:opacity-40"
        >
          {open.isPending ? t('disasters.opening') : t('disasters.open')}
        </button>
      )}
      {open.isError && <p className="text-sm text-danger">{errorText(open.error, t('errors.generic'))}</p>}
    </section>
  )
}

/** Real disasters: FEMA's declarations and the National Weather Service's warnings, opened in Hearthline by staff. */
export default function Disasters() {
  const { t } = useTranslation()
  const date = useDate()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<Tab>('fema')
  const [search, setSearch] = useState('')
  const [picked, setPicked] = useState<Picked | null>(null)
  const [opened, setOpened] = useState<DisasterEvent | null>(null)
  const events = useQuery({ queryKey: ['disasters'], queryFn: () => api<DisasterEvent[]>('/command/disasters') })
  const fema = useQuery({
    queryKey: ['disasters-fema'],
    queryFn: () => api<FemaDeclaration[]>('/command/disasters/fema'),
    enabled: tab === 'fema',
    retry: false,
  })
  const nws = useQuery({
    queryKey: ['disasters-nws'],
    queryFn: () => api<NwsWarning[]>('/command/disasters/nws'),
    enabled: tab === 'nws',
    retry: false,
  })

  const femaColumns = useMemo<ColDef<FemaDeclaration>[]>(
    () => [
      {
        field: 'declared_at',
        headerName: t('disasters.col.declared'),
        width: 120,
        sort: 'desc',
        valueFormatter: (p) => (p.value ? date(p.value) : ''),
      },
      { field: 'code', headerName: t('disasters.col.code'), width: 125 },
      { field: 'state', headerName: t('disasters.col.state'), width: 85, filter: 'agSetColumnFilter' },
      {
        field: 'kind',
        headerName: t('disasters.col.kind'),
        width: 120,
        filter: 'agSetColumnFilter',
        valueFormatter: (p) => t(`disasters.kind.${p.value}`, { defaultValue: p.value }),
      },
      { field: 'title', headerName: t('disasters.col.title'), flex: 1, minWidth: 200 },
      { field: 'counties', headerName: t('disasters.col.counties'), width: 100, type: 'rightAligned' },
      {
        field: 'opened_event_id',
        headerName: t('disasters.col.opened'),
        width: 105,
        valueFormatter: (p) => (p.value ? t('disasters.yes') : ''),
      },
    ],
    [date, t],
  )
  const nwsColumns = useMemo<ColDef<NwsWarning>[]>(
    () => [
      {
        field: 'first_72_hours',
        headerName: t('disasters.col.aid'),
        width: 120,
        filter: 'agSetColumnFilter',
        valueFormatter: (p) => (p.value ? t('disasters.yes') : t('disasters.no')),
        cellRenderer: (p: ICellRendererParams<NwsWarning>) =>
          p.data?.first_72_hours ? (
            <span className="rounded-full bg-danger-soft px-2 py-0.5 text-xs font-medium text-danger">
              {t('disasters.qualifies')}
            </span>
          ) : null,
      },
      { field: 'event', headerName: t('disasters.col.event'), width: 200, filter: 'agSetColumnFilter' },
      { field: 'severity', headerName: t('disasters.col.severity'), width: 110, filter: 'agSetColumnFilter' },
      { field: 'area', headerName: t('disasters.col.area'), flex: 1, minWidth: 220 },
      {
        field: 'sent',
        headerName: t('disasters.col.sent'),
        width: 170,
        valueFormatter: (p) => (p.value ? date(p.value, true) : ''),
      },
      {
        field: 'has_shape',
        headerName: t('disasters.col.zone'),
        width: 140,
        valueGetter: (p) =>
          p.data?.has_shape ? t('disasters.polygon') : t('disasters.countiesN', { count: p.data?.counties ?? 0 }),
      },
    ],
    [date, t],
  )

  const onOpened = (e: DisasterEvent) => {
    setOpened(e)
    setPicked(null)
    for (const key of ['disasters', 'disasters-fema', 'disasters-nws', 'rapid-aid'])
      void queryClient.invalidateQueries({ queryKey: [key] })
  }
  const active = tab === 'fema' ? fema : nws
  const tabClass = (on: boolean) =>
    `rounded-lg px-3 py-1.5 text-sm font-medium ${on ? 'bg-ember text-on-ember' : 'text-ink-soft hover:bg-sunken'}`

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">{t('disasters.title')}</h1>
        <p className="mt-1 max-w-3xl text-ink-soft">{t('disasters.subtitle')}</p>
      </div>

      <section aria-labelledby="open-title" className="space-y-3">
        <h2 id="open-title" className="text-lg font-semibold">
          {t('disasters.inHearthline')}
        </h2>
        <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {events.data?.map((e) => (
            <EventCard key={e.id} e={e} />
          ))}
        </ul>
      </section>

      {opened && (
        <p role="status" className="rounded-lg bg-sage-soft px-4 py-3 text-sm text-sage">
          {t('disasters.openedNote', {
            name: opened.name,
            count: opened.households,
            n: opened.households.toLocaleString(),
          })}{' '}
          <Link to="/command" className="font-medium underline">
            {t('disasters.reviewAid')}
          </Link>
        </p>
      )}

      <section aria-labelledby="find-title" className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="find-title" className="text-lg font-semibold">
              {t('disasters.find')}
            </h2>
            <p className="text-sm text-ink-soft">{t(tab === 'fema' ? 'disasters.femaNote' : 'disasters.nwsNote')}</p>
          </div>
          <div
            role="tablist"
            aria-label={t('disasters.find')}
            className="flex gap-1 rounded-xl border border-line bg-surface p-1"
          >
            {(['fema', 'nws'] as const).map((k) => (
              <button
                key={k}
                role="tab"
                aria-selected={tab === k}
                onClick={() => {
                  setTab(k)
                  setPicked(null)
                }}
                className={tabClass(tab === k)}
              >
                {t(`disasters.tab.${k}`)}
              </button>
            ))}
          </div>
        </div>
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t(tab === 'fema' ? 'disasters.searchFema' : 'disasters.searchNws')}
          aria-label={t(tab === 'fema' ? 'disasters.searchFema' : 'disasters.searchNws')}
          className="w-full max-w-md rounded-lg border border-line bg-surface px-3 py-2 text-sm"
        />
        {active.isError && <p className="text-sm text-danger">{errorText(active.error, t('errors.generic'))}</p>}
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="h-[30rem]">
            {tab === 'fema' ? (
              <AgGridReact<FemaDeclaration>
                theme={gridTheme}
                rowData={fema.data ?? []}
                columnDefs={femaColumns}
                getRowId={(p) => String(p.data.number)}
                quickFilterText={search}
                defaultColDef={{ sortable: true, resizable: true, suppressHeaderMenuButton: true }}
                rowSelection={{ mode: 'singleRow', checkboxes: false, enableClickSelection: true }}
                onRowClicked={(e) => e.data && setPicked({ tab: 'fema', row: e.data })}
                loading={fema.isPending}
              />
            ) : (
              <AgGridReact<NwsWarning>
                theme={gridTheme}
                rowData={nws.data ?? []}
                columnDefs={nwsColumns}
                getRowId={(p) => p.data.id}
                quickFilterText={search}
                defaultColDef={{ sortable: true, resizable: true, suppressHeaderMenuButton: true }}
                rowSelection={{ mode: 'singleRow', checkboxes: false, enableClickSelection: true }}
                onRowClicked={(e) => e.data && setPicked({ tab: 'nws', row: e.data })}
                loading={nws.isPending}
              />
            )}
          </div>
          {picked ? (
            <Preview
              key={picked.tab === 'fema' ? picked.row.number : picked.row.id}
              picked={picked}
              onOpened={onOpened}
            />
          ) : (
            <p className="rounded-xl border border-dashed border-line p-4 text-sm text-ink-soft">
              {t('disasters.pick')}
            </p>
          )}
        </div>
        <p className="text-xs text-ink-faint">{t('disasters.sources')}</p>
      </section>
    </div>
  )
}
