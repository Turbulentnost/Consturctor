import { useEffect, useMemo, useState } from 'react'
import { StyledDocument } from '../components/StyledDocument'
import type {
  RegulationFragment,
  RegulationParseResult,
  RoleFunction,
  RoleMatch,
  RoleMatchResult
} from '../api/types'

const HIGH_CONFIDENCE = 0.85

const MATCH_TYPE_LABELS: Record<string, string> = {
  direct_role_mention: 'Должность указана в тексте или заголовке',
  inherited_from_section: 'Роль унаследована из раздела документа',
  assigned_action: 'Фрагмент описывает выполняемое действие',
  process_role_alias: 'Совпадение с ролью в процессе',
  department_relation: 'Связь через подразделение',
  interaction: 'Взаимодействие с другой ролью',
  related_artifact_or_system: 'Упоминание артефакта или системы',
  semantic_candidate: 'Семантическое совпадение с должностью',
  graph_relation: 'Связь найдена через граф документа',
  definition_link: 'Термин связан с определением в документе',
  actor_inheritance: 'Исполнитель наследуется из связанного блока'
}

interface RoleMatchPageProps {
  result: RoleMatchResult
  regulation: RegulationParseResult | null
  busy?: boolean
  onBack: () => void
  onDecide: (matchId: string, status: 'accepted' | 'rejected') => Promise<void>
  onFinish: () => void
}

interface ProofItem {
  fragmentId: string
  source: string
  quote: string
  badge: string
  kind: string
  note: string
}

function functionTitle(fn: RoleFunction | null, match: RoleMatch, index: number): string {
  const explicit = (fn?.title || '').split('→', 1)[0].trim()
  if (explicit) return explicit
  if (fn?.action && fn.object) return `${fn.action} ${fn.object}`
  if (fn?.action) return fn.action
  const fragmentText = (match.fragment?.text || '').trim()
  if (fragmentText) return fragmentText.slice(0, 120)
  return `Функция ${index + 1}`
}

function orderedMatches(matches: RoleMatch[]): RoleMatch[] {
  return matches
    .filter((match) => match.status !== 'rejected' && Boolean(match.matchId))
    .sort((a, b) => {
      const pageA = a.fragment?.page ?? 0
      const pageB = b.fragment?.page ?? 0
      if (pageA !== pageB) return pageA - pageB
      if (b.confidence !== a.confidence) return b.confidence - a.confidence
      return a.matchId.localeCompare(b.matchId)
    })
}

function shouldPersistAccept(match: RoleMatch): boolean {
  if (match.status === 'accepted' && !match.requiresConfirmation) return false
  return match.status !== 'accepted'
}

function isHighConfidence(match: RoleMatch): boolean {
  return match.confidence >= HIGH_CONFIDENCE
}

function statusLabel(status: string): string {
  if (status === 'accepted') return 'Подтверждена'
  if (status === 'rejected') return 'Отклонена'
  return 'На проверке'
}

function confidenceMeta(value: number): { label: string; className: string } {
  if (value >= HIGH_CONFIDENCE) return { label: 'высокая', className: 'high' }
  if (value >= 0.65) return { label: 'средняя', className: 'mid' }
  return { label: 'низкая', className: 'low' }
}

function cleanLine(value: string): string {
  return value.replace(/\s+/g, ' ').trim()
}

function isWeakQuote(quote: string): boolean {
  const normalized = quote.toLowerCase()
  return ['предыдущий смысловой блок', 'следующий смысловой блок', 'previous_block', 'next_block', 'parent_section'].some(
    (marker) => normalized.includes(marker)
  )
}

function evidenceBadge(relation: string): { badge: string; kind: string } {
  if (relation === 'direct_role_mention' || relation === 'assigned_action') {
    return { badge: 'Прямое указание', kind: 'direct' }
  }
  if (relation === 'actor_inheritance' || relation === 'definition_of' || relation === 'definition_link') {
    return { badge: 'Связь исполнителя', kind: 'actor' }
  }
  if (relation === 'condition_for' || relation === 'exception_for') {
    return { badge: 'Условие работы', kind: 'condition' }
  }
  if (relation === 'previous_block' || relation === 'next_block' || relation === 'input_for' || relation === 'same_process') {
    return { badge: 'Зависимость', kind: 'dependency' }
  }
  return { badge: 'Связь графа', kind: 'graph' }
}

function fragmentById(fragments: RegulationFragment[], fragmentId: string): RegulationFragment | undefined {
  return fragments.find((item) => item.fragmentId === fragmentId)
}

function proofItem(
  fragmentId: string,
  quote: string,
  relation: string,
  note: string,
  fragments: RegulationFragment[]
): ProofItem {
  const fragment = fragmentById(fragments, fragmentId)
  const sourceParts: string[] = []
  if (fragment?.section) sourceParts.push(fragment.section)
  if (fragment?.page) sourceParts.push(`стр. ${fragment.page}`)
  const { badge, kind } = evidenceBadge(relation)
  return {
    fragmentId,
    source: sourceParts.join(' · ') || fragmentId || 'Документ',
    quote: quote.slice(0, 700),
    badge,
    kind,
    note: cleanLine(note).slice(0, 300)
  }
}

function proofItems(match: RoleMatch, fragments: RegulationFragment[]): ProofItem[] {
  const items: ProofItem[] = []
  const seen = new Set<string>()
  const add = (item: ProofItem): void => {
    const key = `${item.fragmentId}|${item.quote}`
    if (!item.quote || seen.has(key)) return
    seen.add(key)
    items.push(item)
  }
  const function_ = match.function
  if (function_) {
    for (const evidence of function_.evidence) {
      const quote = cleanLine(evidence.quote)
      if (!quote || isWeakQuote(quote)) continue
      add(proofItem(evidence.fragmentId || match.fragmentId, quote, 'direct_role_mention', 'Цитата из исходного документа', fragments))
    }
    for (const block of function_.proofChain) {
      const fragmentId = block.blockId || match.fragmentId
      let quote = cleanLine(block.text || block.evidence)
      if (!quote || isWeakQuote(quote)) {
        quote = cleanLine(fragmentById(fragments, fragmentId)?.text || '')
      }
      if (!quote) continue
      add(proofItem(fragmentId, quote, block.relation, block.evidence, fragments))
    }
  }
  if (!items.length) {
    for (const signal of match.signals) {
      const quote = cleanLine(signal.quote)
      if (!quote || isWeakQuote(quote)) continue
      add(proofItem(signal.fragmentId || match.fragmentId, quote, signal.matchType, signal.explanation, fragments))
    }
  }
  if (!items.length) {
    const quote = cleanLine(match.fragment?.text || match.explanation)
    if (quote) {
      add(proofItem(match.fragmentId, quote, 'graph_relation', match.explanation, fragments))
    }
  }
  return items.slice(0, 5)
}

function detailLines(match: RoleMatch): string[] {
  const fn = match.function
  if (!fn) return []
  const lines: string[] = []
  const actor = fn.actor.canonicalPosition || fn.actor.text
  if (actor) {
    lines.push(fn.actor.sourceBlockId ? `Исполнитель: ${actor} (из блока ${fn.actor.sourceBlockId})` : `Исполнитель: ${actor}`)
  }
  if (fn.conditions.length) {
    lines.push(`Условия: ${fn.conditions.slice(0, 2).join('; ')}`)
  }
  const deps = fn.dependencies
    .slice(0, 2)
    .map((item) => item.description || item.blockId)
    .filter(Boolean)
  if (deps.length) {
    lines.push(`Зависимости: ${deps.join('; ')}`)
  }
  if (fn.explanation) lines.push(fn.explanation)
  return lines.slice(0, 5)
}

function reasonLines(match: RoleMatch): string[] {
  const lines: string[] = []
  for (const signal of match.signals) {
    const text = signal.explanation.trim() || MATCH_TYPE_LABELS[signal.matchType] || signal.matchType
    if (text && !lines.includes(text)) lines.push(text)
  }
  if (!lines.length && match.explanation.trim()) lines.push(match.explanation.trim())
  if (!lines.length) lines.push('Фрагмент связан с выбранной должностью')
  return lines.slice(0, 4)
}

function sourceFragmentId(match: RoleMatch): string {
  return (
    match.fragmentId ||
    match.function?.targetBlockId ||
    match.function?.evidence[0]?.fragmentId ||
    match.signals[0]?.fragmentId ||
    ''
  )
}

export function RoleMatchPage({
  result,
  regulation,
  busy,
  onBack,
  onDecide,
  onFinish
}: RoleMatchPageProps): React.JSX.Element {
  const [index, setIndex] = useState(0)
  const [runId, setRunId] = useState(result.runId)
  const [mode, setMode] = useState<'wizard' | 'document'>('wizard')
  const [highlightId, setHighlightId] = useState('')
  const [error, setError] = useState('')

  const items = useMemo(() => orderedMatches(result.matches), [result.matches])

  useEffect(() => {
    if (result.runId === runId) return
    setRunId(result.runId)
    setIndex(0)
    setMode('wizard')
    setHighlightId('')
    setError('')
  }, [result.runId, runId])

  useEffect(() => {
    if (items.length && index >= items.length) {
      setIndex(items.length - 1)
    }
  }, [index, items.length])
  const currentIndex = items.length ? Math.min(index, items.length - 1) : 0
  const current = items[currentIndex]
  const pending = result.matches.filter((item) => item.status === 'pending').length
  const accepted = result.matches.filter((item) => item.status === 'accepted').length
  const fragments = regulation?.fragments ?? []
  const proofs = current ? proofItems(current, fragments) : []
  const confidence = current ? confidenceMeta(current.confidence) : null

  function primaryLabel(): string {
    if (!current || currentIndex >= items.length - 1) return 'Завершить'
    if (isHighConfidence(current)) return 'Продолжить'
    return 'Подтвердить'
  }

  function showDocument(fragmentId: string): void {
    setHighlightId(fragmentId)
    setMode('document')
  }

  function showWizard(): void {
    setMode('wizard')
    setHighlightId('')
  }

  function goBack(): void {
    if (currentIndex > 0) {
      setIndex(currentIndex - 1)
      setError('')
      return
    }
    onBack()
  }

  async function decide(status: 'accepted' | 'rejected'): Promise<void> {
    if (!current) {
      onFinish()
      return
    }
    setError('')
    const last = currentIndex >= items.length - 1
    try {
      const persist =
        status === 'rejected' ? current.status !== 'rejected' : shouldPersistAccept(current)
      if (persist) {
        await onDecide(current.matchId, status)
      }
      if (last) {
        onFinish()
        return
      }
      if (status === 'accepted') {
        setIndex(currentIndex + 1)
      }
      setMode('wizard')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  if (mode === 'document') {
    return (
      <div className="page-with-footer">
        <div className="page-scroll">
          <div className="chat-head">
            <button className="btn-ghost" onClick={showWizard}>
              {'\u2039'} К подтверждению
            </button>
            <h1 className="page-title" style={{ fontSize: 24 }}>
              {regulation?.fileName || 'Регламент'}
            </h1>
            <p className="page-subtitle">Фрагмент, на основе которого сформирован функциональный блок</p>
          </div>
          {fragments.length ? (
            <StyledDocument fragments={fragments} highlightFragmentId={highlightId} />
          ) : (
            <div className="placeholder-card">Документ недоступен</div>
          )}
        </div>
        <div className="page-footer">
          <button className="btn-ghost-dark" onClick={showWizard}>
            К подтверждению
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="page-with-footer">
      <div className="page-scroll">
        <div className="chat-head">
          <button className="btn-ghost" onClick={goBack}>
            {'\u2039'} Назад
          </button>
          <h1 className="page-title" style={{ fontSize: 28 }}>
            Проверка функций должности
          </h1>
          <p className="page-subtitle">
            {result.canonicalTitle || 'Должность из профиля'}
            {result.department ? ` · ${result.department}` : ''}
          </p>
        </div>

        <div className="review-stats">
          <div className="stat">
            <div className="stat-value">{result.matches.length || items.length}</div>
            <div className="stat-label">найдено функций</div>
          </div>
          <div className="stat">
            <div className="stat-value">{pending}</div>
            <div className="stat-label">нужно проверить</div>
          </div>
          <div className="stat">
            <div className="stat-value">{accepted}</div>
            <div className="stat-label">подтверждено</div>
          </div>
        </div>

        <div className="wizard-progress">
          <div className="wizard-progress-meta">
            <span>
              {items.length ? `${currentIndex + 1} из ${items.length}` : '0 из 0'}
            </span>
            <span>Проверен {accepted} из {result.matches.length || items.length}</span>
          </div>
          <div className="wizard-progress-bar">
            <div
              className="wizard-progress-fill"
              style={{ width: items.length ? `${((currentIndex + 1) / items.length) * 100}%` : '0%' }}
            />
          </div>
        </div>

        {error && <div className="wizard-error">{error}</div>}

        {!current && <div className="placeholder-card">Функции по должности не найдены.</div>}

        {current && (
          <div className="wizard-card">
            <div className="wizard-card-meta">
              {current.fragment?.page
                ? `Фрагмент со страницы ${current.fragment.page}`
                : current.fragmentId
                  ? `Фрагмент ${current.fragmentId}`
                  : 'Фрагмент из регламента'}
            </div>
            <div className="fn-head">
              <h3>{functionTitle(current.function, current, currentIndex)}</h3>
              <span className={`phase-pill ${current.status}`}>{statusLabel(current.status)}</span>
            </div>
            {(current.function?.action || current.function?.object || current.function?.recipient) && (
              <p className="wizard-meta-line">
                {[
                  current.function?.action && `Действие: ${current.function.action}`,
                  current.function?.object && `Объект: ${current.function.object}`,
                  current.function?.recipient && `Получатель: ${current.function.recipient}`
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </p>
            )}
            {detailLines(current).length > 0 && (
              <div className="wizard-section">
                <h4>Детали функции</h4>
                {detailLines(current).map((line) => (
                  <p key={line}>{line}</p>
                ))}
              </div>
            )}
            <div className="wizard-section">
              <h4>Почему найдено</h4>
              <ul className="wizard-reasons">
                {reasonLines(current).map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </div>
            {proofs.length > 0 && (
              <div className="wizard-section">
                <h4>Доказательства из документа</h4>
                <div className="proof-list">
                  {proofs.map((item) => (
                    <div key={`${item.fragmentId}-${item.quote}`} className="proof-card">
                      <div className="proof-head">
                        <span className="proof-source">{item.source}</span>
                        <span className={`proof-badge ${item.kind}`}>{item.badge}</span>
                      </div>
                      <p className="proof-quote">«{item.quote}»</p>
                      {item.note && <p className="proof-note">{item.note}</p>}
                      {item.fragmentId && (
                        <button className="btn-link" type="button" onClick={() => showDocument(item.fragmentId)}>
                          Открыть фрагмент
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {confidence && (
              <p className={`wizard-confidence ${confidence.className}`}>
                Уверенность: {confidence.label} · {Math.round(current.confidence * 100)}%
              </p>
            )}
            {sourceFragmentId(current) && (
              <button className="btn-link" type="button" onClick={() => showDocument(sourceFragmentId(current))}>
                Показать в документе
              </button>
            )}
          </div>
        )}
      </div>

      <div className="page-footer">
        <button className="btn-ghost-dark" onClick={goBack} disabled={busy}>
          Назад
        </button>
        <div className="page-footer-actions">
          {current && (
            <button className="btn-ghost-dark" onClick={() => void decide('rejected')} disabled={busy}>
              Не относится
            </button>
          )}
          <button className="btn-primary" style={{ maxWidth: 220 }} onClick={() => void decide('accepted')} disabled={busy}>
            {busy ? 'Сохраняем...' : primaryLabel()}
          </button>
        </div>
      </div>
    </div>
  )
}
