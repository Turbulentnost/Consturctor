import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api/client'
import type { UserProfile, WorkflowFileItem } from '../../api/types'
import { useReportError } from '../../components/ErrorToast'
import { usePageSearch } from '../../layout/pageSearchContext'
import { useRegisterGlobalSearch, type GlobalSearchEntry } from '../../layout/globalSearch'
import { StandardTabChrome, summaryTilesAsChrome } from './TabChromeGrid'
import { DEFAULT_STANDARD_LAYOUT } from './useTabChromeLayout'
import type { SpecSummaryTile } from '../../workplace/specV04Shell'
import { SpecPill } from '../../workplace/specV04Components'
import { isUserFacingResultFile } from '../../workplace/preparedDecisions'
import { useWorkplacePeriod } from '../../workplace/workplacePeriod'
import { isoTimestampInWorkplacePeriod } from '../../workplace/workplacePeriodFilter'
import { GridFilterBar } from './gridFilters'

type AgentFileRow = {
  id: string
  name: string
  agent: string
  kind: 'Регламент' | 'Документ'
  createdAt: string
  summary: string
  downloadUrl: string
  workflowId: string
}

/** Файл, который агент сформировал в запуске с аккаунта текущего пользователя. */
function isAgentFormedFile(file: WorkflowFileItem): boolean {
  const source = (file.source || '').toLowerCase()
  const scope = (file.scope || '').toLowerCase()
  if (scope === 'run_attachment') return false
  if (source !== 'agent' && scope !== 'run_output') return false
  if (!(file.runId || '').trim() || !(file.workflowId || '').trim()) return false
  return isUserFacingResultFile(file)
}

function isRegulation(file: WorkflowFileItem): boolean {
  return /регламент/i.test(`${file.name} ${file.summary} ${file.agentTitle}`)
}

function formatWhen(value: string): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

export function AgentFilesGridTab({ user }: { user: UserProfile }): React.JSX.Element {
  const [rows, setRows] = useState<AgentFileRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [opening, setOpening] = useState(false)
  const [openHint, setOpenHint] = useState('')
  const { from: periodFrom, to: periodTo } = useWorkplacePeriod()
  const { query, setQuery } = usePageSearch()
  const [tileFilter, setTileFilter] = useState('all')
  useReportError(error)

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError('')
    void api
      .listPlatformFiles()
      .then((files) => {
        if (!alive) return
        const next = files.filter(isAgentFormedFile).map((file) => ({
          id: file.id,
          name: file.name || 'Файл',
          agent: file.agentTitle || 'Агент',
          kind: isRegulation(file) ? ('Регламент' as const) : ('Документ' as const),
          createdAt: file.createdAt || '',
          summary: file.summary || '',
          downloadUrl: file.downloadUrl || '',
          workflowId: file.workflowId || ''
        }))
        setRows(next)
      })
      .catch((err: unknown) => {
        if (!alive) return
        setRows([])
        setError(err instanceof Error ? err.message : 'Не удалось загрузить файлы агентов')
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [user.id])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return rows.filter((row) => {
      if (!isoTimestampInWorkplacePeriod(row.createdAt, periodFrom, periodTo)) return false
      if (tileFilter === 'reg' && row.kind !== 'Регламент') return false
      if (tileFilter === 'doc' && row.kind !== 'Документ') return false
      if (q && !`${row.name} ${row.agent} ${row.summary}`.toLowerCase().includes(q)) return false
      return true
    })
  }, [rows, query, tileFilter, periodFrom, periodTo])

  const globalSearchEntries = useMemo<GlobalSearchEntry[]>(
    () =>
      visible.map((row) => ({
        id: `agent-file:${row.id}`,
        source: 'grid:agent_files',
        pageKey: 'agent_files',
        kind: 'entity',
        targetId: row.id,
        title: row.name,
        subtitle: [row.agent, row.kind].filter(Boolean).join(' · '),
        keywords: [row.summary, row.createdAt]
      })),
    [visible]
  )
  useRegisterGlobalSearch('grid:agent_files', globalSearchEntries)

  const selected = visible.find((row) => row.id === (selectedId || visible[0]?.id))
  const regulations = rows.filter((row) => row.kind === 'Регламент').length
  const documents = rows.length - regulations
  const tiles: SpecSummaryTile[] = [
    { id: 'all', label: 'Файлы агентов', value: rows.length ? String(rows.length) : '—', tone: 'blue' },
    { id: 'reg', label: 'Регламенты', value: regulations ? String(regulations) : '—', tone: 'green' },
    { id: 'doc', label: 'Документы', value: documents ? String(documents) : '—', tone: 'purple' }
  ]

  const downloadSelected = (): void => {
    if (!selected?.downloadUrl) {
      setOpenHint('У файла нет ссылки на скачивание.')
      return
    }
    setOpening(true)
    setOpenHint('')
    void api
      .download(selected.downloadUrl, selected.name)
      .then((ok) => {
        if (!ok) setOpenHint('Не удалось скачать файл.')
      })
      .catch(() => setOpenHint('Не удалось скачать файл.'))
      .finally(() => setOpening(false))
  }

  return (
    <StandardTabChrome
      tabId="agent_files"
      userId={user.id || ''}
      defaults={DEFAULT_STANDARD_LAYOUT}
      chromeTiles={summaryTilesAsChrome(tiles, tileFilter, (id) =>
        setTileFilter((current) => (id === current || id === 'all' ? 'all' : id))
      )}
      widgets={{
        filters: (
          <GridFilterBar
            search={{ value: query, onChange: setQuery, placeholder: 'Поиск по файлам агентов…' }}
            onReset={() => {
              setQuery('')
              setTileFilter('all')
            }}
          />
        ),
        main: (
          <div className="spec-v04-table-wrap wp-card">
            <table className="spec-v04-table">
              <thead>
                <tr>
                  <th>Название</th>
                  <th>Агент</th>
                  <th>Тип</th>
                  <th>Создан</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={4} className="spec-v04-empty">
                      Загружаем файлы агентов…
                    </td>
                  </tr>
                ) : null}
                {!loading && !visible.length ? (
                  <tr>
                    <td colSpan={4} className="spec-v04-empty">
                      {rows.length
                        ? 'Нет файлов по выбранному фильтру'
                        : 'Агенты этого аккаунта ещё не сформировали документы.'}
                    </td>
                  </tr>
                ) : null}
                {visible.map((row) => (
                  <tr
                    key={row.id}
                    data-search-id={row.id}
                    className={selected?.id === row.id ? 'selected' : ''}
                    onClick={() => {
                      setSelectedId(row.id)
                      setOpenHint('')
                    }}
                  >
                    <td>
                      <strong>{row.name}</strong>
                    </td>
                    <td>{row.agent}</td>
                    <td>
                      <SpecPill tone={row.kind === 'Регламент' ? 'green' : 'purple'}>{row.kind}</SpecPill>
                    </td>
                    <td>{formatWhen(row.createdAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ),
        side: selected ? (
          <div className="spec-detail-card">
            <h2>{selected.name}</h2>
            <SpecPill tone={selected.kind === 'Регламент' ? 'green' : 'purple'}>{selected.kind}</SpecPill>
            <p className="spec-v04-muted">{selected.agent}</p>
            <p className="spec-v04-muted">{formatWhen(selected.createdAt)}</p>
            {selected.summary ? <p>{selected.summary}</p> : null}
            {openHint ? <p className="spec-v04-muted">{openHint}</p> : null}
            <button
              type="button"
              className="spec-btn-launch spec-btn-launch-block"
              disabled={opening}
              onClick={downloadSelected}
            >
              {opening ? 'Скачиваем…' : 'Скачать'}
            </button>
          </div>
        ) : (
          <div className="wp-card spec-v04-muted">Выберите файл</div>
        )
      }}
    />
  )
}
