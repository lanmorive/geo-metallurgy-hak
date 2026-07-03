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
  | 'Expert'
  | 'Facility'

export type RelationType =
  | 'uses_material'
  | 'operates_at_condition'
  | 'produces_output'
  | 'described_in'
  | 'validated_by'
  | 'contradicts'
  | 'authored_by'
  | 'conducted_at'
  | 'uses_equipment'
  | 'relates_to'

export type NumericOperator = '<=' | '>=' | '=' | 'range'

export interface NumericFilter {
  parameter: string
  operator: NumericOperator
  value: number
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

export async function postQuery(request: QueryRequest): Promise<QueryResponse> {
  if (USE_MOCKS) {
    const mock = await import('../mocks/response.json')
    return mock.default as QueryResponse
  }
  return fetchJson<QueryResponse>(`${API_URL}/api/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
}

export async function getSubgraph(nodeIds?: string[]): Promise<SubgraphResponse> {
  if (USE_MOCKS) {
    const mock = await import('../mocks/response.json')
    const data = mock.default as QueryResponse
    if (!nodeIds?.length) {
      return { nodes: data.graph_subset.nodes, edges: data.graph_subset.edges, mock: true }
    }
    const idSet = new Set(nodeIds)
    const nodes = data.graph_subset.nodes.filter((n) => idSet.has(n.id))
    const nodeIdSet = new Set(nodes.map((n) => n.id))
    const edges = data.graph_subset.edges.filter(
      (e) => nodeIdSet.has(e.source) && nodeIdSet.has(e.target),
    )
    return { nodes, edges, mock: true }
  }
  const params = nodeIds?.length ? `?${nodeIds.map((id) => `node_ids=${encodeURIComponent(id)}`).join('&')}` : ''
  return fetchJson<SubgraphResponse>(`${API_URL}/api/graph/subgraph${params}`)
}

export async function checkHealth(): Promise<HealthResponse> {
  if (USE_MOCKS) {
    return { status: 'ok', neo4j: 'unavailable' }
  }
  return fetchJson<HealthResponse>(`${API_URL}/api/health`)
}
