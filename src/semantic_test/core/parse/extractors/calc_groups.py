"""Calculation group extraction (experimental coverage)."""

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
_CALC_GROUP_MARKER_RE = re.compile(r"^\s*calculationGroup\b|^\s*calculationGroup\s*:")
_CALC_ITEM_RE = re.compile(r"^\s*calculationItem\s+(.+?)(?:\s*=\s*(.*))?\s*$")
_PROPERTY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*:")


def extract_calc_groups(
    parsed: ParsedModel,
    documents: list[TmdlDocument] | list[tuple[str, str, str]],
) -> dict[str, dict[str, Any]]:
    """Extract calc group tables and calc items as graph-presence objects."""
    inventory: dict[str, dict[str, Any]] = {}
    measure_name_index = build_measure_name_index(parsed)

    for relative_path, content in _iter_documents(documents):
        lines = content.split("\n")
        table_name = _find_table_name(lines)
        if table_name is None:
            continue

        if not _is_calc_group(lines):
            continue

        group_ref = ObjectRef(type=ObjectType.CALC_GROUP, name=table_name)
        group_id = group_ref.canonical_id()
        inventory[group_id] = {
            "id": group_id,
            "type": ObjectType.CALC_GROUP.value,
            "name": table_name,
            "table": table_name,
            "source_file": relative_path,
            "experimental_coverage": True,
            "dependencies": set(),
            "unknown_patterns": [],
            "object_ref": group_ref,
        }

        for item in _extract_calc_items(lines):
            item_ref = ObjectRef(type=ObjectType.CALC_ITEM, parent=table_name, name=item["name"])
            item_id = item_ref.canonical_id()
            expression = item["expression"] or ""
            deps, unknown = extract_expression_dependencies(
                expression=expression,
                current_table=table_name,
                measure_name_to_ids=measure_name_index,
            )
            inventory[item_id] = {
                "id": item_id,
                "type": ObjectType.CALC_ITEM.value,
                "name": item["name"],
                "parent": table_name,
                "raw_expression": expression,
                "dependencies": deps,
                "unknown_patterns": unknown,
                "source_file": relative_path,
                "experimental_coverage": True,
                "object_ref": item_ref,
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


def _is_calc_group(lines: list[str]) -> bool:
    return any(_CALC_GROUP_MARKER_RE.search(line) for line in lines) or any(
        _CALC_ITEM_RE.match(line) for line in lines
    )


def _extract_calc_items(lines: list[str]) -> list[dict[str, str | None]]:
    items: list[dict[str, str | None]] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        match = _CALC_ITEM_RE.match(line)
        if not match:
            idx += 1
            continue

        name = match.group(1).strip().strip("'")
        inline_expression = match.group(2)
        expression, next_idx = _collect_expression(
            lines=lines,
            start_idx=idx + 1,
            header_indent=_indent_len(line),
            inline_expression=inline_expression,
        )
        items.append({"name": name, "expression": expression})
        idx = next_idx
    return items


def _collect_expression(
    *,
    lines: list[str],
    start_idx: int,
    header_indent: int,
    inline_expression: str | None,
) -> tuple[str | None, int]:
    if inline_expression is not None and inline_expression.strip():
        return inline_expression.strip(), start_idx

    collected: list[str] = []
    idx = start_idx
    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()
        if not stripped:
            if collected:
                collected.append("")
            idx += 1
            continue
        if _indent_len(line) <= header_indent:
            break
        if _CALC_ITEM_RE.match(stripped):
            break
        if _PROPERTY_RE.match(stripped) or stripped.startswith("annotation "):
            break
        collected.append(stripped)
        idx += 1
    expression = "\n".join(collected).strip()
    return (expression or None), idx


def _indent_len(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))
