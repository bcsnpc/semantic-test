"""Visual dependency extraction from a live Power BI Desktop workspace."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import json
from datetime import datetime, timezone
import re
import subprocess

from semantic_test.core.model.objects import ObjectType, object_id as make_object_id
from semantic_test.core.parse.extractors.report_visuals import (
    _extract_visual_title,
    _load_json,
    _normalize_role,
    _resolve_binding,
    extract_pbix_visuals_with_diagnostics,
    extract_report_visuals_with_diagnostics,
)


def extract_desktop_visuals(
    workspace_dir: Path,
    model_object_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Extract visual dependencies from Desktop workspace, if report metadata exists.

    Desktop internals vary by version. This function currently supports workspace
    layouts that expose a PBIP-like ``Report/definition/pages`` structure.
    """
    candidate_roots = _candidate_report_roots(workspace_dir)
    strategies_tried = [
        "standard_report_root",
        "recursive_visual_json",
        "pbix_layout",
        "desktop_live_pbix_layout",
        "desktop_process_correlated_layout",
        "alternate_artifact_discovery",
    ]
    standard_layout_exists = False
    for report_root in candidate_roots:
        pages_root = report_root / "definition" / "pages"
        if not pages_root.exists():
            continue
        standard_layout_exists = True
        inventory, diagnostics = extract_report_visuals_with_diagnostics(
            report_root,
            model_object_ids=model_object_ids,
        )
        if inventory:
            return inventory, {
                "workspace_dir": str(workspace_dir),
                "report_root": str(report_root),
                "strategies_tried": strategies_tried,
                "candidate_report_roots_checked": [str(path) for path in candidate_roots],
                "standard_layout_exists": standard_layout_exists,
                "visual_json_files_found": _count_files(workspace_dir, "visual.json"),
                "page_json_files_found": _count_files(workspace_dir, "page.json"),
                "report_json_files_found": _count_files(workspace_dir, "report.json"),
                "layout_like_files_found": [],
                "recursive_visual_scan_used": False,
                "empty_reason": "",
                "visual_lineage_status": "available",
                "visual_lineage_reason": "",
                "visual_mapping": {
                    "total_visuals": diagnostics.total_visuals,
                    "total_field_bindings": diagnostics.total_bindings_extracted,
                    "bindings_resolved_measures": diagnostics.bindings_resolved_measures,
                    "bindings_resolved_columns": diagnostics.bindings_resolved_columns,
                    "unresolved_visual_bindings": diagnostics.unresolved_binding_count,
                    "unresolved_examples": diagnostics.unresolved_examples,
                },
            }

    fallback_inventory, fallback_diagnostics = _extract_visuals_by_recursive_scan(
        workspace_dir,
        model_object_ids=model_object_ids,
    )
    if fallback_inventory:
        return fallback_inventory, {
            "workspace_dir": str(workspace_dir),
            "report_root": "",
            "strategies_tried": strategies_tried,
            "candidate_report_roots_checked": [str(path) for path in candidate_roots],
            "standard_layout_exists": standard_layout_exists,
            "visual_json_files_found": _count_files(workspace_dir, "visual.json"),
            "page_json_files_found": _count_files(workspace_dir, "page.json"),
            "report_json_files_found": _count_files(workspace_dir, "report.json"),
            "layout_like_files_found": [],
            "recursive_visual_scan_used": True,
            "empty_reason": "",
            "visual_lineage_status": "available",
            "visual_lineage_reason": "resolved_from_recursive_visual_json_scan",
            "visual_mapping": {
                "total_visuals": fallback_diagnostics.get("total_visuals", 0),
                "total_field_bindings": fallback_diagnostics.get("total_field_bindings", 0),
                "bindings_resolved_measures": fallback_diagnostics.get("bindings_resolved_measures", 0),
                "bindings_resolved_columns": fallback_diagnostics.get("bindings_resolved_columns", 0),
                "unresolved_visual_bindings": fallback_diagnostics.get("unresolved_visual_bindings", 0),
                "unresolved_examples": fallback_diagnostics.get("unresolved_examples", []),
            },
        }

    layout_inventory, layout_diagnostics = _extract_visuals_from_pbix_layout(
        workspace_dir,
        model_object_ids=model_object_ids,
    )
    if layout_inventory:
        return layout_inventory, {
            "workspace_dir": str(workspace_dir),
            "report_root": "",
            "strategies_tried": strategies_tried,
            "candidate_report_roots_checked": [str(path) for path in candidate_roots],
            "standard_layout_exists": standard_layout_exists,
            "visual_json_files_found": _count_files(workspace_dir, "visual.json"),
            "page_json_files_found": _count_files(workspace_dir, "page.json"),
            "report_json_files_found": _count_files(workspace_dir, "report.json"),
            "pbix_layout_files_found": int(layout_diagnostics.get("pbix_layout_files_found", 0)),
            "desktop_live_pbix_layout_files_found": 0,
            "layout_like_files_found": list(layout_diagnostics.get("layout_like_files_found", [])),
            "recursive_visual_scan_used": True,
            "pbix_layout_scan_used": True,
            "desktop_live_pbix_layout_scan_used": False,
            "empty_reason": "",
            "visual_lineage_status": "available",
            "visual_lineage_reason": "resolved_from_pbix_layout",
            "visual_mapping": {
                "total_visuals": layout_diagnostics.get("total_visuals", 0),
                "total_field_bindings": layout_diagnostics.get("total_field_bindings", 0),
                "bindings_resolved_measures": layout_diagnostics.get("bindings_resolved_measures", 0),
                "bindings_resolved_columns": layout_diagnostics.get("bindings_resolved_columns", 0),
                "unresolved_visual_bindings": layout_diagnostics.get("unresolved_visual_bindings", 0),
                "unresolved_examples": layout_diagnostics.get("unresolved_examples", []),
            },
        }

    live_inventory, live_diagnostics = _extract_visuals_from_desktop_live_pbix_layout(
        workspace_dir,
        model_object_ids=model_object_ids,
    )
    if live_inventory:
        return live_inventory, {
            "workspace_dir": str(workspace_dir),
            "report_root": "",
            "strategies_tried": strategies_tried,
            "candidate_report_roots_checked": [str(path) for path in candidate_roots],
            "standard_layout_exists": standard_layout_exists,
            "visual_json_files_found": _count_files(workspace_dir, "visual.json"),
            "page_json_files_found": _count_files(workspace_dir, "page.json"),
            "report_json_files_found": _count_files(workspace_dir, "report.json"),
            "pbix_layout_files_found": int(layout_diagnostics.get("pbix_layout_files_found", 0)),
            "desktop_live_pbix_layout_files_found": int(live_diagnostics.get("desktop_live_pbix_layout_files_found", 0)),
            "layout_like_files_found": list(live_diagnostics.get("layout_like_files_found", [])),
            "recursive_visual_scan_used": True,
            "pbix_layout_scan_used": True,
            "desktop_live_pbix_layout_scan_used": True,
            "desktop_live_search_roots": list(live_diagnostics.get("searched_roots", [])),
            "desktop_live_candidates_checked": list(live_diagnostics.get("candidates_checked", [])),
            "desktop_live_candidates_accepted": list(live_diagnostics.get("candidates_accepted", [])),
            "desktop_live_candidates_rejected": list(live_diagnostics.get("candidates_rejected", [])),
            "desktop_live_signature_matches": list(live_diagnostics.get("signature_matches", [])),
            "desktop_live_parser_ran": bool(live_diagnostics.get("parser_ran", False)),
            "empty_reason": "",
            "visual_lineage_status": "available",
            "visual_lineage_reason": "resolved_from_desktop_live_pbix_layout",
            "visual_mapping": {
                "total_visuals": live_diagnostics.get("total_visuals", 0),
                "total_field_bindings": live_diagnostics.get("total_field_bindings", 0),
                "bindings_resolved_measures": live_diagnostics.get("bindings_resolved_measures", 0),
                "bindings_resolved_columns": live_diagnostics.get("bindings_resolved_columns", 0),
                "unresolved_visual_bindings": live_diagnostics.get("unresolved_visual_bindings", 0),
                "unresolved_examples": live_diagnostics.get("unresolved_examples", []),
            },
        }

    process_inventory, process_diagnostics = _extract_visuals_from_desktop_process_correlated_layout(
        workspace_dir,
        model_object_ids=model_object_ids,
    )
    if process_inventory:
        process_reason = "resolved_from_desktop_process_correlated_layout"
        if str(process_diagnostics.get("pbix_source_format", "")).strip():
            process_reason = "resolved_from_desktop_process_correlated_pbix"
        return process_inventory, {
            "workspace_dir": str(workspace_dir),
            "report_root": "",
            "strategies_tried": strategies_tried,
            "candidate_report_roots_checked": [str(path) for path in candidate_roots],
            "standard_layout_exists": standard_layout_exists,
            "visual_json_files_found": _count_files(workspace_dir, "visual.json"),
            "page_json_files_found": _count_files(workspace_dir, "page.json"),
            "report_json_files_found": _count_files(workspace_dir, "report.json"),
            "pbix_layout_files_found": int(layout_diagnostics.get("pbix_layout_files_found", 0)),
            "desktop_live_pbix_layout_files_found": int(live_diagnostics.get("desktop_live_pbix_layout_files_found", 0)),
            "desktop_process_correlated_layout_files_found": int(process_diagnostics.get("desktop_process_correlated_layout_files_found", 0)),
            "layout_like_files_found": list(process_diagnostics.get("layout_like_files_found", [])),
            "recursive_visual_scan_used": True,
            "pbix_layout_scan_used": True,
            "desktop_live_pbix_layout_scan_used": True,
            "desktop_process_correlated_layout_scan_used": True,
            "desktop_live_search_roots": list(live_diagnostics.get("searched_roots", [])),
            "desktop_live_candidates_checked": list(live_diagnostics.get("candidates_checked", [])),
            "desktop_live_candidates_accepted": list(live_diagnostics.get("candidates_accepted", [])),
            "desktop_live_candidates_rejected": list(live_diagnostics.get("candidates_rejected", [])),
            "desktop_live_signature_matches": list(live_diagnostics.get("signature_matches", [])),
            "desktop_live_parser_ran": bool(live_diagnostics.get("parser_ran", False)),
            "desktop_process_info": list(process_diagnostics.get("process_info", [])),
            "desktop_process_search_roots": list(process_diagnostics.get("searched_roots", [])),
            "desktop_process_candidates_checked": list(process_diagnostics.get("candidates_checked", [])),
            "desktop_process_candidates_accepted": list(process_diagnostics.get("candidates_accepted", [])),
            "desktop_process_candidates_rejected": list(process_diagnostics.get("candidates_rejected", [])),
            "desktop_process_signature_matches": list(process_diagnostics.get("signature_matches", [])),
            "desktop_process_parser_ran": bool(process_diagnostics.get("parser_ran", False)),
            "desktop_process_pbix_source_format": str(process_diagnostics.get("pbix_source_format", "")),
            "empty_reason": "",
            "visual_lineage_status": "available",
            "visual_lineage_reason": process_reason,
            "visual_mapping": {
                "total_visuals": process_diagnostics.get("total_visuals", 0),
                "total_field_bindings": process_diagnostics.get("total_field_bindings", 0),
                "bindings_resolved_measures": process_diagnostics.get("bindings_resolved_measures", 0),
                "bindings_resolved_columns": process_diagnostics.get("bindings_resolved_columns", 0),
                "unresolved_visual_bindings": process_diagnostics.get("unresolved_visual_bindings", 0),
                "unresolved_examples": process_diagnostics.get("unresolved_examples", []),
            },
        }

    alt = _discover_alternate_report_artifacts(workspace_dir)
    visual_reason = str(fallback_diagnostics.get("empty_reason", "")).strip() or "no_visual_artifacts_accessible"
    if alt["layout_like_files_found"]:
        visual_reason = "alternate_artifacts_found_but_not_parseable_to_visual_bindings"
    return fallback_inventory, {
        "workspace_dir": str(workspace_dir),
        "report_root": "",
        "strategies_tried": strategies_tried,
        "candidate_report_roots_checked": [str(path) for path in candidate_roots],
        "standard_layout_exists": standard_layout_exists,
        "visual_json_files_found": _count_files(workspace_dir, "visual.json"),
        "page_json_files_found": _count_files(workspace_dir, "page.json"),
        "report_json_files_found": _count_files(workspace_dir, "report.json"),
        "pbix_layout_files_found": int(layout_diagnostics.get("pbix_layout_files_found", 0)),
        "desktop_live_pbix_layout_files_found": int(live_diagnostics.get("desktop_live_pbix_layout_files_found", 0)),
        "desktop_process_correlated_layout_files_found": int(process_diagnostics.get("desktop_process_correlated_layout_files_found", 0)),
        "layout_like_files_found": alt["layout_like_files_found"],
        "alternate_candidates_found": alt["alternate_candidates_found"],
        "alternate_parser_ran": bool(alt["alternate_parser_ran"]),
        "recursive_visual_scan_used": True,
        "pbix_layout_scan_used": True,
        "desktop_live_pbix_layout_scan_used": True,
        "desktop_process_correlated_layout_scan_used": True,
        "desktop_live_search_roots": list(live_diagnostics.get("searched_roots", [])),
        "desktop_live_candidates_checked": list(live_diagnostics.get("candidates_checked", [])),
        "desktop_live_candidates_accepted": list(live_diagnostics.get("candidates_accepted", [])),
        "desktop_live_candidates_rejected": list(live_diagnostics.get("candidates_rejected", [])),
        "desktop_live_signature_matches": list(live_diagnostics.get("signature_matches", [])),
        "desktop_live_parser_ran": bool(live_diagnostics.get("parser_ran", False)),
        "desktop_process_info": list(process_diagnostics.get("process_info", [])),
        "desktop_process_search_roots": list(process_diagnostics.get("searched_roots", [])),
        "desktop_process_candidates_checked": list(process_diagnostics.get("candidates_checked", [])),
        "desktop_process_candidates_accepted": list(process_diagnostics.get("candidates_accepted", [])),
        "desktop_process_candidates_rejected": list(process_diagnostics.get("candidates_rejected", [])),
        "desktop_process_signature_matches": list(process_diagnostics.get("signature_matches", [])),
        "desktop_process_parser_ran": bool(process_diagnostics.get("parser_ran", False)),
        "empty_reason": str(fallback_diagnostics.get("empty_reason", "")),
        "visual_lineage_status": "unavailable",
        "visual_lineage_reason": visual_reason,
        "visual_mapping": {
            "total_visuals": fallback_diagnostics.get("total_visuals", 0),
            "total_field_bindings": fallback_diagnostics.get("total_field_bindings", 0),
            "bindings_resolved_measures": fallback_diagnostics.get("bindings_resolved_measures", 0),
            "bindings_resolved_columns": fallback_diagnostics.get("bindings_resolved_columns", 0),
            "unresolved_visual_bindings": fallback_diagnostics.get("unresolved_visual_bindings", 0),
            "unresolved_examples": fallback_diagnostics.get("unresolved_examples", []),
        },
    }


def _candidate_report_roots(workspace_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    direct = workspace_dir / "Report"
    if direct.exists() and direct.is_dir():
        candidates.append(direct)

    try:
        for child in workspace_dir.iterdir():
            if not child.is_dir():
                continue
            if child.name.endswith(".Report"):
                candidates.append(child)
    except OSError:
        pass

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _extract_visuals_by_recursive_scan(
    workspace_dir: Path,
    *,
    model_object_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Fallback: recursively discover and parse visual.json files directly."""
    visual_files: list[Path] = []
    try:
        visual_files = [path for path in workspace_dir.rglob("visual.json") if path.is_file()]
    except OSError:
        return {}, {
            "total_visuals": 0,
            "total_field_bindings": 0,
            "bindings_resolved_measures": 0,
            "bindings_resolved_columns": 0,
            "unresolved_visual_bindings": 0,
            "unresolved_examples": [],
            "empty_reason": "recursive_scan_failed",
        }

    if not visual_files:
        return {}, {
            "total_visuals": 0,
            "total_field_bindings": 0,
            "bindings_resolved_measures": 0,
            "bindings_resolved_columns": 0,
            "unresolved_visual_bindings": 0,
            "unresolved_examples": [],
            "empty_reason": "no_visual_json_found",
        }

    merged_inventory: dict[str, dict[str, Any]] = {}
    total_bindings = 0
    resolved_measures = 0
    resolved_columns = 0
    unresolved_count = 0
    unresolved_examples: list[str] = []

    for visual_path in sorted(visual_files):
        visual_data = _load_json(visual_path)
        if visual_data is None:
            continue
        visual_id = str(visual_data.get("name") or visual_path.parent.name)
        visual_name = str(visual_data.get("name") or visual_id)
        visual_type = str(visual_data.get("visual", {}).get("visualType", "unknown"))
        visual_title = _extract_visual_title(visual_data)

        page_dir = visual_path.parent.parent.parent
        page_id = page_dir.name
        page_name = page_id
        page_json = page_dir / "page.json"
        if page_json.exists():
            page_data = _load_json(page_json) or {}
            page_name = str(page_data.get("displayName") or page_id)

        deps: set[str] = set()
        bindings: list[dict[str, str]] = []
        unresolved_bindings: list[str] = []

        query_state = (
            visual_data.get("visual", {})
            .get("query", {})
            .get("queryState", {})
        )
        for role, role_data in query_state.items():
            role_norm = _normalize_role(role)
            if role_norm == "sortdefinition":
                for sort_item in role_data.get("sort", []):
                    resolved = _resolve_binding(
                        sort_item.get("field", {}),
                        sort_item.get("queryRef"),
                        role="sort",
                        model_object_ids=model_object_ids,
                    )
                    if resolved is None:
                        unresolved_bindings.append(str(sort_item.get("queryRef", "")))
                        continue
                    deps.add(resolved.target)
                    bindings.append(
                        {
                            "role": "sort",
                            "target": resolved.target,
                            "source_kind": resolved.source_kind,
                            "raw": resolved.raw,
                        }
                    )
                continue
            for proj in role_data.get("projections", []):
                resolved = _resolve_binding(
                    proj.get("field", {}),
                    proj.get("queryRef"),
                    role=str(role),
                    model_object_ids=model_object_ids,
                )
                if resolved is None:
                    unresolved_bindings.append(str(proj.get("queryRef", "")))
                    continue
                deps.add(resolved.target)
                bindings.append(
                    {
                        "role": str(role),
                        "target": resolved.target,
                        "source_kind": resolved.source_kind,
                        "raw": resolved.raw,
                    }
                )

        short_id = visual_id[:12]
        obj_id = make_object_id(
            obj_type=ObjectType.VISUAL,
            parent=page_name or page_id,
            name=short_id,
        )
        merged_inventory[obj_id] = {
            "type": "Visual",
            "visual_id": visual_id,
            "visual_name": visual_name,
            "title": visual_title,
            "visual_type": visual_type,
            "page_id": page_id,
            "page_name": page_name,
            "dependencies": deps,
            "bindings": bindings,
            "unresolved_bindings": sorted({item for item in unresolved_bindings if item}),
            "unknown_patterns": [],
        }
        total_bindings += len(bindings)
        resolved_measures += sum(1 for b in bindings if str(b.get("target", "")).startswith("Measure:"))
        resolved_columns += sum(1 for b in bindings if str(b.get("target", "")).startswith("Column:"))
        unresolved_count += len(merged_inventory[obj_id]["unresolved_bindings"])
        unresolved_examples.extend(merged_inventory[obj_id]["unresolved_bindings"])

    return merged_inventory, {
        "total_visuals": len(merged_inventory),
        "total_field_bindings": total_bindings,
        "bindings_resolved_measures": resolved_measures,
        "bindings_resolved_columns": resolved_columns,
        "unresolved_visual_bindings": unresolved_count,
        "unresolved_examples": sorted(dict.fromkeys(unresolved_examples))[:10],
        "empty_reason": "" if merged_inventory else "visual_json_parsed_but_no_bindings",
    }


def _count_files(root: Path, file_name: str) -> int:
    try:
        return sum(1 for path in root.rglob(file_name) if path.is_file())
    except OSError:
        return 0


def _discover_alternate_report_artifacts(workspace_dir: Path) -> dict[str, Any]:
    """Discover possible desktop report artifacts when standard JSON layout is absent."""
    layout_like_files: list[str] = []
    alternate_candidates: list[str] = []
    patterns = {"layout", "report", "visualcontainer", "section", "page"}

    try:
        for path in workspace_dir.rglob("*"):
            if not path.is_file():
                continue
            name = path.name.lower()
            if name in {"layout", "report.json", "metadata.json"}:
                layout_like_files.append(str(path))
                continue
            if any(token in name for token in patterns) and path.suffix.lower() in {".json", ".txt", ".pbir"}:
                alternate_candidates.append(str(path))
    except OSError:
        pass

    return {
        "layout_like_files_found": sorted(dict.fromkeys(layout_like_files))[:50],
        "alternate_candidates_found": sorted(dict.fromkeys(alternate_candidates))[:50],
        "alternate_parser_ran": False,
    }


def _extract_visuals_from_pbix_layout(
    workspace_dir: Path,
    *,
    model_object_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Parse PBIX Layout/Layout.json and convert visual bindings into canonical objects."""
    layout_files = _find_pbix_layout_files(workspace_dir)
    inventory, diagnostics = _extract_visuals_from_layout_files(
        layout_files,
        model_object_ids=model_object_ids,
    )
    diagnostics["pbix_layout_files_found"] = len(layout_files)
    diagnostics["layout_like_files_found"] = [str(path) for path in layout_files[:50]]
    return inventory, diagnostics


def _extract_visuals_from_desktop_live_pbix_layout(
    workspace_dir: Path,
    *,
    model_object_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    searched_roots = _desktop_live_search_roots(workspace_dir)
    candidates_checked: list[str] = []
    candidates_accepted: list[str] = []
    candidates_rejected: list[str] = []
    signature_matches: list[str] = []
    candidate_files: list[Path] = []

    for root in searched_roots:
        for candidate in _layout_candidates_under_root(root, max_depth=6):
            candidates_checked.append(str(candidate))
            signature, reason = _file_has_layout_signature(candidate)
            if not signature:
                candidates_rejected.append(f"{candidate} :: {reason}")
                continue
            if not _candidate_correlates_to_session(candidate, workspace_dir):
                candidates_rejected.append(f"{candidate} :: session_correlation_failed")
                continue
            candidates_accepted.append(str(candidate))
            signature_matches.append(str(candidate))
            candidate_files.append(candidate)

    inventory, diagnostics = _extract_visuals_from_layout_files(
        candidate_files,
        model_object_ids=model_object_ids,
    )
    diagnostics.update(
        {
            "desktop_live_pbix_layout_files_found": len(candidate_files),
            "searched_roots": [str(path) for path in searched_roots],
            "candidates_checked": candidates_checked[:100],
            "candidates_accepted": candidates_accepted[:100],
            "candidates_rejected": candidates_rejected[:100],
            "signature_matches": signature_matches[:100],
            "parser_ran": bool(candidate_files),
        }
    )
    return inventory, diagnostics


def _extract_visuals_from_desktop_process_correlated_layout(
    workspace_dir: Path,
    *,
    model_object_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    processes = _active_pbi_desktop_processes()

    pbix_candidates = _candidate_pbix_paths_from_processes(processes)
    pbix_checked: list[str] = []
    pbix_accepted: list[str] = []
    pbix_rejected: list[str] = []
    for pbix_path in pbix_candidates:
        pbix_checked.append(str(pbix_path))
        if not pbix_path.exists() or not pbix_path.is_file():
            pbix_rejected.append(f"{pbix_path} :: missing")
            continue
        if not _candidate_correlates_to_process_session(pbix_path, workspace_dir, processes):
            pbix_rejected.append(f"{pbix_path} :: process_session_correlation_failed")
            continue
        inventory, pbix_diag = extract_pbix_visuals_with_diagnostics(pbix_path, model_object_ids=model_object_ids)
        if inventory:
            pbix_accepted.append(str(pbix_path))
            return inventory, {
                "desktop_process_correlated_layout_files_found": 0,
                "desktop_process_correlated_pbix_files_found": 1,
                "process_info": [
                    {
                        "pid": int(proc.get("pid", 0) or 0),
                        "executable_path": str(proc.get("executable_path", "")),
                        "command_line": str(proc.get("command_line", ""))[:400],
                    }
                    for proc in processes[:10]
                ],
                "searched_roots": [],
                "candidates_checked": pbix_checked[:150],
                "candidates_accepted": pbix_accepted[:150],
                "candidates_rejected": pbix_rejected[:150],
                "signature_matches": pbix_accepted[:150],
                "parser_ran": True,
                "layout_like_files_found": pbix_accepted[:50],
                "pbix_source_format": pbix_diag.source_format,
                "total_visuals": pbix_diag.total_visuals,
                "total_field_bindings": pbix_diag.total_bindings_extracted,
                "bindings_resolved_measures": pbix_diag.bindings_resolved_measures,
                "bindings_resolved_columns": pbix_diag.bindings_resolved_columns,
                "unresolved_visual_bindings": pbix_diag.unresolved_binding_count,
                "unresolved_examples": pbix_diag.unresolved_examples,
            }
        pbix_rejected.append(f"{pbix_path} :: no_parseable_visuals")

    search_roots = _process_correlated_search_roots(workspace_dir, processes)
    candidates_checked: list[str] = []
    candidates_accepted: list[str] = []
    candidates_rejected: list[str] = []
    signature_matches: list[str] = []
    candidate_files: list[Path] = []

    for root in search_roots:
        for candidate in _layout_candidates_under_root(root, max_depth=6):
            candidates_checked.append(str(candidate))
            signature, reason = _file_has_layout_signature(candidate)
            if not signature:
                candidates_rejected.append(f"{candidate} :: {reason}")
                continue
            if not _candidate_correlates_to_process_session(candidate, workspace_dir, processes):
                candidates_rejected.append(f"{candidate} :: process_session_correlation_failed")
                continue
            candidates_accepted.append(str(candidate))
            signature_matches.append(str(candidate))
            candidate_files.append(candidate)

    inventory, diagnostics = _extract_visuals_from_layout_files(
        candidate_files,
        model_object_ids=model_object_ids,
    )
    diagnostics.update(
        {
            "desktop_process_correlated_layout_files_found": len(candidate_files),
            "desktop_process_correlated_pbix_files_found": 0,
            "process_info": [
                {
                    "pid": int(proc.get("pid", 0) or 0),
                    "executable_path": str(proc.get("executable_path", "")),
                    "command_line": str(proc.get("command_line", ""))[:400],
                }
                for proc in processes[:10]
            ],
            "searched_roots": [str(path) for path in search_roots],
            "candidates_checked": [*pbix_checked[:75], *candidates_checked[:75]],
            "candidates_accepted": [*pbix_accepted[:75], *candidates_accepted[:75]],
            "candidates_rejected": [*pbix_rejected[:75], *candidates_rejected[:75]],
            "signature_matches": signature_matches[:150],
            "parser_ran": bool(candidate_files),
            "layout_like_files_found": [str(path) for path in candidate_files[:50]],
            "pbix_source_format": "",
        }
    )
    return inventory, diagnostics


def _find_pbix_layout_files(workspace_dir: Path) -> list[Path]:
    found: list[Path] = []
    try:
        for path in workspace_dir.rglob("*"):
            if not path.is_file():
                continue
            name = path.name.lower()
            if name == "layout" or name == "layout.json":
                found.append(path)
    except OSError:
        return []
    unique: list[Path] = []
    seen: set[str] = set()
    for path in found:
        key = str(path.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return sorted(unique)


def _desktop_live_search_roots(workspace_dir: Path) -> list[Path]:
    roots: list[Path] = [workspace_dir]
    parent = workspace_dir.parent
    roots.append(parent)
    roots.append(parent.parent if parent.parent != parent else parent)

    local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
    if local_appdata:
        lad = Path(local_appdata)
        roots.extend(
            [
                lad / "Microsoft" / "Power BI Desktop",
                lad / "Microsoft" / "Power BI Desktop Store App",
                lad / "Temp",
            ]
        )
    temp_env = os.environ.get("TEMP", "").strip()
    if temp_env:
        roots.append(Path(temp_env))

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            resolved = root.expanduser().resolve()
        except OSError:
            continue
        if not resolved.exists() or not resolved.is_dir():
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(resolved)
    return unique


def _layout_candidates_under_root(root: Path, *, max_depth: int) -> list[Path]:
    candidates: list[Path] = []
    root_depth = len(root.parts)
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            current = Path(dirpath)
            depth = len(current.parts) - root_depth
            if depth > max_depth:
                dirnames[:] = []
                continue
            for name in filenames:
                lower = name.lower()
                if lower in {"layout", "layout.json"}:
                    candidates.append(current / name)
                elif lower.endswith(".json") and any(token in lower for token in ("layout", "report", "visual", "section")):
                    candidates.append(current / name)
    except OSError:
        return []
    unique: list[Path] = []
    seen: set[str] = set()
    for path in sorted(candidates):
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique[:500]


def _active_pbi_desktop_processes() -> list[dict[str, Any]]:
    """Best-effort enumeration of active PBIDesktop.exe processes."""
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='PBIDesktop.exe'\" "
        "| Select-Object ProcessId,ExecutablePath,CommandLine "
        "| ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception:  # noqa: BLE001
        return []
    if result.returncode != 0:
        return []
    text = (result.stdout or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:  # noqa: BLE001
        return []
    rows = parsed if isinstance(parsed, list) else [parsed]
    processes: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        processes.append(
            {
                "pid": int(row.get("ProcessId") or 0),
                "executable_path": str(row.get("ExecutablePath") or ""),
                "command_line": str(row.get("CommandLine") or ""),
            }
        )
    return [proc for proc in processes if proc.get("pid")]


def _process_correlated_search_roots(
    workspace_dir: Path,
    processes: list[dict[str, Any]],
) -> list[Path]:
    roots: list[Path] = [workspace_dir]
    for proc in processes:
        exe = str(proc.get("executable_path", "")).strip()
        if exe:
            try:
                roots.append(Path(exe).resolve().parent)
            except OSError:
                pass
        cmd = str(proc.get("command_line", ""))
        for path_text in _extract_paths_from_command_line(cmd):
            try:
                p = Path(path_text).expanduser().resolve()
            except OSError:
                continue
            roots.append(p if p.is_dir() else p.parent)

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if not resolved.exists() or not resolved.is_dir():
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(resolved)
    return unique


def _extract_paths_from_command_line(command_line: str) -> list[str]:
    if not command_line.strip():
        return []
    quoted = re.findall(r'"([^"]+)"', command_line)
    unquoted = re.findall(r"([A-Za-z]:\\[^\\s]+(?:\\.pbix|\\.pbip|\\.json)?)", command_line)
    candidates = quoted + unquoted
    output: list[str] = []
    for candidate in candidates:
        text = candidate.strip()
        if not text:
            continue
        if any(text.lower().endswith(ext) for ext in (".pbix", ".pbip", ".json", ".pbit")):
            output.append(text)
            continue
        if "power bi" in text.lower() or "report" in text.lower() or "layout" in text.lower():
            output.append(text)
    return output


def _candidate_pbix_paths_from_processes(processes: list[dict[str, Any]]) -> list[Path]:
    candidates: list[Path] = []
    for proc in processes:
        cmd = str(proc.get("command_line", ""))
        for path_text in _extract_paths_from_command_line(cmd):
            if not path_text.lower().endswith(".pbix"):
                continue
            try:
                candidates.append(Path(path_text).expanduser().resolve())
            except OSError:
                continue
    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _candidate_correlates_to_process_session(
    candidate: Path,
    workspace_dir: Path,
    processes: list[dict[str, Any]],
) -> bool:
    if _candidate_correlates_to_session(candidate, workspace_dir):
        return True
    candidate_str = str(candidate).lower()
    for proc in processes:
        exe = str(proc.get("executable_path", "")).lower()
        cmd = str(proc.get("command_line", "")).lower()
        if exe and str(Path(exe).parent).lower() in candidate_str:
            return True
        for path_text in _extract_paths_from_command_line(cmd):
            if path_text.lower() in candidate_str:
                return True
            try:
                path_parent = str(Path(path_text).expanduser().resolve().parent).lower()
            except OSError:
                continue
            if path_parent in candidate_str:
                return True
    return False


def _file_has_layout_signature(path: Path) -> tuple[bool, str]:
    raw = _read_text_prefix(path, max_chars=65536)
    if not raw:
        return False, "read_failed_or_empty"
    lowered = raw.lower()
    has_sections = "\"sections\"" in lowered
    has_visual_containers = "\"visualcontainers\"" in lowered
    has_single_visual = "\"singlevisual\"" in lowered
    has_projections_or_queryref = "\"projections\"" in lowered or "\"queryref\"" in lowered
    if has_sections and (has_visual_containers or has_single_visual) and has_projections_or_queryref:
        return True, "signature_matched"
    return False, "signature_not_matched"


def _read_text_prefix(path: Path, *, max_chars: int) -> str:
    for encoding in ("utf-16", "utf-8", "utf-8-sig", "latin-1"):
        try:
            text = path.read_text(encoding=encoding, errors="replace")
            return text[:max_chars]
        except Exception:  # noqa: BLE001
            continue
    return ""


def _candidate_correlates_to_session(candidate: Path, workspace_dir: Path) -> bool:
    try:
        candidate_resolved = candidate.resolve()
        workspace_resolved = workspace_dir.resolve()
    except OSError:
        return False
    candidate_str = str(candidate_resolved).lower()
    workspace_str = str(workspace_resolved).lower()
    if workspace_str in candidate_str:
        return True

    workspace_token = workspace_resolved.name.lower()
    if workspace_token and workspace_token in candidate_str:
        return True

    # Time-correlation fallback: artifact updated within last 48h.
    try:
        mtime = datetime.fromtimestamp(candidate_resolved.stat().st_mtime, tz=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600.0
        if age_hours <= 48:
            return True
    except OSError:
        pass
    return False


def _load_layout_payload(path: Path) -> dict[str, Any] | None:
    for encoding in ("utf-16", "utf-8", "utf-8-sig", "latin-1"):
        try:
            text = path.read_text(encoding=encoding)
            parsed = _parse_maybe_json(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:  # noqa: BLE001
            continue
    return None


def _extract_visuals_from_layout_files(
    layout_files: list[Path],
    *,
    model_object_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    merged_inventory: dict[str, dict[str, Any]] = {}
    total_bindings = 0
    resolved_measures = 0
    resolved_columns = 0
    unresolved_count = 0
    unresolved_examples: list[str] = []

    for layout_path in layout_files:
        payload = _load_layout_payload(layout_path)
        if payload is None:
            continue
        sections = payload.get("sections", [])
        if not isinstance(sections, list):
            continue
        for section_index, section in enumerate(sections):
            if not isinstance(section, dict):
                continue
            page_name = str(
                section.get("displayName")
                or section.get("name")
                or f"Section {section_index + 1}"
            )
            page_id = str(section.get("name") or f"section_{section_index + 1}")
            containers = section.get("visualContainers", [])
            if not isinstance(containers, list):
                continue
            for container_index, container in enumerate(containers):
                if not isinstance(container, dict):
                    continue
                config_payload = _parse_maybe_json(container.get("config"))
                single_visual = {}
                if isinstance(config_payload, dict):
                    candidate_sv = config_payload.get("singleVisual", {})
                    if isinstance(candidate_sv, dict):
                        single_visual = candidate_sv

                if not single_visual:
                    candidate_sv = container.get("singleVisual", {})
                    if isinstance(candidate_sv, dict):
                        single_visual = candidate_sv

                visual_id = str(
                    container.get("name")
                    or (config_payload.get("name") if isinstance(config_payload, dict) else "")
                    or f"{page_id}_vc_{container_index + 1}"
                )
                visual_type = str(single_visual.get("visualType", "unknown"))
                visual_title = _extract_layout_title(single_visual, config_payload)
                visual_name = visual_title or visual_id

                deps: set[str] = set()
                bindings: list[dict[str, str]] = []
                unresolved_bindings: list[str] = []

                projections = single_visual.get("projections", {})
                if isinstance(projections, dict):
                    for role, role_entries in projections.items():
                        role_values = role_entries if isinstance(role_entries, list) else [role_entries]
                        for item in role_values:
                            if not isinstance(item, dict):
                                continue
                            query_ref = str(item.get("queryRef", "")).strip()
                            resolved = _resolve_binding(
                                field={},
                                query_ref=query_ref,
                                role=str(role),
                                model_object_ids=model_object_ids,
                            ) if query_ref else None
                            if resolved is None:
                                if query_ref:
                                    unresolved_bindings.append(query_ref)
                                continue
                            deps.add(resolved.target)
                            bindings.append(
                                {
                                    "role": str(role),
                                    "target": resolved.target,
                                    "source_kind": "pbix_layout_projection",
                                    "raw": query_ref,
                                }
                            )

                short_id = visual_id[:12]
                obj_id = make_object_id(
                    obj_type=ObjectType.VISUAL,
                    parent=page_name,
                    name=short_id,
                )
                merged_inventory[obj_id] = {
                    "type": "Visual",
                    "visual_id": visual_id,
                    "visual_name": visual_name,
                    "title": visual_title,
                    "visual_type": visual_type,
                    "page_id": page_id,
                    "page_name": page_name,
                    "dependencies": deps,
                    "bindings": bindings,
                    "unresolved_bindings": sorted({item for item in unresolved_bindings if item}),
                    "unknown_patterns": [],
                }
                total_bindings += len(bindings)
                resolved_measures += sum(1 for b in bindings if str(b.get("target", "")).startswith("Measure:"))
                resolved_columns += sum(1 for b in bindings if str(b.get("target", "")).startswith("Column:"))
                unresolved_count += len(merged_inventory[obj_id]["unresolved_bindings"])
                unresolved_examples.extend(merged_inventory[obj_id]["unresolved_bindings"])

    return merged_inventory, {
        "total_visuals": len(merged_inventory),
        "total_field_bindings": total_bindings,
        "bindings_resolved_measures": resolved_measures,
        "bindings_resolved_columns": resolved_columns,
        "unresolved_visual_bindings": unresolved_count,
        "unresolved_examples": sorted(dict.fromkeys(unresolved_examples))[:10],
    }


def _parse_maybe_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return None


def _extract_layout_title(single_visual: dict[str, Any], config_payload: dict[str, Any] | None) -> str:
    title_obj = single_visual.get("vcObjects", {}) if isinstance(single_visual, dict) else {}
    if isinstance(title_obj, dict):
        title = (
            title_obj.get("title", {})
            .get("properties", {})
            .get("text", {})
            .get("expr", {})
            .get("Literal", {})
            .get("Value")
        )
        if isinstance(title, str) and title.strip():
            return title.strip().strip("'")

    if isinstance(config_payload, dict):
        title = config_payload.get("displayName")
        if isinstance(title, str) and title.strip():
            return title.strip()

    return ""
