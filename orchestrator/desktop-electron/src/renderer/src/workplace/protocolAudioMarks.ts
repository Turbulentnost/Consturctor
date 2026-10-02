import { useEffect, useState } from 'react'

/** Что агент сделал по записи: расшифровки, записи в 1С и его итоговое пояснение. */
export type ProtocolAudioResult = {
  transcripts: { name: string; path: string; durationSec: number }[]
  changes: { action: string; summary: string; details: string[]; error: boolean }[]
  explanation: string
  error: string
  finished: boolean
}

/** Аудиозаписи (основная или догруженные ГС), по которым агент дополнял протокол из журнала «Протоколы». */
export type ProtocolAudioMark = {
  protocolId: string
  audioName: string
  audioNames?: string[]
  /** Догрузка голосовых к уже дополненному протоколу. */
  extra?: boolean
  workflowId: string
  runId: string
  /** Id запуска на backend: по нему окно отчёта читает ленту с сервера после перезапуска программы. */
  backendRunId?: string
  at: string
  result?: ProtocolAudioResult
}

const STORAGE_KEY = 'docflow.protocolAudio.v1'
const CHANGED_EVENT = 'docflow-protocol-audio-changed'

type MarkMap = Record<string, ProtocolAudioMark[]>

function readMarks(): MarkMap {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '{}') as unknown
    return parsed && typeof parsed === 'object' ? (parsed as MarkMap) : {}
  } catch {
    return {}
  }
}

function writeMarks(marks: MarkMap): void {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(marks))
  window.dispatchEvent(new Event(CHANGED_EVENT))
}

export function rememberProtocolAudio(mark: ProtocolAudioMark): void {
  const marks = readMarks()
  marks[mark.protocolId] = [...(marks[mark.protocolId] || []), mark].slice(-20)
  writeMarks(marks)
}

export function saveProtocolAudioResult(protocolId: string, runId: string, result: ProtocolAudioResult): void {
  const marks = readMarks()
  const list = marks[protocolId] || []
  const index = list.findIndex((mark) => mark.runId === runId)
  if (index < 0 || JSON.stringify(list[index].result) === JSON.stringify(result)) return
  list[index] = { ...list[index], result }
  marks[protocolId] = list
  writeMarks(marks)
}

export function saveProtocolAudioBackendRun(protocolId: string, runId: string, backendRunId: string): void {
  const marks = readMarks()
  const list = marks[protocolId] || []
  const index = list.findIndex((mark) => mark.runId === runId)
  if (index < 0 || !backendRunId || list[index].backendRunId === backendRunId) return
  list[index] = { ...list[index], backendRunId }
  marks[protocolId] = list
  writeMarks(marks)
}

/** Убрать запись из списка протокола. То, что агент уже записал в 1С, остаётся. */
export function forgetProtocolAudio(protocolId: string, mark: Pick<ProtocolAudioMark, 'runId' | 'at'>): void {
  const marks = readMarks()
  const list = (marks[protocolId] || []).filter((item) => !(item.runId === mark.runId && item.at === mark.at))
  if (list.length) marks[protocolId] = list
  else delete marks[protocolId]
  writeMarks(marks)
}

export function markAudioNames(mark: ProtocolAudioMark): string[] {
  return mark.audioNames?.length ? mark.audioNames : mark.audioName ? [mark.audioName] : []
}

export function useProtocolAudioMarks(): MarkMap {
  const [marks, setMarks] = useState<MarkMap>(readMarks)
  useEffect(() => {
    const refresh = (): void => setMarks(readMarks())
    window.addEventListener(CHANGED_EVENT, refresh)
    window.addEventListener('storage', refresh)
    return () => {
      window.removeEventListener(CHANGED_EVENT, refresh)
      window.removeEventListener('storage', refresh)
    }
  }, [])
  return marks
}

/** Протокол, сформированный или дополненный агентом, несёт это в комментарии 1С — видно и с других машин. */
export function commentMentionsAudio(comment: string): boolean {
  return /по аудиозапис/i.test(comment)
}

export function audioMarkTitle(marks: ProtocolAudioMark[] | undefined, comment: string): string {
  const names = [...new Set((marks || []).flatMap(markAudioNames).filter(Boolean))]
  if (names.length) return `Дополнен из аудио: ${names.join(', ')}`
  return commentMentionsAudio(comment) ? 'Сформирован или дополнен ИИ-агентом по аудиозаписи' : ''
}
