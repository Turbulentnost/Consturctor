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

export function parseQuestionArgs(raw: unknown): { question: string; options: string[] } {
  const args = asRecord(raw)
  const nested = asRecord(args.arguments || args.input || args.properties)
  const source = Object.keys(nested).length ? { ...nested, ...args } : args
  const question =
    asText(source.question) ||
    asText(source.prompt) ||
    asText(source.title) ||
    asText(source.message) ||
    asText(source.text)
  let options = asOptions(source.options)
  if (!options.length) options = asOptions(source.choices)
  if (!options.length) options = asOptions(source.answers)
  if (!options.length) options = asOptions(source.variants)
  if (!options.length && question) options = optionsFromText(question)
  return { question, options }
}

export function isAskQuestion(name: string): boolean {
  const folded = (name || '').trim().toLowerCase().replace(/_/g, '')
  return folded === 'askquestion'
}
