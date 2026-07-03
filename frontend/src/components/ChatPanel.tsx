import { useState } from 'react'
import { Send } from 'lucide-react'
import type { QueryFilters, QueryRequest } from '../api/client'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

interface ChatPanelProps {
  onSubmit: (request: QueryRequest) => void
  loading: boolean
  messages: ChatMessage[]
  filters: QueryFilters
}

export default function ChatPanel({ onSubmit, loading, messages, filters }: ChatPanelProps) {
  const [input, setInput] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const query = input.trim()
    if (!query || loading) return
    onSubmit({ query, filters })
    setInput('')
  }

  return (
    <div className="flex flex-col h-full">
      <h2 className="text-lg font-semibold mb-3 text-cyan-300">Чат</h2>
      <div className="flex-1 overflow-y-auto space-y-3 mb-4 pr-2">
        {messages.length === 0 && (
          <p className="text-slate-400 text-sm">
            Задайте вопрос по R&D документам горно-металлургической отрасли…
          </p>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`rounded-lg px-3 py-2 text-sm ${
              msg.role === 'user'
                ? 'bg-cyan-900/40 ml-8'
                : 'bg-slate-800 mr-8'
            }`}
          >
            <span className="text-xs text-slate-500 block mb-1">
              {msg.role === 'user' ? 'Вы' : 'Научный клубок'}
            </span>
            {msg.content}
          </div>
        ))}
      </div>
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Например: методы обессоливания при сульфатах 200–300 мг/л…"
          className="flex-1 rounded-lg bg-slate-800 border border-slate-600 px-3 py-2 text-sm focus:outline-none focus:border-cyan-500"
          disabled={loading}
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="rounded-lg bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 px-4 py-2 flex items-center gap-1"
        >
          <Send size={16} />
        </button>
      </form>
    </div>
  )
}
