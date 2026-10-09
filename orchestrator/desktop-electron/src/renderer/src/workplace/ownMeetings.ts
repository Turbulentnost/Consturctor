import { useCallback, useState } from 'react'
import type { UserProfile } from '../api/types'
import type { MeetingEvent } from '../utils/outlookMeetings'
import { isIlchenkoAccount } from './boardReportReadiness'
import { meetingOwnerName, samePersonName } from './meetingCalendars'

const SHOW_OWN_KEY = 'orch.meetings.show-own'

function storageKey(fio: string): string {
  return `${SHOW_OWN_KEY}:${String(fio || '').trim().toLowerCase()}`
}

export function readShowOwnMeetings(fio: string): boolean {
  try {
    return window.localStorage.getItem(storageKey(fio)) === '1'
  } catch {
    return false
  }
}

/** Совещание из собственного календаря пользователя (его «обычные» встречи). */
export function isSelfCalendarMeeting(meeting: MeetingEvent, selfLabel: string): boolean {
  return samePersonName(meetingOwnerName(meeting, selfLabel), selfLabel)
}

/**
 * Для аккаунта Ильченко её собственные совещания скрыты, пока не включён тумблер.
 * Для остальных пользователей фильтр не применяется.
 */
export function ownMeetingsHidden(user: UserProfile | null, showOwn: boolean): boolean {
  return isIlchenkoAccount(user) && !showOwn
}

export function useShowOwnMeetings(fio: string): [boolean, (value: boolean) => void] {
  const [showOwn, setShowOwnState] = useState(() => readShowOwnMeetings(fio))
  const setShowOwn = useCallback(
    (value: boolean) => {
      setShowOwnState(value)
      try {
        window.localStorage.setItem(storageKey(fio), value ? '1' : '0')
      } catch {
        /* хранилище недоступно — тумблер работает до перезагрузки */
      }
    },
    [fio]
  )
  return [showOwn, setShowOwn]
}
