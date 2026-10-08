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
  projectId: number
  rows: number
  /** The contractor can drag milestones that haven't been submitted yet; everyone else only looks. */
  editable: boolean
  onSynced?: () => void
}

export default function ProjectGantt({ projectId, rows, editable, onSynced }: Props) {
  const { t } = useTranslation()
  const [error, setError] = useState<string | null>(null)

  const props = useMemo<BryntumGanttProps>(() => {
    const headers = { Authorization: `Bearer ${tokenStore.get()}`, 'Content-Type': 'application/json' }
    const pendingOnly = ({ taskRecord }: { taskRecord: TaskModel }) =>
      editable && taskRecord.get('status') === 'pending'
    return {
      project: {
        transport: {
          load: { url: `${API_URL}/bryntum/gantt/${projectId}/load`, method: 'GET', headers },
          sync: { url: `${API_URL}/bryntum/gantt/${projectId}/sync`, method: 'POST', headers },
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
        { type: 'name', text: t('rebuild.gantt.milestone'), width: 340 },
        { type: 'startdate', text: t('rebuild.gantt.start') },
        { type: 'enddate', text: t('rebuild.gantt.end') },
      ],
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
  }, [editable, onSynced, projectId, t])

  return (
    <div className="space-y-2">
      <div className="overflow-hidden rounded-xl border border-line" style={{ height: 76 + 44 * (rows + 1) }}>
        <BryntumGantt {...props} />
      </div>
      {error && <p className="text-sm text-danger">{error}</p>}
      <p className="text-xs text-ink-faint">{editable ? t('rebuild.gantt.editHint') : t('rebuild.gantt.viewHint')}</p>
    </div>
  )
}
