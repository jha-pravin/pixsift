import { useEffect, useState } from 'react'
import { api, type Face, type NameTarget, type Suggestion } from '../api'
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

  const hidden = !!face.person_hidden

  /** Hidden people are un-hidden by name; resolve a picked existing person to their name. */
  const nameOf = async (t: NameTarget) =>
    'name' in t ? t.name : 'person_id' in t ? (await people.get()).find((p) => p.id === t.person_id)?.name : undefined

  return (
    <div className="face-tag" role="dialog" aria-label="Name this face">
      <div className="face-tag-head">
        <img src={api.faceUrl(face.id)} alt="" className="face-avatar lg" />
        <div>
          <div className="muted small">
            {hidden ? "You chose not to tag this person" : face.assigned_by === 'auto' ? 'Recognised automatically' : face.person_id ? 'This is' : 'Unnamed face'}
          </div>
          <strong>{hidden ? 'Hidden person' : face.person_name ?? 'Who is this?'}</strong>
        </div>
        <button className="icon-btn" aria-label="Close" onClick={onClose}><Icon name="close" /></button>
      </div>
      {face.assigned_by === 'auto' && face.person_id && !hidden && (
        <button className="suggestion" onClick={() => run(api.confirmAuto(face.person_id!, [face.id]))}>
          <Icon name="check" size={16} /> Yes, this is <strong>{face.person_name}</strong>
        </button>
      )}
      {suggestion && (
        <button className="suggestion" onClick={() => run(api.assignFaces([face.id], { person_id: suggestion.person_id }))}>
          <Icon name="check" size={16} />
          {suggestion.hidden ? <>Looks like someone you hid. <strong>Hide too</strong></> : <>Is this <strong>{suggestion.name}</strong>?</>}
        </button>
      )}
      {hidden ? (
        <NameInput autoFocus placeholder="Name this person" submitLabel="Name"
          onSubmit={async (t) => run(api.unhidePerson(face.person_id!, await nameOf(t)))} />
      ) : (
        <NameInput autoFocus placeholder={face.person_id ? 'Rename to…' : 'Type a name'}
          onSubmit={(t) => run(api.assignFaces([face.id], t))} />
      )}
      <div className="face-tag-actions">
        {face.person_id && !hidden && (
          <button onClick={() => run(api.rejectFace(face.id))}>Not {face.person_name}</button>
        )}
        {!face.person_id && (
          <button onClick={() => run(api.hideFace(face.id))} title="Stop asking about this person. You can name them later under People → Hidden">
            Hide this person
          </button>
        )}
        {hidden && <button onClick={() => run(api.rejectFace(face.id))} title="This face isn't the hidden person">Not this person</button>}
        <button onClick={() => run(api.ignoreFace(face.id))} title="Not a real face (a poster, a statue…)">Not a face</button>
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  )
}
