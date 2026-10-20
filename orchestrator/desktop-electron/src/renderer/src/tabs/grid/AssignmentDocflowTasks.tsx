import { CheckCircle2, Clock3, Lock, MessageSquareText, Paperclip } from 'lucide-react'
import { DocflowReviewButtons } from '../../components/agentfeed/DocflowActionsBlock'
import type { ClosureCheckAssignment, ClosureCheckLine } from '../../components/agentfeed/docflowActions'
import { formatCorrespondenceDate } from '../../workplace/fetchDocflowCorrespondence'
import type { AssignmentCard, AssignmentFile, AssignmentTask } from '../../workplace/fetchDocflowAssignments'
import { DocflowFileOpenButton } from './DocflowAttachments'
import './docflowGrid.css'

const GUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

function day(value: string): string {
  if (!value) return ''
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (dateOnly) return `${dateOnly[3]}.${dateOnly[2]}.${dateOnly[1]}`
  return formatCorrespondenceDate(value).replace(/ 00:00$/, '')
}

function personKey(name: string): string {
  return name.toLowerCase().replace(/ё/g, 'е').split(/\s+/).filter(Boolean).slice(0, 2).join(' ')
}

/** Мероприятия ERP, где исполнитель задачи — ответственный: подсказка, когда в ДО задачу отправили без текста. */
function measuresOf(card: AssignmentCard, performer: string): string[] {
  const key = personKey(performer)
  if (!key) return []
  return card.assignment.lines
    .filter((line) => line.text && personKey(line.executor) === key)
    .map((line) => line.text)
}

type TaskText = { text: string; empty?: boolean }

/** Текст задачи ДО; «п. N» в описании — ссылка автора на мероприятие N, пустой текст — мероприятие исполнителя. */
function taskText(card: AssignmentCard, task: AssignmentTask): TaskText {
  const point = /^п\.?\s*(\d+)\.?$/i.exec(task.title.trim())
  if (point) {
    const line = card.assignment.lines.find((item) => item.n === Number(point[1]))
    if (line?.text) return { text: line.text }
  }
  if (task.title) return { text: task.title }
  const measures = measuresOf(card, task.performer)
  if (measures.length) return { text: measures.join('\n') }
  return { text: 'Текст задачи в Документообороте не заполнен', empty: true }
}

function isOverdue(task: AssignmentTask, stage: TaskStage): boolean {
  if (stage !== 'work' || !/^\d{4}-\d{2}-\d{2}/.test(task.due)) return false
  const today = new Date()
  const iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
  return task.due.slice(0, 10) < iso
}

type TaskStage = 'work' | 'done' | 'closed'

const STAGE_LABEL: Record<TaskStage, string> = {
  work: 'На исполнении',
  done: 'Выполнено',
  closed: 'Закрыто'
}

/** Закрыто — автор принял; выполнено — исполнитель отчитался, проверки ещё нет; иначе задача у исполнителя. */
function taskStage(task: AssignmentTask): TaskStage {
  if (task.executed) return 'closed'
  if (task.state === 'исполнитель отчитался, ждёт проверки' || task.state === 'исполнитель отметил выполнение') {
    return 'done'
  }
  return 'work'
}

function StageIcon({ stage }: { stage: TaskStage }): React.JSX.Element {
  if (stage === 'closed') return <Lock size={14} aria-hidden />
  if (stage === 'done') return <CheckCircle2 size={14} aria-hidden />
  return <Clock3 size={14} aria-hidden />
}

export function AssignmentFileList({ files }: { files: AssignmentFile[] }): React.JSX.Element {
  return (
    <ul className="docflow-files assignment-files">
      {files.map((file) => (
        <li key={file.id} title={file.created ? `Загружен ${day(file.created)}` : undefined}>
          <DocflowFileOpenButton file={file}>
            <Paperclip size={12} aria-hidden />
            <span className="assignment-file-name">
              {file.name}
              {file.extension ? `.${file.extension}` : ''}
            </span>
          </DocflowFileOpenButton>
        </li>
      ))}
    </ul>
  )
}

function verdictTone(conclusion: string): 'close' | 'partial' | 'none' {
  const value = conclusion.toLowerCase()
  if (value.startsWith('можно закрыв') || value.startsWith('выполнено')) return 'close'
  if (value.includes('доработ') || value.includes('частично')) return 'partial'
  return 'none'
}

function checkOf(check: ClosureCheckAssignment | undefined, index: number): ClosureCheckLine | undefined {
  return check?.lines.find((line) => line.line === `задача ${index + 1}`) ?? check?.lines[index]
}

function AgentVerdict({ line }: { line: ClosureCheckLine }): React.JSX.Element {
  const tone = verdictTone(line.conclusion)
  return (
    <div className={`assignment-task-verdict tone-${tone}`}>
      <div className="assignment-task-verdict-head">
        <span
          className={`assignment-task-stage stage-${tone === 'close' ? 'closed' : tone === 'partial' ? 'return' : 'work'}`}
        >
          {line.conclusion || 'Нет вердикта'}
        </span>
      </div>
      {line.comment ? <p className="assignment-task-verdict-text">{line.comment}</p> : null}
    </div>
  )
}

function ExecutorAnswer({ task }: { task: AssignmentTask }): React.JSX.Element {
  const comments = task.comments.length
    ? task.comments
    : task.result
      ? [{ step: '', performer: task.performer, begin: '', comment: task.result }]
      : []
  if (!comments.length && !task.files.length) {
    return <p className="assignment-task-answer is-empty">Исполнитель пока не ответил</p>
  }
  return (
    <div className="assignment-task-answer">
      <div className="assignment-task-answer-label">Ответ исполнителя</div>
      {comments.map((entry, index) => (
        <div key={`${task.id}-c${index}`} className="assignment-task-comment">
          <MessageSquareText size={12} aria-hidden />
          <div>
            <p>{entry.comment}</p>
            {entry.begin ? <small>{day(entry.begin)}</small> : null}
          </div>
        </div>
      ))}
      {task.files.length ? <AssignmentFileList files={task.files} /> : null}
    </div>
  )
}

function reviewTaskId(task: AssignmentTask, verdict?: ClosureCheckLine): string {
  const ids = [task.openCheckTaskId, verdict?.action?.taskId, task.openExecuteTaskId, verdict?.openTaskId, task.id]
  return ids.find((id) => GUID_RE.test(id)) || ''
}

function TaskAuthorActions({
  task,
  verdict,
  onDone
}: {
  task: AssignmentTask
  verdict?: ClosureCheckLine
  onDone?: () => void
}): React.JSX.Element | null {
  if (taskStage(task) === 'closed') return null
  const taskId = reviewTaskId(task, verdict)
  if (!taskId) return null
  const waitingCheck = Boolean(task.openCheckTaskId) || taskStage(task) === 'done'
  return (
    <div className="assignment-task-verdict-actions">
      <DocflowReviewButtons
        taskId={taskId}
        closeAction={waitingCheck ? 'close' : 'close_without_report'}
        title={task.openCheckName || task.title}
        step={task.openCheckStep}
        comment={verdict?.comment || ''}
        onDone={onDone}
      />
    </div>
  )
}

/** Задачи поручения в 1С:Документооборот: текст, исполнитель, срок, стадия и ответ исполнителя. */
export function AssignmentDocflowTasks({
  card,
  check,
  onTaskChanged
}: {
  card: AssignmentCard
  check?: ClosureCheckAssignment
  onTaskChanged?: () => void
}): React.JSX.Element {
  const { tasks } = card
  return (
    <>
      {tasks.length ? (
        <ul className="assignment-tasks">
          {tasks.map((task, index) => {
            const stage = taskStage(task)
            const text = taskText(card, task)
            const overdue = isOverdue(task, stage)
            const verdict = checkOf(check, index)
            return (
              <li key={task.id} className={`assignment-task stage-${stage}`}>
                <div className="assignment-task-head">
                  <span className={`assignment-task-stage stage-${stage}`} title={task.state}>
                    <StageIcon stage={stage} /> {STAGE_LABEL[stage]}
                  </span>
                  {task.due ? (
                    <span className={`assignment-task-due${overdue ? ' is-overdue' : ''}`}>
                      {overdue ? 'просрочено · ' : ''}срок {day(task.due)}
                    </span>
                  ) : null}
                </div>
                <p className={`assignment-task-text${text.empty ? ' is-empty' : ''}`}>{text.text}</p>
                <div className="assignment-task-performer">{task.performer || '—'}</div>
                <ExecutorAnswer task={task} />
                {verdict ? <AgentVerdict line={verdict} /> : null}
                <TaskAuthorActions task={task} verdict={verdict} onDone={onTaskChanged} />
              </li>
            )
          })}
        </ul>
      ) : (
        <p className="docflow-muted">По поручению в Документообороте нет задач.</p>
      )}
      {card.missingExecutors.length ? (
        <p className="docflow-muted">Нет задачи в Документообороте: {card.missingExecutors.join(', ')}</p>
      ) : null}
      {card.note ? <p className="docflow-muted">{card.note}</p> : null}
    </>
  )
}
