import ReactMarkdown from 'react-markdown'
import { Download, AlertTriangle, HelpCircle, User } from 'lucide-react'
import type { QueryResponse } from '../api/client'

interface AnswerCardProps {
  response: QueryResponse | null
  loading: boolean
}

export default function AnswerCard({ response, loading }: AnswerCardProps) {
  if (loading) {
    return (
      <div className="rounded-lg bg-slate-800/50 border border-slate-700 p-6 animate-pulse">
        <p className="text-slate-400">Анализ графа знаний…</p>
      </div>
    )
  }

  if (!response) {
    return (
      <div className="rounded-lg bg-slate-800/30 border border-dashed border-slate-700 p-6 text-slate-500 text-sm">
        Ответ появится после запроса
      </div>
    )
  }

  const exportMarkdown = () => {
    const parts = [
      response.answer_markdown,
      '',
      '## Цитаты',
      ...response.citations.map(
        (c) => `- [${c.doc_id}] ${c.title} (${c.confidence}) — ${c.snippet}`,
      ),
      '',
      '## Противоречия',
      ...response.contradictions.map((c) => `- ${c.description}`),
      '',
      '## Пробелы знаний',
      ...response.knowledge_gaps.map((g) => `- ${g.description}`),
    ]
    const blob = new Blob([parts.join('\n')], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'nauchny-klubok-answer.md'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="rounded-lg bg-slate-800/50 border border-slate-700 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-slate-700 bg-slate-800">
        <span className="font-medium text-cyan-300">Обзор</span>
        <div className="flex items-center gap-2">
          {response.mock && (
            <span className="text-xs bg-amber-900/50 text-amber-300 px-2 py-0.5 rounded">
              mock
            </span>
          )}
          <button
            onClick={exportMarkdown}
            className="text-xs flex items-center gap-1 text-slate-300 hover:text-white"
          >
            <Download size={14} /> MD
          </button>
        </div>
      </div>

      {response.warning && (
        <div className="px-4 py-2 bg-amber-900/20 text-amber-200 text-xs flex gap-2">
          <AlertTriangle size={14} className="shrink-0 mt-0.5" />
          {response.warning}
        </div>
      )}

      <div className="p-4 prose prose-invert prose-sm max-w-none">
        <ReactMarkdown>{response.answer_markdown}</ReactMarkdown>
      </div>

      {response.citations.length > 0 && (
        <div className="px-4 pb-4">
          <h3 className="text-sm font-semibold text-slate-300 mb-2">Цитаты</h3>
          <ul className="space-y-2 text-xs">
            {response.citations.map((c) => (
              <li key={c.doc_id} className="bg-slate-900/50 rounded p-2">
                <span className="text-cyan-400">[{c.doc_id}]</span> {c.title}
                <span className="text-slate-500 ml-2">
                  conf={c.confidence} · {c.geography} · {c.year}
                </span>
                <p className="text-slate-400 mt-1">{c.snippet}</p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {response.contradictions.length > 0 && (
        <div className="px-4 pb-4 border-t border-slate-700 pt-3">
          <h3 className="text-sm font-semibold text-red-300 flex items-center gap-1 mb-2">
            <AlertTriangle size={14} /> Противоречия
          </h3>
          {response.contradictions.map((c, i) => (
            <div key={i} className="text-xs bg-red-950/30 rounded p-2 mb-2">
              <p>{c.description}</p>
              <p className="text-slate-500 mt-1">
                {c.source_a} vs {c.source_b}
              </p>
            </div>
          ))}
        </div>
      )}

      {response.knowledge_gaps.length > 0 && (
        <div className="px-4 pb-4 border-t border-slate-700 pt-3">
          <h3 className="text-sm font-semibold text-violet-300 flex items-center gap-1 mb-2">
            <HelpCircle size={14} /> Пробелы знаний
          </h3>
          {response.knowledge_gaps.map((g, i) => (
            <div key={i} className="text-xs bg-violet-950/30 rounded p-2 mb-2">
              <p>{g.description}</p>
              <p className="text-slate-500 mt-1">
                {g.entities.join(' · ')} → нет {g.missing_link}
              </p>
            </div>
          ))}
        </div>
      )}

      {response.recommended_experts.length > 0 && (
        <div className="px-4 pb-4 border-t border-slate-700 pt-3">
          <h3 className="text-sm font-semibold text-emerald-300 flex items-center gap-1 mb-2">
            <User size={14} /> Эксперты
          </h3>
          {response.recommended_experts.map((ex) => (
            <div key={ex.name} className="text-xs mb-2">
              <span className="font-medium">{ex.name}</span>
              {ex.affiliation && (
                <span className="text-slate-500"> — {ex.affiliation}</span>
              )}
              <span className="text-slate-500 ml-2">
                ({ex.publication_count} публ.)
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
