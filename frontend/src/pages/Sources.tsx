import { useEffect, useState } from 'react'
import { api, formatBytes, formatDate, pickFolders, type Drive } from '../api'
import { Icon } from '../components/Icon'
import { useJob } from '../hooks/job'

export function Sources() {
  const { job, refreshJob, version } = useJob()
  const [roots, setRoots] = useState<string[]>([])
  const [scanned, setScanned] = useState<Record<string, string>>({})
  const [suggested, setSuggested] = useState<{ path: string; label: string }[]>([])
  const [input, setInput] = useState('')
  const [native, setNative] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [drives, setDrives] = useState<Drive[]>([])

  useEffect(() => {
    api.drives().then(setDrives)
    Promise.all([api.roots(), api.suggestedRoots()]).then(([known, sugg]) => {
      setScanned(Object.fromEntries(known.map((r) => [r.path, r.last_scanned])))
      setRoots((cur) => cur.length ? cur : known.length ? known.map((r) => r.path) : sugg.filter((s) => s.label === 'Pictures').map((s) => s.path))
      setSuggested(sugg)
    })
    // pywebview injects its bridge shortly after load.
    const check = () => setNative(!!(window as unknown as { pywebview?: { api?: object } }).pywebview?.api)
    check()
    window.addEventListener('pywebviewready', check)
    return () => window.removeEventListener('pywebviewready', check)
  }, [version, job?.new_drives?.length])

  /** Add one or more paths (typed or pasted one per line), skipping duplicates. */
  const add = (...paths: string[]) => {
    const clean = paths.flatMap((p) => p.split(/\r?\n/)).map((p) => p.trim()).filter(Boolean)
    setRoots((r) => [...r, ...clean.filter((p, i) => !r.includes(p) && clean.indexOf(p) === i)])
    setInput('')
  }

  const browse = async () => {
    const picked = await pickFolders()
    if (picked?.length) add(...picked)
  }

  const run = (p: Promise<unknown>) => {
    setError(null)
    p.then(refreshJob).catch((e: Error) => setError(e.message))
  }

  const running = job?.state === 'running'
  const m = job?.models

  return (
    <div className="page narrow">
      <header className="page-head"><h1>Sources</h1></header>

      <section className="card">
        <h2>Folders and drives to scan</h2>
        <ul className="roots">
          {roots.map((r) => (
            <li key={r}>
              <Icon name={r.startsWith('/Volumes') || /^[A-Z]:\\$/.test(r) ? 'drive' : 'folder'} />
              <div className="root-text">
                <span className="path">{r}</span>
                <span className="muted small">{scanned[r] ? `Last scanned ${formatDate(scanned[r] + 'Z')}` : 'Not scanned yet'}</span>
              </div>
              <button className="icon-btn" aria-label={`Remove ${r}`} disabled={running} onClick={() => setRoots(roots.filter((x) => x !== r))}>
                <Icon name="close" size={16} />
              </button>
            </li>
          ))}
          {!roots.length && <li className="muted">Add at least one folder.</li>}
        </ul>
        <div className="add-root">
          {native && <button onClick={browse}><Icon name="folder" /> Choose folders…</button>}
          <form className="inline-form grow" onSubmit={(e) => { e.preventDefault(); add(input) }}>
            <input value={input} onChange={(e) => setInput(e.target.value)} aria-label="Folder path"
              placeholder={native ? 'or type a path' : '/path/to/folder or ~/Pictures'}
              onPaste={(e) => {
                const text = e.clipboardData.getData('text')
                if (text.includes('\n')) { e.preventDefault(); add(text) }  // several paths pasted at once
              }} />
            <button type="submit" disabled={!input.trim()}>Add</button>
          </form>
        </div>
        <div className="chips">
          {suggested.filter((s) => !roots.includes(s.path)).map((s) => (
            <button key={s.path} className="chip" onClick={() => add(s.path)} title={s.path}>+ {s.label}</button>
          ))}
        </div>
        {native && (
          <p className="muted small">In the folder chooser, hold {isMac ? '⌘' : 'Ctrl'} or Shift to select several folders at once.</p>
        )}
        <p className="muted small">Hidden folders, system folders, app bundles and photo-library packages are skipped. Files under 10 KB are ignored.</p>
        <div className="btn-row">
          {running
            ? <button onClick={() => run(api.cancelJob())}>Stop</button>
            : <button className="primary big" disabled={!roots.length} onClick={() => run(api.scan(roots))}>Scan now</button>}
          {!running && <button onClick={() => run(api.analyze())} title="Analyse any pictures not yet analysed and regroup faces">Analyse &amp; group faces</button>}
        </div>
        {error && <p className="error">{error}</p>}
      </section>

      {drives.length > 0 && (
        <section className="card">
          <h2>External drives</h2>
          <p className="muted small">Pictures on a drive stay in your library while it's unplugged. Their people and timelines
            still show them, marked with the drive's name. Plug the drive in to open or edit them; new pictures are found automatically.</p>
          <ul className="drives">
            {drives.map((d) => (
              <li key={d.id}>
                <Icon name="drive" />
                <div className="root-text">
                  <strong>{d.label}</strong>
                  <span className="muted small">
                    {d.mounted ? 'Connected' : 'Not connected'}
                    {d.status === 'tracked' && ` · ${d.pictures.toLocaleString()} pictures`}
                    {d.last_scanned && ` · scanned ${formatDate(d.last_scanned + 'Z')}`}
                    {d.status === 'ignored' && ' · ignored'}
                  </span>
                </div>
                {d.status === 'tracked' ? (
                  <>
                    <label className="check small">
                      <input type="checkbox" checked={!!d.auto_scan}
                        onChange={(e) => api.setDriveAutoScan(d.id, e.target.checked).then(() => api.drives().then(setDrives))} />
                      Scan when connected
                    </label>
                    <button disabled={!d.mounted || running} onClick={() => run(api.scanDrive(d.id))}>Scan now</button>
                  </>
                ) : d.mounted ? (
                  <>
                    <button className="primary" disabled={running} onClick={() => run(api.scanDrive(d.id))}>Scan drive</button>
                    {d.status === 'new' && <button onClick={() => run(api.ignoreDrive(d.id).then(() => api.drives().then(setDrives)))}>Not this drive</button>}
                  </>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      )}

      {job && job.state !== 'idle' && (
        <section className="card">
          <h2>{running ? phaseLabel(job.phase) : `Last run: ${job.state}`}</h2>
          {job.current_root && <p className="muted small path">{job.current_root}</p>}
          {job.phase === 'analyzing' && job.to_analyze > 0 && (
            <progress value={job.analyzed} max={job.to_analyze} />
          )}
          {job.phase === 'models' && m && m.missing_bytes > 0 && (
            <progress value={m.downloaded_bytes} max={m.missing_bytes} />
          )}
          <dl className="kv">
            <dt>Pictures found</dt><dd>{job.found.toLocaleString()}</dd>
            <dt>New or changed</dt><dd>{job.processed.toLocaleString()}</dd>
            <dt>Unchanged</dt><dd>{job.unchanged.toLocaleString()}</dd>
            <dt>Analysed</dt><dd>{job.analyzed.toLocaleString()}{job.to_analyze ? ` of ${job.to_analyze.toLocaleString()}` : ''}</dd>
            <dt>Unreadable</dt><dd>{job.errors.toLocaleString()}</dd>
            <dt>No longer on disk</dt><dd>{job.missing.toLocaleString()}</dd>
            {job.offline_roots > 0 && (<><dt>Skipped (drive not connected)</dt><dd>{job.offline_roots}</dd></>)}
          </dl>
          {job.message && <p className="error">{job.message}</p>}
        </section>
      )}

      {m && (
        <section className="card">
          <h2>On-device AI models</h2>
          <p className="small">
            {m.ready
              ? `Installed (${formatBytes(m.total_bytes)}). Recognition runs entirely on this computer.`
              : `${formatBytes(m.missing_bytes)} will be downloaded once, on the first scan, from Hugging Face and the OpenCV model zoo. After that everything works offline.`}
          </p>
        </section>
      )}
    </div>
  )
}

const isMac = navigator.platform.toLowerCase().includes('mac')

function phaseLabel(phase: string | null) {
  return { models: 'Downloading AI models…', scanning: 'Scanning folders…', analyzing: 'Recognising faces and picture types…', grouping: 'Grouping faces…' }[phase ?? ''] ?? 'Working…'
}
