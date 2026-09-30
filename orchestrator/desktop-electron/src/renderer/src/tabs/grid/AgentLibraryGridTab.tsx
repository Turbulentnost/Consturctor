import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Plus, RefreshCw, Search } from 'lucide-react'
import type { UserProfile } from '../../api/types'
import { api } from '../../api/client'
import { ApiError } from '../../api/types'
import {
  adoptAgentFromLibrary,
  agentPurposeLabel,
  fetchAgentLibrary,
  getCachedAgentLibrary,
  type AgentLibraryEntry
} from '../../workplace/agentLibraryApi'
import { localizeStatusText } from '../../utils/statusText'
import type { PassportTab } from '../../pages/AgentPassportPage'
import { StandardTabChrome } from './TabChromeGrid'
import { DEFAULT_AGENT_LIBRARY_LAYOUT } from './useTabChromeLayout'
import './agentLibraryGrid.css'
import { usePageSearch } from '../../layout/pageSearchContext'
import { useRegisterGlobalSearch, type GlobalSearchEntry } from '../../layout/globalSearch'

function normSearch(value: string): string {
  return (value || '').trim().toLowerCase().replace(/ё/g, 'е')
}

/** В каталоге библиотеки остаются только агенты Ильченко. */
function isIlchenkoLibraryAgent(entry: AgentLibraryEntry): boolean {
  return /ильченко/i.test(`${entry.ownerFio || ''} ${entry.author || ''}`)
}

function matchesSearch(entry: AgentLibraryEntry, query: string): boolean {
  if (!query) return true
  const blob = normSearch(
    [
      entry.title,
      entry.description,
      entry.goal,
      entry.ownerFio,
      entry.triggerSummary,
      agentPurposeLabel(entry.purpose),
      entry.tools.join(' ')
    ].join(' ')
  )
  return blob.includes(query)
}

function AgentSharePreview({ entry }: { entry: AgentLibraryEntry }): React.JSX.Element {
  return (
    <div className="agent-library-share-preview">
      <span className="messenger-agent-ico">{(entry.title[0] || 'А').toUpperCase()}</span>
      <span>
        <strong>{entry.title}</strong>
        <em>{localizeStatusText(entry.status || entry.phase || '', 'Опубликован')}</em>
      </span>
    </div>
  )
}

function formatCreatedAt(iso?: string): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleDateString('ru-RU')
}

function cardBodyLines(entry: AgentLibraryEntry): string[] {
  const lines: string[] = []
  const desc = entry.description.trim()
  if (desc) lines.push(desc)
  else if (entry.goal.trim()) lines.push(entry.goal.trim())
  else lines.push('Описание будет доступно в окне информации об агенте.')
  lines.push(`Предназначение: ${agentPurposeLabel(entry.purpose)}`)
  if (entry.triggerSummary.trim()) lines.push(`Запуск: ${entry.triggerSummary.trim()}`)
  return lines
}

function AgentLibraryTile({
  entry,
  busy,
  variant,
  searchId,
  onOpenInfo,
  onAdd,
  onRemove
}: {
  entry: AgentLibraryEntry
  busy: boolean
  variant: 'catalog' | 'adopted'
  searchId: string
  onOpenInfo: () => void
  onAdd?: () => void
  onRemove?: () => void
}): React.JSX.Element {
  const lines = cardBodyLines(entry)
  const author = (entry.author || '').trim()
  const createdAt = formatCreatedAt(entry.createdAt)
  return (
    <article
      data-search-id={searchId}
      className={`agent-library-tile agent-library-tile--clickable${variant === 'adopted' ? ' agent-library-tile--adopted' : ''}`}
      role="button"
      tabIndex={0}
      onClick={onOpenInfo}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onOpenInfo()
        }
      }}
    >
      <div className="agent-library-tile-top">
        <AgentSharePreview entry={entry} />
        {variant === 'catalog' ? (
          <button
            type="button"
            className="agent-library-tile-add"
            title="Добавить к себе"
            disabled={busy}
            onClick={(event) => {
              event.stopPropagation()
              onAdd?.()
            }}
          >
            <Plus size={20} strokeWidth={2.4} aria-hidden />
          </button>
        ) : (
          <button
            type="button"
            className="agent-library-tile-remove agent-library-tile-remove--corner"
            disabled={busy}
            onClick={(event) => {
              event.stopPropagation()
              onRemove?.()
            }}
          >
            удалить
          </button>
        )}
      </div>
      <div className="agent-library-tile-body">
        {lines.map((line, index) => (
          <p key={`${entry.workflowId}-${index}`}>{line}</p>
        ))}
      </div>
      {author || createdAt ? (
        <div className="agent-library-tile-meta">
          {author ? <span className="agent-library-tile-meta-author">{author}</span> : null}
          {createdAt ? <span className="agent-library-tile-meta-date">{createdAt}</span> : null}
        </div>
      ) : null}
    </article>
  )
}

function AgentLibraryInfoModal({
  entry,
  variant,
  busy,
  onClose,
  onAdd,
  onOpenPassport,
  onRemove
}: {
  entry: AgentLibraryEntry
  variant: 'catalog' | 'adopted'
  busy: boolean
  onClose: () => void
  onAdd?: () => void
  onOpenPassport?: () => void
  onRemove?: () => void
}): React.JSX.Element {
  return (
    <div className="modal-overlay agent-library-info-overlay" onClick={onClose}>
      <div className="modal-card agent-library-info-modal" onClick={(event) => event.stopPropagation()}>
        <AgentSharePreview entry={entry} />
        <div className="agent-library-info-rows">
          <label>Описание</label>
          <div>{entry.description.trim() || 'не указано'}</div>
          <label>Цель</label>
          <div>{entry.goal.trim() || 'не указана'}</div>
          <label>Предназначение</label>
          <div>{agentPurposeLabel(entry.purpose)}</div>
          {entry.ownerFio?.trim() ? (
            <>
              <label>Автор публикации</label>
              <div>{entry.ownerFio.trim()}</div>
            </>
          ) : null}
          <label>Триггер</label>
          <div>{entry.triggerSummary.trim() || entry.triggerKind.trim() || 'не указан'}</div>
          <label>Инструменты</label>
          <div>{entry.tools.length ? entry.tools.join(', ') : 'не указаны'}</div>
        </div>
        <div className="modal-actions agent-library-info-actions">
          <button type="button" className="btn-light" onClick={onClose}>
            Закрыть
          </button>
          {variant === 'catalog' ? (
            <button type="button" className="btn-primary" disabled={busy} onClick={() => onAdd?.()}>
              Добавить к себе
            </button>
          ) : (
            <>
              <button type="button" className="btn-light" disabled={busy} onClick={() => onRemove?.()}>
                Удалить
              </button>
              <button type="button" className="btn-primary" disabled={busy} onClick={() => onOpenPassport?.()}>
                Открыть паспорт
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function SkeletonTile(): React.JSX.Element {
  return (
    <div className="agent-library-tile agent-library-tile--skeleton" aria-hidden>
      <div className="agent-library-skel-block" />
      <div className="agent-library-skel-line" />
      <div className="agent-library-skel-line" />
    </div>
  )
}

export function AgentLibraryGridTab({
  user,
  onOpenPassport
}: {
  user: UserProfile
  onOpenPassport: (workflowId: string, title: string, tab?: PassportTab) => void
}): React.JSX.Element {
  const cached = getCachedAgentLibrary()
  const [catalog, setCatalog] = useState<AgentLibraryEntry[]>(() =>
    (cached?.catalog ?? []).filter((item) => !item.alreadyAdded && isIlchenkoLibraryAgent(item))
  )
  const [adopted, setAdopted] = useState<AgentLibraryEntry[]>(() =>
    (cached?.adopted ?? []).filter(isIlchenkoLibraryAgent)
  )
  const [initialLoading, setInitialLoading] = useState(() => !cached)
  const [refreshing, setRefreshing] = useState(false)
  const [busyId, setBusyId] = useState('')
  const [error, setError] = useState('')
  const { query: search, setQuery: setSearch } = usePageSearch()
  const [info, setInfo] = useState<{ entry: AgentLibraryEntry; variant: 'catalog' | 'adopted' } | null>(
    null
  )
  const loadGen = useRef(0)
  const hasPaintedRef = useRef(Boolean(cached))

  const applySnapshot = useCallback((snap: { catalog: AgentLibraryEntry[]; adopted: AgentLibraryEntry[] }) => {
    setCatalog(snap.catalog.filter((item) => !item.alreadyAdded && isIlchenkoLibraryAgent(item)))
    setAdopted(snap.adopted.filter(isIlchenkoLibraryAgent))
    hasPaintedRef.current = true
  }, [])

  const reload = useCallback(async (mode: 'initial' | 'refresh') => {
    const gen = ++loadGen.current
    setError('')
    if (mode === 'initial' && !hasPaintedRef.current) setInitialLoading(true)
    else setRefreshing(true)
    try {
      const snap = await fetchAgentLibrary({ force: mode === 'refresh' })
      if (gen !== loadGen.current) return
      applySnapshot(snap)
    } catch (err) {
      if (gen !== loadGen.current) return
      if (err instanceof ApiError && err.status === 404) {
        setError(
          'Сервис библиотеки недоступен. Запустите локальный backend (run_dev.bat) или обновите gateway.'
        )
      } else if (err instanceof ApiError && err.status === 0) {
        setError('Нет связи с backend. Проверьте VPN и BACKEND_URL.')
      } else {
        setError(err instanceof Error ? err.message : 'Не удалось загрузить библиотеку')
      }
    } finally {
      if (gen === loadGen.current) {
        setInitialLoading(false)
        setRefreshing(false)
      }
    }
  }, [applySnapshot])

  useEffect(() => {
    void reload('initial')
    return () => {
      loadGen.current += 1
    }
  }, [reload, user.id])

  const query = normSearch(search)
  const adoptedSourceIds = useMemo(() => {
    const ids = new Set<string>()
    for (const entry of adopted) {
      if (entry.workflowId) ids.add(entry.workflowId)
      if (entry.adoptedWorkflowId) ids.add(entry.adoptedWorkflowId)
    }
    return ids
  }, [adopted])

  const filteredCatalog = useMemo(
    () =>
      catalog
        .filter((entry) => !entry.alreadyAdded && !adoptedSourceIds.has(entry.workflowId))
        .filter((entry) => matchesSearch(entry, query)),
    [catalog, query, adoptedSourceIds]
  )
  const filteredAdopted = useMemo(
    () => adopted.filter((entry) => matchesSearch(entry, query)),
    [adopted, query]
  )
  const globalSearchEntries = useMemo<GlobalSearchEntry[]>(
    () =>
      [
        ...filteredCatalog.map((entry) => ({
          entry,
          targetId: `catalog:${entry.workflowId}`,
          variant: 'Каталог'
        })),
        ...filteredAdopted.map((entry) => ({
          entry,
          targetId: `adopted:${entry.adoptedWorkflowId || entry.workflowId}`,
          variant: 'Мои агенты'
        }))
      ].map(({ entry, targetId, variant }) => ({
        id: `agent_library:${targetId}`,
        source: 'grid:agent_library',
        pageKey: 'agent_library',
        kind: 'entity',
        targetId,
        title: entry.title,
        subtitle: [variant, agentPurposeLabel(entry.purpose), entry.ownerFio].filter(Boolean).join(' · '),
        keywords: [entry.description, entry.goal, entry.triggerSummary, entry.author, ...entry.tools]
      })),
    [filteredCatalog, filteredAdopted]
  )
  useRegisterGlobalSearch('grid:agent_library', globalSearchEntries)

  async function handleAdd(entry: AgentLibraryEntry): Promise<void> {
    setBusyId(entry.workflowId)
    setError('')
    try {
      await adoptAgentFromLibrary(entry.workflowId)
      setInfo(null)
      await reload('refresh')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось добавить агента')
    } finally {
      setBusyId('')
    }
  }

  async function handleRemove(entry: AgentLibraryEntry): Promise<void> {
    const wfId = (entry.adoptedWorkflowId || entry.workflowId).trim()
    if (!wfId) return
    const ok = window.confirm(`Удалить «${entry.title}» из ваших агентов?`)
    if (!ok) return
    setBusyId(wfId)
    setError('')
    try {
      await api.deleteWorkflow(wfId)
      setInfo(null)
      await reload('refresh')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось удалить агента')
    } finally {
      setBusyId('')
    }
  }

  function openPassport(entry: AgentLibraryEntry): void {
    const wfId = (entry.adoptedWorkflowId || entry.workflowId).trim()
    if (!wfId) return
    setInfo(null)
    onOpenPassport(wfId, entry.title, 'info')
  }

  const showSkeleton = initialLoading && !catalog.length && !adopted.length

  return (
    <>
      <StandardTabChrome
        tabId="agent_library"
        userId={user.id || ''}
        defaults={DEFAULT_AGENT_LIBRARY_LAYOUT}
        hideGlobalPeriod
        labels={{
          main: 'Доступные к подключению',
          botA: 'Мои агенты'
        }}
        widgets={{
          filters: (
            <div className="agent-library-toolbar-row">
              <div className="agent-library-search" role="search">
                <Search size={16} aria-hidden className="agent-library-search-ico" />
                <input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Поиск по названию, предназначению, описанию…"
                  aria-label="Поиск в библиотеке агентов"
                />
              </div>
              <button
                type="button"
                className="agent-library-refresh"
                disabled={refreshing}
                onClick={() => void reload('refresh')}
              >
                <RefreshCw size={15} className={refreshing ? 'agent-library-spin' : ''} aria-hidden />
                {refreshing ? 'Обновление…' : 'Обновить'}
              </button>
              <span className="agent-library-stats set-muted" aria-live="polite">
                {initialLoading
                  ? 'Загрузка…'
                  : `Доступно: ${catalog.length} · У вас: ${adopted.length}`}
              </span>
              <span className="agent-library-add-hint set-muted">Кнопка «+» — копия к вам</span>
            </div>
          ),
          main: (
            <div className="agent-library-widget agent-library-widget--catalog">
              <h2 className="agent-library-widget-title">Доступные к подключению</h2>
              {error ? <div className="agent-library-error">{error}</div> : null}
              <div className="agent-library-widget-scroll">
                <div className="agent-library-cards agent-library-cards--catalog">
                  {showSkeleton
                    ? Array.from({ length: 8 }, (_, index) => <SkeletonTile key={`sk-${index}`} />)
                    : null}
                  {!showSkeleton && filteredCatalog.length === 0 ? (
                    <div className="agent-library-empty">
                      {query
                        ? 'Ничего не найдено.'
                        : 'Нет новых агентов — все уже добавлены или каталог пуст.'}
                    </div>
                  ) : null}
                  {!showSkeleton
                    ? filteredCatalog.map((entry) => (
                        <AgentLibraryTile
                          key={entry.workflowId}
                          entry={entry}
                          variant="catalog"
                          searchId={`catalog:${entry.workflowId}`}
                          busy={busyId === entry.workflowId}
                          onOpenInfo={() => setInfo({ entry, variant: 'catalog' })}
                          onAdd={() => void handleAdd(entry)}
                        />
                      ))
                    : null}
                </div>
              </div>
            </div>
          ),
          botA: (
            <div className="agent-library-widget agent-library-widget--adopted">
              <h2 className="agent-library-widget-title">Мои агенты</h2>
              <div className="agent-library-widget-scroll">
                <div className="agent-library-cards agent-library-cards--adopted">
                  {!showSkeleton && filteredAdopted.length === 0 ? (
                    <div className="agent-library-empty agent-library-empty--dashed">
                      Добавьте агента из каталога выше.
                    </div>
                  ) : null}
                  {!showSkeleton
                    ? filteredAdopted.map((entry) => (
                        <AgentLibraryTile
                          key={entry.adoptedWorkflowId || entry.workflowId}
                          entry={entry}
                          variant="adopted"
                          searchId={`adopted:${entry.adoptedWorkflowId || entry.workflowId}`}
                          busy={busyId === (entry.adoptedWorkflowId || entry.workflowId)}
                          onOpenInfo={() => setInfo({ entry, variant: 'adopted' })}
                          onRemove={() => void handleRemove(entry)}
                        />
                      ))
                    : null}
                </div>
              </div>
            </div>
          )
        }}
      />

      {info ? (
        <AgentLibraryInfoModal
          entry={info.entry}
          variant={info.variant}
          busy={busyId === (info.entry.adoptedWorkflowId || info.entry.workflowId || info.entry.workflowId)}
          onClose={() => setInfo(null)}
          onAdd={info.variant === 'catalog' ? () => void handleAdd(info.entry) : undefined}
          onRemove={info.variant === 'adopted' ? () => void handleRemove(info.entry) : undefined}
          onOpenPassport={info.variant === 'adopted' ? () => openPassport(info.entry) : undefined}
        />
      ) : null}
    </>
  )
}
