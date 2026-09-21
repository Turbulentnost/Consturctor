import { api } from '../api/client'

export type AssignmentCreateLineDraft = {
  key: string
  text: string
  executor: string
  due: string
  priority: string
}

export type AssignmentCreateDraft = {
  topic: string
  basis: string
  customer: string
  due: string
  reporter: string
  secretary: string
  lines: AssignmentCreateLineDraft[]
}

export type AssignmentCreateResult = {
  ok: boolean
  number?: string
  refKey?: string
  summary?: string
  error?: string
}

export function emptyCreateDraft(): AssignmentCreateDraft {
  return {
    topic: '',
    basis: 'Устное поручение',
    customer: '',
    due: '',
    reporter: '',
    secretary: '',
    lines: [{ key: '1', text: '', executor: '', due: '', priority: '' }]
  }
}

function parseCreateResult(result: unknown): Omit<AssignmentCreateResult, 'ok' | 'error'> {
  if (!result || typeof result !== 'object') return {}
  const payload = result as Record<string, unknown>
  const data =
    payload.data && typeof payload.data === 'object'
      ? (payload.data as Record<string, unknown>)
      : undefined
  return {
    refKey: String(payload.erp_document_id || data?.Ref_Key || '').trim() || undefined,
    number: String(data?.Number || payload.number || '').trim() || undefined,
    summary: String(payload.summary || '').trim() || undefined
  }
}

export async function createAssignmentInOneC(
  draft: AssignmentCreateDraft
): Promise<AssignmentCreateResult> {
  const topic = draft.topic.trim()
  const customer = draft.customer.trim()
  const due = draft.due.trim()
  if (!topic) return { ok: false, error: 'Укажите тему поручения («О чём»)' }
  if (!customer) return { ok: false, error: 'Укажите руководителя (заказчика) — ФИО из 1С' }
  if (!due) return { ok: false, error: 'Укажите срок полного устранения нарушений' }

  const lines = draft.lines
    .map((line, index) => ({
      line: index + 1,
      text: line.text.trim(),
      executor: line.executor.trim(),
      due: line.due.trim() || due,
      priority: line.priority.trim()
    }))
    .filter((line) => line.text)

  if (!lines.length) {
    return { ok: false, error: 'Добавьте хотя бы одну задачу (мероприятие) в поручении' }
  }

  const args: Record<string, unknown> = {
    action: 'create',
    topic,
    basis: draft.basis.trim() || 'Устное поручение',
    customer,
    due,
    lines
  }
  const reporter = draft.reporter.trim()
  const secretary = draft.secretary.trim()
  if (reporter) args.reporter = reporter
  if (secretary) args.secretary = secretary

  const response = await api.invokeServerTool('onec.erp_assignments_write', args, 180_000)
  if (!response.ok) {
    return { ok: false, error: response.error || 'Не удалось создать поручение в 1С' }
  }
  const parsed = parseCreateResult(response.result)
  return {
    ok: true,
    ...parsed,
    summary: parsed.summary || 'Поручение создано в 1С. Номер появится в журнале после проведения.'
  }
}
