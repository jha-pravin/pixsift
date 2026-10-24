import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type ImageItem, type ImageQuery } from '../api'

const PAGE = 120

/** Loads images matching `query` page by page. Reloads from the start when the query or `version` changes. */
export function usePagedImages(query: ImageQuery, version = 0) {
  const [items, setItems] = useState<ImageItem[]>([])
  const [total, setTotal] = useState(0)
  const [loaded, setLoaded] = useState(false)
  const key = JSON.stringify(query)
  const inflight = useRef<string | null>(null)
  const generation = useRef(0)

  useEffect(() => {
    const gen = ++generation.current
    inflight.current = null
    api.images({ ...JSON.parse(key), offset: 0, limit: PAGE }).then((page) => {
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
    setItems((prev) => [...prev, ...page.items])
    setTotal(page.total)
  }, [items.length, total, key])

  return { items, total, loaded, loadMore }
}
