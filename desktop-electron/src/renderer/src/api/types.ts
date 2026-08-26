export interface UserProfile {
  id: string
  fio: string
  department: string
  position: string
  avatarUrl: string | null
  canChangeDepartment: boolean
  activityStatus: string
  isSupport: boolean
}

export interface LoginResult {
  accessToken: string
  user: UserProfile
}

export interface RegulationStyleRun {
  text?: string
  fontName?: string
  fontSize?: number
  isBold?: boolean
  isItalic?: boolean
  underline?: boolean
  color?: number
  bbox?: number[]
  origin?: number[]
}

export interface RegulationTable {
  headers: string[]
  rows: string[][]
}

export interface FragmentEntityTag {
  entityId: string
  kind: 'role' | 'process'
  title: string
  shortTitle: string
}

export interface RegulationEntityLegendItem {
  entityId: string
  kind: 'role' | 'process'
  title: string
  shortTitle: string
  fragmentIds: string[]
}

export interface RegulationFragment {
  fragmentId: string
  page: number
  section: string
  sectionPath: string[]
  kind: string
  blockType: string
  text: string
  table: RegulationTable | null
  fontSize: number | null
  isBold: boolean
  numbering: string | null
  style: string
  styleRuns: RegulationStyleRun[]
  location: Record<string, unknown>
  bbox: number[] | null
  entities: FragmentEntityTag[]
}

export interface RegulationParseResult {
  regulationId: string
  fileName: string
  pageCount: number
  tableCount: number
  sectionCount: number
  recognitionQuality: number
  isScan: boolean
  sections: string[]
  fragments: RegulationFragment[]
  entityLegend: RegulationEntityLegendItem[]
}

export interface WorkflowListItem {
  id: string
  title: string
  phase: string
  updatedAt?: string
}

export interface WorkflowFileItem {
  id: string
  name: string
  sizeBytes: number
  mime?: string
  downloadUrl?: string
  createdAt?: string
  workflowId?: string
  runId?: string
  source?: string
  origin?: string
  scope?: string
  agentTitle?: string
  summary?: string
}

export interface AgentKpiRow {
  label: string
  value: string
}

export interface BoardStats {
  activeAgents: number
  runsToday: number
  errorsToday: number
  needsAttention: number
  nextRunAt: string
}

export interface BoardAgent {
  id: string
  kind: string
  title: string
  description: string
  status: string
  lastRunAt: string
  lastRunStatus: string
  nextRunAt: string
  nextRunLabel: string
  triggerSummary: string
  triggerKind: string
  paused: boolean
  phase: string
  draftId: string
}

export interface CalendarEvent {
  id: string
  workflowId: string
  title: string
  subtitle: string
  startAt: string
  status: string
  source: string
  isFuture: boolean
  runId: string
  triggerId: string
}

export interface WorkflowBoard {
  stats: BoardStats
  agents: BoardAgent[]
  events: CalendarEvent[]
}

export interface AgentRunHistoryItem {
  runId: string
  workflowId: string
  status: string
  source: string
  startedAt: string
  finishedAt: string
  summary: string
}

export interface RegulationCreationMessage {
  messageId: string
  draftId: string
  role: string
  content: string
  structured: Record<string, unknown>
}

export interface RegulationCreationSession {
  draftId: string
  status: string
  messages: RegulationCreationMessage[]
  resultRegulation: RegulationParseResult | null
  resultDocumentPath: string
}

export interface MatchEvidence {
  fragmentId: string
  quote: string
}

export interface MatchSignal {
  matchType: string
  confidence: number
  fragmentId: string
  quote: string
  explanation: string
}

export interface ContextLinkedBlock {
  blockId: string
  relation: string
  text: string
  evidence: string
  confidence: number
}

export interface FunctionActor {
  text: string
  canonicalPosition: string
  sourceBlockId: string
}

export interface FunctionDependency {
  type: string
  blockId: string
  description: string
}

export interface RoleFunction {
  functionId: string
  title: string
  action: string
  object: string
  recipient: string
  explanation: string
  confidence: number
  requiresConfirmation: boolean
  conditions: string[]
  targetBlockId: string
  actor: FunctionActor
  dependencies: FunctionDependency[]
  evidence: MatchEvidence[]
  proofChain: ContextLinkedBlock[]
}

export interface RoleMatch {
  matchId: string
  status: string
  explanation: string
  confidence: number
  requiresConfirmation: boolean
  function: RoleFunction | null
  fragmentId: string
  fragment: RegulationFragment | null
  signals: MatchSignal[]
  evidence: MatchEvidence[]
}

export interface RoleMatchResult {
  runId: string
  regulationId: string
  canonicalTitle: string
  department: string
  matches: RoleMatch[]
  functions: RoleFunction[]
}

export interface ReadinessQuestion {
  questionId: string
  functionId: string
  targetField: string
  severity: string
  question: string
  reason: string
  answerType: string
  options: string[]
  answered: boolean
  answer: string
}

export interface ReadinessChange {
  changeId: string
  operation: string
  before: string
  after: string
  reason: string
  status: string
}

export interface AgentReadinessResult {
  readinessRunId: string
  regulationId: string
  roleMatchRunId: string
  score: number
  questions: ReadinessQuestion[]
  changes: ReadinessChange[]
  status: string
}

export interface AgentSuggestion {
  agentId: string
  title: string
  description: string
  regulationId: string
  roleMatchRunId: string
  functionId: string
  sourceBlockId: string
}

export interface AgentDraft {
  draftId: string
  regulationId: string
  roleMatchRunId: string
  readinessRunId: string
  title: string
  position: string
  department: string
  status: string
  progress: number
  readiness: AgentReadinessResult | null
  agentSuggestions: AgentSuggestion[]
}

export interface AgentDraftFile {
  fileId: string
  draftId: string
  functionId: string
  filename: string
  mimeType: string
  kind: string
  size: number
  sha256: string
  summary: string
  textPreview: string
}

export interface QuestionChatMessage {
  messageId: string
  sessionId: string
  role: string
  content: string
  structured: Record<string, unknown>
}

export interface QuestionChatSession {
  sessionId: string
  draftId: string
  questionId: string
  status: string
  messages: QuestionChatMessage[]
}

export interface AgentPassport {
  name: string
  goal: string
  trigger: string
  receives: string
  checks: string
  decisions: string
  canAutonomous: string
  needsHumanApproval: string
  forbidden: string
  result: string
  missingFields: string[]
  questions: Record<string, unknown>[]
  source: string
  text: string
  autonomyLevel: number
}

export interface PassportFunction {
  name: string
  description: string
  actionLevel: string
  requiresHumanApproval: boolean
  automationKind: string
}

export interface PassportSession {
  passport: AgentPassport
  bpName: string
  excerpt: string
  functions: PassportFunction[]
  draftId: string
  llmError: string
  qaHistory: { prompt: string; answer: string; files: string[] }[]
}

export interface WorkflowPlanStep {
  id: string
  title: string
  action: string
  doneWhen: string
}

export interface WorkflowOpenQuestion {
  id: string
  question: string
  why: string
  answer: string
  options: string[]
}

export interface WorkflowPlan {
  title: string
  goal: string
  constraints: string[]
  outOfScope: string[]
  steps: WorkflowPlanStep[]
  testCriteria: string[]
  openQuestions: WorkflowOpenQuestion[]
  rawText: string
}

export interface WorkflowRecord {
  id: string
  title: string
  phase: string
  notes: string
  localRun: Record<string, unknown>
  plan: WorkflowPlan | null
  lastResult: string
}

export type TriggerKind = 'interval' | 'event' | 'datetime'
export type IntervalUnit = 'minutes' | 'hours' | 'days'

export interface ScheduleTriggerSpec {
  kind: TriggerKind
  message: string
  intervalValue: number
  intervalUnit: IntervalUnit
  condition: string
  at: string
  once: boolean
}

export interface ScheduleDraft {
  name: string
  goal: string
  summary: string
  triggers: ScheduleTriggerSpec[]
}

export interface KpiSide {
  label: string
  value: number | string | null
  unit: string
  description: string
}

export interface KpiMeasure {
  kind: string
  params: Record<string, unknown>
  formula: string
}

export interface KpiSchedule {
  kind: string
  intervalSeconds: number
  at: string
}

export interface KpiMethod {
  how: string
  when: string
  planUpdate: string
  factUpdate: string
  percentFormula: string
  planExplanation: string
  factExplanation: string
  scoreExplanation: string
  system: string
  greenMin: number
  yellowMin: number
  schedule: KpiSchedule | null
}

export interface KpiTile {
  id: string
  name: string
  plan: KpiSide
  fact: KpiSide
  measure: KpiMeasure | null
  scorePercent: number | null
  color: string
  updatedAt: string
  nextRunAt: string
  evidence: string
  method: KpiMethod | null
}

export interface AgentKpi {
  status: string
  generatedAt: string
  summary: string
  title: string
  workflowId: string
  tiles: KpiTile[]
}

export interface StreamEvent {
  type: string
  text?: string
  message?: string
  tool?: string
}

/** A raw runner event payload forwarded by the sidecar inside {type:'event'}. */
export interface AgentRunnerEvent {
  type: string
  text?: string
  message?: string
  tool?: string
  requestId?: string
  arguments?: Record<string, unknown>
  result?: unknown
  ok?: boolean
  skipped?: boolean
  error?: string
  status?: string
  agentId?: string
  run_id?: string
}

/** Top-level messages emitted by the Python agent sidecar. */
export interface AgentEvent {
  type:
    | 'ready'
    | 'ready_state'
    | 'event'
    | 'question'
    | 'hitl'
    | 'result'
    | 'error'
    | 'sidecar_exit'
    | 'log'
    | 'files_updated'
  runId?: string
  requestId?: string
  payload?: AgentRunnerEvent
  question?: string
  options?: string[]
  needsFile?: boolean
  accept?: string[]
  tool?: string
  arguments?: Record<string, unknown>
  kind?: 'design' | 'readiness' | 'demo' | 'run' | 'trigger'
  workflowId?: string
  draftId?: string
  agentId?: string
  runRef?: string
  answer?: string
  status?: string
  fired?: boolean
  ok?: boolean
  code?: string | number
  message?: string
  text?: string
}

export interface ChatThread {
  id: string
  kind: string
  title: string
  position: string
  preview: string
  lastMessageAt: string
  unread: number
  pinned: boolean
  peerId: string
  activityStatus: string
  online: boolean
  ticketStatus: string
  avatarUrl: string | null
}

export interface ChatAttachment {
  id: string
  filename: string
  mime: string
  size: number
}

export interface AgentSharePayload {
  type: 'agent_card'
  workflowId: string
  title: string
  description: string
  goal: string
  triggerSummary: string
  triggerKind: string
  status: string
  phase: string
  tools: string[]
}

export interface ChatMessage {
  id: string
  threadId: string
  senderId: string
  mine: boolean
  text: string
  clientId: string
  createdAt: string
  receipt: string
  attachments: ChatAttachment[]
  agent: AgentSharePayload | null
}

export interface DirectoryUser {
  id: string
  fio: string
  position: string
  department: string
  activityStatus: string
  online: boolean
  isSupport: boolean
}

export interface InboxNotification {
  id: string
  title: string
  body: string
  unread: boolean
  senderFio: string
  createdAt: string
  workflowId: string
}

export class ApiError extends Error {
  status: number
  constructor(message: string, status = 0) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}
