// Emerald glass palette ported from desktop/app/ui/theme.py
export const theme = {
  sidebarTop: '#08745F',
  sidebarMiddle: '#06483D',
  sidebarBottom: '#011713',
  mint: '#62E0BE',
  white: '#F7FBFA',
  textLight: '#EAF7F3',
  textMuted: '#A8C8BF',
  mainText: '#101817',
  contentBg: '#FAFCFB',
  contentMuted: '#6B7773',
  activeBg: '#FFFFFF',
  activeFg: '#101817',
  error: '#ff8a80',
  cardBorder: 'rgba(16, 24, 23, 0.10)'
} as const

export type Theme = typeof theme
