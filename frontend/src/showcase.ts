import { API_URL } from './api'

/** What a judge can open, and as whom: every feature in the demo, one click away (texts in `showcase.*`). */
export type Feature = {
  key: string
  /** The persona the link signs in as (an email prefix); none for public pages. */
  as?: 'elena.rivera' | 'marcus.chen' | 'dana.okafor' | 'priya.nair' | 'sam.whitfield' | 'luis.moreno' | 'rosa.delgado'
  to: string
  /** Proper names, shown as they are: PayPal APIs, AI agents, sponsor tools, public data. */
  tags: string[]
}

export const FEATURE_GROUPS: { key: string; features: Feature[] }[] = [
  {
    key: 'prepare',
    features: [
      { key: 'inventory', as: 'elena.rivera', to: '/inventory', tags: ['Inventory agent', 'Channel3', 'AG Grid'] },
      { key: 'policy', as: 'elena.rivera', to: '/insurance', tags: ['Policy agent'] },
      { key: 'readiness', as: 'marcus.chen', to: '/giving', tags: ['PayPal Subscriptions'] },
      { key: 'navigator', as: 'elena.rivera', to: '/home', tags: ['Navigator agent', 'Voice'] },
    ],
  },
  {
    key: 'respond',
    features: [
      { key: 'first72', as: 'sam.whitfield', to: '/command', tags: ['PayPal Payouts', 'Sentinel agent', 'NWS + FEMA'] },
      { key: 'registry', to: '/r/rivera-family', tags: ['PayPal Orders', 'Venmo', 'Pay Later'] },
      { key: 'abroad', to: '/r/rivera-family', tags: ['PayPal Orders', 'MXN · PHP · EUR · CAD · GBP'] },
      { key: 'shopper', as: 'elena.rivera', to: '/registry', tags: ['Shopper agent', 'Channel3', 'PayPal Payouts'] },
      { key: 'marketplace', as: 'rosa.delgado', to: '/business', tags: ['Store pricing agents', 'MCP'] },
      { key: 'mandates', as: 'marcus.chen', to: '/giving', tags: ['PayPal Vault', 'Giving agent'] },
    ],
  },
  {
    key: 'trust',
    features: [
      { key: 'scam', as: 'priya.nair', to: '/review', tags: ['Sentinel agent', 'PayPal refunds'] },
      { key: 'review', as: 'priya.nair', to: '/review/calendar', tags: ['AG Grid', 'Bryntum Calendar'] },
      { key: 'disputes', as: 'sam.whitfield', to: '/command/disputes', tags: ['PayPal Disputes', 'Funds agent'] },
      {
        key: 'books',
        as: 'sam.whitfield',
        to: '/command/books',
        tags: ['Transaction Search', 'APIMatic SDK', 'PayPal MCP'],
      },
    ],
  },
  {
    key: 'rebuild',
    features: [
      { key: 'claim', as: 'elena.rivera', to: '/insurance', tags: ['PayPal Orders', 'AG Grid'] },
      {
        key: 'milestones',
        as: 'dana.okafor',
        to: '/contractor',
        tags: ['PayPal Payouts', 'Site agent', 'Bryntum Gantt'],
      },
      { key: 'whatif', as: 'dana.okafor', to: '/contractor', tags: ['Bryntum Gantt'] },
      { key: 'reopen', to: '/reopen/morenos-bakery', tags: ['PayPal Subscriptions', 'Bryntum Gantt'] },
      { key: 'pricewatch', to: '/price-watch', tags: ['Channel3', 'AG Grid'] },
    ],
  },
  {
    key: 'run',
    features: [
      { key: 'command', as: 'sam.whitfield', to: '/command', tags: ['AG Grid', 'AI Toolkit'] },
      { key: 'map', as: 'sam.whitfield', to: '/command', tags: ['Leaflet', 'OpenStreetMap'] },
      { key: 'batch', as: 'sam.whitfield', to: '/command', tags: ['PayPal Payouts', 'AG Grid'] },
      { key: 'dispatch', as: 'sam.whitfield', to: '/command/crews', tags: ['Dispatch agent', 'Bryntum Scheduler Pro'] },
      { key: 'disasters', as: 'sam.whitfield', to: '/command/disasters', tags: ['OpenFEMA', 'NWS', 'Census'] },
      { key: 'pipeline', as: 'priya.nair', to: '/review/board', tags: ['Bryntum TaskBoard'] },
      { key: 'grant', as: 'sam.whitfield', to: '/command', tags: ['Funds agent', 'PDF'] },
      { key: 'api', to: `${API_URL}/docs`, tags: ['Public API', 'MCP server'] },
    ],
  },
]

export const FEATURE_COUNT = FEATURE_GROUPS.reduce((n, g) => n + g.features.length, 0)

/** Where a feature opens: signed in as its persona, or the public page itself. */
export const featureHref = (f: Feature) => (f.as ? `/login?as=${f.as}&next=${encodeURIComponent(f.to)}` : f.to)

/** How each sponsor's tool is used, with a link to each use (texts in `showcase.sponsor.*`). */
export type Sponsor = {
  key: string
  name: string
  /** Numbers that show the depth of use; labels are in `showcase.sponsor.<key>.facts.<i>`. */
  facts: string[]
  uses: { key: string; href: string }[]
}

const as = (persona: string, to: string) => `/login?as=${persona}&next=${encodeURIComponent(to)}`

export const SPONSORS: Sponsor[] = [
  {
    key: 'paypal',
    name: 'PayPal',
    facts: ['11', '6', '3'],
    uses: [
      { key: 'orders', href: '/r/rivera-family' },
      { key: 'payouts', href: as('sam.whitfield', '/command') },
      { key: 'subscriptions', href: as('marcus.chen', '/giving') },
      { key: 'vault', href: as('marcus.chen', '/giving') },
      { key: 'disputes', href: as('sam.whitfield', '/command/disputes') },
      { key: 'reporting', href: as('sam.whitfield', '/command/books') },
      { key: 'login', href: as('dana.okafor', '/contractor') },
      { key: 'mcp', href: as('sam.whitfield', '/command/books') },
    ],
  },
  {
    key: 'aggrid',
    name: 'AG Grid Enterprise',
    facts: ['11', '2,005', '26'],
    uses: [
      { key: 'ssrm', href: as('sam.whitfield', '/command') },
      { key: 'toolkit', href: as('sam.whitfield', '/command') },
      { key: 'grouping', href: as('elena.rivera', '/inventory') },
      { key: 'masterDetail', href: as('elena.rivera', '/money') },
      { key: 'sparklines', href: '/price-watch' },
      { key: 'map', href: as('sam.whitfield', '/command') },
    ],
  },
  {
    key: 'bryntum',
    name: 'Bryntum',
    facts: ['5', '4', '1'],
    uses: [
      { key: 'gantt', href: as('dana.okafor', '/contractor') },
      { key: 'scheduler', href: as('sam.whitfield', '/command/crews') },
      { key: 'utilization', href: as('sam.whitfield', '/command/crews') },
      { key: 'calendar', href: as('priya.nair', '/review/calendar') },
      { key: 'taskboard', href: as('priya.nair', '/review/board') },
      { key: 'crud', href: as('luis.moreno', '/business') },
    ],
  },
  {
    key: 'channel3',
    name: 'Channel3',
    facts: ['3', '17'],
    uses: [
      { key: 'valuation', href: as('elena.rivera', '/inventory') },
      { key: 'shopper', href: as('elena.rivera', '/registry') },
      { key: 'history', href: '/price-watch' },
    ],
  },
  {
    key: 'apimatic',
    name: 'APIMatic',
    facts: ['3', '1'],
    uses: [
      { key: 'sdk', href: '/r/rivera-family' },
      { key: 'vault', href: as('marcus.chen', '/giving') },
      { key: 'reporting', href: as('sam.whitfield', '/command/books') },
      { key: 'plugin', href: 'https://github.com/AnshulPatil2005/hearthline-paypal-apimatic' },
      { key: 'openapi', href: `${API_URL}/docs` },
    ],
  },
  {
    key: 'render',
    name: 'Render',
    facts: ['2', '1'],
    uses: [
      { key: 'blueprint', href: 'https://github.com/AnshulPatil2005/hearthline/blob/main/render.yaml' },
      { key: 'reset', href: '/login#reset' },
    ],
  },
]
