"""Exposure command."""

from __future__ import annotations

from dataclasses import asdict
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer

from semantic_test.cli.commands._pipeline import build_model_artifacts
from semantic_test.core.analysis.exposure import analyze_exposure
from semantic_test.core.diff.differ import diff_snapshots
from semantic_test.core.diff.snapshot import load_snapshot
from semantic_test.core.io.index_manager import get_model_entry, load_index
from semantic_test.core.io.output_manager import (
    create_run_folder,
    get_output_root,
    write_manifest,
    write_text,
)
from semantic_test.core.model.coverage import coverage_report
from semantic_test.core.model.model_key import resolve_project_root
from semantic_test.core.report.format_json import format_report_json
from semantic_test.core.report.format_text import format_pr_text


def exposure_command(
    path_a: str = typer.Argument(...),
    path_b: str | None = typer.Argument(None),
    output_format: str = typer.Option("text", "--format"),
    out: str | None = typer.Option(None, "--out"),
    outdir: str | None = typer.Option(None, "--outdir"),
    json_output: bool = typer.Option(False, "--json"),
    strict: bool = typer.Option(False, "--strict"),
) -> None:
    """Analyze downstream dependents for changed objects."""
    if json_output:
        output_format = "json"
    if output_format not in {"text", "json"}:
        raise typer.BadParameter("--format must be one of: text, json")

    now = datetime.now(timezone.utc)
    explicit_mode = path_b is not None
    before_path = path_a if explicit_mode else "<auto-previous>"
    after_path = path_b if explicit_mode else path_a

    project_root = resolve_project_root(after_path)
    output_root = get_output_root(project_root, outdir_override=outdir)
    run_folder = create_run_folder(
        output_root=output_root,
        command="exposure",
        model_key=Path(after_path).name or "model",
        snapshot_hash="pending",
        now=now,
    )
    manifest: dict[str, object] = {
        "version": "0.1",
        "command": "exposure",
        "timestamp_utc": now.isoformat(),
        "mode": "explicit" if explicit_mode else "auto_previous",
        "before_path": before_path,
        "after_path": after_path,
        "output_format": output_format,
        "strict": strict,
        "status": "RUNNING",
        "error": None,
        "before_snapshot_hash": None,
        "after_snapshot_hash": None,
        "model_key": None,
        "run_folder": str(run_folder),
    }

    coverage_lines, coverage_data = coverage_report()
    try:
        after = build_model_artifacts(after_path)
        if explicit_mode:
            before_artifacts = build_model_artifacts(path_a)
            before_snapshot = before_artifacts.snapshot
            before_unknown_patterns = before_artifacts.unknown_patterns
        else:
            before_snapshot, before_unknown_patterns = _load_previous_snapshot(
                output_root=output_root,
                project_root=project_root,
                model_key=after.model_key,
            )
    except (FileNotFoundError, ValueError) as error:
        message = str(error)
        manifest["status"] = "ERROR"
        manifest["error"] = message
        write_text(run_folder, "snapshot.json", json.dumps({"status": "ERROR", "error": message}, indent=2, sort_keys=True))
        write_text(run_folder, "report.txt", f"Status: ERROR\nError: {message}")
        write_text(run_folder, "report.json", json.dumps({"status": "ERROR", "error": message}, indent=2, sort_keys=True))
        write_manifest(run_folder, manifest)
        raise typer.Exit(code=_emit_error(output_format, out, message))

    if before_snapshot is None:
        message = "No previous run found for this model. Run scan first."
        manifest["status"] = "CLEAN"
        manifest["no_previous_snapshot"] = True
        write_text(run_folder, "snapshot.json", json.dumps({"status": "CLEAN", "message": message}, indent=2, sort_keys=True))
        write_text(run_folder, "report.txt", f"Status: CLEAN\n{message}")
        write_text(run_folder, "report.json", json.dumps({"status": "CLEAN", "message": message}, indent=2, sort_keys=True))
        write_manifest(run_folder, manifest)
        _emit_output(message, out)
        return

    manifest["before_snapshot_hash"] = before_snapshot.snapshot_hash
    manifest["after_snapshot_hash"] = after.snapshot.snapshot_hash

    diff_result = diff_snapshots(before_snapshot, after.snapshot)
    exposure_result = analyze_exposure(diff_result, after.graph)
    unknown_patterns = _merge_unknown_patterns(before_unknown_patterns, after.unknown_patterns)
    unresolved_refs = _merge_unresolved_refs(
        before_snapshot.unresolved_refs,
        after.snapshot.unresolved_refs,
    )

    status = _status_from_issues(unknown_patterns, unresolved_refs)
    report_json = format_report_json(
        diff_result=diff_result,
        exposure_result=exposure_result,
        coverage_data=coverage_data,
        run_id=run_folder.name,
        model_key=after.model_key,
        old_snapshot_hash=before_snapshot.snapshot_hash,
        new_snapshot_hash=after.snapshot.snapshot_hash,
        unknown_patterns=unknown_patterns,
        unresolved_refs=unresolved_refs,
    )
    report_text = format_pr_text(
        diff_result=diff_result,
        exposure_result=exposure_result,
        run_id=run_folder.name,
        model_key=after.model_key,
        old_snapshot_hash=before_snapshot.snapshot_hash,
        new_snapshot_hash=after.snapshot.snapshot_hash,
        coverage_lines=coverage_lines,
        coverage_data=coverage_data,
        unknown_patterns=unknown_patterns,
        unresolved_refs=unresolved_refs,
    )

    write_text(run_folder, "snapshot.json", json.dumps(asdict(after.snapshot), indent=2, sort_keys=True))
    write_text(run_folder, "report.json", report_json)
    write_text(run_folder, "report.txt", report_text)

    output = report_json if output_format == "json" else report_text
    _emit_output(output, out)

    manifest["status"] = status
    manifest["model_key"] = after.model_key
    manifest["unknown_pattern_objects"] = len(unknown_patterns)
    manifest["unresolved_ref_count"] = len(unresolved_refs)
    manifest["changed_objects"] = len(diff_result.changed_object_ids)
    write_manifest(run_folder, manifest)
    typer.echo(f"Saved: report.txt, report.json to {run_folder}")
    typer.echo("Also saved: snapshot.json, manifest.json")

    if strict and (unknown_patterns or unresolved_refs):
        manifest["status"] = "STRUCTURAL_ISSUES"
        manifest["strict_policy_failures"] = _strict_failures(unknown_patterns, unresolved_refs)
        write_manifest(run_folder, manifest)
        raise typer.Exit(code=2)


def _load_previous_snapshot(
    *,
    output_root: Path,
    project_root: Path,
    model_key: str,
) -> tuple[Any | None, list[dict[str, Any]]]:
    index_obj = load_index(output_root)
    entry = get_model_entry(index_obj, model_key)
    if not entry:
        return None, []
    run_path = str(entry.get("latest_run_path", ""))
    if not run_path:
        return None, []

    run_folder = Path(run_path)
    if not run_folder.is_absolute():
        run_folder = (project_root / run_folder).resolve()
    snapshot_path = run_folder / "snapshot.json"
    if not snapshot_path.exists():
        return None, []
    snapshot = load_snapshot(snapshot_path)
    return snapshot, list(snapshot.unknown_patterns)


def _emit_output(output: str, out: str | None) -> None:
    if out:
        Path(out).write_text(output, encoding="utf-8")
        typer.echo(f"Wrote output: {out}")
        return
    typer.echo(output)


def _emit_error(output_format: str, out: str | None, message: str) -> int:
    if output_format == "json":
        rendered = json.dumps({"status": "ERROR", "error": message}, indent=2, sort_keys=True)
    else:
        rendered = f"Status: ERROR\nExposure error: {message}"
    _emit_output(rendered, out)
    return 1


def _merge_unknown_patterns(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
) -> list[dict[str, object]]:
    merged: dict[str, set[str]] = {}
    for entry in before + after:
        object_id = str(entry.get("object_id", ""))
        patterns = entry.get("patterns", [])
        if not object_id or not isinstance(patterns, list):
            continue
        merged.setdefault(object_id, set()).update(str(pattern) for pattern in patterns)
    return [
        {"object_id": object_id, "patterns": sorted(patterns)}
        for object_id, patterns in sorted(merged.items())
        if patterns
    ]


def _merge_unresolved_refs(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
) -> list[dict[str, str]]:
    merged: set[tuple[str, str]] = set()
    for entry in before + after:
        object_id = str(entry.get("object_id", ""))
        ref = str(entry.get("ref", ""))
        if object_id and ref:
            merged.add((object_id, ref))
    return [
        {"object_id": object_id, "ref": ref}
        for object_id, ref in sorted(merged)
    ]


def _status_from_issues(
    unknown_patterns: list[dict[str, Any]],
    unresolved_refs: list[dict[str, str]],
) -> str:
    if unknown_patterns or unresolved_refs:
        return "STRUCTURAL_ISSUES"
    return "CLEAN"


def _strict_failures(
    unknown_patterns: list[dict[str, Any]],
    unresolved_refs: list[dict[str, str]],
) -> list[str]:
    failures: list[str] = []
    if unknown_patterns:
        failures.append(f"unknown_patterns:{len(unknown_patterns)}")
    if unresolved_refs:
        failures.append(f"unresolved_refs:{len(unresolved_refs)}")
    return failures
