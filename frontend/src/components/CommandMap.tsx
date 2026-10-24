import { useQuery } from '@tanstack/react-query'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type CommandMapData } from '../api'
import { money } from '../format'

const DAMAGE = ['destroyed', 'major', 'minor', 'affected', 'unknown'] as const
const DAMAGE_COLOR: Record<string, string> = {
  destroyed: '--danger',
  major: '--ember',
  minor: '--amber',
  affected: '--ink-soft',
  unknown: '--ink-faint',
}
// OpenStreetMap's own tiles (free with attribution, for light use like this); dark mode inverts them in CSS.
const TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'

const cssColor = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()
const darkQuery = () => window.matchMedia('(prefers-color-scheme: dark)')

function useDark() {
  const [dark, setDark] = useState(() => darkQuery().matches)
  useEffect(() => {
    const q = darkQuery()
    const on = (e: MediaQueryListEvent) => setDark(e.matches)
    q.addEventListener('change', on)
    return () => q.removeEventListener('change', on)
  }, [])
  return dark
}

/** A popup's content, built as DOM nodes so names from the database are never parsed as HTML. */
function card(lines: [string, string | null][]) {
  const box = document.createElement('div')
  lines.forEach(([text, strong], i) => {
    const p = document.createElement(i === 0 ? 'strong' : 'p')
    p.textContent = text
    if (strong) {
      const b = document.createElement('b')
      b.textContent = ` ${strong}`
      p.append(b)
    }
    p.style.margin = i === 0 ? '0 0 4px' : '0'
    p.style.display = 'block'
    box.append(p)
  })
  return box
}

/** The live map: the grid's households by damage, first-72-hours payments, crew visits, stores and the zones. */
export function CommandMap({ filterModel, tick }: { filterModel: Record<string, unknown>; tick: number }) {
  const { t } = useTranslation()
  const dark = useDark()
  const box = useRef<HTMLDivElement | null>(null)
  const map = useRef<L.Map | null>(null)
  const tiles = useRef<L.TileLayer | null>(null)
  const layers = useRef<Record<'zones' | 'households' | 'paid' | 'jobs' | 'stores', L.LayerGroup> | null>(null)
  const seenPaid = useRef<Set<number> | null>(null)
  const fitted = useRef(false)
  const svg = useRef<L.Renderer | null>(null) // the paid rings pulse, which needs SVG rather than the canvas
  const data = useQuery({
    queryKey: ['command-map', filterModel, tick],
    queryFn: () =>
      api<CommandMapData>('/command/map', { method: 'POST', body: JSON.stringify({ filter_model: filterModel }) }),
    placeholderData: (previous) => previous,
  })

  // The map itself, once
  useEffect(() => {
    if (!box.current || map.current) return
    const m = L.map(box.current, { preferCanvas: true, scrollWheelZoom: false })
    m.setView([38.709, -120.627], 13)
    m.on('focus click', () => m.scrollWheelZoom.enable())
    m.on('blur mouseout', () => m.scrollWheelZoom.disable())
    svg.current = L.svg()
    layers.current = {
      zones: L.layerGroup().addTo(m),
      households: L.layerGroup().addTo(m),
      jobs: L.layerGroup(),
      stores: L.layerGroup().addTo(m),
      paid: L.layerGroup().addTo(m),
    }
    map.current = m
    return () => {
      m.remove()
      map.current = null
    }
  }, [])

  // Tiles (dark mode inverts them with a CSS filter on the tile pane)
  useEffect(() => {
    const m = map.current
    if (!m) return
    tiles.current?.remove()
    tiles.current = L.tileLayer(TILES, { attribution: ATTRIBUTION, maxZoom: 19, className: 'map-tiles' }).addTo(m)
  }, [])

  // Layer names in the reader's language
  useEffect(() => {
    const m = map.current
    const l = layers.current
    if (!m || !l) return
    const control = L.control
      .layers(undefined, {
        [t('map.layer.households')]: l.households,
        [t('map.layer.paid')]: l.paid,
        [t('map.layer.jobs')]: l.jobs,
        [t('map.layer.stores')]: l.stores,
        [t('map.layer.zones')]: l.zones,
      })
      .addTo(m)
    return () => {
      control.remove()
    }
  }, [t])

  // The data
  useEffect(() => {
    const m = map.current
    const l = layers.current
    const d = data.data
    if (!m || !l || !d) return
    Object.values(l).forEach((layer) => layer.clearLayers())
    const color = Object.fromEntries(DAMAGE.map((k) => [k, cssColor(DAMAGE_COLOR[k])]))
    const sage = cssColor('--sage')
    const ink = cssColor('--ink')
    const surface = cssColor('--surface')

    for (const z of d.zones) {
      L.geoJSON(z.zone as GeoJSON.GeoJsonObject, {
        style: { color: cssColor('--ember'), weight: 2, fillColor: cssColor('--ember'), fillOpacity: 0.06 },
        interactive: false,
      }).addTo(l.zones)
    }
    const at = new Map<number, [number, number]>()
    for (const [id, lat, lng, damage] of d.households) {
      at.set(id, [lat, lng])
      const pin = L.circleMarker([lat, lng], {
        radius: 4,
        weight: 1,
        color: surface,
        fillColor: color[damage] ?? color.unknown,
        fillOpacity: 0.9,
      }).addTo(l.households)
      pin.bindPopup(card([[t('map.loading'), null]]))
      pin.on('popupopen', () => {
        void api<Record<string, string | number | boolean | string[] | null>>(`/command/map/households/${id}`).then(
          (h) =>
            pin.setPopupContent(
              card([
                [String(h.name), null],
                [String(h.address_line), null],
                [
                  `${t('command.col.damage')}:`,
                  t(`command.damage.${h.damage_level}`, { defaultValue: String(h.damage_level) }),
                ],
                [`${t('command.col.level')}:`, String(h.verification_level)],
                [`${t('command.col.unmet')}:`, money(String(h.unmet_need))],
                [`${t('command.col.help')}:`, money(String(h.help_received))],
              ]),
            ),
        )
      })
    }
    const before = seenPaid.current
    for (const p of d.paid) {
      const where = at.get(p.household_id)
      if (!where) continue
      const fresh = before !== null && !before.has(p.household_id)
      L.circleMarker(where, {
        radius: 8,
        weight: 2.5,
        color: sage,
        fill: false,
        className: fresh ? 'map-paid map-paid-new' : 'map-paid',
        renderer: svg.current ?? undefined,
        interactive: false,
      }).addTo(l.paid)
    }
    seenPaid.current = new Set(d.paid.map((p) => p.household_id))
    for (const j of d.jobs) {
      L.circleMarker([j.lat, j.lng], { radius: 2.5, weight: 0, fillColor: ink, fillOpacity: 0.9 })
        .bindTooltip(`${j.title} · ${j.crew ?? t('map.unassigned')}`)
        .addTo(l.jobs)
    }
    for (const b of d.businesses) {
      L.marker([b.lat, b.lng], {
        icon: L.divIcon({ className: `map-store map-store-${b.status}`, iconSize: [14, 14] }),
        title: b.name,
        keyboard: true,
      })
        .bindTooltip(`${b.name} · ${t(`map.store.${b.status}`)}`)
        .addTo(l.stores)
    }
    if (!fitted.current && d.zones.length) {
      m.fitBounds(L.geoJSON(d.zones[0].zone as GeoJSON.GeoJsonObject).getBounds(), { padding: [16, 16] })
      fitted.current = true
    }
  }, [data.data, dark, t])

  const d = data.data
  const counts = Object.fromEntries(DAMAGE.map((k) => [k, 0]))
  d?.households.forEach((h) => (counts[h[3]] = (counts[h[3]] ?? 0) + 1))
  const shown = new Set(d?.households.map((h) => h[0]))
  const paidShown = d?.paid.filter((p) => shown.has(p.household_id)).length ?? 0
  return (
    <section aria-labelledby="map-title" className="rounded-xl border border-line bg-surface p-4 shadow-sm">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="map-title" className="text-lg font-semibold">
          {t('map.title')}
        </h2>
        {d && (
          <p className="text-sm text-ink-soft" aria-live="polite">
            {t('map.summary', {
              count: d.households.length,
              n: d.households.length.toLocaleString(),
              paid: paidShown.toLocaleString(),
              jobs: d.jobs.length.toLocaleString(),
            })}
          </p>
        )}
      </div>
      <div
        ref={box}
        role="region"
        aria-label={t('map.label')}
        className="h-[18rem] w-full overflow-hidden rounded-lg border border-line sm:h-[26rem]"
      />
      <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-soft">
        {DAMAGE.filter((k) => counts[k]).map((k) => (
          <li key={k} className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: `var(${DAMAGE_COLOR[k]})` }} />
            {t(`command.damage.${k}`)} ({counts[k].toLocaleString()})
          </li>
        ))}
        <li className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-full border-2" style={{ borderColor: 'var(--sage)' }} />
          {t('map.legend.paid')}
        </li>
        <li className="flex items-center gap-1.5">
          <span className="map-store map-store-open inline-block h-3 w-3" />
          {t('map.legend.stores')}
        </li>
        <li className="text-ink-faint">{t('map.hint')}</li>
      </ul>
    </section>
  )
}
