import { Link } from 'react-router-dom'
import { analysisEta } from '../api'
import { useJob } from '../hooks/job'

export function JobPill() {
  const { job } = useJob()
  if (job?.state !== 'running') return null
  const eta = analysisEta(job)
  const text = {
    models: `Downloading models ${job.models.missing_bytes ? Math.round((job.models.downloaded_bytes / job.models.missing_bytes) * 100) : 0}%`,
    scanning: `Scanning · ${job.found.toLocaleString()} found`,
    analyzing: `Analysing ${job.analyzed.toLocaleString()} / ${job.to_analyze.toLocaleString()}${eta ? ` · ${eta.left} left` : ''}`,
    grouping: 'Grouping faces…',
  }[job.phase ?? 'scanning']
  return (
    <Link to="/sources" className="job-pill" role="status">
      <span className="spinner" aria-hidden="true" /> {text}
    </Link>
  )
}
