"""Versioned report schemas."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from semantic_test import __version__
from semantic_test.core.analysis.exposure import ExposureResult, ExposureTopObject
from semantic_test.core.diff.change_types import ChangeType
from semantic_test.core.diff.differ import DiffResult

REPORT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ChangeEntryV1:
    object_id: str
    object_type: str
    change_type: str


@dataclass(frozen=True, slots=True)
class ExposureEntryV1:
    changed_object_id: str
    downstream_count: int
    downstream_by_type: dict[str, int]
    downstream_ids: list[str]
    top_downstream_items: list[dict[str, str]]


@dataclass(frozen=True, slots=True)
class ReportChangesSummaryV1:
    total: int
    added: int
    removed: int
    modified: int


@dataclass(frozen=True, slots=True)
class ReportGapsV1:
    known_gaps: list[dict[str, str]]
    unknown_patterns: list[dict[str, object]]
    unresolved_refs: list[dict[str, str]]


@dataclass(frozen=True, slots=True)
class ReportSchemaV1:
    schema_version: int
    tool_version: str
    run_id: str
    model_key: str
    old_snapshot_hash: str | None
    new_snapshot_hash: str
    detected_changes: ReportChangesSummaryV1
    changes: list[ChangeEntryV1]
    exposure: list[ExposureEntryV1]
    coverage: dict[str, Any]
    gaps: ReportGapsV1


def build_report_schema_v1(
    diff_result: DiffResult,
    exposure_result: ExposureResult,
    coverage_data: dict[str, Any],
    *,
    run_id: str = "unknown",
    model_key: str = "semanticmodel::unknown",
    old_snapshot_hash: str | None = None,
    new_snapshot_hash: str = "",
    tool_version: str = __version__,
    unknown_patterns: list[dict[str, object]] | None = None,
    unresolved_refs: list[dict[str, str]] | None = None,
) -> ReportSchemaV1:
    """Build stable report schema payload for JSON/text formatters."""
    changes = _normalize_changes(diff_result.changes)
    exposure = _normalize_exposure(exposure_result)
    summary = ReportChangesSummaryV1(
        total=len(diff_result.changed_object_ids),
        added=len(diff_result.added_object_ids),
        removed=len(diff_result.removed_object_ids),
        modified=len(diff_result.modified_object_ids),
    )
    return ReportSchemaV1(
        schema_version=REPORT_SCHEMA_VERSION,
        tool_version=tool_version,
        run_id=run_id,
        model_key=model_key,
        old_snapshot_hash=old_snapshot_hash,
        new_snapshot_hash=new_snapshot_hash,
        detected_changes=summary,
        changes=changes,
        exposure=exposure,
        coverage=_normalize_coverage(coverage_data),
        gaps=ReportGapsV1(
            known_gaps=_known_gaps_from_coverage(coverage_data),
            unknown_patterns=_normalize_unknown_patterns(unknown_patterns or []),
            unresolved_refs=_normalize_unresolved_refs(unresolved_refs or []),
        ),
    )


def _normalize_changes(changes: list[ChangeType]) -> list[ChangeEntryV1]:
    rows = [
        ChangeEntryV1(
            object_id=change.object_id,
            object_type=change.object_type,
            change_type=change.change_type,
        )
        for change in changes
    ]
    rows.sort(key=lambda row: (row.object_id, row.change_type))
    return rows


def _normalize_exposure(exposure_result: ExposureResult) -> list[ExposureEntryV1]:
    rows: list[ExposureEntryV1] = []
    for item in exposure_result.items:
        rows.append(
            ExposureEntryV1(
                changed_object_id=item.changed_object_id,
                downstream_count=len(item.downstream_ids),
                downstream_by_type=dict(sorted(item.downstream_by_type_counts.items())),
                downstream_ids=sorted(item.downstream_ids),
                top_downstream_items=[
                    _top_object_to_dict(top_item) for top_item in item.top_downstream_objects
                ],
            )
        )
    rows.sort(key=lambda row: row.changed_object_id)
    return rows


def _normalize_coverage(coverage_data: dict[str, Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for item in coverage_data.get("items", []):
        items.append(
            {
                "area": str(item.get("area", "")),
                "pattern": str(item.get("pattern", "")),
                "status": str(item.get("status", "")),
                "icon": str(item.get("icon", "")),
                "notes": str(item.get("notes", "")),
            }
        )
    items.sort(key=lambda row: (row["status"], row["area"], row["pattern"]))
    summary_raw = coverage_data.get("summary", {})
    summary = {
        "supported": int(summary_raw.get("supported", 0)),
        "partial": int(summary_raw.get("partial", 0)),
        "unsupported": int(summary_raw.get("unsupported", 0)),
        "total": int(summary_raw.get("total", len(items))),
    }
    return {"summary": summary, "items": items}


def _known_gaps_from_coverage(coverage_data: dict[str, Any]) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    for item in coverage_data.get("items", []):
        status = str(item.get("status", ""))
        if status == "supported":
            continue
        gaps.append(
            {
                "area": str(item.get("area", "")),
                "pattern": str(item.get("pattern", "")),
                "status": status,
                "notes": str(item.get("notes", "")),
            }
        )
    gaps.sort(key=lambda row: (row["status"], row["area"], row["pattern"]))
    return gaps


def _top_object_to_dict(item: ExposureTopObject) -> dict[str, str]:
    return {"object_id": item.object_id, "type": item.type, "name": item.name}


def _normalize_unknown_patterns(
    entries: list[dict[str, object]],
) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for item in entries:
        object_id = str(item.get("object_id", ""))
        patterns_raw = item.get("patterns", [])
        if isinstance(patterns_raw, list):
            patterns = sorted({str(pattern) for pattern in patterns_raw if str(pattern).strip()})
        else:
            patterns = []
        if not object_id or not patterns:
            continue
        normalized.append({"object_id": object_id, "patterns": patterns})
    normalized.sort(key=lambda row: str(row["object_id"]))
    return normalized


def _normalize_unresolved_refs(
    entries: list[dict[str, str]],
) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in entries:
        object_id = str(item.get("object_id", ""))
        ref = str(item.get("ref", ""))
        if not object_id or not ref:
            continue
        normalized.append({"object_id": object_id, "ref": ref})
    normalized.sort(key=lambda row: (row["object_id"], row["ref"]))
    return normalized
