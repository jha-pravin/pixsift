import { useEffect, useMemo, useRef } from 'react'
import { api, monthLabel, type ImageItem } from '../api'
import { Icon } from './Icon'
import { useApp } from '../hooks/app'

interface Props {
  items: ImageItem[]
  total: number
  loadMore: () => void
  onOpen: (index: number) => void
  groupByMonth?: boolean
  empty?: React.ReactNode
}

export function PhotoGrid({ items, total, loadMore, onOpen, groupByMonth, empty }: Props) {
  const sentinel = useRef<HTMLDivElement>(null)
  const { revealLabel } = useApp()

  useEffect(() => {
    const el = sentinel.current
    if (!el) return
    const obs = new IntersectionObserver(([e]) => e.isIntersecting && items.length < total && loadMore(), {
      rootMargin: '800px',
    })
    obs.observe(el)
    return () => obs.disconnect()
  }, [items.length, total, loadMore])

  const sections = useMemo(() => {
    if (!groupByMonth) return [{ label: '', start: 0, items }]
    const out: { label: string; start: number; items: ImageItem[] }[] = []
    items.forEach((it, i) => {
      const label = monthLabel(it.taken_at)
      if (out.at(-1)?.label !== label) out.push({ label, start: i, items: [] })
      out.at(-1)!.items.push(it)
    })
    return out
  }, [items, groupByMonth])

  if (!items.length) return <div className="empty">{empty ?? 'No pictures here yet.'}</div>

  return (
    <>
      {sections.map((s) => (
        <section key={s.label + s.start} className="grid-section">
          {s.label && <h3 className="month">{s.label}</h3>}
          <ul className="grid">
            {s.items.map((it, j) => (
              <li key={it.id}>
                <button className="tile" onClick={() => onOpen(s.start + j)} title={it.filename}>
                  {it.thumb
                    ? <img src={api.thumbUrl(it.id)} alt={it.filename} loading="lazy" />
                    : <span className="broken">Can't read</span>}
                  {it.face_count > 0 && <span className="badge"><Icon name="face" size={12} />{it.face_count}</span>}
                </button>
                <button className="tile-reveal" title={revealLabel} aria-label={`${revealLabel}: ${it.filename}`}
                  onClick={() => api.reveal(it.id)}>
                  <Icon name="folder" size={15} />
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
      <div ref={sentinel} className="sentinel" />
    </>
  )
}
