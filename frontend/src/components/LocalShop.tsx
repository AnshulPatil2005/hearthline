import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type LocalOrder, type LocalShop as Shop } from '../api'
import { money, parseTime } from '../format'

const CATEGORIES = [
  'bedding',
  'furniture',
  'clothing',
  'kitchenware',
  'electronics',
  'appliance',
  'tools',
  'toys',
  'other',
]

/** Orders Hearthline's Shopper placed (already paid through PayPal), for the store to deliver. */
function Orders() {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const orders = useQuery({ queryKey: ['local-orders'], queryFn: () => api<LocalOrder[]>('/businesses/me/orders') })
  const deliver = useMutation({
    mutationFn: (id: number) => api<LocalOrder[]>(`/businesses/me/orders/${id}/delivered`, { method: 'POST' }),
    onSuccess: (r) => queryClient.setQueryData(['local-orders'], r),
  })
  if (!orders.data?.length) return null
  return (
    <section className="panel p-5">
      <h2 className="text-lg font-semibold">{t('localShop.ordersTitle')}</h2>
      <p className="mt-1 text-sm text-ink-soft">{t('localShop.ordersBody')}</p>
      <ul className="mt-3 divide-y divide-line">
        {orders.data.map((o) => (
          <li key={o.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
            <div className="min-w-0 text-sm">
              <p className="font-medium">
                {o.quantity > 1 ? `${o.quantity} × ` : ''}
                {o.title} · {money(o.total, { cents: true })}
              </p>
              <p className="text-ink-soft">{t('localShop.forFamily', { family: o.family })}</p>
              {o.list_price && (
                <p className="text-xs text-ink-faint">
                  {t(o.negotiated ? 'localShop.negotiated' : 'localShop.discounted', {
                    list: money(o.list_price, { cents: true }),
                  })}
                </p>
              )}
              <p className="text-ink-soft">
                {t('localShop.contact', { name: o.contact_name })}{' '}
                {o.contact_email && (
                  <a href={`mailto:${o.contact_email}`} className="text-ember hover:underline">
                    {o.contact_email}
                  </a>
                )}
              </p>
              {o.paid_at && (
                <p className="text-xs text-ink-faint">
                  {t('localShop.paidOn', {
                    date: parseTime(o.paid_at).toLocaleDateString(i18n.resolvedLanguage, { dateStyle: 'medium' }),
                  })}
                </p>
              )}
            </div>
            {o.status === 'delivered' ? (
              <span className="rounded-full bg-sage-soft px-2.5 py-0.5 text-xs font-medium text-sage">
                {t('localShop.delivered')}
              </span>
            ) : (
              <button
                onClick={() => deliver.mutate(o.id)}
                disabled={deliver.isPending}
                className="rounded-lg bg-ember px-3 py-1.5 text-sm font-medium text-on-ember disabled:opacity-40"
              >
                {t('localShop.markDelivered')}
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}

/** What the store sells to families: the Shopper buys here before web stores when the price is close. */
function Catalog() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const shop = useQuery({ queryKey: ['local-shop'], queryFn: () => api<Shop>('/businesses/me/offers') })
  const [title, setTitle] = useState('')
  const [category, setCategory] = useState('bedding')
  const [price, setPrice] = useState('')
  const [error, setError] = useState<string | null>(null)
  const save = (r: Shop) => {
    queryClient.setQueryData(['local-shop'], r)
    setError(null)
  }
  const onError = (e: Error) => setError(e instanceof ApiError ? e.message : t('errors.generic'))
  const add = useMutation({
    mutationFn: () =>
      api<Shop>('/businesses/me/offers', {
        method: 'POST',
        body: JSON.stringify({ title, category, unit_price: price }),
      }),
    onSuccess: (r) => {
      save(r)
      setTitle('')
      setPrice('')
    },
    onError,
  })
  const toggle = useMutation({
    mutationFn: ({ id, available }: { id: number; available: boolean }) =>
      api<Shop>(`/businesses/me/offers/${id}`, { method: 'PATCH', body: JSON.stringify({ available }) }),
    onSuccess: save,
    onError,
  })
  const remove = useMutation({
    mutationFn: (id: number) => api<Shop>(`/businesses/me/offers/${id}`, { method: 'DELETE' }),
    onSuccess: save,
    onError,
  })
  const patch = useMutation({
    mutationFn: ({ id, ...body }: { id: number; stock?: number; floor_price?: string }) =>
      api<Shop>(`/businesses/me/offers/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
    onSuccess: save,
    onError,
  })
  const [note, setNote] = useState<string | null>(null)
  const saveNote = useMutation({
    mutationFn: () => api<Shop>('/businesses/me/agent', { method: 'PUT', body: JSON.stringify({ note: note ?? '' }) }),
    onSuccess: (r) => {
      save(r)
      setNote(null)
    },
    onError,
  })
  const s = shop.data
  if (!s) return null
  return (
    <section className="panel p-5">
      <h2 className="text-lg font-semibold">{t('localShop.catalogTitle')}</h2>
      <p className="mt-1 text-sm text-ink-soft">{t('localShop.catalogBody')}</p>
      {!s.open && <p className="mt-2 rounded-lg bg-amber-soft px-3 py-2 text-sm">{t('localShop.notOpen')}</p>}
      <div className="mt-3 rounded-lg bg-sunken p-3 text-sm">
        <label htmlFor="agent-note" className="font-medium">
          {t('localShop.agentNote')}
        </label>
        <p className="text-xs text-ink-faint">{t('localShop.agentNoteHint')}</p>
        <div className="mt-2 flex flex-wrap gap-2">
          <input
            id="agent-note"
            value={note ?? s.agent_note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={280}
            placeholder={t('localShop.agentNotePlaceholder')}
            className="min-w-48 flex-1 rounded-lg border border-line bg-surface px-3 py-2"
          />
          <button
            onClick={() => saveNote.mutate()}
            disabled={note === null || saveNote.isPending}
            className="rounded-lg border border-line px-3 py-2 hover:bg-surface disabled:opacity-40"
          >
            {t('localShop.saveNote')}
          </button>
        </div>
      </div>
      {s.offers.length > 0 && (
        <ul className="mt-3 divide-y divide-line text-sm">
          {s.offers.map((o) => (
            <li key={o.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span
                className={`min-w-0 basis-full sm:basis-0 sm:flex-1 ${o.available ? '' : 'text-ink-faint line-through'}`}
              >
                {o.title} · {t(`localShop.category.${o.category}`, { defaultValue: o.category })} ·{' '}
                {money(o.unit_price, { cents: true })}
              </span>
              <span className="flex flex-wrap items-center gap-2 text-xs text-ink-soft">
                <label className="flex items-center gap-1">
                  {t('localShop.lowest')}
                  <input
                    type="number"
                    min={1}
                    step="0.01"
                    defaultValue={o.floor_price ?? o.unit_price}
                    onBlur={(e) => {
                      const v = e.target.value
                      if (v && v !== (o.floor_price ?? o.unit_price)) patch.mutate({ id: o.id, floor_price: v })
                    }}
                    className="w-20 rounded border border-line bg-surface px-1.5 py-0.5"
                  />
                </label>
                <label className="flex items-center gap-1">
                  {t('localShop.stock')}
                  <input
                    type="number"
                    min={0}
                    step="1"
                    defaultValue={o.stock}
                    onBlur={(e) => {
                      const v = Number(e.target.value)
                      if (Number.isInteger(v) && v !== o.stock) patch.mutate({ id: o.id, stock: v })
                    }}
                    className="w-14 rounded border border-line bg-surface px-1.5 py-0.5"
                  />
                </label>
              </span>
              <span className="flex gap-3 text-xs">
                <button
                  onClick={() => toggle.mutate({ id: o.id, available: !o.available })}
                  className="text-ink-soft hover:underline"
                >
                  {o.available ? t('localShop.soldOut') : t('localShop.inStock')}
                </button>
                <button onClick={() => remove.mutate(o.id)} className="text-danger hover:underline">
                  {t('localShop.remove')}
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          add.mutate()
        }}
        className="mt-3 flex flex-wrap gap-2"
      >
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={t('localShop.itemPlaceholder')}
          aria-label={t('localShop.item')}
          maxLength={200}
          className="min-w-48 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm"
        />
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          aria-label={t('localShop.categoryLabel')}
          className="rounded-lg border border-line bg-surface px-3 py-2 text-sm"
        >
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {t(`localShop.category.${c}`)}
            </option>
          ))}
        </select>
        <input
          value={price}
          onChange={(e) => setPrice(e.target.value)}
          type="number"
          min={1}
          step="0.01"
          placeholder={t('localShop.price')}
          aria-label={t('localShop.price')}
          className="w-28 rounded-lg border border-line bg-surface px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={add.isPending || title.trim().length < 2 || !(Number(price) > 0)}
          className="rounded-lg border border-line px-3 py-2 text-sm hover:bg-sunken disabled:opacity-40"
        >
          {t('localShop.add')}
        </button>
      </form>
      {error && <p className="mt-2 text-sm text-danger">{error}</p>}
    </section>
  )
}

export function LocalShop() {
  return (
    <>
      <Orders />
      <Catalog />
    </>
  )
}
