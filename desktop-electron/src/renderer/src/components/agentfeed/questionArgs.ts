/** Parse askQuestion arguments the same way desktop runner.questionPayload does. */

function asText(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>
    return (
      asText(record.label) ||
      asText(record.text) ||
      asText(record.value) ||
      asText(record.question) ||
      asText(record.title)
    )
  }
  return ''
}

function asRecord(value: unknown): Record<string, unknown> {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>
  }
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
      try {
        const parsed = JSON.parse(trimmed) as unknown
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          return parsed as Record<string, unknown>
        }
      } catch {
        return {}
      }
    }
  }
  return {}
}

function asOptions(raw: unknown): string[] {
  if (Array.isArray(raw)) {
    return raw.map(asText).filter(Boolean).slice(0, 6)
  }
  if (typeof raw === 'string') {
    return raw
      .split(/\r?\n|;/)
      .map((line) => line.replace(/^(?:[-•*]|\(?[A-Da-dа-гА-Г]\)?[).:])\s+/, '').trim())
      .filter(Boolean)
      .slice(0, 6)
  }
  return []
}

function optionsFromText(text: string): string[] {
  const found: string[] = []
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim()
    const match = /^(?:[-•*]|\(?[A-Da-dа-гА-Г]\)?[).:]|\d+[).])\s+(.+)$/.exec(line)
    if (!match) continue
    const value = match[1].trim()
    if (value && !value.endsWith('?')) found.push(value)
    if (found.length >= 6) break
  }
  return found
}

function asBool(value: unknown): boolean {
  if (typeof value === 'boolean') return value
  const text = String(value || '').trim().toLowerCase()
  return text === '1' || text === 'true' || text === 'yes'
}

function acceptList(raw: unknown): string[] {
  const allowed = new Set(['xlsx', 'xlsm', 'docx'])
  const items = Array.isArray(raw) ? raw : raw ? [raw] : []
  const out: string[] = []
  for (const item of items) {
    const ext = String(item || '')
      .trim()
      .toLowerCase()
      .replace(/^\./, '')
    if (allowed.has(ext) && !out.includes(ext)) out.push(ext)
  }
  return out
}

export function parseQuestionArgs(raw: unknown): {
  question: string
  options: string[]
  needsFile: boolean
  accept: string[]
} {
  const args = asRecord(raw)
  const nested = asRecord(args.arguments || args.input || args.properties)
  const source = Object.keys(nested).length ? { ...nested, ...args } : args
  const question =
    asText(source.question) ||
    asText(source.prompt) ||
    asText(source.title) ||
    asText(source.message) ||
    asText(source.text)
  const needsFile = asBool(source.needsFile ?? source.needs_file ?? source.expectFile)
  let accept = acceptList(source.accept || source.allowedExtensions)
  if (needsFile && !accept.length) accept = ['xlsx', 'xlsm', 'docx']
  let options = asOptions(source.options)
  if (!options.length) options = asOptions(source.choices)
  if (!options.length) options = asOptions(source.answers)
  if (!options.length) options = asOptions(source.variants)
  if (!options.length && question && !needsFile) options = optionsFromText(question)
  return { question, options, needsFile, accept }
}

export function isAskQuestion(name: string): boolean {
  const folded = (name || '').trim().toLowerCase().replace(/_/g, '')
  return folded === 'askquestion'
}
