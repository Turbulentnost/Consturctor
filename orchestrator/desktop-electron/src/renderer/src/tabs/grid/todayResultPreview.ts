import { api } from '../../api/client'
import { cleanRunResult } from '../../utils/cleanRunResult'
import type { TodayAgentResultItem } from '../../workplace/useTodayAgentResults'

export function resultAgentLabel(file: TodayAgentResultItem): string {
  const title = (file.agentTitle || '').trim()
  return title || 'Агент'
}

/** Один агент — одна строка, берём самый свежий файл. */
export function uniqueAgentResults(items: TodayAgentResultItem[]): TodayAgentResultItem[] {
  const seen = new Set<string>()
  const out: TodayAgentResultItem[] = []
  for (const item of items) {
    const key = (item.agentTitle || '').trim().toLowerCase() || item.workflowId || item.id
    if (seen.has(key)) continue
    seen.add(key)
    out.push(item)
  }
  return out
}

export type ResultFilePreview =
  | { kind: 'text'; text: string }
  | { kind: 'table'; headers: string[]; rows: string[][] }
  | { kind: 'embed'; dataUrl: string; mime: string }
  | { kind: 'error'; message: string }

function splitDelimitedLine(line: string, delimiter: string): string[] {
  if (delimiter === ',') {
    const cells: string[] = []
    let current = ''
    let quoted = false
    for (let i = 0; i < line.length; i += 1) {
      const ch = line[i]
      if (ch === '"') {
        quoted = !quoted
        continue
      }
      if (ch === ',' && !quoted) {
        cells.push(current.trim())
        current = ''
        continue
      }
      current += ch
    }
    cells.push(current.trim())
    return cells
  }
  return line.split(delimiter).map((cell) => cell.trim())
}

export function parsePreviewTable(text: string): { headers: string[]; rows: string[][] } | null {
  const lines = text
    .replace(/^\uFEFF/, '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
  if (lines.length < 2) return null
  const delimiter = lines[0].includes(';') ? ';' : lines[0].includes('|') ? '|' : ','
  const rows = lines.map((line) => splitDelimitedLine(line, delimiter).filter((cell) => cell !== ''))
  if (rows.some((row) => row.length < 2)) return null
  const width = rows[0].length
  if (width < 2 || rows.some((row) => row.length !== width)) return null
  return { headers: rows[0], rows: rows.slice(1) }
}

function previewFromText(file: TodayAgentResultItem, text: string): ResultFilePreview {
  const trimmed = text.trim()
  if (!trimmed) return { kind: 'error', message: 'Результат пуст' }
  if (file.kind === 'csv' || file.kind === 'xls') {
    const table = parsePreviewTable(trimmed)
    if (table) return { kind: 'table', ...table }
  }
  return { kind: 'text', text: trimmed }
}

const RESULT_READY_TEXT = 'Отчёт сформирован.\nПолный текст доступен после скачивания.'

async function loadRunResultText(file: TodayAgentResultItem): Promise<string> {
  if (!file.workflowId || !file.runId) return ''
  try {
    const detail = await api.getAgentRunDetail(file.workflowId, file.runId)
    const cleaned = cleanRunResult({
      answer: detail.item.answer,
      summary: detail.item.summary,
      events: detail.events,
      status: detail.item.status
    })
    return (cleaned.text || '').trim()
  } catch {
    return ''
  }
}

export async function loadResultFilePreview(file: TodayAgentResultItem): Promise<ResultFilePreview> {
  const local = (file.summary || '').trim()
  if (local) return previewFromText(file, local)

  const fromRun = await loadRunResultText(file)
  if (fromRun) return previewFromText(file, fromRun)

  const canPreviewInline = file.kind === 'pdf' || file.kind === 'csv'
  if (file.downloadUrl && canPreviewInline) {
    try {
      const remote = await api.fetchFilePreview(file.downloadUrl, file.name)
      if (remote.ok && remote.kind === 'embed') {
        return { kind: 'embed', dataUrl: remote.dataUrl, mime: remote.mime }
      }
      if (remote.ok && remote.kind === 'text') {
        return previewFromText(file, remote.text)
      }
    } catch {
      /* show ready-state below */
    }
  }

  if (file.downloadUrl) return { kind: 'text', text: RESULT_READY_TEXT }
  return { kind: 'error', message: 'Результат ещё не доступен для просмотра' }
}
