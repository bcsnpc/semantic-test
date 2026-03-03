"""Exposure analysis from diff + dependency graph."""

from __future__ import annotations

from dataclasses import dataclass

from semantic_test.core.diff.differ import DiffResult
from semantic_test.core.graph.builder import Graph
from semantic_test.core.graph.queries import downstream, downstream_by_type


@dataclass(frozen=True, slots=True)
class ExposureTopObject:
    object_id: str
    type: str
    name: str


@dataclass(frozen=True, slots=True)
class ExposureEntry:
    changed_object_id: str
    downstream_ids: set[str]
    downstream_by_type_counts: dict[str, int]
    top_downstream_objects: list[ExposureTopObject]


@dataclass(frozen=True, slots=True)
class ExposureResult:
    items: list[ExposureEntry]


def analyze_exposure(
    diff_result: DiffResult,
    graph: Graph,
    top_n: int = 10,
) -> ExposureResult:
    """Enumerate downstream exposure for each changed object."""
    node_types = {node_id: node.type for node_id, node in graph.nodes.items()}
    entries: list[ExposureEntry] = []

    for changed_id in diff_result.changed_object_ids:
        impacted = downstream(changed_id, graph.reverse)
        by_type = downstream_by_type(changed_id, graph.reverse, node_types)
        top_objects = _top_downstream(impacted, graph, top_n)
        entries.append(
            ExposureEntry(
                changed_object_id=changed_id,
                downstream_ids=impacted,
                downstream_by_type_counts=by_type,
                top_downstream_objects=top_objects,
            )
        )

    entries.sort(key=lambda item: item.changed_object_id)
    return ExposureResult(items=entries)


def _top_downstream(impacted: set[str], graph: Graph, top_n: int) -> list[ExposureTopObject]:
    candidates: list[ExposureTopObject] = []
    for object_id in impacted:
        node = graph.nodes.get(object_id)
        if node is None:
            continue
        name = str(node.metadata.get("name", object_id))
        candidates.append(ExposureTopObject(object_id=object_id, type=node.type, name=name))
    candidates.sort(key=lambda item: (item.type, item.name, item.object_id))
    return candidates[: max(top_n, 0)]
