import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { api, type Face, type ImageDetail, type ImageItem } from '../api'
import { useApp } from '../hooks/app'
import { useJob } from '../hooks/job'
import { Editor } from './Editor'
import { FaceTag } from './FaceTag'
import { Icon } from './Icon'
import { InfoPanel } from './InfoPanel'

interface Props {
  items: ImageItem[]
  total: number
  index: number
  loadMore: () => void
  onIndex: (i: number) => void
  onClose: () => void
}

const ZOOM_MAX = 8
const FILM_RADIUS = 12

export function Viewer({ items, total, index, loadMore, onIndex, onClose }: Props) {
  const item = items[index]
  const { revealLabel } = useApp()
  const { bump } = useJob()
  const [detail, setDetail] = useState<ImageDetail | null>(null)
  const [showInfo, setShowInfo] = useState(() => localGet('viewer.info', true))
  const [showFaces, setShowFaces] = useState(() => localGet('viewer.faces', true))
  const [activeFace, setActiveFace] = useState<Face | null>(null)
  const [editing, setEditing] = useState(false)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [stage, setStage] = useState({ w: 0, h: 0 })
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const filmRef = useRef<HTMLDivElement>(null)
  const drag = useRef<{ x: number; y: number; px: number; py: number } | null>(null)

  const reload = useCallback(() => {
    if (item) api.image(item.id).then(setDetail).catch(() => setDetail(null))
  }, [item])

  useEffect(() => {
    setDetail(null)
    setActiveFace(null)
    setZoom(1)
    setPan({ x: 0, y: 0 })
    setNatural(null)
    reload()
  }, [reload])

  useEffect(() => { localSet('viewer.info', showInfo) }, [showInfo])
  useEffect(() => { localSet('viewer.faces', showFaces) }, [showFaces])

  // Fetch more when nearing the end of what's loaded.
  useEffect(() => {
    if (index >= items.length - 5 && items.length < total) loadMore()
  }, [index, items.length, total, loadMore])

  useLayoutEffect(() => {
    const el = stageRef.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setStage({ w: e.contentRect.width, h: e.contentRect.height }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    filmRef.current?.querySelector('.current')?.scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'smooth' })
  }, [index])

  const go = useCallback((delta: number) => {
    const next = index + delta
    if (next >= 0 && next < items.length) onIndex(next)
  }, [index, items.length, onIndex])

  const zoomBy = (f: number) => setZoom((z) => {
    const nz = Math.min(ZOOM_MAX, Math.max(1, z * f))
    if (nz === 1) setPan({ x: 0, y: 0 })
    return nz
  })

  useEffect(() => {
    if (editing) return
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest('input, select, textarea')) return
      if (e.key === 'Escape') {
        if (activeFace) setActiveFace(null)
        else onClose()
      }
      else if (e.key === 'ArrowRight') go(1)
      else if (e.key === 'ArrowLeft') go(-1)
      else if (e.key === 'i') setShowInfo((v) => !v)
      else if (e.key === 'f') setShowFaces((v) => !v)
      else if (e.key === 'e') setEditing(true)
      else if (e.key === '+' || e.key === '=') zoomBy(1.5)
      else if (e.key === '-') zoomBy(1 / 1.5)
      else if (e.key === '0') { setZoom(1); setPan({ x: 0, y: 0 }) }
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [go, onClose, activeFace, editing])

  if (!item) return null

  // Fit the picture into the stage; face boxes are positioned in % of this frame.
  const dims = natural ?? (item.width && item.height ? { w: item.width, h: item.height } : null)
  const scale = dims && stage.w ? Math.min((stage.w - 32) / dims.w, (stage.h - 32) / dims.h, 1.5) : 0
  const frame = dims && scale ? { width: dims.w * scale, height: dims.h * scale } : undefined

  const onWheel = (e: React.WheelEvent) => {
    if (e.ctrlKey || e.metaKey || zoom > 1 || Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
      zoomBy(e.deltaY < 0 ? 1.15 : 1 / 1.15)
    }
  }
  const onPointerDown = (e: React.PointerEvent) => {
    if (zoom <= 1 || (e.target as HTMLElement).closest('.face-box')) return
    drag.current = { x: e.clientX, y: e.clientY, px: pan.x, py: pan.y }
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }
  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current
    if (d) setPan({ x: d.px + (e.clientX - d.x) / zoom, y: d.py + (e.clientY - d.y) / zoom })
  }

  const flash = (m: string) => { setMessage(m); setTimeout(() => setMessage(null), 2500) }
  const act = (p: Promise<unknown>, ok?: string) => p.then(() => ok && flash(ok)).catch((e: Error) => flash(e.message))
  const changed = () => { reload(); bump() }

  const start = Math.max(0, index - FILM_RADIUS)
  const film = items.slice(start, index + FILM_RADIUS + 1)
  const faces = (detail?.faces ?? []).filter((f) => !f.ignored)

  return (
    <div className={`viewer ${showInfo ? 'with-info' : ''}`} role="dialog" aria-modal="true" aria-label={item.filename}>
      <header className="viewer-bar">
        <button className="icon-btn" onClick={onClose} aria-label="Close viewer (Esc)"><Icon name="close" /></button>
        <div className="viewer-title">
          <strong className="ellipsis">{item.filename}</strong>
          <span className="muted small">{index + 1} of {total.toLocaleString()}</span>
        </div>
        <div className="viewer-tools">
          <button className="icon-btn" onClick={() => zoomBy(1 / 1.5)} disabled={zoom <= 1} aria-label="Zoom out (-)"><Icon name="zoomOut" /></button>
          <button className="icon-btn zoom-label" onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }) }} aria-label="Fit to screen (0)">{Math.round(zoom * 100)}%</button>
          <button className="icon-btn" onClick={() => zoomBy(1.5)} aria-label="Zoom in (+)"><Icon name="zoomIn" /></button>
          <span className="sep" />
          <button className={`icon-btn ${showFaces ? 'on' : ''}`} onClick={() => setShowFaces((v) => !v)} aria-pressed={showFaces}
            aria-label="Show faces (F)" title="Show faces (F)"><Icon name="face" /></button>
          <button className="icon-btn" onClick={() => setEditing(true)} aria-label="Edit (E)" title="Edit (E)"><Icon name="edit" /></button>
          <button className="icon-btn" onClick={() => act(api.reveal(item.id))} aria-label={revealLabel} title={revealLabel}><Icon name="folder" /></button>
          <button className="icon-btn" onClick={() => act(api.open(item.id))} aria-label="Open in default app" title="Open in default app"><Icon name="open" /></button>
          <button className="icon-btn" onClick={() => act(navigator.clipboard.writeText(item.path), 'Path copied')} aria-label="Copy path" title="Copy path"><Icon name="copy" /></button>
          <button className={`icon-btn ${showInfo ? 'on' : ''}`} onClick={() => setShowInfo((v) => !v)} aria-pressed={showInfo}
            aria-label="Info (I)" title="Info (I)"><Icon name="info" /></button>
        </div>
      </header>

      <div className="viewer-stage" ref={stageRef} onWheel={onWheel} onPointerDown={onPointerDown}
        onPointerMove={onPointerMove} onPointerUp={() => (drag.current = null)}
        onDoubleClick={() => (zoom > 1 ? (setZoom(1), setPan({ x: 0, y: 0 })) : setZoom(2.5))}
        style={{ cursor: zoom > 1 ? 'grab' : undefined }}>
        <div className="frame" style={{ ...frame, transform: `scale(${zoom}) translate(${pan.x}px, ${pan.y}px)` }}>
          <img key={item.id} src={api.previewUrl(item.id, item.size)} alt={item.filename} draggable={false}
            onLoad={(e) => setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })} />
          {showFaces && faces.map((f) => (
            <button key={f.id} className={`face-box ${f.person_id ? 'named' : ''} ${f.assigned_by === 'auto' ? 'auto' : ''} ${activeFace?.id === f.id ? 'active' : ''}`}
              style={{ left: `${f.x * 100}%`, top: `${f.y * 100}%`, width: `${f.w * 100}%`, height: `${f.h * 100}%` }}
              onClick={(e) => { e.stopPropagation(); setActiveFace(f) }}
              aria-label={f.person_name ? `Face: ${f.person_name}` : 'Unnamed face, click to name'}>
              <span className="face-label">{f.person_name ? `${f.person_name}${f.assigned_by === 'auto' ? '?' : ''}` : '?'}</span>
            </button>
          ))}
        </div>
        <button className="nav prev" onClick={() => go(-1)} disabled={index === 0} aria-label="Previous (←)"><Icon name="left" size={28} /></button>
        <button className="nav next" onClick={() => go(1)} disabled={index >= items.length - 1} aria-label="Next (→)"><Icon name="right" size={28} /></button>
        {activeFace && (
          <FaceTag face={activeFace} onClose={() => setActiveFace(null)} onDone={() => { setActiveFace(null); changed() }} />
        )}
        {message && <div className="toast" role="status">{message}</div>}
      </div>

      <div className="filmstrip" ref={filmRef}>
        {film.map((it, j) => (
          <button key={it.id} className={start + j === index ? 'current' : undefined} onClick={() => onIndex(start + j)}
            aria-label={it.filename}>
            {it.thumb && <img src={api.thumbUrl(it.id)} alt="" loading="lazy" />}
          </button>
        ))}
      </div>

      {showInfo && detail && <InfoPanel img={detail} onChanged={changed} onFace={setActiveFace} />}

      {editing && detail && (
        <Editor img={detail} onClose={() => setEditing(false)}
          onSaved={(r) => {
            setEditing(false)
            changed()
            flash(r.copy ? `Saved a copy: ${r.path.split(/[\\/]/).pop()}` : 'Saved')
          }} />
      )}
    </div>
  )
}

function localGet<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(`pixsift.${key}`)
    return v === null ? fallback : (JSON.parse(v) as T)
  } catch {
    return fallback
  }
}

function localSet(key: string, value: unknown) {
  try { localStorage.setItem(`pixsift.${key}`, JSON.stringify(value)) } catch { /* storage unavailable */ }
}
