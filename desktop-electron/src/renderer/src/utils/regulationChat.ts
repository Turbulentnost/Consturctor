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

function unescapeJsonString(value: string): string {
  return value.replace(/\\n/g, '\n').replace(/\\"/g, '"')
}

function messageFromJsonish(value: string): string {
  const start = value.indexOf('{')
  if (start < 0) return ''
  const blob = value.slice(start)
  try {
    const parsed = JSON.parse(blob) as {
      message?: unknown
      nextQuestion?: { text?: unknown }
    }
    const next =
      parsed.nextQuestion && typeof parsed.nextQuestion === 'object'
        ? String(parsed.nextQuestion.text || '').trim()
        : ''
    return next || String(parsed.message || '').trim()
  } catch {
    const message = blob.match(/"message"\s*:\s*"((?:\\.|[^"\\])*)"?/)
    if (message) return unescapeJsonString(message[1]).trim()
    const text = blob.match(/"text"\s*:\s*"((?:\\.|[^"\\])*)"?/)
    return text ? unescapeJsonString(text[1]).trim() : ''
  }
}

function leadingProse(value: string): string {
  const trimmed = value.trim()
  if (!trimmed || trimmed.startsWith('{') || trimmed.startsWith('[')) return ''
  const fence = value.search(/\n\s*```(?:json)?\s*\n\s*\{/)
  if (fence >= 0) {
    const head = value.slice(0, fence).trim()
    return isProtocolChunk(head) ? '' : head
  }
  const block = value.search(/\n\s*\{/)
  if (block >= 0) {
    const head = value.slice(0, block).trim()
    return isProtocolChunk(head) ? '' : head
  }
  return isProtocolChunk(trimmed) ? '' : trimmed
}

export function visibleAssistantText(text: string): string {
  const value = text || ''
  if (!value.trim()) return ''
  const prose = leadingProse(value)
  if (prose) return prose
  return messageFromJsonish(value)
}

export function formatRegulationMessageTime(value: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const time = date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  const now = new Date()
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  if (sameDay) return time
  const day = date.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
  return `${day} ${time}`
}

export function isProcessSelectText(content: string): boolean {
  const text = (content || '').toLowerCase()
  return /отметьте нужн|отметьте процесс|выберите процесс|извлечены процессы/.test(text)
}

export function hasSelectedProcessesText(content: string): boolean {
  return /^\s*выбраны процессы\s*:/im.test(content || '')
}

export function rewriteSelectAfterChoice(raw: string, selectedIds: string[]): string {
  if (!selectedIds.length) return raw
  const listed = selectedIds.join(', ')
  const fallback = `По выбранному процессу (${listed}) уточните факт, которого нет в тексте документа.`
  const blob = extractInterviewAnswer(raw) || raw.trim()
  try {
    const parsed = JSON.parse(blob) as Record<string, unknown>
    const message = String(parsed.message || '')
    const nextQuestion =
      parsed.nextQuestion && typeof parsed.nextQuestion === 'object'
        ? (parsed.nextQuestion as Record<string, unknown>)
        : {}
    const pipeline =
      parsed.pipeline && typeof parsed.pipeline === 'object'
        ? (parsed.pipeline as Record<string, unknown>)
        : {}
    const stage = String(pipeline.stage || '').toLowerCase()
    if (!isProcessSelectText(message) && !isProcessSelectText(String(nextQuestion.text || '')) && stage !== 'select') {
      return raw
    }
    parsed.status = 'need_more'
    parsed.message = fallback
    parsed.pipeline = {
      ...pipeline,
      stage: 'questions',
      selectedProcessIds: selectedIds
    }
    parsed.nextQuestion = {
      ...nextQuestion,
      text: fallback,
      processId: nextQuestion.processId || selectedIds[0]
    }
    return JSON.stringify(parsed)
  } catch {
    return isProcessSelectText(raw) ? fallback : raw
  }
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
            if (
              status &&
              status !== 'need_more' &&
              status !== 'ready' &&
              status !== 'question' &&
              status !== 'in_progress'
            ) {
              break
            }
            if (!status && !String(parsed.message || '').trim()) {
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
