import type { AgentRunnerEvent } from '../api/types'
import { presentAgentText } from '../components/agentfeed/formatAgentText'

const PLACEHOLDERS = [
  'остановлено пользователем',
  'cursor sdk не отвечает',
  'агент уже выполняется',
  'запуск не завершился'
]

const JUNK_PHRASES = [
  'сначала прочитаю',
  'прочитаю регламент',
  'журнал прошлого запуска',
  'вложения этого запуска',
  'вывод обрезан',
  'читаю разбор',
  'читаю регламент',
  'читаю materials',
  'com 1c',
  'com 1с',
  'constructor_tool',
  'outlook.read',
  'outlook.create',
  'outlook.search',
  'outlook.update',
  'askquestion',
  'жду подтвержд',
  'это запуск',
  'cursor sdk',
  'tests: pass',
  'tests: fail',
  'tool_call',
  'tool_result',
  'human-in-the-loop',
  'требуется hitl',
  'запрос hitl'
]

const JUNK_LINE_START =
  /^(сначала |сейчас |далее |затем |потом )?(прочитаю|читаю|вызову|открою журнал|проверю журнал|проверю вложен)/i

const PROCESS_PREFIX = /^(сначала |сейчас |далее |затем |потом |теперь |параллельно )+/i

// Tool-ish first person: "Открываю календари", "Снимаю карточки".
const PROCESS_VERBS =
  /^(снимаю|сниму|снял|открываю|открою|открыл|смотрю|посмотрю|читаю|прочитаю|запрашиваю|запрошу|загружаю|загружу|беру|возьму|начинаю|перехожу|вызываю)(?=$|[\s,.;:!?«»"'()])/i

// Same verbs are often the actual deliverable ("Планирую совещания…").
// Treat as narration only with an explicit process prefix.
const RESULT_LIKE_VERBS =
  /^(проверяю|проверю|собираю|соберу|анализирую|сверяю|сверю|уточняю|уточню|планирую|формирую|составляю)(?=$|[\s,.;:!?«»"'()])/i

const CONTINUATION_START = /^(и|а|но|или|чтобы|для|его|её|ее|их|этого|этой|этом)\b/i

const NAMED_HEADINGS = ['RESULT', 'Результат', 'Итог']

function fold(value: string): string {
  return (value || '').toLowerCase().replace(/ё/g, 'е')
}

export function isPlaceholderResult(text: string): boolean {
  const value = fold(text).trim()
  if (!value) return true
  return PLACEHOLDERS.some((marker) => value.includes(marker))
}

const WORK_RESULT_RE = /^[ \t]*#{0,6}[ \t]*WORK[ _]?RESULT\b.*$/im

function lastUsefulPrefix(before: string): string {
  const text = (before || '').trim()
  if (!text) return ''
  const paras = text
    .split(/\n{2,}/)
    .map((item) => item.trim())
    .filter(Boolean)
  for (let i = paras.length - 1; i >= 0; i -= 1) {
    if (!isMostlyJunk(paras[i])) return paras[i].replace(/[ \t]+/g, ' ').trim()
  }
  return paras[paras.length - 1] || text
}

export function stripToWorkResult(text: string): string {
  const raw = text || ''
  const match = WORK_RESULT_RE.exec(raw)
  if (!match || match.index === undefined) return raw.trim()
  const before = raw.slice(0, match.index).trim()
  const after = raw.slice(match.index).trim()
  const body = stripWorkResultChrome(after)
  if (before && body && isContinuationFragment(body)) {
    const prefix = lastUsefulPrefix(before)
    if (prefix) return `${prefix} ${body}`.replace(/[ \t]+/g, ' ').trim()
  }
  if (before && body && isBrokenResultText(body)) {
    const useful = stripJunkParagraphs(before) || lastUsefulPrefix(before)
    if (useful && !isMostlyJunk(useful) && !isBrokenResultText(useful) && useful.length >= body.length) {
      return useful
    }
  }
  if (before && body && body.length < 48 && before.length > body.length * 2) {
    const useful = stripJunkParagraphs(before) || lastUsefulPrefix(before)
    if (useful && useful.length > body.length) return useful
  }
  return after
}

export function hasWorkResultMarker(text: string): boolean {
  return WORK_RESULT_RE.test(text || '')
}

function stripWorkResultChrome(text: string): string {
  return (text || '')
    .replace(/^[ \t]*#{0,6}[ \t]*WORK[ _]?RESULT\s*:?\s*/im, '')
    .replace(/^\s*TESTS:\s*(PASS|FAIL)\s*$/gim, '')
    .trim()
}

function stripToolFences(text: string): string {
  let cleaned = (text || '').replace(/\ufffd/g, '')
  if (!cleaned.includes('```constructor_tool') && !cleaned.includes('```tool')) return cleaned.trim()
  const out: string[] = []
  let skip = false
  for (const line of cleaned.split('\n')) {
    const fence = line.trim()
    if (fence.startsWith('```constructor_tool') || fence.startsWith('```tool')) {
      skip = true
      continue
    }
    if (skip && fence.startsWith('```')) {
      skip = false
      continue
    }
    if (!skip) out.push(line)
  }
  return out.join('\n').trim()
}

function extractNamedSection(text: string, heading: string): string {
  const escaped = heading.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const pattern = new RegExp(
    `(?:^|\\n)\\s*(?:#+\\s*)?${escaped}\\s*:?\\s*([\\s\\S]*?)(?=\\n\\s*(?:FILES|ACTIONS|NOTIFICATIONS|SCHEDULE|CLARIFY|ХОД)\\s*:|\\n\`\`\`|$)`,
    'i'
  )
  const match = pattern.exec(text || '')
  return (match?.[1] || '').trim()
}

function isNarrationLine(line: string): boolean {
  const stripped = (line || '').replace(/^[.\s—-]+/, '').trim()
  if (!stripped) return false
  if (PROCESS_VERBS.test(stripped)) return true
  const withoutPrefix = stripped.replace(PROCESS_PREFIX, '')
  if (withoutPrefix === stripped) return false
  return PROCESS_VERBS.test(withoutPrefix) || RESULT_LIKE_VERBS.test(withoutPrefix)
}

function isContinuationFragment(text: string): boolean {
  const value = (text || '').trim()
  if (!value) return false
  return CONTINUATION_START.test(value)
}

/** Обрубок: начало с середины слова/фразы или со служебного союза. */
export function isBrokenResultText(text: string): boolean {
  const value = (text || '').trim()
  if (!value) return true
  if (isContinuationFragment(value)) return true
  return /^[а-яёa-z]/.test(value)
}

function isJunkLine(line: string): boolean {
  const raw = (line || '').trim()
  const stripped = raw.replace(/^[.\s—-]+/, '')
  const text = fold(raw)
  if (!text) return true
  if (text.startsWith('```')) return true
  if (text.startsWith('thinking')) return true
  if (text.startsWith('clarify')) return true
  if (/^tests:\s*(pass|fail)/i.test(raw)) return true
  if (JUNK_PHRASES.some((marker) => text.includes(marker))) return true
  if (JUNK_LINE_START.test(raw)) return true
  if (isNarrationLine(stripped)) return true
  if (/^[a-z][a-z0-9_.]{2,48}$/.test(text)) return true
  if (text.startsWith('{') && (text.includes('"tool"') || text.includes('constructor'))) return true
  if (text.includes('odata') && (text.includes('недоступ') || text.includes('ошиб') || text.includes('читаю'))) {
    return true
  }
  return false
}

function nextKeptLine(lines: string[], from: number): string {
  for (let i = from; i < lines.length; i += 1) {
    const trimmed = lines[i].trim()
    if (trimmed && !isJunkLine(trimmed)) return trimmed
  }
  return ''
}

function stripJunkParagraphs(text: string): string {
  const blocks = (text || '').split(/\n{2,}/)
  const kept: string[] = []
  for (const block of blocks) {
    const lines = block.split('\n')
    const useful: string[] = []
    for (let i = 0; i < lines.length; i += 1) {
      const trimmed = lines[i].trim()
      if (!trimmed) {
        useful.push(lines[i])
        continue
      }
      if (!isJunkLine(trimmed)) {
        useful.push(lines[i])
        continue
      }
      // Dropping "Планирую совещания…" must not leave "и его календарь…".
      if (isContinuationFragment(nextKeptLine(lines, i + 1))) {
        useful.push(lines[i])
      }
    }
    const keptLines = useful.filter((line) => line.trim())
    const sourceLines = lines.filter((line) => line.trim())
    if (!keptLines.length) continue
    if (sourceLines.length && keptLines.length / sourceLines.length < 0.35) continue
    kept.push(useful.join('\n').trim())
  }
  return kept.join('\n\n').trim()
}

function stripResultHeading(text: string): string {
  return text.replace(/^\s*(?:#{1,3}\s*)?(?:RESULT|Результат|Итог)\s*:?\s*/i, '').trim()
}

function preferLongerResult(named: string, full: string): string {
  const short = (named || '').trim()
  const long = (full || '').trim()
  if (!short) return long
  if (!long) return short
  if (short.length < 40 && long.length > short.length * 2) return long
  if (long.includes(short) && long.length > short.length + 20) return long
  return short
}

function looksTruncatedResult(text: string, source: string): boolean {
  const body = (text || '').trim()
  const full = (source || '').trim()
  if (!body) return Boolean(full)
  if (isBrokenResultText(body) && full.length > body.length) return true
  return body.length < 48 && full.length > body.length * 2
}

function cleanText(raw: string): string {
  const stripped = stripToolFences(raw)
  if (!stripped || isPlaceholderResult(stripped)) return ''
  if (hasWorkResultMarker(stripped)) {
    const body = stripWorkResultChrome(stripToWorkResult(stripped))
    if (body && !isPlaceholderResult(body) && !isBrokenResultText(body)) {
      return presentAgentText(body).trim()
    }
  }
  const full = stripResultHeading(stripJunkParagraphs(stripped))
  let named = ''
  for (const heading of NAMED_HEADINGS) {
    const section = extractNamedSection(stripped, heading)
    if (section && !isPlaceholderResult(section) && !isMostlyJunk(section)) {
      named = stripResultHeading(section)
      break
    }
  }
  let body = preferLongerResult(named, full)
  const light = stripResultHeading(stripWorkResultChrome(stripToWorkResult(stripped)))
  if (looksTruncatedResult(body, light)) {
    body = preferLongerResult(body, light)
  }
  if (!body || isPlaceholderResult(body)) return ''
  if (body.length < 8 && isMostlyJunk(stripped)) return ''
  return presentAgentText(body).trim()
}

function isMostlyJunk(raw: string): boolean {
  const lines = (raw || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  if (!lines.length) return true
  const junk = lines.filter((line) => isJunkLine(line)).length
  return junk / lines.length >= 0.55
}

function eventText(event: AgentRunnerEvent): string {
  if (event.text) return String(event.text)
  if (event.message) return String(event.message)
  if (event.answer) return String(event.answer)
  const result = event.result
  if (typeof result === 'string') return result
  if (result && typeof result === 'object') {
    const row = result as Record<string, unknown>
    for (const key of ['text', 'answer', 'summary']) {
      if (typeof row[key] === 'string' && String(row[key]).trim()) return String(row[key])
    }
  }
  return ''
}

function fromEvents(events: AgentRunnerEvent[], allowAssistantFallback = true): string {
  const preferred = new Set(['work_result', 'final', 'result'])
  let last = ''
  for (const event of events) {
    const type = String(event.type || '').toLowerCase()
    if (!preferred.has(type)) continue
    const cleaned = cleanText(eventText(event))
    if (cleaned) last = cleaned
  }
  const truncated = !last || isBrokenResultText(last)
  if (last && !truncated) return last
  if (!allowAssistantFallback) return last
  for (const event of events) {
    const type = String(event.type || '').toLowerCase()
    if (type !== 'assistant' && type !== 'agent_message') continue
    const raw = eventText(event)
    if (isMostlyJunk(raw)) continue
    const cleaned = cleanText(raw)
    if (cleaned && cleaned.length > last.length) last = cleaned
  }
  return last
}

function emptyHint(status: string, answer: string): string {
  const key = (status || '').trim().toLowerCase()
  if (key === 'started' || key === 'running') return 'Запуск ещё выполняется.'
  if (key === 'error' || key === 'failed') return 'Результата нет. Запуск завершился с ошибкой.'
  if (key === 'canceled' || key === 'cancelled' || isPlaceholderResult(answer)) {
    return 'Результата нет. Запуск отменён.'
  }
  return 'Чистый результат не сохранился. Ход работы агента сюда не выводится.'
}

export function cleanRunResult(input: {
  answer?: string
  summary?: string
  events?: AgentRunnerEvent[]
  status?: string
}): { text: string; emptyHint: string } {
  const events = input.events || []
  const rawAnswer = (input.answer || input.summary || '').trim()
  const statusKey = (input.status || '').trim().toLowerCase()
  const terminatedBad =
    statusKey === 'canceled' ||
    statusKey === 'cancelled' ||
    statusKey === 'error' ||
    statusKey === 'failed'
  if (!terminatedBad && hasWorkResultMarker(rawAnswer)) {
    const fromStored = cleanText(rawAnswer)
    if (fromStored && !isBrokenResultText(fromStored)) {
      return { text: fromStored, emptyHint: '' }
    }
  }
  const fromAnswer = terminatedBad ? '' : cleanText(rawAnswer)
  const allowAssistant = !terminatedBad && (!fromAnswer || isBrokenResultText(fromAnswer))
  const fromEvent = fromEvents(events, allowAssistant)
  const text = preferLongerResult(fromEvent, fromAnswer) || fromEvent || fromAnswer
  if (!text) return { text: '', emptyHint: emptyHint(input.status || '', rawAnswer) }
  return { text, emptyHint: '' }
}
