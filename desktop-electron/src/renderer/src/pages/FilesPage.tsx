import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { WorkflowFileItem } from '../api/types'
import { groupFileSessions, type FileSessionGroup } from './filesGrouping'

function formatSize(bytes: number): string {
  if (!bytes) return ''
  const units = ['Б', 'КБ', 'МБ', 'ГБ']
  let value = bytes
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

function extIcon(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() ?? ''
  const map: Record<string, string> = {
    pdf: 'PDF',
    docx: 'DOC',
    doc: 'DOC',
    xlsx: 'XLS',
    xls: 'XLS',
    txt: 'TXT',
    md: 'MD',
    csv: 'CSV',
    json: 'JSON'
  }
  return map[ext] ?? ext.toUpperCase().slice(0, 4) ?? 'FILE'
}

function originLabel(item: WorkflowFileItem): string {
  return item.source === 'agent' ? 'создан агентом' : 'загружен вами'
}

function FileRow({
  item,
  onDownload
}: {
  item: WorkflowFileItem
  onDownload: (item: WorkflowFileItem) => void
}): React.JSX.Element {
  const meta = [formatSize(item.sizeBytes), originLabel(item)].filter(Boolean).join(' · ')
  return (
    <div className="files-row">
      <div className="files-ext">{extIcon(item.name)}</div>
      <div className="files-row-body">
        <div className="files-row-name">{item.name || 'file'}</div>
        <div className="files-row-meta">{meta}</div>
      </div>
      {item.downloadUrl && (
        <button className="icon-btn" title="Скачать файл" onClick={() => onDownload(item)}>
          {'\u2913'}
        </button>
      )}
    </div>
  )
}

function SessionBlock({
  group,
  onDownload
}: {
  group: FileSessionGroup
  onDownload: (item: WorkflowFileItem) => void
}): React.JSX.Element {
  const title = group.stamp ? `${group.title} · ${group.stamp}` : group.title
  return (
    <section className="files-session">
      <h2 className="files-session-title">{title}</h2>
      <p className="files-session-agent">{group.agentTitle}</p>
      {group.ours.length > 0 && (
        <>
          <div className="files-source-label">Сформировано нами · {group.ours.length}</div>
          <div className="files-session-list">
            {group.ours.map((item) => (
              <FileRow key={item.id} item={item} onDownload={onDownload} />
            ))}
          </div>
        </>
      )}
      {group.agent.length > 0 && (
        <>
          <div className="files-source-label">Создано агентом · {group.agent.length}</div>
          <div className="files-session-list">
            {group.agent.map((item) => (
              <FileRow key={item.id} item={item} onDownload={onDownload} />
            ))}
          </div>
        </>
      )}
    </section>
  )
}

export function FilesPage(): React.JSX.Element {
  const [items, setItems] = useState<WorkflowFileItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const list = await api.listPlatformFiles()
        if (alive) setItems(list)
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

  const groups = useMemo(() => groupFileSessions(items), [items])

  async function download(item: WorkflowFileItem): Promise<void> {
    if (!item.downloadUrl) return
    await api.download(item.downloadUrl, item.name)
  }

  return (
    <div>
      <h1 className="page-title">Файлы</h1>
      <p className="page-subtitle">
        Документы по сессиям формирования и запускам агента: отдельно наши файлы и файлы агента.
      </p>

      {loading && (
        <div className="center-state">
          <div className="spinner" />
          <div>Загружаем файлы...</div>
        </div>
      )}
      {error && <div className="placeholder-card">{error}</div>}
      {!loading && !error && items.length === 0 && (
        <div className="placeholder-card">Пока нет файлов</div>
      )}

      {!loading && !error && groups.length > 0 && (
        <div className="files-sessions">
          {groups.map((group) => (
            <SessionBlock key={group.key} group={group} onDownload={download} />
          ))}
        </div>
      )}
    </div>
  )
}
