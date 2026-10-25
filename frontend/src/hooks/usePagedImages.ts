import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type ImageItem, type ImageQuery } from '../api'

const PAGE = 120
const MAX_REFRESH = 500 // the API's page limit

/**
 * Loads images matching `query` page by page (infinite scroll).
 * - A new query starts again from the first page.
 * - A `version` bump (data changed, e.g. while analysis runs) refreshes *in place*: everything already
 *   scrolled through stays loaded, so the list never jumps back to the top.
 */
export function usePagedImages(query: ImageQuery, version = 0) {
  const [items, setItems] = useState<ImageItem[]>([])
  const [total, setTotal] = useState(0)
  const [loaded, setLoaded] = useState(false)
  const key = JSON.stringify(query)
  const inflight = useRef<string | null>(null)
  const generation = useRef(0)
  const loadedCount = useRef(0)
  const lastKey = useRef<string | null>(null)

  useEffect(() => {
    loadedCount.current = items.length
  }, [items.length])

  useEffect(() => {
    const gen = ++generation.current
    inflight.current = null
    const fresh = lastKey.current !== key
    lastKey.current = key
    const depth = fresh ? PAGE : Math.max(PAGE, loadedCount.current)
    if (depth > MAX_REFRESH) {
      // Deep in a long list: keep what's loaded, just update the total so scrolling continues correctly.
      api.images({ ...JSON.parse(key), offset: 0, limit: 1 }).then((page) => {
        if (gen === generation.current) setTotal(page.total)
      })
      return
    }
    api.images({ ...JSON.parse(key), offset: 0, limit: depth }).then((page) => {
      if (gen !== generation.current) return
      setItems(page.items)
      setTotal(page.total)
      setLoaded(true)
    })
  }, [key, version])

  const loadMore = useCallback(async () => {
    if (items.length >= total) return
    const marker = `${generation.current}:${items.length}`
    if (inflight.current === marker) return
    inflight.current = marker
    const gen = generation.current
    const page = await api.images({ ...JSON.parse(key), offset: items.length, limit: PAGE })
    if (gen !== generation.current) return
    setItems((prev) => {
      const seen = new Set(prev.map((i) => i.id))
      return [...prev, ...page.items.filter((i) => !seen.has(i.id))]
    })
    setTotal(page.total)
  }, [items.length, total, key])

  return { items, total, loaded, loadMore }
}
