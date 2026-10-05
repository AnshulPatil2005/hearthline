// On Render, VITE_API_HOST is the API service's hostname (set in render.yaml).
const host = import.meta.env.VITE_API_HOST as string | undefined

export const API_URL: string =
  (import.meta.env.VITE_API_URL as string | undefined) ??
  (host ? `https://${host}` : 'http://localhost:8000')
