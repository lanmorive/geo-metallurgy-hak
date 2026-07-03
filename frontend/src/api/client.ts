/**
 * API types — mirror backend/app/schemas/api.py and ontology.py
 * НЕ МЕНЯТЬ БЕЗ СОГЛАСОВАНИЯ ВСЕЙ КОМАНДЫ (синхронизировать с backend)
 */

export type EntityType =
  | 'Material'
  | 'Process'
  | 'Equipment'
  | 'Property'
  | 'Experiment'
  | 'Publication'
  | 'Chunk'
  | 'Expert'
  | 'Organization'
  | 'Facility'

export type RelationType =
  | 'uses_material'
  | 'operates_at_condition'
  | 'produces_output'
  | 'described_in'
  | 'validated_by'
  | 'contradicts'
  | 'authored_by'
  | 'affiliated_with'
  | 'owns'
  | 'operates'
  | 'conducted_at'
  | 'uses_equipment'
  | 'part_of'
  | 'relates_to'

/** Типы узлов, не отображаемые в графе визуализации */
export const GRAPH_HIDDEN_ENTITY_TYPES: EntityType[] = ['Chunk']

export type NumericOperator = '<=' | '>=' | '=' | 'range'

export interface NumericFilter {
  parameter: string
  operator: NumericOperator
  value?: number | null
  value_min?: number | null
  value_max?: number | null
  unit?: string | null
}

export interface QueryFilters {
  geo?: string | null
  year_range?: [number, number] | null
  min_confidence?: number
  numeric_filters?: NumericFilter[]
}

export interface QueryRequest {
  query: string
  filters?: QueryFilters | null
}

export interface GraphNode {
  id: string
  label: string
  type: EntityType
  name: string
  properties: Record<string, unknown>
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  type: RelationType
  properties: Record<string, unknown>
}

export interface GraphSubset {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface Citation {
  doc_id: string
  title: string
  snippet: string
  confidence: number
  year?: number | null
  geography?: string
}

export interface Contradiction {
  claim_a: string
  claim_b: string
  source_a: string
  source_b: string
  description: string
}

export interface KnowledgeGap {
  entities: string[]
  missing_link: string
  description: string
}

export interface RecommendedExpert {
  name: string
  affiliation?: string | null
  publication_count: number
  top_publications: string[]
}

export interface QueryResponse {
  answer_markdown: string
  citations: Citation[]
  graph_subset: GraphSubset
  contradictions: Contradiction[]
  knowledge_gaps: KnowledgeGap[]
  recommended_experts: RecommendedExpert[]
  mock: boolean
  warning?: string | null
}

export interface SubgraphResponse {
  nodes: GraphNode[]
  edges: GraphEdge[]
  mock: boolean
}

export interface GraphStatsResponse {
  entity_count: number
  mock: boolean
}

export interface HealthResponse {
  status: string
  neo4j: string
}

const API_URL = import.meta.env.VITE_API_URL || ''
const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === '1'

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    throw new Error(`API error ${response.status}: ${response.statusText}`)
  }
  return response.json() as Promise<T>
}

export async function postQuery(
  request: QueryRequest,
  signal?: AbortSignal,
): Promise<QueryResponse> {
  if (USE_MOCKS) {
    await new Promise((resolve) => setTimeout(resolve, 600))
    const mock = await import('../mocks/response.json')
    return mock.default as QueryResponse
  }
  return fetchJson<QueryResponse>(`${API_URL}/api/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  })
}

export async function getSubgraph(
  options?: { nodeIds?: string[]; limit?: number },
): Promise<SubgraphResponse> {
  if (USE_MOCKS) {
    const mock = await import('../mocks/graph.json')
    const data = mock.default as SubgraphResponse & { entity_count?: number }
    const { nodeIds, limit = 150 } = options ?? {}

    let nodes = data.nodes
    let edges = data.edges

    if (nodeIds?.length) {
      const idSet = new Set(nodeIds)
      nodes = nodes.filter((n) => idSet.has(n.id))
      const nodeIdSet = new Set(nodes.map((n) => n.id))
      edges = edges.filter((e) => nodeIdSet.has(e.source) && nodeIdSet.has(e.target))
    } else if (limit > 0 && nodes.length > limit) {
      nodes = nodes.slice(0, limit)
      const nodeIdSet = new Set(nodes.map((n) => n.id))
      edges = edges.filter((e) => nodeIdSet.has(e.source) && nodeIdSet.has(e.target))
    }

    return { nodes, edges, mock: true }
  }

  const params = new URLSearchParams()
  if (options?.limit) params.set('limit', String(options.limit))
  options?.nodeIds?.forEach((id) => params.append('node_ids', id))
  const qs = params.toString() ? `?${params.toString()}` : ''
  return fetchJson<SubgraphResponse>(`${API_URL}/api/graph/subgraph${qs}`)
}

export async function getGraphStats(): Promise<GraphStatsResponse> {
  if (USE_MOCKS) {
    const mock = await import('../mocks/graph.json')
    const data = mock.default as { entity_count: number }
    return { entity_count: data.entity_count, mock: true }
  }
  return fetchJson<GraphStatsResponse>(`${API_URL}/api/graph/stats`)
}

export async function checkHealth(): Promise<HealthResponse> {
  if (USE_MOCKS) {
    return { status: 'ok', neo4j: 'unavailable' }
  }
  return fetchJson<HealthResponse>(`${API_URL}/api/health`)
}
