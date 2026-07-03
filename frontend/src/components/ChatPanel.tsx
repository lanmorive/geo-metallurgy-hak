import { useRef, useEffect, useState } from 'react'
import { ArrowUp } from 'lucide-react'
import type { ConversationItem } from '../hooks/useQuerySystem'
import { DEMO_QUERIES } from '../constants/demoQueries'
import AnswerCard, { AnswerCardError, AnswerCardSkeleton } from './AnswerCard'

interface ChatPanelProps {
  conversation: ConversationItem[]
  loading: boolean
  onSubmit: (query: string) => void
  onRetry: () => void
  onCitationClick: (docId: string) => void
}

function ExampleChips({ onSelect }: { onSelect: (query: string) => void }) {
  return (
    <div className="flex flex-wrap gap-2 justify-center">
      {DEMO_QUERIES.map((q) => (
        <button
          key={q.short}
          type="button"
          onClick={() => onSelect(q.full)}
          className="px-3 py-1.5 text-xs rounded-pill border border-surface-border bg-surface-card text-neutral-700 hover:bg-neutral-50 hover:border-brand-primary/30 transition-colors"
        >
          {q.short}
        </button>
      ))}
    </div>
  )
}

export default function ChatPanel({
  conversation,
  loading,
  onSubmit,
  onRetry,
  onCitationClick,
}: ChatPanelProps) {
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)

  const isEmpty = conversation.length === 0 && !loading

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [conversation, loading])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const query = input.trim()
    if (!query || loading) return
    onSubmit(query)
    setInput('')
  }

  const handleChipSelect = (query: string) => {
    if (loading) return
    onSubmit(query)
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-4 min-h-0">
        {isEmpty && (
          <div className="flex flex-col items-center justify-center h-full gap-6 py-12">
            <h2 className="text-lg font-medium text-neutral-800 text-center">
              Задайте вопрос корпусу знаний
            </h2>
            <ExampleChips onSelect={handleChipSelect} />
          </div>
        )}

        {conversation.map((item) => {
          if (item.role === 'user' && item.query) {
            return (
              <div key={item.id} className="flex justify-end">
                <div className="max-w-[85%] rounded-card bg-neutral-100 px-4 py-3 text-sm text-neutral-800">
                  {item.query}
                </div>
              </div>
            )
          }

          if (item.role === 'assistant') {
            if (item.error) {
              return (
                <div key={item.id}>
                  <AnswerCardError message={item.error} onRetry={onRetry} />
                </div>
              )
            }
            if (item.response) {
              return (
                <div key={item.id}>
                  <AnswerCard
                    response={item.response}
                    onCitationClick={onCitationClick}
                  />
                </div>
              )
            }
          }

          return null
        })}

        {loading && (
          <div className="space-y-2">
            <AnswerCardSkeleton />
            <p className="text-xs text-neutral-500 animate-pulse text-center">
              Ищу связи в графе…
            </p>
          </div>
        )}
      </div>

      {!isEmpty && (
        <div className="px-4 pb-2">
          <ExampleChips onSelect={handleChipSelect} />
        </div>
      )}

      <div className="px-4 pb-4 pt-2 border-t border-surface-border">
        <form onSubmit={handleSubmit} className="flex items-center gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Задайте вопрос по корпусу знаний…"
            disabled={loading}
            className="flex-1 rounded-pill border border-surface-border bg-surface-card px-4 py-2.5 text-sm focus:outline-none focus:border-brand-primary disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="shrink-0 w-9 h-9 flex items-center justify-center rounded-full bg-neutral-900 text-white disabled:opacity-40 hover:opacity-90 transition-opacity"
            aria-label="Отправить"
          >
            <ArrowUp size={16} />
          </button>
        </form>
      </div>
    </div>
  )
}
