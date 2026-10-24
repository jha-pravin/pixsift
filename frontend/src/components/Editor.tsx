import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { api, type EditRequest, type ImageDetail } from '../api'
import { Icon } from './Icon'

type Rect = { x: number; y: number; w: number; h: number } // normalised, in the rotated/flipped view
type Handle = 'move' | 'nw' | 'ne' | 'sw' | 'se'

const ASPECTS: { label: string; value: number | null }[] = [
  { label: 'Free', value: null },
  { label: '1:1', value: 1 },
  { label: '4:3', value: 4 / 3 },
  { label: '3:2', value: 3 / 2 },
  { label: '16:9', value: 16 / 9 },
]
const MIN = 0.05
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

interface Props {
  img: ImageDetail
  onClose: () => void
  onSaved: (r: { id: number; path: string; copy: boolean }) => void
}

export function Editor({ img, onClose, onSaved }: Props) {
  const [rotate, setRotate] = useState<EditRequest['rotate']>(0)
  const [flipH, setFlipH] = useState(false)
  const [flipV, setFlipV] = useState(false)
  const [crop, setCrop] = useState<Rect | null>(null)
  const [aspect, setAspect] = useState<number | null>(null)
  const [cropping, setCropping] = useState(false)
  const [brightness, setBrightness] = useState(1)
  const [contrast, setContrast] = useState(1)
  const [saturation, setSaturation] = useState(1)
  const [mode, setMode] = useState<'copy' | 'overwrite'>('copy')
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [source, setSource] = useState<HTMLImageElement | null>(null)
  const [box, setBox] = useState({ w: 800, h: 560 })
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const areaRef = useRef<HTMLDivElement>(null)
  const drag = useRef<{ handle: Handle; x: number; y: number; start: Rect } | null>(null)

  useEffect(() => {
    const im = new Image()
    im.onload = () => setSource(im)
    im.onerror = () => setError('Could not load the picture')
    im.src = api.previewUrl(img.id, img.mtime)
  }, [img.id, img.mtime])

  useLayoutEffect(() => {
    const el = areaRef.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setBox({ w: e.contentRect.width - 24, h: e.contentRect.height - 24 }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const sideways = rotate % 180 !== 0
  const srcW = source?.naturalWidth ?? 1
  const srcH = source?.naturalHeight ?? 1
  const viewW = sideways ? srcH : srcW
  const viewH = sideways ? srcW : srcH
  const scale = Math.min(box.w / viewW, box.h / viewH, 1)
  const cssW = Math.max(1, Math.round(viewW * scale))
  const cssH = Math.max(1, Math.round(viewH * scale))

  // Draw the rotated/flipped picture. Adjustments are a CSS filter on the canvas (cheap, live).
  useEffect(() => {
    const c = canvasRef.current
    if (!c || !source) return
    const dpr = window.devicePixelRatio || 1
    c.width = cssW * dpr
    c.height = cssH * dpr
    const ctx = c.getContext('2d')!
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, cssW, cssH)
    ctx.translate(cssW / 2, cssH / 2)
    ctx.scale(flipH ? -1 : 1, flipV ? -1 : 1) // applied after rotation, in screen axes (matches the backend)
    ctx.rotate((rotate * Math.PI) / 180)
    const dw = srcW * scale
    const dh = srcH * scale
    ctx.drawImage(source, -dw / 2, -dh / 2, dw, dh)
  }, [source, rotate, flipH, flipV, cssW, cssH, scale, srcW, srcH])

  const fitAspect = (r: number | null): Rect => {
    if (!r) return { x: 0, y: 0, w: 1, h: 1 }
    let w = 1
    let h = (cssW / r) / cssH
    if (h > 1) { h = 1; w = (cssH * r) / cssW }
    return { x: (1 - w) / 2, y: (1 - h) / 2, w, h }
  }

  const startCrop = () => { setCropping(true); setCrop((c) => c ?? fitAspect(aspect)) }
  const chooseAspect = (r: number | null) => { setAspect(r); setCrop(fitAspect(r)); setCropping(true) }
  const turn = (deg: 90 | -90) => { setRotate((r) => (((r + deg + 360) % 360) as EditRequest['rotate'])); setCrop(null); setCropping(false) }
  const flip = (axis: 'h' | 'v') => { (axis === 'h' ? setFlipH : setFlipV)((v) => !v); setCrop(null); setCropping(false) }

  // Drag tracking lives on window so fast pointer moves outside the handle never drop the drag.
  const onDown = (handle: Handle) => (e: React.PointerEvent) => {
    if (!crop) return
    e.preventDefault()
    e.stopPropagation()
    drag.current = { handle, x: e.clientX, y: e.clientY, start: crop }
    const move = (ev: PointerEvent) => onMove(ev)
    const up = () => {
      drag.current = null
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }
  const onMove = (e: PointerEvent) => {
    const d = drag.current
    if (!d) return
    const dx = (e.clientX - d.x) / cssW
    const dy = (e.clientY - d.y) / cssH
    const s = d.start
    if (d.handle === 'move') {
      setCrop({ ...s, x: clamp(s.x + dx, 0, 1 - s.w), y: clamp(s.y + dy, 0, 1 - s.h) })
      return
    }
    const left = d.handle.includes('w')
    const top = d.handle.includes('n')
    // Anchor = the opposite corner, which stays put.
    const ax = left ? s.x + s.w : s.x
    const ay = top ? s.y + s.h : s.y
    let w = clamp(left ? s.w - dx : s.w + dx, MIN, left ? ax : 1 - ax)
    let h = clamp(top ? s.h - dy : s.h + dy, MIN, top ? ay : 1 - ay)
    if (aspect) {
      const hFromW = (w * cssW) / aspect / cssH
      const maxH = top ? ay : 1 - ay
      if (hFromW <= maxH) h = hFromW
      else { h = maxH; w = (h * cssH * aspect) / cssW }
    }
    setCrop({ x: left ? ax - w : ax, y: top ? ay - h : ay, w, h })
  }

  const reset = () => {
    setRotate(0); setFlipH(false); setFlipV(false); setCrop(null); setCropping(false); setAspect(null)
    setBrightness(1); setContrast(1); setSaturation(1)
  }

  const cropActive = crop && (crop.w < 0.999 || crop.h < 0.999)
  const dirty = rotate || flipH || flipV || cropActive || brightness !== 1 || contrast !== 1 || saturation !== 1
  const heic = !['.jpg', '.jpeg', '.png', '.webp', '.tif', '.tiff', '.bmp', '.gif'].includes(img.ext)

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      const r = await api.edit(img.id, {
        rotate, flip_h: flipH, flip_v: flipV, crop: cropActive ? crop : null,
        brightness: round(brightness), contrast: round(contrast), saturation: round(saturation), mode,
      })
      onSaved(r)
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  return (
    <div className="editor" role="dialog" aria-modal="true" aria-label={`Edit ${img.filename}`}>
      <header className="viewer-bar">
        <button className="icon-btn" onClick={onClose} aria-label="Cancel editing (Esc)"><Icon name="close" /></button>
        <div className="viewer-title"><strong>Edit</strong><span className="muted small ellipsis">{img.filename}</span></div>
        <div className="viewer-tools">
          <button onClick={reset} disabled={!dirty}>Reset</button>
        </div>
      </header>

      <div className="editor-area" ref={areaRef}>
        <div className="editor-canvas" style={{ width: cssW, height: cssH }}>
          <canvas ref={canvasRef} style={{ width: cssW, height: cssH, filter: `brightness(${brightness}) contrast(${contrast}) saturate(${saturation})` }} />
          {cropping && crop && (
            <div className="crop-layer">
              <div className="crop-rect" onPointerDown={onDown('move')}
                style={{ left: `${crop.x * 100}%`, top: `${crop.y * 100}%`, width: `${crop.w * 100}%`, height: `${crop.h * 100}%` }}>
                {(['nw', 'ne', 'sw', 'se'] as Handle[]).map((h) => (
                  <span key={h} className={`crop-handle ${h}`} onPointerDown={onDown(h)} />
                ))}
              </div>
            </div>
          )}
        </div>
        {!source && !error && <p className="muted">Loading…</p>}
      </div>

      <aside className="editor-panel">
        <section>
          <h3>Rotate &amp; flip</h3>
          <div className="btn-row">
            <button onClick={() => turn(-90)} aria-label="Rotate left"><Icon name="rotate" className="mirror" /> Left</button>
            <button onClick={() => turn(90)} aria-label="Rotate right"><Icon name="rotate" /> Right</button>
            <button onClick={() => flip('h')} className={flipH ? 'on' : ''} aria-pressed={flipH} aria-label="Flip horizontally"><Icon name="flipH" /> Flip</button>
            <button onClick={() => flip('v')} className={flipV ? 'on' : ''} aria-pressed={flipV} aria-label="Flip vertically"><Icon name="flipV" /> Flip</button>
          </div>
        </section>
        <section>
          <h3>Crop</h3>
          <div className="btn-row">
            {ASPECTS.map((a) => (
              <button key={a.label} className={cropping && aspect === a.value ? 'on' : ''} onClick={() => chooseAspect(a.value)}>{a.label}</button>
            ))}
          </div>
          <div className="btn-row">
            {!cropping
              ? <button onClick={startCrop}><Icon name="crop" /> Crop</button>
              : <button onClick={() => { setCropping(false); setCrop(null) }}>Remove crop</button>}
          </div>
        </section>
        <section>
          <h3>Adjust</h3>
          <Slider label="Brightness" value={brightness} min={0.2} max={2} onChange={setBrightness} />
          <Slider label="Contrast" value={contrast} min={0.2} max={2} onChange={setContrast} />
          <Slider label="Saturation" value={saturation} min={0} max={2} onChange={setSaturation} />
        </section>
        <section>
          <h3>Save as</h3>
          <label className="radio"><input type="radio" name="save-mode" aria-label="Save as new copy" checked={mode === 'copy'} onChange={() => setMode('copy')} /> New copy (original untouched)</label>
          <label className="radio"><input type="radio" name="save-mode" aria-label="Replace original" checked={mode === 'overwrite'} disabled={heic} onChange={() => setMode('overwrite')} /> Replace original</label>
          {heic && <p className="muted small">HEIC edits are saved as a JPEG copy.</p>}
          {mode === 'overwrite' && (
            <label className="radio warn"><input type="checkbox" aria-label="Confirm replacing the original" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
              Replace {img.filename}. A backup is kept in PixSift's data folder.</label>
          )}
        </section>
        {error && <p className="error">{error}</p>}
        <div className="btn-row end">
          <button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={!dirty || busy || (mode === 'overwrite' && !confirmed)} onClick={save}>
            {busy ? 'Saving…' : 'Save'}
          </button>
        </div>
      </aside>
    </div>
  )
}

function Slider({ label, value, min, max, onChange }: { label: string; value: number; min: number; max: number; onChange: (v: number) => void }) {
  return (
    <label className="slider">
      <span>{label}</span>
      <input type="range" aria-label={label} min={min} max={max} step={0.01} value={value} onChange={(e) => onChange(Number(e.target.value))}
        onDoubleClick={() => onChange(1)} />
      <output>{value > 1 ? '+' : ''}{Math.round((value - 1) * 100)}</output>
    </label>
  )
}

const round = (v: number) => Math.round(v * 100) / 100
