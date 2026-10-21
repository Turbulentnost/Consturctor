import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  Building2,
  Check,
  ChevronDown,
  FileUp,
  Globe,
  Lock,
  Search,
  Plus,
  UserRound,
  X
} from 'lucide-react'
import {
  api,
  type ExplorerAccess,
  type ExplorerAccessMode,
  type ExplorerAccessUser,
  type ExplorerItem,
  type ExplorerRight
} from '../../api/client'
import type { DirectoryUser } from '../../api/types'
import { useReportError } from '../../components/ErrorToast'

export const ACCESS_LABELS: Record<ExplorerAccessMode, string> = {
  private: 'Только я',
  users: 'Выбранные люди',
  department: 'Отдел',
  all: 'Все сотрудники'
}

const ACCESS_OPTIONS: {
  mode: ExplorerAccessMode
  icon: typeof Lock
  hint: string
}[] = [
  { mode: 'private', icon: Lock, hint: 'Файл открываете только вы' },
  { mode: 'users', icon: UserRound, hint: 'Каждому можно выдать ключ на чтение или на запись' },
  { mode: 'department', icon: Building2, hint: 'Отдел откроется списком сотрудников, права задаются каждому' },
  { mode: 'all', icon: Globe, hint: 'Файл появится у всех в «Доступные мне»' }
]

const PRIVATE_ACCESS: ExplorerAccess = {
  mode: 'private',
  users: [],
  departments: [],
  allPermission: 'read'
}

export function errorText(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback
}

function initials(name: string): string {
  const parts = name.replace(/\./g, ' ').split(/\s+/).filter(Boolean)
  if (!parts.length) return '?'
  return (parts[0][0] + (parts[1]?.[0] || '')).toUpperCase()
}

function accessIsComplete(access: ExplorerAccess): boolean {
  if (access.mode === 'users') return access.users.length > 0
  if (access.mode === 'department') {
    return (
      access.departments.length > 0 &&
      access.departments.every((dept) => access.users.some((user) => user.department === dept))
    )
  }
  return true
}

function RightSwitch({
  value,
  onChange
}: {
  value: ExplorerRight
  onChange: (next: ExplorerRight) => void
}): React.JSX.Element {
  return (
    <span className="kx-rights" role="group" aria-label="Права">
      <button
        type="button"
        className={value === 'read' ? 'active' : ''}
        aria-pressed={value === 'read'}
        onClick={() => onChange('read')}
      >
        Чтение
      </button>
      <button
        type="button"
        className={value === 'write' ? 'active' : ''}
        aria-pressed={value === 'write'}
        onClick={() => onChange('write')}
      >
        Запись
      </button>
    </span>
  )
}

function isLiquidatedDepartment(name: string): boolean {
  return /^\s*[(_]\s*ликв/i.test(name)
}

function personKey(user: { id?: string; fio: string }): string {
  return (user.id || user.fio).trim().toLowerCase()
}

function samePerson(a: { id?: string; fio: string }, b: { id?: string; fio: string }): boolean {
  if (a.id && b.id) return a.id === b.id
  return a.fio.trim().toLowerCase() === b.fio.trim().toLowerCase()
}

async function searchEmployees(query: string): Promise<DirectoryUser[]> {
  const text = query.trim()
  const fromDirectory = await api.listDirectoryUsers(text).catch(() => [] as DirectoryUser[])
  if (fromDirectory.length) return fromDirectory
  const names = await api.searchUsers(text).catch(() => [] as string[])
  return names.map((fio) => ({
    id: '',
    fio,
    position: '',
    department: '',
    activityStatus: 'online',
    online: false,
    isSupport: false,
    avatarUrl: null
  }))
}

type FloatBox = { top?: number; bottom?: number; left: number; width: number; maxHeight: number }

function useFloatBox(
  open: boolean,
  anchor: React.RefObject<HTMLElement | null>,
  maxHeight = 280
): FloatBox | null {
  const [box, setBox] = useState<FloatBox | null>(null)
  useLayoutEffect(() => {
    if (!open || !anchor.current) {
      setBox(null)
      return
    }
    const place = (): void => {
      const rect = anchor.current?.getBoundingClientRect()
      if (!rect) return
      const gap = 6
      const margin = 12
      const spaceBelow = window.innerHeight - rect.bottom - gap - margin
      const spaceAbove = rect.top - gap - margin
      const openBelow = spaceBelow >= 160 || spaceBelow >= spaceAbove
      const room = Math.max(120, Math.min(maxHeight, openBelow ? spaceBelow : spaceAbove))
      const left = Math.max(margin, Math.min(rect.left, window.innerWidth - rect.width - margin))
      setBox(
        openBelow
          ? { top: rect.bottom + gap, left, width: rect.width, maxHeight: room }
          : { bottom: window.innerHeight - rect.top + gap, left, width: rect.width, maxHeight: room }
      )
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [open, anchor, maxHeight])
  return box
}

function FloatMenu({
  open,
  anchor,
  onClose,
  tall = false,
  children
}: {
  open: boolean
  anchor: React.RefObject<HTMLElement | null>
  onClose: () => void
  tall?: boolean
  children: React.ReactNode
}): React.JSX.Element | null {
  const box = useFloatBox(open, anchor, tall ? 560 : 280)
  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent): void => {
      const target = e.target as Node
      if (anchor.current?.contains(target)) return
      if ((target as HTMLElement).closest?.('[data-kx-float]')) return
      onClose()
    }
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
      }
    }
    document.addEventListener('mousedown', onDoc)
    window.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      window.removeEventListener('keydown', onKey, true)
    }
  }, [open, anchor, onClose])
  if (!open || !box) return null
  return createPortal(
    <div
      data-kx-float
      className={tall ? 'kx-float kx-float-tall' : 'kx-float'}
      style={{
        top: box.top,
        bottom: box.bottom,
        left: box.left,
        width: box.width,
        maxHeight: box.maxHeight
      }}
    >
      {children}
    </div>,
    document.body
  )
}

function PeoplePicker({
  selected,
  onChange
}: {
  selected: ExplorerAccess['users']
  onChange: (users: ExplorerAccess['users']) => void
}): React.JSX.Element {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<DirectoryUser[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState('')
  const wrapRef = useRef<HTMLDivElement>(null)
  const seq = useRef(0)

  useEffect(() => {
    const text = query.trim()
    if (!open) return
    const id = ++seq.current
    setLoading(true)
    setError('')
    const timer = window.setTimeout(() => {
      void searchEmployees(text)
        .then((users) => {
          if (id !== seq.current) return
          setResults(users)
          setLoading(false)
        })
        .catch((err: unknown) => {
          if (id !== seq.current) return
          setResults([])
          setLoading(false)
          setError(errorText(err, 'Не удалось загрузить сотрудников'))
        })
    }, text ? 160 : 0)
    return () => window.clearTimeout(timer)
  }, [query, open])

  const visible = results
    .filter((user) => !selected.some((picked) => samePerson(picked, user)))
    .slice(0, 8)

  const add = (user: DirectoryUser): void => {
    if (!user.fio.trim()) return
    onChange([...selected, { id: user.id || '', fio: user.fio, permission: 'read', department: '' }])
    setQuery('')
    setResults([])
    setOpen(true)
  }

  return (
    <div className="kx-picker">
      <div className="kx-search" ref={wrapRef}>
        <Search size={16} />
        <input
          value={query}
          autoFocus
          placeholder="Начните вводить фамилию"
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            setQuery(e.target.value)
            setOpen(true)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && visible[0]) {
              e.preventDefault()
              add(visible[0])
            }
          }}
        />
      </div>
      <FloatMenu open={open} anchor={wrapRef} onClose={() => setOpen(false)}>
        {loading && !visible.length ? <div className="kx-float-empty">Ищем сотрудников…</div> : null}
        {error ? <div className="kx-float-empty">{error}</div> : null}
        {!loading && !error && !visible.length ? (
          <div className="kx-float-empty">
            {query.trim() ? 'Никого не нашли' : 'Введите фамилию или имя'}
          </div>
        ) : null}
        {visible.map((user) => (
          <button key={user.id || user.fio} type="button" className="kx-float-item" onClick={() => add(user)}>
            <span className="kx-avatar">{initials(user.fio)}</span>
            <span className="kx-result-text">
              <span>{user.fio}</span>
              {user.department || user.position ? <small>{user.department || user.position}</small> : null}
            </span>
          </button>
        ))}
      </FloatMenu>
      {selected.length ? (
        <ul className="kx-people">
          {selected.map((user) => (
            <li key={personKey(user)} className="kx-person">
              <span className="kx-avatar kx-avatar-sm">{initials(user.fio)}</span>
              <span className="kx-person-name">{user.fio}</span>
              <RightSwitch
                value={user.permission || 'read'}
                onChange={(permission) =>
                  onChange(selected.map((item) => (samePerson(item, user) ? { ...item, permission } : item)))
                }
              />
              <button
                type="button"
                className="kx-person-remove"
                aria-label={`Убрать ${user.fio}`}
                onClick={() => onChange(selected.filter((item) => !samePerson(item, user)))}
              >
                <X size={14} />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

async function employeesOf(department: string): Promise<DirectoryUser[]> {
  const fromStructure = await api.listDepartmentPeople(department).catch(() => [] as DirectoryUser[])
  if (fromStructure.length) return fromStructure.filter((user) => user.fio.trim())
  const users = await api.listDirectoryUsers(department).catch(() => [] as DirectoryUser[])
  const key = department.trim().toLowerCase()
  return users.filter(
    (user) => user.fio.trim() && user.department.trim().toLowerCase() === key
  )
}

function DeptPersonAdd({
  taken,
  onAdd
}: {
  taken: ExplorerAccessUser[]
  onAdd: (user: DirectoryUser) => void
}): React.JSX.Element {
  const [openForm, setOpenForm] = useState(false)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<DirectoryUser[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)
  const seq = useRef(0)

  useEffect(() => {
    if (!openForm || !open) return
    const id = ++seq.current
    const timer = window.setTimeout(() => {
      setLoading(true)
      void searchEmployees(query.trim())
        .then((found) => {
          if (id !== seq.current) return
          setResults(found)
          setLoading(false)
        })
        .catch(() => {
          if (id !== seq.current) return
          setResults([])
          setLoading(false)
        })
    }, query.trim() ? 160 : 0)
    return () => window.clearTimeout(timer)
  }, [open, openForm, query])

  const visible = results.filter((user) => user.fio.trim() && !taken.some((item) => samePerson(item, user))).slice(0, 8)

  if (!openForm) {
    return (
      <button type="button" className="kx-dept-plus" aria-label="Добавить сотрудника" onClick={() => setOpenForm(true)}>
        <Plus size={18} />
      </button>
    )
  }

  return (
    <div className="kx-dept-add">
      <div className="kx-search" ref={wrapRef}>
        <Search size={16} />
        <input
          value={query}
          autoFocus
          placeholder="Фамилия сотрудника"
          onFocus={() => setOpen(true)}
          onChange={(event) => {
            setQuery(event.target.value)
            setOpen(true)
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && visible[0]) {
              event.preventDefault()
              onAdd(visible[0])
              setQuery('')
              setOpenForm(false)
            }
            if (event.key === 'Escape') setOpenForm(false)
          }}
        />
      </div>
      <FloatMenu open={open} anchor={wrapRef} onClose={() => setOpen(false)}>
        {loading && !visible.length ? <div className="kx-float-empty">Ищем сотрудников…</div> : null}
        {!loading && !visible.length ? <div className="kx-float-empty">Никого не нашли</div> : null}
        {visible.map((user) => (
          <button
            key={user.id || user.fio}
            type="button"
            className="kx-float-item"
            onClick={() => {
              onAdd(user)
              setQuery('')
              setOpenForm(false)
            }}
          >
            <span className="kx-avatar">{initials(user.fio)}</span>
            <span className="kx-result-text">
              <span>{user.fio}</span>
              {user.position || user.department ? <small>{user.position || user.department}</small> : null}
            </span>
          </button>
        ))}
      </FloatMenu>
    </div>
  )
}

function DepartmentBlocks({
  departments,
  users,
  onChange
}: {
  departments: string[]
  users: ExplorerAccessUser[]
  onChange: (departments: string[], users: ExplorerAccessUser[]) => void
}): React.JSX.Element {
  const [query, setQuery] = useState('')
  const [all, setAll] = useState<string[] | null>(null)
  const [open, setOpen] = useState(false)
  const [pending, setPending] = useState('')
  const [error, setError] = useState('')
  const wrapRef = useRef<HTMLDivElement>(null)
  const tried = useRef(new Set<string>())

  useEffect(() => {
    let alive = true
    void api
      .listDepartmentNames()
      .catch(() => [] as string[])
      .then((items) => {
        if (alive) setAll(items)
      })
    return () => {
      alive = false
    }
  }, [])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (all || []).filter(
      (dept) =>
        !isLiquidatedDepartment(dept) &&
        !departments.includes(dept) &&
        (!q || dept.toLowerCase().includes(q))
    )
  }, [all, query, departments])

  const add = (name: string): void => {
    if (pending || tried.current.has(name)) return
    tried.current.add(name)
    setPending(name)
    setError('')
    void employeesOf(name)
      .then((members) => {
        const block: ExplorerAccessUser[] = members.map((member) => {
          const prev = users.find((user) => samePerson(user, member))
          return {
            id: member.id || prev?.id || '',
            fio: member.fio,
            permission: prev?.permission || 'read',
            department: name
          }
        })
        const blockKeys = new Set(block.map((user) => personKey(user)))
        const rest = users.filter((user) => user.department !== name && !blockKeys.has(personKey(user)))
        onChange(departments.includes(name) ? departments : [...departments, name], [...rest, ...block])
        if (!block.length) setError(`В «${name}» не нашли сотрудников`)
        setQuery('')
        setOpen(false)
      })
      .catch((err: unknown) => setError(errorText(err, 'Не удалось загрузить сотрудников отдела')))
      .finally(() => setPending(''))
  }

  useEffect(() => {
    const missing = departments.find(
      (dept) => !tried.current.has(dept) && !users.some((user) => user.department === dept)
    )
    if (!missing || pending || tried.current.has(missing)) return
    add(missing)
  }, [departments, users, pending])

  const remove = (name: string): void => {
    tried.current.delete(name)
    onChange(
      departments.filter((dept) => dept !== name),
      users.filter((user) => user.department !== name)
    )
  }

  const setAllRights = (name: string, permission: ExplorerRight): void => {
    onChange(
      departments,
      users.map((user) => (user.department === name ? { ...user, permission } : user))
    )
  }

  const setPersonRight = (person: ExplorerAccessUser, permission: ExplorerRight): void => {
    onChange(
      departments,
      users.map((user) => (samePerson(user, person) && user.department === person.department ? { ...user, permission } : user))
    )
  }

  return (
    <div className="kx-picker">
      <div className="kx-search" ref={wrapRef}>
        <Search size={16} />
        <input
          value={query}
          autoFocus
          placeholder="Найдите отдел или подразделение"
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            setQuery(e.target.value)
            setOpen(true)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && visible[0]) {
              e.preventDefault()
              add(visible[0])
            }
          }}
        />
      </div>
      <FloatMenu open={open} anchor={wrapRef} onClose={() => setOpen(false)} tall>
        {all === null || pending ? <div className="kx-float-empty">{pending ? 'Загружаем сотрудников…' : 'Загружаем отделы…'}</div> : null}
        {all !== null && !pending && !visible.length ? <div className="kx-float-empty">Ничего не нашли</div> : null}
        {visible.map((dept) => (
          <button key={dept} type="button" className="kx-float-item" onClick={() => add(dept)}>
            <span className="kx-avatar">
              <Building2 size={14} />
            </span>
            <span className="kx-result-text">
              <span>{dept}</span>
            </span>
          </button>
        ))}
      </FloatMenu>
      {error ? <p className="kx-note">{error}</p> : null}
      {departments.map((dept) => {
        const members = users.filter((user) => user.department === dept)
        return (
          <section key={dept} className="kx-dept">
            <header className="kx-dept-head">
              <span>{dept}</span>
              <span className="kx-dept-actions">
                <button type="button" onClick={() => setAllRights(dept, 'read')}>
                  Всем чтение
                </button>
                <button type="button" onClick={() => setAllRights(dept, 'write')}>
                  Всем запись
                </button>
                <button type="button" aria-label={`Убрать ${dept}`} onClick={() => remove(dept)}>
                  <X size={14} />
                </button>
              </span>
            </header>
            {members.length ? (
              <ul className="kx-people">
                {members.map((user) => (
                  <li key={personKey(user)} className="kx-person">
                    <span className="kx-avatar kx-avatar-sm">{initials(user.fio)}</span>
                    <span className="kx-person-name">{user.fio}</span>
                    <RightSwitch value={user.permission || 'read'} onChange={(permission) => setPersonRight(user, permission)} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="kx-note">В этом отделе пока нет сотрудников.</p>
            )}
            <DeptPersonAdd
              taken={users}
              onAdd={(picked) => {
                if (users.some((item) => samePerson(item, picked))) return
                onChange(departments, [
                  ...users,
                  { id: picked.id || '', fio: picked.fio, permission: 'read', department: dept }
                ])
              }}
            />
          </section>
        )
      })}
    </div>
  )
}

function AccessPicker({
  value,
  onChange
}: {
  value: ExplorerAccess
  onChange: (next: ExplorerAccess) => void
}): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const btnRef = useRef<HTMLButtonElement>(null)
  const current = ACCESS_OPTIONS.find((item) => item.mode === value.mode) || ACCESS_OPTIONS[0]
  const Icon = current.icon

  return (
    <section className="kx-section">
      <h4 className="kx-label">Кто может открыть</h4>
      <button
        ref={btnRef}
        type="button"
        className="kx-select"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="kx-select-icon">
          <Icon size={16} />
        </span>
        <span className="kx-select-text">
          <span>{ACCESS_LABELS[value.mode]}</span>
          <small>{current.hint}</small>
        </span>
        <ChevronDown size={16} />
      </button>
      <FloatMenu open={open} anchor={btnRef} onClose={() => setOpen(false)}>
        {ACCESS_OPTIONS.map(({ mode, icon: ModeIcon, hint }) => {
          const active = value.mode === mode
          return (
            <button
              key={mode}
              type="button"
              className={active ? 'kx-float-item active' : 'kx-float-item'}
              onClick={() => {
                onChange({ ...value, mode })
                setOpen(false)
              }}
            >
              <span className="kx-avatar">
                <ModeIcon size={14} />
              </span>
              <span className="kx-result-text">
                <span>{ACCESS_LABELS[mode]}</span>
                <small>{hint}</small>
              </span>
              {active ? <Check size={16} /> : null}
            </button>
          )
        })}
      </FloatMenu>
      {value.mode === 'users' ? (
        <PeoplePicker
          selected={value.users.filter((user) => !user.department)}
          onChange={(users) =>
            onChange({ ...value, users: [...value.users.filter((user) => user.department), ...users] })
          }
        />
      ) : null}
      {value.mode === 'department' ? (
        <DepartmentBlocks
          departments={value.departments}
          users={value.users}
          onChange={(departments, users) => onChange({ ...value, departments, users })}
        />
      ) : null}
      {value.mode === 'all' ? (
        <section className="kx-section">
          <h4 className="kx-label">Какие права у всех</h4>
          <RightSwitch
            value={value.allPermission || 'read'}
            onChange={(allPermission) => onChange({ ...value, allPermission })}
          />
        </section>
      ) : null}
    </section>
  )
}

function Modal({
  title,
  onClose,
  footer,
  children
}: {
  title: string
  onClose: () => void
  footer: React.ReactNode
  children: React.ReactNode
}): React.JSX.Element {
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key !== 'Escape') return
      if (document.querySelector('[data-kx-float]')) return
      closeRef.current()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  return createPortal(
    <div className="kx-modal-backdrop" onMouseDown={onClose}>
      <div className="kx-modal" role="dialog" aria-label={title} onMouseDown={(e) => e.stopPropagation()}>
        <header className="kx-modal-head">
          <h3>{title}</h3>
          <button type="button" className="kx-close" aria-label="Закрыть" onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <div className="kx-modal-body">{children}</div>
        <footer className="kx-modal-foot">{footer}</footer>
      </div>
    </div>,
    document.body
  )
}

export function NewFolderDialog({
  parentId,
  onClose,
  onCreated
}: {
  parentId: string | null
  onClose: () => void
  onCreated: (item: ExplorerItem) => void
}): React.JSX.Element {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useReportError(error)

  const submit = (): void => {
    if (!name.trim() || busy) return
    setBusy(true)
    setError('')
    void api
      .createExplorerFolder(name.trim(), parentId)
      .then(onCreated)
      .catch((err: unknown) => setError(errorText(err, 'Не удалось создать папку')))
      .finally(() => setBusy(false))
  }

  return (
    <Modal
      title="Новая папка"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="kx-pill" onClick={onClose}>
            Отмена
          </button>
          <button
            type="button"
            className="kx-pill kx-pill-primary"
            disabled={!name.trim() || busy}
            onClick={submit}
          >
            {busy ? 'Создаём…' : 'Создать'}
          </button>
        </>
      }
    >
      <input
        className="kx-input"
        autoFocus
        value={name}
        placeholder="Название папки"
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') submit()
        }}
      />
    </Modal>
  )
}

export function NewFileDialog({
  parentId,
  onClose,
  onCreated
}: {
  parentId: string | null
  onClose: () => void
  onCreated: (item: ExplorerItem) => void
}): React.JSX.Element {
  const [mode, setMode] = useState<'blank' | 'upload'>('blank')
  const [name, setName] = useState('')
  const [sourcePath, setSourcePath] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [access, setAccess] = useState<ExplorerAccess>(PRIVATE_ACCESS)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useReportError(error)

  const takeSource = (path: string): void => {
    if (!path) return
    setSourcePath(path)
    setName(path.split(/[\\/]/).pop() || '')
  }

  const pickFile = (): void => {
    void window.api
      .openFile({ title: 'Выберите файл', properties: ['openFile'] })
      .then((paths) => takeSource(paths[0] || ''))
  }

  const nameHasExtension = /\.[^.\s]+$/.test(name.trim())
  const canSubmit =
    !busy && nameHasExtension && accessIsComplete(access) && (mode === 'blank' || Boolean(sourcePath))

  const submit = (): void => {
    if (!canSubmit) return
    setBusy(true)
    setError('')
    const request =
      mode === 'blank'
        ? api.createExplorerBlankFile(name.trim(), parentId, access)
        : api.uploadExplorerFile(sourcePath, name.trim(), parentId, access)
    void request
      .then(onCreated)
      .catch((err: unknown) => setError(errorText(err, 'Не удалось создать файл')))
      .finally(() => setBusy(false))
  }

  return (
    <Modal
      title="Новый файл"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="kx-pill" onClick={onClose}>
            Отмена
          </button>
          <button type="button" className="kx-pill kx-pill-primary" disabled={!canSubmit} onClick={submit}>
            {busy ? 'Сохраняем…' : mode === 'blank' ? 'Создать' : 'Загрузить'}
          </button>
        </>
      }
    >
      <div className="kx-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'blank'}
          className={mode === 'blank' ? 'active' : ''}
          onClick={() => setMode('blank')}
        >
          Создать
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'upload'}
          className={mode === 'upload' ? 'active' : ''}
          onClick={() => setMode('upload')}
        >
          Загрузить
        </button>
      </div>

      {mode === 'upload' ? (
        <button
          type="button"
          className={dragOver ? 'kx-drop over' : sourcePath ? 'kx-drop filled' : 'kx-drop'}
          onClick={pickFile}
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragOver(false)
            const file = e.dataTransfer.files[0]
            if (file) takeSource(window.api.getPathForFile(file))
          }}
        >
          <FileUp size={20} />
          {sourcePath ? (
            <span className="kx-drop-text">
              <span>{sourcePath.split(/[\\/]/).pop()}</span>
              <small>Нажмите, чтобы выбрать другой</small>
            </span>
          ) : (
            <span className="kx-drop-text">
              <span>Перетащите файл сюда</span>
              <small>или нажмите, чтобы выбрать на компьютере</small>
            </span>
          )}
        </button>
      ) : null}

      <section className="kx-section">
        <h4 className="kx-label">Название</h4>
        <input
          className="kx-input"
          autoFocus={mode === 'blank'}
          value={name}
          placeholder="план работ.docx"
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') submit()
          }}
        />
        {name.trim() && !nameHasExtension ? (
          <p className="kx-note">Добавьте расширение: .docx, .xlsx, .txt</p>
        ) : null}
      </section>

      <AccessPicker value={access} onChange={setAccess} />
    </Modal>
  )
}

export function AccessDialog({
  item,
  onClose,
  onSaved
}: {
  item: ExplorerItem
  onClose: () => void
  onSaved: (item: ExplorerItem) => void
}): React.JSX.Element {
  const [access, setAccess] = useState<ExplorerAccess | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useReportError(error)

  useEffect(() => {
    let alive = true
    void api
      .getExplorerAccess(item.id)
      .then((value) => {
        if (alive) setAccess(value)
      })
      .catch((err: unknown) => {
        if (alive) setError(errorText(err, 'Не удалось загрузить доступы'))
      })
    return () => {
      alive = false
    }
  }, [item.id])

  const canSave = Boolean(access) && !busy && accessIsComplete(access as ExplorerAccess)

  const submit = (): void => {
    if (!access || !canSave) return
    setBusy(true)
    setError('')
    void api
      .updateExplorerAccess(item.id, access)
      .then(onSaved)
      .catch((err: unknown) => setError(errorText(err, 'Не удалось сохранить доступ')))
      .finally(() => setBusy(false))
  }

  return (
    <Modal
      title="Доступ"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="kx-pill" onClick={onClose}>
            Отмена
          </button>
          <button type="button" className="kx-pill kx-pill-primary" disabled={!canSave} onClick={submit}>
            {busy ? 'Сохраняем…' : 'Сохранить'}
          </button>
        </>
      }
    >
      {access ? <AccessPicker value={access} onChange={setAccess} /> : <p className="kx-note">Загружаем…</p>}
    </Modal>
  )
}
