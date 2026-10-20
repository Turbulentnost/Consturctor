import { createContext, useContext } from 'react'
import { ChevronRight, Files } from 'lucide-react'
import { DOCFLOW_JOURNALS, type JournalId } from './docflowJournals'
import '../../extensions/inDevelopment/inDevelopment.css'

type DocflowDockValue = {
  journal: JournalId
  setJournal: (id: JournalId) => void
}

const DocflowDockContext = createContext<DocflowDockValue | null>(null)

export function DocflowDockProvider({
  journal,
  setJournal,
  children
}: DocflowDockValue & { children: React.ReactNode }): React.JSX.Element {
  return <DocflowDockContext.Provider value={{ journal, setJournal }}>{children}</DocflowDockContext.Provider>
}

export function useDocflowDock(): DocflowDockValue {
  return useContext(DocflowDockContext) ?? { journal: 'correspondence', setJournal: () => undefined }
}

export function DocflowDock({
  labeled,
  journal,
  onSelect
}: {
  labeled: boolean
  journal: JournalId
  onSelect: (id: JournalId) => void
}): React.JSX.Element {
  return (
    <aside
      className={labeled ? 'child-dock child-dock--labeled child-dock--wide' : 'child-dock child-dock--wide'}
      aria-label="Журналы документооборота 1С"
    >
      <div className="child-dock-head">
        <span className="child-dock-mark">
          <Files size={16} strokeWidth={1.8} aria-hidden />
        </span>
        <span className="child-dock-head-text">
          <strong>Документооборот</strong>
          <small>Журналы 1С</small>
        </span>
      </div>
      <nav className="child-dock-nav">
        {DOCFLOW_JOURNALS.map((item) => {
          const Icon = item.icon
          return (
            <button
              key={item.id}
              type="button"
              data-search-id={item.id}
              className={journal === item.id ? 'child-dock-item is-active' : 'child-dock-item'}
              title={item.title}
              aria-label={item.title}
              aria-current={journal === item.id ? 'page' : undefined}
              onClick={() => onSelect(item.id)}
            >
              <Icon size={16} strokeWidth={1.8} aria-hidden />
              <span className="child-dock-label">{item.title}</span>
              <ChevronRight className="child-dock-chevron" size={14} strokeWidth={1.8} aria-hidden />
            </button>
          )
        })}
      </nav>
    </aside>
  )
}
