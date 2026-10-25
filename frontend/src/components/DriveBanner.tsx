import { useState } from 'react'
import { api } from '../api'
import { useJob } from '../hooks/job'
import { Icon } from './Icon'

/** Asks once per new drive whether to look for pictures on it. Nothing is scanned without a yes. */
export function DriveBanner() {
  const { job, refreshJob } = useJob()
  const [error, setError] = useState<string | null>(null)
  const drive = job?.new_drives?.[0]
  if (!drive) return null

  const run = (p: Promise<unknown>) => p.then(refreshJob).catch((e: Error) => setError(e.message))

  return (
    <div className="drive-banner" role="status">
      <Icon name="drive" />
      <span>Drive <strong>{drive.label}</strong> connected. Find pictures on it?</span>
      <button className="primary" disabled={job?.state === 'running'} onClick={() => run(api.scanDrive(drive.id))}>
        Scan drive
      </button>
      <button onClick={() => run(api.ignoreDrive(drive.id))}>Not this drive</button>
      {error && <span className="error small">{error}</span>}
    </div>
  )
}
