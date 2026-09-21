import { OrchSlotFilters } from '../../layout/GridSlots'
import type { UserProfile } from '../../api/types'
import type { PageKey } from '../../components/Sidebar'
import { WorkplaceGlobalRangePicker } from '../../workplace/workplacePeriod'
import { EXTENSIONS, canUseExtension } from '../../extensions/extensionRegistry'
import { useExtensions } from '../../extensions/ExtensionsProvider'
import { EXTENSION_MODULE_BY_ID } from '../../extensions/extensionModules'
import { NavIcon } from '../../layout/navIcons'
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

  return (
    <>
    <OrchSlotFilters>
      <div className="workplace-global-filters-strip wp-card">
        <WorkplaceGlobalRangePicker />
      </div>
    </OrchSlotFilters>
    <div className="extensions-hub">
      <header className="extensions-hub-head">
        <p className="set-muted">
          Модульные вкладки: подключите расширение и выведите его на левую панель. Новые модули добавляются в{' '}
          <code className="extensions-hub-code">extensionModules.tsx</code>.
        </p>
      </header>
      <div className="extensions-hub-canvas">
      <ul className="extensions-hub-list">
        {EXTENSIONS.map((ext) => {
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
                  className="today-link-btn"
                  disabled={!allowed}
                  onClick={() => onOpenExtension(ext.pageKey)}
                >
                  Открыть
                </button>
                <button
                  type="button"
                  className={`today-filter-layout-btn${pinned ? ' is-active' : ''}`}
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
                  {pinned ? 'На панели' : 'Добавить на панель'}
                </button>
              </div>
            </li>
          )
        })}
      </ul>
      </div>
    </div>
    </>
  )
}
