"""Column inventory extractor."""

from __future__ import annotations

from typing import Any

from semantic_test.core.model.objects import ObjectRef, ObjectType
from semantic_test.core.parse.extractors.measures import (
    build_reference_registry,
    extract_expression_dependencies,
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
        if expression:
            dependencies, unknown_patterns = extract_expression_dependencies(
                expression=expression,
                current_table=table_name,
                reference_registry=registry,
            )
        inventory[object_key] = {
            "id": object_key,
            "type": ObjectType.COLUMN.value,
            "name": column.name,
            "table": table_name,
            "expression": expression or None,
            "dependencies": dependencies,
            "unknown_patterns": unknown_patterns,
            "source_file": column.source_file,
            "has_known_table": column.table is not None,
            "object_ref": ref,
        }
    return inventory
