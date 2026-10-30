import '../bryntum.css'
import { useQueryClient } from '@tanstack/react-query'
import { StringHelper } from '@bryntum/core-thin'
import {
  BryntumResourceUtilization,
  BryntumSchedulerPro,
  BryntumSchedulerProProjectModel,
  type BryntumSchedulerProProps,
} from '@bryntum/schedulerpro-react-thin'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { API_URL, api, tokenStore } from '../api'
import { DispatchAgent } from '../components/DispatchAgent'

// Jobs are at addresses in Sablewood, California: show local site time whoever is dispatching.
const SITE_TIME_ZONE = 'America/Los_Angeles'
const encode = (v: unknown) => StringHelper.encodeHtml(String(v ?? ''))

// The few record methods used here (Scheduler and Scheduler Pro type their records differently).
type Rec = { id?: unknown; name?: string; get(field: string): unknown; set(field: string, value: unknown): void }
type Loadable = { load: () => Promise<unknown> }

export default function CrewSchedule() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const [now] = useState(() => new Date())
  const [start] = useState(() => {
    const d = new Date()
    d.setDate(d.getDate() - 1)
    d.setHours(0, 0, 0, 0)
    return d
  })
  const project = useRef<BryntumSchedulerProProjectModel>(null)
  const scheduler = useRef<BryntumSchedulerPro>(null)
  const [partner, setPartner] = useState<BryntumSchedulerPro['instance'] | null>(null)
  useEffect(() => setPartner(scheduler.current?.instance ?? null), [])

  // A decision in the dispatch panel (or on a ghost bar) changes jobs: load them again. The load view is drawn anew
  // after each load: redrawn in place, its bars keep stale rows and stretch their labels.
  const [loads, setLoads] = useState(0)
  const reload = () =>
    void (project.current?.instance as unknown as Loadable | undefined)?.load().then(() => setLoads((n) => n + 1))
  const decide = (id: unknown, action: 'accept' | 'reject') =>
    api(`/command/dispatch/proposals/${id}/${action}`, { method: 'POST' })
      .then(() => {
        void queryClient.invalidateQueries({ queryKey: ['dispatch-plan'] })
        reload()
      })
      .catch((e: Error) => setError(e.message))

  const headers = { Authorization: `Bearer ${tokenStore.get()}`, 'Content-Type': 'application/json' }
  const projectProps = {
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
  }

  const end = new Date(start)
  end.setDate(end.getDate() + 5)
  const timeline = {
    startDate: start,
    endDate: end,
    viewPreset: { base: 'hourAndDay', tickWidth: 95 },
    workingTime: { fromHour: 7, toHour: 19 }, // nights are hidden: crews work daylight hours
  }

  const props = useMemo<BryntumSchedulerProProps>(() => {
    const editable = ({ eventRecord }: { eventRecord: Rec }) =>
      eventRecord.get('status') !== 'done' && !eventRecord.get('proposal')
    return {
      visibleDate: { date: now, block: 'start' }, // open on now; earlier days are a scroll away
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
        `${eventRecord.get('proposal') ? `<span class="b-proposal-tag">${encode(t('dispatch.proposed'))}</span> ` : ''}${encode(
          t(`crews.short.${eventRecord.get('kind')}`),
        )}<div class="b-crew-meta">${encode(eventRecord.get('household'))}</div>`,
      // Bryntum's React wrappers take each feature as its own `<name>Feature` prop.
      eventBufferFeature: true, // Scheduler Pro: the travel time drawn before each job
      timeRangesFeature: { showCurrentTimeLine: true },
      eventDragCreateFeature: false,
      eventEditFeature: false,
      taskEditFeature: false,
      dependenciesFeature: false,
      cellMenuFeature: false,
      scheduleMenuFeature: false,
      eventTooltipFeature: {
        template: ({ eventRecord }: { eventRecord: Rec }) =>
          (eventRecord.get('proposal')
            ? `<b>${encode(t('dispatch.proposedBy'))}</b><br>${encode(eventRecord.get('reason'))}<br><br>`
            : '') +
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
          acceptProposal: {
            text: t('dispatch.accept'),
            icon: 'fa fa-check',
            weight: 100,
            onItem: ({ eventRecord }: { eventRecord: Rec }) => decide(eventRecord.get('proposal'), 'accept'),
          },
          rejectProposal: {
            text: t('dispatch.reject'),
            icon: 'fa fa-xmark',
            weight: 110,
            onItem: ({ eventRecord }: { eventRecord: Rec }) => decide(eventRecord.get('proposal'), 'reject'),
          },
        },
        processItems: ({ eventRecord, items }: { eventRecord: Rec; items: Record<string, unknown> }) => {
          const ghost = !!eventRecord.get('proposal')
          if (eventRecord.get('status') === 'done' || ghost) items.markDone = false
          if (!ghost) items.acceptProposal = items.rejectProposal = false
        },
      },
      onBeforeEventDrag: editable,
      onBeforeEventResize: editable,
    } as unknown as BryntumSchedulerProProps
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [now, t])

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">{t('crews.title')}</h1>
        <p className="mt-1 text-ink-soft">{t('crews.subtitle')}</p>
      </div>
      <DispatchAgent onChanged={reload} />
      {error && <p className="text-sm text-danger">{error}</p>}
      <BryntumSchedulerProProjectModel ref={project} {...(projectProps as object)} />
      <div className="h-[calc(100svh-16rem)] min-h-[30rem] overflow-hidden rounded-xl border border-line">
        <BryntumSchedulerPro ref={scheduler} project={project} {...timeline} {...props} />
      </div>
      <section aria-labelledby="load-title">
        <h2 id="load-title" className="mb-2 text-sm font-semibold">
          {t('dispatch.loadTitle')}
        </h2>
        {/* Shorter than its rows on purpose: when every row fits, Chrome draws the bars' labels stretched */}
        <div className="h-64 overflow-hidden rounded-xl border border-line">
          {partner && (
            <BryntumResourceUtilization
              key={loads}
              project={project}
              partner={partner}
              {...timeline}
              rowHeight={36}
              hideHeaders
              showBarTip
              columns={[
                {
                  type: 'tree',
                  field: 'name',
                  text: t('crews.crew'),
                  width: 230,
                  // Rows wrap the Scheduler's resources; the row for jobs without a crew has no name of its own
                  renderer: ({
                    record,
                    value,
                  }: {
                    record: { id?: unknown; origin?: { id?: unknown } }
                    value: string
                  }) => ((record.origin?.id ?? record.id) === 'unassigned' ? t('crews.unassigned') : value),
                },
              ]}
            />
          )}
        </div>
      </section>
      <p className="text-xs text-ink-faint">{t('crews.hint')}</p>
    </div>
  )
}
