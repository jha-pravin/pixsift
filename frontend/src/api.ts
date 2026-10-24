export type Category = 'document' | 'screenshot' | 'photo' | 'graphic'
export type CategoryFilter = Category | 'people' | 'unsorted'

export interface ImageItem {
  id: number
  path: string
  folder: string
  filename: string
  ext: string
  size: number
  width: number | null
  height: number | null
  taken_at: string | null
  date_source: 'exif' | 'file' | null
  thumb: string | null
  error: string | null
  missing: number
  category: Category | null
  face_count: number
  camera_model: string | null
}

export interface Face {
  id: number
  x: number
  y: number
  w: number
  h: number
  person_id: number | null
  person_name: string | null
  cluster_id: number | null
  ignored: number
  assigned_by: 'user' | 'carry' | 'auto' | null
}

export interface ImageDetail extends ImageItem {
  quick_hash: string | null
  camera_make: string | null
  gps_lat: number | null
  gps_lon: number | null
  has_exif: number
  scanned_at: string
  mtime: number
  clip_scores: string | null
  category_locked: number
  analyzed_at: string | null
  edited_from: number | null
  duplicates: { id: number; path: string }[]
  edits: { id: number; path: string }[]
  faces: Face[]
  tags: string[]
}

export interface ImagePage {
  total: number
  offset: number
  limit: number
  items: ImageItem[]
}

export interface ImageQuery {
  category?: CategoryFilter
  person?: number[]
  tag?: string
  folder?: string
  q?: string
  date_from?: string
  date_to?: string
  duplicates?: boolean
  sort?: Sort
}

export interface Stats {
  total: number
  errors: number
  bytes: number
  folders: number
  pending: number
  people: number
  unnamed_groups: number
  auto_named: number
  duplicate_groups: number
  duplicate_files: number
}

export interface Dashboard {
  categories: { key: CategoryFilter; count: number; samples: number[] }[]
  recent: number[]
  stats: Stats
}

export interface ModelStatus {
  ready: boolean
  total_bytes: number
  missing_bytes: number
  downloading: string | null
  downloaded_bytes: number
}

export interface JobStatus {
  state: 'idle' | 'running' | 'done' | 'cancelled' | 'error'
  phase: 'models' | 'scanning' | 'analyzing' | 'grouping' | null
  roots: string[]
  current_root: string | null
  found: number
  processed: number
  unchanged: number
  errors: number
  missing: number
  to_analyze: number
  analyzed: number
  finished_at: number | null
  message: string | null
  models: ModelStatus
}

export interface Person {
  id: number
  name: string
  cover_face_id: number | null
  count: number
  auto_count: number
  first_seen: string | null
  last_seen: string | null
}

export interface PersonDetail extends Person {
  cameras: { camera: string; count: number }[]
  folders: { folder: string; count: number }[]
  years: { year: string; count: number }[]
  places: { id: number; lat: number; lon: number; taken_at: string }[]
  together: { id: number; name: string; count: number }[]
}

export interface Suggestion {
  person_id: number
  name: string
  similarity: number
}

export interface FaceGroup {
  cluster_id: number
  count: number
  faces: { id: number; image_id: number }[]
  suggestion: Suggestion | null
}

export interface Health {
  version: string
  platform: string
  reveal_label: string
}

export interface EditRequest {
  rotate: 0 | 90 | 180 | 270
  flip_h: boolean
  flip_v: boolean
  crop: { x: number; y: number; w: number; h: number } | null
  brightness: number
  contrast: number
  saturation: number
  mode: 'copy' | 'overwrite'
}

export type Sort = 'taken_desc' | 'taken_asc' | 'name' | 'size_desc'

/** Name a face/group: an existing person, a new or existing name, or clear the name. */
export type NameTarget = { person_id: number } | { name: string } | { clear: true }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const detail = body?.detail
    const err = new Error(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail[0]?.msg : `${res.status} ${res.statusText}`)
    throw Object.assign(err, { status: res.status })
  }
  return res.json() as Promise<T>
}

const send = <T>(method: string, path: string, body?: unknown) =>
  request<T>(path, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-PixSift': '1' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

function imageQueryString(q: ImageQuery & { offset: number; limit: number }) {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(q)) {
    if (v === undefined || v === '' || v === false) continue
    if (Array.isArray(v)) v.forEach((x) => qs.append(k, String(x)))
    else qs.set(k, String(v))
  }
  return qs.toString()
}

const enc = encodeURIComponent

export const api = {
  health: () => request<Health>('/api/health'),
  stats: () => request<Stats>('/api/stats'),
  dashboard: () => request<Dashboard>('/api/dashboard'),
  suggestedRoots: () => request<{ path: string; label: string }[]>('/api/suggested-roots'),
  roots: () => request<{ path: string; last_scanned: string }[]>('/api/roots'),
  folders: () => request<{ folder: string; count: number }[]>('/api/folders'),
  tags: () => request<{ tag: string; count: number }[]>('/api/tags'),
  images: (q: ImageQuery & { offset: number; limit: number }) => request<ImagePage>(`/api/images?${imageQueryString(q)}`),
  image: (id: number) => request<ImageDetail>(`/api/images/${id}`),

  job: () => request<JobStatus>('/api/job'),
  scan: (roots: string[]) => send<JobStatus>('POST', '/api/scan', { roots }),
  analyze: () => send<JobStatus>('POST', '/api/analyze'),
  cancelJob: () => send<JobStatus>('POST', '/api/job/cancel'),

  reveal: (id: number) => send<{ ok: boolean }>('POST', `/api/images/${id}/reveal`),
  open: (id: number) => send<{ ok: boolean }>('POST', `/api/images/${id}/open`),
  setCategory: (id: number, category: Category | null) => send('PUT', `/api/images/${id}/category`, { category }),
  addTag: (id: number, tag: string) => send('POST', `/api/images/${id}/tags`, { tag }),
  removeTag: (id: number, tag: string) => send('DELETE', `/api/images/${id}/tags/${enc(tag)}`),
  edit: (id: number, req: EditRequest) => send<{ id: number; path: string; copy: boolean }>('POST', `/api/images/${id}/edit`, req),

  persons: (sort: 'count' | 'name' = 'count') => request<Person[]>(`/api/persons?sort=${sort}`),
  person: (id: number) => request<PersonDetail>(`/api/persons/${id}`),
  personFaces: (id: number) => request<{ id: number; image_id: number; assigned_by: string }[]>(`/api/persons/${id}/faces`),
  confirmAuto: (id: number, faceIds?: number[]) =>
    send<{ auto_named: number }>('POST', `/api/persons/${id}/confirm-auto`, { face_ids: faceIds ?? null }),
  renamePerson: (id: number, name: string) => send('PATCH', `/api/persons/${id}`, { name }),
  setCover: (id: number, cover_face_id: number) => send('PATCH', `/api/persons/${id}`, { cover_face_id }),
  deletePerson: (id: number) => send('DELETE', `/api/persons/${id}`),
  mergePerson: (id: number, into_id: number) => send('POST', `/api/persons/${id}/merge`, { into_id }),

  faceGroups: () => request<FaceGroup[]>('/api/face-groups'),
  nameGroup: (clusterId: number, target: NameTarget) =>
    send<{ person_id: number; auto_named: number }>('POST', `/api/face-groups/${clusterId}/name`, target),
  ignoreGroup: (clusterId: number) => send('POST', `/api/face-groups/${clusterId}/ignore`),
  assignFaces: (faceIds: number[], target: NameTarget) =>
    send<{ person_id: number | null; auto_named: number }>('POST', '/api/faces/assign', { face_ids: faceIds, ...target }),
  rejectFace: (faceId: number) => send('POST', `/api/faces/${faceId}/reject`),
  ignoreFace: (faceId: number) => send('POST', `/api/faces/${faceId}/ignore`),
  faceSuggestion: (faceId: number) => request<{ suggestion: Suggestion | null }>(`/api/faces/${faceId}/suggestion`),

  thumbUrl: (id: number) => `/api/images/${id}/thumb`,
  previewUrl: (id: number, version?: number | string) => `/api/images/${id}/preview${version ? `?v=${version}` : ''}`,
  faceUrl: (faceId: number) => `/api/faces/${faceId}/crop`,
}

export const CATEGORY_LABELS: Record<CategoryFilter, string> = {
  people: 'People',
  photo: 'Photos',
  document: 'Documents',
  screenshot: 'Screenshots',
  graphic: 'Graphics',
  unsorted: 'Not analysed yet',
}

export const formatBytes = (n: number) => {
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i++
  }
  return `${n.toFixed(i ? 1 : 0)} ${units[i]}`
}

export const formatDate = (iso: string | null, withTime = true) =>
  iso
    ? new Date(iso).toLocaleString(undefined, withTime ? { dateStyle: 'medium', timeStyle: 'short' } : { dateStyle: 'medium' })
    : '—'

export const monthLabel = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { month: 'long', year: 'numeric' }) : 'Unknown date'

/** Native multi-folder picker inside the desktop app (pywebview); undefined in a plain browser. */
export async function pickFolders(): Promise<string[] | undefined> {
  const bridge = (window as unknown as { pywebview?: { api?: { pick_folders?: () => Promise<string[]> } } }).pywebview
  if (!bridge?.api?.pick_folders) return undefined
  return bridge.api.pick_folders()
}
