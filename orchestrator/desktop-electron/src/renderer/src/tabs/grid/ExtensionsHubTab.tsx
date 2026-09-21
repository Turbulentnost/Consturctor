import { useMemo, useState } from 'react'
import type { UserProfile } from '../../api/types'
import type { PageKey } from '../../components/Sidebar'
import { EXTENSIONS, canUseExtension } from '../../extensions/extensionRegistry'
import { useExtensions } from '../../extensions/ExtensionsProvider'
import { EXTENSION_MODULE_BY_ID } from '../../extensions/extensionModules'
import {
  EXTENSION_POSITION_FILTERS,
  extensionMatchesPositionFilter,
  type ExtensionPositionFilter
} from '../../extensions/extensionAudience'
import { NavIcon } from '../../layout/navIcons'
import { OrchSlotMain } from '../../layout/GridSlots'
import './extensionsGrid.css'

export function ExtensionsHubTab({
  user,
  onOpenExtension,
  onNotify
}: {
  user: UserProfile
  onOpenExtension: (pageKey: PageKey) => void
  onNotify?: (message: string) => void
}): React.JSX.Element {
  const { isPinned, togglePin } = useExtensions()
  const [positionFilter, setPositionFilter] = useState<ExtensionPositionFilter>('all')

  const visibleExtensions = useMemo(
    () =>
      EXTENSIONS.filter((ext) =>
        extensionMatchesPositionFilter(ext.positionGroups, positionFilter)
      ),
    [positionFilter]
  )

  return (
    <OrchSlotMain spanAll heavyEmbed>
      <div className="extensions-hub">
        <div className="extensions-hub-toolbar">
          <div className="extensions-hub-filter" role="group" aria-label="Фильтр по должности">
            <span className="extensions-hub-filter-label">Должность</span>
            {EXTENSION_POSITION_FILTERS.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`extensions-hub-filter-btn${positionFilter === item.id ? ' is-active' : ''}`}
                aria-pressed={positionFilter === item.id}
                onClick={() => setPositionFilter(item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>
          <span className="extensions-hub-filter-meta set-muted">
            {visibleExtensions.length}{' '}
            {visibleExtensions.length === 1 ? 'расширение' : 'расширения'}
          </span>
        </div>

        <header className="extensions-hub-head">
          <p className="set-muted">
            Подключите модуль и выведите его на левую панель. Новые модули — в{' '}
            <code className="extensions-hub-code">extensionModules.tsx</code>.
          </p>
        </header>

        <div className="extensions-hub-canvas">
          <ul className="extensions-hub-list">
            {visibleExtensions.length === 0 ? (
              <li className="extensions-hub-empty">Нет расширений для выбранной должности.</li>
            ) : null}
            {visibleExtensions.map((ext) => {
              const allowed = canUseExtension(user, ext.id)
              const pinned = isPinned(ext.id)
              const mod = EXTENSION_MODULE_BY_ID[ext.id]
              return (
                <li key={ext.id} className="extensions-hub-card wp-card">
                  <div className="extensions-hub-card-body">
                    <div className="extensions-hub-card-head">
                      <span className="extensions-hub-card-icon" title="Иконка на левой панели">
                        <NavIcon page={ext.pageKey} />
                      </span>
                      <h3>{ext.title}</h3>
                    </div>
                    <p>{ext.description}</p>
                    {!allowed ? (
                      <p className="extensions-hub-locked">Нет доступа для вашей должности</p>
                    ) : null}
                  </div>
                  <div className="extensions-hub-card-actions">
                    <button
                      type="button"
                      className="extensions-hub-btn extensions-hub-btn--open"
                      disabled={!allowed}
                      onClick={() => onOpenExtension(ext.pageKey)}
                    >
                      Открыть
                    </button>
                    <button
                      type="button"
                      className={`extensions-hub-btn extensions-hub-btn--pin${pinned ? ' is-active' : ''}`}
                      disabled={!allowed}
                      onClick={() => {
                        togglePin(ext.id)
                        const title = mod?.title || ext.title
                        onNotify?.(
                          pinned
                            ? `${title} убрано с панели навигации`
                            : `${title} добавлено на панель навигации`
                        )
                      }}
                    >
                      {pinned ? 'Убрать с панели' : 'Добавить на панель'}
                    </button>
                  </div>
                </li>
              )
            })}
          </ul>
        </div>
      </div>
    </OrchSlotMain>
  )
}
