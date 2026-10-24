import i18n from './i18n'

export function money(
  value: string | number | null | undefined,
  opts: { cents?: boolean; currency?: string } = {},
): string {
  if (value === null || value === undefined || value === '') return '—'
  const digits = opts.cents ? 2 : 0
  return new Intl.NumberFormat(i18n.resolvedLanguage ?? 'en', {
    style: 'currency',
    currency: opts.currency ?? 'USD',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(Number(value))
}

/** An API timestamp as a Date. Postgres sends UTC with a zone ("…Z"); SQLite sends none, which is also UTC. */
export function parseTime(iso: string): Date {
  return new Date(/(Z|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`)
}
