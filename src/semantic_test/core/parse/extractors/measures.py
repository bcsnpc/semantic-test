"""Measure inventory and dependency extraction (v1)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re
from typing import Any

from semantic_test.core.model.objects import ObjectRef, ObjectType
from semantic_test.core.parse.tmdl_parser import ParsedModel

_QUOTED_COLUMN_REF_RE = re.compile(r"'([^']+)'\[([^\]]+)\]")
_UNQUOTED_COLUMN_REF_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\[([^\]]+)\]")
_MEASURE_REF_RE = re.compile(r"(?<![A-Za-z0-9_'])\[([^\[\]]+)\]")
_SELECTED_MEASURE_RE = re.compile(r"\bSELECTEDMEASURE\s*\(", re.IGNORECASE)
_SELECTED_MEASURE_NAME_RE = re.compile(r"\bSELECTEDMEASUREName\s*\(", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ExpressionAnalysis:
    dependencies: set[str]
    unknown_patterns: list[str]
    unresolved_references: list[dict[str, str]]
    resolution_assumptions: list[str]
    ambiguous_reference_count: int


def extract_measures(parsed: ParsedModel) -> dict[str, dict[str, Any]]:
    """Build measure inventory as ``{object_id: metadata}``."""
    inventory: dict[str, dict[str, Any]] = {}
    registry = build_reference_registry(parsed)

    for measure in parsed.measures:
        ref = ObjectRef(type=ObjectType.MEASURE, table=measure.table, name=measure.name)
        measure_id = ref.canonical_id()
        expression = measure.expression or ""
        analysis = extract_expression_analysis(
            expression=expression,
            current_measure_id=measure_id,
            current_table=measure.table,
            current_object_id=measure_id,
            current_object_name=measure.name,
            expression_context="measure",
            reference_registry=registry,
        )
        inventory[measure_id] = {
            "id": measure_id,
            "type": ObjectType.MEASURE.value,
            "name": measure.name,
            "table": measure.table,
            "raw_expression": expression,
            "dependencies": analysis.dependencies,
            "unknown_patterns": analysis.unknown_patterns,
            "unresolved_references": analysis.unresolved_references,
            "resolution_assumptions": analysis.resolution_assumptions,
            "ambiguous_reference_count": analysis.ambiguous_reference_count,
            "source_file": measure.source_file,
            "object_ref": ref,
        }
    return inventory


def build_measure_name_index(parsed: ParsedModel) -> dict[str, set[str]]:
    """Build ``measure name -> canonical measure IDs`` map."""
    name_to_ids: dict[str, set[str]] = defaultdict(set)
    for measure in parsed.measures:
        ref = ObjectRef(type=ObjectType.MEASURE, table=measure.table, name=measure.name)
        name_to_ids[measure.name].add(ref.canonical_id())
    return name_to_ids


def build_reference_registry(parsed: ParsedModel) -> dict[str, Any]:
    """Build global reference registry used for expression resolution."""
    measure_name_to_ids: dict[str, set[str]] = defaultdict(set)
    measure_key_to_id: dict[tuple[str, str], str] = {}
    tables_by_lower: dict[str, str] = {}
    columns_by_table_lower: dict[tuple[str, str], str] = {}
    columns_by_name_lower: dict[str, set[str]] = defaultdict(set)

    for table in parsed.tables:
        table_name = table.name.strip()
        if not table_name:
            continue
        tables_by_lower.setdefault(table_name.lower(), table_name)

    for column in parsed.columns:
        if not column.table:
            continue
        table_name = column.table.strip()
        column_name = column.name.strip()
        if not table_name or not column_name:
            continue
        canonical_id = ObjectRef(
            type=ObjectType.COLUMN,
            table=table_name,
            name=column_name,
        ).canonical_id()
        columns_by_table_lower[(table_name.lower(), column_name.lower())] = canonical_id
        columns_by_name_lower[column_name.lower()].add(canonical_id)

    for measure in parsed.measures:
        measure_name = measure.name.strip()
        table_name = (measure.table or "").strip()
        if not measure_name:
            continue
        ref = ObjectRef(type=ObjectType.MEASURE, table=table_name or None, name=measure_name)
        canonical_id = ref.canonical_id()
        measure_name_to_ids[measure_name].add(canonical_id)
        measure_key_to_id[(table_name.lower(), measure_name.lower())] = canonical_id

    return {
        "tables_by_lower": tables_by_lower,
        "columns_by_table_lower": columns_by_table_lower,
        "columns_by_name_lower": dict(columns_by_name_lower),
        "measure_name_to_ids": dict(measure_name_to_ids),
        "measure_key_to_id": measure_key_to_id,
    }


def extract_expression_dependencies(
    *,
    expression: str,
    current_measure_id: str | None = None,
    current_table: str | None,
    reference_registry: dict[str, Any] | None = None,
    measure_name_to_ids: dict[str, set[str]] | None = None,
) -> tuple[set[str], list[str]]:
    """Extract dependencies from an expression using v1 precision-first rules."""
    analysis = extract_expression_analysis(
        expression=expression,
        current_measure_id=current_measure_id,
        current_table=current_table,
        reference_registry=reference_registry,
        measure_name_to_ids=measure_name_to_ids,
        expression_context="measure",
    )
    return analysis.dependencies, analysis.unknown_patterns


def extract_expression_analysis(
    *,
    expression: str,
    current_measure_id: str | None = None,
    current_table: str | None,
    current_object_id: str | None = None,
    current_object_name: str | None = None,
    expression_context: str = "measure",
    reference_registry: dict[str, Any] | None = None,
    measure_name_to_ids: dict[str, set[str]] | None = None,
) -> ExpressionAnalysis:
    """Extract dependencies and detailed diagnostics from a DAX expression."""
    registry = reference_registry or _registry_from_name_index(measure_name_to_ids or {})
    tables_by_lower = registry["tables_by_lower"]
    columns_by_table_lower = registry["columns_by_table_lower"]
    columns_by_name_lower = registry.get("columns_by_name_lower", {})
    measure_key_to_id = registry["measure_key_to_id"]
    name_to_ids = registry["measure_name_to_ids"]

    dependencies: set[str] = set()
    unknown_patterns: list[str] = []
    unresolved_references: list[dict[str, str]] = []
    resolution_assumptions: list[str] = []
    ambiguous_reference_count = 0

    if _SELECTED_MEASURE_RE.search(expression):
        unknown_patterns.append("unsupported_pattern:SELECTEDMEASURE()")
    if _SELECTED_MEASURE_NAME_RE.search(expression):
        unknown_patterns.append("unsupported_pattern:SELECTEDMEASURENAME()")

    for table_name, column_name in _QUOTED_COLUMN_REF_RE.findall(expression):
        _resolve_qualified_reference(
            table_name=table_name,
            object_name=column_name,
            dependencies=dependencies,
            unknown_patterns=unknown_patterns,
            tables_by_lower=tables_by_lower,
            columns_by_table_lower=columns_by_table_lower,
            measure_key_to_id=measure_key_to_id,
        )

    for table_name, column_name in _UNQUOTED_COLUMN_REF_RE.findall(expression):
        _resolve_qualified_reference(
            table_name=table_name,
            object_name=column_name,
            dependencies=dependencies,
            unknown_patterns=unknown_patterns,
            tables_by_lower=tables_by_lower,
            columns_by_table_lower=columns_by_table_lower,
            measure_key_to_id=measure_key_to_id,
        )

    for measure_name in _MEASURE_REF_RE.findall(expression):
        candidate = measure_name.strip()
        if expression_context == "calculated_column":
            (
                column_id,
                reason,
                assumption_message,
                is_ambiguous,
            ) = _resolve_unqualified_column_reference(
                column_name=candidate,
                current_table=current_table,
                columns_by_table_lower=columns_by_table_lower,
                columns_by_name_lower=columns_by_name_lower,
                current_object_id=current_object_id,
                current_object_name=current_object_name,
            )
            if column_id is not None:
                dependencies.add(column_id)
                if assumption_message:
                    resolution_assumptions.append(assumption_message)
                continue
            if is_ambiguous:
                ambiguous_reference_count += 1
                unknown_patterns.append(f"ambiguous_column:[{candidate}]")
            else:
                unknown_patterns.append(f"unresolved_column:[{candidate}]")
            unresolved_references.append(
                {
                    "ref": f"[{candidate}]",
                    "reason": reason,
                    "severity": "ERROR",
                }
            )
            continue

        resolved, reason_code = _resolve_measure_reference(
            measure_name=candidate,
            current_table=current_table,
            measure_name_to_ids=name_to_ids,
            measure_key_to_id=measure_key_to_id,
        )
        if resolved is None:
            unknown_patterns.append(f"unresolved_measure:[{candidate}]")
            unresolved_references.append(
                {
                    "ref": f"[{candidate}]",
                    "reason": _measure_resolution_reason(reason_code),
                    "severity": "ERROR",
                }
            )
            if reason_code == "ambiguous_measure":
                ambiguous_reference_count += 1
            continue
        dependencies.add(resolved)

    if current_measure_id is not None:
        dependencies.discard(current_measure_id)
    return ExpressionAnalysis(
        dependencies=dependencies,
        unknown_patterns=unknown_patterns,
        unresolved_references=unresolved_references,
        resolution_assumptions=resolution_assumptions,
        ambiguous_reference_count=ambiguous_reference_count,
    )


def _resolve_measure_reference(
    *,
    measure_name: str,
    current_table: str | None,
    measure_name_to_ids: dict[str, set[str]],
    measure_key_to_id: dict[tuple[str, str], str],
) -> tuple[str | None, str]:
    candidates = measure_name_to_ids.get(measure_name)
    if candidates is None:
        lowered = measure_name.lower()
        case_insensitive = [
            ids
            for key, ids in measure_name_to_ids.items()
            if key.lower() == lowered
        ]
        merged: set[str] = set()
        for ids in case_insensitive:
            merged.update(ids)
        candidates = merged if merged else None
    if not candidates:
        return None, "missing_measure"
    if len(candidates) == 1:
        return next(iter(candidates)), "resolved"

    if current_table:
        local_id = measure_key_to_id.get((current_table.strip().lower(), measure_name.lower()))
        if local_id is None:
            local_id = ObjectRef(
                type=ObjectType.MEASURE, table=current_table, name=measure_name
            ).canonical_id()
        if local_id in candidates:
            return local_id, "resolved_local_scope"
    return None, "ambiguous_measure"


def _resolve_unqualified_column_reference(
    *,
    column_name: str,
    current_table: str | None,
    columns_by_table_lower: dict[tuple[str, str], str],
    columns_by_name_lower: dict[str, set[str]],
    current_object_id: str | None,
    current_object_name: str | None,
) -> tuple[str | None, str, str | None, bool]:
    if current_table:
        local_id = columns_by_table_lower.get((current_table.strip().lower(), column_name.lower()))
        if local_id is not None:
            object_label = current_object_name or current_object_id or "unknown"
            message = (
                f"Resolved [{column_name}] => {current_table}[{column_name}] "
                f"(implicit current-table scope, object={object_label})"
            )
            return local_id, "Resolved by implicit current-table scope.", message, False

    global_candidates = columns_by_name_lower.get(column_name.lower(), set())
    if len(global_candidates) == 1:
        only_id = next(iter(global_candidates))
        object_label = current_object_name or current_object_id or "unknown"
        message = (
            f"Resolved [{column_name}] => {only_id.split(':', maxsplit=1)[1]} "
            f"(implicit global-unique scope, object={object_label})"
        )
        return only_id, "Resolved by global unique column match.", message, False
    if len(global_candidates) > 1:
        return None, "Ambiguous unqualified column reference; appears in multiple tables.", None, True
    return None, "Unqualified column ref; implicit scope not applied (column missing in current table).", None, False


def _measure_resolution_reason(reason_code: str) -> str:
    if reason_code == "ambiguous_measure":
        return "Ambiguous measure reference; appears in multiple tables."
    return "Missing referenced measure."


def _resolve_qualified_reference(
    *,
    table_name: str,
    object_name: str,
    dependencies: set[str],
    unknown_patterns: list[str],
    tables_by_lower: dict[str, str],
    columns_by_table_lower: dict[tuple[str, str], str],
    measure_key_to_id: dict[tuple[str, str], str],
) -> None:
    table_key = table_name.strip().strip("'").lower()
    object_key = object_name.strip().lower()
    canonical_table = tables_by_lower.get(table_key, table_name.strip().strip("'"))

    column_id = columns_by_table_lower.get((table_key, object_key))
    if column_id:
        dependencies.add(column_id)
        return

    measure_id = measure_key_to_id.get((table_key, object_key))
    if measure_id:
        dependencies.add(measure_id)
        return

    fallback_column = ObjectRef(
        type=ObjectType.COLUMN,
        table=canonical_table,
        name=object_name.strip(),
    ).canonical_id()
    dependencies.add(fallback_column)
    # Keep deterministic fallback for unresolved qualified refs without flagging noise.
    _ = unknown_patterns


def _registry_from_name_index(measure_name_to_ids: dict[str, set[str]]) -> dict[str, Any]:
    measure_key_to_id: dict[tuple[str, str], str] = {}
    for ids in measure_name_to_ids.values():
        for object_id in ids:
            if not object_id.startswith("Measure:"):
                continue
            body = object_id.split(":", maxsplit=1)[1]
            if "." not in body:
                continue
            table_name, measure_name = body.split(".", maxsplit=1)
            measure_key_to_id[(table_name.lower(), measure_name.lower())] = object_id
    return {
        "tables_by_lower": {},
        "columns_by_table_lower": {},
        "columns_by_name_lower": {},
        "measure_name_to_ids": measure_name_to_ids,
        "measure_key_to_id": measure_key_to_id,
    }
