/** Critical human-delay threshold (minutes) for explanation form. */
export const CRITICAL_HUMAN_DELAY_MIN = 60
export const EXPLAIN_BAN_MS = 60 * 60 * 1000

const STORAGE_KEY = 'orchestrator.kpi.humanDelayExplain'

export type HumanDelayVerdict = 'acceptable' | 'rejected'

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
  /** Local sidecar run id while status === evaluating. */
  runId?: string
  toast?: string
  /** Full write-off of overdue human response time after «Допустимо». */
  writtenOff?: boolean
  /** Ban writing a new explanation until this ISO timestamp («Отказано»). */
  banUntil?: string
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

/** Approximate window length in days for period-key comparison. */
export function periodSpanDays(periodKey: string): number {
  const key = (periodKey || '').trim()
  if (key === 'range:7') return 7
  if (key === 'range:30') return 30
  if (key === 'range:90') return 90
  if (key.startsWith('month:')) return 31
  if (key.startsWith('date:')) return 1
  return 0
}

function isWriteOffRecord(record: HumanDelayExplainRecord | null | undefined): boolean {
  if (!record) return false
  return Boolean(record.writtenOff) || (record.status === 'done' && record.verdict === 'acceptable')
}

/**
 * Load explain state for the active period.
 * Write-off from a larger window also applies to a smaller one (30д → 7д).
 * Exact-period evaluating / rejected / error stay preferred.
 */
export function loadEffectiveExplainRecord(
  userId: string,
  periodKey: string
): HumanDelayExplainRecord | null {
  const exact = loadExplainRecord(userId, periodKey)
  if (exact?.status === 'evaluating' || exact?.status === 'error') return exact
  if (exact?.status === 'done' && exact.verdict === 'rejected') return exact
  if (isWriteOffRecord(exact)) {
    return { ...exact, writtenOff: true }
  }

  const prefix = `${userId || 'anon'}::`
  const currentSpan = periodSpanDays(periodKey)
  if (currentSpan <= 0) return exact

  const covering: HumanDelayExplainRecord[] = []
  for (const [key, record] of Object.entries(storageBucket())) {
    if (!key.startsWith(prefix) || !record || typeof record !== 'object') continue
    if (!isWriteOffRecord(record)) continue
    const recordPeriod = record.periodKey || key.slice(prefix.length)
    const span = periodSpanDays(recordPeriod)
    if (span >= currentSpan) covering.push(record)
  }
  if (!covering.length) return exact

  covering.sort((a, b) => periodSpanDays(a.periodKey) - periodSpanDays(b.periodKey))
  const best = covering[0]
  return {
    ...best,
    writtenOff: true,
    status: 'done',
    verdict: 'acceptable',
    periodKey
  }
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

export function clearExplainRecord(userId: string, periodKey: string): void {
  const bucket = storageBucket()
  delete bucket[explainStorageKey(userId, periodKey)]
  saveBucket(bucket)
}

export function explainBanRemainingMs(record: HumanDelayExplainRecord | null, now = Date.now()): number {
  if (!record?.banUntil) return 0
  const until = Date.parse(record.banUntil)
  if (!Number.isFinite(until)) return 0
  return Math.max(0, until - now)
}

export function formatBanRemaining(ms: number): string {
  if (ms <= 0) return ''
  const totalMin = Math.max(1, Math.ceil(ms / 60000))
  if (totalMin < 60) return `${totalMin} мин`
  const hours = Math.floor(totalMin / 60)
  const mins = totalMin % 60
  return mins ? `${hours} ч ${mins} мин` : `${hours} ч`
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
    'Ответь ТОЛЬКО JSON: {"verdict":"acceptable"|"rejected","reason":"..."}',
    'verdict=acceptable — опоздание допустимо; просроченное время будет списано.',
    'verdict=rejected — объяснительная отклонена; писать новую нельзя 1 час.',
    'Не вызывай инструменты, не задавай вопросов.'
  ].join('\n')
}

export function parseExplainVerdict(raw: string): { verdict: HumanDelayVerdict; reason: string } | null {
  const text = (raw || '').trim()
  if (!text) return null
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/i)
  const body = (fenced?.[1] || text).trim()

  const objects = extractJsonObjects(body)
  for (const chunk of [...objects].reverse()) {
    try {
      const parsed = JSON.parse(chunk) as { verdict?: string; reason?: string }
      const mapped = mapVerdict(parsed.verdict, parsed.reason)
      if (mapped) return mapped
    } catch {
      /* try next */
    }
  }

  const folded = text.toLowerCase()
  if (folded.includes('допустим') || folded.includes('acceptable')) {
    if (folded.includes('отказ') || folded.includes('reject') || folded.includes('недопустим')) {
      return { verdict: 'rejected', reason: 'Объяснительная отклонена' }
    }
    return { verdict: 'acceptable', reason: 'Опоздание признано допустимым' }
  }
  if (
    folded.includes('rejected') ||
    folded.includes('отказ') ||
    folded.includes('escalate') ||
    folded.includes('недопустим') ||
    folded.includes('руковод')
  ) {
    return { verdict: 'rejected', reason: 'Объяснительная отклонена' }
  }
  return null
}

function mapVerdict(
  verdictRawInput: unknown,
  reasonRaw: unknown
): { verdict: HumanDelayVerdict; reason: string } | null {
  const verdictRaw = String(verdictRawInput || '')
    .toLowerCase()
    .trim()
  const reason = sanitizeExplainReason(String(reasonRaw || '').trim())
  if (!verdictRaw) return null
  if (verdictRaw === 'acceptable') {
    return { verdict: 'acceptable', reason: reason || 'Опоздание признано допустимым' }
  }
  if (verdictRaw === 'rejected' || verdictRaw === 'escalate' || verdictRaw === 'denied') {
    return { verdict: 'rejected', reason: reason || 'Объяснительная отклонена' }
  }
  if (verdictRaw.includes('accept') || verdictRaw.includes('допустим')) {
    return { verdict: 'acceptable', reason: reason || 'Опоздание признано допустимым' }
  }
  if (
    verdictRaw.includes('reject') ||
    verdictRaw.includes('отказ') ||
    verdictRaw.includes('escal') ||
    verdictRaw.includes('проверк') ||
    verdictRaw.includes('руковод')
  ) {
    return { verdict: 'rejected', reason: reason || 'Объяснительная отклонена' }
  }
  return null
}

/** Pull top-level JSON objects even when the agent concatenates several. */
function extractJsonObjects(text: string): string[] {
  const out: string[] = []
  let i = 0
  while (i < text.length) {
    const start = text.indexOf('{', i)
    if (start < 0) break
    let depth = 0
    let inStr = false
    let esc = false
    let closed = false
    for (let j = start; j < text.length; j += 1) {
      const ch = text[j]
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
          out.push(text.slice(start, j + 1))
          i = j + 1
          closed = true
          break
        }
      }
    }
    if (!closed) break
  }
  return out
}

/** Human-readable reason only — never dump raw JSON into the UI. */
export function sanitizeExplainReason(raw: string): string {
  const text = (raw || '').trim()
  if (!text) return ''
  if (text.startsWith('{') || text.includes('"verdict"')) {
    const objects = extractJsonObjects(text)
    for (const chunk of [...objects].reverse()) {
      try {
        const parsed = JSON.parse(chunk) as { reason?: string; verdict?: string }
        const reason = String(parsed.reason || '').trim()
        if (reason && !reason.startsWith('{')) return reason.slice(0, 320)
        const verdict = String(parsed.verdict || '').toLowerCase()
        if (verdict === 'acceptable') return 'Опоздание признано допустимым'
        if (verdict === 'rejected' || verdict === 'escalate') return 'Объяснительная отклонена'
      } catch {
        /* continue */
      }
    }
    return ''
  }
  return text.replace(/\s+/g, ' ').slice(0, 320)
}
