import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import type { WorkflowFileItem } from '../api/types'
import { fileTypeIconSrc } from '../utils/fileTypeIcon'
import {
  elideFilenameMiddle,
  fileExt,
  formatFileWhen,
  formatSize,
  normalizeAgentTitle,
  parseFileDate,
  sessionKind,
  uniqueAgentOptions
} from './filesGrouping'

const PAGE_SIZE = 20
const FAVORITES_KEY = 'constructor.files.favorites'

type TabKey = 'all' | 'mine' | 'agent' | 'fav'
type PeriodKey = 'all' | 'week' | 'month'
type SortKey = 'new' | 'old' | 'name' | 'size'
type ViewMode = 'list' | 'grid'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'all', label: 'Все файлы' },
  { key: 'mine', label: 'Мои файлы' },
  { key: 'agent', label: 'Создано агентами' },
  { key: 'fav', label: 'Избранное' }
]

function loadFavorites(): Set<string> {
  try {
    const raw = JSON.parse(localStorage.getItem(FAVORITES_KEY) || '[]')
    return new Set(Array.isArray(raw) ? raw.map(String) : [])
  } catch {
    return new Set()
  }
}

function saveFavorites(ids: Set<string>): void {
  localStorage.setItem(FAVORITES_KEY, JSON.stringify([...ids]))
}

function typeLabel(name: string): string {
  const ext = fileExt(name).toUpperCase()
  return ext || 'FILE'
}

function inPeriod(item: WorkflowFileItem, period: PeriodKey, now: Date): boolean {
  if (period === 'all') return true
  const stamp = parseFileDate(item.createdAt)
  if (!stamp) return period === 'week'
  const days = period === 'week' ? 7 : 31
  return now.getTime() - stamp.getTime() <= days * 24 * 60 * 60 * 1000
}

function FileIcon({ name }: { name: string }): React.JSX.Element {
  return <img className="files-type-icon" src={fileTypeIconSrc(name)} alt="" />
}

function SourceChip({ item }: { item: WorkflowFileItem }): React.JSX.Element {
  const agent = item.source === 'agent'
  return (
    <span className={`files-chip ${agent ? 'agent' : 'user'}`}>
      <span className="files-chip-dot" />
      {agent ? 'Создан агентом' : 'Загружен вами'}
    </span>
  )
}

function FilesSelect({
  value,
  options,
  onChange,
  wide = false
}: {
  value: string
  options: { value: string; label: string }[]
  onChange: (value: string) => void
  wide?: boolean
}): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const current = options.find((item) => item.value === value)?.label || options[0]?.label || ''

  useEffect(() => {
    function onDoc(event: MouseEvent): void {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  return (
    <div className={`files-select ${wide ? 'wide' : ''} ${open ? 'open' : ''}`} ref={ref}>
      <button type="button" className="files-select-btn" onClick={() => setOpen((value) => !value)}>
        <span>{current}</span>
        <i />
      </button>
      {open && (
        <div className="files-select-menu">
          {options.map((item) => (
            <button
              key={item.value}
              type="button"
              className={item.value === value ? 'active' : ''}
              onClick={() => {
                onChange(item.value)
                setOpen(false)
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export function FilesPage({
  ownerName = '',
  initialWorkflowId = '',
  initialAgentTitle = '',
  onOpenRun
}: {
  ownerName?: string
  initialWorkflowId?: string
  initialAgentTitle?: string
  onOpenRun?: (workflowId: string, runId: string) => void
}): React.JSX.Element {
  const [items, setItems] = useState<WorkflowFileItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<TabKey>('all')
  const [query, setQuery] = useState('')
  const [view, setView] = useState<ViewMode>('list')
  const [agent, setAgent] = useState('all')
  const [workflowFilter, setWorkflowFilter] = useState('')
  const [kind, setKind] = useState('all')
  const [period, setPeriod] = useState<PeriodKey>('all')
  const [sort, setSort] = useState<SortKey>('new')
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState('')
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [favorites, setFavorites] = useState<Set<string>>(loadFavorites)
  const [menuId, setMenuId] = useState('')
  const [uploadFor, setUploadFor] = useState('')
  const [pendingPaths, setPendingPaths] = useState<string[]>([])
  const [uploading, setUploading] = useState(false)

  async function reload(): Promise<void> {
    const list = await api.listPlatformFiles()
    setItems(list)
    setSelectedId((current) => current || list[0]?.id || '')
  }

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const list = await api.listPlatformFiles()
        if (!alive) return
        setItems(list)
        setSelectedId(list[0]?.id || '')
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : 'Ошибка загрузки')
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [])

  const agents = useMemo(() => uniqueAgentOptions(items), [items])

  useEffect(() => {
    const wid = (initialWorkflowId || '').trim()
    if (!wid) {
      setWorkflowFilter('')
      return
    }
    setTab('agent')
    setWorkflowFilter(wid)
    if ((initialAgentTitle || '').trim()) {
      const norm = normalizeAgentTitle(initialAgentTitle)
      if (norm) setAgent(norm)
    }
  }, [initialWorkflowId, initialAgentTitle])

  function workflowIdByAgent(key: string): string {
    if (!key) return ''
    return items.find((item) => normalizeAgentTitle(item.agentTitle || '') === key)?.workflowId || ''
  }

  const types = useMemo(() => {
    const set = new Set(items.map((item) => fileExt(item.name)).filter(Boolean))
    return [...set].sort()
  }, [items])

  const filtered = useMemo(() => {
    const now = new Date()
    const needle = query.trim().toLowerCase()
    const rows = items.filter((item) => {
      const mine = item.source !== 'agent'
      if (tab === 'mine' && !mine) return false
      if (tab === 'agent' && mine) return false
      if (tab === 'fav' && !favorites.has(item.id)) return false
      if (workflowFilter && item.workflowId !== workflowFilter) return false
      if (agent !== 'all' && normalizeAgentTitle(item.agentTitle || '') !== agent) return false
      if (kind !== 'all' && fileExt(item.name) !== kind) return false
      if (!inPeriod(item, period, now)) return false
      if (needle) {
        const hay = `${item.name} ${item.agentTitle || ''} ${item.runId || ''}`.toLowerCase()
        if (!hay.includes(needle)) return false
      }
      return true
    })
    rows.sort((a, b) => {
      if (sort === 'name') return (a.name || '').localeCompare(b.name || '', 'ru')
      if (sort === 'size') return (b.sizeBytes || 0) - (a.sizeBytes || 0)
      const aTime = parseFileDate(a.createdAt)?.getTime() ?? 0
      const bTime = parseFileDate(b.createdAt)?.getTime() ?? 0
      return sort === 'old' ? aTime - bTime : bTime - aTime
    })
    return rows
  }, [items, tab, query, agent, kind, period, sort, favorites])

  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const safePage = Math.min(page, pages)
  const pageRows = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE)
  const selected = items.find((item) => item.id === selectedId) || pageRows[0] || null

  const stats = useMemo(() => {
    const mine = items.filter((item) => item.source !== 'agent').length
    const agentCount = items.length - mine
    const bytes = items.reduce((sum, item) => sum + (item.sizeBytes || 0), 0)
    return { total: items.length, mine, agent: agentCount, bytes }
  }, [items])

  useEffect(() => {
    setPage(1)
  }, [tab, query, agent, kind, period, sort])

  function toggleFavorite(id: string): void {
    setFavorites((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      saveFavorites(next)
      return next
    })
  }

  function toggleChecked(id: string): void {
    setChecked((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleAll(): void {
    const ids = pageRows.map((item) => item.id)
    const allOn = ids.every((id) => checked.has(id))
    setChecked((current) => {
      const next = new Set(current)
      for (const id of ids) {
        if (allOn) next.delete(id)
        else next.add(id)
      }
      return next
    })
  }

  async function download(item: WorkflowFileItem): Promise<void> {
    if (!item.downloadUrl) return
    await api.download(item.downloadUrl, item.name)
  }

  async function startUpload(): Promise<void> {
    const paths = await window.api.openFile({
      title: 'Загрузить файл',
      properties: ['openFile', 'multiSelections']
    })
    if (!paths.length) return
    const targetKey = agent !== 'all' ? agent : agents.length === 1 ? agents[0].value : ''
    const target = workflowFilter || workflowIdByAgent(targetKey)
    if (!target) {
      setPendingPaths(paths)
      setUploadFor(agents[0]?.value || '')
      return
    }
    await finishUpload(target, paths)
  }

  async function finishUpload(workflowId: string, paths: string[]): Promise<void> {
    if (!workflowId || !paths.length) return
    setUploading(true)
    setError('')
    try {
      await api.uploadWorkflowFiles(workflowId, paths)
      await reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось загрузить файл')
    } finally {
      setUploading(false)
      setPendingPaths([])
      setUploadFor('')
    }
  }

  function openRun(item: WorkflowFileItem): void {
    if (!item.workflowId) return
    onOpenRun?.(item.workflowId, item.runId || '')
  }

  const from = filtered.length === 0 ? 0 : (safePage - 1) * PAGE_SIZE + 1
  const to = Math.min(filtered.length, safePage * PAGE_SIZE)

  return (
    <div className="files-page">
      <button className="btn-primary files-header-upload" onClick={() => void startUpload()} disabled={uploading}>
        {uploading ? 'Загрузка...' : 'Загрузить файл'}
      </button>

      <div className="files-heading">
        <h1 className="page-title">Файлы</h1>
        <p className="page-subtitle">Все документы, загруженные вами и созданные ИИ-агентами</p>
      </div>
      {workflowFilter ? (
        <div className="files-scope">
          <span>
            Показаны файлы агента: <b>{initialAgentTitle || workflowFilter}</b>
          </span>
          <button
            className="btn-ghost"
            type="button"
            onClick={() => {
              setWorkflowFilter('')
              setAgent('all')
              setTab('all')
            }}
          >
            Показать все файлы
          </button>
        </div>
      ) : null}

      {error && <div className="files-error">{error}</div>}

      <div className="files-stats">
        <article>
          <b>{stats.total}</b>
          <span>файлов</span>
        </article>
        <article>
          <b>{stats.mine}</b>
          <span>загружено вами</span>
        </article>
        <article>
          <b>{stats.agent}</b>
          <span>создано агентами</span>
        </article>
        <article>
          <b>{formatSize(stats.bytes) || '0 Б'}</b>
          <span>занято</span>
        </article>
      </div>

      <div className="files-tabs">
        {TABS.map((item) => (
          <button
            key={item.key}
            className={tab === item.key ? 'active' : ''}
            onClick={() => setTab(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="files-toolbar">
        <input
          className="files-search"
          value={query}
          placeholder="Поиск по названию, агенту или запуску"
          onChange={(event) => setQuery(event.target.value)}
        />
        <div className="files-view-toggle">
          <button className={view === 'list' ? 'active' : ''} onClick={() => setView('list')} title="Список">
            ▤
          </button>
          <button className={view === 'grid' ? 'active' : ''} onClick={() => setView('grid')} title="Сетка">
            ▦
          </button>
        </div>
        <FilesSelect
          wide
          value={agent}
          onChange={setAgent}
          options={[{ value: 'all', label: 'Все агенты' }, ...agents]}
        />
        <FilesSelect
          value={kind}
          onChange={setKind}
          options={[
            { value: 'all', label: 'Все типы' },
            ...types.map((item) => ({ value: item, label: item.toUpperCase() }))
          ]}
        />
        <FilesSelect
          value={period}
          onChange={(value) => setPeriod(value as PeriodKey)}
          options={[
            { value: 'all', label: 'За всё время' },
            { value: 'week', label: 'За неделю' },
            { value: 'month', label: 'За месяц' }
          ]}
        />
        <FilesSelect
          value={sort}
          onChange={(value) => setSort(value as SortKey)}
          options={[
            { value: 'new', label: 'Сначала новые' },
            { value: 'old', label: 'Сначала старые' },
            { value: 'name', label: 'По названию' },
            { value: 'size', label: 'По размеру' }
          ]}
        />
      </div>

      {loading ? (
        <div className="center-state">
          <div className="spinner" />
          <div>Загружаем файлы...</div>
        </div>
      ) : (
        <div className={`files-workspace ${selected ? 'with-panel' : ''}`}>
          <div className="files-main">
            {pageRows.length === 0 ? (
              <div className="placeholder-card">Пока нет файлов</div>
            ) : view === 'grid' ? (
              <div className="files-grid">
                {pageRows.map((item) => (
                  <button
                    key={item.id}
                    className={`files-grid-card ${selected?.id === item.id ? 'selected' : ''}`}
                    onClick={() => setSelectedId(item.id)}
                  >
                    <FileIcon name={item.name} />
                    <b title={item.name || 'file'}>{elideFilenameMiddle(item.name || 'file', 22)}</b>
                    <SourceChip item={item} />
                    <span>{item.agentTitle || 'Агент'}</span>
                  </button>
                ))}
              </div>
            ) : (
              <div className="files-table-wrap">
                <table className="files-table">
                  <thead>
                    <tr>
                      <th className="files-check">
                        <input
                          type="checkbox"
                          checked={pageRows.length > 0 && pageRows.every((item) => checked.has(item.id))}
                          onChange={toggleAll}
                        />
                      </th>
                      <th className="files-col-name">Название</th>
                      <th>Источник</th>
                      <th>Связанный агент</th>
                      <th>Создан</th>
                      <th>Размер</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {pageRows.map((item) => (
                      <tr
                        key={item.id}
                        className={selected?.id === item.id ? 'selected' : ''}
                        onClick={() => setSelectedId(item.id)}
                      >
                        <td className="files-check" onClick={(event) => event.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={checked.has(item.id)}
                            onChange={() => toggleChecked(item.id)}
                          />
                        </td>
                        <td className="files-col-name">
                          <div className="files-name-cell" title={item.name || 'file'}>
                            <FileIcon name={item.name} />
                            <span>{elideFilenameMiddle(item.name || 'file', 22)}</span>
                          </div>
                        </td>
                        <td>
                          <SourceChip item={item} />
                        </td>
                        <td>{item.agentTitle || 'Агент'}</td>
                        <td>{formatFileWhen(item.createdAt)}</td>
                        <td>{formatSize(item.sizeBytes) || '—'}</td>
                        <td className="files-row-actions" onClick={(event) => event.stopPropagation()}>
                          <button
                            className={`files-star ${favorites.has(item.id) ? 'on' : ''}`}
                            title="Избранное"
                            onClick={() => toggleFavorite(item.id)}
                          >
                            ★
                          </button>
                          <button
                            className="files-more"
                            title="Ещё"
                            onClick={() => setMenuId((current) => (current === item.id ? '' : item.id))}
                          >
                            ⋮
                          </button>
                          {menuId === item.id && (
                            <div className="files-menu">
                              <button
                                onClick={() => {
                                  setMenuId('')
                                  void download(item)
                                }}
                              >
                                Скачать
                              </button>
                              {item.workflowId && (
                                <button
                                  onClick={() => {
                                    setMenuId('')
                                    openRun(item)
                                  }}
                                >
                                  Открыть запуск
                                </button>
                              )}
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="files-pager">
              <span>
                {from}–{to} из {filtered.length}
              </span>
              <div>
                <button disabled={safePage <= 1} onClick={() => setPage(safePage - 1)}>
                  ‹
                </button>
                {Array.from({ length: pages }, (_, index) => index + 1)
                  .filter((item) => item === 1 || item === pages || Math.abs(item - safePage) <= 2)
                  .map((item, index, list) => (
                    <span key={item}>
                      {index > 0 && list[index - 1] !== item - 1 && <i>…</i>}
                      <button className={item === safePage ? 'active' : ''} onClick={() => setPage(item)}>
                        {item}
                      </button>
                    </span>
                  ))}
                <button disabled={safePage >= pages} onClick={() => setPage(safePage + 1)}>
                  ›
                </button>
              </div>
            </div>
          </div>

          {selected && (
            <aside className="files-panel">
              <div className="files-panel-head">
                <FileIcon name={selected.name} />
                <div>
                  <b>{selected.name || 'file'}</b>
                  <span>
                    {formatSize(selected.sizeBytes) || '—'} · {typeLabel(selected.name)}
                  </span>
                </div>
              </div>
              <div className="files-panel-preview">
                {selected.summary?.trim() || 'Предпросмотр появится после открытия файла.'}
              </div>
              <button className="btn-primary files-panel-download" onClick={() => void download(selected)}>
                Скачать
              </button>
              <h3>Сведения</h3>
              <dl>
                <div>
                  <dt>Источник</dt>
                  <dd>{selected.source === 'agent' ? 'ИИ-агент' : 'Загружен вами'}</dd>
                </div>
                <div>
                  <dt>Агент</dt>
                  <dd>{selected.agentTitle || 'Агент'}</dd>
                </div>
                <div>
                  <dt>Запуск</dt>
                  <dd>
                    {sessionKind(selected) === 'formation'
                      ? 'Формирование агента'
                      : formatFileWhen(selected.createdAt) || 'Запуск агента'}
                  </dd>
                </div>
                <div>
                  <dt>Владелец</dt>
                  <dd>{ownerName || 'Вы'}</dd>
                </div>
              </dl>
              {selected.workflowId && (
                <button className="files-open-run" onClick={() => openRun(selected)}>
                  Открыть запуск агента →
                </button>
              )}
              <h3>Версии</h3>
              <div className="files-version">
                Текущая версия · {formatFileWhen(selected.createdAt) || 'без даты'}
              </div>
            </aside>
          )}
        </div>
      )}

      {pendingPaths.length > 0 && (
        <div className="files-modal-backdrop" onClick={() => setPendingPaths([])}>
          <div className="files-modal" onClick={(event) => event.stopPropagation()}>
            <h3>К какому агенту прикрепить файл?</h3>
            <FilesSelect
              wide
              value={uploadFor}
              onChange={setUploadFor}
              options={agents}
            />
            <div className="files-modal-actions">
              <button className="btn-ghost" onClick={() => setPendingPaths([])}>
                Отмена
              </button>
              <button
                className="btn-primary"
                onClick={() => void finishUpload(workflowIdByAgent(uploadFor), pendingPaths)}
              >
                Загрузить
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
