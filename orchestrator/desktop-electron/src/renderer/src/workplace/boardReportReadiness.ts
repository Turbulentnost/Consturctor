import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { UserProfile } from '../api/types'
import { onecGatewayInvokeArgs } from './userContext'

export type BoardReportReadiness = {
  protocolNumber: string
  protocolDate: string
  total: number
  done: number
  percent: number
  currentMonth: boolean
}

const EMPTY: BoardReportReadiness = {
  protocolNumber: '',
  protocolDate: '',
  total: 0,
  done: 0,
  percent: 0,
  currentMonth: false
}

export function isIlchenkoAccount(user: UserProfile | null): boolean {
  return (user?.fio || '').toLowerCase().includes('ильченко')
}

function str(value: unknown): string {
  return typeof value === 'string' ? value : value == null ? '' : String(value)
}

function rec(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

export function formatProtocolDay(iso: string): string {
  const day = iso.slice(0, 10)
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day)
  return match ? `${match[3]}.${match[2]}.${match[1]}` : day
}

export async function loadBoardReportReadiness(user: UserProfile | null): Promise<BoardReportReadiness> {
  const res = await api.invokeServerTool(
    'onec.docflow_protocols',
    onecGatewayInvokeArgs(user, { action: 'board_readiness' }),
    90_000
  )
  if (!res.ok) throw new Error(res.error || 'Не удалось посчитать готовность к совету директоров')
  const payload = rec(res.result)
  const protocol = rec(payload.protocol)
  const total = Number(payload.total) || 0
  const done = Number(payload.done) || 0
  return {
    protocolNumber: str(protocol.number),
    protocolDate: str(protocol.date).slice(0, 10),
    total,
    done,
    percent: total ? Math.round((done * 100) / total) : Number(payload.percent) || 0,
    currentMonth: Boolean(payload.current_month)
  }
}

export function useBoardReportReadiness(user: UserProfile | null): {
  enabled: boolean
  loading: boolean
  error: string
  readiness: BoardReportReadiness
} {
  const enabled = isIlchenkoAccount(user)
  const [loading, setLoading] = useState(enabled)
  const [error, setError] = useState('')
  const [readiness, setReadiness] = useState<BoardReportReadiness>(EMPTY)

  useEffect(() => {
    if (!enabled) {
      setLoading(false)
      setError('')
      setReadiness(EMPTY)
      return
    }
    let cancelled = false
    setLoading(true)
    setError('')
    void loadBoardReportReadiness(user)
      .then((next) => {
        if (!cancelled) setReadiness(next)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Не удалось посчитать готовность')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [enabled, user?.id, user?.fio])

  return { enabled, loading, error, readiness }
}
