import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, ApiError, type Fund, type Household, type Item, type Registry } from '../api'
import PurchaseList from '../components/PurchaseList'
import { money } from '../format'

function CreateRegistry({ home }: { home: Household }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [title, setTitle] = useState(t('registry.defaultTitle', { name: home.name.replace(/ household$/i, '') }))
  const [story, setStory] = useState('')
  const create = useMutation({
    mutationFn: () => api('/households/me/registry', { method: 'POST', body: JSON.stringify({ title, story }) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['my-registry'] }),
  })
  return (
    <section className="max-w-2xl panel p-5">
      <h2 className="text-lg font-semibold">{t('registry.createTitle')}</h2>
      <p className="mt-1 text-sm text-ink-soft">{t('registry.createBody')}</p>
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        className="mt-4 w-full rounded-lg border border-line bg-surface px-3 py-2"
      />
      <textarea
        value={story}
        onChange={(e) => setStory(e.target.value)}
        rows={5}
        placeholder={t('registry.storyPlaceholder')}
        className="mt-3 w-full rounded-lg border border-line bg-surface px-3 py-2"
      />
      <button
        onClick={() => create.mutate()}
        disabled={title.trim().length < 3 || create.isPending}
        className="mt-3 rounded-lg bg-ember px-4 py-2 text-sm font-medium text-on-ember disabled:opacity-40"
      >
        {t('registry.create')}
      </button>
    </section>
  )
}

function AddItem({ onAdded }: { onAdded: () => void }) {
  const { t } = useTranslation()
  const inventory = useQuery({ queryKey: ['items'], queryFn: () => api<Item[]>('/households/me/items') })
  const [fromInventory, setFromInventory] = useState('')
  const [name, setName] = useState('')
  const [price, setPrice] = useState('')
  const [quantity, setQuantity] = useState(1)
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function add() {
    setError(null)
    const body = fromInventory
      ? { inventory_item_id: Number(fromInventory), note }
      : { name, unit_price: price, quantity, note }
    try {
      await api('/households/me/registry/items', { method: 'POST', body: JSON.stringify(body) })
      setFromInventory('')
      setName('')
      setPrice('')
      setQuantity(1)
      setNote('')
      onAdded()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('errors.generic'))
    }
  }

  const priced = inventory.data?.filter((i) => i.unit_price) ?? []
  return (
    <section className="panel p-5">
      <h2 className="font-semibold">{t('registry.addTitle')}</h2>
      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {priced.length > 0 && (
            <select
              value={fromInventory}
              onChange={(e) => setFromInventory(e.target.value)}
              aria-label={t('a11y.pickItem')}
              className="w-full min-w-0 rounded-lg border border-line bg-surface px-3 py-2 text-sm sm:col-span-2"
            >
              <option value="">{t('registry.custom')}</option>
              {priced.map((i) => (
                <option key={i.id} value={i.id}>
                  {t('registry.fromInventory', { name: i.name, price: money(i.unit_price, { cents: true }) })}
                </option>
              ))}
            </select>
          )}
          {!fromInventory && (
            <>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t('registry.itemName')}
                className="rounded-lg border border-line bg-surface px-3 py-2 text-sm"
              />
              <div className="flex gap-2">
                <input
                  value={price}
                  onChange={(e) => setPrice(e.target.value)}
                  type="number"
                  min={1}
                  placeholder={t('registry.price')}
                  className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm"
                />
                <input
                  value={quantity}
                  onChange={(e) => setQuantity(Number(e.target.value))}
                  type="number"
                  min={1}
                  aria-label={t('inventory.col.qty')}
                  className="w-20 rounded-lg border border-line bg-surface px-3 py-2 text-sm"
                />
              </div>
            </>
          )}
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={t('registry.notePlaceholder')}
            className="rounded-lg border border-line bg-surface px-3 py-2 text-sm sm:col-span-2"
          />
        </div>
        <button
          onClick={() => void add()}
          disabled={!fromInventory && (!name || !price)}
          className="rounded-lg bg-ember px-4 py-2 text-sm font-medium text-on-ember disabled:opacity-40"
        >
          {t('registry.add')}
        </button>
      </div>
      {error && <p className="mt-2 text-sm text-danger">{error}</p>}
    </section>
  )
}

export default function RegistryManage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [copied, setCopied] = useState(false)
  const home = useQuery({ queryKey: ['household'], queryFn: () => api<Household>('/households/me') })
  const registry = useQuery({
    queryKey: ['my-registry'],
    queryFn: () => api<Registry>('/households/me/registry'),
    retry: (count, e) => !(e instanceof ApiError && e.status === 404) && count < 1,
  })
  const fund = useQuery({ queryKey: ['fund'], queryFn: () => api<Fund>('/households/me/fund') })
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['my-registry'] })
    void queryClient.invalidateQueries({ queryKey: ['fund'] })
  }
  const shop = useMutation({
    mutationFn: (id: number) => api(`/households/me/registry/items/${id}/shop`, { method: 'POST' }),
    onSuccess: () => {
      refresh()
      void queryClient.invalidateQueries({ queryKey: ['purchases'] })
    },
  })
  const remove = useMutation({
    mutationFn: (id: number) => api(`/households/me/registry/items/${id}`, { method: 'DELETE' }),
    onSuccess: refresh,
  })

  const missing = registry.error instanceof ApiError && registry.error.status === 404
  const reg = registry.data
  const publicUrl = reg ? `${window.location.origin}/r/${reg.slug}` : ''

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-4xl leading-tight tracking-tight text-balance">{t('registry.manageTitle')}</h1>
        <p className="mt-1 text-ink-soft">{t('registry.manageSubtitle')}</p>
      </div>

      {missing && home.data && <CreateRegistry home={home.data} />}

      {reg && (
        <>
          <section className="flex flex-wrap items-center gap-3 panel p-4">
            <span className="text-sm text-ink-soft">{t('registry.shareLink')}</span>
            <code className="rounded bg-sunken px-2 py-1 text-sm">{publicUrl}</code>
            <button
              onClick={() => {
                void navigator.clipboard?.writeText(publicUrl).then(() => setCopied(true))
              }}
              className="rounded-md border border-line px-3 py-1 text-sm hover:bg-sunken"
            >
              {copied ? t('registry.copied') : t('registry.copy')}
            </button>
            <Link to={`/r/${reg.slug}`} target="_blank" className="text-sm font-medium text-ember hover:underline">
              {t('registry.viewAsDonor')} ↗
            </Link>
          </section>

          {fund.data && (
            <dl className="grid gap-3 sm:grid-cols-3">
              {(['donated', 'spent', 'available'] as const).map((k) => (
                <div key={k} className="rounded-lg border border-line bg-surface px-4 py-3">
                  <dt className="kicker text-ink-faint">{t(`registry.fund.${k}`)}</dt>
                  <dd className="figure mt-0.5 text-2xl font-semibold">{money(fund.data[k], { cents: true })}</dd>
                </div>
              ))}
            </dl>
          )}

          <PurchaseList />

          <section className="panel">
            <ul className="divide-y divide-line">
              {reg.items.map((i) => (
                <li key={i.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                  <div className="min-w-48 flex-1">
                    <div className="font-medium">
                      {i.name} {i.quantity > 1 && <span className="text-ink-faint">× {i.quantity}</span>}
                    </div>
                    {i.note && <div className="text-sm text-ink-faint">{i.note}</div>}
                  </div>
                  <span className="text-sm tabular-nums text-ink-soft">
                    {t('registry.raisedOf', { raised: money(i.funded_amount), target: money(i.target_amount) })}
                  </span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${i.status === 'open' ? 'bg-sunken text-ink-soft' : 'bg-sage-soft text-sage'}`}
                  >
                    {t(`registry.status.${i.status}`)}
                  </span>
                  {i.status === 'funded' && (
                    <button
                      onClick={() => shop.mutate(i.id)}
                      disabled={shop.isPending}
                      className="rounded-md border border-ember px-2.5 py-1 text-sm font-medium text-ember hover:bg-ember-soft disabled:opacity-40"
                    >
                      {t('registry.shopNow')}
                    </button>
                  )}
                  {Number(i.funded_amount) === 0 && (
                    <button onClick={() => remove.mutate(i.id)} className="text-sm text-ink-faint hover:text-danger">
                      {t('registry.remove')}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </section>

          <AddItem onAdded={refresh} />
        </>
      )}
    </div>
  )
}
