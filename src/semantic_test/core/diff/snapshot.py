"""Stable snapshot builder used for model diffs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from semantic_test import __version__
from semantic_test.core.graph.builder import Graph
from semantic_test.core.model.coverage import coverage_report

_EXPRESSION_KEYS = {"expression", "raw_expression"}
_DROP_KEYS = {"object_ref"}


@dataclass(frozen=True, slots=True)
class SnapshotObject:
    """Single object record inside a snapshot."""

    id: str
    metadata: dict[str, Any]
    object_hash: str


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Deterministic snapshot of model objects and dependency edges."""

    tool_version: str
    model_key: str
    definition_path: str
    objects: dict[str, SnapshotObject]
    edges: list[tuple[str, str, str]]
    coverage: dict[str, Any]
    unknown_patterns: list[dict[str, Any]]
    unresolved_refs: list[dict[str, Any]]
    snapshot_hash: str

    @property
    def node_count(self) -> int:
        return len(self.objects)

    @property
    def edge_count(self) -> int:
        return len(self.edges)


def load_snapshot(path: str | Path) -> Snapshot:
    """Load snapshot from JSON file path."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    objects: dict[str, SnapshotObject] = {}
    for object_id, obj in payload.get("objects", {}).items():
        objects[object_id] = SnapshotObject(
            id=str(obj.get("id", object_id)),
            metadata=dict(obj.get("metadata", {})),
            object_hash=str(obj.get("object_hash", "")),
        )
    edges = [tuple(edge) for edge in payload.get("edges", [])]
    return Snapshot(
        tool_version=str(payload.get("tool_version", "")),
        model_key=str(payload.get("model_key", "semanticmodel::unknown")),
        definition_path=str(payload.get("definition_path", "unknown")),
        objects=objects,
        edges=edges,
        coverage=dict(payload.get("coverage", {})),
        unknown_patterns=list(payload.get("unknown_patterns", [])),
        unresolved_refs=list(payload.get("unresolved_refs", [])),
        snapshot_hash=str(payload.get("snapshot_hash", "")),
    )


def build_snapshot(
    objects: dict[str, dict[str, Any]],
    graph: Graph,
    *,
    model_key: str = "semanticmodel::unknown",
    definition_path: str = "unknown",
    coverage_data: dict[str, Any] | None = None,
    unknown_patterns: list[dict[str, Any]] | None = None,
) -> Snapshot:
    """Build a deterministic snapshot for diff/exposure.

    Normalization rules:
    - stable sort for object IDs, metadata keys, sets, and edge rows
    - normalize line endings to ``\\n``
    - normalize DAX whitespace lightly (trim, collapse repeated spaces, trim line tails)
    - ignore source file ordering differences by sorting canonical IDs and edges
    """
    snapshot_objects: dict[str, SnapshotObject] = {}

    for object_id in sorted(objects.keys()):
        normalized_metadata = _normalize_mapping(objects[object_id])
        object_hash = _hash_json({"id": object_id, "metadata": normalized_metadata})
        snapshot_objects[object_id] = SnapshotObject(
            id=object_id,
            metadata=normalized_metadata,
            object_hash=object_hash,
        )

    edges = sorted((edge.source, edge.target, "depends_on") for edge in graph.edges)
    selected_coverage = coverage_data or coverage_report()[1]
    selected_unknown = _normalize_unknown_patterns(unknown_patterns or [])
    unresolved_refs = _extract_unresolved_refs(selected_unknown)

    snapshot_payload = {
        "tool_version": __version__,
        "model_key": model_key,
        "definition_path": definition_path,
        "objects": [
            {
                "id": object_id,
                "hash": snapshot_objects[object_id].object_hash,
            }
            for object_id in sorted(snapshot_objects.keys())
        ],
        "edges": edges,
        "coverage": _normalize_value(selected_coverage),
        "unknown_patterns": selected_unknown,
        "unresolved_refs": unresolved_refs,
    }
    snapshot_hash = _hash_json(snapshot_payload)
    return Snapshot(
        tool_version=__version__,
        model_key=model_key,
        definition_path=definition_path,
        objects=snapshot_objects,
        edges=edges,
        coverage=_normalize_value(selected_coverage),
        unknown_patterns=selected_unknown,
        unresolved_refs=unresolved_refs,
        snapshot_hash=snapshot_hash,
    )


def _normalize_mapping(metadata: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in sorted(metadata.keys()):
        if key in _DROP_KEYS:
            continue
        value = metadata[key]
        if key in _EXPRESSION_KEYS and isinstance(value, str):
            result[key] = _normalize_expression(value)
            continue
        result[key] = _normalize_value(value)
    return result


def _normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _normalize_value(value[k]) for k in sorted(value.keys())}
    if isinstance(value, set):
        normalized_items = [_normalize_value(item) for item in value]
        return sorted(normalized_items, key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, tuple):
        return tuple(_normalize_value(item) for item in value)
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    return value


def _normalize_expression(expression: str) -> str:
    content = expression.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not content:
        return ""
    lines = [_normalize_dax_line(line) for line in content.split("\n")]
    normalized = "\n".join(lines)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized


def _normalize_dax_line(line: str) -> str:
    stripped_tail = line.rstrip()
    collapsed = re.sub(r"[ \t]{2,}", " ", stripped_tail)
    return collapsed.strip()


def _hash_json(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _normalize_unknown_patterns(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        object_id = str(entry.get("object_id", ""))
        patterns_raw = entry.get("patterns", [])
        if not object_id or not isinstance(patterns_raw, list):
            continue
        patterns = sorted({str(pattern) for pattern in patterns_raw if str(pattern).strip()})
        if not patterns:
            continue
        normalized.append({"object_id": object_id, "patterns": patterns})
    normalized.sort(key=lambda item: str(item["object_id"]))
    return normalized


def _extract_unresolved_refs(
    unknown_patterns: list[dict[str, Any]],
) -> list[dict[str, str]]:
    unresolved: list[dict[str, str]] = []
    for entry in unknown_patterns:
        object_id = str(entry.get("object_id", ""))
        for pattern in entry.get("patterns", []):
            pattern_text = str(pattern)
            if pattern_text.startswith("unresolved_measure:"):
                unresolved.append({"object_id": object_id, "ref": pattern_text})
    unresolved.sort(key=lambda item: (item["object_id"], item["ref"]))
    return unresolved
