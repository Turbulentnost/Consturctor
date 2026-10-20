const PLACEHOLDER = 'Агент анализирует задачу…'

/**
 * Short pieces are real deltas: «та» in «Карташова» may already occur earlier in the text.
 * Only a replayed piece at least this long counts as a duplicate.
 */
const REPLAY_MIN_CHARS = 32

export function streamDelta(streamed: string, chunk: string): string {
  if (!chunk) return ''
  if (!streamed) return chunk
  if (chunk.startsWith(streamed)) return chunk.slice(streamed.length)
  if (chunk.length < REPLAY_MIN_CHARS) return chunk
  if (streamed.includes(chunk)) return ''
  for (let overlap = Math.min(streamed.length, chunk.length - 1); overlap >= REPLAY_MIN_CHARS; overlap -= 1) {
    if (streamed.endsWith(chunk.slice(0, overlap))) return chunk.slice(overlap)
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
