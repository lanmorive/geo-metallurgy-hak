import { useMemo, useState } from 'react'
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import type { Components } from 'react-markdown'
import { Loader2 } from 'lucide-react'
import type { Citation, Contradiction, QueryResponse } from '../api/client'
import { DEMO_QUERIES } from '../constants/demoQueries'
import { useOpenDocument } from '../hooks/useOpenDocument'

interface AnswerCardProps {
  response: QueryResponse
  onCitationClick: (docId: string) => void
  onExampleClick: (query: string) => void
}

function shortDocName(citation: Citation): string {
  const label = citation.title.split(/[.:]/)[0]?.trim() ?? citation.doc_id
  if (label.length <= 16) return label
  return `${label.slice(0, 14)}…`
}

function modeLabel(mode: QueryResponse['meta']['mode']): string {
  if (mode === 'full') return 'граф + синтез'
  if (mode === 'vector+graph') return 'граф знаний'
  return 'поиск по документам'
}

function countCitedDocIds(markdown: string): number {
  const ids = new Set<string>()
  for (const m of markdown.matchAll(/\[doc:([^\]]+)\]/g)) {
    ids.add(m[1])
  }
  return ids.size
}

function preprocessMarkdown(markdown: string): string {
  return markdown.replace(/\[doc:([^\]]+)\]/g, '[$1](cite:$1)')
}

function citationUrlTransform(url: string): string {
  if (url.startsWith('cite:')) return url
  return defaultUrlTransform(url)
}

function CitationBadge({
  citation,
  onCitationClick,
}: {
  citation: Citation
  onCitationClick: (docId: string) => void
}) {
  const { openDocument, loading, unavailable } = useOpenDocument()

  return (
    <span className="inline-flex items-center align-middle mx-0.5 rounded-badge overflow-hidden bg-brand-badgeBg">
      <button
        type="button"
        onClick={() => onCitationClick(citation.doc_id)}
        className="inline-flex items-center px-1.5 py-0.5 text-brand-badgeText text-[10px] font-mono hover:opacity-80"
      >
        {shortDocName(citation)} · {citation.confidence.toFixed(2)}
      </button>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          void openDocument(citation.doc_id)
        }}
        disabled={loading || unavailable}
        title={unavailable ? 'Файл недоступен' : 'Открыть документ'}
        className="inline-flex items-center px-1 py-0.5 text-brand-badgeText text-[10px] hover:opacity-80 disabled:opacity-50 disabled:cursor-not-allowed border-l border-brand-badgeText/20"
      >
        {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : '📄'}
      </button>
    </span>
  )
}

export default function AnswerCard({
  response,
  onCitationClick,
  onExampleClick,
}: AnswerCardProps) {
  const [showContradictions, setShowContradictions] = useState(false)

  const citationMap = useMemo(() => {
    const map = new Map<string, Citation>()
    response.citations.forEach((c) => map.set(c.doc_id, c))
    return map
  }, [response.citations])

  const markdownComponents: Components = useMemo(
    () => ({
      p: ({ children }) => (
        <p className="text-sm leading-relaxed mb-3 last:mb-0">{children}</p>
      ),
      strong: ({ children }) => <strong className="font-medium">{children}</strong>,
      a: ({ href, children }) => {
        if (href?.startsWith('cite:')) {
          const docId = href.slice(5)
          const citation = citationMap.get(docId)
          if (!citation) return <span>{children}</span>
          return (
            <CitationBadge citation={citation} onCitationClick={onCitationClick} />
          )
        }
        return <a href={href}>{children}</a>
      },
    }),
    [citationMap, onCitationClick],
  )

  const processedMarkdown = useMemo(
    () => preprocessMarkdown(response.answer_markdown),
    [response.answer_markdown],
  )

  const consensusCount = countCitedDocIds(response.answer_markdown)
  const showConsensus = response.meta.mode === 'full' && consensusCount >= 2
  const hasContradictions = response.contradictions.length > 0
  const hasExperts = response.recommended_experts.length > 0
  const isEmptyResult = response.citations.length === 0

  if (isEmptyResult) {
    return (
      <div className="w-full rounded-card border border-surface-border bg-surface-card overflow-hidden">
        <div className="px-4 pt-4 pb-3 flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-medium text-neutral-900">Ничего не найдено</h3>
            <p className="text-sm text-neutral-600 mt-1">
              Попробуйте переформулировать запрос или расширить фильтры.
            </p>
          </div>
          <span className="shrink-0 text-[10px] px-2 py-1 rounded-badge border border-surface-border bg-neutral-50 text-neutral-500">
            {modeLabel(response.meta.mode)}
          </span>
        </div>
        <div className="px-4 pb-4 flex flex-wrap gap-2">
          {DEMO_QUERIES.map((q) => (
            <button
              key={q.short}
              type="button"
              onClick={() => onExampleClick(q.full)}
              className="px-3 py-1.5 text-xs rounded-pill border border-surface-border bg-neutral-50 text-neutral-700 hover:bg-surface-card hover:border-brand-primary/30 transition-colors"
            >
              {q.short}
            </button>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="w-full rounded-card border border-surface-border bg-surface-card overflow-hidden">
      <div className="px-4 pt-4 pb-2 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-neutral-900">Ответ по корпусу документов</h3>
          {response.warning && (
            <p className="text-xs text-neutral-500 mt-1">{response.warning}</p>
          )}
        </div>
        <span className="shrink-0 text-[10px] px-2 py-1 rounded-badge border border-surface-border bg-neutral-50 text-neutral-500">
          {modeLabel(response.meta.mode)}
        </span>
      </div>

      <div className="px-4 pb-3 text-neutral-800">
        <ReactMarkdown
          components={markdownComponents}
          urlTransform={citationUrlTransform}
        >
          {processedMarkdown}
        </ReactMarkdown>
      </div>

      {(showConsensus || hasContradictions || response.knowledge_gaps.length > 0) && (
      <div className="px-4 pb-3 flex flex-wrap gap-1.5">
        {showConsensus && (
          <span className="inline-flex items-center px-2.5 py-1 rounded-pill text-xs bg-semantic-consensus-bg text-semantic-consensus-text">
            ✓ Консенсус: {consensusCount} источников
          </span>
        )}
        {hasContradictions && (
          <button
            type="button"
            onClick={() => setShowContradictions((v) => !v)}
            className="inline-flex items-center px-2.5 py-1 rounded-pill text-xs bg-semantic-contradiction-bg text-semantic-contradiction-text hover:opacity-90"
          >
            ⤫ Противоречия: {response.contradictions.length}
          </button>
        )}
        {response.knowledge_gaps.map((gap, i) => (
          <span
            key={i}
            className="inline-flex items-center px-2.5 py-1 rounded-pill text-xs bg-semantic-gap-bg text-semantic-gap-text"
          >
            ◧ Пробел: {gap.description}
          </span>
        ))}
      </div>
      )}

      {showContradictions && hasContradictions && (
        <div className="px-4 pb-3 space-y-2 border-t border-surface-border pt-3 mx-4 mb-3">
          {response.contradictions.map((c: Contradiction, i) => (
            <div
              key={i}
              className="text-xs rounded-control border border-semantic-contradiction-bg bg-semantic-contradiction-bg/50 p-2 text-semantic-contradiction-text"
            >
              <p>{c.description}</p>
              <p className="mt-1 font-mono text-[10px] opacity-75">
                {c.source_a} ↔ {c.source_b}
              </p>
            </div>
          ))}
        </div>
      )}

      {hasExperts && (
        <div className="px-4 pb-4 flex flex-wrap items-center gap-2">
          <span className="text-xs text-neutral-500">Эксперты по теме:</span>
          {response.recommended_experts.map((ex) => (
            <span
              key={ex.name}
              className="px-2.5 py-1 rounded-pill text-xs border border-surface-border bg-neutral-50 text-neutral-700"
            >
              {ex.name}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

export function AnswerCardSkeleton() {
  return (
    <div className="w-full rounded-card border border-surface-border bg-surface-card p-4 animate-pulse">
      <div className="h-4 bg-neutral-200 rounded w-2/3 mb-4" />
      <div className="space-y-2 mb-4">
        <div className="h-3 bg-neutral-100 rounded w-full" />
        <div className="h-3 bg-neutral-100 rounded w-5/6" />
        <div className="h-3 bg-neutral-100 rounded w-4/6" />
      </div>
      <div className="flex gap-2">
        <div className="h-6 bg-neutral-100 rounded-pill w-32" />
        <div className="h-6 bg-neutral-100 rounded-pill w-24" />
      </div>
    </div>
  )
}

export function AnswerCardError({
  message,
  onRetry,
}: {
  message: string
  onRetry: () => void
}) {
  return (
    <div className="w-full rounded-card border border-semantic-contradiction-bg bg-surface-card p-4">
      <p className="text-sm text-semantic-contradiction-text mb-3">{message}</p>
      <button
        type="button"
        onClick={onRetry}
        className="text-xs px-3 py-1.5 rounded-control border border-surface-border hover:bg-neutral-50"
      >
        Повторить
      </button>
    </div>
  )
}
