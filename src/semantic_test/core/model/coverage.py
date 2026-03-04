"""Coverage model for parser/extractor support disclosure."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import os
import sys
from typing import Any


class CoverageStatus(str, Enum):
    """Coverage status marker with explicit icon output."""

    SUPPORTED = "✅"
    PARTIAL = "⚠️"
    UNSUPPORTED = "❌"


@dataclass(frozen=True, slots=True)
class CoverageItem:
    """Single capability in the parser/extractor support matrix."""

    area: str
    pattern: str
    status: CoverageStatus
    notes: str = ""


@dataclass(frozen=True, slots=True)
class CoverageMatrix:
    """Complete parser/extractor coverage matrix."""

    items: list[CoverageItem]


DEFAULT_CRITICAL_COVERAGE_AREAS = (
    "parser",
    "extractor.tables",
    "extractor.columns",
    "extractor.measures",
    "extractor.relationships",
)
CRITICAL_COVERAGE_ENV_VAR = "SEMANTIC_TEST_CRITICAL_COVERAGE"


def default_coverage_matrix() -> CoverageMatrix:
    """Return initial conservative coverage claims."""
    return CoverageMatrix(
        items=[
            CoverageItem(
                area="parser",
                pattern="Locate PBIP/TMDL files",
                status=CoverageStatus.SUPPORTED,
                notes="Finds definition folders from repo root, .SemanticModel, or definition path.",
            ),
            CoverageItem(
                area="extractor.tables",
                pattern="Table object extraction",
                status=CoverageStatus.SUPPORTED,
                notes="Canonical table IDs are defined.",
            ),
            CoverageItem(
                area="extractor.columns",
                pattern="Column extraction",
                status=CoverageStatus.PARTIAL,
                notes="Creates column nodes and parses calculated-column expressions for dependencies.",
            ),
            CoverageItem(
                area="extractor.measures",
                pattern="Measure extraction",
                status=CoverageStatus.PARTIAL,
                notes="Creates measure nodes and resolves common DAX dependency reference patterns.",
            ),
            CoverageItem(
                area="extractor.relationships",
                pattern="Relationship extraction",
                status=CoverageStatus.PARTIAL,
                notes="Extracts relationship properties and IDs; relationship edge enrichment is limited.",
            ),
            CoverageItem(
                area="extractor.calc_groups",
                pattern="Calculation groups and items",
                status=CoverageStatus.PARTIAL,
                notes="Experimental: creates calc group/item nodes and parses calc-item expression dependencies.",
            ),
            CoverageItem(
                area="extractor.field_params",
                pattern="Field parameter tables",
                status=CoverageStatus.PARTIAL,
                notes="Experimental: detects field parameter tables and parses partition-source dependencies.",
            ),
        ]
    )


def coverage_report(
    matrix: CoverageMatrix | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Return human-readable summary lines plus machine-readable coverage data."""
    selected = matrix or default_coverage_matrix()
    counts = {
        CoverageStatus.SUPPORTED: 0,
        CoverageStatus.PARTIAL: 0,
        CoverageStatus.UNSUPPORTED: 0,
    }
    for item in selected.items:
        counts[item.status] += 1

    status_labels = {
        CoverageStatus.SUPPORTED: _display_status(CoverageStatus.SUPPORTED),
        CoverageStatus.PARTIAL: _display_status(CoverageStatus.PARTIAL),
        CoverageStatus.UNSUPPORTED: _display_status(CoverageStatus.UNSUPPORTED),
    }

    summary_lines = [
        "Coverage Summary",
        f"  {status_labels[CoverageStatus.SUPPORTED]} Supported: {counts[CoverageStatus.SUPPORTED]}",
        f"  {status_labels[CoverageStatus.PARTIAL]} Partial: {counts[CoverageStatus.PARTIAL]}",
        f"  {status_labels[CoverageStatus.UNSUPPORTED]} Unsupported: {counts[CoverageStatus.UNSUPPORTED]}",
        "Coverage Matrix",
    ]
    for item in selected.items:
        line = f"  {status_labels[item.status]} [{item.area}] {item.pattern}"
        if item.notes:
            line = f"{line} - {item.notes}"
        summary_lines.append(line)

    machine_data = {
        "summary": {
            "supported": counts[CoverageStatus.SUPPORTED],
            "partial": counts[CoverageStatus.PARTIAL],
            "unsupported": counts[CoverageStatus.UNSUPPORTED],
            "total": len(selected.items),
        },
        "items": [
            {
                **asdict(item),
                "status": item.status.name.lower(),
                "icon": item.status.value,
            }
            for item in selected.items
        ],
    }
    return summary_lines, machine_data


def strict_policy_violations(
    *,
    coverage_data: dict[str, Any],
    unknown_patterns: list[dict[str, Any]] | None = None,
    unresolved_refs: list[dict[str, Any]] | None = None,
    critical_areas: list[str] | tuple[str, ...] | set[str] | None = None,
) -> list[str]:
    """Return strict-mode policy failures for CI gating."""
    violations: list[str] = []

    unknown_count = len(unknown_patterns or [])
    if unknown_count:
        violations.append(f"unknown_patterns:{unknown_count}")

    unresolved_count = len(unresolved_refs or [])
    if unresolved_count:
        violations.append(f"unresolved_refs:{unresolved_count}")

    areas = set(critical_areas) if critical_areas is not None else critical_coverage_areas()
    unsupported_critical = _unsupported_critical_areas(coverage_data, areas)
    for area in unsupported_critical:
        violations.append(f"unsupported_coverage:{area}")
    return violations


def critical_coverage_areas() -> set[str]:
    """Resolve critical coverage categories from env or defaults."""
    raw_value = os.getenv(CRITICAL_COVERAGE_ENV_VAR, "").strip()
    if not raw_value:
        return set(DEFAULT_CRITICAL_COVERAGE_AREAS)
    values = [item.strip() for item in raw_value.split(",")]
    parsed = {value for value in values if value}
    if parsed:
        return parsed
    return set(DEFAULT_CRITICAL_COVERAGE_AREAS)


def _display_status(status: CoverageStatus) -> str:
    if _supports_console_icon(status.value):
        return status.value
    fallback = {
        CoverageStatus.SUPPORTED: "[OK]",
        CoverageStatus.PARTIAL: "[WARN]",
        CoverageStatus.UNSUPPORTED: "[MISS]",
    }
    return fallback[status]


def _unsupported_critical_areas(
    coverage_data: dict[str, Any],
    critical_areas: set[str],
) -> list[str]:
    matches: set[str] = set()
    for item in coverage_data.get("items", []):
        status = str(item.get("status", "")).strip().lower()
        area = str(item.get("area", "")).strip()
        if status != "unsupported" or not area:
            continue
        if area in critical_areas:
            matches.add(area)
    return sorted(matches)


def _supports_console_icon(icon: str) -> bool:
    encoding = sys.stdout.encoding or "utf-8"
    try:
        icon.encode(encoding)
    except UnicodeEncodeError:
        return False
    return True
