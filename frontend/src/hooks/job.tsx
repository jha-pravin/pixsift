import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { api, type JobStatus } from '../api'

interface JobCtx {
  job: JobStatus | null
  /** Increments whenever library data may have changed (job progress/finish, edits, naming). */
  version: number
  bump: () => void
  refreshJob: () => void
}

const Ctx = createContext<JobCtx>({ job: null, version: 0, bump: () => {}, refreshJob: () => {} })

export function JobProvider({ children }: { children: ReactNode }) {
  const [job, setJob] = useState<JobStatus | null>(null)
  const [version, setVersion] = useState(0)
  const ticks = useRef(0)
  const bump = useCallback(() => setVersion((v) => v + 1), [])

  const refreshJob = useCallback(() => {
    api.job().then(setJob).catch(() => {})
  }, [])

  useEffect(refreshJob, [refreshJob])

  const running = job?.state === 'running'
  useEffect(() => {
    // Every second while a job runs; every 5 s when idle, to notice drives being plugged in
    // (which may start a scan by themselves).
    const t = setInterval(async () => {
      const next = await api.job().catch(() => null)
      if (!next) return
      setJob(next)
      // Refresh visible data every few seconds while running, and once when the job ends.
      // Lists refresh in place (see usePagedImages); every 15 s is plenty and keeps heavy pages light.
      if (running && (next.state !== 'running' || ++ticks.current % 15 === 0)) bump()
    }, running ? 1000 : 5000)
    return () => clearInterval(t)
  }, [running, bump])

  return <Ctx.Provider value={{ job, version, bump, refreshJob }}>{children}</Ctx.Provider>
}

export const useJob = () => useContext(Ctx)
