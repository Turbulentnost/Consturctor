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
  'вложения этого прогона',
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
  'это прогон',
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

// First-person process narration ("Снимаю свежие карточки", "открываю календари")
// belongs to «Ход работы», never to «Результат».
const NARRATION_START =
  /^(сначала |сейчас |далее |затем |потом |теперь |параллельно )*(снимаю|сниму|снял|открываю|открою|открыл|смотрю|посмотрю|читаю|прочитаю|проверяю|проверю|запрашиваю|запрошу|загружаю|загружу|беру|возьму|собираю|соберу|анализирую|сверяю|сверю|уточняю|уточню|планирую|формирую|составляю|начинаю|перехожу|вызываю)\b/i

const NAMED_HEADINGS = ['RESULT', 'Результат', 'Итог']

function fold(value: string): string {
  return (value || '').toLowerCase().replace(/ё/g, 'е')
}

export function isPlaceholderResult(text: string): boolean {
  const value = fold(text).trim()
  if (!value) return true
  return PLACEHOLDERS.some((marker) => value.includes(marker))
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
  if (NARRATION_START.test(stripped)) return true
  if (/^[a-z][a-z0-9_.]{2,48}$/.test(text)) return true
  if (text.startsWith('{') && (text.includes('"tool"') || text.includes('constructor'))) return true
  if (text.includes('odata') && (text.includes('недоступ') || text.includes('ошиб') || text.includes('читаю'))) {
    return true
  }
  return false
}

function stripJunkParagraphs(text: string): string {
  const blocks = (text || '').split(/\n{2,}/)
  const kept: string[] = []
  for (const block of blocks) {
    const lines = block.split('\n')
    const useful = lines.filter((line) => {
      const trimmed = line.trim()
      return !trimmed || !isJunkLine(trimmed)
    })
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

function cleanText(raw: string): string {
  const stripped = stripToolFences(raw)
  if (!stripped || isPlaceholderResult(stripped)) return ''
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
  if (last) return last
  if (!allowAssistantFallback) return ''
  for (const event of events) {
    const type = String(event.type || '').toLowerCase()
    if (type !== 'assistant' && type !== 'agent_message') continue
    const raw = eventText(event)
    if (isMostlyJunk(raw)) continue
    const cleaned = cleanText(raw)
    if (cleaned) last = cleaned
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
  const fromEvent = fromEvents(events, !terminatedBad)
  // For cancelled/errored runs the raw answer is usually partial narration, not a result.
  const fromAnswer = terminatedBad ? '' : cleanText(rawAnswer)
  const text = preferLongerResult(fromEvent, fromAnswer) || fromEvent || fromAnswer
  if (!text) return { text: '', emptyHint: emptyHint(input.status || '', rawAnswer) }
  return { text, emptyHint: '' }
}
