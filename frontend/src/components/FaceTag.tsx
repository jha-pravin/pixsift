import { useEffect, useState } from 'react'
import { api, type Face, type Suggestion } from '../api'
import { NameInput, people } from './NameInput'
import { Icon } from './Icon'

interface Props {
  face: Face
  onDone: () => void
  onClose: () => void
}

/** Name / rename / reject one face. */
export function FaceTag({ face, onDone, onClose }: Props) {
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setSuggestion(null)
    if (!face.person_id) api.faceSuggestion(face.id).then((r) => setSuggestion(r.suggestion)).catch(() => {})
  }, [face.id, face.person_id])

  const run = (p: Promise<unknown>) =>
    p.then(() => { people.invalidate(); onDone() }).catch((e: Error) => setError(e.message))

  return (
    <div className="face-tag" role="dialog" aria-label="Name this face">
      <div className="face-tag-head">
        <img src={api.faceUrl(face.id)} alt="" className="face-avatar lg" />
        <div>
          <div className="muted small">{face.assigned_by === 'auto' ? 'Recognised automatically' : face.person_id ? 'This is' : 'Unnamed face'}</div>
          <strong>{face.person_name ?? 'Who is this?'}</strong>
        </div>
        <button className="icon-btn" aria-label="Close" onClick={onClose}><Icon name="close" /></button>
      </div>
      {face.assigned_by === 'auto' && face.person_id && (
        <button className="suggestion" onClick={() => run(api.confirmAuto(face.person_id!, [face.id]))}>
          <Icon name="check" size={16} /> Yes, this is <strong>{face.person_name}</strong>
        </button>
      )}
      {suggestion && (
        <button className="suggestion" onClick={() => run(api.assignFaces([face.id], { person_id: suggestion.person_id }))}>
          <Icon name="check" size={16} /> Is this <strong>{suggestion.name}</strong>?
        </button>
      )}
      <NameInput autoFocus placeholder={face.person_id ? 'Rename to…' : 'Type a name'}
        onSubmit={(t) => run(api.assignFaces([face.id], t))} />
      <div className="face-tag-actions">
        {face.person_id && (
          <button onClick={() => run(api.rejectFace(face.id))}>Not {face.person_name}</button>
        )}
        <button onClick={() => run(api.ignoreFace(face.id))} title="Stranger, or not a face">Ignore face</button>
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  )
}
