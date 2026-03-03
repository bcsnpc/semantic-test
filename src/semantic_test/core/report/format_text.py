"""Text formatters for CLI report output."""

from semantic_test import __version__
from semantic_test.core.analysis.exposure import ExposureResult
from semantic_test.core.diff.differ import DiffResult
from semantic_test.core.model.coverage import coverage_report
from semantic_test.core.report.schemas import build_report_schema_v1


def format_coverage_text() -> str:
    """Render coverage summary block for terminal output."""
    lines, _machine_data = coverage_report()
    return "\n".join(lines)


def format_pr_text(
    diff_result: DiffResult,
    exposure_result: ExposureResult,
    run_id: str = "unknown",
    model_key: str = "semanticmodel::unknown",
    old_snapshot_hash: str | None = None,
    new_snapshot_hash: str = "",
    coverage_lines: list[str] | None = None,
    coverage_data: dict | None = None,
    unknown_patterns: list[dict[str, object]] | None = None,
    unresolved_refs: list[dict[str, str]] | None = None,
) -> str:
    """Render PR-friendly report text (schema v1)."""
    cov_lines, cov_data = coverage_report()
    selected_lines = coverage_lines or cov_lines
    selected_data = coverage_data or cov_data
    report = build_report_schema_v1(
        diff_result,
        exposure_result,
        selected_data,
        run_id=run_id,
        model_key=model_key,
        old_snapshot_hash=old_snapshot_hash,
        new_snapshot_hash=new_snapshot_hash,
        unknown_patterns=unknown_patterns,
        unresolved_refs=unresolved_refs,
    )

    lines: list[str] = [
        "semantic-test Exposure Report",
        f"Tool Version: {__version__}",
        f"Model Key: {report.model_key}",
        f"Run ID: {report.run_id}",
        f"Old Snapshot Hash: {report.old_snapshot_hash or 'none'}",
        f"New Snapshot Hash: {report.new_snapshot_hash or 'none'}",
        "",
        "Detected Changes",
        f"  Total: {report.detected_changes.total}",
        f"  Added: {report.detected_changes.added}",
        f"  Removed: {report.detected_changes.removed}",
        f"  Modified: {report.detected_changes.modified}",
        "",
        "Per-Changed-Object Exposure",
    ]

    exposure_by_id = {item.changed_object_id: item for item in report.exposure}
    if not report.changes:
        lines.append("- No changed objects.")
    for change in report.changes:
        exposure = exposure_by_id.get(change.object_id)
        lines.append(f"- {change.object_id}")
        lines.append(f"  - Change Type: {change.change_type}")
        if exposure is None:
            lines.append("  - Downstream Dependents: 0")
            lines.append("  - Breakdown: none")
            lines.append("  - Sample Affected Objects: none")
            continue
        lines.append(f"  - Downstream Dependents: {exposure.downstream_count}")
        if exposure.downstream_by_type:
            by_type = ", ".join(
                f"{object_type}={count}"
                for object_type, count in sorted(exposure.downstream_by_type.items())
            )
        else:
            by_type = "none"
        lines.append(f"  - Breakdown: {by_type}")
        if exposure.downstream_ids:
            _TEXT_DISPLAY_LIMIT = 20
            display_ids = exposure.downstream_ids[:_TEXT_DISPLAY_LIMIT]
            remaining = len(exposure.downstream_ids) - len(display_ids)
            lines.append("  - All Affected Objects:")
            for object_id in display_ids:
                lines.append(f"    - {object_id}")
            if remaining > 0:
                lines.append(f"    - ...and {remaining} more (see downstream_ids in report.json)")
        else:
            lines.append("  - All Affected Objects: none")

    lines.extend(["", "Coverage Summary"])
    summary = report.coverage.get("summary", {})
    lines.append(f"  Supported: {summary.get('supported', 0)}")
    lines.append(f"  Partial: {summary.get('partial', 0)}")
    lines.append(f"  Unsupported: {summary.get('unsupported', 0)}")
    lines.extend(["", "Coverage Details", *selected_lines, "", "Known Gaps"])
    if report.gaps.known_gaps:
        for gap in report.gaps.known_gaps:
            lines.append(
                f"- [{gap['status']}] {gap['area']} | {gap['pattern']} | {gap['notes']}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "Unknown Patterns"])
    if report.gaps.unknown_patterns:
        for entry in report.gaps.unknown_patterns:
            patterns = ", ".join(str(pattern) for pattern in entry["patterns"])
            lines.append(f"- {entry['object_id']}: {patterns}")
    else:
        lines.append("- none")

    lines.extend(["", "Unresolved Refs"])
    if report.gaps.unresolved_refs:
        for entry in report.gaps.unresolved_refs:
            lines.append(f"- {entry['object_id']}: {entry['ref']}")
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "Disclaimer: Structural exposure only; does not evaluate KPI correctness.",
        ]
    )
    return "\n".join(lines)
