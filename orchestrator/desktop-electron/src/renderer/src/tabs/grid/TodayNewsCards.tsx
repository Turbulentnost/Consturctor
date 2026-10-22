import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, FileText, ListChecks, X } from 'lucide-react'
import { api, type TodayNews } from '../../api/client'
import { formatPlatformDateTime } from '../../workplace/platformTasks'
import { bentoColumns, bentoPages, type BentoCell } from '../../workplace/newsBento'

const KIND_LABEL: Record<TodayNews['kind'], string> = {
  process_change: 'Изменение процесса',
  info: 'Новость'
}

function tasksLabel(count: number): string {
  const last = count % 10
  const lastTwo = count % 100
  let word = 'задач'
  if (last === 1 && lastTwo !== 11) word = 'задача'
  else if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) word = 'задачи'
  return `Поставлено: ${count} ${word}`
}

function useWidth(ref: React.RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const node = ref.current
    if (!node) return
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(node)
    setWidth(node.getBoundingClientRect().width)
    return () => observer.disconnect()
  }, [ref])
  return width
}

/** Новости «Сегодня» Bento-сеткой: до двух строк, фото крупнее, лишнее — на следующей странице. */
export function TodayNewsCards(): React.JSX.Element | null {
  const [items, setItems] = useState<TodayNews[]>([])
  const [images, setImages] = useState<Record<string, string>>({})
  const [page, setPage] = useState(0)
  const [busy, setBusy] = useState('')
  const box = useRef<HTMLElement | null>(null)
  const width = useWidth(box)

  useEffect(() => {
    let alive = true
    const load = (): void => {
      void api
        .listTodayNews()
        .then((rows) => {
          if (alive) setItems(rows)
        })
        .catch(() => {
          if (alive) setItems([])
        })
    }
    load()
    const timer = window.setInterval(load, 60_000)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [])

  useEffect(() => {
    for (const item of items) {
      if (!item.imageUrl || item.id in images) continue
      void api.fetchDataUrl(item.imageUrl).then((dataUrl) =>
        setImages((prev) => ({ ...prev, [item.id]: dataUrl || '' }))
      )
    }
  }, [items, images])

  const visible = useMemo(() => items.filter((item) => new Date(item.showUntil).getTime() > Date.now()), [items])
  const cols = bentoColumns(width || 1200)
  const pages = useMemo(
    () => bentoPages(visible.map((item) => ({ id: item.id, photo: Boolean(item.imageUrl) })), cols),
    [visible, cols]
  )

  useEffect(() => {
    setPage((current) => Math.min(current, Math.max(0, pages.length - 1)))
  }, [pages.length])

  const dismiss = (id: string): void => {
    setBusy(id)
    void api
      .dismissTodayNews(id)
      .then(() => setItems((prev) => prev.filter((item) => item.id !== id)))
      .catch(() => undefined)
      .finally(() => setBusy(''))
  }

  const byId = new Map(visible.map((item) => [item.id, item]))
  const current = pages[Math.min(page, pages.length - 1)]

  return (
    <section ref={box} className={visible.length ? 'ht-news' : 'ht-news is-empty'} aria-label="Новости">
      {current ? (
        <>
          <div
            className={`ht-news-grid rows-${current.rows}`}
            style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
          >
            {current.cells.map((cell) => {
              const item = byId.get(cell.id)
              return item ? (
                <NewsCard
                  key={item.id}
                  item={item}
                  cell={cell}
                  image={images[item.id]}
                  busy={busy === item.id}
                  onDismiss={() => dismiss(item.id)}
                />
              ) : null
            })}
          </div>
          {pages.length > 1 ? (
            <div className="ht-news-pager">
              <button
                type="button"
                className="ht-metrics-arrow"
                aria-label="Предыдущие новости"
                disabled={page === 0}
                onClick={() => setPage((value) => Math.max(0, value - 1))}
              >
                <ChevronLeft size={16} />
              </button>
              <span>
                {page + 1} / {pages.length}
              </span>
              <button
                type="button"
                className="ht-metrics-arrow"
                aria-label="Следующие новости"
                disabled={page >= pages.length - 1}
                onClick={() => setPage((value) => Math.min(pages.length - 1, value + 1))}
              >
                <ChevronRight size={16} />
              </button>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  )
}

function NewsCard({
  item,
  cell,
  image,
  busy,
  onDismiss
}: {
  item: TodayNews
  cell: BentoCell
  image: string | undefined
  busy: boolean
  onDismiss: () => void
}): React.JSX.Element {
  const photo = Boolean(item.imageUrl)
  return (
    <article
      className={`ht-news-card size-${cell.size} is-${item.kind}${photo ? ' has-photo' : ''}`}
      style={{
        gridColumn: `${cell.col} / span ${cell.colSpan}`,
        gridRow: `${cell.row} / span ${cell.rowSpan}`
      }}
    >
      {photo ? (
        <div className="ht-news-photo" style={image ? { backgroundImage: `url("${image}")` } : undefined} aria-hidden />
      ) : null}
      <div className="ht-news-content">
        <header>
          <span className="ht-news-kicker">{KIND_LABEL[item.kind]}</span>
          <button type="button" className="ht-news-close" aria-label="Скрыть новость" disabled={busy} onClick={onDismiss}>
            <X size={14} />
          </button>
        </header>
        <h3 title={item.title}>{item.title}</h3>
        {item.body ? (
          <p className="ht-news-body" title={item.body}>
            {item.body}
          </p>
        ) : null}
        <footer>
          {item.fileName ? (
            <span title={item.fileName}>
              <FileText size={13} aria-hidden /> {item.fileName}
            </span>
          ) : null}
          {item.taskIds.length ? (
            <span>
              <ListChecks size={13} aria-hidden /> {tasksLabel(item.taskIds.length)}
            </span>
          ) : null}
          <span className="ht-news-until">до {formatPlatformDateTime(item.showUntil)}</span>
        </footer>
      </div>
    </article>
  )
}
