import { useEffect, useRef } from 'react'
import { ClarifyCard } from './ClarifyCard'
import { HitlCard } from './HitlCard'
import { ToolCard } from './ToolCard'
import type { FeedItem, PendingHitl, PendingQuestion } from './types'

interface AgentFeedProps {
  items: FeedItem[]
  status: string
  running: boolean
  pendingQuestion: PendingQuestion | null
  pendingHitl: PendingHitl | null
  emptyHint?: string
  allowQuestionFiles?: boolean
  onAnswer: (requestId: string, value: string, filePaths?: string[]) => void
  onHitl: (requestId: string, approved: boolean) => void
  onSkip: () => void
}

function FeedRow({ item }: { item: FeedItem }): React.JSX.Element | null {
  switch (item.kind) {
    case 'thinking':
      return (
        <div className="feed-thinking">
          <span className="feed-thinking-badge">Размышляет</span>
          <span className="feed-thinking-text">{item.text}</span>
        </div>
      )
    case 'message':
      return (
        <div className={item.role === 'user' ? 'feed-message user' : 'feed-message agent'}>
          <div className="feed-message-role">{item.role === 'user' ? 'Вы' : 'Агент'}</div>
          <div className="feed-message-text">{item.text}</div>
        </div>
      )
    case 'system':
      return <div className={`feed-system ${item.tone || 'info'}`}>{item.text}</div>
    case 'tool':
      return <ToolCard item={item} />
    case 'result':
      return <div className="feed-result">{item.text}</div>
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
  onAnswer,
  onHitl,
  onSkip
}: AgentFeedProps): React.JSX.Element {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [items, pendingQuestion, pendingHitl, status])

  const isEmpty = items.length === 0 && !pendingQuestion && !pendingHitl && !running

  return (
    <div className="agent-feed">
      {isEmpty && emptyHint && <div className="agent-feed-empty">{emptyHint}</div>}
      {items.map((item) => (
        <FeedRow key={item.id} item={item} />
      ))}
      {pendingQuestion && (
        <ClarifyCard
          question={pendingQuestion}
          allowFiles={allowQuestionFiles}
          onAnswer={onAnswer}
        />
      )}
      {pendingHitl && <HitlCard hitl={pendingHitl} onRespond={onHitl} onSkip={onSkip} />}
      {running && !pendingQuestion && !pendingHitl && (
        <div className="agent-feed-status">
          <span className="agent-feed-spinner" />
          {status || 'Агент работает…'}
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  )
}
