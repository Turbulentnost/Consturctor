export interface ThinkingItem {
  kind: 'thinking'
  id: string
  text: string
}

export interface MessageItem {
  kind: 'message'
  id: string
  role: 'agent' | 'user'
  text: string
}

export interface SystemItem {
  kind: 'system'
  id: string
  text: string
  tone?: 'info' | 'error' | 'success'
}

export interface ToolItem {
  kind: 'tool'
  id: string
  tool: string
  title: string
  arguments: Record<string, unknown>
  result: Record<string, unknown> | null
  summary: string
  done: boolean
}

export interface ResultItem {
  kind: 'result'
  id: string
  text: string
}

export type FeedItem = ThinkingItem | MessageItem | SystemItem | ToolItem | ResultItem

export interface PendingQuestion {
  requestId: string
  question: string
  options: string[]
}

export interface PendingHitl {
  requestId: string
  tool: string
  title: string
  arguments: Record<string, unknown>
}
