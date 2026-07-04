import { useCallback, useState } from 'react'
import { getDocumentLink } from '../api/client'

export function useOpenDocument() {
  const [loading, setLoading] = useState(false)
  const [unavailable, setUnavailable] = useState(false)

  const openDocument = useCallback(async (docId: string) => {
    if (loading || unavailable) return
    setLoading(true)
    try {
      const { url } = await getDocumentLink(docId)
      window.open(url, '_blank', 'noopener,noreferrer')
    } catch {
      setUnavailable(true)
    } finally {
      setLoading(false)
    }
  }, [loading, unavailable])

  return { openDocument, loading, unavailable }
}
