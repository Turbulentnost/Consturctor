import type { ModelParam, SessionStatus } from './api/types'

const MODEL_PARAM_LABELS: Record<string, Record<string, string>> = {
  reasoning_effort: { low: 'Low', medium: 'Medium', high: 'High', xhigh: 'Extra High' },
  effort: { low: 'Low', medium: 'Medium', high: 'High', xhigh: 'Extra High' },
  fast: { true: 'Fast' },
  context: { '256k': '256k', '500k': '500k' }
}

/** grok-4.7 и его параметры: «grok-4.7 · Extra High · Fast · 500k». */
export function modelLabel(model: string, params?: ModelParam[]): string {
  const parts = (params ?? [])
    .map((param) => MODEL_PARAM_LABELS[param.id]?.[param.value] ?? param.value)
    .filter(Boolean)
  return parts.length ? `${model} · ${parts.join(' · ')}` : model
}

export const SESSION_STATUS: Record<SessionStatus, string> = {
  running: 'Работает',
  finished: 'Готово',
  error: 'Ошибка',
  cancelled: 'Остановлен'
}

export function formatTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}
