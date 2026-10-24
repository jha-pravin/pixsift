import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, CATEGORY_LABELS, type CategoryFilter, type ImageQuery, type Person, type Sort } from '../api'
import { PhotoGrid } from '../components/PhotoGrid'
import { Viewer } from '../components/Viewer'
import { useDebounced } from '../hooks/useDebounced'
import { useJob } from '../hooks/job'
import { usePagedImages } from '../hooks/usePagedImages'

const CATS: (CategoryFilter | '')[] = ['', 'people', 'photo', 'document', 'screenshot', 'graphic', 'unsorted']

export function Library() {
  const [params, setParams] = useSearchParams()
  const { version } = useJob()
  const [persons, setPersons] = useState<Person[]>([])
  const [folders, setFolders] = useState<{ folder: string; count: number }[]>([])
  const [tags, setTags] = useState<{ tag: string; count: number }[]>([])
  const [search, setSearch] = useState(params.get('q') ?? '')
  const [view, setView] = useState<number | null>(null)
  const q = useDebounced(search.trim())

  useEffect(() => {
    api.persons('name').then(setPersons)
    api.folders().then(setFolders)
    api.tags().then(setTags)
  }, [version])

  useEffect(() => { setSearch(params.get('q') ?? '') }, [params])

  const set = (key: string, value: string | null) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  useEffect(() => {
    if ((params.get('q') ?? '') !== q) set('q', q || null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q])

  const query: ImageQuery = useMemo(() => ({
    category: (params.get('category') as CategoryFilter) || undefined,
    person: params.getAll('person').map(Number),
    tag: params.get('tag') || undefined,
    folder: params.get('folder') || undefined,
    q: params.get('q') || undefined,
    date_from: params.get('from') ? `${params.get('from')}-01` : undefined,
    date_to: params.get('to') ? nextMonth(params.get('to')!) : undefined,
    duplicates: params.get('duplicates') === '1',
    sort: (params.get('sort') as Sort) || 'taken_desc',
  }), [params])

  const { items, total, loaded, loadMore } = usePagedImages(query, version)
  const selectedPeople = query.person ?? []
  const hasFilters = [...params.keys()].some((k) => k !== 'sort')

  return (
    <div className="page">
      <header className="page-head">
        <h1>{query.duplicates ? 'Duplicates' : query.category ? CATEGORY_LABELS[query.category] : 'Library'}</h1>
        <span className="muted">{total.toLocaleString()} pictures</span>
      </header>

      <div className="filters">
        <div className="seg" role="group" aria-label="Type">
          {CATS.map((c) => (
            <button key={c || 'all'} className={(query.category ?? '') === c ? 'on' : ''} onClick={() => set('category', c || null)}>
              {c ? CATEGORY_LABELS[c] : 'All'}
            </button>
          ))}
        </div>
        <div className="filter-row">
          <input type="search" placeholder="File name or tag" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search" />
          <select aria-label="Person" value="" onChange={(e) => {
            const next = new URLSearchParams(params)
            next.append('person', e.target.value)
            setParams(next, { replace: true })
          }}>
            <option value="">{selectedPeople.length ? '+ with…' : 'Person'}</option>
            {persons.filter((p) => !selectedPeople.includes(p.id)).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <select aria-label="Tag" value={query.tag ?? ''} onChange={(e) => set('tag', e.target.value || null)}>
            <option value="">Tag</option>
            {tags.map((t) => <option key={t.tag} value={t.tag}>{t.tag} ({t.count})</option>)}
          </select>
          <select aria-label="Folder" value={query.folder ?? ''} onChange={(e) => set('folder', e.target.value || null)} className="folder-select">
            <option value="">All folders</option>
            {folders.map((f) => <option key={f.folder} value={f.folder}>{f.folder} ({f.count})</option>)}
          </select>
          <label className="date-range">
            <span className="muted small">From</span>
            <input type="month" value={params.get('from') ?? ''} onChange={(e) => set('from', e.target.value || null)} aria-label="From month" />
            <span className="muted small">to</span>
            <input type="month" value={params.get('to') ?? ''} onChange={(e) => set('to', e.target.value || null)} aria-label="To month" />
          </label>
          <select aria-label="Sort" value={query.sort} onChange={(e) => set('sort', e.target.value === 'taken_desc' ? null : e.target.value)}>
            <option value="taken_desc">Newest first</option>
            <option value="taken_asc">Oldest first</option>
            <option value="name">Name</option>
            <option value="size_desc">Largest</option>
          </select>
          <label className="check"><input type="checkbox" checked={!!query.duplicates} onChange={(e) => set('duplicates', e.target.checked ? '1' : null)} /> Duplicates</label>
          {hasFilters && <button className="link" onClick={() => setParams({}, { replace: true })}>Clear filters</button>}
        </div>
        {selectedPeople.length > 0 && (
          <div className="chips">
            {selectedPeople.map((id) => (
              <span key={id} className="chip">
                {persons.find((p) => p.id === id)?.name ?? `#${id}`}
                <button className="chip-x" aria-label="Remove person filter" onClick={() => {
                  const next = new URLSearchParams(params)
                  next.delete('person')
                  selectedPeople.filter((x) => x !== id).forEach((x) => next.append('person', String(x)))
                  setParams(next, { replace: true })
                }}>×</button>
              </span>
            ))}
            {selectedPeople.length > 1 && <span className="muted small">pictures with all of them</span>}
          </div>
        )}
      </div>

      {loaded && (
        <PhotoGrid items={items} total={total} loadMore={loadMore} onOpen={setView}
          groupByMonth={!query.sort || query.sort.startsWith('taken')}
          empty={hasFilters ? 'No pictures match these filters.' : 'No pictures yet — add folders under Sources.'} />
      )}
      {view !== null && items[view] && (
        <Viewer items={items} total={total} index={view} loadMore={loadMore} onIndex={setView} onClose={() => setView(null)} />
      )}
    </div>
  )
}

function nextMonth(ym: string) {
  const [y, m] = ym.split('-').map(Number)
  return m === 12 ? `${y + 1}-01-01` : `${y}-${String(m + 1).padStart(2, '0')}-01`
}
