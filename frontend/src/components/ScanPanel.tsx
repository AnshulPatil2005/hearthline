import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type Room, type Scan } from '../api'
import { extractFrames } from '../frames'

const MAX_PHOTOS = 12
const NEW_ROOM = 'new'

export default function ScanPanel() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const rooms = useQuery({ queryKey: ['rooms'], queryFn: () => api<Room[]>('/households/me/rooms') })
  // '' = not chosen yet: default to the first existing room, or a new room if there are none.
  const [chosenRoom, setRoomChoice] = useState('')
  const roomChoice = chosenRoom || (rooms.data?.length ? String(rooms.data[0].id) : NEW_ROOM)
  const [newRoomName, setNewRoomName] = useState('')
  const [photos, setPhotos] = useState<File[]>([])
  const [preparing, setPreparing] = useState(false)
  const [scanId, setScanId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const scan = useQuery({
    queryKey: ['scan', scanId],
    queryFn: () => api<Scan>(`/scans/${scanId}`),
    enabled: scanId !== null,
    refetchInterval: (q) => (q.state.data && ['done', 'failed'].includes(q.state.data.status) ? false : 2000),
  })
  const status = scan.data?.status
  const busy = preparing || (scanId !== null && status !== 'done' && status !== 'failed')

  useEffect(() => {
    if (status === 'done') {
      void queryClient.invalidateQueries({ queryKey: ['items'] })
      void queryClient.invalidateQueries({ queryKey: ['inventory-summary'] })
      void queryClient.invalidateQueries({ queryKey: ['rooms'] })
    }
  }, [status, queryClient])

  async function onFiles(list: FileList | null) {
    if (!list) return
    setError(null)
    setPreparing(true)
    try {
      const collected: File[] = []
      for (const file of Array.from(list)) {
        const room = MAX_PHOTOS - collected.length
        if (room <= 0) break
        if (file.type.startsWith('video/')) collected.push(...(await extractFrames(file, Math.min(8, room))))
        else if (file.type.startsWith('image/')) collected.push(file)
      }
      setPhotos(collected)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('errors.generic'))
    } finally {
      setPreparing(false)
    }
  }

  async function startScan() {
    setError(null)
    try {
      let roomId = Number(roomChoice)
      if (roomChoice === NEW_ROOM) {
        const room = await api<Room>('/households/me/rooms', {
          method: 'POST',
          body: JSON.stringify({ name: newRoomName }),
        })
        roomId = room.id
        setRoomChoice(String(room.id))
        setNewRoomName('')
      }
      const form = new FormData()
      photos.forEach((p) => form.append('files', p))
      const created = await api<Scan>(`/households/me/rooms/${roomId}/scans`, { method: 'POST', body: form })
      setScanId(created.id)
      setPhotos([])
    } catch (e) {
      setError(e instanceof Error ? e.message : t('errors.generic'))
    }
  }

  const roomName = rooms.data?.find((r) => r.id === scan.data?.room_id)?.name ?? newRoomName
  const canStart = photos.length > 0 && !busy && (roomChoice !== NEW_ROOM || newRoomName.trim().length > 0)

  return (
    <section className="panel p-5">
      <h2 className="text-lg font-semibold">{t('inventory.scan.title')}</h2>
      <div className="mt-4 grid gap-4 md:grid-cols-[minmax(0,14rem)_minmax(0,1fr)_auto] md:items-end">
        <label className="block text-sm">
          <span className="text-ink-soft">{t('inventory.scan.room')}</span>
          <select
            value={roomChoice}
            onChange={(e) => setRoomChoice(e.target.value)}
            className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2"
          >
            {rooms.data?.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
            <option value={NEW_ROOM}>{t('inventory.scan.newRoom')}</option>
          </select>
          {roomChoice === NEW_ROOM && (
            <input
              value={newRoomName}
              onChange={(e) => setNewRoomName(e.target.value)}
              placeholder={t('inventory.scan.newRoomName')}
              className="mt-2 w-full rounded-lg border border-line bg-surface px-3 py-2"
            />
          )}
        </label>

        <label className="block cursor-pointer rounded-lg border-2 border-dashed border-line px-4 py-3 text-sm hover:border-ember">
          <span className="font-medium">{t('inventory.scan.choose')}</span>
          <span className="mt-0.5 block text-ink-faint">
            {preparing
              ? t('inventory.scan.extracting')
              : photos.length
                ? t('inventory.scan.selected', { count: photos.length })
                : t('inventory.scan.hint')}
          </span>
          <input
            type="file"
            accept="image/*,video/*"
            multiple
            className="sr-only"
            disabled={busy}
            onChange={(e) => void onFiles(e.target.files)}
          />
        </label>

        <button
          onClick={() => void startScan()}
          disabled={!canStart}
          className="rounded-lg bg-ember px-4 py-2.5 text-sm font-medium text-on-ember hover:opacity-90 disabled:opacity-40"
        >
          {t('inventory.scan.start')}
        </button>
      </div>

      <div aria-live="polite" className="mt-3 text-sm">
        {busy && scanId !== null && <p className="text-ink-soft">{t('inventory.scan.working')}</p>}
        {status === 'done' && (
          <p className="text-sage">{t('inventory.scan.done', { count: scan.data!.item_count, room: roomName })}</p>
        )}
        {status === 'failed' && (
          <p className="text-danger">
            {scan.data!.error === 'ai_busy'
              ? t('inventory.scan.aiBusy')
              : t('inventory.scan.failed', { error: scan.data!.error })}
          </p>
        )}
        {error && <p className="text-danger">{error}</p>}
      </div>
    </section>
  )
}
