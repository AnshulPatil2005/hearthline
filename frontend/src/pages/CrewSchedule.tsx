import '@bryntum/schedulerpro/fontawesome/css/fontawesome.css'
import '@bryntum/schedulerpro/fontawesome/css/solid.css'
import '@bryntum/schedulerpro/schedulerpro.css'
import '@bryntum/schedulerpro/stockholm-light.css'
import { StringHelper } from '@bryntum/schedulerpro'
import { BryntumSchedulerPro, type BryntumSchedulerProProps } from '@bryntum/schedulerpro-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { API_URL, tokenStore } from '../api'

// Jobs are at addresses in Sablewood, California: show local site time whoever is dispatching.
const SITE_TIME_ZONE = 'America/Los_Angeles'
const encode = (v: unknown) => StringHelper.encodeHtml(String(v ?? ''))

// The few record methods used here (Scheduler and Scheduler Pro type their records differently).
type Rec = { id?: unknown; name?: string; get(field: string): unknown; set(field: string, value: unknown): void }

export default function CrewSchedule() {
  const { t } = useTranslation()
  const [error, setError] = useState<string | null>(null)
  const [now] = useState(() => new Date())
  const [start] = useState(() => {
    const d = new Date()
    d.setDate(d.getDate() - 1)
    d.setHours(0, 0, 0, 0)
    return d
  })

  const props = useMemo<BryntumSchedulerProProps>(() => {
    const headers = { Authorization: `Bearer ${tokenStore.get()}`, 'Content-Type': 'application/json' }
    const end = new Date(start)
    end.setDate(end.getDate() + 5)
    const editable = ({ eventRecord }: { eventRecord: Rec }) => eventRecord.get('status') !== 'done'
    return {
      project: {
        transport: {
          load: { url: `${API_URL}/bryntum/crews/load`, method: 'GET', headers },
          sync: { url: `${API_URL}/bryntum/crews/sync`, method: 'POST', headers },
        },
        autoLoad: true,
        autoSync: true,
        timeZone: SITE_TIME_ZONE,
        onSync: () => setError(null),
        onSyncFail: ({ source, response }: { source: unknown; response: unknown }) => {
          setError((response as { message?: string } | null)?.message ?? t('errors.generic'))
          ;(source as unknown as { revertChanges?: () => void }).revertChanges?.()
        },
        onLoadFail: () => setError(t('errors.generic')),
      },
      startDate: start,
      endDate: end,
      viewPreset: { base: 'hourAndDay', tickWidth: 95 },
      visibleDate: { date: now, block: 'start' }, // open on now; earlier days are a scroll away
      workingTime: { fromHour: 7, toHour: 19 }, // nights are hidden: crews work daylight hours
      rowHeight: 56,
      barMargin: 6,
      eventStyle: 'rounded',
      columns: [
        {
          text: t('crews.crew'),
          field: 'name',
          width: 230,
          renderer: ({ record }: { record: Rec }) =>
            record.id === 'unassigned'
              ? `<b>${encode(t('crews.unassigned'))}</b>`
              : `<div><b>${encode(record.name)}</b><div class="b-crew-meta">${encode(
                  t(`crews.kind.${record.get('kind')}`),
                )} · ${encode(t('crews.people', { count: record.get('size') }))} · ${encode(record.get('lead'))}</div></div>`,
        },
      ],
      eventRenderer: ({ eventRecord }: { eventRecord: Rec }) =>
        `${encode(t(`crews.short.${eventRecord.get('kind')}`))}<div class="b-crew-meta">${encode(eventRecord.get('household'))}</div>`,
      // Bryntum's React wrappers take each feature as its own `<name>Feature` prop.
      eventBufferFeature: true, // Scheduler Pro: the 20 minutes of travel drawn before each job
      timeRangesFeature: { showCurrentTimeLine: true },
      eventDragCreateFeature: false,
      eventEditFeature: false,
      taskEditFeature: false,
      dependenciesFeature: false,
      cellMenuFeature: false,
      scheduleMenuFeature: false,
      eventTooltipFeature: {
          template: ({ eventRecord }: { eventRecord: Rec }) =>
            `<b>${encode(t(`crews.job.${eventRecord.get('kind')}`))}</b><br>` +
            `${encode(eventRecord.get('household'))} · ${encode(eventRecord.get('address'))}<br>` +
            `${encode(t('crews.peopleAt', { count: eventRecord.get('people') }))} · ${encode(
              t(`command.damage.${eventRecord.get('damage')}`),
            )}<br>${encode(t(`crews.status.${eventRecord.get('status')}`))}`,
        },
      eventMenuFeature: {
          items: {
            deleteEvent: false,
            copyEvent: false,
            cutEvent: false,
            splitEvent: false,
            unassignEvent: false,
            editEvent: false,
            markDone: {
              text: t('crews.markDone'),
              icon: 'fa fa-check',
              weight: 100,
              onItem: ({ eventRecord }: { eventRecord: Rec }) => eventRecord.set('status', 'done'),
            },
          },
          processItems: ({ eventRecord, items }: { eventRecord: Rec; items: Record<string, unknown> }) => {
            if (eventRecord.get('status') === 'done') items.markDone = false
          },
        },
      onBeforeEventDrag: editable,
      onBeforeEventResize: editable,
    } as unknown as BryntumSchedulerProProps
  }, [now, start, t])

  return (
    <div className="flex h-[calc(100svh-11rem)] min-h-[34rem] flex-col gap-4">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">{t('crews.title')}</h1>
        <p className="mt-1 text-ink-soft">{t('crews.subtitle')}</p>
      </div>
      {error && <p className="text-sm text-danger">{error}</p>}
      <div className="min-h-0 flex-1 overflow-hidden rounded-xl border border-line">
        <BryntumSchedulerPro {...props} />
      </div>
      <p className="text-xs text-ink-faint">{t('crews.hint')}</p>
    </div>
  )
}
