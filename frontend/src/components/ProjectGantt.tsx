import '../bryntum.css'
// Thin packages register only their own product's features; the today line (timeRanges) is Scheduler's.
import '@bryntum/scheduler-thin/lib/feature/TimeRanges.js'
import type { TaskModel } from '@bryntum/gantt-thin'
import { BryntumGantt, type BryntumGanttProps } from '@bryntum/gantt-react-thin'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { API_URL, tokenStore } from '../api'
import { BuiltWith } from './Showcase'

/** Lets a page show "what if this step runs late?" on the chart, scheduled by Bryntum's engine, without saving. */
export type GanttPreview = {
  /** Draw the plan with the step taking `days` longer; resolves to the move-in day the engine works out. */
  preview: (milestoneId: number, days: number) => Promise<Date | null>
  /** Back to the saved schedule. */
  clear: () => void
}

// The few project and task methods the preview uses
type Task = { duration: number; startDate: Date; get(field: string): unknown; setDuration(d: number): Promise<unknown> }
type Engine = {
  project: {
    suspendAutoSync(): void
    resumeAutoSync(sync: boolean): void
    revertChanges(): void
    commitAsync(): Promise<unknown>
  }
  taskStore: { getById(id: number): Task | undefined; allRecords: Task[] }
  features: { criticalPaths?: { disabled: boolean } }
  zoomToFit(options: object): void
}

type Props = {
  /** CrudManager endpoints, e.g. `/bryntum/gantt/7` (load) and the same + `/sync`. */
  base: string
  rows: number
  /** The contractor can drag milestones that haven't been submitted yet; everyone else only looks. */
  editable: boolean
  onSynced?: () => void
  label?: string
  hint?: string
  /** Only the name column, so a narrow page still shows the timeline. */
  compact?: boolean
  /** A rebuild schedule: the accepted plan as a baseline, the critical path, each step's days to spare, move-in day. */
  schedule?: boolean
  onPreviewReady?: (preview: GanttPreview) => void
}

export default function ProjectGantt({
  base,
  rows,
  editable,
  onSynced,
  label,
  hint,
  compact = false,
  schedule = false,
  onPreviewReady,
}: Props) {
  const { t } = useTranslation()
  const [error, setError] = useState<string | null>(null)
  const [critical, setCritical] = useState(true)
  const gantt = useRef<BryntumGantt>(null)
  const engine = () => gantt.current?.instance as unknown as Engine | undefined
  // The whole plan, through move-in day, fits the chart's width
  const fit = () => setTimeout(() => engine()?.zoomToFit({ leftMargin: 24, rightMargin: 48 }))

  useEffect(() => {
    if (!onPreviewReady) return
    let suspended = false // while previewing, nothing is saved
    onPreviewReady({
      preview: async (milestoneId, days) => {
        const g = engine()
        if (!g) return null
        if (!suspended) g.project.suspendAutoSync()
        suspended = true
        g.project.revertChanges() // start from the saved schedule each time
        await g.project.commitAsync()
        const task = g.taskStore.getById(milestoneId)
        if (!task) return null
        await task.setDuration(task.duration + days) // the engine moves every step that waits for it
        await g.project.commitAsync()
        fit()
        return g.taskStore.allRecords.find((r) => r.get('status') === 'move_in')?.startDate ?? null
      },
      clear: () => {
        const g = engine()
        if (!g || !suspended) return
        g.project.revertChanges()
        g.project.resumeAutoSync(false)
        suspended = false
        fit()
      },
    })
  }, [onPreviewReady])

  const props = useMemo<BryntumGanttProps>(() => {
    const headers = { Authorization: `Bearer ${tokenStore.get()}`, 'Content-Type': 'application/json' }
    const pendingOnly = ({ taskRecord }: { taskRecord: TaskModel }) =>
      editable && taskRecord.get('status') === 'pending'
    return {
      project: {
        transport: {
          load: { url: `${API_URL}${base}/load`, method: 'GET', headers },
          sync: { url: `${API_URL}${base}/sync`, method: 'POST', headers },
        },
        autoLoad: true,
        autoSync: editable,
        onSync: () => {
          setError(null)
          onSynced?.()
        },
        onSyncFail: ({ source, response }) => {
          setError((response as { message?: string } | null)?.message ?? t('errors.generic'))
          ;(source as unknown as { revertChanges?: () => void }).revertChanges?.()
        },
        onLoadFail: () => setError(t('errors.generic')),
        onLoad: fit,
      },
      readOnly: !editable,
      viewPreset: 'weekAndMonth',
      rowHeight: schedule ? 52 : 44,
      barMargin: schedule ? 10 : 8,
      columns: [
        {
          type: 'name',
          text: label ?? t('rebuild.gantt.milestone'),
          width: compact ? 260 : schedule ? 300 : 340,
          renderer: ({ record, value }: { record: TaskModel; value: string }) =>
            record.get('status') === 'move_in' ? t('rebuild.whatIf.moveIn') : value,
        },
        // A schedule leaves the timeline the room; its dates are on the cards below and in each bar's tooltip
        ...(compact || schedule
          ? []
          : [
              { type: 'startdate', text: t('rebuild.gantt.start') },
              { type: 'enddate', text: t('rebuild.gantt.end') },
            ]),
        ...(schedule
          ? [
              {
                type: 'totalslack',
                text: t('rebuild.gantt.spare'),
                width: 130,
                // Only steps still to come can slip; paid and submitted work stays where it is
                renderer: ({ record, value }: { record: TaskModel; value: number }) =>
                  record.get('status') === 'pending' ? t('rebuild.whatIf.days', { count: Math.round(value) }) : '',
              },
            ]
          : []),
      ] as BryntumGanttProps['columns'],
      // Bryntum's React wrappers take each feature as its own `<name>Feature` prop.
      taskEditFeature: false, // milestones change through the plan, which the homeowner must accept
      taskMenuFeature: false,
      cellEditFeature: false,
      dependencyEditFeature: false,
      dependenciesFeature: { allowCreate: false },
      percentBarFeature: { allowResize: false },
      projectLinesFeature: false,
      timeRangesFeature: { showCurrentTimeLine: true },
      baselinesFeature: schedule, // the plan the homeowner accepted, under each bar
      criticalPathsFeature: schedule && { disabled: false }, // the steps that set move-in day (off unless asked)
      taskDragFeature: editable,
      taskResizeFeature: editable,
      onBeforeTaskDrag: pendingOnly,
      onBeforeTaskResize: pendingOnly,
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, compact, editable, label, onSynced, schedule, t])

  return (
    <div className="space-y-2">
      <div
        className="overflow-hidden rounded-xl border border-line"
        style={{ height: 76 + (schedule ? 52 : 44) * (rows + 1) }}
      >
        <BryntumGantt ref={gantt} {...props} />
      </div>
      {error && <p className="text-sm text-danger">{error}</p>}
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
        <BuiltWith
          name="Bryntum Gantt"
          what={
            schedule
              ? 'scheduling engine · baselines · critical path · total slack · what-if preview · CrudManager sync'
              : 'CrudManager load and sync with FastAPI'
          }
        />
        <p className="text-xs text-ink-faint">
          {hint ?? (editable ? t('rebuild.gantt.editHint') : t('rebuild.gantt.viewHint'))}
          {schedule && ` ${t('rebuild.gantt.scheduleHint')}`}
        </p>
        {schedule && (
          <label className="flex shrink-0 items-center gap-2 text-xs text-ink-soft">
            <input
              type="checkbox"
              checked={critical}
              onChange={(e) => {
                setCritical(e.target.checked)
                const feature = engine()?.features.criticalPaths
                if (feature) feature.disabled = !e.target.checked
              }}
            />
            {t('rebuild.gantt.criticalPath')}
          </label>
        )}
      </div>
    </div>
  )
}
