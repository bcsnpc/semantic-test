"""JSON report formatter."""

from __future__ import annotations

from dataclasses import asdict
import json

from semantic_test.core.analysis.exposure import ExposureResult
from semantic_test.core.diff.differ import DiffResult
from semantic_test.core.model.coverage import coverage_report
from semantic_test.core.report.schemas import build_report_schema_v1


def format_report_json(
    diff_result: DiffResult,
    exposure_result: ExposureResult,
    coverage_data: dict | None = None,
    run_id: str = "unknown",
    model_key: str = "semanticmodel::unknown",
    old_snapshot_hash: str | None = None,
    new_snapshot_hash: str = "",
    unknown_patterns: list[dict[str, object]] | None = None,
    unresolved_refs: list[dict[str, str]] | None = None,
) -> str:
    """Render versioned JSON report output (schema v1)."""
    selected_coverage = coverage_data or coverage_report()[1]
    report = build_report_schema_v1(
        diff_result,
        exposure_result,
        selected_coverage,
        run_id=run_id,
        model_key=model_key,
        old_snapshot_hash=old_snapshot_hash,
        new_snapshot_hash=new_snapshot_hash,
        unknown_patterns=unknown_patterns,
        unresolved_refs=unresolved_refs,
    )
    return json.dumps(asdict(report), indent=2, sort_keys=True)
