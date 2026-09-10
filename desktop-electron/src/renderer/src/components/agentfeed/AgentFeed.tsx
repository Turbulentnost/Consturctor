import { useEffect, useMemo, useRef, useState } from 'react'
import { ClarifyCard } from './ClarifyCard'
import { HitlCard } from './HitlCard'
import { MarkdownBody } from './MarkdownBody'
import { MiniCalendar, meetingsFromFeed } from './MiniCalendar'
import { presentAgentText } from './formatAgentText'
import { ToolCard } from './ToolCard'
import { fileTypeIconSrc } from '../../utils/fileTypeIcon'
import type { FeedItem, PendingHitl, PendingQuestion, ResultFileLink } from './types'

const RESULT_FILE_RE = /\.(xlsx|xls|xlsm|csv|docx|doc|pdf)$/i

function addResultFile(out: ResultFileLink[], seen: Set<string>, raw: string, downloadUrl?: string): void {
  const name = raw.split(/[\\/]/).pop()?.trim() || ''
  if (!name || !RESULT_FILE_RE.test(name)) return
  const key = name.toLowerCase()
  if (seen.has(key)) {
    const existing = out.find((item) => item.name.toLowerCase() === key)
    if (existing && !existing.downloadUrl && downloadUrl) existing.downloadUrl = downloadUrl
    return
  }
  seen.add(key)
  out.push({ name, downloadUrl })
}

function filesFromToolResults(items: FeedItem[]): ResultFileLink[] {
  const out: ResultFileLink[] = []
  const seen = new Set<string>()
  for (const item of items) {
    if (item.kind !== 'tool' || !item.result) continue
    for (const key of ['file', 'path', 'result_file', 'filename']) {
      const value = item.result[key]
      if (typeof value === 'string' && value.trim()) addResultFile(out, seen, value)
    }
  }
  return out
}

function mergeResultFiles(fromTools: ResultFileLink[], fromProps: ResultFileLink[]): ResultFileLink[] {
  const out: ResultFileLink[] = []
  const seen = new Set<string>()
  for (const item of [...fromProps, ...fromTools]) {
    addResultFile(out, seen, item.name, item.downloadUrl)
  }
  return out
}

/** Collapsible "thinking" block (dim, full width, hidden by default). */
function ThinkingRow({ text }: { text: string }): React.JSX.Element {
  const [open, setOpen] = useState(false)
  return (
    <div className="feed-thinking">
      <button className="feed-thinking-toggle" onClick={() => setOpen((v) => !v)}>
        <span className="feed-thinking-chevron">{open ? '\u25BE' : '\u25B8'}</span>
        <span className="feed-thinking-label">Размышления</span>
      </button>
      {open && <div className="feed-thinking-text">{text}</div>}
    </div>
  )
}

interface AgentFeedProps {
  items: FeedItem[]
  status: string
  running: boolean
  pendingQuestion: PendingQuestion | null
  pendingHitl: PendingHitl | null
  emptyHint?: string
  allowQuestionFiles?: boolean
  hideRunningStatus?: boolean
  dockQuestion?: boolean
  onAnswer: (requestId: string, value: string, filePaths?: string[]) => void
  onHitl: (requestId: string, approved: boolean) => void
  onSkip: () => void
  resultFiles?: ResultFileLink[]
  onOpenResultFile?: (file: ResultFileLink) => void
}

function ResultBlock({
  text,
  meetings,
  files,
  onOpenFile
}: {
  text?: string
  meetings: ReturnType<typeof meetingsFromFeed>
  files?: ResultFileLink[]
  onOpenFile?: (file: ResultFileLink) => void
}): React.JSX.Element {
  const body = (text || '').trim()
  return (
    <div className="feed-result">
      {meetings.length > 0 && (
        <div className="feed-result-calendar">
          <MiniCalendar meetings={meetings} />
        </div>
      )}
      {files && files.length > 0 ? (
        <div className="feed-result-files">
          <div className="feed-result-files-label">Файлы запуска</div>
          {files.map((file) => (
            <button
              key={file.name}
              type="button"
              className="feed-result-file"
              onClick={() => onOpenFile?.(file)}
            >
              <img className="files-type-icon" src={fileTypeIconSrc(file.name)} alt="" />
              <span className="feed-result-file-name">{file.name}</span>
              <span className="feed-result-file-action">Открыть</span>
            </button>
          ))}
        </div>
      ) : null}
      {body ? <MarkdownBody text={presentAgentText(body)} /> : null}
    </div>
  )
}

function FeedRow({
  item,
  resultMeetings,
  liftCalendar,
  files,
  onOpenFile
}: {
  item: FeedItem
  resultMeetings: ReturnType<typeof meetingsFromFeed>
  liftCalendar: boolean
  files?: ResultFileLink[]
  onOpenFile?: (file: ResultFileLink) => void
}): React.JSX.Element | null {
  switch (item.kind) {
    case 'thinking':
      return <ThinkingRow text={item.text} />
    case 'message':
      if (item.role === 'user') {
        return (
          <div className="feed-message user">
            <div className="feed-message-text">{item.text}</div>
          </div>
        )
      }
      return (
        <div className="feed-assistant">
          <MarkdownBody text={presentAgentText(item.text)} />
        </div>
      )
    case 'system':
      return <div className={`feed-system ${item.tone || 'info'}`}>{item.text}</div>
    case 'tool':
      return <ToolCard item={item} liftMeetings={liftCalendar} />
    case 'result':
      return (
        <ResultBlock
          text={item.text}
          meetings={resultMeetings}
          files={files}
          onOpenFile={onOpenFile}
        />
      )
    default:
      return null
  }
}

export function AgentFeed({
  items,
  status,
  running,
  pendingQuestion,
  pendingHitl,
  emptyHint,
  allowQuestionFiles = false,
  hideRunningStatus = false,
  dockQuestion = false,
  onAnswer,
  onHitl,
  onSkip,
  resultFiles = [],
  onOpenResultFile
}: AgentFeedProps): React.JSX.Element {
  const scrollRef = useRef<HTMLDivElement>(null)
  // Stay pinned to the bottom only while the user is already near it, so
  // scrolling up to read history is not yanked back down by new events.
  const pinnedRef = useRef(true)

  const handleScroll = (): void => {
    const el = scrollRef.current
    if (!el) return
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight
    pinnedRef.current = distance < 60
  }

  useEffect(() => {
    if (!pinnedRef.current) return
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [items, pendingQuestion, pendingHitl, status, running])

  const resultMeetings = useMemo(() => meetingsFromFeed(items), [items])
  const resultDocs = useMemo(
    () => mergeResultFiles(filesFromToolResults(items), resultFiles),
    [items, resultFiles]
  )
  const hasResultItem = items.some((item) => item.kind === 'result')
  const liftCalendar = resultMeetings.length > 0
  const isEmpty = items.length === 0 && !pendingQuestion && !pendingHitl && !running

  return (
    <div className="agent-feed" ref={scrollRef} onScroll={handleScroll}>
      {isEmpty && emptyHint && <div className="agent-feed-empty">{emptyHint}</div>}
      {items.map((item) => (
        <FeedRow
          key={item.id}
          item={item}
          resultMeetings={resultMeetings}
          liftCalendar={liftCalendar}
          files={resultDocs}
          onOpenFile={onOpenResultFile}
        />
      ))}
      {!hasResultItem && (liftCalendar || resultDocs.length > 0) ? (
        <ResultBlock meetings={resultMeetings} files={resultDocs} onOpenFile={onOpenResultFile} />
      ) : null}
      {pendingQuestion && !dockQuestion && (
        <ClarifyCard
          key={`${pendingQuestion.requestId}:${pendingQuestion.question}:${pendingQuestion.options.join('|')}`}
          question={pendingQuestion}
          allowFiles={allowQuestionFiles || Boolean(pendingQuestion.needsFile)}
          onAnswer={onAnswer}
        />
      )}
      {pendingHitl && <HitlCard hitl={pendingHitl} onRespond={onHitl} onSkip={onSkip} />}
      {!hideRunningStatus && running && !pendingQuestion && !pendingHitl && (
        <div className="agent-feed-status">
          <span className="agent-feed-spinner" />
          {status || 'Агент работает…'}
        </div>
      )}
    </div>
  )
}
