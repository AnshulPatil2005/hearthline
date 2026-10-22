import type { GeoJsonGeometry } from '../api'

type Ring = number[][]

function rings(zone: GeoJsonGeometry): Ring[] {
  if (zone.type === 'Polygon') return zone.coordinates as Ring[]
  if (zone.type === 'MultiPolygon') return (zone.coordinates as Ring[][]).flat()
  return []
}

function bounds(all: Ring[]): [number, number, number, number] {
  let [minX, maxX, minY, maxY] = [Infinity, -Infinity, Infinity, -Infinity]
  for (const ring of all)
    for (const [x, y] of ring) {
      minX = Math.min(minX, x)
      maxX = Math.max(maxX, x)
      minY = Math.min(minY, y)
      maxY = Math.max(maxY, y)
    }
  return [minX, maxX, minY, maxY]
}

/** A disaster zone's outline, drawn from its GeoJSON (no map tiles): enough to see what a declaration covers. */
export function ZoneShape({
  zone,
  label,
  className = '',
}: {
  zone: GeoJsonGeometry
  label: string
  className?: string
}) {
  let all = rings(zone)
  if (!all.length) return null
  // A zone across the date line (western Alaska): keep it in one piece.
  if (bounds(all)[1] - bounds(all)[0] > 180) all = all.map((r) => r.map(([x, y]) => [x < 0 ? x + 360 : x, y]))
  const [minX, maxX, minY, maxY] = bounds(all)
  // Longitude degrees shrink toward the poles; scale them so the shape isn't stretched.
  const k = Math.cos((((minY + maxY) / 2) * Math.PI) / 180)
  const width = Math.max((maxX - minX) * k, 0.01)
  const height = Math.max(maxY - minY, 0.01)
  const pad = Math.max(width, height) * 0.06
  const d = all
    .map(
      (ring) =>
        'M' +
        ring.map(([x, y]) => `${((x - minX) * k + pad).toFixed(4)},${(maxY - y + pad).toFixed(4)}`).join('L') +
        'Z',
    )
    .join('')
  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${(width + 2 * pad).toFixed(4)} ${(height + 2 * pad).toFixed(4)}`}
      preserveAspectRatio="xMidYMid meet"
      className={`rounded-lg bg-sunken ${className}`}
    >
      <path
        d={d}
        fill="var(--ember-soft)"
        stroke="var(--ember)"
        strokeWidth={1.5}
        strokeLinejoin="round"
        fillRule="evenodd"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}
