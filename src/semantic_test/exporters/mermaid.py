"""Mermaid graph exporter for trace results."""

from __future__ import annotations

import re
from typing import Any


def export_trace_to_mermaid(trace_result: dict[str, Any], *, mode: str = "full") -> str:
    """Render a trace payload as Mermaid graph text."""
    object_id = str(trace_result.get("object_id", "")).strip()
    if not object_id:
        return "graph LR\n"
    if mode not in {"full", "simple"}:
        mode = "full"

    upstream_nodes = _as_str_list(trace_result.get("upstream", []))
    downstream_nodes = _as_str_list(trace_result.get("downstream", []))

    # Preferred path: preserve true dependency flow from trace-induced real edges.
    # Internal graph edges are stored dependent -> dependency. Reverse for display.
    edges = {(target, source) for source, target in _real_trace_edges(trace_result.get("trace_scope_edges", []))}
    # Backward-compatible fallback for payloads without explicit real edges.
    if not edges:
        upstream_visuals = _visual_ids(trace_result.get("upstream_visual_dependencies", []))
        downstream_visuals = _visual_ids(trace_result.get("downstream_visual_dependencies", []))
        for node in upstream_nodes:
            edges.add((node, object_id))
        for node in downstream_nodes:
            if node.startswith("Visual:"):
                continue
            edges.add((object_id, node))
        for visual_id in upstream_visuals:
            edges.add((visual_id, object_id))
        for visual_id in downstream_visuals:
            edges.add((object_id, visual_id))

    if mode == "simple":
        edges = _simplify_edges(edges=edges, object_id=object_id)

    known_nodes = {object_id}
    for source, target in edges:
        known_nodes.add(source)
        known_nodes.add(target)

    node_ids = _build_node_id_map(sorted(known_nodes))
    lines = ["graph LR"]
    for object_ref in sorted(known_nodes):
        node_id = node_ids[object_ref]
        label = _escape_label(object_ref)
        lines.append(f'    {node_id}["{label}"]')
    for source, target in sorted(edges):
        lines.append(f"    {node_ids[source]} --> {node_ids[target]}")
    return "\n".join(lines) + "\n"


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _visual_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        text = str(item.get("object_id", "")).strip()
        if text:
            out.append(text)
    return out


def _real_trace_edges(value: Any) -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    if not isinstance(value, list):
        return edges
    for item in value:
        source = ""
        target = ""
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            source = str(item[0]).strip()
            target = str(item[1]).strip()
        elif isinstance(item, dict):
            source = str(item.get("source", "")).strip()
            target = str(item.get("target", "")).strip()
        if source and target:
            edges.add((source, target))
    return edges


def _simplify_edges(*, edges: set[tuple[str, str]], object_id: str) -> set[tuple[str, str]]:
    measure_nodes = {object_id} if object_id.startswith("Measure:") else set()
    visual_nodes: set[str] = set()
    business_columns: set[str] = set()
    for source, target in edges:
        for node in (source, target):
            if node.startswith("Measure:"):
                measure_nodes.add(node)
            elif node.startswith("Visual:"):
                visual_nodes.add(node)

    for source, target in edges:
        if source.startswith("Column:") and target in measure_nodes and not _is_technical_column(source):
            business_columns.add(source)

    keep_nodes = measure_nodes | visual_nodes | business_columns | {object_id}
    simplified: set[tuple[str, str]] = set()
    for source, target in edges:
        if source not in keep_nodes or target not in keep_nodes:
            continue
        # Suppress noisy column-to-column scaffolding in simplified mode.
        if source.startswith("Column:") and target.startswith("Column:"):
            continue
        simplified.add((source, target))
    return simplified


def _is_technical_column(object_id: str) -> bool:
    if not object_id.startswith("Column:"):
        return False
    body = object_id.split(":", maxsplit=1)[1]
    table = body.split(".", maxsplit=1)[0] if "." in body else body
    column = body.split(".", maxsplit=1)[1] if "." in body else ""
    table_lower = table.lower()
    column_lower = column.lower()
    if table_lower.startswith("localdatetable_"):
        return True
    if table_lower.startswith("datetabletemplate_"):
        return True
    if column_lower.startswith("rownumber") or "rownumber-" in column_lower:
        return True
    if column_lower.startswith("__"):
        return True
    return False


def _build_node_id_map(object_ids: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    used: set[str] = set()
    for object_id in object_ids:
        base = _sanitize_node_id(object_id)
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        used.add(candidate)
        out[object_id] = candidate
    return out


def _sanitize_node_id(object_id: str) -> str:
    no_spaces = re.sub(r"\s+", "", object_id)
    cleaned = re.sub(r"[^0-9A-Za-z]+", "_", no_spaces).strip("_")
    if not cleaned:
        cleaned = "Node"
    if cleaned[0].isdigit():
        cleaned = f"N_{cleaned}"
    return cleaned


def _escape_label(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')
