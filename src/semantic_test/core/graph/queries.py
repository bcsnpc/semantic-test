"""Graph traversal helpers."""

from __future__ import annotations

from semantic_test.core.graph.builder import Graph


def downstream(node_id: str, reverse_adj: dict[str, set[str]]) -> set[str]:
    """Return transitive downstream dependents for ``node_id``."""
    return _walk(reverse_adj, node_id)


def downstream_by_type(
    node_id: str,
    reverse_adj: dict[str, set[str]],
    node_types: dict[str, str],
) -> dict[str, int]:
    """Return downstream dependent counts grouped by object type."""
    counts: dict[str, int] = {}
    for dependent_id in downstream(node_id, reverse_adj):
        object_type = node_types.get(dependent_id, "Unknown")
        counts[object_type] = counts.get(object_type, 0) + 1
    return counts


def traverse_upstream(graph: Graph, start_node_id: str) -> set[str]:
    """Return transitive dependencies of ``start_node_id``."""
    return _walk(graph.forward, start_node_id)


def traverse_downstream(graph: Graph, start_node_id: str) -> set[str]:
    """Return transitive dependents impacted by ``start_node_id``."""
    return downstream(start_node_id, graph.reverse)


def _walk(adjacency: dict[str, set[str]], start: str) -> set[str]:
    visited: set[str] = set()
    stack = list(adjacency.get(start, set()))
    while stack:
        node = stack.pop()
        if node in visited:
            continue
        visited.add(node)
        stack.extend(adjacency.get(node, set()) - visited)
    return visited
