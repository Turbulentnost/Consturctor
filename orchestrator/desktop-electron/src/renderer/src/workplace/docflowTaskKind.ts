import type { SpecPillTone } from './specV04DemoData'

/** Зеркало backend/app/tools/onec/docflow_task_kinds.py. */
export type DocflowTaskKind =
  | 'execute'
  | 'check'
  | 'acquaint'
  | 'acquaint_result'
  | 'approve'
  | 'confirm'
  | 'consider'
  | 'question'
  | 'resolution'
  | 'other'

export type DocflowActionId =
  | 'execute'
  | 'accept'
  | 'return'
  | 'acquaint'
  | 'approve'
  | 'approve_remarks'
  | 'decline'
  | 'confirm'
  | 'consider'
  | 'close_question'
  | 'process'
  | 'done'

export type DocflowActionSpec = {
  id: DocflowActionId
  label: string
  /** Подпись кнопки в строке таблицы. */
  shortLabel: string
  tone: 'primary' | 'outline' | 'danger'
  /** 1С не примет отрицательный результат без комментария. */
  needsComment?: boolean
}

const KINDS = new Set<string>([
  'execute',
  'check',
  'acquaint',
  'acquaint_result',
  'approve',
  'confirm',
  'consider',
  'question',
  'resolution',
  'other'
])

export const DOCFLOW_KIND_LABEL: Record<DocflowTaskKind, string> = {
  execute: 'Исполнение',
  check: 'Проверка исполнения',
  acquaint: 'Ознакомление',
  acquaint_result: 'Ознакомление с результатом',
  approve: 'Согласование',
  confirm: 'Утверждение',
  consider: 'Рассмотрение',
  question: 'Вопрос',
  resolution: 'Резолюция',
  other: 'Задача'
}

export const DOCFLOW_KIND_TONE: Record<DocflowTaskKind, SpecPillTone> = {
  execute: 'blue',
  check: 'orange',
  acquaint: 'gray',
  acquaint_result: 'gray',
  approve: 'purple',
  confirm: 'purple',
  consider: 'yellow',
  question: 'yellow',
  resolution: 'green',
  other: 'gray'
}

const KIND_ACTIONS: Record<DocflowTaskKind, DocflowActionSpec[]> = {
  execute: [{ id: 'execute', label: 'Исполнено', shortLabel: 'Исполнено', tone: 'primary' }],
  check: [
    { id: 'accept', label: 'Принять исполнение', shortLabel: 'Принять', tone: 'primary' },
    { id: 'return', label: 'Вернуть на доработку', shortLabel: 'Вернуть', tone: 'danger', needsComment: true }
  ],
  acquaint: [{ id: 'acquaint', label: 'Ознакомлен', shortLabel: 'Ознакомлен', tone: 'primary' }],
  acquaint_result: [{ id: 'acquaint', label: 'Ознакомлен', shortLabel: 'Ознакомлен', tone: 'primary' }],
  approve: [
    { id: 'approve', label: 'Согласовать', shortLabel: 'Согласовать', tone: 'primary' },
    {
      id: 'approve_remarks',
      label: 'Согласовать с замечаниями',
      shortLabel: 'С замечаниями',
      tone: 'outline',
      needsComment: true
    },
    { id: 'decline', label: 'Не согласовать', shortLabel: 'Не согласовать', tone: 'danger', needsComment: true }
  ],
  confirm: [
    { id: 'confirm', label: 'Утвердить', shortLabel: 'Утвердить', tone: 'primary' },
    { id: 'decline', label: 'Не утверждать', shortLabel: 'Не утверждать', tone: 'danger', needsComment: true }
  ],
  consider: [{ id: 'consider', label: 'Рассмотрено', shortLabel: 'Рассмотрено', tone: 'primary' }],
  question: [{ id: 'close_question', label: 'Закрыть вопрос', shortLabel: 'Закрыть вопрос', tone: 'primary' }],
  resolution: [{ id: 'process', label: 'Резолюция обработана', shortLabel: 'Обработано', tone: 'primary' }],
  other: [{ id: 'done', label: 'Выполнено', shortLabel: 'Выполнено', tone: 'primary' }]
}

function normalize(text: string | undefined): string {
  return String(text || '')
    .toLowerCase()
    .replace(/ё/g, 'е')
    .replace(/\s+/g, ' ')
    .trim()
}

/** Тип по шагу процесса (businessProcessStep); имя задачи — запасной вариант. */
export function docflowTaskKind(step?: string, name?: string, serverKind?: string): DocflowTaskKind {
  const fromServer = String(serverKind || '').trim()
  if (KINDS.has(fromServer) && fromServer !== 'other') return fromServer as DocflowTaskKind
  for (const raw of [step, name]) {
    const text = normalize(raw)
    if (!text) continue
    if (text.startsWith('ознакомиться с результатом') || text.startsWith('ознакомиться:')) return 'acquaint_result'
    if (text.includes('ознаком')) return 'acquaint'
    if (text.includes('проверить') || text.includes('контрол')) return 'check'
    if (text.includes('согласова')) return 'approve'
    if (text.includes('утверд') || text.includes('подписа')) return 'confirm'
    if (text.includes('резолюц')) return 'resolution'
    if (text.includes('вопрос')) return 'question'
    if (text.includes('рассмотр')) return 'consider'
    if (text.includes('исполн')) return 'execute'
  }
  return 'other'
}

export function docflowKindActions(kind: DocflowTaskKind): DocflowActionSpec[] {
  return KIND_ACTIONS[kind] ?? KIND_ACTIONS.other
}

export function docflowPrimaryAction(kind: DocflowTaskKind): DocflowActionSpec {
  return docflowKindActions(kind)[0]
}
