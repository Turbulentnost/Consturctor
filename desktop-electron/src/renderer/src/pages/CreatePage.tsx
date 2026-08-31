import { useState } from 'react'
import { api } from '../api/client'
import { ApiError, type RegulationParseResult } from '../api/types'
import uploadIcon from '../assets/create-upload.png'
import aiIcon from '../assets/create-ai.png'

const ALLOWED = ['.docx', '.doc', '.pdf', '.xlsx', '.md', '.txt']

interface CreatePageProps {
  onRegulationParsed: (result: RegulationParseResult) => void
  onStartRegulationChat: () => void
  hasRegulationDraft?: boolean
  regulationDraftBusy?: boolean
  onResumeRegulationDraft?: () => void
  onRestartRegulationDraft?: () => void
}

export function CreatePage({
  onRegulationParsed,
  onStartRegulationChat,
  hasRegulationDraft = false,
  regulationDraftBusy = false,
  onResumeRegulationDraft,
  onRestartRegulationDraft
}: CreatePageProps): React.JSX.Element {
  const [hover, setHover] = useState(false)
  const [fileName, setFileName] = useState('')
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)

  async function pickFile(): Promise<void> {
    const paths = await window.api.openFile({
      title: 'Выберите регламент',
      filters: [{ name: 'Документы', extensions: ['docx', 'doc', 'pdf', 'xlsx', 'md', 'txt'] }],
      properties: ['openFile']
    })
    if (paths.length) await handleFile(paths[0])
  }

  function isAllowed(path: string): boolean {
    const lower = path.toLowerCase()
    return ALLOWED.some((ext) => lower.endsWith(ext))
  }

  async function handleFile(path: string): Promise<void> {
    if (!isAllowed(path)) {
      setStatus('Допустимы только DOC, DOCX, PDF, XLSX, MD, TXT.')
      return
    }
    setFileName(path.split(/[\\/]/).pop() ?? path)
    setBusy(true)
    setStatus('Распознаём документ и размечаем, какие блоки к кому относятся...')
    try {
      const result = await api.uploadRegulation(path)
      setStatus('')
      onRegulationParsed(result)
    } catch (err) {
      setStatus(err instanceof ApiError ? err.message : 'Ошибка распознавания')
    } finally {
      setBusy(false)
    }
  }

  function onDrop(e: React.DragEvent): void {
    e.preventDefault()
    e.stopPropagation()
    setHover(false)
    const file = e.dataTransfer.files?.[0]
    if (!file) {
      setStatus('Не удалось прочитать файл')
      return
    }
    const path = window.api.getPathForFile(file)
    if (!path) {
      setStatus('Не удалось получить путь к файлу. Выберите его через «выберите на компьютере».')
      return
    }
    void handleFile(path)
  }

  return (
    <div className="create-page">
      <div>
        <h1 className="page-title">Создать ИИ-агента</h1>
        <p className="page-subtitle">
          Начните с готового регламента или создайте его вместе с ИИ
        </p>
      </div>

      <div className="create-cards">
        <div className="option-card">
          <div className="option-badge-row" />
          <div className="option-icon">
            <img src={uploadIcon} alt="" />
          </div>
          <h3>Загрузить регламент</h3>
          <p>Прикрепите готовый документ — мы проанализируем его и спланируем работу агента</p>
          <div className="option-card-action">
            <div
              className={hover ? 'dropzone hover' : 'dropzone'}
              onClick={pickFile}
              onDragOver={(e) => {
                e.preventDefault()
                setHover(true)
              }}
              onDragLeave={() => setHover(false)}
              onDrop={onDrop}
              style={{ cursor: busy ? 'default' : 'pointer' }}
            >
              <div className="dz-title">{fileName ? 'Файл выбран' : 'Перетащите файл сюда'}</div>
              <div className="dz-hint">
                или{' '}
                <a
                  onClick={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    void pickFile()
                  }}
                >
                  выберите на компьютере
                </a>
              </div>
              <div className="dz-formats">DOC, DOCX, PDF, XLSX, MD, TXT</div>
              {fileName && <div className="dz-file">{fileName}</div>}
            </div>
          </div>
        </div>

        <div className="option-card">
          <div className="option-badge-row">
            <div className="badge-pill">Нет регламента?</div>
          </div>
          <div className="option-icon">
            <img src={aiIcon} alt="" />
          </div>
          <h3>Создать с помощью ИИ</h3>
          <div className="option-card-mid">
            <p>Ответьте на несколько вопросов — ИИ поможет оформить регламент и подготовить агента</p>
            {hasRegulationDraft ? (
              <div className="create-ai-actions">
                <p className="create-ai-hint">
                  Черновик и история вопросов сохранены. Можно продолжить с того же места.
                </p>
                <button
                  className="btn-primary"
                  onClick={onResumeRegulationDraft || onStartRegulationChat}
                  disabled={busy}
                >
                  Продолжить черновик
                </button>
                <button
                  className="btn-ghost-dark"
                  type="button"
                  onClick={onRestartRegulationDraft}
                  disabled={busy || regulationDraftBusy}
                >
                  Начать заново
                </button>
              </div>
            ) : (
              <button className="btn-primary" onClick={onStartRegulationChat} disabled={busy}>
                Создать регламент
              </button>
            )}
          </div>
        </div>
      </div>

      {status && <div className="status-line">{status}</div>}

      <p className="create-footer">
        Регламент можно будет проверить и отредактировать перед созданием агента
      </p>
    </div>
  )
}
