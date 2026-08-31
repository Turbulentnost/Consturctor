import { useEffect, useRef } from 'react'
import { ClarifyCard } from './ClarifyCard'
import { HitlCard } from './HitlCard'
import { MarkdownBody } from './MarkdownBody'
import { presentAgentText } from './formatAgentText'
import type { FeedItem, PendingHitl, PendingQuestion } from './types'

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
}

function readableFeedText(text: string): string {
  const value = (text || '').trim()
  if (!value) return 'Ошибка запуска агента'
  // Иногда backend присылает строку только из вопросительных знаков.
  // Показываем полезный fallback с действием для пользователя.
  if (!value.replace(/[?？\s.,;:!…()[\]{}'"`+-]/g, '')) {
    return 'Запуск прерван до получения ответа. Откройте «Диагностика» и запустите прогон ещё раз.'
  }
  return value
}

function FeedRow({ item }: { item: FeedItem }): React.JSX.Element | null {
  switch (item.kind) {
    case 'thinking':
      return null
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
      return <div className={`feed-system ${item.tone || 'info'}`}>{readableFeedText(item.text)}</div>
    case 'tool':
      return null
    case 'result':
      return (
        <div className="feed-result">
          <MarkdownBody text={presentAgentText(item.text)} />
        </div>
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
  onSkip
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

  const isEmpty = items.length === 0 && !pendingQuestion && !pendingHitl && !running

  return (
    <div className="agent-feed" ref={scrollRef} onScroll={handleScroll}>
      {isEmpty && emptyHint && <div className="agent-feed-empty">{emptyHint}</div>}
      {items.map((item) => (
        <FeedRow key={item.id} item={item} />
      ))}
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
