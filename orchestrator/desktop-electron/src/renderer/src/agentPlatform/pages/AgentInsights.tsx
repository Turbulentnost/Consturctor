import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { apiGet } from '../api/client'
import type {
  AgentProcess,
  ContextItem,
  ContextItemType,
  ContextSnapshot,
  MetricSample,
  MetricsChunk,
  SessionContext,
  SpikeEvent,
  SpikeMark,
  TraceChunk,
  TraceEntry
} from '../api/types'
import { ChevronDownIcon } from '../components/Icons'
import { Segmented } from '../components/Segmented'
type InsightTab = 'performance' | 'interaction' | 'context'

const TABS: { key: InsightTab; label: string }[] = [
  { key: 'performance', label: 'Производительность' },
  { key: 'interaction', label: 'Взаимодействие' },
  { key: 'context', label: 'Контекст' }
]

const RUNNING_POLL_MS = 1000
const IDLE_POLL_MS = 5000
const CONTEXT_POLL_MS = 1000
const POINT_SPACING_PX = 26
const METRICS_KEEP = 7200
const GAP_MS = 3000
const STICK_PX = 60
const CHARS_PER_TOKEN = 4

interface InsightsProps {
  sessionId: string | null
  running: boolean
  turns: number
  remote?: boolean
}

function base(sessionId: string): string {
  return `/api/v1/platform/sessions/${encodeURIComponent(sessionId)}`
}

function clockTime(value: string | number, withMs = false): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const time = date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  return withMs ? `${time}.${String(date.getMilliseconds()).padStart(3, '0')}` : time
}

function tokens(chars: number): string {
  const value = Math.round(chars / CHARS_PER_TOKEN)
  return value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value)
}

/** Опрос, пока вкладка открыта: чаще, пока агент работает. */
function usePoll(load: (() => Promise<void>) | null, delay: number, deps: unknown[]): void {
  useEffect(() => {
    if (!load) return
    let alive = true
    let timer = 0
    const tick = async (): Promise<void> => {
      try {
        await load()
      } catch {
        // следующая попытка по таймеру
      }
      if (alive) timer = window.setTimeout(() => void tick(), delay)
    }
    void tick()
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, deps)
}

/* ---------- Производительность ---------- */

interface Series {
  key: 'cpu' | 'ram' | 'gpu' | 'disk' | 'gen'
  title: string
  color: string
  value: (sample: MetricSample) => number | null
  detail?: (sample: MetricSample) => string
  format: (value: number) => string
  scale: (peak: number) => number
}

function formatPercent(value: number): string {
  return `${value.toFixed(value < 10 ? 2 : 1)}%`
}

function formatRate(mb: number): string {
  if (!Number.isFinite(mb) || mb < 0.005) return '0 КБ/с'
  if (mb < 1) return `${Math.round(mb * 1024)} КБ/с`
  if (mb < 10) return `${mb.toFixed(2)} МБ/с`
  return `${mb.toFixed(mb < 100 ? 1 : 0)} МБ/с`
}

function scaleMax(peak: number): number {
  for (const step of [1, 2, 5, 10, 25, 50, 100]) if (peak <= step * 0.9) return step
  return 100
}

function scaleRate(peak: number): number {
  for (const step of [0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 25, 50, 100, 250, 500]) {
    if (peak <= step * 0.9) return step
  }
  return Math.max(peak, 0.05)
}

const SERIES: Series[] = [
  { key: 'cpu', title: 'ЦП', color: 'var(--accent)', value: (s) => s.cpu, format: formatPercent, scale: scaleMax },
  {
    key: 'ram',
    title: 'ОЗУ',
    color: 'var(--ok)',
    value: (s) => s.ram,
    detail: (s) => `${s.ram_mb.toFixed(0)} МБ`,
    format: formatPercent,
    scale: scaleMax
  },
  { key: 'gpu', title: 'ГП', color: 'var(--warn)', value: (s) => s.gpu, format: formatPercent, scale: scaleMax },
  {
    key: 'disk',
    title: 'SSD',
    color: '#a78bfa',
    value: (s) => s.disk ?? 0,
    detail: (s) => `чтение ${formatRate(s.disk_read ?? 0)} · запись ${formatRate(s.disk_write ?? 0)}`,
    format: formatRate,
    scale: scaleRate
  }
]

function formatTokenRate(value: number): string {
  return `${value.toFixed(value < 10 ? 1 : 0)} ток/с`
}

function scaleTokenRate(peak: number): number {
  for (const step of [10, 25, 50, 100, 200, 400, 800, 1600]) if (peak <= step * 0.9) return step
  return Math.max(peak, 10)
}

const GENERATION: Series = {
  key: 'gen',
  title: 'Генерация',
  color: '#f472b6',
  value: (s) => s.gen ?? null,
  format: formatTokenRate,
  scale: scaleTokenRate
}

interface GenerationStats {
  tokens: number
  seconds: number
  /** Токены всех ходов — точные из итога SDK, а не оценка по тексту. */
  exact: boolean
}

/** Средняя скорость: токены ходов делятся на секунды, когда модель что-то выдавала, без ожидания инструментов. */
function generationStats(samples: MetricSample[], exact: Record<string, number>): GenerationStats {
  const seconds = new Map<number, number>()
  const estimated = new Map<number, number>()
  samples.forEach((sample, index) => {
    if (!sample.gen) return
    const previous = samples[index - 1]
    const step = previous && previous.turn === sample.turn ? Math.min(sample.t - previous.t, 2000) / 1000 : 1
    seconds.set(sample.turn, (seconds.get(sample.turn) ?? 0) + step)
    estimated.set(sample.turn, (estimated.get(sample.turn) ?? 0) + sample.gen * step)
  })
  let tokens = 0
  let total = 0
  let allExact = seconds.size > 0
  for (const [turn, spent] of seconds) {
    total += spent
    const known = exact[String(turn)]
    if (known) tokens += known
    else {
      tokens += estimated.get(turn) ?? 0
      allExact = false
    }
  }
  return { tokens, seconds: total, exact: allExact }
}

function generationSummary(stats: GenerationStats, current: number | null, running: boolean): { value: string; detail: string } {
  const average = stats.seconds ? stats.tokens / stats.seconds : 0
  const approx = stats.exact ? '' : '≈ '
  const spent = `${Math.round(stats.tokens)} токенов за ${Math.round(stats.seconds)} с генерации`
  if (running) {
    return {
      value: current === null ? '—' : `≈ ${formatTokenRate(current)}`,
      detail: stats.seconds ? `в среднем ${approx}${formatTokenRate(average)}` : 'ждём первых токенов'
    }
  }
  return {
    value: stats.seconds ? `в среднем ${approx}${formatTokenRate(average)}` : '—',
    detail: stats.seconds ? spent : 'генерации не было'
  }
}

function nearestSample(samples: MetricSample[], ratio: number): number {
  const start = samples[0].t
  const target = start + ratio * Math.max(1, samples[samples.length - 1].t - start)
  let low = 0
  let high = samples.length - 1
  while (low < high) {
    const mid = (low + high) >> 1
    if (samples[mid].t < target) low = mid + 1
    else high = mid
  }
  if (low > 0 && target - samples[low - 1].t <= samples[low].t - target) return low - 1
  return low
}

function spikeText(mark: SpikeMark): string {
  const series = SERIES.find((item) => item.key === mark.metric)
  return `${series?.title ?? mark.metric} ${series ? series.format(mark.value) : mark.value}`
}

interface SpikeRow {
  spike: SpikeEvent
  mark: SpikeMark
  series: Series
  /** Сила скачка внутри своей метрики: 0…1 от самого резкого роста. */
  strength: number
}

function spikeRows(spikes: SpikeEvent[]): SpikeRow[] {
  const rows = spikes.flatMap((spike) =>
    spike.marks.flatMap((mark) => {
      const series = SERIES.find((item) => item.key === mark.metric)
      return series ? [{ spike, mark, series, strength: 0 }] : []
    })
  )
  const strongest = new Map<string, number>()
  for (const row of rows) {
    const rise = row.mark.value - row.mark.baseline
    strongest.set(row.series.key, Math.max(strongest.get(row.series.key) ?? 0, rise))
  }
  for (const row of rows) {
    row.strength = (row.mark.value - row.mark.baseline) / Math.max(strongest.get(row.series.key) ?? 1, 1e-9)
  }
  return rows
}

type SpikeSort = 'time' | 'strength'

function SpikeList({
  spikes,
  pinned,
  onPin
}: {
  spikes: SpikeEvent[]
  pinned: SpikeEvent | null
  onPin: (spike: SpikeEvent | null) => void
}): React.JSX.Element {
  const [metric, setMetric] = useState<Series['key'] | 'all'>('all')
  const [sort, setSort] = useState<SpikeSort>('time')
  const rows = useMemo(() => spikeRows(spikes), [spikes])
  const counts = new Map<Series['key'], number>()
  for (const row of rows) counts.set(row.series.key, (counts.get(row.series.key) ?? 0) + 1)
  const visible = rows
    .filter((row) => metric === 'all' || row.series.key === metric)
    .sort((a, b) => (sort === 'time' ? b.spike.t - a.spike.t : b.strength - a.strength))

  return (
    <section className="ins-spikes" aria-label="Скачки">
      <header className="ins-spikes-head">
        <h4>
          Скачки <b>{rows.length}</b>
        </h4>
        <div className="ins-spikes-sort" role="group" aria-label="Сортировка">
          <button type="button" className={sort === 'time' ? 'on' : ''} onClick={() => setSort('time')}>
            новые
          </button>
          <button type="button" className={sort === 'strength' ? 'on' : ''} onClick={() => setSort('strength')}>
            сильные
          </button>
        </div>
      </header>
      <div className="ins-spikes-filter" role="group" aria-label="Метрика">
        <button type="button" className={metric === 'all' ? 'on' : ''} onClick={() => setMetric('all')}>
          Все <span>{rows.length}</span>
        </button>
        {SERIES.filter((item) => counts.get(item.key)).map((item) => (
          <button
            key={item.key}
            type="button"
            className={metric === item.key ? 'on' : ''}
            onClick={() => setMetric(metric === item.key ? 'all' : item.key)}
          >
            <i style={{ background: item.color }} />
            {item.title} <span>{counts.get(item.key)}</span>
          </button>
        ))}
      </div>
      <ol className="ins-spike-list">
        {visible.map((row) => {
          const on = pinned?.t === row.spike.t
          return (
            <li key={`${row.spike.t}:${row.series.key}`}>
              <button
                type="button"
                className={on ? 'ins-spike-row on' : 'ins-spike-row'}
                aria-pressed={on}
                onClick={() => onPin(on ? null : row.spike)}
              >
                <time>{clockTime(row.spike.t)}</time>
                <span className="ins-spike-metric">
                  <i style={{ background: row.series.color }} />
                  {row.series.title}
                </span>
                <span className="ins-spike-value">{row.series.format(row.mark.value)}</span>
                <span className="ins-spike-bar" aria-hidden="true">
                  <span style={{ width: `${Math.max(6, row.strength * 100)}%`, background: row.series.color }} />
                </span>
                <span className="ins-spike-rise">
                  с {row.series.format(row.mark.baseline)}
                </span>
              </button>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

function Chart({
  samples,
  series,
  cursor,
  spikes,
  pinnedT,
  summary
}: {
  samples: MetricSample[]
  series: Series
  cursor: number | null
  spikes: SpikeEvent[]
  pinnedT: number | null
  /** Своя подпись вместо последнего значения: у генерации — текущая или средняя скорость. */
  summary?: { value: string; detail: string }
}): React.JSX.Element {
  const values = samples.map(series.value)
  const known = values.filter((value): value is number => value !== null)
  const last = known.length ? known[known.length - 1] : null
  const peak = known.length ? Math.max(...known) : 0
  const top = series.scale(peak)
  const start = samples[0]?.t ?? 0
  const span = Math.max(1, (samples[samples.length - 1]?.t ?? 0) - start)
  const at = cursor === null ? null : values[cursor]
  const guideX = cursor === null ? 0 : ((samples[cursor].t - start) / span) * 100
  const guideY = at === null ? null : 100 - (Math.min(at, top) / top) * 100

  const segments: [number, number][][] = []
  let segment: [number, number][] = []
  samples.forEach((sample, index) => {
    const value = values[index]
    const gap = index > 0 && sample.t - samples[index - 1].t > GAP_MS
    if (value === null || gap) {
      if (segment.length) segments.push(segment)
      segment = []
      if (value === null) return
    }
    segment.push([((sample.t - start) / span) * 100, 100 - (Math.min(value, top) / top) * 100])
  })
  if (segment.length) segments.push(segment)
  const shapes = segments.map((points) => {
    const line = points.map(([x, y], index) => `${index ? 'L' : 'M'}${x.toFixed(2)},${y.toFixed(2)}`).join('')
    const first = points[0][0].toFixed(2)
    const end = points[points.length - 1][0].toFixed(2)
    return { line, area: `${line}L${end},100L${first},100Z` }
  })

  const latest = samples[samples.length - 1]
  return (
    <div className="ins-chart" data-series={series.key}>
      <div className="ins-chart-head">
        <span className="ins-chart-title">
          <i style={{ background: series.color }} />
          {series.title}
        </span>
        <strong>{summary ? summary.value : last === null ? '—' : series.format(last)}</strong>
        {summary ? (
          <span className="ins-chart-detail">{summary.detail}</span>
        ) : latest && series.detail ? (
          <span className="ins-chart-detail">{series.detail(latest)}</span>
        ) : null}
        <span className="ins-chart-peak">пик {known.length ? series.format(peak) : '—'}</span>
      </div>
      <div className="ins-chart-box">
        <span className="ins-chart-scale">{series.format(top)}</span>
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          <line x1="0" y1="50" x2="100" y2="50" className="ins-grid" />
          {shapes.map((shape, index) => (
            <g key={index}>
              <path d={shape.area} fill={series.color} className="ins-area" />
              <path d={shape.line} stroke={series.color} className="ins-line" />
            </g>
          ))}
        </svg>
        {cursor !== null ? (
          <>
            <span className="ins-guide" style={{ left: `${guideX}%` }} />
            {guideY !== null ? <span className="ins-guide-y" style={{ top: `${guideY}%` }} /> : null}
            {guideY !== null ? (
              <span className="ins-guide-dot" style={{ left: `${guideX}%`, top: `${guideY}%`, background: series.color }} />
            ) : null}
            {at !== null ? (
              <span className={guideX > 72 ? 'ins-guide-label left' : 'ins-guide-label'} style={{ left: `${guideX}%` }}>
                {series.format(at)}
              </span>
            ) : null}
          </>
        ) : null}
        {spikes.map((spike) => {
          const mark = spike.marks.find((item) => item.metric === series.key)
          if (!mark) return null
          const x = ((spike.t - start) / span) * 100
          if (x < 0 || x > 100) return null
          return (
            <span
              key={spike.t}
              className={spike.t === pinnedT ? 'ins-spike on' : 'ins-spike'}
              style={{ left: `${x}%`, background: series.color }}
            />
          )
        })}
      </div>
    </div>
  )
}

function Performance({
  sessionId,
  running,
  remote
}: {
  sessionId: string
  running: boolean
  remote: boolean
}): React.JSX.Element {
  const [samples, setSamples] = useState<MetricSample[]>([])
  const [processes, setProcesses] = useState<AgentProcess[]>([])
  const [info, setInfo] = useState<Pick<MetricsChunk, 'cpu_count' | 'ram_total_mb' | 'gpu_available'> | null>(null)
  const [spikes, setSpikes] = useState<SpikeEvent[]>([])
  const [outputTokens, setOutputTokens] = useState<Record<string, number>>({})
  const [pinned, setPinned] = useState<SpikeEvent | null>(null)
  const [cursor, setCursor] = useState<{ key: Series['key']; index: number } | null>(null)
  const lastT = useRef(0)

  useEffect(() => {
    lastT.current = 0
    setSamples([])
    setProcesses([])
    setSpikes([])
    setOutputTokens({})
    setPinned(null)
    setCursor(null)
  }, [sessionId])

  usePoll(
    async () => {
      const chunk = await apiGet<MetricsChunk>(`${base(sessionId)}/metrics?since=${lastT.current}`)
      setInfo({ cpu_count: chunk.cpu_count, ram_total_mb: chunk.ram_total_mb, gpu_available: chunk.gpu_available })
      setProcesses(chunk.processes)
      setSpikes(chunk.spikes ?? [])
      setOutputTokens(chunk.output_tokens ?? {})
      if (chunk.samples.length) {
        lastT.current = Math.max(lastT.current, chunk.samples[chunk.samples.length - 1].t)
        setSamples((current) => {
          const after = current.length ? current[current.length - 1].t : -1
          const fresh = chunk.samples.filter((sample) => sample.t > after)
          return fresh.length ? [...current, ...fresh].slice(-METRICS_KEEP) : current
        })
      }
    },
    running ? RUNNING_POLL_MS : IDLE_POLL_MS,
    [sessionId, running]
  )

  if (!samples.length) {
    return (
      <p className="ins-empty">
        {remote
          ? 'Показатели с того компьютера попадают в базу после каждого ответа агента. Для этого запуска их пока нет.'
          : running
            ? 'Снимаем первые показатели…'
            : 'Показатели снимаются, пока агент работает. У этого запуска их нет.'}
      </p>
    )
  }

  const machine = info && !info.gpu_available ? SERIES.filter((item) => item.key !== 'gpu') : SERIES
  const measured = samples.some((sample) => sample.gen !== undefined && sample.gen !== null)
  const series = measured ? [GENERATION, ...machine] : machine
  const lastGen = samples[samples.length - 1].gen
  const generation = measured
    ? generationSummary(generationStats(samples, outputTokens), lastGen ?? null, running)
    : undefined
  const first = samples[0]
  const last = samples[samples.length - 1]
  const aim = (event: React.MouseEvent<HTMLDivElement>): void => {
    const boxes = [...event.currentTarget.querySelectorAll<HTMLElement>('.ins-chart-box')]
    const y = event.clientY
    let plot: HTMLElement | null = null
    let distance = Infinity
    for (const box of boxes) {
      const rect = box.getBoundingClientRect()
      const gap = y < rect.top ? rect.top - y : y > rect.bottom ? y - rect.bottom : 0
      if (gap < distance) {
        distance = gap
        plot = box
      }
    }
    const rect = plot?.getBoundingClientRect()
    const key = plot?.closest<HTMLElement>('.ins-chart')?.dataset.series
    const ratio = rect ? (event.clientX - rect.left) / rect.width : -1
    if (!plot || !rect || !key || distance > 48 || ratio < 0 || ratio > 1) {
      setCursor(null)
      return
    }
    setCursor({ key: key as Series['key'], index: nearestSample(samples, ratio) })
  }
  const hoveredSpike = cursor ? (spikes.find((spike) => spike.t === samples[cursor.index]?.t) ?? null) : null
  const focused = hoveredSpike ?? pinned
  const rows = focused ? focused.processes : processes
  return (
    <div className="ins-perf" onMouseMove={aim} onMouseLeave={() => setCursor(null)}>
      <p className="ins-note">
        Все процессы агента: раннер Cursor SDK, MCP-сервер и запущенные им команды. Проценты ЦП, ОЗУ и ГП — от всего
        компьютера{info ? ` (${info.cpu_count} потоков ЦП, ${(info.ram_total_mb / 1024).toFixed(1)} ГБ ОЗУ)` : ''}. SSD —
        скорость чтения и записи этих процессов. Точки сверху — скачки относительно уровня перед ними: более сильный
        следующий не убирает предыдущие.
        {measured
          ? ' Генерация — сколько токенов в секунду модель выдаёт в ответ, размышления и вызовы инструментов: пока агент работает, это оценка по тексту. Средняя — точные выходные токены из итога хода, делённые на время, когда шла генерация.'
          : ''}
      </p>
      {series.map((item) => (
        <Chart
          key={item.key}
          samples={samples}
          series={item}
          cursor={cursor?.key === item.key ? cursor.index : null}
          spikes={spikes}
          pinnedT={pinned?.t ?? null}
          summary={item.key === 'gen' ? generation : undefined}
        />
      ))}
      <div className="ins-axis">
        <span>{clockTime(first.t)}</span>
        <span>{cursor === null ? '' : clockTime(samples[cursor.index].t)}</span>
        <span>{clockTime(last.t)}</span>
      </div>
      {spikes.length ? <SpikeList spikes={spikes} pinned={pinned} onPin={setPinned} /> : null}
      <h4 className="ins-subhead">
        {focused
          ? `Процессы на скачке · ${clockTime(focused.t)} · ${focused.marks.map(spikeText).join(', ')}`
          : `Процессы ${running ? 'сейчас' : 'в конце запуска'}`}
      </h4>
      {focused && !rows.length ? (
        <p className="ins-empty small">Снимок процессов этого скачка не сохранился. Новые скачки сохраняются вместе с процессами.</p>
      ) : rows.length ? (
        <table className="ins-table">
          <thead>
            <tr>
              <th>Процесс</th>
              <th>PID</th>
              <th>ЦП</th>
              <th>ОЗУ</th>
              {info?.gpu_available ? <th>ГП</th> : null}
              <th>SSD</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((proc) => (
              <tr key={proc.pid}>
                <td>{proc.name}</td>
                <td>{proc.pid}</td>
                <td>{proc.cpu.toFixed(1)}%</td>
                <td>{proc.ram_mb.toFixed(0)} МБ</td>
                {info?.gpu_available ? <td>{proc.gpu === null ? '—' : `${proc.gpu.toFixed(1)}%`}</td> : null}
                <td>{formatRate(proc.disk ?? 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="ins-empty small">Процессы агента завершены.</p>
      )}
    </div>
  )
}

/* ---------- Взаимодействие ---------- */

const DIRECTIONS: Record<string, { label: string; tone: string }> = {
  'user→platform': { label: 'Пользователь → Платформа', tone: 'tone-user' },
  'platform→runner': { label: 'Платформа → Раннер', tone: 'tone-platform' },
  'runner→sdk': { label: 'Раннер → Cursor SDK', tone: 'tone-to-sdk' },
  'sdk→runner': { label: 'Cursor SDK → Раннер', tone: 'tone-from-sdk' },
  'runner→platform': { label: 'Раннер → Платформа', tone: 'tone-runner' },
  'runner stderr': { label: 'Раннер · stderr', tone: 'tone-stderr' }
}

function direction(dir: string): { label: string; tone: string } {
  return DIRECTIONS[dir] ?? { label: dir, tone: 'tone-runner' }
}

function pretty(data: string): string {
  try {
    return JSON.stringify(JSON.parse(data), null, 2)
  } catch {
    return data
  }
}

function summary(entry: TraceEntry): string {
  const source = entry.text || entry.data
  const line = source.replace(/\s+/g, ' ').trim()
  return line.length > 180 ? `${line.slice(0, 180)}…` : line
}

function TraceRow({ entry, startedAt }: { entry: TraceEntry; startedAt: number }): React.JSX.Element {
  const meta = direction(entry.dir)
  const offset = (new Date(entry.at).getTime() - startedAt) / 1000
  return (
    <details className={`ins-trace ${meta.tone}`}>
      <summary>
        <span className="ins-trace-time" title={clockTime(entry.at, true)}>
          +{offset.toFixed(offset < 10 ? 2 : 1)}с
        </span>
        <span className="ins-trace-dir">{meta.label}</span>
        <span className="ins-trace-kind">{entry.kind}</span>
        {entry.count > 1 ? <span className="ins-trace-count">×{entry.count}</span> : null}
        <span className="ins-trace-text">{summary(entry)}</span>
        <ChevronDownIcon size={13} />
      </summary>
      <div className="ins-trace-body">
        <span>
          {clockTime(entry.at, true)} · ход {entry.turn}
          {entry.count > 1 ? ` · склеено фрагментов потока: ${entry.count}` : ''}
        </span>
        {entry.text ? <pre>{entry.text}</pre> : null}
        {entry.data ? <pre>{pretty(entry.data)}</pre> : null}
      </div>
    </details>
  )
}

function Interaction({ sessionId, running }: { sessionId: string; running: boolean }): React.JSX.Element {
  const [entries, setEntries] = useState<TraceEntry[]>([])
  const [hidden, setHidden] = useState<Set<string>>(new Set())
  const revRef = useRef(0)
  const boxRef = useRef<HTMLDivElement>(null)
  const stickRef = useRef(true)

  useEffect(() => {
    revRef.current = 0
    stickRef.current = true
    setEntries([])
  }, [sessionId])

  usePoll(
    async () => {
      const chunk = await apiGet<TraceChunk>(`${base(sessionId)}/trace?since=${revRef.current}`)
      revRef.current = chunk.rev
      if (!chunk.entries.length) return
      setEntries((current) => {
        const bySeq = new Map(current.map((entry) => [entry.seq, entry]))
        for (const entry of chunk.entries) bySeq.set(entry.seq, entry)
        return [...bySeq.values()].sort((a, b) => a.seq - b.seq)
      })
    },
    running ? RUNNING_POLL_MS : IDLE_POLL_MS,
    [sessionId, running]
  )

  useLayoutEffect(() => {
    const box = boxRef.current
    if (box && stickRef.current) box.scrollTop = box.scrollHeight
  }, [entries])

  const present = useMemo(() => [...new Set(entries.map((entry) => entry.dir))], [entries])
  const startedAt = entries.length ? new Date(entries[0].at).getTime() : 0
  const visible = entries.filter((entry) => !hidden.has(entry.dir))

  function toggle(dir: string): void {
    setHidden((current) => {
      const next = new Set(current)
      if (next.has(dir)) next.delete(dir)
      else next.add(dir)
      return next
    })
  }

  if (!entries.length) return <p className="ins-empty">Журнал появится с первым запросом.</p>

  return (
    <div className="ins-interaction">
      <div className="ins-filters">
        {present.map((dir) => {
          const meta = direction(dir)
          return (
            <button
              key={dir}
              type="button"
              className={hidden.has(dir) ? `ins-filter ${meta.tone} off` : `ins-filter ${meta.tone}`}
              aria-pressed={!hidden.has(dir)}
              onClick={() => toggle(dir)}
            >
              {meta.label}
            </button>
          )
        })}
      </div>
      <div
        className="ins-trace-list"
        ref={boxRef}
        onScroll={(event) => {
          const box = event.currentTarget
          stickRef.current = box.scrollHeight - box.scrollTop - box.clientHeight < STICK_PX
        }}
      >
        {visible.map((entry, index) => (
          <div key={entry.seq}>
            {index === 0 || visible[index - 1].turn !== entry.turn ? (
              <div className="ins-turn">Ход {entry.turn}</div>
            ) : null}
            <TraceRow entry={entry} startedAt={startedAt} />
          </div>
        ))}
      </div>
    </div>
  )
}

/* ---------- Контекст ---------- */

const CONTEXT_TYPES: Record<ContextItemType, { label: string; color: string }> = {
  tools: { label: 'Определения инструментов', color: '#8b5cf6' },
  user: { label: 'Промпты пользователя', color: '#2f7cf6' },
  thinking: { label: 'Размышления', color: '#94a3b8' },
  assistant: { label: 'Ответы ассистента', color: '#3cb878' },
  tool_call: { label: 'Вызовы инструментов', color: '#e3a33b' },
  tool_result: { label: 'Результаты инструментов', color: '#14b8a6' },
  other: { label: 'Прочее', color: '#64748b' }
}

const TYPE_ORDER: ContextItemType[] = ['tools', 'user', 'thinking', 'assistant', 'tool_call', 'tool_result', 'other']

interface Resolved {
  item: ContextItem
  chars: number
}

function resolve(snapshot: ContextSnapshot, items: Record<string, ContextItem>): Resolved[] {
  return snapshot.items.flatMap(([id, chars]) => (items[id] ? [{ item: items[id], chars }] : []))
}

/** Что шаг добавил или дописал по сравнению с предыдущей точкой. */
function addedBy(snapshot: ContextSnapshot, previous: ContextSnapshot | undefined): Set<string> {
  const before = new Map(previous?.items ?? [])
  return new Set(snapshot.items.filter(([id, chars]) => before.get(id) !== chars).map(([id]) => id))
}

function byType(resolved: Resolved[]): Map<ContextItemType, Resolved[]> {
  const groups = new Map<ContextItemType, Resolved[]>()
  for (const entry of resolved) {
    const type = CONTEXT_TYPES[entry.item.type] ? entry.item.type : 'other'
    groups.set(type, [...(groups.get(type) ?? []), entry])
  }
  return groups
}

function ContextView({ sessionId, running }: { sessionId: string; running: boolean }): React.JSX.Element {
  const [data, setData] = useState<SessionContext | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const trackRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setData(null)
    setSelected(null)
  }, [sessionId])

  usePoll(
    async () => {
      setData(await apiGet<SessionContext>(`${base(sessionId)}/context`))
    },
    running ? CONTEXT_POLL_MS : IDLE_POLL_MS,
    [sessionId, running]
  )

  const snapshots = data?.snapshots ?? []
  const following = selected === null
  const active = snapshots.find((snapshot) => snapshot.seq === selected) ?? snapshots[snapshots.length - 1]

  useLayoutEffect(() => {
    const track = trackRef.current
    if (track && following) track.scrollLeft = track.scrollWidth
  }, [snapshots.length, following])

  if (!data || !snapshots.length || !active) {
    return <p className="ins-empty">{data ? 'Контекст появится после отправки промпта.' : 'Загружаем контекст…'}</p>
  }

  const totals = snapshots.map((snapshot) => snapshot.items.reduce((sum, [, chars]) => sum + chars, 0))
  const peak = Math.max(1, ...totals)
  const activeIndex = snapshots.indexOf(active)
  const resolved = resolve(active, data.items)
  const groups = byType(resolved)
  const total = resolved.reduce((sum, entry) => sum + entry.chars, 0)
  const added = addedBy(active, snapshots[activeIndex - 1])
  const fresh = resolved.filter((entry) => added.has(entry.item.id))
  const freshChars = fresh.reduce((sum, entry) => sum + entry.chars, 0)

  return (
    <div className="ins-context">
      <div className="ins-timeline" ref={trackRef}>
        <div className="ins-track" style={{ minWidth: `${Math.max(100, snapshots.length * POINT_SPACING_PX)}px` }}>
          <span className="ins-track-line" />
          {snapshots.map((snapshot, index) => {
            const left = snapshots.length === 1 ? 50 : (index / (snapshots.length - 1)) * 100
            const size = 8 + (totals[index] / peak) * 10
            const isActive = snapshot.seq === active.seq
            const newTurn = index > 0 && snapshots[index - 1].turn !== snapshot.turn
            const color = snapshot.kind ? CONTEXT_TYPES[snapshot.kind]?.color : undefined
            return (
              <div key={snapshot.seq}>
                {newTurn || index === 0 ? (
                  <span className="ins-track-turn" style={{ left: `${left}%` }}>
                    ход {snapshot.turn}
                  </span>
                ) : null}
                <button
                  type="button"
                  className={isActive ? 'ins-point active' : 'ins-point'}
                  style={{ left: `${left}%`, width: size, height: size, ...(color ? { background: color } : {}) }}
                  title={`${clockTime(snapshot.at)} · ${snapshot.reason} · ≈${tokens(totals[index])} ток.`}
                  aria-label={`Контекст на ${clockTime(snapshot.at)}`}
                  aria-pressed={isActive}
                  onClick={() => setSelected(index === snapshots.length - 1 ? null : snapshot.seq)}
                />
                {isActive ? (
                  <span className="ins-point-time" style={{ left: `${left}%` }}>
                    {clockTime(snapshot.at)}
                  </span>
                ) : null}
              </div>
            )
          })}
        </div>
      </div>

      <div className="ins-context-head">
        <div>
          <strong>
            {clockTime(active.at)} · ход {active.turn}
          </strong>
          <span>
            шаг {activeIndex + 1} из {snapshots.length} · {active.reason}
            {following && running ? ' · следим за последним' : ''}
          </span>
        </div>
        <div className="ins-context-total">
          <strong>≈{tokens(total)}</strong>
          <span>токенов (оценка)</span>
        </div>
      </div>

      {active.usage ? (
        <div className="ins-usage">
          <span>По данным SDK за ход:</span>
          <b>вход {active.usage.inputTokens ?? '—'}</b>
          <b>кэш {active.usage.cacheReadTokens ?? '—'}</b>
          <b>выход {active.usage.outputTokens ?? '—'}</b>
          {active.usage.reasoningTokens ? <b>рассуждения {active.usage.reasoningTokens}</b> : null}
        </div>
      ) : null}

      {fresh.length ? (
        <section className="ins-step">
          <div className="ins-step-head">
            <span>Добавлено этим шагом</span>
            <b>+≈{tokens(freshChars)}</b>
          </div>
          {fresh.map(({ item, chars }) => (
            <details key={item.id} className="ins-item" open={fresh.length === 1}>
              <summary>
                <i style={{ background: (CONTEXT_TYPES[item.type] ?? CONTEXT_TYPES.other).color }} />
                <span>{item.label}</span>
                <b>{chars.toLocaleString('ru-RU')} симв.</b>
              </summary>
              <pre>{item.text.length > chars ? item.text.slice(0, chars) : item.text}</pre>
            </details>
          ))}
        </section>
      ) : null}

      <div className="ins-stack" aria-hidden="true">
        {TYPE_ORDER.filter((type) => groups.has(type)).map((type) => {
          const chars = (groups.get(type) ?? []).reduce((sum, entry) => sum + entry.chars, 0)
          return (
            <span
              key={type}
              style={{ flexGrow: Math.max(chars, 1), background: CONTEXT_TYPES[type].color }}
              title={`${CONTEXT_TYPES[type].label}: ≈${tokens(chars)}`}
            />
          )
        })}
      </div>

      <div className="ins-groups">
        {TYPE_ORDER.filter((type) => groups.has(type)).map((type) => {
          const entries = groups.get(type) ?? []
          const chars = entries.reduce((sum, entry) => sum + entry.chars, 0)
          return (
            <details key={type} className="ins-group">
              <summary>
                <i style={{ background: CONTEXT_TYPES[type].color }} />
                <span>{CONTEXT_TYPES[type].label}</span>
                <em>{entries.length}</em>
                <b>≈{tokens(chars)}</b>
                <ChevronDownIcon size={13} />
              </summary>
              {entries.map(({ item, chars: size }) => (
                <details key={item.id} className="ins-item">
                  <summary>
                    <span>{item.label}</span>
                    {added.has(item.id) ? <em className="ins-new">новое</em> : null}
                    <b>{size.toLocaleString('ru-RU')} симв.</b>
                  </summary>
                  <pre>{item.text.length > size ? item.text.slice(0, size) : item.text}</pre>
                </details>
              ))}
            </details>
          )
        })}
      </div>
      <p className="ins-note">
        Точка — снимок после каждого шага агента: промпта, размышления, ответа, вызова инструмента и его результата.
        Размер — оценка (~4 символа на токен).
        Системный промпт и схемы инструментов SDK снаружи не видны: точные токены — в строке «По данным SDK».
      </p>
    </div>
  )
}

/* ---------- Панель ---------- */

export function AgentInsights({ sessionId, running, turns, remote = false }: InsightsProps): React.JSX.Element {
  const [tab, setTab] = useState<InsightTab>('performance')
  const live = running || turns === 0

  return (
    <aside className="glass-panel ins-panel" aria-label="Работа агента">
      <header className="ins-head">
        <Segmented items={TABS} value={tab} label="Работа агента" className="ins-tabs" onChange={setTab} />
      </header>
      <div className="ins-body" key={`${tab}:${sessionId ?? ''}`}>
        {!sessionId ? (
          <p className="ins-empty">Здесь появится работа агента: ресурсы, журнал обмена и контекст — после запуска.</p>
        ) : tab === 'performance' ? (
          <Performance sessionId={sessionId} running={live} remote={remote} />
        ) : tab === 'interaction' ? (
          <Interaction sessionId={sessionId} running={live} />
        ) : (
          <ContextView sessionId={sessionId} running={live} />
        )}
      </div>
    </aside>
  )
}
