"""Field parameter extraction (experimental coverage)."""

from __future__ import annotations

import re
from typing import Any

from semantic_test.core.model.objects import ObjectRef, ObjectType
from semantic_test.core.parse.extractors.measures import (
    build_measure_name_index,
    extract_expression_dependencies,
)
from semantic_test.core.parse.tmdl_parser import ParsedModel
from semantic_test.core.parse.tmdl_reader import TmdlDocument

_TABLE_RE = re.compile(r"^\s*table\s+(.+?)\s*$")
_PARTITION_SOURCE_RE = re.compile(r"^\s*source\s*=\s*(.*)$")
_FIELD_PARAM_MARKER_RE = re.compile(
    r"ParameterMetadata|NAMEOF\(|field\s*parameter|parameter",
    flags=re.IGNORECASE,
)


def extract_field_params(
    parsed: ParsedModel,
    documents: list[TmdlDocument] | list[tuple[str, str, str]],
) -> dict[str, dict[str, Any]]:
    """Detect and extract field-parameter tables as special nodes."""
    inventory: dict[str, dict[str, Any]] = {}
    measure_name_index = build_measure_name_index(parsed)

    for relative_path, content in _iter_documents(documents):
        lines = content.split("\n")
        table_name = _find_table_name(lines)
        if table_name is None:
            continue

        if not _looks_like_field_parameter_table(table_name, content):
            continue

        partition_source = _extract_partition_source(lines)
        dependencies, unknown_patterns = extract_expression_dependencies(
            expression=partition_source or "",
            current_table=table_name,
            measure_name_to_ids=measure_name_index,
        )

        ref = ObjectRef(type=ObjectType.FIELD_PARAMETER, name=table_name)
        object_id = ref.canonical_id()
        inventory[object_id] = {
            "id": object_id,
            "type": ObjectType.FIELD_PARAMETER.value,
            "name": table_name,
            "table": table_name,
            "raw_expression": partition_source or "",
            "dependencies": dependencies,
            "unknown_patterns": unknown_patterns,
            "source_file": relative_path,
            "special_table": True,
            "experimental_coverage": True,
            "object_ref": ref,
        }
    return inventory


def _iter_documents(
    documents: list[TmdlDocument] | list[tuple[str, str, str]],
) -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    for item in documents:
        if isinstance(item, TmdlDocument):
            output.append((item.relative_path, item.content))
        else:
            output.append((item[0], item[1]))
    return output


def _find_table_name(lines: list[str]) -> str | None:
    for line in lines:
        match = _TABLE_RE.match(line)
        if match:
            name = match.group(1).strip()
            if len(name) >= 2 and name[0] == "'" and name[-1] == "'":
                return name[1:-1]
            return name
    return None


def _looks_like_field_parameter_table(table_name: str, content: str) -> bool:
    if "parameter" in table_name.lower():
        return True
    return _FIELD_PARAM_MARKER_RE.search(content) is not None


def _extract_partition_source(lines: list[str]) -> str | None:
    for idx, line in enumerate(lines):
        match = _PARTITION_SOURCE_RE.match(line)
        if not match:
            continue
        inline = match.group(1).strip()
        if inline:
            return inline
        base_indent = _indent_len(line)
        collected: list[str] = []
        cursor = idx + 1
        while cursor < len(lines):
            nested = lines[cursor]
            if nested.strip() and _indent_len(nested) <= base_indent:
                break
            if nested.strip():
                collected.append(nested.strip())
            cursor += 1
        return "\n".join(collected).strip() or None
    return None


def _indent_len(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))
