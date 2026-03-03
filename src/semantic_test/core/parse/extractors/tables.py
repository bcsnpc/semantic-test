"""Table inventory extractor."""

from __future__ import annotations

from typing import Any

from semantic_test.core.model.objects import ObjectRef, ObjectType
from semantic_test.core.parse.tmdl_parser import ParsedModel


def extract_tables(parsed: ParsedModel) -> dict[str, dict[str, Any]]:
    """Build table inventory as ``{object_id: metadata}``."""
    inventory: dict[str, dict[str, Any]] = {}
    for table in parsed.tables:
        ref = ObjectRef(type=ObjectType.TABLE, name=table.name)
        object_key = ref.canonical_id()
        inventory[object_key] = {
            "id": object_key,
            "type": ObjectType.TABLE.value,
            "name": table.name,
            "source_file": table.source_file,
            "object_ref": ref,
        }
    return inventory
