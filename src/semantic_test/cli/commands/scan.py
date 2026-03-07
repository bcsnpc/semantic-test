"""Scan command."""

from __future__ import annotations

from dataclasses import asdict
import json
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any

import typer

from semantic_test import __version__
from semantic_test.cli.commands._pipeline import (
    build_model_artifacts,
    build_model_artifacts_from_desktop,
)
from semantic_test.core.live.desktop import (
    DesktopInstance,
    discover_pbi_desktop_instances,
    parse_desktop_input,
)
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

    # --- Desktop mode: dispatch before any file-system operations ---
    if input_path.startswith("desktop"):
        _run_desktop_scan(
            input_path=input_path,
            output_format=output_format,
            stdout_format=stdout_format,
            outdir=outdir,
            no_index=no_index,
            strict=strict,
            debug=debug,
            show_all=show_all,
        )
        return

    now = datetime.now(timezone.utc)
    invocation_prefix = _invocation_prefix()
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
        report_text = _error_report_text(message, discovery=discovery, invocation_prefix=invocation_prefix)
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

    visual_count = len(artifacts.visual_inventory)
    visual_edge_count = sum(
        len(meta.get("dependencies", set()))
        for meta in artifacts.visual_inventory.values()
    )
    visual_page_count = len({
        meta.get("page_id") for meta in artifacts.visual_inventory.values()
    })

    summary = {
        "objects": len(artifacts.objects),
        "tables": len(artifacts.table_inventory),
        "measures": len(artifacts.measure_inventory),
        "columns": len(artifacts.column_inventory),
        "relationships": len(artifacts.relationship_inventory),
        "calc_groups": calc_group_count,
        "calc_items": calc_item_count,
        "field_params": len(artifacts.field_param_inventory),
        "visuals": visual_count,
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
        "visual_lineage": artifacts.diagnostics.get("visual_lineage", {}),
    }
    if debug:
        report_json_obj["debug"] = {
            "coverage_summary": coverage_data.get("summary", {}),
            "coverage_matrix": coverage_data.get("items", []),
            "internal_notes": coverage_lines,
            "raw_patterns": artifacts.unknown_patterns,
            "raw_unresolved_refs": artifacts.snapshot.unresolved_refs,
            "resolution_traces": resolution_assumption_traces,
            "parity_diagnostics": artifacts.diagnostics,
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
        invocation_prefix=invocation_prefix,
        semantic_cli_available=_semantic_cli_available(),
        visual_count=visual_count,
        visual_page_count=visual_page_count,
        visual_edge_count=visual_edge_count,
        visual_lineage=artifacts.diagnostics.get("visual_lineage", {}),
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


def _run_desktop_scan(
    *,
    input_path: str,
    output_format: str,
    stdout_format: str,
    outdir: str | None,
    no_index: bool,
    strict: bool,
    debug: bool,
    show_all: bool,
) -> None:
    """Handle ``semantic-test scan desktop[:<port>]`` mode."""
    # Resolve port
    try:
        explicit_port = parse_desktop_input(input_path)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if explicit_port is None:
        # Auto-discover
        instances = discover_pbi_desktop_instances()
        if not instances:
            typer.echo(
                "Error: No Power BI Desktop instance found.\n"
                "Open a .pbix file in Power BI Desktop and try again.",
                err=True,
            )
            raise typer.Exit(code=1)
        if len(instances) > 1:
            typer.echo(
                f"Error: {len(instances)} Power BI Desktop instances are running.\n"
                "Specify which one to scan:\n",
                err=True,
            )
            for inst in instances:
                label = f"  # {inst.catalog_name}" if inst.catalog_name else ""
                typer.echo(f"  semantic-test scan desktop:{inst.port}{label}", err=True)
            raise typer.Exit(code=1)
        port = instances[0].port
        workspace_dir = str(instances[0].workspace_dir)
        label = instances[0].catalog_name or f"port {port}"
        typer.echo(f"Found Power BI Desktop: {label}.")
    else:
        port = explicit_port
        workspace_dir = None
        for instance in discover_pbi_desktop_instances():
            if instance.port == port:
                workspace_dir = str(instance.workspace_dir)
                break

    now = datetime.now(timezone.utc)
    invocation_prefix = _invocation_prefix()

    # Use current working directory as output root for desktop scans
    project_root = Path.cwd()
    output_root = get_output_root(project_root, outdir_override=outdir)

    run_folder = create_run_folder(
        output_root=output_root,
        command="scan",
        model_key=f"desktop-{port}",
        snapshot_hash="pending",
        now=now,
    )

    coverage_lines, coverage_data = coverage_report()

    try:
        artifacts = build_model_artifacts_from_desktop(port, workspace_dir=workspace_dir)
    except RuntimeError as error:
        message = str(error)
        typer.echo(f"Error: {message}", err=True)
        write_text(run_folder, "report.txt", f"Error: {message}")
        write_manifest(run_folder, {"status": "ERROR", "error": message, "command": "scan", "timestamp_utc": now.isoformat()})
        raise typer.Exit(code=1) from error

    # Reuse the standard scan render path — compute all the same locals
    unresolved_groups = _build_unresolved_issue_groups(objects=artifacts.objects)
    unsupported_groups = _build_unsupported_issue_groups(
        unknown_patterns=artifacts.unknown_patterns,
        objects=artifacts.objects,
    )
    unresolved_count = sum(len(g["items"]) for g in unresolved_groups)
    unsupported_count = sum(len(g["items"]) for g in unsupported_groups)
    status = _scan_status(unresolved_count, unsupported_count)

    calc_group_count = sum(1 for item in artifacts.calc_group_inventory.values() if item.get("type") == "CalcGroup")
    calc_item_count = sum(1 for item in artifacts.calc_group_inventory.values() if item.get("type") == "CalcItem")
    resolution_assumption_count, resolution_assumption_traces = _resolution_assumptions(artifacts.objects)
    ambiguous_reference_count = _ambiguous_reference_count(artifacts.objects, unresolved_groups)

    visual_count = len(artifacts.visual_inventory)
    visual_edge_count = sum(len(m.get("dependencies", set())) for m in artifacts.visual_inventory.values())
    visual_page_count = len({m.get("page_id") for m in artifacts.visual_inventory.values()})

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
        "visuals": visual_count,
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
        "source": "desktop",
        "definition_path": artifacts.definition_folder,
        "model_key": artifacts.model_key,
        "scan_input_path": input_path,
        "selected_model_key": artifacts.model_key,
        "selected_model_definition_path": artifacts.selected_model_definition_path,
        "models_detected_count": 1,
        "models_detected": artifacts.models_detected,
        "summary": summary,
        "issues": {
            "unresolved_references": unresolved_groups,
            "unsupported_reference_patterns": unsupported_groups,
        },
        "strict_fail_reasons": strict_fail_reasons,
        "top_dependency_hubs": top_hubs,
        "visual_lineage": artifacts.diagnostics.get("visual_lineage", {}),
    }
    if debug:
        parity_diagnostics = dict(artifacts.diagnostics)
        parity_diagnostics["semantic_parity_diff"] = _build_desktop_semantic_parity_diff(
            artifacts,
        )
        report_json_obj["debug"] = {
            "coverage_summary": coverage_data.get("summary", {}),
            "coverage_matrix": coverage_data.get("items", []),
            "internal_notes": coverage_lines,
            "raw_patterns": artifacts.unknown_patterns,
            "raw_unresolved_refs": artifacts.snapshot.unresolved_refs,
            "resolution_traces": resolution_assumption_traces,
            "parity_diagnostics": parity_diagnostics,
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
        models_detected_count=1,
        resolution_assumption_traces=resolution_assumption_traces,
        invocation_prefix=invocation_prefix,
        semantic_cli_available=_semantic_cli_available(),
        visual_count=visual_count,
        visual_page_count=visual_page_count,
        visual_edge_count=visual_edge_count,
        visual_lineage=artifacts.diagnostics.get("visual_lineage", {}),
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

    manifest: dict[str, object] = {
        "version": "0.1",
        "command": "scan",
        "source": "desktop",
        "timestamp_utc": now.isoformat(),
        "input_path": input_path,
        "port": port,
        "status": status,
        "snapshot_hash": artifacts.snapshot.snapshot_hash,
        "model_key": artifacts.model_key,
        "run_folder": str(run_folder),
    }
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
    strict_fail_reasons: dict[str, int],
    debug: bool,
    show_all: bool,
    coverage_lines: list[str],
    scan_input_path: str,
    selected_model_definition_path: str,
    models_detected_count: int,
    resolution_assumption_traces: list[str],
    invocation_prefix: str,
    semantic_cli_available: bool,
    visual_count: int = 0,
    visual_page_count: int = 0,
    visual_edge_count: int = 0,
    visual_lineage: dict[str, Any] | None = None,
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
                debug=debug,
            )
        )
        lines.extend(
            _render_issue_section(
                title="Unsupported Reference Patterns",
                groups=unsupported_groups,
                item_label="unsupported",
                show_all=(show_all or debug),
                debug=debug,
            )
        )

    if visual_count > 0:
        lines.extend([
            "",
            "Report Visuals",
            "--------------",
            f"Pages: {visual_page_count} | Visuals: {visual_count} | Visual-field edges: {visual_edge_count}",
        ])
    else:
        lineage = visual_lineage or {}
        if str(lineage.get("status", "")) == "unavailable":
            reason = str(lineage.get("reason", "")).strip() or "visual_artifacts_unavailable"
            lines.extend([
                "",
                "Report Visuals",
                "--------------",
                f"Unavailable in current desktop session: {reason}",
                "Tip: Use PBIP (.Report/definition) scan for full visual lineage when desktop artifacts are not accessible.",
            ])

    lines.extend(["", "Top Dependency Hubs", "-------------------"])
    if not top_hubs:
        lines.append("none")
    else:
        for hub in top_hubs:
            lines.append(f"{hub['measure_id']} -> {hub['downstream_count']} downstream objects")

    strict_target = selected_model_definition_path
    debug_target = selected_model_definition_path
    strict_cmd = _scan_command(invocation_prefix, strict_target, "--strict")
    debug_cmd = _scan_command(invocation_prefix, debug_target, "--debug")

    lines.extend(["", "Next Actions", "------------"])
    if status == "STRUCTURAL_ISSUES":
        lines.append(f"- Re-run this specific model: {strict_cmd}")
        if models_detected_count == 1 and scan_input_path != selected_model_definition_path:
            lines.append(
                f"- Re-run using your original input path: "
                f"{_scan_command(invocation_prefix, scan_input_path, '--strict')}"
            )
        lines.append(f"- For parser/coverage diagnostics: {debug_cmd}")
        if invocation_prefix != "semantic-test":
            lines.append(
                f"- If CLI entrypoint is installed: "
                f"{_scan_command('semantic-test', strict_target, '--strict')}"
            )
        if not semantic_cli_available:
            lines.append("- Install CLI entrypoint (dev): pip install -e .")
    else:
        lines.append(f"- Model is structurally clean. Gate CI with: {strict_cmd}")
        if invocation_prefix != "semantic-test":
            lines.append(
                f"- If CLI entrypoint is installed: "
                f"{_scan_command('semantic-test', strict_target, '--strict')}"
            )
        if not semantic_cli_available:
            lines.append("- Install CLI entrypoint (dev): pip install -e .")

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
                debug=True,
            )
        )
        lines.extend(
            _render_issue_section(
                title="Unsupported Reference Patterns",
                groups=unsupported_groups,
                item_label="unsupported",
                show_all=True,
                debug=True,
            )
        )

    return "\n".join(lines)


def _render_issue_section(
    *,
    title: str,
    groups: list[dict[str, Any]],
    item_label: str,
    show_all: bool,
    debug: bool,
) -> list[str]:
    lines: list[str] = [title]
    if not groups:
        lines.append("none")
        return lines

    limit = len(groups) if show_all else 10
    displayed = groups[:limit]
    for group in displayed:
        lines.append(f"{group['source_object_name']} ({group['source_object_type']})")
        if debug:
            lines.append(f"  object_id: {group.get('source_object_id', 'unknown')}")
            source_file = group.get("source_file_path")
            if source_file:
                lines.append(f"  source_file: {source_file}")
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
            lines.append(
                "    "
                f"expected_type: {item.get('expected_type', 'unknown')} | "
                f"expected_scope: {item.get('expected_scope', 'unknown')} | "
                f"likely_cause: {item.get('likely_cause', 'unknown')}"
            )
            lines.append(f"    action: {item.get('action', 'MANUAL_REVIEW')}")
            if item.get("best_guess") is not None:
                lines.append(
                    "    "
                    f"best_guess: {item.get('best_guess')} "
                    f"(score: {item.get('best_guess_score')})"
                )
                if item.get("why_best_guess"):
                    lines.append(f"    why_best_guess: {item.get('why_best_guess')}")
            lines.append(f"    referrers_count: {item.get('referrers_count', 0)}")
            suggestions = item.get("did_you_mean")
            if isinstance(suggestions, list) and suggestions:
                lines.append(f"    did_you_mean: {suggestions}")
            ranked = item.get("did_you_mean_top3_ranked") or item.get("did_you_mean_ranked")
            if isinstance(ranked, list) and ranked:
                top_ranked = []
                for candidate in ranked[:3]:
                    if not isinstance(candidate, dict):
                        continue
                    top_ranked.append(
                        f"({candidate.get('score', 0)}) {candidate.get('candidate', '')}"
                    )
                if top_ranked:
                    lines.append(f"    did_you_mean_top3: {top_ranked}")
        for idx, option in enumerate(group.get("suggested_fix_options", []), start=1):
            expr = str(option.get("expression", "")).strip()
            if not expr:
                continue
            score = int(option.get("combined_score", 0))
            lines.append(f"  Suggested fix (option {idx}, score {score}): {expr}")
    remaining = len(groups) - len(displayed)
    if remaining > 0:
        lines.append(f"(+{remaining} more; re-run with --show-all)")
    return lines


def _build_unresolved_issue_groups(
    *,
    objects: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    referrers_count_map = _build_referrers_count_map(objects)
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
                        "did_you_mean": list(raw.get("did_you_mean", []))
                        if isinstance(raw.get("did_you_mean"), list)
                        else [],
                        "did_you_mean_ranked": list(raw.get("did_you_mean_ranked", []))
                        if isinstance(raw.get("did_you_mean_ranked"), list)
                        else [],
                        "expected_type": str(raw.get("expected_type", "unknown")),
                        "expected_scope": str(raw.get("expected_scope", "unknown")),
                        "likely_cause": str(raw.get("likely_cause", "unknown")),
                        "best_guess": raw.get("best_guess"),
                        "best_guess_score": raw.get("best_guess_score"),
                        "why_best_guess": raw.get("why_best_guess"),
                        "action": str(raw.get("action", "MANUAL_REVIEW")),
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
                                "did_you_mean": [],
                                "did_you_mean_ranked": [],
                                "expected_type": "unknown",
                                "expected_scope": "unknown",
                                "likely_cause": "unknown",
                                "best_guess": None,
                                "best_guess_score": None,
                                "why_best_guess": None,
                                "action": "MANUAL_REVIEW",
                            }
                        )
                    if text.startswith("ambiguous_column:"):
                        items.append(
                            {
                                "kind": "ambiguous",
                                "target": text.split(":", maxsplit=1)[1],
                                "reason": "Ambiguous reference resolved to multiple candidate columns.",
                                "severity": "ERROR",
                                "did_you_mean": [],
                                "did_you_mean_ranked": [],
                                "expected_type": "column",
                                "expected_scope": "any_table",
                                "likely_cause": "unknown",
                                "best_guess": None,
                                "best_guess_score": None,
                                "why_best_guess": None,
                                "action": "MANUAL_REVIEW",
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
                "source_file_path": str(metadata.get("source_file", "")) or None,
                "items": sorted(
                    [
                        {
                            **item,
                            "referrers_count": referrers_count_map.get(
                                _normalize_ref_target(str(item.get("target", ""))),
                                0,
                            ),
                        }
                        for item in items
                    ],
                    key=lambda item: item["target"],
                ),
                "suggested_fix_options": _suggested_fix_options(
                    expression=_expression_text(metadata),
                    items=[
                        {
                            **item,
                            "referrers_count": referrers_count_map.get(
                                _normalize_ref_target(str(item.get("target", ""))),
                                0,
                            ),
                        }
                        for item in items
                    ],
                ),
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
                "source_file_path": str(metadata.get("source_file", "")) or None,
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


def _suggested_fix_options(
    *,
    expression: str,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not expression:
        return []
    if len(items) < 2:
        return []

    ranked_by_ref: dict[str, list[dict[str, Any]]] = {}
    best_guess_count = 0
    for item in items:
        ref = str(item.get("target", "")).strip()
        ranked = item.get("did_you_mean_ranked", [])
        if not ref or not isinstance(ranked, list):
            continue
        normalized_ranked = [entry for entry in ranked if isinstance(entry, dict) and entry.get("candidate")]
        if not normalized_ranked:
            continue
        ranked_by_ref[ref] = normalized_ranked
        if item.get("best_guess"):
            best_guess_count += 1

    if best_guess_count == 0:
        return []

    # Build option seeds: base top-1, plus up to two perturbations from next-ranked candidates.
    option_maps: list[dict[str, dict[str, Any]]] = []
    base_map: dict[str, dict[str, Any]] = {}
    for ref, ranked in ranked_by_ref.items():
        base_map[ref] = ranked[0]
    option_maps.append(base_map)

    alternates: list[tuple[int, str, dict[str, Any]]] = []
    for ref, ranked in ranked_by_ref.items():
        for alt in ranked[1:3]:
            alternates.append((int(alt.get("score", 0)), ref, alt))
    alternates.sort(key=lambda row: -row[0])
    for _, ref, alt in alternates[:2]:
        candidate_map = dict(base_map)
        candidate_map[ref] = alt
        option_maps.append(candidate_map)

    options: list[dict[str, Any]] = []
    seen_expr: set[str] = set()
    for candidate_map in option_maps:
        rewritten = expression
        scores: list[int] = []
        for ref, choice in candidate_map.items():
            replacement = _replacement_from_candidate(str(choice.get("candidate", "")))
            if not replacement:
                continue
            rewritten = rewritten.replace(ref, replacement)
            scores.append(int(choice.get("score", 0)))
        if not scores:
            continue
        if rewritten in seen_expr:
            continue
        seen_expr.add(rewritten)
        options.append(
            {
                "expression": rewritten,
                "combined_score": int(round(sum(scores) / len(scores))),
            }
        )

    options.sort(key=lambda row: -int(row.get("combined_score", 0)))
    return options[:3]


def _replacement_from_candidate(candidate: str) -> str | None:
    text = candidate.strip()
    if text.startswith("measure:"):
        name = text.split(":", maxsplit=1)[1].strip()
        return f"[{name}]" if name else None
    if text.startswith("column:"):
        body = text.split(":", maxsplit=1)[1].strip()
        if "[" in body and body.endswith("]"):
            table_name, col_part = body.split("[", maxsplit=1)
            column_name = col_part[:-1]
            table = table_name.strip().strip("'")
            if not table or not column_name:
                return None
            return f"'{table}'[{column_name}]"
    return None


def _build_referrers_count_map(objects: dict[str, dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for metadata in objects.values():
        expression = _expression_text(metadata)
        if not expression:
            continue
        refs = {match.strip() for match in re.findall(r"\[([^\[\]]+)\]", expression)}
        for ref in refs:
            key = ref.lower()
            counts[key] = counts.get(key, 0) + 1
    return counts


def _normalize_ref_target(target: str) -> str:
    text = target.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return text.lower().strip()


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


def _build_desktop_semantic_parity_diff(desktop_artifacts: Any) -> dict[str, Any]:
    compare_target, resolve_diag = _resolve_pbip_compare_target_for_desktop_debug()
    if not compare_target:
        return {
            "status": "unavailable",
            "reason": "no_pbip_compare_target_found",
            "resolution": resolve_diag,
        }
    try:
        pbip_artifacts = build_model_artifacts(compare_target)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "unavailable",
            "reason": "pbip_compare_build_failed",
            "resolution": {
                **resolve_diag,
                "selected_compare_target": compare_target,
                "error": str(exc),
            },
        }
    parity = _compute_semantic_parity_diff(pbip_artifacts, desktop_artifacts)
    parity["resolution"] = {
        **resolve_diag,
        "selected_compare_target": compare_target,
    }
    return parity


def _resolve_pbip_compare_target_for_desktop_debug() -> tuple[str | None, dict[str, Any]]:
    env_key = "SEMANTIC_TEST_PARITY_COMPARE_PATH"
    env_target = os.environ.get(env_key, "").strip()
    if env_target:
        try:
            if Path(env_target).exists():
                return env_target, {"strategy": "env", "env_key": env_key}
            return None, {
                "strategy": "env",
                "env_key": env_key,
                "error": "path_not_found",
                "value": env_target,
            }
        except Exception as exc:  # noqa: BLE001
            return None, {"strategy": "env", "env_key": env_key, "error": str(exc)}

    try:
        discovered = [str(path) for path in discover_definition_folders(str(Path.cwd()))]
    except Exception as exc:  # noqa: BLE001
        return None, {"strategy": "cwd_discovery", "error": str(exc), "cwd": str(Path.cwd())}

    if len(discovered) == 1:
        return discovered[0], {"strategy": "cwd_single_model", "cwd": str(Path.cwd())}
    if len(discovered) > 1:
        return None, {
            "strategy": "cwd_discovery",
            "cwd": str(Path.cwd()),
            "error": "multiple_models_detected",
            "candidates": discovered[:25],
            "candidates_count": len(discovered),
        }
    return None, {
        "strategy": "cwd_discovery",
        "cwd": str(Path.cwd()),
        "error": "no_models_detected",
    }


def _compute_semantic_parity_diff(
    pbip_artifacts: Any,
    desktop_artifacts: Any,
) -> dict[str, Any]:
    pbip_by_type = _object_ids_by_type(getattr(pbip_artifacts, "objects", {}))
    desktop_by_type = _object_ids_by_type(getattr(desktop_artifacts, "objects", {}))

    pbip_columns = pbip_by_type.get("Column", set())
    desktop_columns = desktop_by_type.get("Column", set())
    pbip_measures = pbip_by_type.get("Measure", set())
    desktop_measures = desktop_by_type.get("Measure", set())
    pbip_calc_groups = pbip_by_type.get("CalcGroup", set())
    desktop_calc_groups = desktop_by_type.get("CalcGroup", set())
    pbip_calc_items = pbip_by_type.get("CalcItem", set())
    desktop_calc_items = desktop_by_type.get("CalcItem", set())

    columns_only_in_pbip = sorted(pbip_columns - desktop_columns)
    columns_only_in_desktop = sorted(desktop_columns - pbip_columns)
    measures_only_in_pbip = sorted(pbip_measures - desktop_measures)
    measures_only_in_desktop = sorted(desktop_measures - pbip_measures)
    calc_groups_only_in_pbip = sorted(pbip_calc_groups - desktop_calc_groups)
    calc_groups_only_in_desktop = sorted(desktop_calc_groups - pbip_calc_groups)
    calc_items_only_in_pbip = sorted(pbip_calc_items - desktop_calc_items)
    calc_items_only_in_desktop = sorted(desktop_calc_items - pbip_calc_items)

    pbip_semantic = (
        getattr(pbip_artifacts, "diagnostics", {}).get("semantic_inventory", {})
        if isinstance(getattr(pbip_artifacts, "diagnostics", {}), dict)
        else {}
    )
    desktop_semantic = (
        getattr(desktop_artifacts, "diagnostics", {}).get("semantic_inventory", {})
        if isinstance(getattr(desktop_artifacts, "diagnostics", {}), dict)
        else {}
    )
    pbip_edges = dict(pbip_semantic.get("edge_category_counts", {}))
    desktop_edges = dict(desktop_semantic.get("edge_category_counts", {}))
    edge_categories = sorted(set(pbip_edges.keys()) | set(desktop_edges.keys()))
    edge_diff = {
        category: int(desktop_edges.get(category, 0)) - int(pbip_edges.get(category, 0))
        for category in edge_categories
    }

    desktop_column_inventory = getattr(desktop_artifacts, "column_inventory", {})
    desktop_extra_column_classification = _classify_column_subset(
        desktop_column_inventory if isinstance(desktop_column_inventory, dict) else {},
        set(columns_only_in_desktop),
    )

    return {
        "status": "available",
        "pbip_definition_path": str(getattr(pbip_artifacts, "definition_folder", "")),
        "desktop_definition_path": str(getattr(desktop_artifacts, "definition_folder", "")),
        "object_counts_by_source": {
            "pbip": dict(pbip_semantic.get("object_type_counts", {})),
            "desktop": dict(desktop_semantic.get("object_type_counts", {})),
        },
        "object_id_differences": {
            "columns_only_in_pbip": columns_only_in_pbip[:200],
            "columns_only_in_desktop": columns_only_in_desktop[:200],
            "measures_only_in_pbip": measures_only_in_pbip[:200],
            "measures_only_in_desktop": measures_only_in_desktop[:200],
            "calc_groups_only_in_pbip": calc_groups_only_in_pbip[:200],
            "calc_groups_only_in_desktop": calc_groups_only_in_desktop[:200],
            "calc_items_only_in_pbip": calc_items_only_in_pbip[:200],
            "calc_items_only_in_desktop": calc_items_only_in_desktop[:200],
        },
        "object_id_difference_counts": {
            "columns_only_in_pbip": len(columns_only_in_pbip),
            "columns_only_in_desktop": len(columns_only_in_desktop),
            "measures_only_in_pbip": len(measures_only_in_pbip),
            "measures_only_in_desktop": len(measures_only_in_desktop),
            "calc_groups_only_in_pbip": len(calc_groups_only_in_pbip),
            "calc_groups_only_in_desktop": len(calc_groups_only_in_desktop),
            "calc_items_only_in_pbip": len(calc_items_only_in_pbip),
            "calc_items_only_in_desktop": len(calc_items_only_in_desktop),
        },
        "edge_category_counts": {
            "pbip": pbip_edges,
            "desktop": desktop_edges,
            "diff_desktop_minus_pbip": edge_diff,
        },
        "desktop_extra_columns_classification": desktop_extra_column_classification,
        "calc_group_support": {
            "pbip": "supported_by_tmdl_parser",
            "desktop": str(
                desktop_semantic.get("semantic_limitations", {}).get(
                    "calc_groups_items_from_desktop_dmv",
                    "unknown",
                )
            ),
        },
    }


def _object_ids_by_type(objects: dict[str, dict[str, Any]]) -> dict[str, set[str]]:
    typed: dict[str, set[str]] = {}
    for object_id, metadata in objects.items():
        object_type = str(metadata.get("type", "Unknown"))
        typed.setdefault(object_type, set()).add(object_id)
    return typed


def _classify_column_subset(
    column_inventory: dict[str, dict[str, Any]],
    target_ids: set[str],
) -> dict[str, Any]:
    hidden = 0
    visible = 0
    local_date = 0
    technical = 0
    local_date_samples: list[str] = []
    technical_samples: list[str] = []
    for object_id in sorted(target_ids):
        metadata = column_inventory.get(object_id, {})
        table_name = str(metadata.get("table", "")).lower()
        column_name = str(metadata.get("name", "")).lower()
        is_hidden = bool(metadata.get("is_hidden", False))
        if is_hidden:
            hidden += 1
        else:
            visible += 1

        is_local_date = (
            table_name.startswith("localdatetable_")
            or "localdate" in table_name
            or "autodate" in table_name
        )
        if is_local_date:
            local_date += 1
            if len(local_date_samples) < 10:
                local_date_samples.append(object_id)

        is_technical = (
            is_local_date
            or column_name.startswith("rownumber")
            or column_name.startswith("__")
            or column_name.endswith("key0")
        )
        if is_technical:
            technical += 1
            if len(technical_samples) < 10:
                technical_samples.append(object_id)
    return {
        "total": len(target_ids),
        "hidden": hidden,
        "visible": visible,
        "local_date_table_like": local_date,
        "technical_like": technical,
        "local_date_samples": local_date_samples,
        "technical_samples": technical_samples,
    }


def _error_report_text(
    message: str,
    discovery: dict[str, Any] | None = None,
    invocation_prefix: str = "semantic-test",
) -> str:
    lines = [
        f"semantic-test Scan Report (v{__version__})",
        "Status: ERROR",
        f"Error: {message}",
    ]
    models = (discovery or {}).get("models_detected", [])
    if isinstance(models, list) and len(models) > 1:
        lines.extend(["", "Next Actions", "------------"])
        first = models[0]
        path = str(first.get("definition_path", "<definition_path>"))
        lines.append(
            "Multiple models were detected. Re-run a specific model, for example: "
            f"{_scan_command(invocation_prefix, path, '--strict')}"
        )
        if invocation_prefix != "semantic-test":
            lines.append(
                f"If CLI entrypoint is installed: {_scan_command('semantic-test', path, '--strict')}"
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


def _invocation_prefix() -> str:
    argv0 = Path(sys.argv[0]).name.lower()
    if argv0.startswith("semantic-test"):
        return "semantic-test"
    return "python -m semantic_test.cli.main"


def _semantic_cli_available() -> bool:
    return shutil.which("semantic-test") is not None


def _scan_command(prefix: str, target_path: str, flag: str) -> str:
    return f"{prefix} scan {_quote_arg(target_path)} {flag}"


def _quote_arg(value: str) -> str:
    escaped = str(value).replace('"', '\\"')
    return f"\"{escaped}\""
