import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { agentClient } from '../api/agent'
import { api } from '../api/client'
import type { WorkflowFileItem } from '../api/types'
import type { RunEntry } from '../store/runs'
import { useRuns } from '../store/runs'
import type { MeetingEvent } from '../utils/outlookMeetings'

export type ProtocolRunStatus = 'running' | 'done' | 'error'

export type MeetingProtocolRecord = {
  workflowId: string
  runId: string
  backendRunId: string
  status: ProtocolRunStatus
  audioPath: string
  audioName: string
  startedAt: string
  reportFileId: string
  reportName: string
  reportUrl: string
}

type ProtocolBucket = Record<string, MeetingProtocolRecord>

const STORAGE_PREFIX = 'orch-meeting-protocol-v1:'

function storageKey(userId: string): string {
  return `${STORAGE_PREFIX}${(userId || '').trim() || 'default'}`
}

export function meetingProtocolKey(meeting: MeetingEvent): string {
  return `${meeting.id}|${meeting.start}`
}

function readBucket(userId: string): ProtocolBucket {
  try {
    const raw = localStorage.getItem(storageKey(userId))
    if (!raw) return {}
    const parsed = JSON.parse(raw) as ProtocolBucket
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function writeBucket(userId: string, bucket: ProtocolBucket): void {
  try {
    localStorage.setItem(storageKey(userId), JSON.stringify(bucket))
  } catch {
    /* ignore quota */
  }
}

export function loadMeetingProtocol(
  userId: string,
  meeting: MeetingEvent
): MeetingProtocolRecord | null {
  const key = meetingProtocolKey(meeting)
  return readBucket(userId)[key] || null
}

export function saveMeetingProtocol(
  userId: string,
  meeting: MeetingEvent,
  record: MeetingProtocolRecord
): void {
  const key = meetingProtocolKey(meeting)
  const bucket = readBucket(userId)
  bucket[key] = record
  writeBucket(userId, bucket)
}

function isAgentProducedFile(item: WorkflowFileItem): boolean {
  const source = String(item.source || '').toLowerCase()
  const origin = String(item.origin || '').toLowerCase()
  const scope = String(item.scope || '').toLowerCase()
  return (
    source === 'agent' ||
    source === 'result' ||
    scope === 'run_output' ||
    origin.includes('agent') ||
    origin.includes('result')
  )
}

function parseTimestamp(value: string | undefined): number {
  const ms = Date.parse(String(value || '').trim())
  return Number.isFinite(ms) ? ms : NaN
}

/**
 * Untagged (no runId / 'local') docx may belong to any earlier run of the same agent,
 * so accept it only when its createdAt is known and not before this record's startedAt.
 */
function isCreatedAfterStart(item: WorkflowFileItem, startedAt: string): boolean {
  const created = parseTimestamp(item.createdAt)
  const started = parseTimestamp(startedAt)
  if (!Number.isFinite(created) || !Number.isFinite(started)) return false
  return created >= started
}

/**
 * Latest agent *.docx for this run.
 * - runId known: only files tagged with the same runId; untagged files only if created after startedAt.
 * - runId unknown: only files created after startedAt (any tag).
 * Files from other runs (different runId, or untagged but older than startedAt) are skipped —
 * otherwise a stale protocol-*.docx from a previous launch would be shown for a new meeting.
 */
function pickLatestDocx(
  files: WorkflowFileItem[],
  backendRunId = '',
  startedAt = ''
): WorkflowFileItem | null {
  const wanted = backendRunId.trim()
  const docx = files
    .filter(isAgentProducedFile)
    .filter((item) => /\.docx$/i.test(item.name || ''))
    .filter((item) => {
      const rid = String(item.runId || '').trim()
      const untagged = !rid || rid === 'local'
      if (!wanted) return isCreatedAfterStart(item, startedAt)
      if (untagged) return isCreatedAfterStart(item, startedAt)
      return rid === wanted
    })
    .sort((left, right) => String(right.createdAt || '').localeCompare(String(left.createdAt || '')))
  return docx[0] || null
}

function hasSuccessfulResult(entry: RunEntry): boolean {
  return (entry.state.items || []).some((item) => item.kind === 'result')
}

/**
 * done only after a successful result event (or already done).
 * Cancel / stop without result must not become done (attach would show a false report).
 */
function deriveStatus(entry: RunEntry | undefined, prev: ProtocolRunStatus): ProtocolRunStatus {
  if (!entry) return prev
  const { state } = entry
  if (state.error) return 'error'
  if (state.running || state.pendingHitl || state.pendingQuestion) return 'running'
  if (hasSuccessfulResult(entry)) return 'done'
  if (prev === 'done') return 'done'
  // Stopped without result (e.g. user cancel) — unlock attach, do not enable report.
  if (prev === 'running' && !state.running) return 'error'
  return prev
}

/** Live agent feed is one slot per workflow. Show it only on the meeting that started it. */
export function runBelongsToMeeting(
  record: MeetingProtocolRecord | null,
  entry: RunEntry | undefined
): boolean {
  if (!record || !entry) return false
  const local = (record.runId || '').trim()
  const active = (entry.state.activeRunId || '').trim()
  return Boolean(local && active && local === active)
}

export type MeetingProtocolHook = {
  record: MeetingProtocolRecord | null
  runEntry: RunEntry | undefined
  rememberStart: (next: MeetingProtocolRecord) => void
  patchRecord: (partial: Partial<MeetingProtocolRecord>) => void
}

export function useMeetingProtocol(
  meeting: MeetingEvent | null,
  userId: string
): MeetingProtocolHook {
  const runs = useRuns()
  const startedRunIds = useRef(new Set<string>())
  const meetingKey = meeting ? meetingProtocolKey(meeting) : ''
  const [record, setRecord] = useState<MeetingProtocolRecord | null>(() =>
    meeting ? loadMeetingProtocol(userId, meeting) : null
  )

  useEffect(() => {
    setRecord(meeting ? loadMeetingProtocol(userId, meeting) : null)
  }, [meetingKey, userId, meeting])

  const workflowId = record?.workflowId || ''
  const sharedEntry = workflowId ? runs.entries[workflowId] : undefined
  const runEntry = runBelongsToMeeting(record, sharedEntry) ? sharedEntry : undefined

  const persist = useCallback(
    (next: MeetingProtocolRecord) => {
      if (!meeting) return
      saveMeetingProtocol(userId, meeting, next)
      setRecord(next)
    },
    [meeting, userId]
  )

  const rememberStart = useCallback(
    (next: MeetingProtocolRecord) => {
      const runId = (next.runId || '').trim()
      if (runId) startedRunIds.current.add(runId)
      persist(next)
    },
    [persist]
  )

  const patchRecord = useCallback(
    (partial: Partial<MeetingProtocolRecord>) => {
      setRecord((prev) => {
        if (!prev || !meeting) return prev
        let changed = false
        for (const key of Object.keys(partial) as (keyof MeetingProtocolRecord)[]) {
          if (partial[key] !== undefined && partial[key] !== prev[key]) {
            changed = true
            break
          }
        }
        if (!changed) return prev
        const next = { ...prev, ...partial }
        saveMeetingProtocol(userId, meeting, next)
        return next
      })
    },
    [meeting, userId]
  )

  const refreshReportFiles = useCallback(
    async (target: MeetingProtocolRecord) => {
      const wid = target.workflowId
      const rid = target.backendRunId || ''
      if (!wid) return
      try {
        // listWorkflowFiles flattens {user_files, agent_files, run_attachments};
        // pickLatestDocx keeps only agent/run_output *.docx of this run (latest by createdAt);
        // untagged files count only when created after target.startedAt.
        const files = await api.listWorkflowFiles(wid, rid)
        const docx = pickLatestDocx(files, rid, target.startedAt || '')
        if (!docx) return
        patchRecord({
          reportFileId: docx.id,
          reportName: docx.name,
          reportUrl: docx.downloadUrl || '',
          // Docx from agent_files means the run produced a report (e.g. after restart).
          status: target.status === 'error' ? 'error' : 'done'
        })
      } catch {
        /* keep previous report fields */
      }
    },
    [patchRecord]
  )

  const finishingOwnRun =
    Boolean(record?.runId) &&
    record?.status === 'running' &&
    startedRunIds.current.has(record.runId) &&
    Boolean(sharedEntry) &&
    !sharedEntry?.state.running &&
    !sharedEntry?.state.activeRunId

  // Sync status / backendRunId only for the meeting that started this run.
  useEffect(() => {
    if (!record || !sharedEntry || (!runEntry && !finishingOwnRun)) return
    const source = runEntry || sharedEntry
    const nextBackend = source.backendRunId || record.backendRunId
    const nextStatus = deriveStatus(source, record.status)
    if (nextBackend === record.backendRunId && nextStatus === record.status) return
    const next = {
      ...record,
      backendRunId: nextBackend,
      status: nextStatus
    }
    patchRecord({
      backendRunId: nextBackend,
      status: nextStatus
    })
    if (nextStatus === 'done' && nextBackend) {
      void refreshReportFiles(next)
    }
  }, [
    record?.workflowId,
    record?.backendRunId,
    record?.status,
    finishingOwnRun,
    sharedEntry?.backendRunId,
    sharedEntry?.state.running,
    runEntry?.backendRunId,
    runEntry?.state.running,
    runEntry?.state.error,
    runEntry?.state.pendingHitl?.requestId,
    runEntry?.state.pendingQuestion?.requestId,
    patchRecord,
    refreshReportFiles
  ])

  // files_updated → re-list and remember latest agent *.docx (own workflow/run only)
  useEffect(() => {
    if (!workflowId) return
    return agentClient.onEvent((event) => {
      if (event.type !== 'files_updated') return
      // Require exact workflow match — empty/other ids must not overwrite this meeting's report.
      if ((event.workflowId || '').trim() !== workflowId) return
      const current = meeting ? loadMeetingProtocol(userId, meeting) : null
      if (!current?.workflowId || current.workflowId !== workflowId) return
      if (sharedEntry && !runBelongsToMeeting(current, sharedEntry)) return
      const eventRun = String(event.runId || '').trim()
      if (eventRun) {
        const ours = [current.backendRunId, current.runId].map((v) => String(v || '').trim()).filter(Boolean)
        // If we already know our run ids, ignore updates from a different run of the same agent.
        if (ours.length && !ours.includes(eventRun)) return
      }
      void refreshReportFiles(current)
    })
  }, [workflowId, meeting, userId, refreshReportFiles, sharedEntry])

  // Restore on mount / meeting change: status from runs + files list.
  useEffect(() => {
    if (!record?.workflowId) return
    let cancelled = false
    const snapshot = record
    void (async () => {
      if (cancelled) return
      if (sharedEntry && !runBelongsToMeeting(snapshot, sharedEntry)) return
      if (runEntry) {
        const nextStatus = deriveStatus(runEntry, snapshot.status)
        const nextBackend = runEntry.backendRunId || snapshot.backendRunId
        if (nextStatus !== snapshot.status || nextBackend !== snapshot.backendRunId) {
          patchRecord({ status: nextStatus, backendRunId: nextBackend })
        }
      }
      await refreshReportFiles(snapshot)
    })()
    return () => {
      cancelled = true
    }
    // Identity only — avoid re-fetching on every status tick.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meetingKey, record?.workflowId])

  return useMemo(
    () => ({ record, runEntry, rememberStart, patchRecord }),
    [record, runEntry, rememberStart, patchRecord]
  )
}
