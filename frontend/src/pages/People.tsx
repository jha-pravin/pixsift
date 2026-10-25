import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type FaceGroup, type NameTarget, type Person } from '../api'
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
  const [hidden, setHidden] = useState<Person[]>([])
  const [askMin, setAskMin] = useState(2)

  useEffect(() => {
    api.persons().then(setPersons)
    api.faceGroups().then(setGroups)
    api.hiddenPersons().then(setHidden)
    api.settings().then((s) => setAskMin(s.ask_min_photos))
  }, [version])

  const changeAskMin = (n: number) => {
    setAskMin(n)
    api.saveSettings({ ask_min_photos: n }).then(bump)
  }

  /** Name (or stop hiding) a hidden person; a picked existing person is matched by name and merged. */
  const unhide = async (p: Person, t?: NameTarget) => {
    const name = !t ? undefined : 'name' in t ? t.name
      : 'person_id' in t ? (persons ?? []).find((x) => x.id === t.person_id)?.name : undefined
    setHidden((hs) => hs.filter((h) => h.id !== p.id))
    await api.unhidePerson(p.id, name).catch((e: Error) => setError(e.message))
    peopleCache.invalidate()
    bump()
  }

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
          <label className="ask-min small">
            Ask about people in at least
            <select value={askMin} onChange={(e) => changeAskMin(Number(e.target.value))} aria-label="Minimum photos before asking">
              {[2, 3, 5, 10, 20].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
            photos
          </label>
        </div>
        {groups && groups.length > 0 && (
          <p className="muted small">{groups.length} unnamed {groups.length === 1 ? 'group' : 'groups'}. Name the people you care about.
            For everyone else, choose <strong>Hide person</strong>: PixSift stops asking and quietly sets their photos aside. You can name them later.</p>
        )}
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
                    <Icon name="check" size={16} />
                    {g.suggestion.hidden ? <>Looks like someone you hid. <strong>Hide too</strong></> : <>Is this <strong>{g.suggestion.name}</strong>?</>}
                  </button>
                )}
                <NameInput onSubmit={(t) => act(api.nameGroup(g.cluster_id, t), g.cluster_id)} />
                <div className="group-secondary">
                  <button onClick={() => act(api.hideGroup(g.cluster_id), g.cluster_id)}
                    title="Stop asking about this person. Find them later under Hidden people">
                    Hide person
                  </button>
                  <button className="link small" onClick={() => act(api.ignoreGroup(g.cluster_id), g.cluster_id)}
                    title="These aren't real faces (posters, statues…)">Not faces</button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      </section>
      {hidden.length > 0 && (
        <section>
          <details className="hidden-people">
            <summary><h2>Hidden people <span className="muted">({hidden.length})</span></h2></summary>
            <p className="muted small">People you chose not to tag. PixSift still recognises them so it doesn't ask again.
              Name someone any time: every photo of them found meanwhile comes along.</p>
            <ul className="group-list">
              {hidden.map((p) => (
                <li key={p.id} className="group-card hidden-card">
                  <div className="hidden-head">
                    {p.cover_face_id ? <img src={api.faceUrl(p.cover_face_id)} alt="" className="face-avatar xl" loading="lazy" /> : <span className="face-avatar xl" />}
                    <div>
                      <strong>{p.count} {p.count === 1 ? 'photo' : 'photos'}</strong>
                      <div><Link className="small" to={`/library?person=${p.id}`}>See photos</Link></div>
                    </div>
                  </div>
                  <NameInput placeholder="Name this person" submitLabel="Name" onSubmit={(t) => unhide(p, t)} />
                  <button className="link small" onClick={() => unhide(p)}>Ask me about them again</button>
                </li>
              ))}
            </ul>
          </details>
        </section>
      )}
    </div>
  )
}
