import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  ArrowRight,
  ArrowUp,
  ChevronRight,
  File as FileIcon,
  FilePlus,
  FileText,
  FileSpreadsheet,
  Folder,
  FolderPlus,
  FolderOpen,
  Image as ImageIcon,
  KeyRound,
  Lock,
  RefreshCw,
  Trash2,
  Users
} from 'lucide-react'
import { api, type ExplorerItem, type ExplorerListing } from '../../api/client'
import { useErrorToast } from '../../components/ErrorToast'
import { OrchSlotMain } from '../../layout/GridSlots'
import { ACCESS_LABELS, AccessDialog, NewFileDialog, NewFolderDialog, errorText } from './KnowledgeDialogs'
import './knowledgeExplorer.css'

const ROOT_LABEL = 'Мои файлы'

function formatSize(bytes: number): string {
  if (!bytes) return '0 Б'
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`
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

function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : ''
}

function ItemIcon({ item, size = 18 }: { item: ExplorerItem; size?: number }): React.JSX.Element {
  if (item.kind === 'folder') {
    return item.isVirtual ? (
      <Users size={size} className="kx-icon kx-icon-shared" />
    ) : (
      <Folder size={size} className="kx-icon kx-icon-folder" />
    )
  }
  const ext = extensionOf(item.name)
  if (['xls', 'xlsx', 'csv', 'ods'].includes(ext)) {
    return <FileSpreadsheet size={size} className="kx-icon kx-icon-sheet" />
  }
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg'].includes(ext)) {
    return <ImageIcon size={size} className="kx-icon kx-icon-image" />
  }
  if (['doc', 'docx', 'txt', 'md', 'rtf', 'pdf', 'odt'].includes(ext)) {
    return <FileText size={size} className="kx-icon kx-icon-doc" />
  }
  return <FileIcon size={size} className="kx-icon" />
}

function accessSummary(item: ExplorerItem): string {
  if (!item.isOwner) return `Ключ выдал ${item.ownerFio || 'владелец'}`
  return item.accessMode ? `Доступ: ${ACCESS_LABELS[item.accessMode].toLowerCase()}` : ''
}

type Dialog = { kind: 'folder' } | { kind: 'file' } | { kind: 'access'; item: ExplorerItem } | null

/** Проводник базы знаний: файлы хранятся на сетевой папке зашифрованными, ключи — на сервере. */
export function KnowledgeGridTab(): React.JSX.Element {
  const reportError = useErrorToast()
  const [folderId, setFolderId] = useState<string | null>(null)
  const [listing, setListing] = useState<ExplorerListing>({ path: [], parentId: null, items: [] })
  const [loading, setLoading] = useState(true)
  const [reloadKey, setReloadKey] = useState(0)
  const [selectedId, setSelectedId] = useState('')
  const [dialog, setDialog] = useState<Dialog>(null)
  const [notice, setNotice] = useState<{ id: number; text: string } | null>(null)
  const [noticeLeaving, setNoticeLeaving] = useState(false)
  const noticeSeq = useRef(0)
  const [menu, setMenu] = useState<{ x: number; y: number; itemId: string } | null>(null)

  const reload = useCallback(() => setReloadKey((k) => k + 1), [])

  const showNotice = useCallback((text: string) => {
    noticeSeq.current += 1
    setNoticeLeaving(false)
    setNotice({ id: noticeSeq.current, text })
  }, [])

  const clearNotice = useCallback(() => {
    setNotice(null)
    setNoticeLeaving(false)
  }, [])

  useEffect(() => {
    let alive = true
    setLoading(true)
    void api
      .listExplorerItems(folderId)
      .then((next) => {
        if (!alive) return
        setListing(next)
        setSelectedId((current) => (next.items.some((i) => i.id === current) ? current : ''))
      })
      .catch((err: unknown) => {
        if (!alive) return
        reportError(errorText(err, 'Не удалось загрузить базу знаний'))
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [folderId, reloadKey, reportError])

  useEffect(
    () =>
      window.api.onExplorerSynced((event) => {
        if (event.ok) {
          showNotice(`Изменения в «${event.name}» сохранены`)
          reload()
        } else {
          reportError(event.error || `Не удалось сохранить «${event.name}»`)
        }
      }),
    [reload, reportError, showNotice]
  )

  useEffect(() => {
    if (!notice) return
    const id = notice.id
    const hide = window.setTimeout(() => setNoticeLeaving(true), 4000)
    const gone = window.setTimeout(() => {
      setNotice((current) => (current?.id === id ? null : current))
      setNoticeLeaving(false)
    }, 4360)
    return () => {
      window.clearTimeout(hide)
      window.clearTimeout(gone)
    }
  }, [notice])

  const selected = useMemo(
    () => listing.items.find((item) => item.id === selectedId) || null,
    [listing.items, selectedId]
  )
  const inShared = folderId === 'shared'
  const canCreateHere = !inShared

  const goUp = (): void => {
    if (folderId === null) return
    setFolderId(inShared ? null : listing.parentId)
    setSelectedId(folderId)
  }

  const openItem = (item: ExplorerItem): void => {
    if (item.kind === 'folder') {
      setFolderId(item.id)
      setSelectedId('')
      return
    }
    showNotice(`Открываем «${item.name}»…`)
    void api
      .openExplorerFile(item)
      .then(() => showNotice(`«${item.name}» открыт. Сохранённые изменения попадут в базу знаний.`))
      .catch((err: unknown) => {
        clearNotice()
        reportError(errorText(err, 'Не удалось открыть файл'))
      })
  }

  const deleteItem = (item: ExplorerItem): void => {
    const what = item.kind === 'folder' ? `папку «${item.name}» со всем содержимым` : `файл «${item.name}»`
    if (!window.confirm(`Удалить ${what}?`)) return
    void api
      .deleteExplorerItem(item.id)
      .then(() => {
        setSelectedId('')
        reload()
      })
      .catch((err: unknown) => reportError(errorText(err, 'Не удалось удалить')))
  }

  const onCreated = (item: ExplorerItem): void => {
    setDialog(null)
    setSelectedId(item.id)
    reload()
  }

  const onListKey = (e: React.KeyboardEvent): void => {
    if (e.key === 'Backspace' || (e.altKey && e.key === 'ArrowUp')) {
      e.preventDefault()
      goUp()
      return
    }
    if (!listing.items.length) return
    const index = listing.items.findIndex((i) => i.id === selectedId)
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      const next = e.key === 'ArrowDown' ? Math.min(index + 1, listing.items.length - 1) : Math.max(index - 1, 0)
      setSelectedId(listing.items[next].id)
    } else if (e.key === 'Enter' && selected) {
      openItem(selected)
    } else if (e.key === 'Delete' && selected?.isOwner) {
      deleteItem(selected)
    }
  }

  useEffect(() => {
    if (!menu) return
    const close = (): void => setMenu(null)
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') close()
    }
    window.addEventListener('mousedown', close)
    window.addEventListener('keydown', onKey)
    window.addEventListener('scroll', close, true)
    return () => {
      window.removeEventListener('mousedown', close)
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', close, true)
    }
  }, [menu])

  const openCreateMenu = (event: React.MouseEvent): void => {
    const target = event.target as HTMLElement
    if (target.closest('input, textarea, .kx-toolbar-actions, .kx-go, .kx-menu')) return
    const row = target.closest('[data-kx-id]')
    const itemId = row?.getAttribute('data-kx-id') || ''
    const item = listing.items.find((entry) => entry.id === itemId) || null
    const canDelete = Boolean(item?.isOwner && !item.isVirtual)
    if (!canCreateHere && !canDelete) return
    event.preventDefault()
    if (item) setSelectedId(item.id)
    const width = 220
    const height = canDelete ? 136 : 96
    setMenu({
      x: Math.max(8, Math.min(event.clientX, window.innerWidth - width - 8)),
      y: Math.max(8, Math.min(event.clientY, window.innerHeight - height - 8)),
      itemId
    })
  }

  const crumbs = [{ id: '', name: ROOT_LABEL }, ...listing.path]

  return (
    <OrchSlotMain spanAll heavyEmbed>
      <section className="kx-page" onContextMenu={openCreateMenu}>
        <div className="kx-toolbar">
          <button
            type="button"
            className="kx-icon-btn"
            title="На уровень вверх"
            aria-label="На уровень вверх"
            disabled={folderId === null}
            onClick={goUp}
          >
            <ArrowUp size={18} />
          </button>
          <nav className="kx-crumbs" aria-label="Путь">
            {crumbs.map((crumb, index) => (
              <span key={crumb.id || 'root'} className="kx-crumb">
                {index > 0 ? <ChevronRight size={14} className="kx-crumb-sep" /> : null}
                <button
                  type="button"
                  disabled={index === crumbs.length - 1}
                  onClick={() => {
                    setFolderId(crumb.id || null)
                    setSelectedId('')
                  }}
                >
                  {crumb.name}
                </button>
              </span>
            ))}
          </nav>
          <div className="kx-toolbar-actions">
            <button
              type="button"
              className="kx-icon-btn"
              title="Обновить"
              aria-label="Обновить"
              onClick={reload}
            >
              <RefreshCw size={17} className={loading ? 'kx-spin' : ''} />
            </button>
            <button
              type="button"
              className="kx-icon-btn"
              title={canCreateHere ? 'Новая папка' : 'В «Доступные мне» создавать нельзя'}
              aria-label="Новая папка"
              disabled={!canCreateHere}
              onClick={() => setDialog({ kind: 'folder' })}
            >
              <FolderPlus size={19} />
            </button>
            <button
              type="button"
              className="kx-icon-btn"
              title={canCreateHere ? 'Новый файл' : 'В «Доступные мне» создавать нельзя'}
              aria-label="Новый файл"
              disabled={!canCreateHere}
              onClick={() => setDialog({ kind: 'file' })}
            >
              <FilePlus size={19} />
            </button>
          </div>
        </div>

        <div className="kx-body">
          <div
            className="kx-list"
            tabIndex={0}
            onKeyDown={onListKey}
            onMouseDown={(e) => {
              if (e.target === e.currentTarget) setSelectedId('')
            }}
          >
            <div className="kx-list-head">
              <span>Имя</span>
              <span>Изменён</span>
              <span>Размер</span>
              <span />
            </div>
            {listing.items.map((item) => (
              <div
                key={item.id}
                role="button"
                tabIndex={-1}
                className={item.id === selectedId ? 'kx-item selected' : 'kx-item'}
                data-kx-id={item.id}
                onClick={() => setSelectedId(item.id)}
                onDoubleClick={() => openItem(item)}
              >
                <span className="kx-item-name">
                  <ItemIcon item={item} />
                  <span>{item.name}</span>
                  {item.kind === 'file' && !item.isOwner ? (
                    <span className="kx-item-owner">{item.ownerFio}</span>
                  ) : null}
                </span>
                <span className="kx-item-meta">{item.isVirtual ? '' : formatWhen(item.updatedAt)}</span>
                <span className="kx-item-meta">{formatSize(item.size)}</span>
                <span className="kx-row-actions">
                  {item.kind === 'file' ? (
                    <button
                      type="button"
                      className="kx-go"
                      title="Открыть"
                      aria-label={`Открыть: ${item.name}`}
                      onClick={(event) => {
                        event.stopPropagation()
                        openItem(item)
                      }}
                    >
                      <ArrowRight size={16} />
                    </button>
                  ) : null}
                  {item.isOwner && !item.isVirtual ? (
                    <button
                      type="button"
                      className="kx-go kx-go-danger"
                      title="Удалить"
                      aria-label={`Удалить: ${item.name}`}
                      onClick={(event) => {
                        event.stopPropagation()
                        deleteItem(item)
                      }}
                    >
                      <Trash2 size={15} />
                    </button>
                  ) : null}
                </span>
              </div>
            ))}
            {!loading && listing.items.length === 0 ? (
              <div className="kx-empty">
                {inShared ? (
                  <p>Вам пока не выдали ключ ни к одному файлу.</p>
                ) : (
                  <>
                    <p>Здесь пока пусто.</p>
                    <p className="kx-hint">Правый щелчок по странице создаёт папку или файл.</p>
                  </>
                )}
              </div>
            ) : null}
          </div>

          <aside className="kx-details">
            {selected ? (
              <>
                <div className="kx-details-icon">
                  <ItemIcon item={selected} size={44} />
                </div>
                <h3 className="kx-details-name">{selected.name}</h3>
                {selected.isVirtual ? (
                  <p className="kx-hint">Файлы других сотрудников, которые выдали вам ключ.</p>
                ) : (
                  <dl className="kx-props">
                    <dt>Тип</dt>
                    <dd>
                      {selected.kind === 'folder'
                        ? 'Папка'
                        : extensionOf(selected.name).toUpperCase() || 'Файл'}
                    </dd>
                    <dt>Размер</dt>
                    <dd>{formatSize(selected.size)}</dd>
                    <dt>Владелец</dt>
                    <dd>{selected.isOwner ? 'Вы' : selected.ownerFio || '—'}</dd>
                    <dt>Создан</dt>
                    <dd>{formatWhen(selected.createdAt)}</dd>
                    <dt>Изменён</dt>
                    <dd>{formatWhen(selected.updatedAt)}</dd>
                  </dl>
                )}
                {selected.kind === 'file' ? (
                  <p className="kx-access-line">
                    <Lock size={13} /> Зашифрован. {accessSummary(selected)}
                  </p>
                ) : null}
                <div className="kx-details-actions">
                  <button
                    type="button"
                    className="kx-btn kx-btn-primary"
                    onClick={() => openItem(selected)}
                  >
                    <FolderOpen size={15} /> Открыть
                  </button>
                  {selected.kind === 'file' && selected.isOwner ? (
                    <button
                      type="button"
                      className="kx-btn"
                      onClick={() => setDialog({ kind: 'access', item: selected })}
                    >
                      <KeyRound size={15} /> Доступ
                    </button>
                  ) : null}
                  {selected.isOwner ? (
                    <button type="button" className="kx-btn kx-btn-danger" onClick={() => deleteItem(selected)}>
                      <Trash2 size={15} /> Удалить
                    </button>
                  ) : null}
                </div>
              </>
            ) : (
              <div className="kx-details-empty">
                <Folder size={36} className="kx-icon kx-icon-folder" />
                <p>Выберите файл или папку, чтобы увидеть сведения.</p>
                <p className="kx-hint">Двойной щелчок открывает папку или файл.</p>
              </div>
            )}
          </aside>
        </div>
        {notice ? (
          <div key={notice.id} className={noticeLeaving ? 'kx-notice is-leaving' : 'kx-notice'} role="status">
            {notice.text}
          </div>
        ) : null}
        {menu
          ? createPortal(
              <div className="kx-menu" style={{ left: menu.x, top: menu.y }} role="menu" onMouseDown={(event) => event.stopPropagation()}>
                {canCreateHere ? (
                  <>
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setMenu(null)
                        setDialog({ kind: 'folder' })
                      }}
                    >
                      <FolderPlus size={16} /> Создать папку
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setMenu(null)
                        setDialog({ kind: 'file' })
                      }}
                    >
                      <FilePlus size={16} /> Создать файл
                    </button>
                  </>
                ) : null}
                {menu.itemId
                  ? (() => {
                      const target = listing.items.find((entry) => entry.id === menu.itemId)
                      if (!target?.isOwner || target.isVirtual) return null
                      return (
                        <button
                          type="button"
                          role="menuitem"
                          className="kx-menu-danger"
                          onClick={() => {
                            setMenu(null)
                            deleteItem(target)
                          }}
                        >
                          <Trash2 size={16} /> Удалить
                        </button>
                      )
                    })()
                  : null}
              </div>,
              document.body
            )
          : null}
      </section>

      {dialog?.kind === 'folder' ? (
        <NewFolderDialog parentId={folderId} onClose={() => setDialog(null)} onCreated={onCreated} />
      ) : null}
      {dialog?.kind === 'file' ? (
        <NewFileDialog parentId={folderId} onClose={() => setDialog(null)} onCreated={onCreated} />
      ) : null}
      {dialog?.kind === 'access' ? (
        <AccessDialog
          item={dialog.item}
          onClose={() => setDialog(null)}
          onSaved={() => {
            setDialog(null)
            reload()
          }}
        />
      ) : null}
    </OrchSlotMain>
  )
}
