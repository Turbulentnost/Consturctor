import type { AgentRunnerEvent, WorkflowFileItem } from '../api/types'

function fileBaseName(raw: string): string {
  return raw.replace(/\\/g, '/').split('/').pop()?.trim() || ''
}

function mentionedOutputNames(answer: string, events: AgentRunnerEvent[]): Set<string> {
  const names = new Set<string>()
  const add = (raw: string): void => {
    const name = fileBaseName(raw)
    if (name && /\.[A-Za-z0-9]{1,8}$/.test(name)) names.add(name.toLowerCase())
  }
  for (const match of answer.matchAll(/`([^`]+)`/g)) add(match[1])
  for (const match of answer.matchAll(/([^\s`"'<>]+\.(?:xlsx|xls|docx|pdf|md|csv|txt))/gi)) {
    add(match[1])
  }
  for (const event of events) {
    if (event.text) {
      for (const match of event.text.matchAll(/`([^`]+)`/g)) add(match[1])
    }
    const result = event.result
    if (result && typeof result === 'object') {
      const row = result as Record<string, unknown>
      for (const key of ['file', 'path', 'filename', 'result_file']) {
        if (typeof row[key] === 'string') add(row[key])
      }
    }
  }
  return names
}

function isAgentOutput(file: WorkflowFileItem): boolean {
  return file.source === 'agent' || file.scope === 'run_output'
}

export function filesForHistoryRun(
  files: WorkflowFileItem[],
  runId: string,
  answer: string,
  events: AgentRunnerEvent[]
): WorkflowFileItem[] {
  const mentioned = mentionedOutputNames(answer, events)
  const wanted = (runId || '').trim()
  return files.filter((file) => {
    if (!isAgentOutput(file)) return false
    const rid = (file.runId || '').trim()
    if (wanted && rid && rid !== wanted && rid !== 'local') {
      return mentioned.has((file.name || '').toLowerCase())
    }
    if (wanted && rid === wanted) return true
    return mentioned.has((file.name || '').toLowerCase())
  })
}
