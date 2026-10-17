import '@bryntum/gantt/fontawesome/css/fontawesome.css'
import '@bryntum/gantt/fontawesome/css/solid.css'
import '@bryntum/gantt/gantt.css'
import '@bryntum/gantt/stockholm-light.css'
import type { TaskModel } from '@bryntum/gantt'
import { BryntumGantt, type BryntumGanttProps } from '@bryntum/gantt-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { API_URL, tokenStore } from '../api'

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
}

export default function ProjectGantt({ base, rows, editable, onSynced, label, hint, compact = false }: Props) {
  const { t } = useTranslation()
  const [error, setError] = useState<string | null>(null)

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
      },
      readOnly: !editable,
      viewPreset: 'weekAndMonth',
      rowHeight: 44,
      barMargin: 8,
      columns: [
        { type: 'name', text: label ?? t('rebuild.gantt.milestone'), width: compact ? 260 : 340 },
        ...(compact
          ? []
          : [
              { type: 'startdate', text: t('rebuild.gantt.start') },
              { type: 'enddate', text: t('rebuild.gantt.end') },
            ]),
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
      taskDragFeature: editable,
      taskResizeFeature: editable,
      onBeforeTaskDrag: pendingOnly,
      onBeforeTaskResize: pendingOnly,
    }
  }, [base, compact, editable, label, onSynced, t])

  return (
    <div className="space-y-2">
      <div className="overflow-hidden rounded-xl border border-line" style={{ height: 76 + 44 * (rows + 1) }}>
        <BryntumGantt {...props} />
      </div>
      {error && <p className="text-sm text-danger">{error}</p>}
      <p className="text-xs text-ink-faint">{hint ?? (editable ? t('rebuild.gantt.editHint') : t('rebuild.gantt.viewHint'))}</p>
    </div>
  )
}
