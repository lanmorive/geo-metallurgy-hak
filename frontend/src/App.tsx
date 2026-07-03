import { useState, useCallback } from 'react'
import ChatPanel, { type ChatMessage } from './components/ChatPanel'
import Filters from './components/Filters'
import AnswerCard from './components/AnswerCard'
import GraphView from './components/GraphView'
import {
  postQuery,
  type QueryFilters,
  type QueryRequest,
  type QueryResponse,
} from './api/client'

const defaultFilters: QueryFilters = {
  geo: null,
  year_range: [2010, 2025],
  min_confidence: 0,
  numeric_filters: [],
}

export default function App() {
  const [filters, setFilters] = useState<QueryFilters>(defaultFilters)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [response, setResponse] = useState<QueryResponse | null>(null)
  const [loading, setLoading] = useState(false)

  const citedNodeIds = response?.citations.map((c) => c.doc_id) ?? []

  const handleSubmit = useCallback(async (request: QueryRequest) => {
    setMessages((prev) => [...prev, { role: 'user', content: request.query }])
    setLoading(true)
    try {
      const result = await postQuery(request)
      setResponse(result)
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: result.answer_markdown.slice(0, 300) + (result.answer_markdown.length > 300 ? '…' : ''),
        },
      ])
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка запроса'
      setMessages((prev) => [...prev, { role: 'assistant', content: `Ошибка: ${msg}` }])
    } finally {
      setLoading(false)
    }
  }, [])

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-slate-800 px-6 py-4">
        <h1 className="text-xl font-bold text-cyan-300">Научный клубок</h1>
        <p className="text-sm text-slate-400">
          Поисково-аналитическая система на графе знаний R&D документов
        </p>
      </header>

      <main className="flex-1 grid grid-cols-1 lg:grid-cols-12 gap-4 p-4 min-h-0">
        <aside className="lg:col-span-2 bg-slate-900/50 rounded-lg border border-slate-800 p-4">
          <Filters filters={filters} onChange={setFilters} />
        </aside>

        <section className="lg:col-span-5 flex flex-col gap-4 min-h-[60vh]">
          <div className="bg-slate-900/50 rounded-lg border border-slate-800 p-4 flex-1 min-h-[200px]">
            <ChatPanel
              onSubmit={handleSubmit}
              loading={loading}
              messages={messages}
              filters={filters}
            />
          </div>
          <AnswerCard response={response} loading={loading} />
        </section>

        <section className="lg:col-span-5 min-h-[60vh] bg-slate-900/50 rounded-lg border border-slate-800 p-4">
          <GraphView
            nodes={response?.graph_subset.nodes ?? []}
            edges={response?.graph_subset.edges ?? []}
            highlightedNodeIds={citedNodeIds}
          />
        </section>
      </main>
    </div>
  )
}
