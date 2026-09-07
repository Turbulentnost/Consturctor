export type TimingPhase = 'agent' | 'human' | 'idle'

export interface LiveTiming {
  phase: TimingPhase
  phaseStartedMs: number | null
  agentWorkMs: number
  humanWaitMs: number
}

export const EMPTY_TIMING: LiveTiming = {
  phase: 'idle',
  phaseStartedMs: null,
  agentWorkMs: 0,
  humanWaitMs: 0
}

export function durationLabel(ms: number): string {
  const value = Math.max(0, Math.round(ms))
  if (value < 1000) return '0 с'
  const sec = Math.floor(value / 1000)
  if (sec < 60) return `${sec} с`
  const minutes = Math.floor(sec / 60)
  const rest = sec % 60
  if (minutes < 60) return rest ? `${minutes} мин ${rest} с` : `${minutes} мин`
  const hours = Math.floor(minutes / 60)
  const minRest = minutes % 60
  return minRest ? `${hours} ч ${minRest} мин` : `${hours} ч`
}

function accrue(timing: LiveTiming, at: number): LiveTiming {
  if (!timing.phaseStartedMs || timing.phase === 'idle') return timing
  const delta = Math.max(0, at - timing.phaseStartedMs)
  if (!delta) return { ...timing, phaseStartedMs: at }
  if (timing.phase === 'agent') {
    return { ...timing, agentWorkMs: timing.agentWorkMs + delta, phaseStartedMs: at }
  }
  if (timing.phase === 'human') {
    return { ...timing, humanWaitMs: timing.humanWaitMs + delta, phaseStartedMs: at }
  }
  return timing
}

export function beginAgentPhase(timing: LiveTiming, at = Date.now()): LiveTiming {
  if (timing.phase === 'agent') return timing
  const next = accrue(timing, at)
  return { ...next, phase: 'agent', phaseStartedMs: at }
}

export function beginHumanPhase(timing: LiveTiming, at = Date.now()): LiveTiming {
  if (timing.phase === 'human') return timing
  const next = accrue(timing, at)
  return { ...next, phase: 'human', phaseStartedMs: at }
}

export function closeTiming(timing: LiveTiming, at = Date.now()): LiveTiming {
  const next = accrue(timing, at)
  return { ...next, phase: 'idle', phaseStartedMs: null }
}

export function liveTotals(timing: LiveTiming, now = Date.now()): { agentMs: number; humanMs: number } {
  const open =
    timing.phase !== 'idle' && timing.phaseStartedMs != null ? Math.max(0, now - timing.phaseStartedMs) : 0
  return {
    agentMs: timing.agentWorkMs + (timing.phase === 'agent' ? open : 0),
    humanMs: timing.humanWaitMs + (timing.phase === 'human' ? open : 0)
  }
}
