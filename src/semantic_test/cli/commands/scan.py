"""Scan command."""

from __future__ import annotations

from dataclasses import asdict
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer

from semantic_test import __version__
from semantic_test.cli.commands._pipeline import build_model_artifacts
from semantic_test.core.io.index_manager import (
    load_index,
    save_index_atomic,
    upsert_model_entry,
)
from semantic_test.core.io.output_manager import (
    create_run_folder,
    get_output_root,
    write_manifest,
    write_text,
)
from semantic_test.core.model.coverage import coverage_report
from semantic_test.core.model.model_key import build_model_key, resolve_project_root
from semantic_test.core.parse.pbip_locator import discover_definition_folders

SCAN_SCHEMA_VERSION = 3


def scan_command(
    input_path: str = typer.Argument("."),
    output_format: str = typer.Option("both", "--format"),
    stdout_format: str = typer.Option("text", "--stdout"),
    outdir: str | None = typer.Option(None, "--outdir"),
    no_index: bool = typer.Option(False, "--no-index"),
    strict: bool = typer.Option(False, "--strict"),
    debug: bool = typer.Option(False, "--debug"),
    show_all: bool = typer.Option(False, "--show-all"),
) -> None:
    """Scan model artifacts."""
    if output_format not in {"text", "json", "both"}:
        raise typer.BadParameter("--format must be one of: text, json, both")
    if stdout_format not in {"text", "json", "none"}:
        raise typer.BadParameter("--stdout must be one of: text, json, none")

    now = datetime.now(timezone.utc)
    project_root = resolve_project_root(input_path)
    output_root = get_output_root(project_root, outdir_override=outdir)
    run_folder = create_run_folder(
        output_root=output_root,
        command="scan",
        model_key=Path(input_path).name or "model",
        snapshot_hash="pending",
        now=now,
    )

    discovery = _discover_models(input_path)
    manifest: dict[str, object] = {
        "version": "0.1",
        "command": "scan",
        "timestamp_utc": now.isoformat(),
        "input_path": input_path,
        "scan_input_path": input_path,
        "output_format": output_format,
        "stdout": stdout_format,
        "no_index": no_index,
        "strict": strict,
        "debug": debug,
        "show_all": show_all,
        "status": "RUNNING",
        "error": None,
        "snapshot_hash": None,
        "run_folder": str(run_folder),
        "models_detected_count": discovery["models_detected_count"],
        "models_detected": discovery["models_detected"],
    }

    coverage_lines, coverage_data = coverage_report()
    try:
        artifacts = build_model_artifacts(input_path)
    except (FileNotFoundError, ValueError) as error:
        message = str(error)
        manifest["status"] = "ERROR"
        manifest["error"] = message

        report_json_obj = {
            "schema_version": SCAN_SCHEMA_VERSION,
            "tool_version": __version__,
            "status": "ERROR",
            "definition_path": input_path,
            "model_key": "semanticmodel::unknown",
            "scan_input_path": input_path,
            "selected_model_key": None,
            "selected_model_definition_path": None,
            "models_detected_count": discovery["models_detected_count"],
            "models_detected": discovery["models_detected"],
            "summary": {},
            "issues": {
                "unresolved_references": [],
                "unsupported_reference_patterns": [],
            },
            "top_dependency_hubs": [],
            "error": message,
        }
        report_json = json.dumps(report_json_obj, indent=2, sort_keys=True)
        report_text = _error_report_text(message, discovery=discovery)
        write_text(run_folder, "snapshot.json", json.dumps({"status": "ERROR", "error": message}, indent=2, sort_keys=True))
        write_text(run_folder, "report.txt", report_text)
        write_text(run_folder, "report.json", report_json)
        write_manifest(run_folder, manifest)

        _emit_error(stdout_format, message)
        typer.echo(f"Saved reports to: {run_folder}")
        raise typer.Exit(code=1)

    unresolved_groups = _build_unresolved_issue_groups(objects=artifacts.objects)
    unsupported_groups = _build_unsupported_issue_groups(
        unknown_patterns=artifacts.unknown_patterns,
        objects=artifacts.objects,
    )
    unresolved_count = sum(len(group["items"]) for group in unresolved_groups)
    unsupported_count = sum(len(group["items"]) for group in unsupported_groups)
    status = _scan_status(unresolved_count, unsupported_count)

    calc_group_count = sum(
        1 for item in artifacts.calc_group_inventory.values() if item.get("type") == "CalcGroup"
    )
    calc_item_count = sum(
        1 for item in artifacts.calc_group_inventory.values() if item.get("type") == "CalcItem"
    )

    resolution_assumption_count, resolution_assumption_traces = _resolution_assumptions(artifacts.objects)
    ambiguous_reference_count = _ambiguous_reference_count(artifacts.objects, unresolved_groups)

    strict_fail_reasons = {
        "unresolved_references": unresolved_count,
        "unsupported_reference_patterns": unsupported_count,
        "parser_coverage_gaps_treated_as_errors": 0,
    }

    summary = {
        "objects": len(artifacts.objects),
        "tables": len(artifacts.table_inventory),
        "measures": len(artifacts.measure_inventory),
        "columns": len(artifacts.column_inventory),
        "relationships": len(artifacts.relationship_inventory),
        "calc_groups": calc_group_count,
        "calc_items": calc_item_count,
        "field_params": len(artifacts.field_param_inventory),
        "graph_nodes": artifacts.graph.node_count,
        "graph_edges": artifacts.graph.edge_count,
        "unresolved_references": unresolved_count,
        "unsupported_reference_patterns": unsupported_count,
        "resolution_assumptions_applied": resolution_assumption_count,
        "ambiguous_references": ambiguous_reference_count,
    }

    top_hubs = _top_dependency_hubs(artifacts.objects, artifacts.graph.reverse, top_n=10)
    report_json_obj: dict[str, Any] = {
        "schema_version": SCAN_SCHEMA_VERSION,
        "tool_version": __version__,
        "status": status,
        "definition_path": artifacts.definition_folder,
        "model_key": artifacts.model_key,
        "scan_input_path": input_path,
        "selected_model_key": artifacts.model_key,
        "selected_model_definition_path": artifacts.selected_model_definition_path,
        "models_detected_count": artifacts.models_detected_count,
        "models_detected": artifacts.models_detected,
        "summary": summary,
        "issues": {
            "unresolved_references": unresolved_groups,
            "unsupported_reference_patterns": unsupported_groups,
        },
        "strict_fail_reasons": strict_fail_reasons,
        "top_dependency_hubs": top_hubs,
    }
    if debug:
        report_json_obj["debug"] = {
            "coverage_summary": coverage_data.get("summary", {}),
            "coverage_matrix": coverage_data.get("items", []),
            "internal_notes": coverage_lines,
            "raw_patterns": artifacts.unknown_patterns,
            "raw_unresolved_refs": artifacts.snapshot.unresolved_refs,
            "resolution_traces": resolution_assumption_traces,
        }

    report_text = _render_text(
        definition_path=artifacts.definition_folder,
        model_key=artifacts.model_key,
        status=status,
        summary=summary,
        unresolved_groups=unresolved_groups,
        unsupported_groups=unsupported_groups,
        top_hubs=top_hubs,
        strict=strict,
        strict_fail_reasons=strict_fail_reasons,
        debug=debug,
        show_all=show_all,
        coverage_lines=coverage_lines,
        scan_input_path=input_path,
        selected_model_definition_path=artifacts.selected_model_definition_path,
        models_detected_count=artifacts.models_detected_count,
        resolution_assumption_traces=resolution_assumption_traces,
    )
    report_json = json.dumps(report_json_obj, indent=2, sort_keys=True)
    snapshot_json = json.dumps(asdict(artifacts.snapshot), indent=2, sort_keys=True)

    write_text(run_folder, "snapshot.json", snapshot_json)
    write_text(run_folder, "report.txt", report_text)
    write_text(run_folder, "report.json", report_json)

    if stdout_format == "text":
        typer.echo(report_text)
    elif stdout_format == "json":
        typer.echo(report_json)

    run_path = _display_path(run_folder, output_root.parent)
    if not no_index:
        index_obj = load_index(output_root)
        upsert_model_entry(
            index_obj,
            model_key=artifacts.model_key,
            definition_path=artifacts.definition_path,
            latest_snapshot_hash=artifacts.snapshot.snapshot_hash,
            latest_run_id=run_folder.name,
            latest_run_path=run_path,
        )
        save_index_atomic(output_root, index_obj)

    manifest["status"] = status
    manifest["snapshot_hash"] = artifacts.snapshot.snapshot_hash
    manifest["unsupported_reference_pattern_count"] = unsupported_count
    manifest["unresolved_ref_count"] = unresolved_count
    manifest["model_key"] = artifacts.model_key
    manifest["selected_model_definition_path"] = artifacts.selected_model_definition_path
    write_manifest(run_folder, manifest)

    typer.echo(f"Saved reports to: {run_folder}")

    if strict and status == "STRUCTURAL_ISSUES":
        manifest["strict_policy_failures"] = [
            f"unresolved_references:{unresolved_count}",
            f"unsupported_reference_patterns:{unsupported_count}",
            "parser_coverage_gaps_treated_as_errors:0",
        ]
        write_manifest(run_folder, manifest)
        raise typer.Exit(code=2)


def _render_text(
    *,
    definition_path: str,
    model_key: str,
    status: str,
    summary: dict[str, int],
    unresolved_groups: list[dict[str, Any]],
    unsupported_groups: list[dict[str, Any]],
    top_hubs: list[dict[str, Any]],
    strict: bool,
    strict_fail_reasons: dict[str, int],
    debug: bool,
    show_all: bool,
    coverage_lines: list[str],
    scan_input_path: str,
    selected_model_definition_path: str,
    models_detected_count: int,
    resolution_assumption_traces: list[str],
) -> str:
    lines: list[str] = [
        f"semantic-test Scan Report (v{__version__})",
        f"Definition: {definition_path}",
    ]
    if len(model_key) <= 80:
        lines.append(f"Model Key: {model_key}")

    lines.extend(
        [
            "",
            f"Status: {status}",
            (
                "Objects: "
                f"{summary['objects']} | Tables: {summary['tables']} | Measures: {summary['measures']} | "
                f"Columns: {summary['columns']} | Relationships: {summary['relationships']}"
            ),
            f"Graph: Nodes: {summary['graph_nodes']} | Edges: {summary['graph_edges']}",
            f"Unresolved References: {summary['unresolved_references']}",
            f"Unsupported Reference Patterns: {summary['unsupported_reference_patterns']}",
            f"Resolution Assumptions Applied: {summary['resolution_assumptions_applied']}",
            f"Ambiguous References: {summary['ambiguous_references']}",
        ]
    )

    if strict:
        lines.append(f"Strict Mode: {'PASS' if status == 'CLEAN' else 'FAIL'}")
    elif status == "STRUCTURAL_ISSUES":
        lines.append("Strict Mode: would FAIL (run with --strict to gate CI)")

    lines.append(
        "Strict fail reasons: "
        f"{strict_fail_reasons['unresolved_references']} unresolved refs, "
        f"{strict_fail_reasons['unsupported_reference_patterns']} unsupported patterns, "
        f"{strict_fail_reasons['parser_coverage_gaps_treated_as_errors']} parser coverage gaps treated as errors"
    )

    if summary["unresolved_references"] > 0 or summary["unsupported_reference_patterns"] > 0:
        lines.extend(["", "Issues", "------"])
        lines.extend(
            _render_issue_section(
                title="Unresolved References",
                groups=unresolved_groups,
                item_label="missing",
                show_all=(show_all or debug),
            )
        )
        lines.extend(
            _render_issue_section(
                title="Unsupported Reference Patterns",
                groups=unsupported_groups,
                item_label="unsupported",
                show_all=(show_all or debug),
            )
        )

    lines.extend(["", "Top Dependency Hubs", "-------------------"])
    if not top_hubs:
        lines.append("none")
    else:
        for hub in top_hubs:
            lines.append(f"{hub['measure_id']} -> {hub['downstream_count']} downstream objects")

    strict_target = selected_model_definition_path
    debug_target = selected_model_definition_path

    lines.extend(["", "Next Actions", "------------"])
    if status == "STRUCTURAL_ISSUES":
        lines.append(f"- Re-run this specific model: semantic-test scan {strict_target} --strict")
        if models_detected_count == 1 and scan_input_path != selected_model_definition_path:
            lines.append(f"- Re-run using your original input path: semantic-test scan {scan_input_path} --strict")
        lines.append(f"- For parser/coverage diagnostics: semantic-test scan {debug_target} --debug")
    else:
        lines.append(f"- Model is structurally clean. Gate CI with: semantic-test scan {strict_target} --strict")

    if debug:
        lines.extend(["", "Details", "-------", "Coverage Matrix"])
        lines.extend(coverage_lines)
        if resolution_assumption_traces:
            lines.extend(["", "Resolution Trace"])
            for trace in resolution_assumption_traces:
                lines.append(f"- {trace}")
        lines.extend(["", "Full Issues (Debug)"])
        lines.extend(
            _render_issue_section(
                title="Unresolved References",
                groups=unresolved_groups,
                item_label="missing",
                show_all=True,
            )
        )
        lines.extend(
            _render_issue_section(
                title="Unsupported Reference Patterns",
                groups=unsupported_groups,
                item_label="unsupported",
                show_all=True,
            )
        )

    return "\n".join(lines)


def _render_issue_section(
    *,
    title: str,
    groups: list[dict[str, Any]],
    item_label: str,
    show_all: bool,
) -> list[str]:
    lines: list[str] = [title]
    if not groups:
        lines.append("none")
        return lines

    limit = len(groups) if show_all else 10
    displayed = groups[:limit]
    for group in displayed:
        lines.append(f"{group['source_object_name']} ({group['source_object_type']})")
        snippet = group.get("expression_snippet")
        if snippet:
            lines.append(f"  expression: {snippet}")
        for item in group["items"]:
            lines.append(
                "  - "
                f"{item_label}: {item['target']} | "
                f"reason: {item.get('reason', 'n/a')} | "
                f"severity: {item.get('severity', 'ERROR')}"
            )
    remaining = len(groups) - len(displayed)
    if remaining > 0:
        lines.append(f"(+{remaining} more; re-run with --show-all)")
    return lines


def _build_unresolved_issue_groups(
    *,
    objects: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for source in sorted(objects.keys()):
        metadata = objects[source]
        explicit_items = metadata.get("unresolved_references", [])
        items: list[dict[str, Any]] = []
        if isinstance(explicit_items, list):
            for raw in explicit_items:
                if not isinstance(raw, dict):
                    continue
                target = str(raw.get("ref", "")).strip()
                if not target:
                    continue
                items.append(
                    {
                        "kind": "missing",
                        "target": target,
                        "reason": str(raw.get("reason", "Missing reference")),
                        "severity": str(raw.get("severity", "ERROR")),
                    }
                )

        if not items:
            patterns = metadata.get("unknown_patterns", [])
            if isinstance(patterns, list):
                for pattern in patterns:
                    text = str(pattern).strip()
                    if text.startswith("unresolved_measure:") or text.startswith("unresolved_column:"):
                        items.append(
                            {
                                "kind": "missing",
                                "target": text.split(":", maxsplit=1)[1],
                                "reason": "Reference could not be resolved.",
                                "severity": "ERROR",
                            }
                        )
                    if text.startswith("ambiguous_column:"):
                        items.append(
                            {
                                "kind": "ambiguous",
                                "target": text.split(":", maxsplit=1)[1],
                                "reason": "Ambiguous reference resolved to multiple candidate columns.",
                                "severity": "ERROR",
                            }
                        )

        if not items:
            continue

        output.append(
            {
                "source_object_id": source,
                "source_object_name": _display_object_id(source),
                "source_object_type": _object_kind(metadata),
                "expression_snippet": _expression_snippet(metadata),
                "items": sorted(items, key=lambda item: item["target"]),
            }
        )
    return output


def _build_unsupported_issue_groups(
    *,
    unknown_patterns: list[dict[str, Any]],
    objects: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, set[str]] = {}
    for entry in unknown_patterns:
        source = str(entry.get("object_id", "")).strip()
        patterns = entry.get("patterns", [])
        if not source or not isinstance(patterns, list):
            continue
        for pattern in patterns:
            pattern_text = str(pattern).strip()
            if not pattern_text:
                continue
            if pattern_text.startswith("unresolved_") or pattern_text.startswith("ambiguous_"):
                continue
            grouped.setdefault(source, set()).add(pattern_text)

    output: list[dict[str, Any]] = []
    for source in sorted(grouped.keys()):
        metadata = objects.get(source, {})
        items = [
            {
                "kind": "unsupported",
                "target": pattern,
                "reason": "Coverage gap in parser/extractor.",
                "severity": "WARN",
            }
            for pattern in sorted(grouped[source])
        ]
        output.append(
            {
                "source_object_id": source,
                "source_object_name": _display_object_id(source),
                "source_object_type": _object_kind(metadata),
                "expression_snippet": _expression_snippet(metadata),
                "items": items,
            }
        )
    return output


def _object_kind(metadata: dict[str, Any]) -> str:
    object_type = str(metadata.get("type", "Unknown")).strip()
    expression = _expression_text(metadata)
    if object_type == "Column" and expression:
        return "Calculated Column"
    if object_type == "Measure":
        return "Measure"
    if object_type == "Relationship":
        return "Relationship"
    if object_type == "CalcItem":
        return "Calculation Item"
    if object_type == "CalcGroup":
        return "Calculation Group"
    return object_type or "Unknown"


def _expression_text(metadata: dict[str, Any]) -> str:
    expression = str(metadata.get("expression") or metadata.get("raw_expression") or "").strip()
    return expression


def _expression_snippet(metadata: dict[str, Any], limit: int = 120) -> str | None:
    expression = _expression_text(metadata)
    if not expression:
        return None
    normalized = " ".join(expression.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def _resolution_assumptions(
    objects: dict[str, dict[str, Any]],
) -> tuple[int, list[str]]:
    traces: list[str] = []
    for metadata in objects.values():
        assumptions = metadata.get("resolution_assumptions", [])
        if not isinstance(assumptions, list):
            continue
        traces.extend(str(item) for item in assumptions if str(item).strip())
    return len(traces), sorted(traces)


def _ambiguous_reference_count(
    objects: dict[str, dict[str, Any]],
    unresolved_groups: list[dict[str, Any]],
) -> int:
    explicit = 0
    for metadata in objects.values():
        explicit += int(metadata.get("ambiguous_reference_count", 0) or 0)
    if explicit > 0:
        return explicit

    inferred = 0
    for group in unresolved_groups:
        for item in group.get("items", []):
            if item.get("kind") == "ambiguous" or "Ambiguous" in str(item.get("reason", "")):
                inferred += 1
    return inferred


def _discover_models(input_path: str) -> dict[str, Any]:
    try:
        project_root = resolve_project_root(input_path)
        definitions = discover_definition_folders(input_path)
    except (FileNotFoundError, ValueError):
        return {"models_detected_count": 0, "models_detected": []}

    models: list[dict[str, str]] = []
    for definition in definitions:
        models.append(
            {
                "model_key": build_model_key(str(definition), project_root=project_root),
                "definition_path": str(definition),
            }
        )
    models.sort(key=lambda item: item["definition_path"])
    return {"models_detected_count": len(models), "models_detected": models}


def _scan_status(unresolved_count: int, unsupported_count: int) -> str:
    if unresolved_count > 0 or unsupported_count > 0:
        return "STRUCTURAL_ISSUES"
    return "CLEAN"


def _top_dependency_hubs(
    objects: dict[str, dict[str, Any]],
    reverse_adj: dict[str, set[str]],
    *,
    top_n: int,
) -> list[dict[str, Any]]:
    hubs: list[dict[str, Any]] = []
    for object_id, metadata in objects.items():
        if str(metadata.get("type", "")) != "Measure":
            continue
        hubs.append(
            {
                "measure_id": object_id,
                "downstream_count": len(reverse_adj.get(object_id, set())),
            }
        )
    hubs.sort(key=lambda row: (-int(row["downstream_count"]), str(row["measure_id"])))
    return hubs[: max(top_n, 0)]


def _display_object_id(object_id: str) -> str:
    if object_id.startswith("Measure:"):
        body = object_id.split(":", maxsplit=1)[1]
        if "." in body:
            table_name, measure_name = body.split(".", maxsplit=1)
            return f"{table_name}[{measure_name}]"
    if object_id.startswith("Column:"):
        body = object_id.split(":", maxsplit=1)[1]
        if "." in body:
            table_name, column_name = body.split(".", maxsplit=1)
            return f"{table_name}[{column_name}]"
    return object_id


def _error_report_text(message: str, discovery: dict[str, Any] | None = None) -> str:
    lines = [
        f"semantic-test Scan Report (v{__version__})",
        "Status: ERROR",
        f"Error: {message}",
    ]
    models = (discovery or {}).get("models_detected", [])
    if isinstance(models, list) and len(models) > 1:
        lines.extend(["", "Next Actions", "------------"])
        first = models[0]
        lines.append(
            "Multiple models were detected. Re-run a specific model, for example: "
            f"semantic-test scan {first.get('definition_path', '<definition_path>')} --strict"
        )
    return "\n".join(lines)


def _emit_error(stdout_format: str, message: str) -> None:
    if stdout_format == "json":
        typer.echo(
            json.dumps(
                {
                    "schema_version": SCAN_SCHEMA_VERSION,
                    "tool_version": __version__,
                    "status": "ERROR",
                    "error": message,
                },
                indent=2,
                sort_keys=True,
            )
        )
    elif stdout_format == "text":
        typer.echo(f"Status: ERROR\nError: {message}")


def _display_path(path: Path, base: Path) -> str:
    try:
        relative = path.resolve().relative_to(base.resolve())
        return relative.as_posix()
    except ValueError:
        return str(path.resolve())
