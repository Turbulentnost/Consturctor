const STATUS_LABELS: Record<string, string> = {
  done: 'Готов',
  completed: 'Готов',
  complete: 'Готов',
  ready: 'Готов',
  published: 'Опубликован',
  active: 'В работе',
  running: 'В работе',
  started: 'Запущен',
  executing: 'Выполняется',
  paused: 'Пауза',
  waiting_human: 'Ждёт решения',
  waiting: 'Ждёт решения',
  hitl: 'Ждёт решения',
  pending: 'Ожидает',
  approval: 'Ожидает согласования',
  error: 'Ошибка',
  failed: 'Ошибка',
  fail: 'Ошибка',
  canceled: 'Отменён',
  cancelled: 'Отменён',
  draft: 'Черновик',
  design: 'Проектирование',
  document: 'Документ',
  tested: 'Протестирован'
}

export function localizeStatusText(raw: string, fallback = ''): string {
  const value = (raw || '').trim()
  if (!value) return fallback
  const key = value.toLowerCase()
  return STATUS_LABELS[key] || value
}
