import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { UserProfile } from '../../api/types'
import { StandardTabChrome, summaryTilesAsChrome } from './TabChromeGrid'
import { DEFAULT_STANDARD_LAYOUT } from './useTabChromeLayout'
import type { SpecSummaryTile } from '../../workplace/specV04Shell'
import { SpecPill } from '../../workplace/specV04Components'
import { type SpecMailRow } from '../../workplace/specV04DemoData'
import { useSpecV04Sources } from '../../workplace/useSpecV04Data'
import { countMailTiles, mailMatchesTile, toggleSimpleTile } from '../../workplace/tileFilters'
import { mailListEmptyHint } from '../../workplace/mailProbe'
import { formatMailTime } from '../../utils/outlookMail'
import { decodeMimeHeader } from '../../utils/mimeHeader'
import { GridFilterBar, toFilterOptions, uniqueFilterValues } from './gridFilters'
import { useWorkplacePeriod } from '../../workplace/workplacePeriod'
import { MailDetailPanel } from './MailDetailPanel'
import { usePageSearch } from '../../layout/pageSearchContext'
import {
  applyMailMeta,
  createMailFolderId,
  isDefaultMailFolder,
  loadMailFolders,
  loadMailMeta,
  MAIL_FOLDER_COLORS,
  MAIL_PRIORITY_OPTIONS,
  priorityToneForLabel,
  saveMailFolders,
  saveMailMeta,
  type MailFolder,
  type MailFolderColor,
  type MailRowMeta
} from '../../workplace/mailFolders'
import './mailGrid.css'

type MailDirectionTab = 'inbox' | 'sent'

type ContextMenuState = {
  x: number
  y: number
  rowId: string
}

type FolderEditorState =
  | { mode: 'create' }
  | { mode: 'edit'; folderId: string }

function mailMatchesDirection(row: SpecMailRow, direction: MailDirectionTab): boolean {
  if (direction === 'sent') return row.direction === 'sent'
  return row.direction !== 'sent'
}

export function MailGridTab({
  user,
  onAskOrchestrator
}: {
  user: UserProfile
  onAskOrchestrator: (message: string, context: string) => void
}): React.JSX.Element {
  const userId = user.id || ''
  const data = useSpecV04Sources(user)
  const { from: periodFrom, to: periodTo } = useWorkplacePeriod()
  const [rowPatches, setRowPatches] = useState<Record<string, Partial<SpecMailRow>>>({})
  const [mailMeta, setMailMeta] = useState<Record<string, MailRowMeta>>(() => loadMailMeta(userId))
  const [folders, setFolders] = useState<MailFolder[]>(() => loadMailFolders(userId))
  const [directionTab, setDirectionTab] = useState<MailDirectionTab>('inbox')
  const [folderFilter, setFolderFilter] = useState<string>('all')
  const [selectedId, setSelectedId] = useState('')
  const [tileFilter, setTileFilter] = useState('all')
  const { query, setQuery } = usePageSearch()
  const [barPriority, setBarPriority] = useState('')
  const [barStatus, setBarStatus] = useState('')
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null)
  const contextMenuRef = useRef<HTMLDivElement>(null)
  const [folderEditor, setFolderEditor] = useState<FolderEditorState | null>(null)
  const [folderDraftName, setFolderDraftName] = useState('')
  const [folderDraftColor, setFolderDraftColor] = useState<MailFolderColor>('blue')

  useEffect(() => {
    setMailMeta(loadMailMeta(userId))
    setFolders(loadMailFolders(userId))
  }, [userId])

  const persistMeta = useCallback(
    (next: Record<string, MailRowMeta>) => {
      setMailMeta(next)
      saveMailMeta(userId, next)
    },
    [userId]
  )

  const persistFolders = useCallback(
    (next: MailFolder[]) => {
      setFolders(next)
      saveMailFolders(userId, next)
    },
    [userId]
  )

  const mailRows = useMemo(
    () =>
      data.mailRows.map((row) => {
        const fromMeta = applyMailMeta(row, mailMeta[row.id])
        const patch = rowPatches[row.id]
        return { ...row, ...fromMeta, ...patch }
      }),
    [data.mailRows, mailMeta, rowPatches]
  )

  const directionRows = useMemo(
    () => mailRows.filter((row) => mailMatchesDirection(row, directionTab)),
    [mailRows, directionTab]
  )

  const visibleMail = useMemo(() => {
    const q = query.trim().toLowerCase()
    return directionRows.filter((row) => {
      if (folderFilter !== 'all' && row.appFolderId !== folderFilter) return false
      if (!mailMatchesTile(row, tileFilter)) return false
      if (barPriority && row.priority !== barPriority) return false
      if (barStatus && row.status !== barStatus) return false
      if (
        q &&
        !`${decodeMimeHeader(row.sender)} ${decodeMimeHeader(row.to || '')} ${decodeMimeHeader(row.subject)} ${row.status}`.toLowerCase().includes(q)
      ) {
        return false
      }
      return true
    })
  }, [directionRows, folderFilter, tileFilter, query, barPriority, barStatus])

  const selected = visibleMail.find((m) => m.id === (selectedId || visibleMail[0]?.id))
  const patchRow = useCallback((id: string, patch: Partial<(typeof mailRows)[0]>) => {
    setRowPatches((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }))
  }, [])

  const updateRowMeta = useCallback(
    (rowId: string, patch: MailRowMeta | 'clear-priority') => {
      const next = { ...mailMeta }
      const current = { ...(next[rowId] || {}) }
      if (patch === 'clear-priority') {
        delete current.priority
        delete current.priTone
      } else {
        if (patch.priority !== undefined) {
          current.priority = patch.priority
          current.priTone = patch.priTone || priorityToneForLabel(patch.priority)
        }
        if (patch.appFolderId !== undefined) {
          current.appFolderId = patch.appFolderId
        }
      }
      if (
        !current.priority &&
        (current.appFolderId === undefined || current.appFolderId === null)
      ) {
        delete next[rowId]
      } else {
        next[rowId] = current
      }
      persistMeta(next)
    },
    [mailMeta, persistMeta]
  )

  const tiles: SpecSummaryTile[] = useMemo(() => {
    const counts = countMailTiles(mailRows)
    const inView = countMailTiles(directionRows)
    const dash = (n: number): string => (n ? String(n) : '—')
    return [
      { id: 'inbox', label: 'Входящие', value: dash(counts.inbox), tone: 'orange' },
      { id: 'sent', label: 'Исходящие', value: dash(counts.sent), tone: 'blue' },
      { id: 'hi', label: 'Высокий приоритет', value: dash(inView.hi), tone: 'red' },
      { id: 'proj', label: 'Проектные', value: dash(inView.proj), tone: 'purple' }
    ]
  }, [mailRows, directionRows])

  const ask = (m: string) => onAskOrchestrator(m, 'Вкладка «Письма»')
  const partyHeader = directionTab === 'sent' ? 'Кому' : 'Отправитель'

  const openFolderCreate = () => {
    setFolderDraftName('')
    setFolderDraftColor('blue')
    setFolderEditor({ mode: 'create' })
  }

  const openFolderEdit = (folder: MailFolder) => {
    setFolderDraftName(folder.name)
    setFolderDraftColor(folder.color)
    setFolderEditor({ mode: 'edit', folderId: folder.id })
  }

  const submitFolderEditor = () => {
    const name = folderDraftName.trim()
    if (!name || !folderEditor) return
    if (folderEditor.mode === 'create') {
      persistFolders([
        ...folders,
        { id: createMailFolderId(), name, color: folderDraftColor }
      ])
    } else {
      persistFolders(
        folders.map((f) =>
          f.id === folderEditor.folderId ? { ...f, name, color: folderDraftColor } : f
        )
      )
    }
    setFolderEditor(null)
  }

  const deleteFolder = (folderId: string) => {
    if (isDefaultMailFolder(folderId)) return
    persistFolders(folders.filter((f) => f.id !== folderId))
    if (folderFilter === folderId) setFolderFilter('all')
    const nextMeta = { ...mailMeta }
    let changed = false
    for (const [id, meta] of Object.entries(nextMeta)) {
      if (meta.appFolderId === folderId) {
        nextMeta[id] = { ...meta, appFolderId: null }
        changed = true
      }
    }
    if (changed) persistMeta(nextMeta)
    setFolderEditor(null)
  }

  useLayoutEffect(() => {
    const el = contextMenuRef.current
    if (!contextMenu || !el) return
    const margin = 8
    const rect = el.getBoundingClientRect()
    let left = contextMenu.x
    let top = contextMenu.y
    if (left + rect.width > window.innerWidth - margin) {
      left = Math.max(margin, window.innerWidth - rect.width - margin)
    }
    if (top + rect.height > window.innerHeight - margin) {
      const above = contextMenu.y - rect.height
      top = above >= margin ? above : margin
    }
    if (left < margin) left = margin
    if (top < margin) top = margin
    el.style.left = `${left}px`
    el.style.top = `${top}px`
  }, [contextMenu, folders])

  useEffect(() => {
    if (!contextMenu) return
    const close = () => setContextMenu(null)
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', onKey)
    }
  }, [contextMenu])

  return (
    <StandardTabChrome
      tabId="mail"
      userId={userId}
      defaults={DEFAULT_STANDARD_LAYOUT}
      chromeTiles={summaryTilesAsChrome(
        tiles,
        tileFilter === 'all' ? directionTab : [directionTab, tileFilter],
        (id) => {
          if (id === 'inbox' || id === 'sent') {
            setDirectionTab(id)
            return
          }
          setTileFilter((current) => toggleSimpleTile(current, id))
        }
      )}
      widgets={{
        filters: (
          <GridFilterBar
            search={{ value: query, onChange: setQuery, placeholder: 'Поиск в письмах…' }}
            selects={[
              {
                id: 'priority',
                value: barPriority,
                emptyLabel: 'Приоритет: все',
                onChange: setBarPriority,
                options: toFilterOptions(uniqueFilterValues(directionRows.map((row) => row.priority)))
              },
              {
                id: 'status',
                value: barStatus,
                emptyLabel: 'Статус: все',
                onChange: setBarStatus,
                options: toFilterOptions(uniqueFilterValues(directionRows.map((row) => row.status)))
              }
            ]}
            onReset={() => {
              setQuery('')
              setBarPriority('')
              setBarStatus('')
              setTileFilter('all')
              setFolderFilter('all')
            }}
          />
        ),
        main: (
          <div className="spec-v04-table-wrap wp-card mail-grid-main">
            <div className="mail-dir-tabs" role="tablist" aria-label="Направление писем">
              <button
                type="button"
                role="tab"
                aria-selected={directionTab === 'inbox'}
                className={directionTab === 'inbox' ? 'mail-dir-tab is-active' : 'mail-dir-tab'}
                onClick={() => setDirectionTab('inbox')}
              >
                Входящие
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={directionTab === 'sent'}
                className={directionTab === 'sent' ? 'mail-dir-tab is-active' : 'mail-dir-tab'}
                onClick={() => setDirectionTab('sent')}
              >
                Исходящие
              </button>
            </div>

            <div className="mail-folder-chips" aria-label="Папки">
              <button
                type="button"
                className={
                  folderFilter === 'all' ? 'mail-folder-chip is-active' : 'mail-folder-chip'
                }
                onClick={() => setFolderFilter('all')}
              >
                Все
              </button>
              {folders.map((folder) => (
                <button
                  key={folder.id}
                  type="button"
                  className={
                    folderFilter === folder.id
                      ? `mail-folder-chip is-active tone-${folder.color}`
                      : `mail-folder-chip tone-${folder.color}`
                  }
                  onClick={() => setFolderFilter(folder.id)}
                  onDoubleClick={() => openFolderEdit(folder)}
                  title={
                    isDefaultMailFolder(folder.id)
                      ? 'Двойной клик — переименовать / цвет'
                      : 'Двойной клик — изменить · ПКМ строки — положить письмо'
                  }
                >
                  <span className={`mail-folder-dot tone-${folder.color}`} aria-hidden />
                  {folder.name}
                </button>
              ))}
              <button type="button" className="mail-folder-chip mail-folder-chip-new" onClick={openFolderCreate}>
                + Новая папка
              </button>
            </div>

            {folderEditor ? (
              <div className="mail-folder-editor">
                <input
                  className="mail-folder-editor-name"
                  value={folderDraftName}
                  onChange={(e) => setFolderDraftName(e.target.value)}
                  placeholder="Название папки"
                  autoFocus
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') submitFolderEditor()
                    if (e.key === 'Escape') setFolderEditor(null)
                  }}
                />
                <div className="mail-folder-color-row">
                  {MAIL_FOLDER_COLORS.map((color) => (
                    <button
                      key={color}
                      type="button"
                      className={
                        folderDraftColor === color
                          ? `mail-folder-color-swatch tone-${color} is-active`
                          : `mail-folder-color-swatch tone-${color}`
                      }
                      aria-label={color}
                      onClick={() => setFolderDraftColor(color)}
                    />
                  ))}
                </div>
                <div className="mail-folder-editor-actions">
                  <button type="button" className="spec-btn-outline mail-folder-editor-btn" onClick={() => setFolderEditor(null)}>
                    Отмена
                  </button>
                  {folderEditor.mode === 'edit' && !isDefaultMailFolder(folderEditor.folderId) ? (
                    <button
                      type="button"
                      className="spec-btn-outline mail-folder-editor-btn is-danger"
                      onClick={() => deleteFolder(folderEditor.folderId)}
                    >
                      Удалить
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="spec-btn-launch mail-folder-editor-btn"
                    disabled={!folderDraftName.trim()}
                    onClick={submitFolderEditor}
                  >
                    Сохранить
                  </button>
                </div>
              </div>
            ) : null}

            <table className="spec-v04-table">
              <thead>
                <tr>
                  <th>{partyHeader}</th>
                  <th>Тема</th>
                  <th>Время</th>
                  <th>Приоритет</th>
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody>
                {!visibleMail.length ? (
                  <tr>
                    <td colSpan={5} className="spec-v04-empty">
                      {directionRows.length
                        ? folderFilter !== 'all'
                          ? 'Нет писем в выбранной папке'
                          : 'Нет писем по выбранной плитке'
                        : mailListEmptyHint({
                            loading: data.mailLoading,
                            imapPrimary: data.mailImapPrimary,
                            mailbox: data.outlookMailbox,
                            imapStatus: data.mailImapStatus,
                            periodFrom,
                            periodTo
                          })}
                    </td>
                  </tr>
                ) : null}
                {visibleMail.map((row) => (
                  <tr
                    key={row.id}
                    className={selected?.id === row.id ? 'selected' : ''}
                    onClick={() => setSelectedId(row.id)}
                    onContextMenu={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      setSelectedId(row.id)
                      setContextMenu({ x: e.clientX, y: e.clientY, rowId: row.id })
                    }}
                  >
                    <td>
                      {decodeMimeHeader(directionTab === 'sent' ? row.to || row.sender : row.sender)}
                    </td>
                    <td>{decodeMimeHeader(row.subject)}</td>
                    <td>{formatMailTime(row.time)}</td>
                    <td>
                      <SpecPill tone={row.priTone}>{row.priority}</SpecPill>
                    </td>
                    <td>
                      <SpecPill tone={row.stTone}>{row.status}</SpecPill>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {contextMenu
              ? createPortal(
              <div
                ref={contextMenuRef}
                className="mail-ctx-menu"
                style={{ left: contextMenu.x, top: contextMenu.y }}
                onMouseDown={(e) => e.stopPropagation()}
                role="menu"
              >
                <div className="mail-ctx-section-label">Приоритет</div>
                {MAIL_PRIORITY_OPTIONS.map((label) => (
                  <button
                    key={label}
                    type="button"
                    className="mail-ctx-item"
                    role="menuitem"
                    onClick={() => {
                      updateRowMeta(contextMenu.rowId, {
                        priority: label,
                        priTone: priorityToneForLabel(label)
                      })
                      setContextMenu(null)
                    }}
                  >
                    <SpecPill tone={priorityToneForLabel(label)}>{label}</SpecPill>
                  </button>
                ))}
                <button
                  type="button"
                  className="mail-ctx-item"
                  role="menuitem"
                  onClick={() => {
                    updateRowMeta(contextMenu.rowId, 'clear-priority')
                    setContextMenu(null)
                  }}
                >
                  Сбросить приоритет
                </button>
                <div className="mail-ctx-sep" />
                <div className="mail-ctx-section-label">В папку</div>
                {folders.map((folder) => (
                  <button
                    key={folder.id}
                    type="button"
                    className="mail-ctx-item"
                    role="menuitem"
                    onClick={() => {
                      updateRowMeta(contextMenu.rowId, { appFolderId: folder.id })
                      setContextMenu(null)
                    }}
                  >
                    <span className={`mail-folder-dot tone-${folder.color}`} aria-hidden />
                    {folder.name}
                  </button>
                ))}
                <button
                  type="button"
                  className="mail-ctx-item"
                  role="menuitem"
                  onClick={() => {
                    updateRowMeta(contextMenu.rowId, { appFolderId: null })
                    setContextMenu(null)
                  }}
                >
                  Убрать из папки
                </button>
              </div>,
              document.body
            )
              : null}
          </div>
        ),
        side: selected ? (
          <MailDetailPanel mail={selected} user={user} onPatchRow={patchRow} onAskOrchestrator={ask} />
        ) : (
          <div className="wp-card spec-v04-muted">Выберите письмо</div>
        )
      }}
    />
  )
}
