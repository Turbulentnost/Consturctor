import { createContext, useContext } from 'react'

export type OpenReferencedFile = (fileName: string) => void

const ResultFileOpenContext = createContext<OpenReferencedFile | null>(null)

export function ResultFileOpenProvider({
  onOpen,
  children
}: {
  onOpen: OpenReferencedFile
  children: React.ReactNode
}): React.JSX.Element {
  return <ResultFileOpenContext.Provider value={onOpen}>{children}</ResultFileOpenContext.Provider>
}

export function useOpenReferencedFile(): OpenReferencedFile | null {
  return useContext(ResultFileOpenContext)
}
