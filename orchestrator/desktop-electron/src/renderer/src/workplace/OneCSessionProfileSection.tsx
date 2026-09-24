import { useCallback, useState } from 'react'
import type { UserProfile } from '../api/types'
import { api } from '../api/client'
import { agentClient } from '../api/agent'
import {
  buildSidecarSessionFields,
  loadOneCSessionProfile,
  saveOneCSessionProfileFromUser,
  type OneCSessionProfile
} from '../store/onecSessionProfile'
import { comCredentials, hasComPassword } from '../store/session'
import { loadDocflowDelegates, parseDelegateText, saveDocflowDelegates } from '../store/docflowDelegates'
import { useGridDataRefreshContext } from './GridDataRefreshContext'

function formatWhen(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('ru-RU')
}

export function OneCSessionProfileSection({ user }: { user: UserProfile }): React.JSX.Element {
  const [profile, setProfile] = useState<OneCSessionProfile | null>(() => loadOneCSessionProfile())
  const [busy, setBusy] = useState(false)
  const [hint, setHint] = useState('')

  const refreshFromBackend = useCallback(async (): Promise<void> => {
    setBusy(true)
    setHint('')
    try {
      const token = api.getToken()
      const me = await api.me()
      const saved = saveOneCSessionProfileFromUser(me, 'me', token)
      setProfile(saved)
      setHint('Профиль обновлён из backend (api.me).')
      void agentClient.ready(token, buildSidecarSessionFields(me))
    } catch (err) {
      setHint(err instanceof Error ? err.message : 'Не удалось загрузить профиль')
    } finally {
      setBusy(false)
    }
  }, [])

  const syncSidecar = (): void => {
    const token = api.getToken()
    const fields = buildSidecarSessionFields(user)
    void agentClient
      .ready(token, fields)
      .then(() => setHint('Данные сессии отправлены в sidecar (COM).'))
      .catch(() => setHint('Sidecar недоступен'))
  }

  const creds = comCredentials()
  const display = profile || {
    orchestratorUserId: user.id,
    fio: user.fio,
    nameMail: user.nameMail,
    department: user.department,
    position: user.position,
    onecCatalogRefKey: user.onecCatalogRefKey || '',
    savedAt: '',
    source: 'manual' as const
  }

  return (
    <section className="set-card">
      <h2>Профиль 1С (временно)</h2>
      <p className="set-muted">
        Локальное сохранение Ref_Key и данных пользователя erp_pm для COM и sidecar. Не заменяет вход с
        паролем 1С.
      </p>
      <dl className="set-kv">
        <div>
          <dt>ФИО</dt>
          <dd>{display.fio || '—'}</dd>
        </div>
        <div>
          <dt>ID Orchestrator</dt>
          <dd>{display.orchestratorUserId || '—'}</dd>
        </div>
        <div>
          <dt>nameMail (1С)</dt>
          <dd>{display.nameMail || '—'}</dd>
        </div>
        <div>
          <dt>Ref_Key (Catalog_Пользователи)</dt>
          <dd className="set-mono">{display.onecCatalogRefKey || '—'}</dd>
        </div>
        <div>
          <dt>Подразделение / должность</dt>
          <dd>
            {[display.department, display.position].filter(Boolean).join(' · ') || '—'}
          </dd>
        </div>
        <div>
          <dt>Сохранено</dt>
          <dd>
            {display.savedAt ? `${formatWhen(display.savedAt)} (${display.source})` : 'ещё не сохранялось'}
          </dd>
        </div>
        <div>
          <dt>Пароль 1С в сессии</dt>
          <dd>{hasComPassword() ? 'есть (для COM)' : 'нет — войдите с паролем'}</dd>
        </div>
        <div>
          <dt>Логин COM (FIO)</dt>
          <dd>{creds.login || user.fio || '—'}</dd>
        </div>
      </dl>
      {hint ? <p className="set-muted">{hint}</p> : null}
      <div className="wp-actions">
        <button className="btn-primary" type="button" disabled={busy} onClick={() => void refreshFromBackend()}>
          {busy ? 'Загрузка…' : 'Обновить из 1С/backend'}
        </button>
        <button className="btn-ghost" type="button" onClick={syncSidecar}>
          Отправить в sidecar
        </button>
      </div>
      <DocflowDelegatesField userId={user.id || ''} />
    </section>
  )
}

function DocflowDelegatesField({ userId }: { userId: string }): React.JSX.Element {
  const { softRefresh } = useGridDataRefreshContext()
  const [saved, setSaved] = useState(() => loadDocflowDelegates(userId))
  const [text, setText] = useState(() => saved.join('\n'))
  const [note, setNote] = useState('')
  const dirty = parseDelegateText(text).join('\n') !== saved.join('\n')

  const save = (): void => {
    const next = saveDocflowDelegates(userId, parseDelegateText(text))
    setSaved(next)
    setText(next.join('\n'))
    setNote(next.length ? `Сохранено: ${next.length}. Задачи обновятся на вкладке «Задачи».` : 'Список очищен.')
    softRefresh()
  }

  return (
    <div className="set-delegates">
      <h3>Работаю также за</h3>
      <p className="set-muted">
        ФИО сотрудников, чьи задачи 1С:Документооборот вы ведёте (замещение, помощник). Их задачи появятся во вкладке
        «Задачи» с пометкой «за …», и по ним можно ставить отметки. Каждое ФИО с новой строки, как в 1С.
      </p>
      <textarea
        rows={3}
        value={text}
        placeholder="Ясыров Богдан Джумазаевич"
        onChange={(event) => setText(event.target.value)}
      />
      {note ? <p className="set-muted">{note}</p> : null}
      <div className="wp-actions">
        <button className="btn-primary" type="button" disabled={!dirty} onClick={save}>
          Сохранить
        </button>
      </div>
    </div>
  )
}
