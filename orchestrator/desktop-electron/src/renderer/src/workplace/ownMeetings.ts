import { useCallback, useEffect, useState } from 'react'
import type { UserProfile } from '../api/types'
import type { MeetingEvent } from '../utils/outlookMeetings'
import { isIlchenkoAccount } from './boardReportReadiness'
import { meetingOwnerName, samePersonName } from './meetingCalendars'

const SHOW_OWN_KEY = 'orch.meetings.show-own.v2'
export const OWN_MEETINGS_EVENT = 'orch-own-meetings'

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

/**
 * Личный календарь Outlook этого человека.
 * Общий календарь, из которого у сотрудника читаются совещания компании,
 * сюда не входит: его отключение не должно гасить чужие встречи.
 */
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
  useEffect(() => {
    const sync = (): void => setShowOwnState(readShowOwnMeetings(fio))
    window.addEventListener(OWN_MEETINGS_EVENT, sync)
    return () => window.removeEventListener(OWN_MEETINGS_EVENT, sync)
  }, [fio])
  const setShowOwn = useCallback(
    (value: boolean) => {
      setShowOwnState(value)
      try {
        window.localStorage.setItem(storageKey(fio), value ? '1' : '0')
      } catch {
        /* хранилище недоступно — тумблер работает до перезагрузки */
      }
      window.dispatchEvent(new Event(OWN_MEETINGS_EVENT))
    },
    [fio]
  )
  return [showOwn, setShowOwn]
}

export function useOwnMeetingsVersion(): number {
  const [version, setVersion] = useState(0)
  useEffect(() => {
    const bump = (): void => setVersion((value) => value + 1)
    window.addEventListener(OWN_MEETINGS_EVENT, bump)
    return () => window.removeEventListener(OWN_MEETINGS_EVENT, bump)
  }, [])
  return version
}
