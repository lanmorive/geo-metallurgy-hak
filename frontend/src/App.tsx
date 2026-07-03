import { useEffect, useState } from 'react'
import { FileDown, Network } from 'lucide-react'
import Filters from './components/Filters'
import ChatPanel from './components/ChatPanel'
import GraphView from './components/GraphView'
import { getSubgraph, type GraphEdge, type GraphNode } from './api/client'
import { useQuerySystem } from './hooks/useQuerySystem'

function formatEntityCount(count: number | null): string {
  if (count == null) return '—'
  return count.toLocaleString('ru-RU')
}

function exportMarkdown(markdown: string) {
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'nauchny-klubok-answer.md'
  a.click()
  URL.revokeObjectURL(url)
}

export default function App() {
  const {
    filters,
    setFilters,
    conversation,
    loading,
    entityCount,
    currentResponse,
    highlightedNodeId,
    flashNodeId,
    highlightNode,
    sendQuery,
    retryLast,
  } = useQuerySystem()

  const [previewNodes, setPreviewNodes] = useState<GraphNode[]>([])
  const [previewEdges, setPreviewEdges] = useState<GraphEdge[]>([])

  useEffect(() => {
    getSubgraph({ limit: 150 })
      .then((data) => {
        setPreviewNodes(data.nodes)
        setPreviewEdges(data.edges)
      })
      .catch(() => {
        setPreviewNodes([])
        setPreviewEdges([])
      })
  }, [])

  const graphNodes = currentResponse?.graph_subset.nodes ?? previewNodes
  const graphEdges = currentResponse?.graph_subset.edges ?? previewEdges
  const citedNodeIds =
    currentResponse?.graph_subset.nodes.map((n) => n.id) ?? []

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <header className="h-14 shrink-0 border-b border-surface-border bg-surface-card flex items-center justify-between px-4">
        <div className="flex items-center gap-3 min-w-0">
          <Network className="w-5 h-5 text-brand-primary shrink-0" />
          <h1 className="text-sm font-medium text-neutral-900 shrink-0">Научный клубок</h1>
          <span className="text-xs px-2.5 py-1 rounded-pill border border-surface-border bg-neutral-50 text-neutral-600 font-mono shrink-0">
            граф: {formatEntityCount(entityCount)} сущностей
          </span>
        </div>
        <button
          type="button"
          onClick={() => {
            if (currentResponse?.answer_markdown) {
              exportMarkdown(currentResponse.answer_markdown)
            }
          }}
          disabled={!currentResponse?.answer_markdown}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-control border border-surface-border text-neutral-700 hover:bg-neutral-50 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <FileDown size={14} />
          Экспорт MD
        </button>
      </header>

      <div className="flex-1 grid grid-cols-[240px_minmax(0,1fr)_360px] min-h-0">
        <aside className="border-r border-surface-border overflow-hidden min-h-0">
          <Filters filters={filters} onChange={setFilters} />
        </aside>

        <main className="min-h-0 overflow-hidden">
          <ChatPanel
            conversation={conversation}
            loading={loading}
            onSubmit={sendQuery}
            onRetry={retryLast}
            onCitationClick={highlightNode}
          />
        </main>

        <aside className="border-l border-surface-border min-h-0 overflow-hidden">
          <GraphView
            nodes={graphNodes}
            edges={graphEdges}
            citedNodeIds={citedNodeIds}
            highlightedNodeId={highlightedNodeId}
            flashNodeId={flashNodeId}
            onSendQuery={sendQuery}
          />
        </aside>
      </div>
    </div>
  )
}
