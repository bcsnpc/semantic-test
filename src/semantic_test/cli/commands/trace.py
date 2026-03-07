"""Trace command."""

from __future__ import annotations

from dataclasses import asdict
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer

from semantic_test.core.diff.snapshot import Snapshot, load_snapshot
from semantic_test.core.io.index_manager import get_model_entry, load_index
from semantic_test.core.io.output_manager import (
    create_run_folder,
    get_output_root,
    write_manifest,
    write_text,
)
from semantic_test.core.model.model_key import build_model_key, resolve_project_root
from semantic_test.core.parse.pbip_locator import locate_definition_folder
from semantic_test.exporters.mermaid import export_trace_to_mermaid


def trace_command(
    object_id: str = typer.Argument(...),
    path: str = typer.Argument("."),
    upstream: bool = typer.Option(False, "--upstream"),
    downstream: bool = typer.Option(False, "--downstream"),
    depth: int = typer.Option(2, "--depth"),
    output_format: str = typer.Option("text", "--format"),
    export: str | None = typer.Option(None, "--export"),
    out: str | None = typer.Option(None, "--out"),
    outdir: str | None = typer.Option(None, "--outdir"),
) -> None:
    """Trace upstream/downstream dependencies for an object from latest snapshot."""
    if output_format not in {"text", "json"}:
        raise typer.BadParameter("--format must be one of: text, json")
    if export is not None and export not in {"mmd", "mmd-simple"}:
        raise typer.BadParameter("--export currently supports only: mmd, mmd-simple")
    if depth < 0:
        raise typer.BadParameter("--depth must be >= 0")

    show_upstream = upstream or not downstream
    show_downstream = downstream or not upstream

    now = datetime.now(timezone.utc)
    project_root = resolve_project_root(path)
    output_root = get_output_root(project_root, outdir_override=outdir)

    model_key = _resolve_model_key(path, project_root, output_root)
    entry = get_model_entry(load_index(output_root), model_key) if model_key else None
    snapshot = _load_snapshot_from_entry(entry, project_root)

    run_folder = create_run_folder(
        output_root=output_root,
        command="trace",
        model_key=model_key or "model",
        snapshot_hash=snapshot.snapshot_hash[:12] if snapshot else "pending",
        now=now,
    )
    manifest: dict[str, object] = {
        "version": "0.1",
        "command": "trace",
        "timestamp_utc": now.isoformat(),
        "path": path,
        "object_id": object_id,
        "depth": depth,
        "upstream": show_upstream,
        "downstream": show_downstream,
        "status": "RUNNING",
        "error": None,
        "run_folder": str(run_folder),
    }

    if snapshot is None:
        message = "No previous run found for this model. Run scan first."
        manifest["status"] = "CLEAN"
        manifest["no_previous_snapshot"] = True
        write_text(run_folder, "snapshot.json", json.dumps({"status": "CLEAN", "message": message}, indent=2, sort_keys=True))
        write_text(run_folder, "report.txt", f"Status: CLEAN\n{message}")
        write_text(run_folder, "report.json", json.dumps({"status": "CLEAN", "message": message}, indent=2, sort_keys=True))
        write_manifest(run_folder, manifest)
        _emit_output(message, out)
        return

    if object_id not in snapshot.objects:
        message = f"Object not found in snapshot: {object_id}"
        manifest["status"] = "ERROR"
        manifest["error"] = message
        write_text(run_folder, "snapshot.json", json.dumps(asdict(snapshot), indent=2, sort_keys=True))
        write_text(run_folder, "report.txt", f"Status: ERROR\nError: {message}")
        write_text(run_folder, "report.json", json.dumps({"status": "ERROR", "error": message}, indent=2, sort_keys=True))
        write_manifest(run_folder, manifest)
        _emit_output(f"Status: ERROR\nError: {message}", out)
        raise typer.Exit(code=1)

    forward, reverse = _build_adjacency(snapshot)
    upstream_nodes = _walk_depth(forward, object_id, depth) if show_upstream else []
    downstream_nodes = _walk_depth(reverse, object_id, depth) if show_downstream else []
    show_upstream_visuals = _is_visual_object(object_id)
    upstream_visuals = _visual_rows(snapshot, upstream_nodes, traced_object_id=object_id) if show_upstream_visuals else []
    downstream_visuals = _visual_rows(snapshot, downstream_nodes, traced_object_id=object_id)

    report_text = _format_text(
        object_id,
        upstream_nodes,
        downstream_nodes,
        upstream_visuals=upstream_visuals,
        downstream_visuals=downstream_visuals,
        show_upstream_visuals=show_upstream_visuals,
    )
    report_payload = {
        "status": "CLEAN",
        "object_id": object_id,
        "upstream": upstream_nodes,
        "downstream": downstream_nodes,
        "upstream_visual_dependencies": upstream_visuals,
        "downstream_visual_dependencies": downstream_visuals,
        "depth": depth,
        "model_key": snapshot.model_key,
        "snapshot_hash": snapshot.snapshot_hash,
        "trace_scope_edges": _trace_scope_edges(
            snapshot,
            scope_nodes={object_id, *upstream_nodes, *downstream_nodes},
        ),
    }
    report_json = json.dumps(report_payload, indent=2, sort_keys=True)

    write_text(run_folder, "snapshot.json", json.dumps(asdict(snapshot), indent=2, sort_keys=True))
    write_text(run_folder, "report.txt", report_text)
    write_text(run_folder, "report.json", report_json)
    if export == "mmd":
        mmd_text = export_trace_to_mermaid(report_payload, mode="full")
        write_text(run_folder, "trace_graph.mmd", mmd_text)
    if export == "mmd-simple":
        mmd_text = export_trace_to_mermaid(report_payload, mode="simple")
        write_text(run_folder, "trace_graph.mmd", mmd_text)

    manifest["status"] = "CLEAN"
    manifest["snapshot_hash"] = snapshot.snapshot_hash
    if export:
        manifest["export"] = export
    write_manifest(run_folder, manifest)

    output = report_json if output_format == "json" else report_text
    _emit_output(output, out)


def _resolve_model_key(path: str, project_root: Path, output_root: Path) -> str | None:
    try:
        definition = locate_definition_folder(path)
        return build_model_key(definition, project_root=project_root)
    except (FileNotFoundError, ValueError):
        pass

    index_obj = load_index(output_root)
    models = index_obj.get("models", [])
    if not isinstance(models, list) or not models:
        return None
    models_sorted = sorted(models, key=lambda item: str(item.get("latest_run_id", "")))
    return str(models_sorted[-1].get("model_key", "")) or None


def _load_snapshot_from_entry(entry: dict[str, Any] | None, project_root: Path) -> Snapshot | None:
    if not entry:
        return None
    run_path = str(entry.get("latest_run_path", "")).strip()
    if not run_path:
        return None
    run_folder = Path(run_path)
    if not run_folder.is_absolute():
        run_folder = (project_root / run_folder).resolve()
    snapshot_path = run_folder / "snapshot.json"
    if not snapshot_path.exists():
        return None
    return load_snapshot(snapshot_path)


def _build_adjacency(snapshot: Snapshot) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    forward: dict[str, set[str]] = {node_id: set() for node_id in snapshot.objects}
    reverse: dict[str, set[str]] = {node_id: set() for node_id in snapshot.objects}
    for source, target, _kind in snapshot.edges:
        if source not in forward:
            forward[source] = set()
        if target not in forward:
            forward[target] = set()
        if source not in reverse:
            reverse[source] = set()
        if target not in reverse:
            reverse[target] = set()
        forward[source].add(target)
        reverse[target].add(source)
    return forward, reverse


def _walk_depth(adjacency: dict[str, set[str]], start: str, depth: int) -> list[str]:
    if depth == 0:
        return []
    visited: set[str] = set()
    frontier: list[tuple[str, int]] = [(start, 0)]
    while frontier:
        node, level = frontier.pop(0)
        if level >= depth:
            continue
        for neighbor in sorted(adjacency.get(node, set())):
            if neighbor in visited or neighbor == start:
                continue
            visited.add(neighbor)
            frontier.append((neighbor, level + 1))
    return sorted(visited)


def _trace_scope_edges(snapshot: Snapshot, *, scope_nodes: set[str]) -> list[list[str]]:
    edges: list[list[str]] = []
    for source, target, _kind in snapshot.edges:
        if source in scope_nodes and target in scope_nodes:
            edges.append([source, target])
    edges.sort(key=lambda row: (row[0], row[1]))
    return edges


def _visual_rows(
    snapshot: Snapshot,
    nodes: list[str],
    *,
    traced_object_id: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for node_id in nodes:
        if not node_id.startswith("Visual:"):
            continue
        metadata = snapshot.objects.get(node_id)
        meta = metadata.metadata if metadata is not None else {}
        roles = _roles_for_traced_object(meta, traced_object_id)
        rows.append(
            {
                "object_id": node_id,
                "page_name": str(meta.get("page_name", "")) or "<unknown_page>",
                "visual_name": str(meta.get("visual_name", "")) or str(meta.get("visual_id", "")) or "<unknown_visual>",
                "title": str(meta.get("title", "")) or "<no_title>",
                "visual_id": str(meta.get("visual_id", "")) or "<unknown_id>",
                "visual_type": str(meta.get("visual_type", "")) or "<unknown_type>",
                "roles": ", ".join(roles) if roles else "<unknown_role>",
            }
        )
    rows.sort(key=lambda row: (row["page_name"], row["visual_name"], row["visual_id"], row["roles"], row["object_id"]))
    return rows


def _format_text(
    object_id: str,
    upstream_nodes: list[str],
    downstream_nodes: list[str],
    *,
    upstream_visuals: list[dict[str, str]],
    downstream_visuals: list[dict[str, str]],
    show_upstream_visuals: bool,
) -> str:
    lines = [f"Object: {object_id}", "", "Upstream:"]
    if upstream_nodes:
        for item in upstream_nodes:
            lines.append(f"  {item}")
    else:
        lines.append("  none")
    if show_upstream_visuals:
        lines.extend(["", "Upstream Visual Dependencies:"])
        if upstream_visuals:
            lines.extend(_format_grouped_visuals(upstream_visuals))
        else:
            lines.append("  none")
    lines.extend(["", "Downstream:"])
    if downstream_nodes:
        for item in downstream_nodes:
            lines.append(f"  {item}")
    else:
        lines.append("  none")
    lines.extend(["", "Downstream Visual Dependencies:"])
    if downstream_visuals:
        lines.extend(_format_grouped_visuals(downstream_visuals))
    else:
        lines.append("  none")
    return "\n".join(lines)


def _format_grouped_visuals(rows: list[dict[str, str]]) -> list[str]:
    lines: list[str] = ["------------------------------"]
    current_page: str | None = None
    for row in rows:
        page = row["page_name"]
        if page != current_page:
            lines.append(f"Page: {page}")
            current_page = page
        visual_label = row["title"] if row["title"] != "<no_title>" else row["visual_id"]
        lines.append(f"  Visual: {visual_label}")
        lines.append(f"    Type: {row['visual_type']}")
        lines.append(f"    Role: {row['roles']}")
        if visual_label != row["visual_id"]:
            lines.append(f"    Id: {row['visual_id']}")
        lines.append(f"    ObjectId: {row['object_id']}")
    return lines


def _roles_for_traced_object(visual_meta: dict[str, Any], traced_object_id: str) -> list[str]:
    bindings = visual_meta.get("bindings", [])
    if not isinstance(bindings, list):
        return []
    roles = sorted(
        {
            str(binding.get("role", "")).strip() or "unknown"
            for binding in bindings
            if isinstance(binding, dict) and str(binding.get("target", "")) == traced_object_id
        }
    )
    return roles


def _is_visual_object(object_id: str) -> bool:
    return object_id.startswith("Visual:")


def _emit_output(output: str, out: str | None) -> None:
    if out:
        Path(out).write_text(output, encoding="utf-8")
        typer.echo(f"Wrote output: {out}")
        return
    typer.echo(output)
