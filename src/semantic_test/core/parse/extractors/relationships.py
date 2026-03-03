"""Relationship inventory extractor."""

from __future__ import annotations

from typing import Any

from semantic_test.core.model.objects import ObjectRef, ObjectType
from semantic_test.core.parse.tmdl_parser import ParsedModel


def extract_relationships(parsed: ParsedModel) -> dict[str, dict[str, Any]]:
    """Build relationship inventory as ``{object_id: metadata}``."""
    inventory: dict[str, dict[str, Any]] = {}
    for relationship in parsed.relationships:
        has_full_endpoints = all(
            [
                relationship.from_table,
                relationship.from_column,
                relationship.to_table,
                relationship.to_column,
            ]
        )

        if has_full_endpoints:
            ref = ObjectRef(
                type=ObjectType.RELATIONSHIP,
                from_table=relationship.from_table,
                from_column=relationship.from_column,
                to_table=relationship.to_table,
                to_column=relationship.to_column,
            )
            object_key = ref.canonical_id()
            from_column_id = ObjectRef(
                type=ObjectType.COLUMN,
                table=str(relationship.from_table),
                name=str(relationship.from_column),
            ).canonical_id()
            to_column_id = ObjectRef(
                type=ObjectType.COLUMN,
                table=str(relationship.to_table),
                name=str(relationship.to_column),
            ).canonical_id()
            dependencies = {from_column_id, to_column_id}
        else:
            # Phase 1 parser can surface incomplete blocks; keep them disclosed.
            ref = None
            object_key = f"RelIncomplete:{relationship.name}"
            dependencies = set()

        inventory[object_key] = {
            "id": object_key,
            "type": ObjectType.RELATIONSHIP.value,
            "name": relationship.name,
            "from_table": relationship.from_table,
            "from_column": relationship.from_column,
            "to_table": relationship.to_table,
            "to_column": relationship.to_column,
            "cardinality": relationship.cardinality,
            "cross_filter_direction": relationship.cross_filter_direction,
            "is_active": relationship.is_active,
            "source_file": relationship.source_file,
            "is_complete": has_full_endpoints,
            "dependencies": dependencies,
            "object_ref": ref,
        }
    return inventory
