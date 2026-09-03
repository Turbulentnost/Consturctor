import {
  ApiError,
  type AgentDraft,
  type AgentDraftFile,
  type AgentPassport,
  type AgentReadinessResult,
  type AgentRunHistoryItem,
  type AgentRunnerEvent,
  type AgentSuggestion,
  type BoardAgent,
  type BoardStats,
  type CalendarEvent,
  type LoginResult,
  type WorkflowBoard,
  type PassportSession,
  type QuestionChatSession,
  type RegulationCreationMessage,
  type RegulationCreationSession,
  type FragmentEntityTag,
  type RegulationEntityLegendItem,
  type RegulationFragment,
  type RegulationParseResult,
  type RegulationStyleRun,
  type RegulationTable,
  type ContextLinkedBlock,
  type FunctionActor,
  type FunctionDependency,
  type MatchEvidence,
  type MatchSignal,
  type RoleFunction,
  type RoleMatch,
  type RoleMatchResult,
  type StreamEvent,
  type UserProfile,
  type WorkflowFileItem,
  type WorkflowListItem,
  type WorkflowRecord,
  type ScheduleDraft,
  type ScheduleTriggerSpec,
  type TriggerKind,
  type IntervalUnit,
  type AgentKpi,
  type PositionOrchestrator,
  type KpiTile,
  type KpiSide,
  type KpiMethod,
  type AgentSharePayload,
  type ChatAttachment,
  type ChatMessage,
  type ChatThread,
  type DirectoryUser,
  type InboxNotification,
  type AppHealth,
  type WorkflowHealthInfo,
  type ToolStatus,
  type SupportTicketItem
} from './types'
import { decodeAgentMessage, previewText } from './chatCodec'

type Params = Record<string, string | number | boolean | undefined | null>

function optionalUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const text = value.trim()
  return text || null
}

function parseWorkflowList(data: unknown): WorkflowListItem[] {
  const rows = Array.isArray(data)
    ? data
    : data && typeof data === 'object' && Array.isArray((data as { items?: unknown[] }).items)
      ? ((data as { items: unknown[] }).items)
      : []
  return rows
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map((item) => ({
      id: String(item.id ?? ''),
      title: String(item.title ?? ''),
      phase: String(item.phase ?? ''),
      updatedAt: String(item.updatedAt ?? item.updated_at ?? '')
    }))
    .filter((item) => item.id)
}

function parsePlatformFile(item: Record<string, unknown>): WorkflowFileItem {
  const id = String(item.id ?? '')
  const workflowId = String(item.workflow_id ?? item.workflowId ?? '')
  const downloadUrl =
    String(item.downloadUrl ?? item.download_url ?? '') ||
    (id && workflowId ? `/api/v1/workflows/${workflowId}/files/${id}/download` : '')
  return {
    id,
    name: String(item.filename ?? item.name ?? item.fileName ?? ''),
    sizeBytes: Number(item.size ?? item.sizeBytes ?? item.size_bytes ?? 0),
    mime: String(item.mime_type ?? item.mime ?? ''),
    downloadUrl,
    createdAt: String(item.created_at ?? item.createdAt ?? ''),
    workflowId,
    runId: String(item.run_id ?? item.runId ?? ''),
    source: String(item.source ?? 'user'),
    origin: String(item.origin ?? ''),
    scope: String(item.scope ?? ''),
    agentTitle: String(item.agent_title ?? item.agentTitle ?? ''),
    summary: String(item.summary ?? item.text_preview ?? item.textPreview ?? '')
  }
}

function normalizeFioKey(value: string): string {
  return (value || '').toLowerCase().replace(/[ьъ\u0301]/g, '')
}

const PROFILE_OVERRIDES: Array<{ needle: string; position: string; department: string }> = [
  {
    needle: 'мангасарян',
    position: 'Помощник Председателя совета директоров',
    department: 'Управление делами'
  }
]

function applyProfileOverrides(user: UserProfile): UserProfile {
  const key = normalizeFioKey(user.fio)
  for (const item of PROFILE_OVERRIDES) {
    if (key.includes(item.needle)) {
      return { ...user, position: item.position, department: item.department || user.department }
    }
  }
  return user
}

function parseUser(data: Record<string, unknown>): UserProfile {
  return applyProfileOverrides({
    id: String(data.id ?? ''),
    fio: String(data.fio ?? ''),
    department: String(data.department ?? ''),
    position: String(data.position ?? ''),
    avatarUrl: optionalUrl(data.avatarUrl) ?? optionalUrl(data.avatar_url),
    canChangeDepartment:
      (data.canChangeDepartment as boolean) ?? (data.can_change_department as boolean) ?? true,
    activityStatus:
      (data.activityStatus as string) ?? (data.activity_status as string) ?? 'online',
    isSupport: (data.isSupport as boolean) ?? (data.is_support as boolean) ?? false
  })
}

function parseCreationSession(data: Record<string, unknown>): RegulationCreationSession {
  const rawMessages = (data.messages as Record<string, unknown>[]) ?? []
  const messages: RegulationCreationMessage[] = rawMessages.map((item) => ({
    messageId: String(item.messageId ?? ''),
    draftId: String(item.draftId ?? ''),
    role: String(item.role ?? ''),
    content: String(item.content ?? ''),
    structured:
      item.structured && typeof item.structured === 'object'
        ? (item.structured as Record<string, unknown>)
        : {},
    createdAt: String(item.createdAt ?? item.created_at ?? '')
  }))
  const resultRaw = data.resultRegulation
  return {
    draftId: String(data.draftId ?? ''),
    status: String(data.status ?? ''),
    messages,
    resultRegulation:
      resultRaw && typeof resultRaw === 'object'
        ? parseRegulation(resultRaw as Record<string, unknown>)
        : null,
    resultDocumentPath: String(data.resultDocumentPath ?? '')
  }
}

function parseRegulation(data: Record<string, unknown>): RegulationParseResult {
  const rawFragments = Array.isArray(data.fragments) ? data.fragments : []
  return {
    regulationId: String(data.regulationId ?? ''),
    fileName: String(data.fileName ?? ''),
    pageCount: Number(data.pageCount ?? 0),
    tableCount: Number(data.tableCount ?? 0),
    sectionCount: Number(data.sectionCount ?? 0),
    recognitionQuality: Number(data.recognitionQuality ?? 0),
    isScan: Boolean(data.isScan),
    sections: (data.sections as string[]) ?? [],
    fragments: rawFragments.map(parseFragment),
    entityLegend: Array.isArray(data.entityLegend)
      ? data.entityLegend.map(parseLegendItem)
      : []
  }
}

function parseFragment(value: unknown): RegulationFragment {
  const data = asRecord(value)
  const tableRaw = data.table && typeof data.table === 'object' ? asRecord(data.table) : null
  const table: RegulationTable | null = tableRaw
    ? {
        headers: Array.isArray(tableRaw.headers) ? tableRaw.headers.map((item) => String(item ?? '')) : [],
        rows: Array.isArray(tableRaw.rows)
          ? tableRaw.rows.map((row) =>
              Array.isArray(row) ? row.map((cell) => String(cell ?? '')) : []
            )
          : []
      }
    : null
  const styleRuns = Array.isArray(data.styleRuns)
    ? data.styleRuns.map((item) => parseStyleRun(item))
    : []
  return {
    fragmentId: String(data.fragmentId ?? ''),
    page: Number(data.page ?? 1),
    section: String(data.section ?? ''),
    sectionPath: Array.isArray(data.sectionPath) ? data.sectionPath.map((item) => String(item)) : [],
    kind: String(data.kind ?? 'text'),
    blockType: String(data.blockType ?? 'paragraph'),
    text: String(data.text ?? ''),
    table,
    fontSize: data.fontSize == null || data.fontSize === '' ? null : Number(data.fontSize),
    isBold: Boolean(data.isBold),
    numbering: data.numbering == null || data.numbering === '' ? null : String(data.numbering),
    style: String(data.style ?? ''),
    styleRuns,
    location: asRecord(data.location),
    bbox: Array.isArray(data.bbox) ? data.bbox.map((item) => Number(item)) : null,
    entities: Array.isArray(data.entities) ? data.entities.map(parseEntityTag) : []
  }
}

function parseEntityTag(value: unknown): FragmentEntityTag {
  const data = asRecord(value)
  const kind = data.kind === 'process' ? 'process' : 'role'
  return {
    entityId: String(data.entityId ?? ''),
    kind,
    title: String(data.title ?? ''),
    shortTitle: String(data.shortTitle ?? '')
  }
}

function parseLegendItem(value: unknown): RegulationEntityLegendItem {
  const data = asRecord(value)
  const kind = data.kind === 'process' ? 'process' : 'role'
  return {
    entityId: String(data.entityId ?? ''),
    kind,
    title: String(data.title ?? ''),
    shortTitle: String(data.shortTitle ?? ''),
    fragmentIds: Array.isArray(data.fragmentIds) ? data.fragmentIds.map((item) => String(item)) : []
  }
}

function parseStyleRun(value: unknown): RegulationStyleRun {
  const data = asRecord(value)
  return {
    text: String(data.text ?? ''),
    fontName: String(data.fontName ?? ''),
    fontSize: Number(data.fontSize ?? 0) || undefined,
    isBold: Boolean(data.isBold),
    isItalic: Boolean(data.isItalic),
    underline: Boolean(data.underline),
    color: Number(data.color ?? 0) || undefined,
    bbox: Array.isArray(data.bbox) ? data.bbox.map((item) => Number(item)) : undefined,
    origin: Array.isArray(data.origin) ? data.origin.map((item) => Number(item)) : undefined
  }
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

function parseInboxNotification(value: unknown): InboxNotification {
  const data = asRecord(value)
  return {
    id: String(data.id ?? ''),
    title: String(data.title ?? ''),
    body: String(data.body ?? ''),
    unread: Boolean(data.unread),
    senderFio: String(data.senderFio ?? data.sender_fio ?? ''),
    createdAt: String(data.createdAt ?? data.created_at ?? ''),
    workflowId: String(data.workflowId ?? data.workflow_id ?? ''),
    runId: String(data.runId ?? data.run_id ?? '')
  }
}

function parseAgentShare(value: unknown): AgentSharePayload | null {
  const data = asRecord(value)
  if (!data.type && !data.workflowId && !data.workflow_id && !data.title) return null
  const tools = Array.isArray(data.tools) ? data.tools.map((item) => String(item)) : []
  return {
    type: 'agent_card',
    workflowId: String(data.workflowId ?? data.workflow_id ?? ''),
    title: String(data.title ?? 'ИИ-агент'),
    description: String(data.description ?? ''),
    goal: String(data.goal ?? ''),
    triggerSummary: String(data.triggerSummary ?? data.trigger_summary ?? ''),
    triggerKind: String(data.triggerKind ?? data.trigger_kind ?? ''),
    status: String(data.status ?? 'active'),
    phase: String(data.phase ?? ''),
    tools
  }
}

export function parseChatThread(value: unknown): ChatThread {
  const data = asRecord(value)
  return {
    id: String(data.id ?? ''),
    kind: String(data.kind ?? 'dm'),
    title: String(data.title ?? 'Диалог'),
    position: String(data.position ?? ''),
    preview: previewText(String(data.preview ?? '')),
    lastMessageAt: String(data.lastMessageAt ?? data.last_message_at ?? ''),
    unread: Number(data.unread ?? 0),
    pinned: Boolean(data.pinned),
    peerId: String(data.peerId ?? data.peer_id ?? ''),
    activityStatus: String(data.activityStatus ?? data.activity_status ?? ''),
    online: Boolean(data.online),
    ticketStatus: String(data.ticketStatus ?? data.ticket_status ?? ''),
    avatarUrl: optionalUrl(data.avatarUrl) ?? optionalUrl(data.avatar_url)
  }
}

export function parseChatMessage(value: unknown): ChatMessage {
  const data = asRecord(value)
  const rawText = String(data.text ?? '')
  const decoded = decodeAgentMessage(rawText)
  const embedded = parseAgentShare(data.agent)
  const files = Array.isArray(data.attachments) ? data.attachments : []
  return {
    id: String(data.id ?? ''),
    threadId: String(data.threadId ?? data.thread_id ?? ''),
    senderId: String(data.senderId ?? data.sender_id ?? ''),
    mine: Boolean(data.mine),
    text: decoded.text,
    clientId: String(data.clientId ?? data.client_id ?? ''),
    createdAt: String(data.createdAt ?? data.created_at ?? ''),
    receipt: String(data.receipt ?? 'delivered'),
    attachments: files.map((item) => {
      const row = asRecord(item)
      return {
        id: String(row.id ?? ''),
        filename: String(row.filename ?? ''),
        mime: String(row.mime ?? ''),
        size: Number(row.size ?? 0)
      }
    }),
    agent: embedded ?? decoded.agent
  }
}

function parseDirectoryUsers(data: unknown): DirectoryUser[] {
  const raw = Array.isArray(data) ? data : ((asRecord(data).items as unknown[]) ?? [])
  const users: DirectoryUser[] = []
  for (const item of raw) {
    if (typeof item === 'string') {
      const fio = item.trim()
      if (fio) {
        users.push({
          id: '',
          fio,
          position: '',
          department: '',
          activityStatus: 'online',
          online: false,
          isSupport: false,
          avatarUrl: null
        })
      }
      continue
    }
    const row = asRecord(item)
    const fio = String(row.fio ?? row.name ?? '').trim()
    if (!fio) continue
    const id = String(row.id ?? row.user_id ?? row.userId ?? '').trim()
    users.push({
      id,
      fio,
      position: String(row.position ?? ''),
      department: String(row.department ?? ''),
      activityStatus: String(row.activityStatus ?? row.activity_status ?? 'online'),
      online: Boolean(row.online),
      isSupport: Boolean(row.isSupport ?? row.is_support),
      avatarUrl:
        optionalUrl(row.avatarUrl) ??
        optionalUrl(row.avatar_url) ??
        (id ? `/api/v1/auth/users/${id}/avatar` : null)
    })
  }
  return users
}

function parseEvidence(value: unknown): MatchEvidence {
  const data = asRecord(value)
  return {
    fragmentId: String(data.fragmentId ?? ''),
    quote: String(data.quote ?? '')
  }
}

function parseSignal(value: unknown): MatchSignal {
  const data = asRecord(value)
  return {
    matchType: String(data.matchType ?? ''),
    confidence: Number(data.confidence ?? 0),
    fragmentId: String(data.fragmentId ?? ''),
    quote: String(data.quote ?? ''),
    explanation: String(data.explanation ?? '')
  }
}

function parseProofBlock(value: unknown): ContextLinkedBlock {
  const data = asRecord(value)
  return {
    blockId: String(data.blockId ?? ''),
    relation: String(data.relation ?? ''),
    text: String(data.text ?? ''),
    evidence: String(data.evidence ?? ''),
    confidence: Number(data.confidence ?? 0)
  }
}

function parseActor(value: unknown): FunctionActor {
  const data = asRecord(value)
  return {
    text: String(data.text ?? ''),
    canonicalPosition: String(data.canonicalPosition ?? ''),
    sourceBlockId: String(data.sourceBlockId ?? '')
  }
}

function parseDependency(value: unknown): FunctionDependency {
  const data = asRecord(value)
  return {
    type: String(data.type ?? ''),
    blockId: String(data.blockId ?? ''),
    description: String(data.description ?? '')
  }
}

function parseRoleFunction(data: unknown): RoleFunction | null {
  if (!data || typeof data !== 'object') return null
  const item = data as Record<string, unknown>
  return {
    functionId: String(item.functionId ?? ''),
    title: String(item.title ?? ''),
    action: String(item.action ?? ''),
    object: String(item.object ?? ''),
    recipient: String(item.recipient ?? ''),
    explanation: String(item.explanation ?? ''),
    confidence: Number(item.confidence ?? 0),
    requiresConfirmation: Boolean(item.requiresUserConfirmation),
    conditions: ((item.conditions as unknown[]) ?? []).map((x) => String(x)),
    targetBlockId: String(item.targetBlockId ?? ''),
    actor: parseActor(item.actor),
    dependencies: ((item.dependencies as unknown[]) ?? []).map(parseDependency),
    evidence: ((item.evidence as unknown[]) ?? []).map(parseEvidence),
    proofChain: ((item.proofChain as unknown[]) ?? []).map(parseProofBlock)
  }
}

function parseMatch(item: Record<string, unknown>): RoleMatch {
  const fragmentRaw = item.fragment
  return {
    matchId: String(item.matchId ?? ''),
    status: String(item.status ?? 'pending'),
    explanation: String(item.explanation ?? ''),
    confidence: Number(item.confidence ?? 0),
    requiresConfirmation: Boolean(item.requiresUserConfirmation),
    function: parseRoleFunction(item.function),
    fragmentId: String(item.fragmentId ?? ''),
    fragment: fragmentRaw && typeof fragmentRaw === 'object' ? parseFragment(fragmentRaw) : null,
    signals: ((item.signals as unknown[]) ?? []).map(parseSignal),
    evidence: ((item.evidence as unknown[]) ?? []).map(parseEvidence)
  }
}

export function parseRoleMatch(data: Record<string, unknown>): RoleMatchResult {
  const profile = asRecord(data.profile)
  return {
    runId: String(data.runId ?? ''),
    regulationId: String(data.regulationId ?? ''),
    canonicalTitle: String(profile.canonicalTitle ?? ''),
    department: String(profile.department ?? ''),
    matches: ((data.matches as Record<string, unknown>[]) ?? []).map((item) => parseMatch(item)),
    functions: ((data.functions as unknown[]) ?? [])
      .map(parseRoleFunction)
      .filter((item): item is RoleFunction => item !== null)
  }
}

export function parseReadiness(data: Record<string, unknown>): AgentReadinessResult {
  return {
    readinessRunId: String(data.readinessRunId ?? ''),
    regulationId: String(data.regulationId ?? ''),
    roleMatchRunId: String(data.roleMatchRunId ?? ''),
    score: Number(data.score ?? 0),
    questions: ((data.questions as Record<string, unknown>[]) ?? []).map((item) => ({
      questionId: String(item.questionId ?? ''),
      functionId: String(item.functionId ?? ''),
      targetField: String(item.targetField ?? ''),
      severity: String(item.severity ?? ''),
      question: String(item.question ?? ''),
      reason: String(item.reason ?? ''),
      answerType: String(item.answerType ?? 'text'),
      options: ((item.options as unknown[]) ?? []).map((x) => String(x)),
      answered: Boolean(item.answered),
      answer: String(item.answer ?? '')
    })),
    changes: ((data.changes as Record<string, unknown>[]) ?? []).map((item) => ({
      changeId: String(item.changeId ?? ''),
      operation: String(item.operation ?? ''),
      before: String(item.before ?? ''),
      after: String(item.after ?? ''),
      reason: String(item.reason ?? ''),
      status: String(item.status ?? 'pending')
    })),
    status: String(data.status ?? '')
  }
}

export function parseSuggestion(data: Record<string, unknown>): AgentSuggestion {
  return {
    agentId: String(data.agentId ?? ''),
    title: String(data.title ?? ''),
    description: String(data.description ?? ''),
    regulationId: String(data.regulationId ?? ''),
    roleMatchRunId: String(data.roleMatchRunId ?? ''),
    functionId: String(data.functionId ?? ''),
    sourceBlockId: String(data.sourceBlockId ?? '')
  }
}

export function parseBoard(data: Record<string, unknown>): WorkflowBoard {
  const rawStats = asRecord(data.stats)
  const stats: BoardStats = {
    activeAgents: Number(rawStats.active_agents ?? rawStats.activeAgents ?? 0),
    runsToday: Number(rawStats.runs_today ?? rawStats.runsToday ?? 0),
    errorsToday: Number(rawStats.errors_today ?? rawStats.errorsToday ?? 0),
    needsAttention: Number(rawStats.needs_attention ?? rawStats.needsAttention ?? 0),
    nextRunAt: String(rawStats.next_run_at ?? rawStats.nextRunAt ?? '')
  }
  const agents: BoardAgent[] = (Array.isArray(data.agents) ? data.agents : [])
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map((item) => ({
      id: String(item.id ?? ''),
      kind: String(item.kind ?? 'workflow'),
      title: String(item.title ?? ''),
      description: String(item.description ?? ''),
      status: String(item.status ?? 'active'),
      lastRunAt: String(item.last_run_at ?? item.lastRunAt ?? ''),
      lastRunStatus: String(item.last_run_status ?? item.lastRunStatus ?? ''),
      nextRunAt: String(item.next_run_at ?? item.nextRunAt ?? ''),
      nextRunLabel: String(item.next_run_label ?? item.nextRunLabel ?? ''),
      triggerSummary: String(item.trigger_summary ?? item.triggerSummary ?? ''),
      triggerKind: String(item.trigger_kind ?? item.triggerKind ?? ''),
      paused: Boolean(item.paused),
      phase: String(item.phase ?? ''),
      draftId: String(item.draft_id ?? item.draftId ?? '')
    }))
  const events: CalendarEvent[] = (Array.isArray(data.events) ? data.events : [])
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map((item) => ({
      id: String(item.id ?? ''),
      workflowId: String(item.workflow_id ?? item.workflowId ?? ''),
      title: String(item.title ?? ''),
      subtitle: String(item.subtitle ?? ''),
      startAt: String(item.start_at ?? item.startAt ?? ''),
      status: String(item.status ?? 'scheduled'),
      source: String(item.source ?? 'schedule'),
      isFuture: Boolean(item.is_future ?? item.isFuture),
      runId: String(item.run_id ?? item.runId ?? ''),
      triggerId: String(item.trigger_id ?? item.triggerId ?? '')
    }))
  return { stats, agents, events }
}

export function parseDraft(data: Record<string, unknown>): AgentDraft {
  const readinessRaw = data.readiness
  return {
    draftId: String(data.draftId ?? ''),
    regulationId: String(data.regulationId ?? ''),
    roleMatchRunId: String(data.roleMatchRunId ?? ''),
    readinessRunId: String(data.readinessRunId ?? ''),
    title: String(data.title ?? ''),
    position: String(data.position ?? ''),
    department: String(data.department ?? ''),
    status: String(data.status ?? 'draft'),
    progress: Number(data.progress ?? 0),
    readiness:
      readinessRaw && typeof readinessRaw === 'object'
        ? parseReadiness(readinessRaw as Record<string, unknown>)
        : null,
    agentSuggestions: ((data.agentSuggestions as Record<string, unknown>[]) ?? []).map(
      parseSuggestion
    )
  }
}

function parseDraftFile(data: Record<string, unknown>): AgentDraftFile {
  return {
    fileId: String(data.fileId ?? ''),
    draftId: String(data.draftId ?? ''),
    functionId: String(data.functionId ?? ''),
    filename: String(data.filename ?? 'file'),
    mimeType: String(data.mimeType ?? ''),
    kind: String(data.kind ?? 'text'),
    size: Number(data.size ?? 0),
    sha256: String(data.sha256 ?? ''),
    summary: String(data.summary ?? ''),
    textPreview: String(data.textPreview ?? '')
  }
}

function parseQuestionChat(data: Record<string, unknown>): QuestionChatSession {
  return {
    sessionId: String(data.sessionId ?? ''),
    draftId: String(data.draftId ?? ''),
    questionId: String(data.questionId ?? ''),
    status: String(data.status ?? ''),
    messages: ((data.messages as Record<string, unknown>[]) ?? []).map((item) => ({
      messageId: String(item.messageId ?? ''),
      sessionId: String(item.sessionId ?? ''),
      role: String(item.role ?? ''),
      content: String(item.content ?? ''),
      structured: asRecord(item.structured)
    }))
  }
}

export function parsePassportSession(data: Record<string, unknown>): PassportSession {
  const raw = asRecord(data.passport)
  return {
    passport: {
      name: String(raw.name ?? ''),
      goal: String(raw.goal ?? ''),
      trigger: String(raw.trigger ?? ''),
      receives: String(raw.receives ?? ''),
      checks: String(raw.checks ?? ''),
      decisions: String(raw.decisions ?? ''),
      canAutonomous: String(raw.can_autonomous ?? raw.canAutonomous ?? ''),
      needsHumanApproval: String(raw.needs_human_approval ?? raw.needsHumanApproval ?? ''),
      forbidden: String(raw.forbidden ?? ''),
      result: String(raw.result ?? ''),
      missingFields: ((raw.missing_fields ?? raw.missingFields ?? []) as unknown[]).map((x) =>
        String(x)
      ),
      questions: ((raw.questions as Record<string, unknown>[]) ?? []).filter(
        (item) => item && typeof item === 'object'
      ),
      source: String(raw.source ?? 'heuristic'),
      text: String(raw.text ?? ''),
      autonomyLevel: Number(raw.autonomy_level ?? raw.autonomyLevel ?? 1) || 1
    },
    bpName: String(data.bp_name ?? data.bpName ?? ''),
    excerpt: String(data.excerpt ?? ''),
    functions: ((data.functions as Record<string, unknown>[]) ?? [])
      .filter((item) => String(item.name ?? '').trim())
      .map((item) => ({
        name: String(item.name ?? ''),
        description: String(item.description ?? ''),
        actionLevel: String(item.action_level ?? item.actionLevel ?? 'read'),
        requiresHumanApproval: Boolean(
          item.requires_human_approval ?? item.requiresHumanApproval
        ),
        automationKind: String(item.automation_kind ?? item.automationKind ?? 'auto')
      })),
    draftId: String(data.draftId ?? ''),
    llmError: String(data.llmError ?? raw.llm_error ?? ''),
    qaHistory: ((data.qaHistory as Record<string, unknown>[]) ?? []).map((item) => ({
      prompt: String(item.prompt ?? ''),
      answer: String(item.answer ?? ''),
      files: ((item.files as unknown[]) ?? []).map((x) => String(x))
    }))
  }
}

export function parseWorkflow(data: Record<string, unknown>): WorkflowRecord {
  const planData = asRecord(data.plan)
  const hasPlan = Boolean(data.plan && typeof data.plan === 'object')
  return {
    id: String(data.id ?? ''),
    title: String(data.title ?? 'Без названия'),
    phase: String(data.phase ?? 'document'),
    notes: String(data.notes ?? ''),
    localRun: asRecord(data.local_run ?? data.localRun),
    lastResult: String(data.last_result ?? data.lastResult ?? ''),
    plan: hasPlan
      ? {
          title: String(planData.title ?? ''),
          goal: String(planData.goal ?? ''),
          constraints: ((planData.constraints as unknown[]) ?? []).map((x) => String(x)),
          outOfScope: ((planData.out_of_scope ?? planData.outOfScope ?? []) as unknown[]).map((x) =>
            String(x)
          ),
          steps: ((planData.steps as Record<string, unknown>[]) ?? []).map((s) => ({
            id: String(s.id ?? ''),
            title: String(s.title ?? ''),
            action: String(s.action ?? ''),
            doneWhen: String(s.done_when ?? s.doneWhen ?? '')
          })),
          testCriteria: ((planData.test_criteria ?? planData.testCriteria ?? []) as unknown[]).map(
            (x) => String(x)
          ),
          openQuestions: (
            (planData.open_questions ?? planData.openQuestions ?? []) as Record<string, unknown>[]
          ).map((q) => ({
            id: String(q.id ?? ''),
            question: String(q.question ?? ''),
            why: String(q.why ?? ''),
            answer: String(q.answer ?? ''),
            options: ((q.options as unknown[]) ?? []).map((x) => String(x))
          })),
          rawText: String(planData.raw_text ?? planData.rawText ?? '')
        }
      : null
  }
}

export function parseScheduleTrigger(raw: Record<string, unknown>): ScheduleTriggerSpec {
  const kindRaw = String(raw.kind ?? 'event').toLowerCase()
  const kind: TriggerKind =
    kindRaw === 'interval' || kindRaw === 'datetime' ? (kindRaw as TriggerKind) : 'event'
  const unitRaw = String(raw.interval_unit ?? raw.intervalUnit ?? 'hours').toLowerCase()
  const intervalUnit: IntervalUnit =
    unitRaw === 'minutes' || unitRaw === 'days' ? (unitRaw as IntervalUnit) : 'hours'
  const weekdaysRaw = raw.weekdays ?? raw.active_days
  const weekdays = Array.isArray(weekdaysRaw)
    ? weekdaysRaw
        .map((day) => Number(day))
        .filter((day) => Number.isInteger(day) && day >= 0 && day <= 6)
    : []
  return {
    kind,
    message: String(raw.message ?? ''),
    intervalValue: Number(raw.interval_value ?? raw.intervalValue ?? 0) || 0,
    intervalUnit,
    condition: String(raw.condition ?? ''),
    at: String(raw.at ?? ''),
    once: Boolean(raw.once),
    weekdays,
    windowStart: String(raw.window_start ?? raw.windowStart ?? ''),
    windowEnd: String(raw.window_end ?? raw.windowEnd ?? '')
  }
}

export function parseScheduleDraft(raw: Record<string, unknown>): ScheduleDraft {
  const triggers = ((raw.triggers as Record<string, unknown>[]) ?? [])
    .filter((t) => t && typeof t === 'object')
    .map((t) => parseScheduleTrigger(t))
  return {
    name: String(raw.name ?? ''),
    goal: String(raw.goal ?? ''),
    summary: String(raw.summary ?? raw.description ?? raw.recommendation ?? ''),
    triggers
  }
}

function parseAgentRunItem(item: Record<string, unknown>, workflowId: string): AgentRunHistoryItem {
  return {
    runId: String(item.run_id ?? item.runId ?? item.id ?? ''),
    workflowId: String(item.workflow_id ?? item.workflowId ?? workflowId),
    status: String(item.status ?? ''),
    source: String(item.source ?? ''),
    message: String(item.message ?? ''),
    triggerKind: String(item.trigger_kind ?? item.triggerKind ?? ''),
    triggerReason: String(item.trigger_reason ?? item.triggerReason ?? ''),
    startedAt: String(item.started_at ?? item.startedAt ?? ''),
    finishedAt: String(item.finished_at ?? item.finishedAt ?? ''),
    summary: String(item.summary ?? item.answer ?? item.result ?? ''),
    answer: String(item.answer ?? item.summary ?? item.result ?? ''),
    agentWorkMs: Math.max(0, Number(item.agent_work_ms ?? item.agentWorkMs ?? 0) || 0),
    humanWaitMs: Math.max(0, Number(item.human_wait_ms ?? item.humanWaitMs ?? 0) || 0),
    openSegment: String(item.open_segment ?? item.openSegment ?? ''),
    openSegmentAt: String(item.open_segment_at ?? item.openSegmentAt ?? '')
  }
}

export function scheduleTriggerToApi(spec: ScheduleTriggerSpec): Record<string, unknown> {
  return {
    kind: spec.kind,
    message: spec.message,
    interval_value: spec.intervalValue,
    interval_unit: spec.intervalUnit,
    condition: spec.condition,
    at: spec.at,
    once: spec.once,
    weekdays: spec.weekdays ?? [],
    window_start: spec.windowStart ?? '',
    window_end: spec.windowEnd ?? ''
  }
}

export function scheduleDraftToApi(draft: ScheduleDraft): Record<string, unknown> {
  return {
    name: draft.name,
    goal: draft.goal,
    triggers: draft.triggers.map((t) => scheduleTriggerToApi(t))
  }
}

function parseKpiSide(raw: Record<string, unknown>): KpiSide {
  const value = raw.value
  return {
    label: String(raw.label ?? ''),
    value: value === null || value === undefined ? null : (value as number | string),
    unit: String(raw.unit ?? ''),
    description: String(raw.description ?? '')
  }
}

function parseKpiMethod(raw: Record<string, unknown>): KpiMethod {
  const schedule = asRecord(raw.schedule)
  const hasSchedule = Boolean(raw.schedule && typeof raw.schedule === 'object')
  return {
    how: String(raw.how ?? ''),
    when: String(raw.when ?? ''),
    planUpdate: String(raw.plan_update ?? raw.planUpdate ?? ''),
    factUpdate: String(raw.fact_update ?? raw.factUpdate ?? ''),
    percentFormula: String(raw.percent_formula ?? raw.percentFormula ?? ''),
    planExplanation: String(raw.plan_explanation ?? raw.planExplanation ?? ''),
    factExplanation: String(raw.fact_explanation ?? raw.factExplanation ?? ''),
    scoreExplanation: String(raw.score_explanation ?? raw.scoreExplanation ?? ''),
    system: String(raw.system ?? ''),
    greenMin: Number(raw.green_min ?? raw.greenMin ?? 90) || 90,
    yellowMin: Number(raw.yellow_min ?? raw.yellowMin ?? 70) || 70,
    schedule: hasSchedule
      ? {
          kind: String(schedule.kind ?? ''),
          intervalSeconds: Number(schedule.interval_seconds ?? schedule.intervalSeconds ?? 0) || 0,
          at: String(schedule.at ?? '')
        }
      : null
  }
}

export function parseKpiTile(raw: Record<string, unknown>): KpiTile {
  const measure = asRecord(raw.measure)
  const hasMeasure = Boolean(raw.measure && typeof raw.measure === 'object')
  const method = asRecord(raw.method)
  const hasMethod = Boolean(raw.method && typeof raw.method === 'object')
  const score = raw.score_percent ?? raw.scorePercent
  return {
    id: String(raw.id ?? ''),
    name: String(raw.name ?? ''),
    plan: parseKpiSide(asRecord(raw.plan)),
    fact: parseKpiSide(asRecord(raw.fact)),
    measure: hasMeasure
      ? {
          kind: String(measure.kind ?? ''),
          params: asRecord(measure.params),
          formula: String(measure.formula ?? '')
        }
      : null,
    scorePercent: score === null || score === undefined ? null : Number(score),
    color: String(raw.color ?? ''),
    updatedAt: String(raw.updated_at ?? raw.updatedAt ?? ''),
    nextRunAt: String(raw.next_run_at ?? raw.nextRunAt ?? ''),
    evidence: String(raw.evidence ?? ''),
    method: hasMethod ? parseKpiMethod(method) : null
  }
}

export function intervalSecondsFromUnit(value: number, unit: IntervalUnit): number {
  const amount = Math.max(0, Number(value) || 0)
  if (unit === 'minutes') return Math.round(amount * 60)
  if (unit === 'days') return Math.round(amount * 86400)
  return Math.round(amount * 3600)
}

export function kpiFromRecord(record: WorkflowRecord | null | undefined): AgentKpi | null {
  if (!record) return null
  const local = record.localRun ?? {}
  return parseAgentKpi(asRecord((local as Record<string, unknown>).kpi))
}

export function scheduleDraftFromRecord(
  record: WorkflowRecord | null | undefined
): ScheduleDraft | null {
  if (!record) return null
  const local = record.localRun ?? {}
  const raw = (local as Record<string, unknown>).schedule_draft
  if (!raw || typeof raw !== 'object') return null
  return parseScheduleDraft(asRecord(raw))
}

export function parsePositionOrchestrator(raw: Record<string, unknown> | null | undefined): PositionOrchestrator {
  const data = raw && typeof raw === 'object' ? raw : {}
  const tiles = ((data.tiles as Record<string, unknown>[]) ?? [])
    .filter((item) => item && typeof item === 'object')
    .map((item) => parseKpiTile(item))
  const agents = ((data.agents as Record<string, unknown>[]) ?? [])
    .filter((item) => item && typeof item === 'object')
    .map((item) => ({
      id: String(item.id ?? ''),
      title: String(item.title ?? ''),
      goal: String(item.goal ?? ''),
      steps: Array.isArray(item.steps) ? (item.steps as Array<Record<string, unknown>>) : []
    }))
  const user = asRecord(data.user)
  return {
    status: String(data.status ?? 'empty'),
    locked: Boolean(data.locked),
    summary: String(data.summary ?? ''),
    tiles,
    sourceFingerprint: String(data.source_fingerprint ?? data.sourceFingerprint ?? ''),
    currentFingerprint: String(data.current_fingerprint ?? data.currentFingerprint ?? ''),
    sourceAgentIds: Array.isArray(data.source_agent_ids)
      ? (data.source_agent_ids as unknown[]).map((item) => String(item))
      : [],
    needsForm: Boolean(data.needs_form ?? data.needsForm),
    needsCalc: Boolean(data.needs_calc ?? data.needsCalc),
    dueTileIds: Array.isArray(data.due_tile_ids)
      ? (data.due_tile_ids as unknown[]).map((item) => String(item))
      : [],
    sdkAgentId: String(data.sdk_agent_id ?? data.sdkAgentId ?? ''),
    formedAt: String(data.formed_at ?? data.formedAt ?? ''),
    formPrompt: String(data.form_prompt ?? data.formPrompt ?? ''),
    calcPrompt: String(data.calc_prompt ?? data.calcPrompt ?? ''),
    agents,
    user: {
      id: String(user.id ?? ''),
      fio: String(user.fio ?? ''),
      position: String(user.position ?? '')
    }
  }
}

export function parseAgentKpi(raw: Record<string, unknown> | null | undefined): AgentKpi | null {
  if (!raw || typeof raw !== 'object') return null
  const tiles = ((raw.tiles as Record<string, unknown>[]) ?? [])
    .filter((t) => t && typeof t === 'object')
    .map((t) => parseKpiTile(t))
  if (tiles.length === 0 && !raw.summary) return null
  return {
    status: String(raw.status ?? ''),
    generatedAt: String(raw.generated_at ?? raw.generatedAt ?? ''),
    summary: String(raw.summary ?? ''),
    title: String(raw.title ?? ''),
    workflowId: String(raw.workflow_id ?? raw.workflowId ?? ''),
    tiles
  }
}

export function passportToApi(passport: AgentPassport): Record<string, unknown> {
  return {
    name: passport.name,
    goal: passport.goal,
    trigger: passport.trigger,
    receives: passport.receives,
    checks: passport.checks,
    decisions: passport.decisions,
    can_autonomous: passport.canAutonomous,
    needs_human_approval: passport.needsHumanApproval,
    forbidden: passport.forbidden,
    result: passport.result,
    missing_fields: passport.missingFields,
    questions: passport.questions,
    source: passport.source,
    text: passport.text,
    autonomy_level: passport.autonomyLevel
  }
}

export function notesFromPassport(session: PassportSession): string {
  const p = session.passport
  if (p.text.trim()) return p.text.trim()
  return [
    `ИИ-агент: ${p.name || session.bpName || '—'}`,
    `Цель: ${p.goal || '—'}`,
    `Триггер: ${p.trigger || '—'}`,
    `Получает: ${p.receives || '—'}`,
    `Проверяет: ${p.checks || '—'}`,
    `Принимает решения: ${p.decisions || '—'}`,
    `Может самостоятельно: ${p.canAutonomous || '—'}`,
    `Требует подтверждения человека: ${p.needsHumanApproval || '—'}`,
    `Не может: ${p.forbidden || '—'}`,
    `Результат: ${p.result || '—'}`
  ].join('\n')
}

export function suggestionsFromRoleMatch(roleMatch: RoleMatchResult): AgentSuggestion[] {
  const functions =
    roleMatch.functions.length > 0
      ? roleMatch.functions
      : roleMatch.matches
          .filter((item) => item.status !== 'rejected')
          .map((item) => item.function)
          .filter((item): item is RoleFunction => item !== null)
  const seen = new Set<string>()
  const out: AgentSuggestion[] = []
  functions.forEach((fn, index) => {
    const key = fn.functionId || `${fn.action}:${fn.object}` || String(index)
    if (seen.has(key)) return
    seen.add(key)
    const titleBase = (fn.title.split('→', 1)[0] || '').trim()
    const title =
      titleBase ||
      [fn.action, fn.object].filter(Boolean).join(' ') ||
      `бизнес-процесса ${index + 1}`
    out.push({
      agentId: `agent-suggestion-${String(index + 1).padStart(3, '0')}`,
      title: `ИИ-агент: ${title}`.slice(0, 180),
      description: fn.explanation,
      regulationId: roleMatch.regulationId,
      roleMatchRunId: roleMatch.runId,
      functionId: fn.functionId,
      sourceBlockId: fn.targetBlockId
    })
  })
  return out
}


export class ApiClient {
  private token: string | null = null

  setToken(token: string | null): void {
    this.token = token
  }

  getToken(): string | null {
    return this.token
  }

  private async request<T = unknown>(
    method: string,
    path: string,
    opts: { body?: unknown; params?: Params; timeoutMs?: number } = {}
  ): Promise<T> {
    const res = await window.api.request<T>({
      method,
      path,
      body: opts.body,
      params: opts.params,
      token: this.token,
      timeoutMs: opts.timeoutMs
    })
    if (!res.ok) {
      throw new ApiError(res.error || 'Ошибка backend', res.status)
    }
    return (res.data ?? ({} as T)) as T
  }

  // ---------- Auth ----------
  async login(fio: string, password: string): Promise<LoginResult> {
    const data = await this.request<Record<string, unknown>>('POST', '/api/v1/auth/login', {
      body: { fio, password, client: 'orchestrator' }
    })
    const token = String(data.access_token ?? '')
    this.token = token
    return { accessToken: token, user: parseUser((data.user as Record<string, unknown>) ?? {}) }
  }

  async me(timeoutMs = 15_000): Promise<UserProfile> {
    const data = await this.request<Record<string, unknown>>('GET', '/api/v1/auth/me', {
      timeoutMs
    })
    return parseUser(data)
  }

  async searchUsers(search = ''): Promise<string[]> {
    try {
      const data = await this.request<{ items?: unknown[] }>('GET', '/api/v1/auth/users', {
        params: search.trim() ? { search } : undefined
      })
      return (data.items ?? []).map((x) => String(x))
    } catch {
      return []
    }
  }

  // ---------- Regulations ----------
  async uploadRegulation(filePath: string): Promise<RegulationParseResult> {
    const res = await window.api.upload<Record<string, unknown>>({
      endpoint: '/api/v1/regulations/upload',
      filePath,
      token: this.token,
      timeoutMs: 420_000
    })
    if (!res.ok) throw new ApiError(res.error || 'Ошибка распознавания', res.status)
    return parseRegulation(res.data ?? {})
  }

  async startRegulationCreation(): Promise<RegulationCreationSession> {
    const data = await this.request<Record<string, unknown>>(
      'POST',
      '/api/v1/regulation-creation/sessions',
      { timeoutMs: 120_000 }
    )
    return parseCreationSession(data)
  }

  async getRegulationCreationSession(draftId: string): Promise<RegulationCreationSession> {
    const data = await this.request<Record<string, unknown>>(
      'GET',
      `/api/v1/regulation-creation/sessions/${draftId}`,
      { timeoutMs: 60_000 }
    )
    return parseCreationSession(data)
  }

  async sendRegulationCreationMessage(
    draftId: string,
    message: string
  ): Promise<RegulationCreationSession> {
    const data = await this.request<Record<string, unknown>>(
      'POST',
      `/api/v1/regulation-creation/sessions/${draftId}/messages`,
      { body: { message }, timeoutMs: 600_000 }
    )
    return parseCreationSession(data)
  }

  async streamRegulationCreationMessage(
    draftId: string,
    message: string,
    filePaths: string[],
    onEvent: (event: StreamEvent) => void
  ): Promise<RegulationCreationSession> {
    const unsubscribe = window.api.onStreamEvent((payload) => {
      const type = String(payload.type || '')
      if (type === 'session') return
      onEvent({
        type,
        text: String(payload.text || payload.message || ''),
        message: String(payload.message || ''),
        tool: String(payload.tool || '')
      })
    })
    try {
      const hasFiles = Array.isArray(filePaths) && filePaths.length > 0
      const res = await window.api.stream<Record<string, unknown>>({
        method: 'POST',
        path: `/api/v1/regulation-creation/sessions/${draftId}/messages/stream`,
        body: hasFiles ? undefined : { message },
        filePaths: hasFiles ? filePaths : undefined,
        extraFields: hasFiles ? { message } : undefined,
        token: this.token
      })
      if (!res.ok) throw new ApiError(res.error || 'Ошибка потока регламента', res.status)
      return parseCreationSession(res.data ?? {})
    } finally {
      unsubscribe()
    }
  }

  async terminateRegulationCreationSessions(): Promise<void> {
    try {
      await this.request('POST', '/api/v1/regulation-creation/sessions/terminate-active', {
        timeoutMs: 30_000
      })
    } catch {
      /* ignore */
    }
  }

  // ---------- Workflows / board ----------
  async listWorkflows(): Promise<WorkflowListItem[]> {
    const data = await this.request<unknown>('GET', '/api/v1/workflows')
    return parseWorkflowList(data)
  }

  async getWorkflowBoard(params?: {
    window_from?: string
    window_to?: string
    workflow_id?: string
  }): Promise<WorkflowBoard> {
    const data = await this.request<Record<string, unknown>>('GET', '/api/v1/workflows/board', {
      params,
      timeoutMs: 15_000
    })
    return parseBoard(data)
  }

  async createTimedTrigger(workflowId: string, at: string, message = ''): Promise<void> {
    await this.request('POST', '/api/v1/triggers', {
      body: { workflow_id: workflowId, at, once: true, message: message.trim() },
      timeoutMs: 30_000
    })
  }

  async cancelTrigger(triggerId: string): Promise<void> {
    await this.request('POST', `/api/v1/triggers/${triggerId}/cancel`, { timeoutMs: 30_000 })
  }

  async skipTriggerSlot(triggerId: string, at: string): Promise<void> {
    await this.request('POST', `/api/v1/triggers/${triggerId}/skip-slot`, {
      body: { at },
      timeoutMs: 30_000
    })
  }

  async deleteWorkflow(workflowId: string): Promise<void> {
    await this.request('DELETE', `/api/v1/workflows/${workflowId}`, { timeoutMs: 60_000 })
  }

  async stopWorkflowAutoRun(workflowId: string): Promise<void> {
    await this.request('POST', `/api/v1/workflows/${workflowId}/stop-auto-run`, {
      timeoutMs: 30_000
    })
  }

  async resumeWorkflowAutoRun(workflowId: string): Promise<void> {
    await this.request('POST', `/api/v1/workflows/${workflowId}/resume-auto-run`, {
      timeoutMs: 30_000
    })
  }

  async proposeScheduleDraft(workflowId: string): Promise<ScheduleDraft> {
    const data = await this.request<Record<string, unknown>>(
      'POST',
      `/api/v1/workflows/${workflowId}/schedule-draft`,
      { timeoutMs: 90_000 }
    )
    return parseScheduleDraft(data ?? {})
  }

  async listAgentRuns(workflowId: string): Promise<AgentRunHistoryItem[]> {
    const data = await this.request<Record<string, unknown>[] | { items?: Record<string, unknown>[] }>(
      'GET',
      `/api/v1/workflows/${workflowId}/runs`,
      { timeoutMs: 60_000 }
    )
    const items = Array.isArray(data) ? data : (data.items ?? [])
    return (items as Record<string, unknown>[])
      .filter((item) => item && typeof item === 'object')
      .map((item) => parseAgentRunItem(item, workflowId))
  }

  async listAgentDrafts(): Promise<AgentDraft[]> {
    const data = await this.request<{ items?: Record<string, unknown>[] }>(
      'GET',
      '/api/v1/agents/drafts',
      { timeoutMs: 60_000 }
    )
    return ((data.items ?? []) as Record<string, unknown>[]).map(parseDraft)
  }

  async extractRegulationFunctions(
    regulationId: string,
    position: string,
    department: string
  ): Promise<RoleMatchResult> {
    const data = await this.request<Record<string, unknown>>(
      'POST',
      `/api/v1/regulations/${regulationId}/function-extraction`,
      { body: { position, department }, timeoutMs: 420_000 }
    )
    return parseRoleMatch(data)
  }

  async decideRoleMatch(
    regulationId: string,
    runId: string,
    matchId: string,
    status: string
  ): Promise<RoleMatchResult> {
    const data = await this.request<Record<string, unknown>>(
      'PATCH',
      `/api/v1/regulations/${regulationId}/role-matches/${runId}/${matchId}`,
      { body: { status }, timeoutMs: 60_000 }
    )
    return parseRoleMatch(data)
  }

  async createAgentDraft(regulationId: string, roleMatchRunId: string): Promise<AgentDraft> {
    const data = await this.request<Record<string, unknown>>(
      'POST',
      `/api/v1/regulations/${regulationId}/role-matches/${roleMatchRunId}/draft`,
      { timeoutMs: 120_000 }
    )
    return parseDraft(data)
  }

  async ensureDraftReadiness(draftId: string): Promise<AgentDraft> {
    const data = await this.request<Record<string, unknown>>(
      'POST',
      `/api/v1/agents/drafts/${draftId}/readiness`,
      { timeoutMs: 180_000 }
    )
    return parseDraft(data)
  }

  async updateAgentDraftStatus(draftId: string, status: string): Promise<AgentDraft> {
    const data = await this.request<Record<string, unknown>>(
      'PATCH',
      `/api/v1/agents/drafts/${draftId}/status`,
      { body: { status }, timeoutMs: 60_000 }
    )
    return parseDraft(data)
  }

  async getAgentDraft(draftId: string): Promise<AgentDraft> {
    const data = await this.request<Record<string, unknown>>(
      'GET',
      `/api/v1/agents/drafts/${draftId}`,
      { timeoutMs: 60_000 }
    )
    return parseDraft(data)
  }

  async uploadAgentDraftFiles(
    draftId: string,
    filePaths: string[],
    functionId = ''
  ): Promise<AgentDraftFile[]> {
    const uploaded: AgentDraftFile[] = []
    for (const filePath of filePaths) {
      const res = await window.api.upload<Record<string, unknown>>({
        endpoint: `/api/v1/agents/drafts/${draftId}/files`,
        filePath,
        fieldName: 'files',
        token: this.token,
        extraFields: functionId ? { functionId } : undefined,
        timeoutMs: 180_000
      })
      if (!res.ok) throw new ApiError(res.error || 'Не удалось прикрепить файл', res.status)
      const files = ((res.data?.files as Record<string, unknown>[]) ?? []).map(parseDraftFile)
      uploaded.splice(0, uploaded.length, ...files)
    }
    return uploaded
  }

  async createQuestionChat(draftId: string, questionId: string): Promise<QuestionChatSession> {
    const data = await this.request<Record<string, unknown>>(
      'POST',
      `/api/v1/agents/drafts/${draftId}/questions/${questionId}/chat`,
      { timeoutMs: 120_000 }
    )
    return parseQuestionChat(data)
  }

  async latestQuestionChat(draftId: string): Promise<QuestionChatSession> {
    const data = await this.request<Record<string, unknown>>(
      'GET',
      `/api/v1/agents/drafts/${draftId}/chat/latest`,
      { timeoutMs: 60_000 }
    )
    return parseQuestionChat(data)
  }

  async sendQuestionChatMessage(
    draftId: string,
    questionId: string,
    message: string
  ): Promise<QuestionChatSession> {
    const data = await this.request<Record<string, unknown>>(
      'POST',
      `/api/v1/agents/drafts/${draftId}/questions/${questionId}/chat/messages`,
      { body: { message }, timeoutMs: 180_000 }
    )
    return parseQuestionChat(data)
  }

  async draftPassportFromSuggestion(
    suggestion: AgentSuggestion,
    draftId = '',
    agentId = ''
  ): Promise<PassportSession> {
    const data = await this.request<Record<string, unknown>>(
      'POST',
      '/api/v1/regulations/passport/draft-from-suggestion',
      {
        body: {
          regulationId: suggestion.regulationId,
          roleMatchRunId: suggestion.roleMatchRunId,
          functionId: suggestion.functionId,
          agentTitle: suggestion.title,
          agentDescription: suggestion.description,
          draftId,
          agentId
        },
        timeoutMs: 180_000
      }
    )
    return parsePassportSession(data)
  }

  async completePassport(
    session: PassportSession,
    answers: Record<string, string>,
    suggestion: AgentSuggestion,
    draftId = '',
    agentId = ''
  ): Promise<PassportSession> {
    const data = await this.request<Record<string, unknown>>(
      'POST',
      '/api/v1/regulations/passport/complete',
      {
        body: {
          passport: passportToApi(session.passport),
          answers,
          field_updates: {},
          bp_name: session.bpName,
          excerpt: session.excerpt,
          functions: session.functions.map((item) => ({
            name: item.name,
            description: item.description,
            action_level: item.actionLevel,
            requires_human_approval: item.requiresHumanApproval,
            automation_kind: item.automationKind
          })),
          draftId: draftId || session.draftId,
          agentId,
          functionId: suggestion.functionId,
          regulationId: suggestion.regulationId,
          roleMatchRunId: suggestion.roleMatchRunId,
          qaHistory: session.qaHistory
        },
        timeoutMs: 180_000
      }
    )
    return parsePassportSession(data)
  }

  async createWorkflow(notes: string, draftId = ''): Promise<WorkflowRecord> {
    const res = await window.api.createWorkflow<Record<string, unknown>>({
      notes,
      draftId,
      token: this.token
    })
    if (!res.ok) throw new ApiError(res.error || 'Ошибка создания workflow', res.status)
    return parseWorkflow(res.data ?? {})
  }

  async getWorkflow(workflowId: string): Promise<WorkflowRecord> {
    const data = await this.request<Record<string, unknown>>(
      'GET',
      `/api/v1/workflows/${workflowId}`,
      { timeoutMs: 60_000 }
    )
    return parseWorkflow(data)
  }

  async updateWorkflowLocalRun(
    workflowId: string,
    localRun: Record<string, unknown>
  ): Promise<WorkflowRecord> {
    const data = await this.request<Record<string, unknown>>(
      'PATCH',
      `/api/v1/workflows/${workflowId}/local-run`,
      { body: { local_run: localRun }, timeoutMs: 60_000 }
    )
    return parseWorkflow(data)
  }

  async confirmWorkflowKpi(workflowId: string): Promise<WorkflowRecord> {
    const data = await this.request<Record<string, unknown>>(
      'POST',
      `/api/v1/workflows/${workflowId}/kpi/confirm`,
      { timeoutMs: 180_000 }
    )
    return parseWorkflow(data)
  }

  streamGenerateWorkflowKpi(
    workflowId: string,
    onEvent: (event: StreamEvent) => void
  ): Promise<WorkflowRecord> {
    return this.streamWorkflow(`/api/v1/workflows/${workflowId}/kpi/generate/stream`, onEvent)
  }

  async persistScheduleDraft(workflowId: string, draft: ScheduleDraft): Promise<WorkflowRecord> {
    const current = await this.getWorkflow(workflowId)
    const merged: Record<string, unknown> = {
      ...(current.localRun ?? {}),
      schedule_draft: scheduleDraftToApi(draft)
    }
    return this.updateWorkflowLocalRun(workflowId, merged)
  }

  async getWorkflowKpi(workflowId: string): Promise<AgentKpi | null> {
    const data = await this.request<Record<string, unknown>>(
      'GET',
      `/api/v1/workflows/${workflowId}/kpi`,
      { timeoutMs: 60_000 }
    )
    return parseAgentKpi(data ?? {})
  }

  async calculateWorkflowKpi(workflowId: string): Promise<AgentKpi | null> {
    const data = await this.request<Record<string, unknown>>(
      'POST',
      `/api/v1/workflows/${workflowId}/kpi/calculate`,
      { timeoutMs: 180_000 }
    )
    return parseAgentKpi(data ?? {})
  }

  async getOrchestrator(): Promise<PositionOrchestrator> {
    const data = await this.request<Record<string, unknown>>('GET', '/api/v1/orchestrator/me', {
      timeoutMs: 60_000
    })
    return parsePositionOrchestrator(data ?? {})
  }

  async ensureOrchestrator(mode: 'form' | 'calc'): Promise<PositionOrchestrator> {
    const data = await this.request<Record<string, unknown>>('POST', '/api/v1/orchestrator/ensure', {
      body: { mode },
      timeoutMs: 60_000
    })
    return parsePositionOrchestrator(data ?? {})
  }

  async createTriggerFromSpec(workflowId: string, spec: ScheduleTriggerSpec): Promise<void> {
    if (spec.kind === 'interval') {
      await this.createTrigger({
        workflowId,
        message: spec.message,
        intervalSeconds: intervalSecondsFromUnit(spec.intervalValue, spec.intervalUnit),
        once: false,
        activeDays: spec.weekdays ?? [],
        windowStart: spec.windowStart ?? '',
        windowEnd: spec.windowEnd ?? ''
      })
      return
    }
    if (spec.kind === 'event') {
      await this.createTrigger({
        workflowId,
        message: spec.message,
        condition: spec.condition,
        once: Boolean(spec.once)
      })
      return
    }
    await this.createTrigger({
      workflowId,
      message: spec.message,
      at: spec.at,
      once: Boolean(spec.once)
    })
  }

  async createTrigger(spec: {
    workflowId: string
    message?: string
    once?: boolean
    at?: string
    intervalSeconds?: number
    condition?: string
    activeDays?: number[]
    windowStart?: string
    windowEnd?: string
  }): Promise<void> {
    const body: Record<string, unknown> = {
      workflow_id: spec.workflowId,
      message: (spec.message || '').trim(),
      once: Boolean(spec.once)
    }
    if (spec.at) body.at = spec.at
    if (spec.intervalSeconds) {
      body.interval_seconds = spec.intervalSeconds
      body.once = false
    }
    if (spec.condition) body.condition = spec.condition.trim()
    if (spec.activeDays && spec.activeDays.length) body.active_days = spec.activeDays
    if (spec.windowStart) body.window_start = spec.windowStart
    if (spec.windowEnd) body.window_end = spec.windowEnd
    await this.request('POST', '/api/v1/triggers', { body, timeoutMs: 30_000 })
  }

  async getAgentRunDetail(
    workflowId: string,
    runId: string
  ): Promise<{ item: AgentRunHistoryItem; events: AgentRunnerEvent[] }> {
    const data = await this.request<Record<string, unknown>>(
      'GET',
      `/api/v1/workflows/${workflowId}/runs/${runId}`,
      { timeoutMs: 60_000 }
    )
    const rawEvents = Array.isArray(data.events) ? (data.events as Record<string, unknown>[]) : []
    const events: AgentRunnerEvent[] = rawEvents
      .filter((item) => item && typeof item === 'object')
      .map((item) => ({
        type: String(item.type ?? ''),
        text:
          item.text != null
            ? String(item.text)
            : item.answer != null
              ? String(item.answer)
              : undefined,
        message: item.message != null ? String(item.message) : undefined,
        answer: item.answer != null ? String(item.answer) : undefined,
        tool: item.tool != null ? String(item.tool) : undefined,
        title: item.title != null ? String(item.title) : undefined,
        requestId:
          item.requestId != null
            ? String(item.requestId)
            : item.request_id != null
              ? String(item.request_id)
              : undefined,
        arguments: (item.arguments as Record<string, unknown>) || undefined,
        result: item.result,
        ok: item.ok == null ? undefined : Boolean(item.ok),
        skipped: item.skipped == null ? undefined : Boolean(item.skipped),
        confirmOnly:
          item.confirm_only == null && item.confirmOnly == null
            ? undefined
            : Boolean(item.confirm_only ?? item.confirmOnly),
        error: item.error != null ? String(item.error) : undefined,
        status: item.status != null ? String(item.status) : undefined
      }))
    return {
      item: parseAgentRunItem({ ...data, id: data.run_id ?? data.runId ?? data.id ?? runId }, workflowId),
      events
    }
  }

  async finishLocalAgentRun(
    workflowId: string,
    runId: string,
    opts: { status: string; answer?: string }
  ): Promise<void> {
    await this.request('POST', `/api/v1/workflows/${workflowId}/runs/${runId}/finish`, {
      body: {
        status: opts.status,
        answer: opts.answer || '',
        events: [],
        message: ''
      },
      timeoutMs: 30_000
    })
  }

  async streamWorkflow(
    path: string,
    onEvent: (event: StreamEvent) => void,
    body?: unknown
  ): Promise<WorkflowRecord> {
    const unsubscribe = window.api.onStreamEvent((payload) => {
      const type = String(payload.type || '')
      const text = String(payload.text || payload.message || '')
      onEvent({ type, text, message: String(payload.message || ''), tool: String(payload.tool || '') })
    })
    try {
      const res = await window.api.stream<Record<string, unknown>>({
        method: 'POST',
        path,
        body,
        token: this.token
      })
      if (!res.ok) throw new ApiError(res.error || 'Ошибка потока workflow', res.status)
      return parseWorkflow(res.data ?? {})
    } finally {
      unsubscribe()
    }
  }

  streamPlanWorkflow(workflowId: string, onEvent: (event: StreamEvent) => void): Promise<WorkflowRecord> {
    return this.streamWorkflow(`/api/v1/workflows/${workflowId}/plan/stream`, onEvent)
  }

  streamDemoWorkflow(workflowId: string, onEvent: (event: StreamEvent) => void): Promise<WorkflowRecord> {
    return this.streamWorkflow(`/api/v1/workflows/${workflowId}/demo/stream`, onEvent)
  }

  streamClarifyWorkflow(
    workflowId: string,
    answers: Record<string, string>,
    onEvent: (event: StreamEvent) => void
  ): Promise<WorkflowRecord> {
    return this.streamWorkflow(`/api/v1/workflows/${workflowId}/clarify/stream`, onEvent, {
      answers
    })
  }

  // ---------- Files ----------
  async listPlatformFiles(): Promise<WorkflowFileItem[]> {
    const data = await this.request<Record<string, unknown>>('GET', '/api/v1/workflows/files', {
      timeoutMs: 20_000
    })
    const raw = (data.files as Record<string, unknown>[]) ?? []
    return raw.map(parsePlatformFile)
  }

  async listWorkflowFiles(workflowId: string, runId = ''): Promise<WorkflowFileItem[]> {
    const data = await this.request<Record<string, unknown>>(
      'GET',
      `/api/v1/workflows/${workflowId}/files`,
      { timeoutMs: 20_000, params: runId ? { run_id: runId } : undefined }
    )
    const userFiles = (data.user_files as Record<string, unknown>[]) ?? []
    const agentFiles = (data.agent_files as Record<string, unknown>[]) ?? []
    const runAttachments = (data.run_attachments as Record<string, unknown>[]) ?? []
    return [...userFiles, ...agentFiles, ...runAttachments].map((item) =>
      parsePlatformFile({ ...item, workflow_id: workflowId })
    )
  }

  async uploadWorkflowFiles(workflowId: string, filePaths: string[]): Promise<WorkflowFileItem[]> {
    let latest: WorkflowFileItem[] = []
    for (const filePath of filePaths) {
      const res = await window.api.upload<Record<string, unknown>>({
        endpoint: `/api/v1/workflows/${workflowId}/files`,
        filePath,
        fieldName: 'files',
        token: this.token,
        timeoutMs: 180_000
      })
      if (!res.ok) throw new ApiError(res.error || 'Не удалось загрузить файл', res.status)
      const userFiles = (res.data?.user_files as Record<string, unknown>[]) ?? []
      const agentFiles = (res.data?.agent_files as Record<string, unknown>[]) ?? []
      const runAttachments = (res.data?.run_attachments as Record<string, unknown>[]) ?? []
      latest = [...userFiles, ...agentFiles, ...runAttachments].map((item) =>
        parsePlatformFile({ ...item, workflow_id: workflowId })
      )
    }
    return latest
  }

  // ---------- Notifications ----------
  async listChatThreads(search = ''): Promise<ChatThread[]> {
    try {
      const data = await this.request<{ items?: Record<string, unknown>[] }>(
        'GET',
        '/api/v1/chat/threads',
        { params: search ? { search } : undefined }
      )
      return (data.items ?? []).map(parseChatThread)
    } catch {
      return []
    }
  }

  async listChatMessages(threadId: string): Promise<ChatMessage[]> {
    const data = await this.request<{ items?: Record<string, unknown>[] }>(
      'GET',
      `/api/v1/chat/threads/${threadId}/messages`
    )
    return (data.items ?? []).map(parseChatMessage)
  }

  async listDirectoryUsers(search = ''): Promise<DirectoryUser[]> {
    const paths = [
      '/api/v1/notifications/users',
      '/api/v1/auth/directory',
      '/api/v1/chat/directory'
    ]
    const byFio = new Map<string, DirectoryUser>()
    for (const path of paths) {
      try {
        const data = await this.request<unknown>('GET', path, {
          params: search ? { search } : undefined
        })
        for (const user of parseDirectoryUsers(data)) {
          const key = user.fio.trim().toLowerCase()
          if (!key) continue
          const prev = byFio.get(key)
          if (!prev) {
            byFio.set(key, user)
            continue
          }
          const id = prev.id || user.id
          byFio.set(key, {
            ...prev,
            ...user,
            id,
            position: prev.position || user.position,
            department: prev.department || user.department,
            avatarUrl:
              prev.avatarUrl ||
              user.avatarUrl ||
              (id ? `/api/v1/auth/users/${id}/avatar` : null)
          })
        }
      } catch {
        /* try next directory source */
      }
    }
    return [...byFio.values()].sort((a, b) => a.fio.localeCompare(b.fio, 'ru'))
  }

  async chatCommand(payload: Record<string, unknown>): Promise<string> {
    const data = await this.request<{ client_id?: string; clientId?: string }>(
      'POST',
      '/api/v1/chat/commands',
      { body: payload, timeoutMs: 30_000 }
    )
    return String(data.clientId ?? data.client_id ?? '')
  }

  async uploadChatFile(filePath: string): Promise<ChatAttachment> {
    const res = await window.api.upload<Record<string, unknown>>({
      endpoint: '/api/v1/chat/files',
      filePath,
      fieldName: 'file',
      token: this.token,
      timeoutMs: 60_000
    })
    if (!res.ok || !res.data) {
      throw new ApiError(res.error || 'Не удалось загрузить файл', res.status)
    }
    return {
      id: String(res.data.file_id ?? res.data.fileId ?? res.data.id ?? ''),
      filename: String(res.data.filename ?? ''),
      mime: String(res.data.mime ?? ''),
      size: Number(res.data.size ?? 0)
    }
  }

  async markChatRead(threadId: string): Promise<void> {
    try {
      await this.chatCommand({ type: 'mark_read', thread_id: threadId })
    } catch {
      /* ignore */
    }
  }

  async openDirectChat(peerId: string): Promise<void> {
    await this.chatCommand({ type: 'open_dm', peer_id: peerId })
  }

  async listNotifications(): Promise<InboxNotification[]> {
    const data = await this.request<{ items?: Record<string, unknown>[] }>(
      'GET',
      '/api/v1/notifications',
      { timeoutMs: 15_000 }
    )
    return ((data.items ?? []) as Record<string, unknown>[]).map(parseInboxNotification)
  }

  async markAllNotificationsRead(): Promise<void> {
    await this.request('POST', '/api/v1/notifications/read-all', { timeoutMs: 15_000 })
  }

  async markNotificationRead(notificationId: string): Promise<void> {
    await this.request(
      'POST',
      `/api/v1/notifications/${encodeURIComponent(notificationId)}/read`,
      { timeoutMs: 15_000 }
    )
  }

  async clearNotifications(): Promise<void> {
    await this.request('POST', '/api/v1/notifications/clear', { timeoutMs: 15_000 })
  }

  async deleteNotification(notificationId: string): Promise<void> {
    await this.request('DELETE', `/api/v1/notifications/${encodeURIComponent(notificationId)}`, {
      timeoutMs: 15_000
    })
  }

  async unreadNotificationCount(): Promise<number> {
    try {
      const data = await this.request<{ unread?: number; count?: number }>(
        'GET',
        '/api/v1/notifications/unread-count',
        { timeoutMs: 8_000 }
      )
      return Number(data.unread ?? data.count ?? 0)
    } catch {
      return 0
    }
  }

  async getHealth(): Promise<AppHealth> {
    const data = await this.request<Record<string, unknown>>('GET', '/health', { timeoutMs: 10_000 })
    return {
      status: String(data.status ?? ''),
      erpReachable: Boolean(data.erp_reachable ?? data.erpReachable),
      erpServer: String(data.erp_server ?? data.erpServer ?? ''),
      llmProvider: String(data.llm_provider ?? data.llmProvider ?? '')
    }
  }

  async getWorkflowHealth(): Promise<WorkflowHealthInfo> {
    const data = await this.request<Record<string, unknown>>('GET', '/api/v1/workflows/health', {
      timeoutMs: 15_000
    })
    return {
      ok: Boolean(data.ok),
      who: String(data.who ?? ''),
      message: String(data.message ?? '')
    }
  }

  async getToolStatus(kind: 'onec' | 'imap' | 'turboproject'): Promise<ToolStatus> {
    const data = await this.request<Record<string, unknown>>('GET', `/api/v1/tools/${kind}/status`, {
      timeoutMs: 10_000
    })
    return {
      name: kind,
      configured: Boolean(data.configured),
      mode: String(data.mode ?? (data.configured ? 'real' : 'stub'))
    }
  }

  async listSupportTickets(shelf: 'queue' | 'mine' | 'all' = 'all'): Promise<SupportTicketItem[]> {
    const data = await this.request<{ items?: Record<string, unknown>[] }>(
      'GET',
      `/api/v1/chat/support/${shelf}`,
      { timeoutMs: 20_000 }
    )
    return ((data.items ?? []) as Record<string, unknown>[]).map((item) => ({
      id: String(item.id ?? ''),
      threadId: String(item.thread_id ?? item.threadId ?? ''),
      status: String(item.status ?? ''),
      assignedTo: String(item.assigned_to ?? item.assignedTo ?? ''),
      authorId: String(item.author_id ?? item.authorId ?? ''),
      authorFio: String(item.author_fio ?? item.authorFio ?? ''),
      authorPosition: String(item.author_position ?? item.authorPosition ?? ''),
      preview: String(item.preview ?? ''),
      queuedAt: String(item.queued_at ?? item.queuedAt ?? '')
    }))
  }

  async fetchDataUrl(url: string): Promise<string | null> {
    if (!url) return null
    const res = await window.api.fetchDataUrl({ url, token: this.token })
    return res.ok && res.dataUrl ? res.dataUrl : null
  }

  // ---------- Download ----------
  async download(url: string, defaultName: string): Promise<boolean> {
    const res = await window.api.download({ url, defaultName, token: this.token })
    return Boolean(res.ok)
  }
}

export const api = new ApiClient()
