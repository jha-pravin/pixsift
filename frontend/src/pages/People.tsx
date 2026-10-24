import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type FaceGroup, type Person } from '../api'
import { Icon } from '../components/Icon'
import { NameInput, people as peopleCache } from '../components/NameInput'
import { useJob } from '../hooks/job'

export function People() {
  const { version, bump } = useJob()
  const [persons, setPersons] = useState<Person[] | null>(null)
  const [groups, setGroups] = useState<FaceGroup[] | null>(null)
  const [filter, setFilter] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [found, setFound] = useState<string | null>(null)

  useEffect(() => {
    api.persons().then(setPersons)
    api.faceGroups().then(setGroups)
  }, [version])

  const act = (p: Promise<{ auto_named?: number } | unknown>, clusterId: number) => {
    // Optimistically drop the group; the next refresh brings the regrouped state.
    setGroups((gs) => gs?.filter((g) => g.cluster_id !== clusterId) ?? null)
    setFound(null)
    p.then((r) => {
      const n = (r as { auto_named?: number })?.auto_named ?? 0
      if (n) setFound(`Recognised ${n} more ${n === 1 ? 'face' : 'faces'} automatically. Review them on each person's page.`)
      peopleCache.invalidate()
      bump()
    }).catch((e: Error) => { setError(e.message); bump() })
  }

  const shown = (persons ?? []).filter((p) => p.name.toLowerCase().includes(filter.toLowerCase()))

  return (
    <div className="page">
      <header className="page-head">
        <h1>People</h1>
        <input type="search" placeholder="Find a person" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Find a person" />
      </header>
      {error && <p className="error">{error}</p>}
      {found && <div className="notice"><Icon name="check" /> {found}</div>}

      <section>
        <ul className="people-grid">
          {shown.map((p) => (
            <li key={p.id}>
              <Link to={`/people/${p.id}`} className="person-card">
                {p.cover_face_id ? <img src={api.faceUrl(p.cover_face_id)} alt="" className="face-avatar xxl" /> : <span className="face-avatar xxl" />}
                <strong className="ellipsis">{p.name}</strong>
                <span className="muted small">{p.count.toLocaleString()} {p.count === 1 ? 'picture' : 'pictures'}</span>
                {p.auto_count > 0 && <span className="review-badge">{p.auto_count} to review</span>}
              </Link>
            </li>
          ))}
        </ul>
        {persons && !persons.length && (
          <p className="muted">Nobody named yet. Name the groups below. PixSift then finds those people in every picture.</p>
        )}
      </section>

      <section>
        <div className="section-head">
          <h2>Who are these people?</h2>
          {groups && <span className="muted">{groups.length} unnamed {groups.length === 1 ? 'group' : 'groups'}</span>}
        </div>
        {groups && !groups.length && (
          <p className="muted">No unnamed faces. New faces show up here after a scan.</p>
        )}
        <ul className="group-list">
          {groups?.map((g) => (
            <li key={g.cluster_id} className="group-card">
              <div className="group-faces">
                {g.faces.map((f) => <img key={f.id} src={api.faceUrl(f.id)} alt="" className="face-avatar lg" loading="lazy" />)}
                {g.count > g.faces.length && <span className="more">+{g.count - g.faces.length}</span>}
              </div>
              <div className="group-actions">
                <span className="muted small">{g.count} pictures</span>
                {g.suggestion && (
                  <button className="suggestion" onClick={() => act(api.nameGroup(g.cluster_id, { person_id: g.suggestion!.person_id }), g.cluster_id)}>
                    <Icon name="check" size={16} /> Is this <strong>{g.suggestion.name}</strong>?
                  </button>
                )}
                <NameInput onSubmit={(t) => act(api.nameGroup(g.cluster_id, t), g.cluster_id)} />
                <button className="link small" onClick={() => act(api.ignoreGroup(g.cluster_id), g.cluster_id)}>Ignore these faces</button>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
