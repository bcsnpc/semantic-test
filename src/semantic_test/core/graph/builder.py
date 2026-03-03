"""Build dependency graphs from extracted semantic objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from semantic_test.core.graph.edges import GraphEdge
from semantic_test.core.graph.nodes import GraphNode
from semantic_test.core.model.objects import ObjectRef, ObjectType


@dataclass(frozen=True, slots=True)
class Graph:
    """Directed dependency graph with forward and reverse adjacency."""

    nodes: dict[str, GraphNode]
    edges: set[GraphEdge]
    forward: dict[str, set[str]]
    reverse: dict[str, set[str]]

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def stats(self) -> dict[str, int]:
        return {"node_count": self.node_count, "edge_count": self.edge_count}


def build_dependency_graph(objects: dict[str, dict[str, Any]]) -> Graph:
    """Build graph where edge ``A -> B`` means object A depends on object B."""
    nodes: dict[str, GraphNode] = {}
    edges: set[GraphEdge] = set()
    forward: dict[str, set[str]] = {}
    reverse: dict[str, set[str]] = {}

    for object_id, metadata in objects.items():
        node = GraphNode(
            id=object_id,
            type=str(metadata.get("type", "Unknown")),
            metadata=metadata,
        )
        nodes[object_id] = node
        forward.setdefault(object_id, set())
        reverse.setdefault(object_id, set())

    for source_id, metadata in objects.items():
        deps = metadata.get("dependencies", set())
        if not isinstance(deps, (set, list, tuple)):
            continue
        for target_id in deps:
            target = str(target_id)
            if target not in nodes:
                continue
            edge = GraphEdge(source=source_id, target=target)
            edges.add(edge)
            forward[source_id].add(target)
            reverse[target].add(source_id)
        _add_relationship_column_edges(
            source_id=source_id,
            metadata=metadata,
            nodes=nodes,
            edges=edges,
            forward=forward,
            reverse=reverse,
        )

    return Graph(nodes=nodes, edges=edges, forward=forward, reverse=reverse)


def _add_relationship_column_edges(
    *,
    source_id: str,
    metadata: dict[str, Any],
    nodes: dict[str, GraphNode],
    edges: set[GraphEdge],
    forward: dict[str, set[str]],
    reverse: dict[str, set[str]],
) -> None:
    if str(metadata.get("type", "")) != ObjectType.RELATIONSHIP.value:
        return
    if not bool(metadata.get("is_complete", False)):
        return
    from_table = str(metadata.get("from_table", "")).strip()
    from_column = str(metadata.get("from_column", "")).strip()
    to_table = str(metadata.get("to_table", "")).strip()
    to_column = str(metadata.get("to_column", "")).strip()
    if not all([from_table, from_column, to_table, to_column]):
        return
    from_id = ObjectRef(
        type=ObjectType.COLUMN,
        table=from_table,
        name=from_column,
    ).canonical_id()
    to_id = ObjectRef(
        type=ObjectType.COLUMN,
        table=to_table,
        name=to_column,
    ).canonical_id()
    if from_id not in nodes or to_id not in nodes:
        return
    for left, right in ((from_id, to_id), (to_id, from_id)):
        edge = GraphEdge(source=left, target=right)
        edges.add(edge)
        forward[left].add(right)
        reverse[right].add(left)
