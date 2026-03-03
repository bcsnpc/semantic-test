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
from semantic_test.core.model.model_key import resolve_project_root

SCAN_SCHEMA_VERSION = 2


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
    manifest: dict[str, object] = {
        "version": "0.1",
        "command": "scan",
        "timestamp_utc": now.isoformat(),
        "input_path": input_path,
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
            "summary": {},
            "issues": {
                "unresolved_references": [],
                "unsupported_reference_patterns": [],
            },
            "top_dependency_hubs": [],
            "error": message,
        }
        report_json = json.dumps(report_json_obj, indent=2, sort_keys=True)
        report_text = _error_report_text(message)
        write_text(run_folder, "snapshot.json", json.dumps({"status": "ERROR", "error": message}, indent=2, sort_keys=True))
        write_text(run_folder, "report.txt", report_text)
        write_text(run_folder, "report.json", report_json)
        write_manifest(run_folder, manifest)

        _emit_error(stdout_format, message)
        typer.echo(f"Saved reports to: {run_folder}")
        raise typer.Exit(code=1)

    unresolved_groups = _build_unresolved_issue_groups(
        unresolved_refs=artifacts.snapshot.unresolved_refs,
        objects=artifacts.objects,
    )
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
    }

    top_hubs = _top_dependency_hubs(artifacts.objects, artifacts.graph.reverse, top_n=10)
    report_json_obj: dict[str, Any] = {
        "schema_version": SCAN_SCHEMA_VERSION,
        "tool_version": __version__,
        "status": status,
        "definition_path": artifacts.definition_folder,
        "model_key": artifacts.model_key,
        "summary": summary,
        "issues": {
            "unresolved_references": unresolved_groups,
            "unsupported_reference_patterns": unsupported_groups,
        },
        "top_dependency_hubs": top_hubs,
    }
    if debug:
        report_json_obj["debug"] = {
            "coverage_summary": coverage_data.get("summary", {}),
            "coverage_matrix": coverage_data.get("items", []),
            "internal_notes": coverage_lines,
            "raw_patterns": artifacts.unknown_patterns,
            "raw_unresolved_refs": artifacts.snapshot.unresolved_refs,
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
        debug=debug,
        show_all=show_all,
        coverage_lines=coverage_lines,
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
    write_manifest(run_folder, manifest)

    typer.echo(f"Saved reports to: {run_folder}")

    if strict and status == "STRUCTURAL_ISSUES":
        manifest["strict_policy_failures"] = [
            f"unresolved_references:{unresolved_count}",
            f"unsupported_reference_patterns:{unsupported_count}",
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
    debug: bool,
    show_all: bool,
    coverage_lines: list[str],
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
        ]
    )

    if strict:
        lines.append(f"Strict Mode: {'PASS' if status == 'CLEAN' else 'FAIL'}")
    elif status == "STRUCTURAL_ISSUES":
        lines.append("Strict Mode: would FAIL (run with --strict to gate CI)")

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

    lines.extend(["", "Next Actions", "------------"])
    if status == "STRUCTURAL_ISSUES":
        lines.append("- Fix unresolved references and re-run: semantic-test scan . --strict")
        lines.append("- For parser/coverage diagnostics: semantic-test scan . --debug")
    else:
        lines.append("- Model is structurally clean. You can gate CI with: semantic-test scan . --strict")

    if debug:
        lines.extend(["", "Details", "-------", "Coverage Matrix"])
        lines.extend(coverage_lines)
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
        lines.append(_display_object_id(group["source_object_id"]))
        for item in group["items"]:
            lines.append(f"  - {item_label}: {item['target']}")
    remaining = len(groups) - len(displayed)
    if remaining > 0:
        lines.append(f"(+{remaining} more; re-run with --show-all)")
    return lines


def _build_unresolved_issue_groups(
    *,
    unresolved_refs: list[dict[str, Any]],
    objects: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for entry in unresolved_refs:
        source = str(entry.get("object_id", "")).strip()
        ref = str(entry.get("ref", "")).strip()
        if not source or not ref:
            continue
        target = _extract_missing_target(ref)
        grouped.setdefault(source, []).append({"kind": "missing", "target": target})

    output: list[dict[str, Any]] = []
    for source in sorted(grouped.keys()):
        items = sorted(grouped[source], key=lambda item: item["target"])
        output.append(
            {
                "source_object_id": source,
                "source_object_type": _object_type_from_id(source, objects),
                "items": items,
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
            if pattern_text.startswith("unresolved_measure:"):
                continue
            grouped.setdefault(source, set()).add(pattern_text)

    output: list[dict[str, Any]] = []
    for source in sorted(grouped.keys()):
        items = [
            {"kind": "unsupported", "target": pattern}
            for pattern in sorted(grouped[source])
        ]
        output.append(
            {
                "source_object_id": source,
                "source_object_type": _object_type_from_id(source, objects),
                "items": items,
            }
        )
    return output


def _extract_missing_target(ref: str) -> str:
    if ref.startswith("unresolved_measure:"):
        return ref.split(":", maxsplit=1)[1]
    return ref


def _object_type_from_id(object_id: str, objects: dict[str, dict[str, Any]]) -> str:
    metadata = objects.get(object_id, {})
    type_from_metadata = str(metadata.get("type", "")).strip()
    if type_from_metadata:
        return type_from_metadata
    if ":" not in object_id:
        return "Unknown"
    prefix = object_id.split(":", maxsplit=1)[0]
    return prefix or "Unknown"


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


def _error_report_text(message: str) -> str:
    return "\n".join(
        [
            f"semantic-test Scan Report (v{__version__})",
            "Status: ERROR",
            f"Error: {message}",
        ]
    )


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
