import { useEffect, useRef, useMemo } from 'react'
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d'
import type { GraphEdge, GraphNode } from '../api/client'

interface GraphViewProps {
  nodes: GraphNode[]
  edges: GraphEdge[]
  highlightedNodeIds?: string[]
}

interface ForceNode {
  id: string
  name: string
  type: string
  color?: string
}

interface ForceLink {
  source: string
  target: string
  type: string
}

const TYPE_COLORS: Record<string, string> = {
  Material: '#38bdf8',
  Process: '#a78bfa',
  Property: '#fbbf24',
  Experiment: '#34d399',
  Publication: '#f472b6',
  Expert: '#fb923c',
  Facility: '#94a3b8',
  Equipment: '#64748b',
}

export default function GraphView({
  nodes,
  edges,
  highlightedNodeIds = [],
}: GraphViewProps) {
  const fgRef = useRef<ForceGraphMethods<ForceNode, ForceLink> | undefined>(undefined)
  const highlightSet = useMemo(() => new Set(highlightedNodeIds), [highlightedNodeIds])

  const graphData = useMemo(() => {
    const forceNodes: ForceNode[] = nodes.map((n) => ({
      id: n.id,
      name: n.name,
      type: n.type,
      color: highlightSet.has(n.id) ? '#fef08a' : TYPE_COLORS[n.type] ?? '#94a3b8',
    }))
    const forceLinks: ForceLink[] = edges.map((e) => ({
      source: e.source,
      target: e.target,
      type: e.type,
    }))
    return { nodes: forceNodes, links: forceLinks }
  }, [nodes, edges, highlightSet])

  useEffect(() => {
    if (graphData.nodes.length > 0) {
      fgRef.current?.zoomToFit(400, 40)
    }
  }, [graphData])

  if (nodes.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-slate-500 text-sm border border-dashed border-slate-700 rounded-lg">
        Граф появится после запроса
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      <h2 className="text-lg font-semibold mb-2 text-cyan-300">Граф знаний</h2>
      <div className="flex-1 rounded-lg border border-slate-700 overflow-hidden bg-slate-900">
        <ForceGraph2D
          ref={fgRef}
          graphData={graphData}
          nodeLabel="name"
          nodeColor={(n) => (n as ForceNode).color ?? '#94a3b8'}
          linkDirectionalArrowLength={3}
          linkDirectionalArrowRelPos={1}
          linkColor={() => '#475569'}
          backgroundColor="#0f172a"
          width={undefined}
          height={undefined}
        />
      </div>
    </div>
  )
}
