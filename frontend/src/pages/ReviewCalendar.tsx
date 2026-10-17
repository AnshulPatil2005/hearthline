import '@bryntum/calendar/calendar.css'
import '@bryntum/calendar/fontawesome/css/fontawesome.css'
import '@bryntum/calendar/fontawesome/css/solid.css'
import '@bryntum/calendar/stockholm-light.css'
import { BryntumCalendar, type BryntumCalendarProps } from '@bryntum/calendar-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { API_URL, tokenStore } from '../api'

export default function ReviewCalendar() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [today] = useState(() => new Date())

  const props = useMemo<BryntumCalendarProps>(() => {
    const headers = { Authorization: `Bearer ${tokenStore.get()}`, 'Content-Type': 'application/json' }
    return {
      date: today,
      mode: 'week',
      autoCreate: false, // calls are booked from a case, so each one is tied to a household
      crudManager: {
        transport: {
          load: { url: `${API_URL}/bryntum/calendar/load`, method: 'GET', headers },
          sync: { url: `${API_URL}/bryntum/calendar/sync`, method: 'POST', headers },
        },
        autoLoad: true,
        autoSync: true,
      },
      eventEditFeature: false,
      listeners: {
        eventClick: ({ eventRecord }: { eventRecord: { get: (field: string) => unknown } }) => {
          const caseId = eventRecord.get('caseId')
          if (caseId) navigate(`/review/cases/${caseId}`)
        },
      },
    }
  }, [navigate, today])

  return (
    <div className="flex h-[calc(100svh-11rem)] min-h-[32rem] flex-col gap-4">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">{t('calendar.title')}</h1>
        <p className="mt-1 text-ink-soft">{t('calendar.subtitle')}</p>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden rounded-xl border border-line">
        <BryntumCalendar {...props} />
      </div>
    </div>
  )
}
