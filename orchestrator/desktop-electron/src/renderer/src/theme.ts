// Blue glass palette for Orchestrator (Constructor used emerald).
// Today tab overrides shell to light via `.app-root.shell-today`.
export const theme = {
  sidebarTop: '#1565C0',
  sidebarMiddle: '#0D3B73',
  sidebarBottom: '#061428',
  mint: '#7EB6FF',
  white: '#F7FAFD',
  textLight: '#E8F1FB',
  textMuted: '#9BB4D0',
  mainText: '#10141A',
  contentBg: '#F7FAFD',
  contentMuted: '#6B7380',
  activeBg: '#FFFFFF',
  activeFg: '#10141A',
  error: '#ff8a80',
  cardBorder: 'rgba(16, 20, 26, 0.10)'
} as const

export type Theme = typeof theme
