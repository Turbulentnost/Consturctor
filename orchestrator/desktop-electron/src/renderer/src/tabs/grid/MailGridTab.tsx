import { useCallback, useMemo, useState } from 'react'
import type { UserProfile } from '../../api/types'
import { StandardTabChrome, summaryTilesAsChrome } from './TabChromeGrid'
import { DEFAULT_STANDARD_LAYOUT } from './useTabChromeLayout'
import type { SpecSummaryTile } from '../../workplace/specV04Shell'
import { SpecPill } from '../../workplace/specV04Components'
import { type SpecMailRow } from '../../workplace/specV04DemoData'
import { useSpecV04Sources } from '../../workplace/useSpecV04Data'
import { countMailTiles, mailMatchesTile, toggleSimpleTile } from '../../workplace/tileFilters'
import { mailListEmptyHint } from '../../workplace/mailProbe'
import { GridFilterBar, toFilterOptions, uniqueFilterValues } from './gridFilters'
import { MailDetailPanel } from './MailDetailPanel'

export function MailGridTab({
  user,
  onAskOrchestrator
}: {
  user: UserProfile
  onAskOrchestrator: (message: string, context: string) => void
}): React.JSX.Element {
  const data = useSpecV04Sources(user)
  const [rowPatches, setRowPatches] = useState<Record<string, Partial<SpecMailRow>>>({})
  const mailRows = useMemo(
    () => data.mailRows.map((row) => ({ ...row, ...rowPatches[row.id] })),
    [data.mailRows, rowPatches]
  )
  const [selectedId, setSelectedId] = useState('')
  const [tileFilter, setTileFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [barPriority, setBarPriority] = useState('')
  const [barStatus, setBarStatus] = useState('')
  const visibleMail = useMemo(() => {
    const q = query.trim().toLowerCase()
    return mailRows.filter((row) => {
      if (!mailMatchesTile(row, tileFilter)) return false
      if (barPriority && row.priority !== barPriority) return false
      if (barStatus && row.status !== barStatus) return false
      if (q && !`${row.sender} ${row.subject} ${row.status}`.toLowerCase().includes(q)) return false
      return true
    })
  }, [mailRows, tileFilter, query, barPriority, barStatus])
  const selected = visibleMail.find((m) => m.id === (selectedId || visibleMail[0]?.id))
  const patchRow = useCallback((id: string, patch: Partial<(typeof mailRows)[0]>) => {
    setRowPatches((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }))
  }, [])

  const tiles: SpecSummaryTile[] = useMemo(() => {
    const counts = countMailTiles(mailRows)
    const dash = (n: number): string => (n ? String(n) : '—')
    return [
      { id: 'new', label: 'Новые', value: dash(counts.new), tone: 'orange' },
      { id: 'proc', label: 'К обработке', value: dash(counts.proc), tone: 'blue' },
      { id: 'hi', label: 'Высокий приоритет', value: dash(counts.hi), tone: 'red' },
      { id: 'proj', label: 'Проектные', value: dash(counts.proj), tone: 'purple' },
      { id: 'reg', label: 'Регламентные', value: dash(counts.reg), tone: 'yellow' }
    ]
  }, [mailRows])

  const ask = (m: string) => onAskOrchestrator(m, 'Вкладка «Письма»')

  return (
    <StandardTabChrome
      tabId="mail"
      userId={user.id || ''}
      defaults={DEFAULT_STANDARD_LAYOUT}
      chromeTiles={summaryTilesAsChrome(tiles, tileFilter === 'all' ? 'new' : tileFilter, (id) =>
        setTileFilter((current) => (id === 'new' ? 'all' : toggleSimpleTile(current, id)))
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
              options: toFilterOptions(uniqueFilterValues(mailRows.map((row) => row.priority)))
            },
            {
              id: 'status',
              value: barStatus,
              emptyLabel: 'Статус: все',
              onChange: setBarStatus,
              options: toFilterOptions(uniqueFilterValues(mailRows.map((row) => row.status)))
            }
          ]}
          onReset={() => {
            setQuery('')
            setBarPriority('')
            setBarStatus('')
            setTileFilter('all')
          }}
        />
        ),
        main: (
        <div className="spec-v04-table-wrap wp-card">
          {data.mailComError || data.mailImapError || (!data.mailImapPrimary && data.mailImapStatus) ? (
            <p className="spec-v04-muted">
              {[data.mailComError, data.mailImapError, data.mailImapPrimary ? '' : data.mailImapStatus]
                .filter(Boolean)
                .join(' · ')}
            </p>
          ) : null}
          <table className="spec-v04-table">
            <thead>
              <tr>
                <th>Отправитель</th>
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
                    {mailRows.length
                      ? 'Нет писем по выбранной плитке'
                      : mailListEmptyHint({
                          loading: data.mailLoading,
                          imapPrimary: data.mailImapPrimary,
                          mailbox: data.outlookMailbox,
                          imapStatus: data.mailImapStatus
                        })}
                  </td>
                </tr>
              ) : null}
              {visibleMail.map((row) => (
                <tr key={row.id} className={selected?.id === row.id ? 'selected' : ''} onClick={() => setSelectedId(row.id)}>
                  <td>{row.sender}</td>
                  <td>{row.subject}</td>
                  <td>{row.time}</td>
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
        </div>
        ),
        side: selected ? (
          <MailDetailPanel mail={selected} onPatchRow={patchRow} onAskOrchestrator={ask} />
        ) : (
          <div className="wp-card spec-v04-muted">Выберите письмо</div>
        )
      }}
    />
  )
}
