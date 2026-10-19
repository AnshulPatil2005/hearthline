import '../bryntum.css'
import { BryntumTaskBoard, type BryntumTaskBoardProps } from '@bryntum/taskboard-react-thin'
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { API_URL, tokenStore } from '../api'

const STATUSES = ['in_review', 'needs_info', 'escalated', 'approved', 'rejected'] as const
const COLORS: Record<(typeof STATUSES)[number], string> = {
  in_review: 'blue',
  needs_info: 'orange',
  escalated: 'purple',
  approved: 'green',
  rejected: 'red',
}

export default function ReviewBoard() {
  const { t } = useTranslation()
  const navigate = useNavigate()

  const props = useMemo<BryntumTaskBoardProps>(
    () => ({
      readOnly: true, // case status only changes through review decisions, never by dragging
      columnField: 'status',
      columns: STATUSES.map((s) => ({
        id: s,
        text: t(`review.status.${s}`),
        tooltip: t(`review.status.${s}`),
        color: COLORS[s],
      })),
      // Read-only pipeline: no add buttons, editors or menus.
      columnToolbarsFeature: false,
      taskEditFeature: false,
      taskMenuFeature: false,
      columnHeaderMenuFeature: false,
      project: {
        transport: {
          load: {
            url: `${API_URL}/bryntum/board/load`,
            method: 'GET',
            headers: { Authorization: `Bearer ${tokenStore.get()}` },
          },
        },
        autoLoad: true,
      },
      listeners: {
        taskClick: ({ taskRecord }: { taskRecord: { id: string | number } }) =>
          navigate(`/review/cases/${taskRecord.id}`),
      },
    }),
    [t, navigate],
  )

  return (
    <div className="flex h-[calc(100svh-11rem)] min-h-[32rem] flex-col gap-4">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">{t('board.title')}</h1>
        <p className="mt-1 text-ink-soft">{t('board.subtitle')}</p>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden rounded-xl border border-line">
        <BryntumTaskBoard {...props} />
      </div>
    </div>
  )
}
