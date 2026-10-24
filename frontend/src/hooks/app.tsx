import { createContext, useContext, type ReactNode } from 'react'

interface AppCtx {
  revealLabel: string
}

const Ctx = createContext<AppCtx>({ revealLabel: 'Show in folder' })

export function AppProvider({ revealLabel, children }: { revealLabel: string; children: ReactNode }) {
  return <Ctx.Provider value={{ revealLabel }}>{children}</Ctx.Provider>
}

export const useApp = () => useContext(Ctx)
