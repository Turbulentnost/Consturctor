import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { WorkflowFileItem } from '../api/types'

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

  async function download(item: WorkflowFileItem): Promise<void> {
    if (!item.downloadUrl) return
    await api.download(item.downloadUrl, item.name)
  }

  return (
    <div>
      <h1 className="page-title">Файлы</h1>
      <p className="page-subtitle">Файлы, созданные и загруженные ИИ-агентами</p>

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

      {!loading && !error && items.length > 0 && (
        <div style={{ marginTop: 24, display: 'flex', flexDirection: 'column', gap: 10 }}>
          {items.map((item) => (
            <div
              key={item.id}
              style={{
                background: '#fff',
                border: '1px solid var(--card-border)',
                borderRadius: 14,
                padding: '12px 16px',
                display: 'flex',
                alignItems: 'center',
                gap: 14
              }}
            >
              <div
                style={{
                  width: 40,
                  height: 40,
                  borderRadius: 10,
                  background: '#eef7f3',
                  color: '#06483d',
                  fontSize: 11,
                  fontWeight: 700,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}
              >
                {extIcon(item.name)}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    fontWeight: 500,
                    color: 'var(--main-text)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap'
                  }}
                >
                  {item.name}
                </div>
                <div style={{ fontSize: 12, color: 'var(--content-muted)' }}>
                  {formatSize(item.sizeBytes)}
                </div>
              </div>
              {item.downloadUrl && (
                <button
                  className="icon-btn"
                  title="Скачать файл"
                  onClick={() => download(item)}
                >
                  {'\u2913'}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
