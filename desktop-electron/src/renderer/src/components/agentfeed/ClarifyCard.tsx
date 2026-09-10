import { useEffect, useRef, useState } from 'react'
import { fileDialogFilters, fileInputAccept } from './questionArgs'
import type { PendingQuestion } from './types'

interface ClarifyCardProps {
  question: PendingQuestion
  allowFiles?: boolean
  onAnswer: (requestId: string, value: string, filePaths?: string[]) => void
}

function pathsFromFileList(list: FileList | File[] | null | undefined): string[] {
  if (!list) return []
  const files = Array.from(list)
  return files
    .map((file) => {
      try {
        return window.api.getPathForFile?.(file) || ''
      } catch {
        return ''
      }
    })
    .filter(Boolean)
}

export function ClarifyCard({
  question,
  allowFiles = false,
  onAnswer
}: ClarifyCardProps): React.JSX.Element {
  const [selected, setSelected] = useState('')
  const [useCustom, setUseCustom] = useState(question.options.length === 0)
  const [custom, setCustom] = useState('')
  const [filePaths, setFilePaths] = useState<string[]>([])
  const [fileError, setFileError] = useState('')
  const cardRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (useCustom) {
      inputRef.current?.focus()
      return
    }
    cardRef.current?.focus()
  }, [useCustom, question.requestId])

  const needsFile = Boolean(question.needsFile)
  const canAttach = allowFiles || needsFile
  const hasAnswer = Boolean(useCustom ? custom.trim() || filePaths.length : selected) || filePaths.length > 0
  const canSubmit = hasAnswer || needsFile

  const addPaths = (paths: string[]): void => {
    if (!paths.length) return
    setFileError('')
    setFilePaths((prev) => Array.from(new Set([...prev, ...paths])))
  }

  const submit = (): void => {
    const text = (useCustom ? custom.trim() : selected).trim()
    const names = filePaths.map((path) => path.split(/[\\/]/).pop()).filter(Boolean)
    const skipNote = needsFile && !filePaths.length && !text ? 'Файл не приложен' : ''
    const value = [text, names.length ? `Прикрепленные файлы: ${names.join(', ')}` : '', skipNote]
      .filter(Boolean)
      .join('\n')
    if (!value && filePaths.length === 0) return
    onAnswer(question.requestId, value, filePaths)
  }

  const pickViaDialog = async (): Promise<boolean> => {
    const paths = await window.api.openFile({
      title: needsFile ? 'Прикрепить файл для этого запуска' : 'Прикрепить файл к ответу',
      properties: ['openFile', 'multiSelections'],
      filters: fileDialogFilters(question.accept)
    })
    if (!paths.length) return false
    addPaths(paths)
    return true
  }

  const pickFiles = async (): Promise<void> => {
    setFileError('')
    try {
      await pickViaDialog()
    } catch {
      if (fileRef.current) {
        fileRef.current.click()
        return
      }
      setFileError('Не удалось открыть выбор файла. Попробуйте ещё раз.')
    }
  }

  const onHtmlFiles = (event: React.ChangeEvent<HTMLInputElement>): void => {
    const files = event.target.files
    const paths = pathsFromFileList(files)
    event.target.value = ''
    if (paths.length) {
      addPaths(paths)
      return
    }
    if (!files?.length) return
    void pickViaDialog()
      .then((opened) => {
        if (!opened) setFileError('Не удалось прочитать файл. Выберите его ещё раз.')
      })
      .catch(() => {
        setFileError('Не удалось прочитать файл. Выберите его ещё раз.')
      })
  }

  const addClipboardImage = async (event?: React.ClipboardEvent): Promise<boolean> => {
    const fromList = pathsFromFileList(event?.clipboardData?.files)
    if (fromList.length) {
      event?.preventDefault()
      addPaths(fromList)
      return true
    }
    try {
      const path = (await window.api.saveClipboardImage?.()) || ''
      if (!path) return false
      event?.preventDefault()
      addPaths([path])
      return true
    } catch {
      return false
    }
  }

  const onCardKeyDown = (event: React.KeyboardEvent<HTMLDivElement>): void => {
    if (event.key !== 'Enter' || event.shiftKey) return
    if (event.target instanceof HTMLTextAreaElement) return
    if (!canSubmit) return
    event.preventDefault()
    submit()
  }

  const title = question.question.trim() || 'Агенту нужно уточнение'
  const kicker = question.context?.trim() || 'Агенту нужно уточнение'
  const blockTitle = question.blockTitle?.trim() || ''

  return (
    <div
      className="clarify"
      ref={cardRef}
      tabIndex={0}
      onKeyDown={onCardKeyDown}
      onDragOver={
        canAttach
          ? (event) => {
              event.preventDefault()
            }
          : undefined
      }
      onDrop={
        canAttach
          ? (event) => {
              event.preventDefault()
              const paths = pathsFromFileList(event.dataTransfer.files)
              if (paths.length) addPaths(paths)
            }
          : undefined
      }
      onPaste={
        canAttach
          ? (event) => {
              void addClipboardImage(event)
            }
          : undefined
      }
    >
      <div className="clarify-kicker">{kicker}</div>
      {blockTitle ? <div className="clarify-block">{blockTitle}</div> : null}
      <div className="clarify-question">{title}</div>

      {question.options.length > 0 && (
        <div className="clarify-options">
          {question.options.map((option) => {
            const active = !useCustom && selected === option
            return (
              <button
                key={option}
                type="button"
                className={active ? 'clarify-option active' : 'clarify-option'}
                onClick={() => {
                  setSelected(option)
                  setUseCustom(false)
                }}
              >
                <span className={active ? 'clarify-radio on' : 'clarify-radio'} />
                <span className="clarify-option-label">{option}</span>
              </button>
            )
          })}
        </div>
      )}

      <div className={useCustom ? 'clarify-custom-row on' : 'clarify-custom-row'}>
        <button
          type="button"
          className={useCustom ? 'clarify-option other active' : 'clarify-option other'}
          onClick={() => {
            setUseCustom(true)
            setSelected('')
            inputRef.current?.focus()
          }}
        >
          <span className={useCustom ? 'clarify-radio on' : 'clarify-radio'} />
          <span className="clarify-option-label">Свой вариант</span>
        </button>
        <input
          ref={inputRef}
          className="clarify-custom-input"
          placeholder="Напишите свой ответ"
          value={custom}
          onFocus={() => {
            setUseCustom(true)
            setSelected('')
          }}
          onChange={(e) => {
            setCustom(e.target.value)
            setUseCustom(true)
            setSelected('')
          }}
          onPaste={
            canAttach
              ? (event) => {
                  void addClipboardImage(event)
                }
              : undefined
          }
        />
      </div>

      {canAttach && (
        <div className="clarify-files">
          <input
            ref={fileRef}
            className="clarify-file-input"
            type="file"
            multiple
            accept={fileInputAccept(question.accept)}
            onChange={onHtmlFiles}
          />
          <button type="button" className="clarify-attach" onClick={() => void pickFiles()}>
            {needsFile ? 'Прикрепить файл для этого запуска' : 'Прикрепить файл'}
          </button>
          {needsFile && (
            <span className="clarify-file-hint">
              Необязательно. Word, Excel, PDF, изображения. Сканы и фото читаются через OCR.
              Можно вставить скриншот (Ctrl+V) или нажать Далее без файла.
            </span>
          )}
          {fileError ? <span className="clarify-file-error">{fileError}</span> : null}
          {filePaths.map((path) => (
            <button
              key={path}
              type="button"
              className="clarify-file-name"
              title="Убрать файл"
              onClick={() => setFilePaths((prev) => prev.filter((item) => item !== path))}
            >
              {path.split(/[\\/]/).pop() || path}
              <span aria-hidden="true"> ×</span>
            </button>
          ))}
        </div>
      )}

      <div className="clarify-actions">
        <button className="clarify-submit" onClick={submit} disabled={!canSubmit}>
          Далее
        </button>
      </div>
    </div>
  )
}
