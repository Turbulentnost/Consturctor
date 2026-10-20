export interface Health {
  status: string
  sdk: string
  agents: number
  tools: number
  skills: number
  constructor: OwnersState
}

export interface ToolEnvField {
  key: string
  label: string
  hint: string
  secret: boolean
  default: string
  /** Для секретов всегда пусто: сервер отдаёт только is_set. */
  value: string
  is_set: boolean
  /** TurboTester, Constructor desktop, Constructor backend или пусто. */
  source: string
  overridden: boolean
  constructor_value: string
  constructor_set: boolean
  constructor_source: string
}

export interface ToolEnvGroup {
  id: string
  title: string
  summary: string
  fields: ToolEnvField[]
}

export interface ToolEnvSnapshot {
  env_file: string
  sources: { label: string; path: string; found: boolean }[]
  groups: ToolEnvGroup[]
}

export interface AgentUserProfile {
  fio: string
  position: string
  department: string
  verified: boolean
  checked_at: string
}

export interface AgentUserState {
  fio: string
  password_set: boolean
  profile: AgentUserProfile | null
  error: string
}

export interface AgentSpec {
  id: string
  title: string
  description: string
  model: string
  modes: string[]
  tool_names: string[]
  source: 'local' | 'constructor'
  owner_id: string
  owner_fio: string
}

export type OwnersState = 'idle' | 'ready' | 'error'

export interface ConstructorAgent {
  id: string
  title: string
  description: string
  status: 'active' | 'paused'
  tools: string[]
  trigger_summary: string
  updated_at: string | null
}

export interface AgentDetail {
  id: string
  title: string
  name: string
  description: string
  prompt: string
  example_run: string
  chain: string
  steps: string[]
  status: 'active' | 'paused'
  tools: string[]
  trigger_summary: string
  owner_fio: string
  owner_position: string
  updated_at: string | null
}

export interface AgentOwner {
  id: string
  fio: string
  position: string
  department: string
  avatar_url: string | null
  agents: ConstructorAgent[]
}

export interface OwnersSnapshot {
  state: OwnersState
  refreshing: boolean
  error: string
  source: string
  loaded_at: string | null
  items: AgentOwner[]
}

export type ToolSideEffect = 'read' | 'create_draft' | 'write' | 'dangerous'

export interface ToolSpec {
  name: string
  title: string
  group: string
  summary: string
  description: string
  input_schema: JsonSchema
  execution: 'local' | 'server'
  runtime: string
  side_effect: ToolSideEffect
  requires_approval: boolean
  timeout_seconds: number
  requires: string[]
  source: { project: 'NewConstructor' | 'AIAgentBack'; path: string } | null
  replaces: string[]
  available: boolean
  unavailable_reason: string
}

export interface JsonSchema {
  type?: string | string[]
  description?: string
  properties?: Record<string, JsonSchema>
  required?: string[]
  items?: JsonSchema
  enum?: unknown[]
  default?: unknown
  $ref?: string
  [key: string]: unknown
}

export interface ToolGroup {
  id: string
  title: string
  summary: string
  order: number
  requires: string[]
  tool_count: number
  available_count: number
}

export interface ToolCallResult {
  tool: string
  ok: boolean
  result: unknown
  error: string | null
  duration_ms: number
}

export interface SkillSpec {
  id: string
  title: string
  description: string
}

export interface RunRecord {
  id: string
  agent_id: string
  prompt: string
  tool_names: string[]
  status: string
  message: string
  created_at: string
}

export interface ModelParam {
  id: string
  value: string
}

export interface PlatformConfig {
  id: string
  title: string
  description: string
  model: string
  model_params?: ModelParam[]
  tags: string[]
  entry: string[]
  prompt_source: 'instruction'
  attachments: boolean
  plan_instruction: boolean
  path: string
  error: string
  runnable: boolean
}

export interface SharedAgentTool {
  name: string
  calls: number
  errors: number
}

/** Агент конфигурации с plan_instruction: из общей базы (turbotest.agents) или ещё только локальный. */
export interface SharedAgent {
  id: string
  title: string
  config_id: string
  request: string
  /** План в markdown — инструкция агента; пусто, пока план составляется. */
  instruction: string
  author: string
  author_host: string
  created_at: string
  updated_at: string
  runs: number
  tools: SharedAgentTool[]
  last_run: { status: SessionStatus; finished_at: string; steps: number; error: string } | null
  /** Паспорт в формате Constructor; заполняет облачный агент Cursor после успешного прогона. */
  passport: AgentPassport | null
  /** Контурная SVG-иконка 24×24 в стиле иконок программы, уже очищенная сервером. */
  icon_svg: string
  profile_status: '' | 'pending' | 'ready' | 'error'
  profile_error: string
  shared: boolean
  mine: boolean
}

export interface AgentPassport {
  name: string
  goal: string
  trigger: string
  receives: string
  checks: string
  decisions: string
  can_autonomous: string
  needs_human_approval: string
  forbidden: string
  result: string
}

export interface SharedAgentsResponse {
  items: SharedAgent[]
  shared?: { enabled: boolean; source: string; error: string }
}

/** Агент, сформированный в Конструкторе: план собран из public.workflows (playbook, write_recipe, plan_json). */
export interface ConstructorBrief {
  id: string
  title: string
  goal: string
  owner_fio: string
  owner_position: string
  tools: string[]
  steps: string[]
  /** План в markdown, с которым его исполнит конфигурация 2. */
  plan: string
}

/** Человек со страницы входа оркестратора. id пустой, пока он ни разу не входил. */
export interface PublishUser {
  id: string
  fio: string
  position: string
  department: string
}

/** Агент платформы из turbotest.agents. */
export interface StoredAgent {
  id: string
  title: string
  config_id: string
  config_title: string
}

export interface StoredAgentsResponse {
  items: StoredAgent[]
  shared?: { enabled: boolean; source: string; error: string }
}

export interface SessionAttachment {
  name: string
  /** Относительно папки сессии: attachments/… */
  path: string
  mime: string
  size: number
  image: boolean
}

export interface AttachmentUpload {
  name: string
  mime: string
  /** Содержимое файла в base64 без префикса data: */
  data: string
}

export interface PlatformConfigs {
  items: PlatformConfig[]
  root: string
}

export type SessionStatus = 'running' | 'finished' | 'error' | 'cancelled'

export interface PlatformSession {
  id: string
  config_id: string
  config_title: string
  source: 'custom' | 'constructor'
  agent_id: string
  agent_title: string
  prompt: string
  status: SessionStatus
  error: string
  sdk_agent_id: string
  turns: number
  plan_turn: number
  plan: string
  rev: number
  created_at: string
  updated_at: string
  /** Кто и на каком компьютере запускал; local — запуск с этого устройства. */
  author?: string
  author_host?: string
  local?: boolean
  /** Тестовый запуск инструмента: сессия живёт только в памяти сервера. */
  ephemeral?: boolean
  test_tool?: string
}

export interface PlatformSessionsResponse {
  items: PlatformSession[]
  host?: string
  /** Общая база истории недоступна — показаны только запуски этого устройства. */
  history_error?: string
}

export interface SessionEvent {
  seq: number
  rev: number
  turn: number
  type: 'user' | 'status' | 'thinking' | 'assistant' | 'tool' | 'plan' | 'error' | 'approval'
  text: string
  name: string
  status: string
  call_id: string
  args: string
  result: string
  attachments?: SessionAttachment[]
  label?: string
  /** call_id вызова task: шаг подагента, а не основного агента. */
  parent?: string
}

export interface AgentQuestionItem {
  id: string
  prompt: string
  /** cells — ячейки строки под заголовками columns (ask_choice с колонками). */
  options: { id: string; label: string; cells?: string[] }[]
  allow_multiple: boolean
  /** radio / checkbox — выбор из списка (ask_choice) без своего ответа; пусто — обычный вопрос ask_user. */
  choice?: '' | 'radio' | 'checkbox'
  columns?: string[]
}

/** Вопрос агента (MCP ask_user / ask_choice), который ждёт ответа на экране сессии. */
export interface AgentQuestion {
  id: string
  title: string
  questions: AgentQuestionItem[]
  asked_at: string
}

export type ApprovalKind = 'shell' | 'write' | 'delete' | 'mcp'

/** Действие агента, которое ждёт разрешения человека (хук preToolUse). */
export interface AgentApproval {
  id: string
  kind: ApprovalKind
  tool: string
  title: string
  subject: string
  preview: string
  remember_label: string
  asked_at: string
}

export interface PlatformSessionDetail {
  session: PlatformSession
  events: SessionEvent[]
  /** Запуск другого компьютера из общей базы: только просмотр. */
  remote?: { author: string; host: string }
  question?: AgentQuestion | null
  approval?: AgentApproval | null
}

export interface TraceEntry {
  seq: number
  rev: number
  at: string
  turn: number
  dir: string
  kind: string
  text: string
  data: string
  count: number
}

export interface TraceChunk {
  rev: number
  entries: TraceEntry[]
}

export interface MetricSample {
  t: number
  turn: number
  cpu: number
  ram: number
  ram_mb: number
  gpu: number | null
  /** Чтение и запись процессов агента, МБ/с. */
  disk: number
  disk_read: number
  disk_write: number
  processes: number
  /** Скорость генерации модели, токенов/с (оценка по символам потока). Нет у старых запусков. */
  gen?: number | null
}

export interface AgentProcess {
  pid: number
  name: string
  cpu: number
  ram_mb: number
  gpu: number | null
  /** Чтение и запись процесса, МБ/с. */
  disk: number
}

export interface SpikeMark {
  metric: 'cpu' | 'ram' | 'gpu' | 'disk'
  value: number
  baseline: number
}

export interface SpikeEvent {
  t: number
  turn: number
  marks: SpikeMark[]
  processes: AgentProcess[]
}

export interface MetricsChunk {
  samples: MetricSample[]
  processes: AgentProcess[]
  spikes: SpikeEvent[]
  cpu_count: number
  ram_total_mb: number
  gpu_available: boolean
  /** Точное число выходных токенов по ходам (номер хода → токены) из итога SDK. */
  output_tokens?: Record<string, number>
}

export type ContextItemType = 'tools' | 'user' | 'thinking' | 'assistant' | 'tool_call' | 'tool_result' | 'other'

export interface ContextItem {
  id: string
  turn: number
  type: ContextItemType
  label: string
  chars: number
  text: string
}

export interface TokenUsage {
  inputTokens?: number
  outputTokens?: number
  cacheReadTokens?: number
  cacheWriteTokens?: number
  totalTokens?: number
  reasoningTokens?: number
}

export interface ContextSnapshot {
  seq: number
  at: string
  turn: number
  reason: string
  /** Тип шага, после которого снят снимок; пусто у старых запусков. */
  kind: ContextItemType | ''
  items: [string, number][]
  usage: TokenUsage | null
}

export interface SessionContext {
  items: Record<string, ContextItem>
  snapshots: ContextSnapshot[]
}

export interface ListResponse<T> {
  items: T[]
}
