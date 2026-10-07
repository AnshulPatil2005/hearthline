// On Render, VITE_API_HOST is the API service's hostname (set in render.yaml).
const host = import.meta.env.VITE_API_HOST as string | undefined

export const API_URL: string =
  (import.meta.env.VITE_API_URL as string | undefined) ?? (host ? `https://${host}` : 'http://localhost:8000')

const TOKEN_KEY = 'hearthline.token'

// Storage can be unavailable (private windows, blocked site data); the app still works per session.
let memoryToken: string | null = null
export const tokenStore = {
  get(): string | null {
    try {
      return localStorage.getItem(TOKEN_KEY) ?? memoryToken
    } catch {
      return memoryToken
    }
  },
  set(token: string | null) {
    memoryToken = token
    try {
      if (token) localStorage.setItem(TOKEN_KEY, token)
      else localStorage.removeItem(TOKEN_KEY)
    } catch {
      /* keep the in-memory copy */
    }
  },
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const token = tokenStore.get()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const res = await fetch(`${API_URL}${path}`, { ...init, headers })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const detail = typeof body?.detail === 'string' ? body.detail : res.statusText
    throw new ApiError(res.status, detail)
  }
  return (res.status === 204 ? undefined : await res.json()) as T
}

export const mediaUrl = (path: string | null) => (path ? `${API_URL}${path}` : null)

export type Role = 'household' | 'donor' | 'contractor' | 'reviewer' | 'supervisor' | 'org_admin' | 'business'

export type User = {
  id: number
  name: string
  email: string
  role: Role
  title: string | null
  locale: string
  household_id: number | null
}

export type Disaster = { id: number; slug: string; name: string; kind: string; status: string; is_fictional: boolean }

export type Household = {
  id: number
  name: string
  address_line: string
  city: string
  state: string
  postal_code: string
  lat: number | null
  lng: number | null
  insured_contents_value: string | null
  verification_level: number
  disaster_event: Disaster | null
  in_disaster_zone: boolean
}

export type RoomTotal = { room_id: number | null; room_name: string; item_count: number; total_value: string }

export type InventorySummary = {
  item_count: number
  confirmed_count: number
  unpriced_count: number
  total_value: string
  insured_contents_value: string | null
  coverage_gap: string | null
  by_room: RoomTotal[]
}

export type Room = { id: number; name: string }

export type Scan = {
  id: number
  room_id: number
  status: 'queued' | 'processing' | 'done' | 'failed'
  error: string | null
  photo_count: number
  item_count: number
}

export type EvidenceLevel = 'pre_disaster_scan' | 'photo' | 'receipt' | 'memory'

export type Item = {
  id: number
  room_id: number | null
  room_name: string | null
  name: string
  category: string
  quantity: number
  brand: string | null
  condition: string | null
  ai_confidence: number | null
  unit_price: string | null
  price_low: string | null
  price_high: string | null
  total_value: string | null
  price_source: string | null
  match_title: string | null
  match_url: string | null
  retailer: string | null
  offers_considered: number
  evidence_level: EvidenceLevel
  confirmed: boolean
  user_edited: boolean
  photo_url: string | null
}

export const CATEGORIES = [
  'furniture', 'electronics', 'appliance', 'lighting', 'bedding', 'decor', 'kitchenware',
  'clothing', 'books', 'toys', 'tools', 'sports', 'musical', 'other',
] as const

export type RegistryItem = {
  id: number
  name: string
  note: string
  category: string
  quantity: number
  unit_price: string
  target_amount: string
  funded_amount: string
  remaining: string
  status: 'open' | 'funded' | 'purchased' | 'delivered'
  priority: number
  retailer: string | null
  match_url: string | null
}

export type PublicDonation = {
  id: number
  donor_name: string | null
  message: string
  amount: string
  payment_method: string
  item_name: string | null
  captured_at: string | null
}

export type Registry = {
  slug: string
  title: string
  story: string
  status: string
  household_name: string
  city: string
  state: string
  disaster_name: string | null
  items: RegistryItem[]
  total_target: string
  total_funded: string
  donor_count: number
  recent_donations: PublicDonation[]
}

export type Fund = { available: string; donated: string; spent: string }

export type PolicyCheck = { rule: string; passed: boolean; detail: string }

export type Purchase = {
  id: number
  registry_item_id: number | null
  title: string
  retailer: string
  url: string | null
  unit_price: string
  quantity: number
  total: string
  status: 'proposed' | 'awaiting_approval' | 'approved' | 'paid' | 'shipped' | 'delivered' | 'blocked' | 'rejected' | 'failed'
  policy_checks: PolicyCheck[]
  ai_reasoning: string
  ai_confidence: number | null
  candidates_considered: number
  payment_rail: string
  paypal_ref: string | null
  carrier: string | null
  tracking_number: string | null
  error: string | null
  created_at: string
  paid_at: string | null
}
