"""Column inventory extractor."""

from __future__ import annotations

from typing import Any

from semantic_test.core.model.objects import ObjectRef, ObjectType
from semantic_test.core.parse.extractors.measures import (
    build_reference_registry,
    extract_expression_analysis,
)
from semantic_test.core.parse.tmdl_parser import ParsedModel

_UNKNOWN_TABLE = "<unknown>"


def extract_columns(parsed: ParsedModel) -> dict[str, dict[str, Any]]:
    """Build column inventory as ``{object_id: metadata}``."""
    inventory: dict[str, dict[str, Any]] = {}
    registry = build_reference_registry(parsed)
    for column in parsed.columns:
        table_name = column.table or _UNKNOWN_TABLE
        ref = ObjectRef(type=ObjectType.COLUMN, table=table_name, name=column.name)
        object_key = ref.canonical_id()
        expression = column.expression or ""
        dependencies: set[str] = set()
        unknown_patterns: list[str] = []
        unresolved_references: list[dict[str, str]] = []
        resolution_assumptions: list[str] = []
        ambiguous_reference_count = 0
        if expression:
            analysis = extract_expression_analysis(
                expression=expression,
                current_table=table_name,
                current_object_id=object_key,
                current_object_name=column.name,
                expression_context="calculated_column",
                reference_registry=registry,
            )
            dependencies = analysis.dependencies
            unknown_patterns = analysis.unknown_patterns
            unresolved_references = analysis.unresolved_references
            resolution_assumptions = analysis.resolution_assumptions
            ambiguous_reference_count = analysis.ambiguous_reference_count
        inventory[object_key] = {
            "id": object_key,
            "type": ObjectType.COLUMN.value,
            "name": column.name,
            "table": table_name,
            "expression": expression or None,
            "dependencies": dependencies,
            "unknown_patterns": unknown_patterns,
            "unresolved_references": unresolved_references,
            "resolution_assumptions": resolution_assumptions,
            "ambiguous_reference_count": ambiguous_reference_count,
            "source_file": column.source_file,
            "has_known_table": column.table is not None,
            "object_ref": ref,
        }
    return inventory
