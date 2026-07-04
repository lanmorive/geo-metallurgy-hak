import type { GraphNode } from '../api/client'

const GEO_LABELS: Record<string, string> = {
  RU: 'Россия',
  WORLD: 'мир',
}

export type ConfidenceLevel = 'high' | 'medium' | 'low'

export function getConfidenceFromProps(properties: Record<string, unknown>): number | null {
  const conf = properties.confidence
  return typeof conf === 'number' ? conf : null
}

export function confidenceLevel(conf: number): ConfidenceLevel {
  if (conf >= 0.8) return 'high'
  if (conf >= 0.6) return 'medium'
  return 'low'
}

export function confidenceDotClass(level: ConfidenceLevel): string {
  switch (level) {
    case 'high':
      return 'bg-green-500'
    case 'medium':
      return 'bg-yellow-500'
    case 'low':
      return 'bg-neutral-400'
  }
}

export function formatGeography(value: unknown): string | null {
  if (typeof value !== 'string' || !value.trim() || value === 'UNKNOWN') return null
  return GEO_LABELS[value] ?? value
}

export function formatAliases(properties: Record<string, unknown>): string | null {
  const raw = properties.aliases
  if (!Array.isArray(raw)) return null
  const aliases = raw
    .filter((a): a is string => typeof a === 'string' && a.trim().length > 0)
    .map((a) => a.trim())
  if (aliases.length === 0) return null
  return aliases.join(', ')
}

export function getSourceDoc(properties: Record<string, unknown>): string | null {
  const doc = properties.source_doc
  return typeof doc === 'string' && doc.trim() ? doc : null
}

export function resolvePublicationTitle(nodes: GraphNode[], sourceDoc: string): string | null {
  const pub = nodes.find((n) => n.type === 'Publication' && n.id === sourceDoc)
  if (!pub) return null
  if (pub.name.trim()) return pub.name
  const title = pub.properties.title
  return typeof title === 'string' && title.trim() ? title : null
}

export function formatPublicationMeta(properties: Record<string, unknown>): string | null {
  const parts: string[] = []

  const year = properties.year
  if (typeof year === 'number') {
    parts.push(String(year))
  }

  const venue = properties.venue
  if (typeof venue === 'string' && venue.trim()) {
    parts.push(venue.trim())
  } else {
    const docType = properties.doc_type
    if (typeof docType === 'string' && docType.trim()) {
      parts.push(docType.trim())
    }
  }

  return parts.length > 0 ? parts.join(' · ') : null
}
