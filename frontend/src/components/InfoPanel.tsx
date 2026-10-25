import { useEffect, useId, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, CATEGORY_LABELS, formatBytes, formatDate, type Category, type Face, type ImageDetail } from '../api'
import { Icon } from './Icon'

interface Props {
  img: ImageDetail
  onChanged: () => void
  onFace: (f: Face) => void
}

const TYPES: Category[] = ['photo', 'document', 'screenshot', 'graphic']

export function InfoPanel({ img, onChanged, onFace }: Props) {
  const [tag, setTag] = useState('')
  const [allTags, setAllTags] = useState<string[]>([])
  const tagListId = useId()
  const scores: Record<string, number> = img.clip_scores ? JSON.parse(img.clip_scores) : {}
  const faces = img.faces.filter((f) => !f.ignored)

  useEffect(() => { api.tags().then((t) => setAllTags(t.map((x) => x.tag))) }, [img.id])

  const addTag = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!tag.trim()) return
    await api.addTag(img.id, tag)
    setTag('')
    onChanged()
  }

  return (
    <aside className="info-panel" aria-label="Picture information">
      <h2 className="info-title" title={img.filename}>{img.filename}</h2>

      <dl className="meta">
        <dt><Icon name="calendar" size={15} /></dt>
        <dd>{formatDate(img.taken_at)}{img.date_source === 'file' && <span className="muted"> · file date</span>}</dd>
        {(img.camera_make || img.camera_model) && (<>
          <dt><Icon name="camera" size={15} /></dt>
          <dd>{[img.camera_make, img.camera_model].filter(Boolean).join(' ')}</dd>
        </>)}
        <dt><Icon name="photo" size={15} /></dt>
        <dd>{img.width && img.height ? `${img.width} × ${img.height} · ` : ''}{formatBytes(img.size)} · {img.ext.slice(1).toUpperCase()}</dd>
        {img.gps_lat != null && img.gps_lon != null && (<>
          <dt><Icon name="pin" size={15} /></dt>
          <dd>{img.gps_lat.toFixed(5)}, {img.gps_lon.toFixed(5)}</dd>
        </>)}
        {img.drive && (<>
          <dt><Icon name="drive" size={15} /></dt>
          <dd>Drive {img.drive}{img.offline ? <span className="muted"> · not connected</span> : ''}</dd>
        </>)}
        <dt><Icon name="folder" size={15} /></dt>
        <dd className="path">{img.folder}</dd>
      </dl>

      <section>
        <h3>Type</h3>
        <select value={img.category_locked ? img.category ?? '' : ''} aria-label="Picture type"
          onChange={(e) => api.setCategory(img.id, (e.target.value || null) as Category | null).then(onChanged)}>
          <option value="">
            Automatic{img.category ? `: ${CATEGORY_LABELS[img.category]}` : ''}
            {img.category && scores[img.category] ? ` (${Math.round(scores[img.category] * 100)}%)` : ''}
          </option>
          {TYPES.map((t) => <option key={t} value={t}>{CATEGORY_LABELS[t]}</option>)}
        </select>
      </section>

      <section>
        <h3>People {faces.length > 0 && <span className="muted">({faces.length})</span>}</h3>
        {faces.length === 0 && <p className="muted small">{img.analyzed_at ? 'No faces found.' : 'Not analysed yet.'}</p>}
        <ul className="face-list">
          {faces.map((f) => (
            <li key={f.id}>
              <button className="face-chip" onClick={() => onFace(f)} aria-label={f.person_name ? `${f.person_name}: rename or remove` : 'Name this face'}>
                <img src={api.faceUrl(f.id)} alt="" className="face-avatar" />
                <span>{f.person_hidden ? <em className="muted">Hidden person</em> : f.person_name ?? <em className="muted">Name…</em>}</span>
                {f.assigned_by === 'auto' && !f.person_hidden && <span className="auto-tag" title="Recognised automatically. Click to confirm">auto</span>}
              </button>
              {f.person_id && !f.person_hidden && (
                <Link to={`/people/${f.person_id}`} className="small" aria-label={`All pictures of ${f.person_name}`}>
                  All
                </Link>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3>Tags</h3>
        <div className="chips">
          {img.tags.map((t) => (
            <span key={t} className="chip">
              <Link to={`/library?tag=${encodeURIComponent(t)}`}>{t}</Link>
              <button className="chip-x" aria-label={`Remove tag ${t}`}
                onClick={() => api.removeTag(img.id, t).then(onChanged)}>×</button>
            </span>
          ))}
        </div>
        <form className="inline-form" onSubmit={addTag}>
          <input list={tagListId} value={tag} onChange={(e) => setTag(e.target.value)} placeholder="Add a tag"
            aria-label="Add a tag" />
          <datalist id={tagListId}>{allTags.map((t) => <option key={t} value={t} />)}</datalist>
          <button type="submit" disabled={!tag.trim()}>Add</button>
        </form>
      </section>

      {(img.duplicates.length > 0 || img.edits.length > 0 || img.edited_from) && (
        <section>
          <h3>Related files</h3>
          <ul className="related">
            {img.edited_from && <li><button className="link" onClick={() => api.reveal(img.edited_from!)}>Original</button></li>}
            {img.edits.map((e) => <li key={e.id}><button className="link" onClick={() => api.reveal(e.id)}>Edited: {e.path.split(/[\\/]/).pop()}</button></li>)}
            {img.duplicates.map((d) => <li key={d.id}><button className="link" onClick={() => api.reveal(d.id)}>Duplicate: {d.path}</button></li>)}
          </ul>
        </section>
      )}
      {img.error && <p className="error small">{img.error}</p>}
    </aside>
  )
}
