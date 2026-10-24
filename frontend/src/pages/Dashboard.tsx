import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, CATEGORY_LABELS, formatBytes, type Dashboard as Data, type Person } from '../api'
import { Icon, type IconName } from '../components/Icon'
import { useJob } from '../hooks/job'

const CAT_ICONS: Record<string, IconName> = { people: 'people', photo: 'photo', document: 'doc', screenshot: 'screen', graphic: 'graphic' }

export function Dashboard() {
  const { version, job, refreshJob } = useJob()
  const [data, setData] = useState<Data | null>(null)
  const [people, setPeople] = useState<Person[]>([])

  useEffect(() => {
    api.dashboard().then(setData)
    api.persons().then(setPeople)
  }, [version])

  if (!data) return null
  const s = data.stats

  if (s.total === 0) {
    return (
      <div className="page onboarding">
        <h1>Welcome to PixSift</h1>
        <p className="lead">Find every picture on this computer, sorted into documents, screenshots and photos, with the
          people in them recognised on-device. Nothing leaves your machine.</p>
        <Link className="button primary big" to="/sources">Choose folders to scan</Link>
      </div>
    )
  }

  return (
    <div className="page">
      <header className="page-head">
        <h1>Dashboard</h1>
        <ul className="stat-row">
          <li><strong>{s.total.toLocaleString()}</strong><span>pictures</span></li>
          <li><strong>{s.people.toLocaleString()}</strong><span>people</span></li>
          <li><strong>{s.folders.toLocaleString()}</strong><span>folders</span></li>
          <li><strong>{formatBytes(s.bytes)}</strong><span>on disk</span></li>
          {s.duplicate_files > 0 && (
            <li><Link to="/library?duplicates=1"><strong>{s.duplicate_files.toLocaleString()}</strong><span>duplicates</span></Link></li>
          )}
        </ul>
      </header>

      {s.pending > 0 && job?.state !== 'running' && (
        <div className="notice">
          <Icon name="info" /> {s.pending.toLocaleString()} pictures haven't been analysed yet.
          <button className="primary" onClick={() => api.analyze().then(refreshJob)}>Analyse now</button>
        </div>
      )}

      <section className="cat-cards">
        {data.categories.map((c) => (
          <Link key={c.key} to={`/library?category=${c.key}`} className="cat-card">
            <div className={`mosaic n${Math.min(c.samples.length, 4)}`}>
              {c.samples.map((id) => <img key={id} src={api.thumbUrl(id)} alt="" loading="lazy" />)}
              {!c.samples.length && <Icon name={CAT_ICONS[c.key]} size={40} />}
            </div>
            <div className="cat-meta">
              <Icon name={CAT_ICONS[c.key]} />
              <strong>{CATEGORY_LABELS[c.key]}</strong>
              <span className="muted">{c.count.toLocaleString()}</span>
            </div>
          </Link>
        ))}
      </section>

      <section>
        <div className="section-head">
          <h2>People</h2>
          <Link to="/people">See all</Link>
        </div>
        {s.unnamed_groups > 0 && (
          <Link to="/people" className="notice link-notice">
            <Icon name="face" /> {s.unnamed_groups} groups of faces are waiting for a name. <strong>Name them →</strong>
          </Link>
        )}
        {s.auto_named > 0 && (
          <Link to="/people" className="notice link-notice">
            <Icon name="check" /> {s.auto_named} faces were recognised automatically. <strong>Review →</strong>
          </Link>
        )}
        <ul className="people-row">
          {people.slice(0, 12).map((p) => (
            <li key={p.id}>
              <Link to={`/people/${p.id}`} className="person-chip">
                {p.cover_face_id ? <img src={api.faceUrl(p.cover_face_id)} alt="" className="face-avatar xl" /> : <span className="face-avatar xl" />}
                <strong className="ellipsis">{p.name}</strong>
                <span className="muted small">{p.count}</span>
              </Link>
            </li>
          ))}
          {!people.length && <li className="muted">No one named yet.</li>}
        </ul>
      </section>

      <section>
        <div className="section-head">
          <h2>Recent</h2>
          <Link to="/library">Open library</Link>
        </div>
        <ul className="strip">
          {data.recent.map((id) => (
            <li key={id}><Link to="/library"><img src={api.thumbUrl(id)} alt="" loading="lazy" /></Link></li>
          ))}
        </ul>
      </section>
    </div>
  )
}
