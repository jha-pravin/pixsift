import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, formatDate, type Person as PersonT, type PersonDetail, type Sort } from '../api'
import { Icon } from '../components/Icon'
import { people as peopleCache } from '../components/NameInput'
import { PhotoGrid } from '../components/PhotoGrid'
import { Viewer } from '../components/Viewer'
import { useJob } from '../hooks/job'
import { usePagedImages } from '../hooks/usePagedImages'

export function Person() {
  const id = Number(useParams().id)
  const navigate = useNavigate()
  const { version, bump } = useJob()
  const [p, setP] = useState<PersonDetail | null>(null)
  const [others, setOthers] = useState<PersonT[]>([])
  const [sort, setSort] = useState<Sort>('taken_desc')
  const [year, setYear] = useState<string | null>(null)
  const [renaming, setRenaming] = useState(false)
  const [name, setName] = useState('')
  const [reviewing, setReviewing] = useState(false)
  const [faces, setFaces] = useState<{ id: number; image_id: number; assigned_by: string }[]>([])
  const [view, setView] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.person(id).then(setP).catch(() => setP(null))
    api.persons('name').then((ps) => setOthers(ps.filter((x) => x.id !== id)))
  }, [id, version])

  useEffect(() => { if (reviewing) api.personFaces(id).then(setFaces) }, [id, reviewing, version])

  const query = useMemo(() => ({
    person: [id], sort,
    date_from: year ? `${year}-01-01` : undefined,
    date_to: year ? `${Number(year) + 1}-01-01` : undefined,
  }), [id, sort, year])
  const { items, total, loaded, loadMore } = usePagedImages(query, version)

  const run = (pr: Promise<unknown>) => pr.then(() => { peopleCache.invalidate(); bump() }).catch((e: Error) => setError(e.message))

  if (!p) return <div className="page"><p className="muted">Loading…</p></div>
  const maxYear = Math.max(1, ...p.years.map((y) => y.count))

  return (
    <div className="page">
      <Link to="/people" className="back"><Icon name="left" size={16} /> People</Link>
      <header className="person-head">
        {p.cover_face_id ? <img src={api.faceUrl(p.cover_face_id)} alt="" className="face-avatar hero" /> : <span className="face-avatar hero" />}
        <div className="person-title">
          {renaming ? (
            <form className="inline-form" onSubmit={(e) => {
              e.preventDefault()
              run(api.renamePerson(id, name)).then(() => setRenaming(false))
            }}>
              <input value={name} onChange={(e) => setName(e.target.value)} autoFocus aria-label="Name" />
              <button className="primary" type="submit" disabled={!name.trim()}>Save</button>
              <button type="button" onClick={() => setRenaming(false)}>Cancel</button>
            </form>
          ) : (
            <h1>{p.name} <button className="icon-btn" aria-label="Rename" onClick={() => { setName(p.name); setRenaming(true) }}><Icon name="edit" size={16} /></button></h1>
          )}
          <p className="muted">
            {p.count.toLocaleString()} {p.count === 1 ? 'picture' : 'pictures'}
            {p.first_seen && <> · {formatDate(p.first_seen, false)} – {formatDate(p.last_seen, false)}</>}
          </p>
          {p.auto_count > 0 && !reviewing && (
            <button className="notice link-notice review-cta" onClick={() => setReviewing(true)}>
              <Icon name="face" /> {p.auto_count} {p.auto_count === 1 ? 'face was' : 'faces were'} recognised automatically. <strong>Review</strong>
            </button>
          )}
          <div className="btn-row">
            <button className={reviewing ? 'on' : ''} onClick={() => setReviewing((v) => !v)}><Icon name="face" /> Review faces</button>
            <select aria-label="Merge into another person" value="" onChange={(e) => {
              const into = Number(e.target.value)
              const target = others.find((o) => o.id === into)
              if (target && confirm(`Merge ${p.name} into ${target.name}? All of ${p.name}'s faces will be named ${target.name}.`)) {
                run(api.mergePerson(id, into)).then(() => navigate(`/people/${into}`))
              }
            }}>
              <option value="">Merge into…</option>
              {others.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
            <button onClick={() => {
              if (confirm(`Remove the name "${p.name}"? Pictures are not touched; the faces become unnamed again.`)) {
                run(api.deletePerson(id)).then(() => navigate('/people'))
              }
            }}><Icon name="trash" /> Remove name</button>
          </div>
          {error && <p className="error">{error}</p>}
        </div>
      </header>

      {reviewing && (
        <section className="review">
          <div className="review-head">
            <p className="muted small">Remove faces that aren't {p.name}. Click a face to use it as the profile picture.
              Faces with a dashed ring were recognised automatically.</p>
            {faces.some((f) => f.assigned_by === 'auto') && (
              <button className="primary" onClick={() => run(api.confirmAuto(id))}>
                <Icon name="check" /> {confirmLabel(faces.filter((f) => f.assigned_by === 'auto').length)}
              </button>
            )}
          </div>
          <ul className="face-review">
            {faces.map((f) => (
              <li key={f.id} className={f.assigned_by === 'auto' ? 'auto' : undefined}>
                <button className="face-pick" onClick={() => run(api.setCover(id, f.id))} title="Use as profile picture">
                  <img src={api.faceUrl(f.id)} alt="" loading="lazy" />
                </button>
                <button className="face-x" aria-label={`Not ${p.name}`} title={`Not ${p.name}`}
                  onClick={() => { setFaces((fs) => fs.filter((x) => x.id !== f.id)); run(api.rejectFace(f.id)) }}>×</button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="person-body">
        <section className="person-timeline">
          <div className="section-head">
            <h2>{year ? <>Photos from {year}</> : <>All photos</>} <span className="muted">· {total.toLocaleString()}</span></h2>
            {year && <button className="link small" onClick={() => setYear(null)}>Show all years</button>}
            <select className="push" aria-label="Order" value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
              <option value="taken_desc">Newest first</option>
              <option value="taken_asc">Oldest first</option>
            </select>
          </div>
          {loaded && <PhotoGrid items={items} total={total} loadMore={loadMore} onOpen={setView} groupByMonth />}
        </section>
        <aside className="person-facts" aria-label={`About ${p.name}`}>
          {p.years.length > 0 && (
            <div className="fact">
              <h3>By year</h3>
              <div className="years">
                {p.years.map((y) => (
                  <button key={y.year} className={`year ${year === y.year ? 'on' : ''}`} onClick={() => setYear(year === y.year ? null : y.year)}
                    title={`${y.count} in ${y.year}`}>
                    <span className="bar" style={{ height: `${(y.count / maxYear) * 100}%` }} />
                    <span className="small">{y.year}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
          {p.together.length > 0 && (
            <div className="fact">
              <h3>Often with</h3>
              <ul className="plain">
                {p.together.map((t) => (
                  <li key={t.id}>
                    <Link to={`/people/${t.id}`}>{t.name}</Link>{' '}
                    <Link className="muted small" to={`/library?person=${id}&person=${t.id}`}>{t.count} together</Link>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {p.cameras.length > 0 && (
            <div className="fact">
              <h3>Cameras</h3>
              <ul className="plain">{p.cameras.map((c) => <li key={c.camera}>{c.camera} <span className="muted small">{c.count}</span></li>)}</ul>
            </div>
          )}
          <div className="fact">
            <h3>Folders</h3>
            <ul className="plain">
              {p.folders.map((f) => (
                <li key={f.folder}><Link to={`/library?person=${id}&folder=${encodeURIComponent(f.folder)}`} className="path">{f.folder}</Link> <span className="muted small">{f.count}</span></li>
              ))}
            </ul>
          </div>
          {p.places.length > 0 && (
            <div className="fact">
              <h3>Places</h3>
              <p className="small">{p.places.length} pictures have a location.</p>
              <ul className="plain small">
                {p.places.slice(0, 4).map((pl) => <li key={pl.id}>{pl.lat.toFixed(3)}, {pl.lon.toFixed(3)} <span className="muted">{formatDate(pl.taken_at, false)}</span></li>)}
              </ul>
            </div>
          )}
        </aside>

      </div>
      {view !== null && items[view] && (
        <Viewer items={items} total={total} index={view} loadMore={loadMore} onIndex={setView} onClose={() => setView(null)} />
      )}
    </div>
  )
}

const confirmLabel = (n: number) => (n === 1 ? 'Confirm automatic match' : `Confirm all ${n} automatic matches`)
