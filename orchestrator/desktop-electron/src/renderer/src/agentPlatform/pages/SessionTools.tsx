import { useState, type ReactNode } from 'react'
import type { SessionEvent } from '../api/types'
import {
  BotIcon,
  CheckIcon,
  ChecklistIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  ClockIcon,
  FileIcon,
  FolderIcon,
  GlobeIcon,
  ImageIcon,
  PlugIcon,
  QuestionIcon,
  SearchIcon,
  SparklesIcon,
  TerminalIcon,
  TrashIcon,
  WrenchIcon
} from '../components/Icons'
type Json = Record<string, unknown>
export type ToolState = 'running' | 'done' | 'error' | 'stopped'

interface ToolData {
  args: Json
  value: Json
  error: string
  state: ToolState
}

const OWN_CARDS = new Set(['edit', 'write', 'delete', 'shell', 'updateTodos', 'task', 'askQuestion', 'generateImage'])

export function isExploreTool(name: string): boolean {
  return !OWN_CARDS.has(name)
}

// Вопрос человеку агент задаёт MCP-инструментом платформы: встроенный askQuestion локальный SDK отклоняет.
const ASK_USER = 'ask_user'
const WAIT_ANSWER = 'wait_answer'
const ASK_CHOICE = 'ask_choice'
const ASK_TOOLS = [ASK_USER, ASK_CHOICE]
const MAX_ASK_OPTIONS = 8

function mcpToolName(event: SessionEvent): string {
  return event.name === 'mcp' ? str(asObject(parseJson(event.args)).toolName) : ''
}

export function isExploreEvent(event: SessionEvent): boolean {
  return !ASK_TOOLS.includes(mcpToolName(event)) && isExploreTool(event.name)
}

export function isQuestionEvent(event: SessionEvent): boolean {
  return event.name === 'askQuestion' || ASK_TOOLS.includes(mcpToolName(event))
}

/** Повторные ожидания ответа: в ленте их заменяет сам вопрос и ответ человека. */
export function isHiddenTool(event: SessionEvent): boolean {
  return mcpToolName(event) === WAIT_ANSWER
}

function parseJson(text: string): unknown {
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

function asObject(value: unknown): Json {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Json) : {}
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function str(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function mcpText(value: Json): string {
  return asArray(value.content)
    .map((item) => {
      const text = asObject(item).text
      return typeof text === 'string' ? text : str(asObject(text).text)
    })
    .filter(Boolean)
    .join('\n')
}

function readTool(event: SessionEvent, active: boolean): ToolData {
  const args = asObject(parseJson(event.args))
  const result = asObject(parseJson(event.result))
  const value = result.status === 'success' ? asObject(result.value) : {}
  let error = ''
  if (result.status === 'error') error = str(asObject(result.error).message) || str(result.error) || 'Ошибка'
  else if (event.status === 'error') error = event.result || 'Ошибка'
  else if (value.isError === true) error = mcpText(value) || 'Инструмент вернул ошибку'
  let state: ToolState = error ? 'error' : event.status === 'completed' ? 'done' : 'running'
  if (state === 'running' && !active) state = 'stopped'
  return { args, value, error, state }
}

function baseName(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean)
  return parts[parts.length - 1] || path
}

const SESSION_WORKSPACE = /[\\/]workspaces[\\/][0-9a-f-]{36}(?=[\\/]|$)/i

function parentDir(path: string): string {
  const workspace = SESSION_WORKSPACE.exec(path)
  const inner = workspace ? path.slice(workspace.index + workspace[0].length) : path
  const parts = inner.split(/[\\/]/).filter(Boolean)
  return parts.slice(workspace ? 0 : Math.max(0, parts.length - 3), -1).join('/')
}

function relativeTo(path: string, root: string): string {
  const clean = (value: string): string => value.replaceAll('\\', '/').replace(/\/+$/, '')
  const full = clean(path)
  const base = clean(root)
  const relative = base && full.toLowerCase().startsWith(`${base.toLowerCase()}/`) ? full.slice(base.length + 1) : full
  return relative.replace(/^\.\//, '')
}

function plural(count: number, one: string, few: string, many: string): string {
  const mod10 = count % 10
  const mod100 = count % 100
  if (mod10 === 1 && mod100 !== 11) return one
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few
  return many
}

function counted(count: number, one: string, few: string, many: string): string {
  return `${count} ${plural(count, one, few, many)}`
}

function pretty(value: unknown): string {
  if (typeof value === 'string') {
    const parsed = parseJson(value)
    return parsed && typeof parsed === 'object' ? JSON.stringify(parsed, null, 2) : value
  }
  return JSON.stringify(value, null, 2)
}

function genericOutput(value: Json): string {
  const text = mcpText(value)
  if (text) return pretty(text)
  return Object.keys(value).length ? pretty(value) : ''
}

function seconds(ms: number | null): string {
  if (ms === null) return ''
  return ms < 1000 ? `${Math.round(ms)} мс` : `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} с`
}

function StateMark({ state }: { state: ToolState }): React.JSX.Element | null {
  if (state === 'done') return null
  return <span className={`tool-state ${state}`} aria-label={state === 'running' ? 'выполняется' : state} />
}

function ErrorText({ text }: { text: string }): React.JSX.Element | null {
  return text ? <p className="tool-error">{text}</p> : null
}

/* ---------- Исследование: чтение, поиск, веб, MCP ---------- */

type ExploreKind = 'file' | 'search' | 'dir' | 'web' | 'call'

interface ExploreRowInfo {
  icon: ReactNode
  kind: ExploreKind
  label: string
  target: string
  meta: string
  body: ReactNode
}

function Pre({ text }: { text: string }): React.JSX.Element | null {
  return text ? <pre className="tool-pre">{text}</pre> : null
}

function PathList({ paths }: { paths: string[] }): React.JSX.Element | null {
  if (!paths.length) return null
  return (
    <ul className="tool-paths">
      {paths.map((path, index) => (
        <li key={`${index}:${path}`} title={path}>
          <FileIcon size={13} />
          <span>{path}</span>
        </li>
      ))}
    </ul>
  )
}

function grepBody(value: Json, root: string): { body: ReactNode; meta: string } {
  const results = Object.values(asObject(value.workspaceResults)).map(asObject)
  const active = asObject(value.activeEditorResult)
  if (Object.keys(active).length) results.push(active)
  const matches: { file: string; line: number | null; text: string }[] = []
  const files: string[] = []
  let total = 0
  for (const result of results) {
    const output = asObject(result.output)
    if (result.type === 'content') {
      total += num(output.totalMatches) ?? 0
      for (const raw of asArray(output.matches)) {
        const match = asObject(raw)
        matches.push({ file: relativeTo(str(match.file), root), line: num(match.lineNumber), text: str(match.line) })
      }
    } else if (result.type === 'files') {
      total += num(output.count) ?? 0
      files.push(...asArray(output.files).map((file) => relativeTo(str(file), root)))
    } else if (result.type === 'count') {
      total += num(output.total) ?? 0
      for (const raw of asArray(output.counts)) {
        const item = asObject(raw)
        files.push(`${relativeTo(str(item.file), root)} — ${num(item.count) ?? 0}`)
      }
    }
  }
  const found = Math.max(total, matches.length, files.length)
  const meta = found ? counted(found, 'совпадение', 'совпадения', 'совпадений') : 'нет совпадений'
  if (matches.some((match) => match.text || match.line !== null)) {
    return {
      meta,
      body: (
        <ul className="tool-matches">
          {matches.map((match, index) => (
            <li key={index}>
              <span className="tool-match-file">
                {match.file}
                {match.line !== null ? `:${match.line}` : ''}
              </span>
              <code>{match.text}</code>
            </li>
          ))}
        </ul>
      )
    }
  }
  return { meta, body: <PathList paths={[...matches.map((match) => match.file), ...files]} /> }
}

function TreeNode({ node, depth }: { node: Json; depth: number }): React.JSX.Element {
  const dirs = asArray(node.childrenDirs).map(asObject)
  const files = asArray(node.childrenFiles).map(asObject)
  return (
    <>
      {dirs.map((dir, index) => (
        <li key={`d${index}`}>
          <span style={{ paddingLeft: depth * 14 }}>
            <FolderIcon size={13} />
            {baseName(str(dir.absPath))}
          </span>
          {depth < 3 ? (
            <ul>
              <TreeNode node={dir} depth={depth + 1} />
            </ul>
          ) : null}
        </li>
      ))}
      {files.map((file, index) => (
        <li key={`f${index}`}>
          <span style={{ paddingLeft: depth * 14 }}>
            <FileIcon size={13} />
            {str(file.name)}
          </span>
        </li>
      ))}
    </>
  )
}

function lintBody(value: Json): ReactNode {
  const files = asArray(value.fileDiagnostics).map(asObject)
  const rows = files.flatMap((file) =>
    asArray(file.diagnostics).map((raw) => ({ file: baseName(str(file.path)), item: asObject(raw) }))
  )
  if (!rows.length) return <p className="tool-empty">Ошибок нет</p>
  return (
    <ul className="tool-matches">
      {rows.map(({ file, item }, index) => {
        const line = num(asObject(asObject(item.range).start).line)
        return (
          <li key={index} className={`lint-${str(item.severity)}`}>
            <span className="tool-match-file">
              {file}
              {line !== null ? `:${line}` : ''}
            </span>
            <code>{str(item.message)}</code>
          </li>
        )
      })}
    </ul>
  )
}

function exploreInfo(event: SessionEvent, data: ToolData): ExploreRowInfo {
  const { args, value } = data
  switch (event.name) {
    case 'read': {
      const path = str(args.path)
      const lines = num(value.totalLines)
      return {
        icon: <FileIcon size={14} />,
        kind: 'file',
        label: 'Чтение',
        target: baseName(path),
        meta: lines !== null ? counted(lines, 'строка', 'строки', 'строк') : '',
        body: <Pre text={str(value.content)} />
      }
    }
    case 'grep': {
      const { body, meta } = grepBody(value, str(args.path))
      return {
        icon: <SearchIcon size={14} />,
        kind: 'search',
        label: 'Поиск',
        target: str(args.pattern),
        meta: data.state === 'done' ? meta : '',
        body
      }
    }
    case 'glob': {
      const root = str(args.targetDirectory)
      const files = asArray(value.files).map((file) => relativeTo(str(file), root))
      const total = num(value.totalFiles)
      return {
        icon: <SearchIcon size={14} />,
        kind: 'search',
        label: 'Файлы',
        target: str(args.globPattern),
        meta: total !== null ? counted(total, 'файл', 'файла', 'файлов') : '',
        body: total === 0 ? <p className="tool-empty">Ничего не найдено</p> : <PathList paths={files} />
      }
    }
    case 'ls': {
      const tree = asObject(value.directoryTreeRoot)
      const total = num(tree.numFiles)
      return {
        icon: <FolderIcon size={14} />,
        kind: 'dir',
        label: 'Каталог',
        target: baseName(str(args.path)),
        meta: total !== null ? counted(total, 'файл', 'файла', 'файлов') : '',
        body: Object.keys(tree).length ? (
          <ul className="tool-tree">
            <TreeNode node={tree} depth={0} />
          </ul>
        ) : null
      }
    }
    case 'semSearch':
      return {
        icon: <SparklesIcon size={14} />,
        kind: 'search',
        label: 'Поиск по смыслу',
        target: str(args.query),
        meta: '',
        body: <Pre text={str(value.results)} />
      }
    case 'webSearch':
      return {
        icon: <GlobeIcon size={14} />,
        kind: 'web',
        label: 'Веб-поиск',
        target: str(args.searchTerm) || str(args.search_term),
        meta: '',
        body: <Pre text={genericOutput(value)} />
      }
    case 'webFetch':
      return {
        icon: <GlobeIcon size={14} />,
        kind: 'web',
        label: 'Страница',
        target: str(args.url),
        meta: '',
        body: <Pre text={genericOutput(value)} />
      }
    case 'readLints': {
      const paths = asArray(args.paths).map((path) => baseName(str(path)))
      const total = num(value.totalDiagnostics)
      return {
        icon: <WrenchIcon size={14} />,
        kind: 'search',
        label: 'Линтер',
        target: paths.join(', ') || 'все файлы',
        meta: total !== null ? (total ? counted(total, 'замечание', 'замечания', 'замечаний') : 'чисто') : '',
        body: data.state === 'done' ? lintBody(value) : null
      }
    }
    case 'mcp': {
      const tool = str(args.toolName).replaceAll('__', '.') || 'инструмент'
      const input = asObject(args.args)
      return {
        icon: <PlugIcon size={14} />,
        kind: 'call',
        label: tool,
        // Инструменты mcp_server.py раннер отдаёт агенту как customTools SDK.
        target: str(args.providerIdentifier).replace('custom-user-tools', 'TurboTester'),
        meta: '',
        body: (
          <>
            {Object.keys(input).length ? (
              <>
                <span className="tool-caption">Вход</span>
                <Pre text={pretty(input)} />
              </>
            ) : null}
            {data.state === 'done' ? (
              <>
                <span className="tool-caption">Ответ</span>
                <Pre text={genericOutput(value) || '(пусто)'} />
              </>
            ) : null}
          </>
        )
      }
    }
    default: {
      const hint = ['path', 'query', 'pattern', 'taskId', 'url', 'description']
        .map((key) => str(args[key]))
        .find(Boolean)
      return {
        icon: <WrenchIcon size={14} />,
        kind: 'call',
        label: event.name || 'инструмент',
        target: hint || '',
        meta: '',
        body: (
          <>
            {Object.keys(args).length ? (
              <>
                <span className="tool-caption">Вход</span>
                <Pre text={pretty(args)} />
              </>
            ) : null}
            {data.state === 'done' ? (
              <>
                <span className="tool-caption">Ответ</span>
                <Pre text={genericOutput(data.value) || pretty(event.result)} />
              </>
            ) : null}
          </>
        )
      }
    }
  }
}

function ExploreRow({ event, active }: { event: SessionEvent; active: boolean }): React.JSX.Element {
  const data = readTool(event, active)
  const info = exploreInfo(event, data)
  const hasBody = Boolean(data.error) || data.state === 'done'
  return (
    <details className={`explore-row ${data.state}`}>
      <summary className={hasBody ? '' : 'static'}>
        <span className="explore-row-icon">{info.icon}</span>
        <span className="explore-row-label">{info.label}</span>
        {info.target ? (
          <span className="explore-row-target" title={info.target}>
            {info.target}
          </span>
        ) : null}
        <span className="tool-end">
          {info.meta ? <span className="explore-row-meta">{info.meta}</span> : null}
          <StateMark state={data.state} />
        </span>
      </summary>
      {hasBody ? (
        <div className="explore-row-body">
          <ErrorText text={data.error} />
          {data.error ? null : info.body}
        </div>
      ) : null}
    </details>
  )
}

function ThinkingRow({ event }: { event: SessionEvent }): React.JSX.Element {
  return (
    <details className="explore-row">
      <summary>
        <span className="explore-row-icon">
          <SparklesIcon size={14} />
        </span>
        <span className="explore-row-label">Размышления</span>
      </summary>
      <div className="explore-row-body">
        <p className="tool-thinking">{event.text}</p>
      </div>
    </details>
  )
}

function exploreSummary(tools: SessionEvent[]): string {
  const counts: Record<ExploreKind, number> = { file: 0, search: 0, dir: 0, web: 0, call: 0 }
  for (const event of tools) {
    const name = event.name
    if (name === 'read') counts.file += 1
    else if (name === 'ls') counts.dir += 1
    else if (name === 'webSearch' || name === 'webFetch') counts.web += 1
    else if (['grep', 'glob', 'semSearch', 'readLints'].includes(name)) counts.search += 1
    else counts.call += 1
  }
  const parts = [
    counts.file ? counted(counts.file, 'файл', 'файла', 'файлов') : '',
    counts.search ? counted(counts.search, 'поиск', 'поиска', 'поисков') : '',
    counts.dir ? counted(counts.dir, 'каталог', 'каталога', 'каталогов') : '',
    counts.web ? counted(counts.web, 'запрос в сеть', 'запроса в сеть', 'запросов в сеть') : '',
    counts.call ? counted(counts.call, 'вызов', 'вызова', 'вызовов') : ''
  ].filter(Boolean)
  return parts.join(', ')
}

export function ExploreGroup({
  items,
  active,
  live
}: {
  items: SessionEvent[]
  active: boolean
  live: boolean
}): React.JSX.Element {
  const tools = items.filter((item) => item.type === 'tool')
  const current = tools[tools.length - 1]
  const working = live && current !== undefined && readTool(current, active).state === 'running'
  const errors = tools.filter((tool) => readTool(tool, active).state === 'error').length
  let headline = `Исследовано: ${exploreSummary(tools)}`
  if (working && current) {
    const info = exploreInfo(current, readTool(current, active))
    headline = `${info.label}${info.target ? ` · ${info.target}` : ''}`
  }
  return (
    <details className={working ? 'explore live' : 'explore'}>
      <summary>
        <span className="explore-title">{headline}</span>
        {errors ? <span className="explore-errors">{counted(errors, 'ошибка', 'ошибки', 'ошибок')}</span> : null}
        <ChevronDownIcon size={14} />
      </summary>
      <div className="explore-list">
        {items.map((item) =>
          item.type === 'tool' ? (
            <ExploreRow key={item.seq} event={item} active={active} />
          ) : (
            <ThinkingRow key={item.seq} event={item} />
          )
        )}
      </div>
    </details>
  )
}

/* ---------- Правки файлов ---------- */

interface DiffLine {
  kind: 'add' | 'del' | 'ctx' | 'hunk'
  text: string
  number: number | null
}

function parseDiff(diff: string): DiffLine[] {
  const lines: DiffLine[] = []
  let oldLine = 0
  let newLine = 0
  for (const raw of diff.replace(/\r/g, '').split('\n')) {
    if (/^(diff |index |--- |\+\+\+ )/.test(raw)) continue
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(raw)
    if (hunk) {
      oldLine = Number(hunk[1])
      newLine = Number(hunk[2])
      if (lines.length) lines.push({ kind: 'hunk', text: '⋯', number: null })
      continue
    }
    if (raw.startsWith('+')) lines.push({ kind: 'add', text: raw.slice(1), number: newLine++ || null })
    else if (raw.startsWith('-')) lines.push({ kind: 'del', text: raw.slice(1), number: oldLine++ || null })
    else if (raw.startsWith('\\')) continue
    else {
      oldLine += 1
      lines.push({ kind: 'ctx', text: raw.startsWith(' ') ? raw.slice(1) : raw, number: newLine++ || null })
    }
  }
  while (lines.length && lines[lines.length - 1].kind === 'ctx' && !lines[lines.length - 1].text) lines.pop()
  return lines
}

function DiffView({ lines }: { lines: DiffLine[] }): React.JSX.Element {
  return (
    <div className="diff">
      {lines.map((line, index) => (
        <div key={index} className={`diff-line ${line.kind}`}>
          <span className="diff-num">{line.number ?? ''}</span>
          <span className="diff-sign">{line.kind === 'add' ? '+' : line.kind === 'del' ? '−' : ''}</span>
          <span className="diff-text">{line.text || ' '}</span>
        </div>
      ))}
    </div>
  )
}

function FileChangeCard({ event, active }: { event: SessionEvent; active: boolean }): React.JSX.Element {
  const data = readTool(event, active)
  const { args, value, state } = data
  const path = str(args.path) || str(value.path)
  const deleted = event.name === 'delete'
  let lines: DiffLine[] = []
  let added = num(value.linesAdded)
  let removed = num(value.linesRemoved)
  if (event.name === 'write') {
    const text = str(args.fileText)
    lines = text
      ? text
          .replace(/\r/g, '')
          .split('\n')
          .map((line, index) => ({ kind: 'add' as const, text: line, number: index + 1 }))
      : []
    added = num(value.linesCreated) ?? (lines.length || null)
    removed = null
  } else if (!deleted) {
    lines = parseDiff(str(value.diffString))
    if (added === null && lines.length) added = lines.filter((line) => line.kind === 'add').length
    if (removed === null && lines.length) removed = lines.filter((line) => line.kind === 'del').length
  }
  const [open, setOpen] = useState(true)
  const expandable = !deleted && (lines.length > 0 || Boolean(data.error))
  const verb = state === 'running' ? (deleted ? 'Удаляет' : event.name === 'write' ? 'Создаёт' : 'Правит') : ''
  return (
    <div className={`file-card ${state}${deleted ? ' deleted' : ''}`}>
      <button
        type="button"
        className="file-card-head"
        onClick={() => expandable && setOpen((value) => !value)}
        aria-expanded={expandable ? open : undefined}
      >
        <span className="file-card-icon">{deleted ? <TrashIcon size={14} /> : <FileIcon size={14} />}</span>
        {verb ? <span className="file-card-verb">{verb}</span> : null}
        <span className="file-card-name" title={path}>
          {baseName(path) || 'файл'}
        </span>
        {parentDir(path) ? <span className="file-card-dir">{parentDir(path)}</span> : null}
        <span className="tool-end">
          <span className="file-card-stats">
            {deleted && state === 'done' ? <span className="del">удалён</span> : null}
            {added ? <span className="add">+{added}</span> : null}
            {removed ? <span className="del">−{removed}</span> : null}
          </span>
          <StateMark state={state} />
        </span>
        {expandable ? <ChevronDownIcon size={14} /> : null}
      </button>
      {expandable && open ? (
        <div className="file-card-body">
          <ErrorText text={data.error} />
          {lines.length ? <DiffView lines={lines} /> : null}
        </div>
      ) : null}
      {!expandable && data.error ? <ErrorText text={data.error} /> : null}
    </div>
  )
}

/* ---------- Терминал ---------- */

function TerminalCard({ event, active }: { event: SessionEvent; active: boolean }): React.JSX.Element {
  const data = readTool(event, active)
  const { args, value, state } = data
  const command = str(args.command)
  const exitCode = num(value.exitCode)
  const stdout = str(value.stdout).replace(/\s+$/, '')
  const stderr = str(value.stderr).replace(/\s+$/, '')
  const failed = state === 'error' || (exitCode !== null && exitCode !== 0)
  const [open, setOpen] = useState(true)
  return (
    <div className={`term-card ${state}${failed ? ' failed' : ''}`}>
      <button type="button" className="term-head" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        <TerminalIcon size={14} />
        <span className="term-title" title={str(args.workingDirectory) || undefined}>
          {state === 'running' ? 'Выполняет команду' : 'Терминал'}
        </span>
        <span className="tool-end term-meta">
          {exitCode !== null && exitCode !== 0 ? <span className="term-exit">код {exitCode}</span> : null}
          {state === 'done' && num(value.executionTime) !== null ? seconds(num(value.executionTime)) : null}
          <StateMark state={state} />
        </span>
        <ChevronDownIcon size={14} />
      </button>
      {open ? (
        <div className="term-body">
          <div className="term-command">
            <span className="term-prompt">$</span>
            <span>{command}</span>
          </div>
          {stdout ? <pre className="term-out">{stdout}</pre> : null}
          {stderr ? <pre className="term-out err">{stderr}</pre> : null}
          {state === 'done' && !stdout && !stderr ? <p className="term-empty">Команда ничего не вывела</p> : null}
          {data.error ? <pre className="term-out err">{data.error}</pre> : null}
        </div>
      ) : null}
    </div>
  )
}

/* ---------- Список дел ---------- */

function TodosCard({ event, active }: { event: SessionEvent; active: boolean }): React.JSX.Element {
  const data = readTool(event, active)
  const source = asArray(data.value.todos).length ? data.value.todos : data.args.todos
  const todos = asArray(source).map(asObject)
  const doneCount = todos.filter((todo) => todo.status === 'completed').length
  return (
    <div className="todo-card">
      <div className="todo-head">
        <ChecklistIcon size={14} />
        <span>Список дел</span>
        <span className="todo-progress">
          {doneCount} из {todos.length}
        </span>
      </div>
      <ul className="todo-list">
        {todos.map((todo, index) => {
          const status = str(todo.status) || 'pending'
          return (
            <li key={str(todo.id) || index} className={`todo ${status}`}>
              <span className="todo-mark">{status === 'completed' ? <CheckIcon size={11} /> : null}</span>
              <span className="todo-text">{str(todo.content)}</span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/* ---------- Подагент ---------- */

export interface SubagentInfo {
  state: ToolState
  description: string
  prompt: string
  type: string
  model: string
  error: string
  durationMs: number | null
}

export function readSubagent(event: SessionEvent, active: boolean): SubagentInfo {
  const data = readTool(event, active)
  const { args, value } = data
  const kind = asObject(args.subagentType)
  return {
    state: data.state,
    description: str(args.description),
    prompt: str(args.prompt),
    type: str(kind.name) || (str(kind.kind) && str(kind.kind) !== 'unspecified' ? str(kind.kind) : ''),
    model: str(args.model),
    error: data.error,
    durationMs: num(value.durationMs)
  }
}

export function SubagentMeta({ info }: { info: SubagentInfo }): React.JSX.Element {
  return (
    <span className="tool-end">
      {info.type ? <span className="agent-card-tag">{info.type}</span> : null}
      {info.state === 'done' && info.durationMs !== null ? (
        <span className="agent-card-time">
          <ClockIcon size={12} />
          {seconds(info.durationMs)}
        </span>
      ) : null}
      <StateMark state={info.state} />
    </span>
  )
}

export interface SubagentLink {
  open: string | null
  onOpen: (callId: string) => void
}

function SubagentCard({
  event,
  active,
  link
}: {
  event: SessionEvent
  active: boolean
  link?: SubagentLink
}): React.JSX.Element {
  const info = readSubagent(event, active)
  const label = <span className="agent-card-label">{info.state === 'running' ? 'Подагент работает' : 'Подагент'}</span>
  if (link && event.call_id) {
    const selected = link.open === event.call_id
    return (
      <button
        type="button"
        className={`agent-card agent-card-link ${info.state}${selected ? ' selected' : ''}`}
        aria-pressed={selected}
        title={selected ? 'Вернуться к производительности' : 'Открыть ход подагента справа'}
        onClick={() => link.onOpen(event.call_id)}
      >
        <BotIcon size={14} />
        {label}
        <span className="agent-card-desc">{info.description}</span>
        <SubagentMeta info={info} />
        <ChevronRightIcon size={14} />
      </button>
    )
  }
  return (
    <details className={`agent-card ${info.state}`}>
      <summary>
        <BotIcon size={14} />
        {label}
        <span className="agent-card-desc">{info.description}</span>
        <SubagentMeta info={info} />
        <ChevronDownIcon size={14} />
      </summary>
      <div className="agent-card-body">
        <span className="tool-caption">Задание</span>
        <p className="agent-card-prompt">{info.prompt}</p>
        {info.model ? <span className="tool-caption">Модель: {info.model}</span> : null}
        <ErrorText text={info.error} />
      </div>
    </details>
  )
}

/* ---------- Вопрос человеку ---------- */

/** Вопрос ask_user / ask_choice, на который агент ещё ждёт ответа: его задаёт форма вместо поля ввода. */
export function isWaitingQuestion(event: SessionEvent): boolean {
  return (
    event.type === 'tool' &&
    !event.parent &&
    ASK_TOOLS.includes(mcpToolName(event)) &&
    event.status !== 'completed' &&
    event.status !== 'error'
  )
}

function askOptions(question: Json): string[] {
  const rows = asArray(question.rows)
  if (rows.length) return rows.map((row) => asArray(row).map(str).filter(Boolean).join(' | '))
  return asArray(question.options).map((raw) => str(asObject(raw).label) || str(raw))
}

function AskAnswer({ answer }: { answer: Json | undefined }): React.JSX.Element {
  const selected = asArray(answer?.selected).map(str).filter(Boolean)
  const text = str(answer?.text)
  return (
    <div className="ask-answer">
      <span className="ask-answer-label">Ваш ответ</span>
      {selected.length || text ? (
        <div className="ask-options">
          {selected.map((label) => (
            <span key={label} className="ask-option chosen">
              <CheckIcon size={12} />
              {label}
            </span>
          ))}
          {text ? <span className="ask-answer-text">{text}</span> : null}
        </div>
      ) : (
        <span className="ask-answer-empty">ничего не выбрано</span>
      )}
    </div>
  )
}

// viaMcp — вопрос через ask_user / ask_choice: ответ человека приходит агенту результатом инструмента.
// Пока агент ждёт, вопрос задаёт форма вместо поля ввода, поэтому в ленте карточки нет.
function QuestionCard({
  event,
  active,
  viaMcp = false
}: {
  event: SessionEvent
  active: boolean
  viaMcp?: boolean
}): React.JSX.Element | null {
  const data = readTool(event, active)
  if (viaMcp && data.state === 'running') return null
  const input = viaMcp ? asObject(data.args.args) : data.args
  // ask_choice передаёт один вопрос плоско: question, options (строки) или columns + rows, type.
  const questions = input.question ? [input] : asArray(input.questions).map(asObject)
  const reply = viaMcp && data.state === 'done' ? asObject(parseJson(mcpText(data.value))) : {}
  const answers = asArray(reply.answers).map(asObject)
  const answered = reply.status === 'answered'
  const skipped = reply.status === 'skipped'
  const answer = !viaMcp && data.state === 'done' ? genericOutput(data.value) : ''
  const note = answered ? 'Отвечено' : skipped ? 'Пропущено' : viaMcp && data.state !== 'error' ? 'Без ответа' : ''
  return (
    <div className={`ask-card ${data.state}${answered ? ' answered' : ''}`}>
      <div className="ask-head">
        <QuestionIcon size={14} />
        <span>{str(input.title) || 'Вопрос к вам'}</span>
        <span className="tool-end">
          {note ? <span className="ask-note">{note}</span> : <StateMark state={data.state} />}
        </span>
      </div>
      {questions.map((question, index) => {
        const prompt = str(question.prompt) || str(question.question)
        const options = askOptions(question)
        return (
          <div key={str(question.id) || index} className="ask-question">
            <p>{prompt}</p>
            {answered ? (
              <AskAnswer answer={answers.find((item) => str(item.question) === prompt) ?? answers[index]} />
            ) : skipped ? null : (
              <div className="ask-options">
                {options.slice(0, MAX_ASK_OPTIONS).map((label, optionIndex) => (
                  <span key={optionIndex} className="ask-option">
                    {label}
                  </span>
                ))}
                {options.length > MAX_ASK_OPTIONS ? (
                  <span className="ask-option">ещё {options.length - MAX_ASK_OPTIONS}</span>
                ) : null}
              </div>
            )}
          </div>
        )
      })}
      {skipped ? <p className="ask-skipped">Вы пропустили вопрос — агент решает сам.</p> : null}
      {answer ? (
        <>
          <span className="tool-caption">Ответ</span>
          <Pre text={answer} />
        </>
      ) : null}
      <ErrorText text={data.error} />
    </div>
  )
}

/* ---------- Изображение ---------- */

function ImageCard({ event, active }: { event: SessionEvent; active: boolean }): React.JSX.Element {
  const data = readTool(event, active)
  const image = str(data.value.imageData)
  const path = str(data.value.filePath) || str(data.args.filePath)
  const complete = image && !image.endsWith('…')
  return (
    <div className={`image-card ${data.state}`}>
      <div className="image-head">
        <ImageIcon size={14} />
        <span className="image-title">{data.state === 'running' ? 'Рисует изображение' : 'Изображение'}</span>
        {path ? (
          <span className="image-path" title={path}>
            {baseName(path)}
          </span>
        ) : null}
        <span className="tool-end">
          <StateMark state={data.state} />
        </span>
      </div>
      {complete ? (
        <img src={image.startsWith('data:') ? image : `data:image/png;base64,${image}`} alt={str(data.args.description)} />
      ) : data.state === 'running' ? (
        <div className="image-placeholder">{str(data.args.description)}</div>
      ) : null}
      <ErrorText text={data.error} />
    </div>
  )
}

export function ToolCard({
  event,
  active,
  subagents
}: {
  event: SessionEvent
  active: boolean
  subagents?: SubagentLink
}): React.JSX.Element | null {
  switch (event.name) {
    case 'edit':
    case 'write':
    case 'delete':
      return <FileChangeCard event={event} active={active} />
    case 'shell':
      return <TerminalCard event={event} active={active} />
    case 'updateTodos':
      return <TodosCard event={event} active={active} />
    case 'task':
      return <SubagentCard event={event} active={active} link={subagents} />
    case 'askQuestion':
      return <QuestionCard event={event} active={active} />
    case 'generateImage':
      return <ImageCard event={event} active={active} />
    case 'mcp':
      if (ASK_TOOLS.includes(mcpToolName(event))) return <QuestionCard event={event} active={active} viaMcp />
      return <ExploreGroup items={[event]} active={active} live={false} />
    default:
      return <ExploreGroup items={[event]} active={active} live={false} />
  }
}
