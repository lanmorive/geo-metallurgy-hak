"""Neo4j record → GraphNode/GraphEdge conversion (shared by api and retrieval)."""

from __future__ import annotations

import logging
from typing import Any

from app.schemas.api import GraphSubset
from app.schemas.ontology import EntityType, GraphEdge, GraphNode, RelationType

logger = logging.getLogger(__name__)

ENTITY_LABELS = [
    "Material",
    "Process",
    "Equipment",
    "Property",
    "Experiment",
    "Expert",
    "Organization",
    "Facility",
]

ALL_NODE_LABELS = [*ENTITY_LABELS, "Publication", "Chunk"]

_NODE_ID_KEYS = {
    "Publication": "doc_id",
    "Chunk": "chunk_id",
}


def first_known_label(labels: list[str]) -> str:
    for label in labels:
        if label in ALL_NODE_LABELS:
            return label
    return labels[0] if labels else "Property"


def node_id(label: str, props: dict[str, Any], element_id: str | None = None) -> str:
    key = _NODE_ID_KEYS.get(label)
    if key and props.get(key):
        return str(props[key])
    if props.get("id"):
        return str(props["id"])
    if props.get("name_norm"):
        return str(props["name_norm"])
    if props.get("name"):
        return str(props["name"])
    return f"{label}:{element_id or 'unknown'}"


def node_name(label: str, props: dict[str, Any], nid: str) -> str:
    if label == "Publication":
        return str(props.get("title") or props.get("name") or nid)
    if label == "Chunk":
        text = str(props.get("text") or nid)
        return text[:80]
    return str(props.get("name") or props.get("title") or nid)


def to_graph_node(node: Any) -> GraphNode:
    labels = list(node.labels)
    label = first_known_label(labels)
    props = dict(node)
    nid = node_id(label, props, str(node.element_id))
    try:
        entity_type = EntityType(label)
    except ValueError:
        entity_type = EntityType.PROPERTY
    return GraphNode(
        id=nid,
        label=label,
        type=entity_type,
        name=node_name(label, props, nid),
        properties={k: v for k, v in props.items() if k != "embedding"},
    )


def to_graph_edge(rel: Any) -> GraphEdge | None:
    source = to_graph_node(rel.start_node).id
    target = to_graph_node(rel.end_node).id
    rel_type = rel.type
    try:
        typed_rel = RelationType(rel_type)
    except ValueError:
        logger.debug("Skipping unsupported relation type %s", rel_type)
        return None
    return GraphEdge(
        id=str(rel.element_id),
        source=source,
        target=target,
        type=typed_rel,
        properties=dict(rel),
    )


def records_to_subset(nodes: list[Any], rels: list[Any]) -> GraphSubset:
    graph_nodes: dict[str, GraphNode] = {}
    for node in nodes:
        if node is None:
            continue
        graph_node = to_graph_node(node)
        graph_nodes[graph_node.id] = graph_node

    graph_edges: dict[str, GraphEdge] = {}
    for rel in rels:
        if rel is None:
            continue
        edge = to_graph_edge(rel)
        if edge and edge.source in graph_nodes and edge.target in graph_nodes:
            graph_edges[edge.id] = edge

    return GraphSubset(nodes=list(graph_nodes.values()), edges=list(graph_edges.values()))


def build_publication_star(chunks: list[dict[str, Any]]) -> GraphSubset:
    """Build a small deterministic graph from vector results."""
    center = GraphNode(
        id="query",
        label="Query",
        type=EntityType.PROPERTY,
        name="Запрос",
        properties={},
    )
    nodes: dict[str, GraphNode] = {center.id: center}
    edges: list[GraphEdge] = []

    for row in chunks:
        doc_id = str(row.get("doc_id") or "")
        if not doc_id or doc_id in nodes:
            continue
        title = str(row.get("title") or doc_id)
        nodes[doc_id] = GraphNode(
            id=doc_id,
            label="Publication",
            type=EntityType.PUBLICATION,
            name=title,
            properties={
                "year": row.get("year"),
                "venue": row.get("venue"),
                "doc_type": row.get("doc_type"),
                "score": row.get("score"),
            },
        )
        edges.append(
            GraphEdge(
                id=f"query:{doc_id}",
                source="query",
                target=doc_id,
                type=RelationType.RELATES_TO,
                properties={"score": row.get("score")},
            )
        )

    return GraphSubset(nodes=list(nodes.values()), edges=edges)


def truncate_subset(subset: GraphSubset, max_nodes: int = 60) -> GraphSubset:
    """Оставить до max_nodes узлов и инцидентные рёбра."""
    if len(subset.nodes) <= max_nodes:
        return subset
    kept = subset.nodes[:max_nodes]
    node_ids = {n.id for n in kept}
    edges = [
        e for e in subset.edges if e.source in node_ids and e.target in node_ids
    ]
    return GraphSubset(nodes=kept, edges=edges)


def merge_subsets(*subsets: GraphSubset, max_nodes: int = 60) -> GraphSubset:
    """Объединить подграфы с дедупликацией и лимитом узлов."""
    nodes: dict[str, GraphNode] = {}
    edges: dict[str, GraphEdge] = {}
    for subset in subsets:
        for node in subset.nodes:
            nodes.setdefault(node.id, node)
        for edge in subset.edges:
            edges.setdefault(edge.id, edge)
    merged = GraphSubset(nodes=list(nodes.values()), edges=list(edges.values()))
    return truncate_subset(merged, max_nodes=max_nodes)
