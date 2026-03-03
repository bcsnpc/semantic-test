"""Minimal structured extraction parser for TMDL (Phase 1)."""

from __future__ import annotations

from dataclasses import dataclass
import re

from semantic_test.core.parse.tmdl_reader import TmdlDocument

_TABLE_RE = re.compile(r"^\s*table\s+(.+?)\s*$")
_COLUMN_RE = re.compile(r"^\s*column\s+(.+?)(?:\s*=\s*(.*))?\s*$")
_MEASURE_RE = re.compile(r"^\s*measure\s+(.+?)(?:\s*=\s*(.*))?\s*$")
_REL_RE = re.compile(r"^\s*relationship\s+(.+?)\s*$")
_FROM_RE = re.compile(r"^\s*fromColumn:\s*(.+?)\s*$")
_TO_RE = re.compile(r"^\s*toColumn:\s*(.+?)\s*$")
_CARDINALITY_RE = re.compile(r"^\s*cardinality:\s*(.+?)\s*$")
_CROSS_FILTER_RE = re.compile(r"^\s*crossFilteringBehavior:\s*(.+?)\s*$")
_IS_ACTIVE_RE = re.compile(r"^\s*isActive:\s*(true|false)\s*$", re.IGNORECASE)
_PROPERTY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*:")


@dataclass(frozen=True, slots=True)
class ParsedTable:
    name: str
    source_file: str


@dataclass(frozen=True, slots=True)
class ParsedColumn:
    name: str
    table: str | None
    expression: str | None
    source_file: str


@dataclass(frozen=True, slots=True)
class ParsedMeasure:
    name: str
    table: str | None
    expression: str | None
    source_file: str


@dataclass(frozen=True, slots=True)
class ParsedRelationship:
    name: str
    from_table: str | None
    from_column: str | None
    to_table: str | None
    to_column: str | None
    source_file: str
    cardinality: str | None = None
    cross_filter_direction: str | None = None
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class ParsedModel:
    tables: list[ParsedTable]
    columns: list[ParsedColumn]
    measures: list[ParsedMeasure]
    relationships: list[ParsedRelationship]


def parse_tmdl_documents(
    documents: list[TmdlDocument] | list[tuple[str, str, str]],
) -> ParsedModel:
    """Parse TMDL text into a minimal structured model."""
    tables: list[ParsedTable] = []
    columns: list[ParsedColumn] = []
    measures: list[ParsedMeasure] = []
    relationships: list[ParsedRelationship] = []

    for relative_path, content in _iter_document_content(documents):
        _parse_single_document(
            relative_path=relative_path,
            content=content,
            tables=tables,
            columns=columns,
            measures=measures,
            relationships=relationships,
        )

    return ParsedModel(
        tables=tables,
        columns=columns,
        measures=measures,
        relationships=relationships,
    )


def _iter_document_content(
    documents: list[TmdlDocument] | list[tuple[str, str, str]],
) -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    for item in documents:
        if isinstance(item, TmdlDocument):
            output.append((item.relative_path, item.content))
            continue
        relative_path, content, _sha256 = item
        output.append((relative_path, content))
    return output


def _parse_single_document(
    *,
    relative_path: str,
    content: str,
    tables: list[ParsedTable],
    columns: list[ParsedColumn],
    measures: list[ParsedMeasure],
    relationships: list[ParsedRelationship],
) -> None:
    lines = content.split("\n")
    current_table: str | None = None
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        table_match = _TABLE_RE.match(line)
        if table_match:
            table_name = _clean_name(table_match.group(1))
            current_table = table_name
            tables.append(ParsedTable(name=table_name, source_file=relative_path))
            idx += 1
            continue

        column_match = _COLUMN_RE.match(line)
        if column_match:
            name = _clean_name(column_match.group(1))
            inline_expr = column_match.group(2)
            expression, next_idx = _collect_expression(
                lines=lines,
                start_idx=idx + 1,
                header_indent=_indent_len(line),
                inline_expression=inline_expr,
            )
            columns.append(
                ParsedColumn(
                    name=name,
                    table=current_table,
                    expression=expression,
                    source_file=relative_path,
                )
            )
            idx = next_idx
            continue

        measure_match = _MEASURE_RE.match(line)
        if measure_match:
            name = _clean_name(measure_match.group(1))
            inline_expr = measure_match.group(2)
            expression, next_idx = _collect_expression(
                lines=lines,
                start_idx=idx + 1,
                header_indent=_indent_len(line),
                inline_expression=inline_expr,
            )
            measures.append(
                ParsedMeasure(
                    name=name,
                    table=current_table,
                    expression=expression,
                    source_file=relative_path,
                )
            )
            idx = next_idx
            continue

        rel_match = _REL_RE.match(line)
        if rel_match:
            rel_name = _clean_name(rel_match.group(1))
            from_table = None
            from_column = None
            to_table = None
            to_column = None
            cardinality = None
            cross_filter_direction = None
            is_active = True
            next_idx = idx + 1
            while next_idx < len(lines):
                nested = lines[next_idx]
                if _indent_len(nested) <= _indent_len(line) and nested.strip():
                    break
                from_match = _FROM_RE.match(nested)
                to_match = _TO_RE.match(nested)
                cardinality_match = _CARDINALITY_RE.match(nested)
                cross_filter_match = _CROSS_FILTER_RE.match(nested)
                is_active_match = _IS_ACTIVE_RE.match(nested)
                if from_match:
                    from_table, from_column = _parse_endpoint(from_match.group(1))
                if to_match:
                    to_table, to_column = _parse_endpoint(to_match.group(1))
                if cardinality_match:
                    cardinality = cardinality_match.group(1).strip()
                if cross_filter_match:
                    cross_filter_direction = cross_filter_match.group(1).strip()
                if is_active_match:
                    is_active = is_active_match.group(1).strip().lower() == "true"
                next_idx += 1
            relationships.append(
                ParsedRelationship(
                    name=rel_name,
                    from_table=from_table,
                    from_column=from_column,
                    to_table=to_table,
                    to_column=to_column,
                    source_file=relative_path,
                    cardinality=cardinality,
                    cross_filter_direction=cross_filter_direction,
                    is_active=is_active,
                )
            )
            idx = next_idx
            continue

        idx += 1


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
        if _looks_like_object_header(stripped):
            break
        if _PROPERTY_RE.match(stripped) or stripped.startswith("annotation "):
            break
        collected.append(stripped)
        idx += 1

    expression = "\n".join(collected).strip()
    return (expression or None), idx


def _looks_like_object_header(stripped_line: str) -> bool:
    return any(
        regex.match(stripped_line)
        for regex in (_TABLE_RE, _COLUMN_RE, _MEASURE_RE, _REL_RE)
    )


def _parse_endpoint(endpoint: str) -> tuple[str | None, str | None]:
    parts = endpoint.rsplit(".", maxsplit=1)
    if len(parts) != 2:
        return None, None
    return _clean_name(parts[0]), _clean_name(parts[1])


def _clean_name(value: str) -> str:
    name = value.strip()
    if len(name) >= 2 and name[0] == "'" and name[-1] == "'":
        return name[1:-1]
    return name


def _indent_len(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))
