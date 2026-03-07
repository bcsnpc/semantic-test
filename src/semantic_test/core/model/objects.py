"""Canonical object model and ID helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ObjectType(str, Enum):
    """Supported semantic model object categories."""

    TABLE = "Table"
    COLUMN = "Column"
    MEASURE = "Measure"
    RELATIONSHIP = "Rel"
    CALC_GROUP = "CalcGroup"
    CALC_ITEM = "CalcItem"
    FIELD_PARAMETER = "FieldParam"
    HIERARCHY = "Hierarchy"
    LEVEL = "Level"
    VISUAL = "Visual"


@dataclass(frozen=True, slots=True)
class ObjectRef:
    """Stable internal reference for semantic objects."""

    type: ObjectType
    name: str | None = None
    table: str | None = None
    from_table: str | None = None
    from_column: str | None = None
    to_table: str | None = None
    to_column: str | None = None
    parent: str | None = None

    def canonical_id(self) -> str:
        """Return canonical stable ID for this object."""
        return object_id(
            obj_type=self.type,
            name=self.name,
            table=self.table,
            from_table=self.from_table,
            from_column=self.from_column,
            to_table=self.to_table,
            to_column=self.to_column,
            parent=self.parent,
        )


def _require(value: str | None, field_name: str) -> str:
    if value is None:
        raise ValueError(f"{field_name} is required")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty")
    return cleaned


def object_id(
    *,
    obj_type: ObjectType,
    name: str | None = None,
    table: str | None = None,
    from_table: str | None = None,
    from_column: str | None = None,
    to_table: str | None = None,
    to_column: str | None = None,
    parent: str | None = None,
) -> str:
    """Build canonical object IDs used across parse/graph/diff layers."""

    if obj_type is ObjectType.TABLE:
        return f"Table:{_require(name, 'name')}"

    if obj_type is ObjectType.COLUMN:
        return f"Column:{_require(table, 'table')}.{_require(name, 'name')}"

    if obj_type is ObjectType.MEASURE:
        measure_name = _require(name, "name")
        if table is None or not table.strip():
            return f"Measure:{measure_name}"
        return f"Measure:{table.strip()}.{measure_name}"

    if obj_type is ObjectType.RELATIONSHIP:
        return (
            "Rel:"
            f"{_require(from_table, 'from_table')}.{_require(from_column, 'from_column')}"
            "->"
            f"{_require(to_table, 'to_table')}.{_require(to_column, 'to_column')}"
        )

    if obj_type is ObjectType.CALC_GROUP:
        return f"CalcGroup:{_require(name, 'name')}"

    if obj_type is ObjectType.CALC_ITEM:
        return f"CalcItem:{_require(parent, 'parent')}.{_require(name, 'name')}"

    if obj_type is ObjectType.FIELD_PARAMETER:
        return f"FieldParam:{_require(name, 'name')}"

    if obj_type is ObjectType.HIERARCHY:
        return f"Hierarchy:{_require(table, 'table')}.{_require(name, 'name')}"

    if obj_type is ObjectType.LEVEL:
        return (
            "Level:"
            f"{_require(table, 'table')}.{_require(parent, 'parent')}.{_require(name, 'name')}"
        )

    if obj_type is ObjectType.VISUAL:
        # parent = page display name, name = visual_id (first 12 chars)
        return f"Visual:{_require(parent, 'parent')}.{_require(name, 'name')}"

    raise ValueError(f"Unsupported object type: {obj_type}")
