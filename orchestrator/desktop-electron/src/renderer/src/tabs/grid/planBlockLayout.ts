import type { CSSProperties } from 'react'
import type { TodayPlanBlock } from './todayDemoData'

export const PLAN_BLOCK_ROW_HEIGHT = 48
export const PLAN_TRACK_PAD = 6
export const PLAN_TRACK_ROW_GAP = 4

export type PositionedPlanBlock = TodayPlanBlock & {
  row: number
  rowCount: number
}

export type PlanTrackLayout = {
  blocks: PositionedPlanBlock[]
  rowCount: number
  heightPx: number
}

export function planTrackHeightPx(rowCount: number): number {
  if (rowCount <= 0) return PLAN_BLOCK_ROW_HEIGHT + PLAN_TRACK_PAD * 2
  return (
    PLAN_TRACK_PAD * 2 +
    rowCount * PLAN_BLOCK_ROW_HEIGHT +
    Math.max(rowCount - 1, 0) * PLAN_TRACK_ROW_GAP
  )
}

/** Outlook-style: пересечения — отдельные горизонтальные строки, ширина по времени. */
export function layoutPlanTrack(blocks: TodayPlanBlock[]): PlanTrackLayout {
  if (!blocks.length) {
    return { blocks: [], rowCount: 0, heightPx: planTrackHeightPx(0) }
  }

  const sorted = [...blocks].sort(
    (left, right) => left.startHour - right.startHour || left.endHour - right.endHour
  )

  const rowEnds: number[] = []
  const placed: PositionedPlanBlock[] = []

  for (const block of sorted) {
    let row = rowEnds.findIndex((endHour) => endHour <= block.startHour + 1e-6)
    if (row === -1) {
      row = rowEnds.length
      rowEnds.push(block.endHour)
    } else {
      rowEnds[row] = block.endHour
    }
    placed.push({ ...block, row, rowCount: 0 })
  }

  const rowCount = Math.max(rowEnds.length, 1)
  for (const block of placed) {
    block.rowCount = rowCount
  }

  return {
    blocks: placed,
    rowCount,
    heightPx: planTrackHeightPx(rowCount)
  }
}

export function planBlockStyle(
  block: PositionedPlanBlock,
  dayStart: number,
  dayEnd: number
): CSSProperties {
  const daySpan = dayEnd - dayStart
  const leftPct = ((block.startHour - dayStart) / daySpan) * 100
  const widthPct = ((block.endHour - block.startHour) / daySpan) * 100
  const topPx = PLAN_TRACK_PAD + block.row * (PLAN_BLOCK_ROW_HEIGHT + PLAN_TRACK_ROW_GAP)

  return {
    left: `max(0px, calc(${leftPct}% + 1px))`,
    width: `max(28px, calc(${Math.max(widthPct, 2.2)}% - 2px))`,
    top: `${topPx}px`,
    height: `${PLAN_BLOCK_ROW_HEIGHT}px`,
    bottom: 'auto',
    zIndex: block.lane === 'lunch' ? 1 : block.row + 2
  }
}
