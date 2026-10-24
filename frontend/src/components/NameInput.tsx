import { useEffect, useId, useState } from 'react'
import { api, type NameTarget, type Person } from '../api'

let cache: Promise<Person[]> | null = null
/** Person list shared by every name input; invalidate after naming. */
export const people = {
  get: () => (cache ??= api.persons('name')),
  invalidate: () => { cache = null },
}

interface Props {
  onSubmit: (target: NameTarget) => void | Promise<void>
  placeholder?: string
  autoFocus?: boolean
  submitLabel?: string
}

/** Text input with autocomplete over existing people; picking a known name reuses that person. */
export function NameInput({ onSubmit, placeholder = 'Who is this?', autoFocus, submitLabel = 'Save' }: Props) {
  const [value, setValue] = useState('')
  const [list, setList] = useState<Person[]>([])
  const [busy, setBusy] = useState(false)
  const id = useId()

  useEffect(() => { people.get().then(setList) }, [])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const name = value.trim()
    if (!name) return
    const known = list.find((p) => p.name.toLowerCase() === name.toLowerCase())
    setBusy(true)
    try {
      await onSubmit(known ? { person_id: known.id } : { name })
      people.invalidate()
      setValue('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="name-input" onSubmit={submit}>
      <input list={id} value={value} onChange={(e) => setValue(e.target.value)} placeholder={placeholder}
        autoFocus={autoFocus} aria-label={placeholder} />
      <datalist id={id}>{list.map((p) => <option key={p.id} value={p.name} />)}</datalist>
      <button type="submit" className="primary" disabled={!value.trim() || busy}>{submitLabel}</button>
    </form>
  )
}
