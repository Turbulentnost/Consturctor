import { createContext, useContext } from 'react'

export const TodayWidgetExpandContext = createContext(false)

export function useTodayWidgetExpanded(): boolean {
  return useContext(TodayWidgetExpandContext)
}
