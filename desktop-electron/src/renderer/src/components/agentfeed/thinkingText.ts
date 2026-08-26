const PLACEHOLDER = 'Агент анализирует задачу…'

export function streamDelta(streamed: string, chunk: string): string {
  if (!chunk) return ''
  if (!streamed) return chunk
  if (chunk.startsWith(streamed)) return chunk.slice(streamed.length)
  if (streamed.endsWith(chunk) || streamed.includes(chunk)) return ''
  let overlap = Math.min(streamed.length, chunk.length)
  while (overlap > 0) {
    if (streamed.endsWith(chunk.slice(0, overlap))) return chunk.slice(overlap)
    overlap -= 1
  }
  return chunk
}

/** Keep chunk whitespace: trim() glued words like "Закрыт" + "первый". */
export function appendThinkingText(prev: string, incoming: string): string {
  const chunk = (incoming || '').replace(/\uFFFD/g, '')
  const trimmed = chunk.trim()
  if (trimmed.startsWith('{') || trimmed.toLowerCase().includes('traceback')) {
    return prev || PLACEHOLDER
  }
  if (!chunk) return prev || PLACEHOLDER
  const base = prev === PLACEHOLDER ? '' : prev
  const next = base + streamDelta(base, chunk)
  return next || PLACEHOLDER
}
