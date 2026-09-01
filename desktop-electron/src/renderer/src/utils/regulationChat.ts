const PROTOCOL_KEY =
  /"(status|interview|document|quickAnswers|positions|roleStatus|actor|sourceRefs|triggerAction|userAction|openGaps|periodicity|functions)"\s*:/

export function isReplacementGarbage(text: string): boolean {
  const value = (text || '').trim()
  if (value.length < 8) return false
  const qmarks = (value.match(/\?/g) || []).length
  if (qmarks < 8) return false
  if (/[А-Яа-яЁё]/.test(value)) return false
  return qmarks >= Math.max(8, Math.floor(value.length / 3))
}

function isProtocolChunk(text: string): boolean {
  const value = text.trim()
  if (!value) return true
  if (/^[{}\[\]",:\s]+$/.test(value)) return true
  if (value.startsWith('{') || value.startsWith('[')) return true
  if (PROTOCOL_KEY.test(value)) return true
  if (/"[^"]+"\s*:/.test(value) && /[{}\[\],]/.test(value)) return true
  if (/:\s*"(belongs|foreign|unclear)/.test(value)) return true
  return false
}

function isAttachmentLine(line: string): boolean {
  const value = line.trim()
  if (!value) return false
  if (value.startsWith('📎')) return true
  if (/^приложены файлы\s*:/i.test(value)) return true
  return false
}

export function visibleUserText(text: string): string {
  const lines = (text || '').replace(/\r\n/g, '\n').split('\n')
  const hadAttachmentNote = lines.some((line) => isAttachmentLine(line))
  const noteNames = attachmentNamesFromContent(text)
  const body = lines
    .filter((line) => !isAttachmentLine(line))
    .join('\n')
    .trim()
  if (!body) return ''
  if (
    hadAttachmentNote &&
    noteNames.some((name) => name.toLowerCase() === body.toLowerCase())
  ) {
    return ''
  }
  return body
}

export function attachmentNamesFromContent(text: string): string[] {
  const names: string[] = []
  for (const line of (text || '').split(/\r?\n/)) {
    const value = line.trim()
    let rest = ''
    if (value.startsWith('📎')) {
      rest = value.replace(/^📎\s*/, '')
    } else if (/^приложены файлы\s*:/i.test(value)) {
      rest = value.replace(/^приложены файлы\s*:/i, '')
    } else {
      continue
    }
    for (const part of rest.split(',')) {
      const name = part.trim()
      if (name) names.push(name)
    }
  }
  return names
}

export function visibleAssistantText(text: string): string {
  const value = (text || '').trim()
  if (!value) return ''
  if (value.startsWith('{')) {
    try {
      const parsed = JSON.parse(value) as { message?: unknown }
      return String(parsed.message || '').trim()
    } catch {
      const match = value.match(/"message"\s*:\s*"((?:\\.|[^"\\])*)"/)
      return match ? match[1].replace(/\\n/g, '\n').replace(/\\"/g, '"') : ''
    }
  }
  return isProtocolChunk(value) ? '' : value
}

export function extractInterviewAnswer(raw: string): string {
  const text = raw || ''
  let start = text.indexOf('{')
  while (start >= 0) {
    let depth = 0
    let inStr = false
    let esc = false
    for (let i = start; i < text.length; i += 1) {
      const ch = text[i]
      if (inStr) {
        if (esc) {
          esc = false
          continue
        }
        if (ch === '\\') {
          esc = true
          continue
        }
        if (ch === '"') inStr = false
        continue
      }
      if (ch === '"') {
        inStr = true
        continue
      }
      if (ch === '{') depth += 1
      if (ch === '}') {
        depth -= 1
        if (depth === 0) {
          const blob = text.slice(start, i + 1)
          try {
            const parsed = JSON.parse(blob) as { status?: unknown; message?: unknown }
            const status = String(parsed.status || '')
            if (status !== 'need_more' && status !== 'ready') {
              break
            }
            if (isReplacementGarbage(String(parsed.message || '')) || isReplacementGarbage(blob)) {
              return ''
            }
            return blob
          } catch {
            break
          }
        }
      }
    }
    start = text.indexOf('{', start + 1)
  }
  return ''
}
