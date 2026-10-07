import i18n from './i18n'

export function money(value: string | number | null | undefined, opts: { cents?: boolean } = {}): string {
  if (value === null || value === undefined || value === '') return '—'
  const digits = opts.cents ? 2 : 0
  return new Intl.NumberFormat(i18n.resolvedLanguage ?? 'en', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(Number(value))
}
