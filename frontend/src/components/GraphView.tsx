import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d'
import type { EntityType, GraphEdge, GraphNode } from '../api/client'
import { GRAPH_HIDDEN_ENTITY_TYPES } from '../api/client'
import { colors } from '../theme/tokens'

interface GraphViewProps {
  nodes: GraphNode[]
  edges: GraphEdge[]
  citedNodeIds: string[]
  highlightedNodeId: string | null
  flashNodeId: string | null
  onSendQuery: (text: string) => void
}

interface ForceNode {
  id: string
  label: string
  name: string
  type: EntityType
  properties: Record<string, unknown>
  degree: number
  x?: number
  y?: number
}

interface ForceLink {
  source: string | ForceNode
  target: string | ForceNode
  type: string
}

const ENTITY_TYPES: EntityType[] = [
  'Process',
  'Material',
  'Publication',
  'Experiment',
  'Expert',
  'Organization',
  'Equipment',
  'Property',
  'Facility',
]

const ENTITY_LABELS: Record<EntityType, string> = {
  Process: 'Процесс',
  Material: 'Материал',
  Publication: 'Публикация',
  Experiment: 'Эксперимент',
  Expert: 'Эксперт',
  Organization: 'Организация',
  Equipment: 'Оборудование',
  Property: 'Свойство',
  Facility: 'Объект',
  Chunk: 'Фрагмент',
}

const ENTITY_BG_CLASS: Record<EntityType, string> = {
  Process: 'bg-entity-Process',
  Material: 'bg-entity-Material',
  Publication: 'bg-entity-Publication',
  Experiment: 'bg-entity-Experiment',
  Expert: 'bg-entity-Expert',
  Organization: 'bg-entity-Organization',
  Equipment: 'bg-entity-Equipment',
  Property: 'bg-entity-Property',
  Facility: 'bg-entity-Facility',
  Chunk: 'bg-neutral-300',
}

function truncateLabel(label: string, max = 14): string {
  if (label.length <= max) return label
  return `${label.slice(0, max - 1)}…`
}

function getNodeColor(type: EntityType): string {
  const palette = colors.entity as Record<string, string>
  return palette[type] ?? colors.graph.edge
}

export default function GraphView({
  nodes,
  edges,
  citedNodeIds,
  highlightedNodeId,
  flashNodeId,
  onSendQuery,
}: GraphViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const fgRef = useRef<ForceGraphMethods<ForceNode, ForceLink> | undefined>(undefined)
  const fitPendingRef = useRef(true)
  const [dimensions, setDimensions] = useState({ width: 360, height: 400 })
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)
  const [popoverPos, setPopoverPos] = useState({ x: 0, y: 0 })

  const citedSet = useMemo(() => new Set(citedNodeIds), [citedNodeIds])
  const hiddenTypes = useMemo(() => new Set(GRAPH_HIDDEN_ENTITY_TYPES), [])
  const visibleNodes = useMemo(
    () => nodes.filter((n) => !hiddenTypes.has(n.type)),
    [nodes, hiddenTypes],
  )
  const nodeMap = useMemo(() => new Map(visibleNodes.map((n) => [n.id, n])), [visibleNodes])

  const graphData = useMemo(() => {
    const visibleIds = new Set(visibleNodes.map((n) => n.id))
    const degreeMap = new Map<string, number>()
    edges.forEach((e) => {
      if (!visibleIds.has(e.source) || !visibleIds.has(e.target)) return
      degreeMap.set(e.source, (degreeMap.get(e.source) ?? 0) + 1)
      degreeMap.set(e.target, (degreeMap.get(e.target) ?? 0) + 1)
    })

    const forceNodes: ForceNode[] = visibleNodes.map((n) => ({
      id: n.id,
      label: n.label || n.name,
      name: n.name,
      type: n.type,
      properties: n.properties,
      degree: degreeMap.get(n.id) ?? 0,
    }))

    const forceLinks: ForceLink[] = edges
      .filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target))
      .map((e) => ({
      source: e.source,
      target: e.target,
      type: e.type,
    }))

    return { nodes: forceNodes, links: forceLinks }
  }, [visibleNodes, edges])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (entry) {
        setDimensions({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        })
      }
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    fitPendingRef.current = true
  }, [graphData])

  const fitGraphToView = useCallback(() => {
    if (!fgRef.current || graphData.nodes.length === 0) return
    fgRef.current.zoomToFit(400, 40)
    requestAnimationFrame(() => {
      const zoom = fgRef.current?.zoom()
      if (zoom !== undefined && zoom < 0.55) {
        fgRef.current?.zoom(0.55, 200)
      }
    })
  }, [graphData.nodes.length])

  const handleEngineStop = useCallback(() => {
    if (!fitPendingRef.current) return
    fitPendingRef.current = false
    fitGraphToView()
  }, [fitGraphToView])

  useEffect(() => {
    if (!highlightedNodeId || !fgRef.current) return

    let attempts = 0
    const tryCenter = () => {
      const node = graphData.nodes.find((n) => n.id === highlightedNodeId)
      if (node?.x != null && node?.y != null) {
        fgRef.current?.centerAt(node.x, node.y, 500)
        fgRef.current?.zoom(2.5, 500)
      } else if (attempts < 20) {
        attempts += 1
        setTimeout(tryCenter, 100)
      }
    }
    tryCenter()
  }, [highlightedNodeId, graphData.nodes])

  const paintNode = useCallback(
    (node: ForceNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const radius = 4 + node.degree
      const isCited = citedSet.has(node.id)
      const isFlashing = flashNodeId === node.id
      const x = node.x ?? 0
      const y = node.y ?? 0

      ctx.beginPath()
      ctx.arc(x, y, radius, 0, 2 * Math.PI)
      ctx.fillStyle = getNodeColor(node.type)
      ctx.fill()

      if (isCited || isFlashing) {
        ctx.strokeStyle = colors.graph.highlight
        ctx.lineWidth = isFlashing ? 3 / globalScale : 2 / globalScale
        ctx.setLineDash([])
        ctx.stroke()
      }

      const fontSize = 11 / globalScale
      const label = truncateLabel(node.label)
      ctx.font = `${fontSize}px sans-serif`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'top'
      const labelY = y + radius + 2 / globalScale
      const textWidth = ctx.measureText(label).width
      const pad = 2 / globalScale
      ctx.fillStyle = 'rgba(255, 255, 255, 0.9)'
      ctx.fillRect(
        x - textWidth / 2 - pad,
        labelY - pad / 2,
        textWidth + pad * 2,
        fontSize + pad,
      )
      ctx.fillStyle = colors.graph.label
      ctx.fillText(label, x, labelY)
    },
    [citedSet, flashNodeId],
  )

  const handleNodeClick = useCallback(
    (node: ForceNode) => {
      const full = nodeMap.get(node.id)
      if (!full) return
      setSelectedNode(full)
      if (node.x != null && node.y != null) {
        const rect = containerRef.current?.getBoundingClientRect()
        if (rect) {
          setPopoverPos({
            x: Math.min(rect.width - 200, Math.max(8, (node.x + rect.width / 2) % rect.width)),
            y: Math.min(rect.height - 160, Math.max(8, (node.y + rect.height / 2) % rect.height)),
          })
        }
      }
    },
    [nodeMap],
  )

  const getConfidence = (node: GraphNode): number | null => {
    const conf = node.properties.confidence
    return typeof conf === 'number' ? conf : null
  }

  const getSourceDoc = (node: GraphNode): string | null => {
    const doc = node.properties.source_doc
    return typeof doc === 'string' ? doc : null
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      <p className="text-xs text-neutral-500 px-4 pt-3 pb-2 shrink-0">
        Граф связей · подсвечены цитируемые
      </p>

      <div ref={containerRef} className="flex-1 relative min-h-0 mx-2 mb-2 rounded-control border border-surface-border bg-surface-card overflow-hidden">
        {visibleNodes.length === 0 ? (
          <div className="absolute inset-0 flex items-center justify-center text-xs text-neutral-400">
            Загрузка графа…
          </div>
        ) : (
          <ForceGraph2D
            ref={fgRef}
            width={dimensions.width}
            height={dimensions.height}
            graphData={graphData}
            nodeCanvasObject={paintNode}
            nodePointerAreaPaint={(node, color, ctx) => {
              const n = node as ForceNode
              const radius = 4 + n.degree
              ctx.beginPath()
              ctx.arc(n.x ?? 0, n.y ?? 0, radius + 4, 0, 2 * Math.PI)
              ctx.fillStyle = color
              ctx.fill()
            }}
            linkColor={(link) =>
              (link as ForceLink).type === 'contradicts'
                ? colors.semantic.contradiction.text
                : colors.graph.edge
            }
            linkLineDash={(link) =>
              (link as ForceLink).type === 'contradicts' ? [3, 2] : null
            }
            linkWidth={1}
            onNodeClick={(node) => handleNodeClick(node as ForceNode)}
            onBackgroundClick={() => setSelectedNode(null)}
            onEngineStop={handleEngineStop}
            backgroundColor={colors.surface.card}
            cooldownTicks={80}
            minZoom={0.35}
            maxZoom={8}
            enableNodeDrag
            enablePanInteraction
            enableZoomInteraction
          />
        )}

        {selectedNode && (
          <div
            className="absolute z-10 w-52 rounded-card border border-surface-border bg-surface-card p-3 shadow-none"
            style={{ left: popoverPos.x, top: popoverPos.y }}
          >
            <p className="text-sm font-medium text-neutral-900 leading-tight mb-2">
              {selectedNode.name}
            </p>
            <span
              className={`inline-block px-1.5 py-0.5 rounded-badge text-[10px] text-white mb-2 ${ENTITY_BG_CLASS[selectedNode.type]}`}
            >
              {ENTITY_LABELS[selectedNode.type]}
            </span>
            {Object.entries(selectedNode.properties)
              .filter(([k]) => !['confidence', 'source_doc'].includes(k))
              .slice(0, 3)
              .map(([k, v]) => (
                <p key={k} className="text-[10px] text-neutral-600">
                  <span className="text-neutral-400">{k}: </span>
                  <span className="font-mono">{String(v)}</span>
                </p>
              ))}
            {getConfidence(selectedNode) != null && (
              <p className="text-[10px] text-neutral-600 mt-1">
                <span className="text-neutral-400">confidence: </span>
                <span className="font-mono">{getConfidence(selectedNode)?.toFixed(2)}</span>
              </p>
            )}
            {getSourceDoc(selectedNode) && (
              <p className="text-[10px] text-neutral-600">
                <span className="text-neutral-400">source: </span>
                <span className="font-mono">{getSourceDoc(selectedNode)}</span>
              </p>
            )}
            <button
              type="button"
              onClick={() => {
                onSendQuery(`Показать связи сущности «${selectedNode.name}»`)
                setSelectedNode(null)
              }}
              className="mt-2 w-full text-[10px] py-1.5 rounded-control border border-surface-border hover:bg-neutral-50"
            >
              Показать связи
            </button>
          </div>
        )}
      </div>

      <div className="px-4 pb-3 flex flex-wrap gap-x-3 gap-y-1 items-center shrink-0">
        {ENTITY_TYPES.map((type) => (
          <div key={type} className="flex items-center gap-1">
            <span className={`w-2 h-2 rounded-full shrink-0 ${ENTITY_BG_CLASS[type]}`} />
            <span className="text-[10px] text-neutral-500">{ENTITY_LABELS[type]}</span>
          </div>
        ))}
        <div className="flex items-center gap-1">
          <svg width="16" height="2" className="shrink-0">
            <line
              x1="0"
              y1="1"
              x2="16"
              y2="1"
              stroke={colors.semantic.contradiction.text}
              strokeWidth="2"
              strokeDasharray="3 2"
            />
          </svg>
          <span className="text-[10px] text-neutral-500">противоречие</span>
        </div>
      </div>
    </div>
  )
}
