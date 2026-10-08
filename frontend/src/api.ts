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

export type LedgerPosting = { account_code: string; account_name: string; amount: string }

export type LedgerRow = {
  id: number
  kind: string
  description: string
  created_at: string
  paypal_ref: string | null
  amount: string
  balance: string
  postings: LedgerPosting[]
}

export type RiskTier = 'low' | 'medium' | 'high'

export type QueueRow = {
  id: number
  kind: 'cash_aid' | 'registry_verification' | 'contents_claim'
  title: string
  household_id: number
  household_name: string
  city: string
  amount_requested: string
  status: 'in_review' | 'needs_info' | 'escalated' | 'approved' | 'rejected'
  risk_score: number
  risk_tier: RiskTier
  flag_count: number
  required_reviews: number
  reviews_done: number
  video_call_required: boolean
  my_role: string | null
  awaiting_me: boolean
  created_at: string
}

export type CaseFlag = { code: string; severity: 'low' | 'medium' | 'high'; message: string; evidence: Record<string, unknown> }

export type CaseDetail = QueueRow & {
  note: string
  flags: CaseFlag[]
  sentinel_summary: string
  sentinel_questions: string[]
  sentinel_recommendation: string | null
  random_audit: boolean
  decision_note: string | null
  paypal_ref: string | null
  address: string
  lat: number | null
  lng: number | null
  in_disaster_zone: boolean
  verification_level: number
  payout_email: string | null
  vouch_note: string | null
  inventory_items: number
  inventory_value: string
  registry_slug: string | null
  photos: { media_id: number; url: string; captured_at: string | null }[]
  reviews: { reviewer_name: string; role: string; decision: string; reason: string; created_at: string }[]
  reviewers: string[]
  milestone: MilestoneEvidence | null
}

export type Verification = {
  level: number
  level_name: string
  in_disaster_zone: boolean
  residence_verified: boolean
  vouched: boolean
  next_step: 'address_outside_zone' | 'confirm_residence' | 'scan_before_disaster' | null
}

export type HouseholdCase = {
  id: number
  kind: 'cash_aid' | 'registry_verification' | 'contents_claim' | 'milestone_payment' | 'contractor_dispute'
  title: string
  amount_requested: string
  status: 'in_review' | 'needs_info' | 'escalated' | 'approved' | 'rejected'
  video_call_required: boolean
  decision_note: string | null
  created_at: string
  decided_at: string | null
}

export type SiteCheck = {
  verdict: 'matches' | 'partial' | 'does_not_match' | 'unchecked'
  confidence: number
  observations: string[]
  concerns: string[]
  metadata_concerns?: string[]
}

export type MilestoneStatus = 'pending' | 'submitted' | 'under_review' | 'paid' | 'disputed' | 'refunded'

export type Milestone = {
  id: number
  seq: number
  title: string
  done_looks_like: string
  amount: string
  is_deposit: boolean
  start_date: string
  end_date: string
  status: MilestoneStatus
  site_check: SiteCheck | null
  case_id: number | null
  paypal_ref: string | null
  submitted_at: string | null
  paid_at: string | null
  photo_urls: string[]
  needs_human_review: boolean
}

export type Contractor = {
  id: number
  business_name: string
  license_number: string
  license_state: string
  license_verified: boolean
}

export type Project = {
  id: number
  title: string
  status: 'awaiting_plan' | 'plan_submitted' | 'active' | 'completed'
  total_price: string
  household_name: string
  contractor: Contractor
  deposit_cap: string
  escrow_balance: string
  milestones: Milestone[]
}

export type MilestoneEvidence = Pick<
  Milestone,
  'id' | 'seq' | 'title' | 'done_looks_like' | 'amount' | 'start_date' | 'end_date' | 'status' | 'site_check' | 'photo_urls'
> & { project_id: number; project_title: string; contractor_name: string; license_number: string }

export type DamageLevel = 'destroyed' | 'major' | 'minor' | 'affected' | 'unknown'

export type CommandRow = {
  id: number
  name: string
  address_line: string
  street: string | null
  damage_level: DamageLevel
  household_size: number
  verification_level: number
  needs: string[]
  estimated_loss: string | null
  help_received: string
  unmet_need: string
  payout_ready: boolean
  registered: string
  help_trend: number[]
}

export type CommandSummary = {
  households: number
  destroyed: number
  verified: number
  help_received: string
  unmet_need: string
}
