export interface DesignDraft {
  title: string
  goal: string
  whenToRun: string
  result: string
  recipient: string
  inputs: string[]
  confirmations: string[]
  clarifications: string[]
  answers: string
  steps: DesignStep[]
}

export interface DesignStep {
  id: string
  title: string
  action: string
  doneWhen: string
  onEmpty: string
  onError: string
  system: string
}

function asText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function asList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => asText(item)).filter(Boolean)
}

export function extractJsonObject(text: string): { data: Record<string, unknown>; prefix: string } | null {
  const objects = extractJsonObjects(text)
  if (!objects.length) return null
  return { data: objects[0].data, prefix: objects[0].prefix }
}

function extractJsonObjects(
  text: string
): { data: Record<string, unknown>; prefix: string; start: number; end: number }[] {
  const raw = text || ''
  const fence = /```(?:json)?\s*([\s\S]*?)```/i.exec(raw)
  const source = fence ? fence[1] : raw
  const prefix = fence ? raw.slice(0, fence.index).trim() : ''
  const found: { data: Record<string, unknown>; prefix: string; start: number; end: number }[] = []
  let i = 0
  while (i < source.length) {
    const start = source.indexOf('{', i)
    if (start < 0) break
    let depth = 0
    let inStr = false
    let esc = false
    let closed = -1
    for (let j = start; j < source.length; j += 1) {
      const ch = source[j]
      if (inStr) {
        if (esc) esc = false
        else if (ch === '\\') esc = true
        else if (ch === '"') inStr = false
        continue
      }
      if (ch === '"') {
        inStr = true
        continue
      }
      if (ch === '{') depth += 1
      else if (ch === '}') {
        depth -= 1
        if (depth === 0) {
          closed = j
          break
        }
      }
    }
    if (closed < 0) break
    try {
      const parsed = JSON.parse(source.slice(start, closed + 1)) as unknown
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        found.push({
          data: parsed as Record<string, unknown>,
          prefix: found.length === 0 ? (fence ? prefix : source.slice(0, start).trim()) : '',
          start,
          end: closed
        })
      }
    } catch {
      /* skip invalid */
    }
    i = closed + 1
  }
  return found
}

function formatVerdictMarkdown(data: Record<string, unknown>): string | null {
  const verdict = asText(data.verdict).toLowerCase()
  if (!verdict) return null
  const reason = asText(data.reason)
  if (verdict === 'acceptable') {
    return reason ? `**Допустимо.** ${reason}` : '**Допустимо.**'
  }
  if (verdict === 'rejected' || verdict === 'escalate' || verdict === 'denied') {
    return reason ? `**Отказано.** ${reason}` : '**Отказано.**'
  }
  return null
}

function isDesignDraft(data: Record<string, unknown>): boolean {
  return Boolean(
    data.steps ||
      data.goal ||
      data.result ||
      data.required_clarifications ||
      data.confirmation_points ||
      data.when_to_run
  )
}

export function parseDesignDraft(data: Record<string, unknown>): DesignDraft | null {
  if (!isDesignDraft(data)) return null
  const steps: DesignStep[] = []
  const rawSteps = Array.isArray(data.steps) ? data.steps : []
  rawSteps.forEach((raw, index) => {
    if (!raw || typeof raw !== 'object') return
    const step = raw as Record<string, unknown>
    const action = asText(step.action) || asText(step.operation) || asText(step.title)
    steps.push({
      id: asText(step.id) || `s${index + 1}`,
      title: asText(step.title) || action || `Шаг ${index + 1}`,
      action,
      doneWhen: asText(step.done_when) || asText(step.doneWhen),
      onEmpty: asText(step.on_empty) || asText(step.onEmpty),
      onError: asText(step.on_error) || asText(step.onError),
      system: asText(step.system)
    })
  })
  return {
    title: asText(data.title),
    goal: asText(data.goal),
    whenToRun: asText(data.when_to_run) || asText(data.whenToRun),
    result: asText(data.result),
    recipient: asText(data.recipient),
    inputs: asList(data.inputs),
    confirmations: asList(data.confirmation_points).concat(asList(data.confirmationPoints)),
    clarifications: asList(data.required_clarifications).concat(asList(data.requiredClarifications)),
    answers: asText(data.answers),
    steps
  }
}

export function draftToMarkdown(draft: DesignDraft): string {
  const lines: string[] = ['## Черновик агента']
  if (draft.title) lines.push(`**${draft.title}**`)
  if (draft.goal) lines.push(`**Цель:** ${draft.goal}`)
  if (draft.whenToRun) lines.push(`**Когда запускать:** ${draft.whenToRun}`)
  if (draft.result) lines.push(`**Итог:** ${draft.result}`)
  if (draft.recipient) lines.push(`**Кому:** ${draft.recipient}`)
  if (draft.inputs.length) {
    lines.push('', '**Входы:**')
    for (const item of draft.inputs) lines.push(`- ${item}`)
  }
  if (draft.confirmations.length) {
    lines.push('', '**Точки подтверждения:**')
    for (const item of draft.confirmations) lines.push(`- ${item}`)
  }
  if (draft.answers) {
    lines.push('', `**Ответы:** ${draft.answers}`)
  }
  if (draft.steps.length) {
    lines.push('', '### Шаги')
    for (const step of draft.steps) {
      const head = step.id && step.title !== step.id ? `${step.id} — ${step.title}` : step.title
      lines.push(`- **${head}**`)
      if (step.action && step.action !== step.title) lines.push(`  ${step.action}`)
      if (step.system) lines.push(`  Система: ${step.system}`)
      if (step.doneWhen) lines.push(`  Готово когда: ${step.doneWhen}`)
      if (step.onEmpty) lines.push(`  Если пусто: ${step.onEmpty}`)
      if (step.onError) lines.push(`  Если ошибка: ${step.onError}`)
    }
  }
  if (draft.clarifications.length) {
    lines.push('', '**Ещё нужно уточнить:**')
    for (const item of draft.clarifications) lines.push(`- ${item}`)
  }
  return lines.join('\n')
}

export function presentAgentText(text: string): string {
  const objects = extractJsonObjects(text)
  if (!objects.length) return text
  const verdicts = objects.map((item) => formatVerdictMarkdown(item.data))
  if (verdicts.every(Boolean)) {
    const body = verdicts.join('\n\n')
    const prefix = objects[0].prefix
    return prefix ? `${prefix}\n\n${body}` : body
  }
  const extracted = objects[0]
  const draft = parseDesignDraft(extracted.data)
  if (!draft) return text
  const decoded = draftToMarkdown(draft)
  return extracted.prefix ? `${extracted.prefix}\n\n${decoded}` : decoded
}
