/** Рекомендации агента по задачам 1С:Документооборот: блок ```docflow-actions [...]``` в итоговом ответе. */
export type DocflowActionKind = 'close' | 'return'

export type AgentDocflowAction = {
  assignment: string
  line: string
  event: string
  performer: string
  taskId: string
  step: string
  title: string
  targetId: string
  action: DocflowActionKind
  reason: string
  comment: string
}

const BLOCK_RE = /```docflow-actions\s*\n([\s\S]*?)```/i
const GUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

function text(value: unknown): string {
  return value === null || value === undefined ? '' : String(value).trim()
}

/** «задача 2» — задача ДО поручения; «п.2» — пункт в результатах до перехода на задачи. */
function unitLabel(row: Record<string, unknown>): string {
  if (text(row.n)) return `задача ${text(row.n)}`
  return text(row.line) ? `п.${text(row.line)}` : ''
}

function toAction(raw: unknown): AgentDocflowAction | null {
  if (!raw || typeof raw !== 'object') return null
  const row = raw as Record<string, unknown>
  const taskId = text(row.task_id ?? row.taskId)
  const action = text(row.action).toLowerCase()
  if (!GUID_RE.test(taskId) || (action !== 'close' && action !== 'return')) return null
  return {
    assignment: text(row.assignment ?? row.number),
    line: unitLabel(row),
    event: text(row.task ?? row.event ?? row.text),
    performer: text(row.performer),
    taskId,
    step: text(row.step),
    title: text(row.title ?? row.name),
    targetId: text(row.target_id ?? row.targetId),
    action,
    reason: text(row.reason),
    comment: text(row.comment)
  }
}

/** Убирает служебный блок из текста ответа и возвращает распознанные действия. */
export function extractDocflowActions(body: string): { text: string; actions: AgentDocflowAction[] } {
  const match = BLOCK_RE.exec(body || '')
  if (!match) return { text: body, actions: [] }
  let parsed: unknown
  try {
    parsed = JSON.parse(match[1])
  } catch {
    return { text: body, actions: [] }
  }
  const actions = (Array.isArray(parsed) ? parsed : [])
    .map(toAction)
    .filter((item): item is AgentDocflowAction => item !== null)
  return { text: body.replace(match[0], '').trim(), actions }
}

/** Задача ДО поручения в итоге проверки; в старых результатах — пункт поручения. */
export type ClosureCheckLine = {
  /** «задача 2» или «п.2». */
  line: string
  /** Что поручено в задаче (в старых результатах — мероприятие). */
  event: string
  executor: string
  conclusion: string
  evidence: string
  taskState: string
  advice: string
  /** Замечание агента исполнителю: уходит в комментарий возврата на доработку. */
  comment: string
  action: AgentDocflowAction | null
  /** Открытая задача исполнителя: закрыть или вернуть её пока нельзя, только открыть карточку. */
  openTaskId: string
}

export type ClosureCheckAssignment = {
  number: string
  /** ref_key поручения в 1С ERP. */
  targetId: string
  conclusion: string
  done: number
  total: number
  reason: string
  lines: ClosureCheckLine[]
}

const CHECK_RE = /```closure-check\s*\n([\s\S]*?)```/i

function closureLine(assignment: Record<string, unknown>, raw: unknown): ClosureCheckLine | null {
  if (!raw || typeof raw !== 'object') return null
  const row = raw as Record<string, unknown>
  const action = toAction({
    ...row,
    assignment: assignment.number,
    target_id: row.target_id ?? assignment.target_id,
    performer: row.performer ?? row.executor
  })
  return {
    line: unitLabel(row),
    event: text(row.task ?? row.event ?? row.text),
    executor: text(row.executor ?? row.performer),
    conclusion: text(row.conclusion),
    evidence: text(row.evidence),
    taskState: text(row.task_state ?? row.taskState),
    advice: text(row.advice),
    comment: text(row.comment),
    action,
    openTaskId: GUID_RE.test(text(row.open_task_id)) ? text(row.open_task_id) : ''
  }
}

/** Итог проверки поручений: блок ```closure-check {"assignments": [...]}``` в ответе агента. */
export function extractClosureCheck(body: string): { text: string; assignments: ClosureCheckAssignment[] } {
  const match = CHECK_RE.exec(body || '')
  if (!match) return { text: body, assignments: [] }
  let parsed: unknown
  try {
    parsed = JSON.parse(match[1])
  } catch {
    return { text: body, assignments: [] }
  }
  const list = Array.isArray(parsed)
    ? parsed
    : parsed && typeof parsed === 'object'
      ? (parsed as Record<string, unknown>).assignments
      : []
  const assignments = (Array.isArray(list) ? list : [])
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map((item) => ({
      number: text(item.number),
      targetId: GUID_RE.test(text(item.target_id)) ? text(item.target_id) : '',
      conclusion: text(item.conclusion),
      done: Number(item.done) || 0,
      total: Number(item.total) || 0,
      reason: text(item.reason),
      lines: (Array.isArray(item.tasks) ? item.tasks : Array.isArray(item.lines) ? item.lines : [])
        .map((line) => closureLine(item, line))
        .filter((line): line is ClosureCheckLine => line !== null)
    }))
    .filter((item) => item.number)
  return { text: body.replace(match[0], '').trim(), assignments }
}

/** Текст для чата без служебных блоков и действия для кнопок из обоих форматов. */
export function splitAgentResult(body: string): {
  text: string
  actions: AgentDocflowAction[]
  assignments: ClosureCheckAssignment[]
} {
  const check = extractClosureCheck(body)
  const legacy = extractDocflowActions(check.text)
  const fromCheck = check.assignments.flatMap((item) =>
    item.lines.map((line) => line.action).filter((action): action is AgentDocflowAction => action !== null)
  )
  const seen = new Set(fromCheck.map((item) => item.taskId))
  return {
    text: legacy.text,
    actions: [...fromCheck, ...legacy.actions.filter((item) => !seen.has(item.taskId))],
    assignments: check.assignments
  }
}

export function defaultReworkDue(days = 7): string {
  const date = new Date()
  date.setDate(date.getDate() + days)
  return date.toISOString().slice(0, 10)
}
