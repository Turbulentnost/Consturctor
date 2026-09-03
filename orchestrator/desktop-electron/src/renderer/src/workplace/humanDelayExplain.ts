/** Critical human-delay threshold (minutes) for explanation form. */
export const CRITICAL_HUMAN_DELAY_MIN = 60

const STORAGE_KEY = 'orchestrator.kpi.humanDelayExplain'

export type HumanDelayVerdict = 'acceptable' | 'escalate'

export type HumanDelayExplainStatus = 'idle' | 'evaluating' | 'done' | 'error'

export interface HumanDelayExplainRecord {
  status: HumanDelayExplainStatus
  verdict: HumanDelayVerdict | null
  reason: string
  delayMinutes: number
  explanation: string
  at: string
  workflowId: string
  periodKey: string
  toast?: string
}

function storageBucket(): Record<string, HumanDelayExplainRecord> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Record<string, HumanDelayExplainRecord>
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function saveBucket(bucket: Record<string, HumanDelayExplainRecord>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(bucket))
  } catch {
    /* ignore quota */
  }
}

export function explainStorageKey(userId: string, periodKey: string): string {
  return `${userId || 'anon'}::${periodKey}`
}

export function loadExplainRecord(userId: string, periodKey: string): HumanDelayExplainRecord | null {
  const item = storageBucket()[explainStorageKey(userId, periodKey)]
  return item || null
}

export function saveExplainRecord(
  userId: string,
  periodKey: string,
  record: HumanDelayExplainRecord
): void {
  const bucket = storageBucket()
  bucket[explainStorageKey(userId, periodKey)] = record
  saveBucket(bucket)
}

export function buildExplainPrompt(input: {
  delayMinutes: number
  processes: Array<{ title: string; humanDelayMinutes: number }>
  explanation: string
}): string {
  const processLines = input.processes
    .map((item) => `- ${item.title}: ${item.humanDelayMinutes} мин`)
    .join('\n')
  return [
    'Оцени объяснительную по задержке ответа человека.',
    `Задержка: ${input.delayMinutes} мин (порог риска > ${CRITICAL_HUMAN_DELAY_MIN}).`,
    'Процессы:',
    processLines || '- (нет детализации)',
    `Объяснительная: "${input.explanation.trim()}"`,
    'Ответь ТОЛЬКО JSON: {"verdict":"acceptable"|"escalate","reason":"..."}',
    'verdict=acceptable — опоздание допустимо исходя из объяснительной.',
    'verdict=escalate — требуется проверка вышестоящего руководителя.',
    'Не вызывай инструменты, не задавай вопросов.'
  ].join('\n')
}

export function parseExplainVerdict(raw: string): { verdict: HumanDelayVerdict; reason: string } | null {
  const text = (raw || '').trim()
  if (!text) return null
  const jsonMatch = text.match(/\{[\s\S]*\}/)
  if (jsonMatch) {
    try {
      const parsed = JSON.parse(jsonMatch[0]) as { verdict?: string; reason?: string }
      const verdictRaw = String(parsed.verdict || '').toLowerCase()
      const reason = String(parsed.reason || '').trim()
      if (verdictRaw === 'acceptable' || verdictRaw === 'escalate') {
        return { verdict: verdictRaw, reason: reason || 'Без подробностей' }
      }
      if (verdictRaw.includes('accept') || verdictRaw.includes('допустим')) {
        return { verdict: 'acceptable', reason: reason || 'Допустимо' }
      }
      if (verdictRaw.includes('escal') || verdictRaw.includes('проверк') || verdictRaw.includes('руковод')) {
        return { verdict: 'escalate', reason: reason || 'Нужна проверка руководителя' }
      }
    } catch {
      /* fall through to keywords */
    }
  }
  const folded = text.toLowerCase()
  if (
    folded.includes('"verdict":"acceptable"') ||
    folded.includes('допустим') ||
    folded.includes('acceptable')
  ) {
    if (folded.includes('escal') || folded.includes('руковод') || folded.includes('проверк')) {
      if (folded.indexOf('escal') < folded.indexOf('допустим') || folded.includes('требуется провер')) {
        return { verdict: 'escalate', reason: text.slice(0, 280) }
      }
    }
    return { verdict: 'acceptable', reason: text.slice(0, 280) }
  }
  if (
    folded.includes('escalate') ||
    folded.includes('руковод') ||
    folded.includes('проверк') ||
    folded.includes('недопустим')
  ) {
    return { verdict: 'escalate', reason: text.slice(0, 280) }
  }
  return null
}
