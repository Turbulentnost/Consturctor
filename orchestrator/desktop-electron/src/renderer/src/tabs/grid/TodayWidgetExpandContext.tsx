import { createContext, useContext } from 'react'

export const TodayWidgetExpandContext = createContext(false)

export function useTodayWidgetExpanded(): boolean {
  return useContext(TodayWidgetExpandContext)
}

/** Открыть свой виджет на весь экран из его содержимого (клик по строке). */
export const TodayWidgetRequestExpandContext = createContext<(() => void) | null>(null)

export function useRequestTodayWidgetExpand(): (() => void) | null {
  return useContext(TodayWidgetRequestExpandContext)
}
