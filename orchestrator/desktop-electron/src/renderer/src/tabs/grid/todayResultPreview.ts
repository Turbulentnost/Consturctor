import { api } from '../../api/client'
import { cleanRunResult } from '../../utils/cleanRunResult'
import type { TodayAgentResultItem } from '../../workplace/useTodayAgentResults'
import { stripInlineMarkdown } from './TodayResultReport'

export function resultAgentLabel(file: TodayAgentResultItem): string {
  const title = stripInlineMarkdown((file.agentTitle || '').trim())
  return title || 'Агент'
}

/** Один агент — одна строка, берём самый свежий файл. */
export function uniqueAgentResults(items: TodayAgentResultItem[]): TodayAgentResultItem[] {
  const seen = new Set<string>()
  const out: TodayAgentResultItem[] = []
  const ranked = [...items].sort((left, right) => (right.createdAt || '').localeCompare(left.createdAt || ''))
  for (const item of ranked) {
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

function pickPreviewText(fromRun: string, summary: string): string {
  const cleaned = (fromRun || '').trim()
  const local = (summary || '').trim()
  if (!cleaned) return local
  const truncated = cleaned.length < 48 || /^(и|а|но|или)\b/i.test(cleaned)
  if (truncated && local.length > cleaned.length) return local
  return cleaned
}

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

function normalizeFileKey(name: string): string {
  return (name || '').trim().toLowerCase().replace(/[\s_]+/g, '')
}

function remotePreviewToResult(
  remote:
    | { ok: true; kind: 'text'; text: string; mime: string }
    | { ok: true; kind: 'embed'; dataUrl: string; mime: string }
    | { ok: true; kind: 'external'; hint: string; mime: string },
  fileName: string
): ResultFilePreview {
  if (remote.kind === 'embed') return { kind: 'embed', dataUrl: remote.dataUrl, mime: remote.mime }
  if (remote.kind === 'text') {
    const table = parsePreviewTable(remote.text)
    if (table && /\.(csv|xlsx?|xlsm)$/i.test(fileName)) return { kind: 'table', ...table }
    return { kind: 'text', text: remote.text }
  }
  return { kind: 'error', message: remote.hint || 'Предпросмотр недоступен' }
}

export async function resolveAgentFileDownload(
  fileName: string,
  context: TodayAgentResultItem
): Promise<{ url: string; name: string } | null> {
  const key = normalizeFileKey(fileName)
  if (!key) return null
  if (normalizeFileKey(context.name || '') === key && context.downloadUrl) {
    return { url: context.downloadUrl, name: fileName }
  }
  const wantStem = key.replace(/\.[a-z0-9]+$/, '')
  const attachedStem = normalizeFileKey(context.name || '').replace(/\.[a-z0-9]+$/, '')
  if (context.downloadUrl && wantStem && attachedStem && wantStem === attachedStem) {
    return { url: context.downloadUrl, name: fileName }
  }
  try {
    const files = await api.listPlatformFiles()
    const exact = files.find((item) => normalizeFileKey(item.name || '') === key)
    if (exact?.downloadUrl) return { url: exact.downloadUrl, name: exact.name || fileName }
    if (context.workflowId) {
      const inWorkflow = files.find(
        (item) => item.workflowId === context.workflowId && normalizeFileKey(item.name || '') === key
      )
      if (inWorkflow?.downloadUrl) {
        return { url: inWorkflow.downloadUrl, name: inWorkflow.name || fileName }
      }
    }
    const stem = key.replace(/\.[a-z0-9]+$/, '')
    const fuzzy = files.find((item) => {
      const itemKey = normalizeFileKey(item.name || '')
      const itemStem = itemKey.replace(/\.[a-z0-9]+$/, '')
      return itemKey.includes(stem) || stem.includes(itemStem)
    })
    if (fuzzy?.downloadUrl) return { url: fuzzy.downloadUrl, name: fuzzy.name || fileName }
  } catch {
    /* fallback below */
  }
  return null
}

export async function loadReferencedFilePreview(
  fileName: string,
  context: TodayAgentResultItem
): Promise<ResultFilePreview> {
  const resolved = await resolveAgentFileDownload(fileName, context)
  if (!resolved) return { kind: 'error', message: `Файл «${fileName}» не найден` }
  try {
    const remote = await api.fetchFilePreview(resolved.url, resolved.name)
    if (!remote.ok) return { kind: 'error', message: remote.error || 'Не удалось загрузить файл' }
    return remotePreviewToResult(remote, resolved.name)
  } catch {
    return { kind: 'error', message: 'Не удалось открыть файл' }
  }
}

export async function loadResultFilePreview(file: TodayAgentResultItem): Promise<ResultFilePreview> {
  const fromRun = await loadRunResultText(file)
  const stub = pickPreviewText(fromRun, file.summary || '').trim()

  if (stub) {
    return previewFromText(file, stub)
  }

  if (file.downloadUrl) {
    try {
      const remote = await api.fetchFilePreview(file.downloadUrl, file.name)
      if (remote.ok && remote.kind === 'embed') {
        return { kind: 'embed', dataUrl: remote.dataUrl, mime: remote.mime }
      }
      if (remote.ok && remote.kind === 'text' && remote.text.trim()) {
        return previewFromText(file, remote.text.trim())
      }
      if (remote.ok && remote.kind === 'external') {
        return { kind: 'error', message: remote.hint || 'Предпросмотр недоступен' }
      }
      if (!remote.ok) {
        return { kind: 'error', message: remote.error || 'Не удалось загрузить файл' }
      }
    } catch {
      /* fallback below */
    }
  }

  if (file.downloadUrl) return { kind: 'text', text: RESULT_READY_TEXT }
  return { kind: 'error', message: 'Результат ещё не доступен для просмотра' }
}
