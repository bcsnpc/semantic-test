"""Shared CLI pipeline utilities for model loading and analysis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from semantic_test.core.diff.snapshot import Snapshot, build_snapshot
from semantic_test.core.graph.builder import Graph, build_dependency_graph
from semantic_test.core.model.model_key import (
    build_model_key,
    normalize_definition_path,
    resolve_project_root,
)
from semantic_test.core.parse.extractors.calc_groups import extract_calc_groups
from semantic_test.core.parse.extractors.columns import extract_columns
from semantic_test.core.parse.extractors.field_params import extract_field_params
from semantic_test.core.parse.extractors.measures import extract_measures
from semantic_test.core.parse.extractors.relationships import extract_relationships
from semantic_test.core.parse.extractors.tables import extract_tables
from semantic_test.core.parse.extractors.report_visuals import (
    extract_report_visuals_with_diagnostics,
)
from semantic_test.core.parse.pbip_locator import (
    discover_definition_folders,
    locate_definition_folder,
)
from semantic_test.core.parse.report_locator import locate_report_folder
from semantic_test.core.parse.tmdl_parser import ParsedModel, parse_tmdl_documents
from semantic_test.core.parse.tmdl_reader import TmdlDocument, read_tmdl_documents


@dataclass(frozen=True, slots=True)
class ModelArtifacts:
    """All derived artifacts for a single model input."""

    definition_folder: str
    scan_input_path: str
    definition_path: str
    model_key: str
    selected_model_definition_path: str
    models_detected_count: int
    models_detected: list[dict[str, str]]
    documents: list[TmdlDocument]
    parsed_model: ParsedModel
    table_inventory: dict[str, dict[str, Any]]
    column_inventory: dict[str, dict[str, Any]]
    measure_inventory: dict[str, dict[str, Any]]
    relationship_inventory: dict[str, dict[str, Any]]
    calc_group_inventory: dict[str, dict[str, Any]]
    field_param_inventory: dict[str, dict[str, Any]]
    visual_inventory: dict[str, dict[str, Any]]
    objects: dict[str, dict[str, Any]]
    unknown_patterns: list[dict[str, Any]]
    graph: Graph
    snapshot: Snapshot
    diagnostics: dict[str, Any]


def build_model_artifacts(input_path: str) -> ModelArtifacts:
    """Build parsed/extracted/graph/snapshot artifacts from a model path."""
    project_root = resolve_project_root(input_path)
    discovered = discover_definition_folders(input_path)
    definition_folder = str(locate_definition_folder(input_path))
    definition_path = normalize_definition_path(definition_folder, project_root=project_root)
    model_key = build_model_key(definition_folder, project_root=project_root)
    selected_model_definition_path = definition_folder
    detected_models: list[dict[str, str]] = []
    for definition_candidate in discovered:
        detected_models.append(
            {
                "model_key": build_model_key(str(definition_candidate), project_root=project_root),
                "definition_path": str(definition_candidate),
            }
        )
    detected_models.sort(key=lambda item: item["definition_path"])
    documents = read_tmdl_documents(definition_folder)
    parsed_model = parse_tmdl_documents(documents)

    table_inventory = extract_tables(parsed_model)
    column_inventory = extract_columns(parsed_model)
    measure_inventory = extract_measures(parsed_model)
    relationship_inventory = extract_relationships(parsed_model)
    calc_group_inventory = extract_calc_groups(parsed_model, documents)
    field_param_inventory = extract_field_params(parsed_model, documents)

    objects = _merge_inventories(
        table_inventory,
        column_inventory,
        measure_inventory,
        relationship_inventory,
        calc_group_inventory,
        field_param_inventory,
    )

    # Auto-discover adjacent .Report folder and add visual nodes
    report_folder = locate_report_folder(definition_folder)
    visual_inventory: dict[str, dict[str, Any]] = {}
    if report_folder is not None:
        visual_inventory, visual_diag = extract_report_visuals_with_diagnostics(
            report_folder,
            set(objects.keys()),
        )
        objects = _merge_inventories(objects, visual_inventory)
    else:
        visual_diag = None

    unknown_patterns = _collect_unknown_patterns(objects)
    graph = build_dependency_graph(objects)
    object_type_counts = _object_type_counts(objects)
    edge_category_counts = _edge_category_counts(objects, graph)
    snapshot = build_snapshot(
        objects,
        graph,
        model_key=model_key,
        definition_path=definition_path,
        unknown_patterns=unknown_patterns,
    )
    return ModelArtifacts(
        definition_folder=definition_folder,
        scan_input_path=str(input_path),
        definition_path=definition_path,
        model_key=model_key,
        selected_model_definition_path=selected_model_definition_path,
        models_detected_count=len(detected_models),
        models_detected=detected_models,
        documents=documents,
        parsed_model=parsed_model,
        table_inventory=table_inventory,
        column_inventory=column_inventory,
        measure_inventory=measure_inventory,
        relationship_inventory=relationship_inventory,
        calc_group_inventory=calc_group_inventory,
        field_param_inventory=field_param_inventory,
        visual_inventory=visual_inventory,
        objects=objects,
        unknown_patterns=unknown_patterns,
        graph=graph,
        snapshot=snapshot,
        diagnostics={
            "source": "pbip",
            "visual_lineage": {
                "status": "available" if visual_inventory else "unavailable",
                "reason": "" if visual_inventory else "no_adjacent_report_folder_or_no_visual_bindings",
            },
            "semantic_inventory": {
                "object_type_counts": object_type_counts,
                "edge_category_counts": edge_category_counts,
            },
            "visual_mapping": {
                "total_visuals": int(visual_diag.total_visuals) if visual_diag else 0,
                "total_field_bindings": int(visual_diag.total_bindings_extracted) if visual_diag else 0,
                "bindings_resolved_measures": int(visual_diag.bindings_resolved_measures) if visual_diag else 0,
                "bindings_resolved_columns": int(visual_diag.bindings_resolved_columns) if visual_diag else 0,
                "unresolved_visual_bindings": int(visual_diag.unresolved_binding_count) if visual_diag else 0,
                "unresolved_examples": list(visual_diag.unresolved_examples) if visual_diag else [],
            },
        },
    )


def build_model_artifacts_from_desktop(
    port: int,
    *,
    workspace_dir: str | None = None,
) -> ModelArtifacts:
    """Build ModelArtifacts from a live Power BI Desktop AS instance via DMV.

    Connects to the local Analysis Services running at ``localhost:<port>``,
    queries schema DMVs (tables, columns, measures, relationships), and builds
    the same ``ModelArtifacts`` structure as ``build_model_artifacts()`` so the
    rest of the scan pipeline is unaware of the source.

    Raises
    ------
    RuntimeError
        If pyodbc is not installed or the connection / DMV queries fail.
    """
    from semantic_test.core.live.dmv_schema import extract_desktop_schema
    from semantic_test.core.live.report_visuals import extract_desktop_visuals
    from semantic_test.core.parse.extractors.measures import (
        build_reference_registry_from_inventory,
        extract_expression_dependencies,
    )

    schema = extract_desktop_schema(port)
    catalog = schema.catalog_name

    # Build lookup: table_id → table_name
    id_to_table: dict[object, str] = {t["id"]: str(t["name"]) for t in schema.tables}
    resolver_registry = build_reference_registry_from_inventory(
        table_names=[str(t.get("name", "")) for t in schema.tables],
        columns=[
            (str(id_to_table.get(c.get("table_id"), "")), str(c.get("name", "")))
            for c in schema.columns
        ],
        measures=[
            (str(id_to_table.get(m.get("table_id"), "")), str(m.get("name", "")))
            for m in schema.measures
        ],
    )

    # --- Table inventory ---
    table_inventory: dict[str, dict[str, Any]] = {}
    for t in schema.tables:
        name = str(t["name"])
        obj_id = f"Table:{name}"
        table_inventory[obj_id] = {
            "type": "Table",
            "name": name,
            "dependencies": set(),
            "is_hidden": bool(t.get("is_hidden", False)),
        }

    # --- Column inventory ---
    column_inventory: dict[str, dict[str, Any]] = {}
    for c in schema.columns:
        col_name = str(c["name"])
        if not col_name:
            continue
        table_name = str(id_to_table.get(c["table_id"], ""))
        if not table_name:
            continue
        obj_id = f"Column:{table_name}.{col_name}"
        column_inventory[obj_id] = {
            "type": "Column",
            "name": col_name,
            "table": table_name,
            "dependencies": set(),
            "is_hidden": bool(c.get("is_hidden", False)),
        }

    # --- Measure inventory (with DAX dependency extraction) ---
    all_ids: set[str] = set(table_inventory) | set(column_inventory)
    measure_inventory: dict[str, dict[str, Any]] = {}
    for m in schema.measures:
        measure_name = str(m["name"])
        if not measure_name:
            continue
        table_name = str(id_to_table.get(m["table_id"], ""))
        obj_id = f"Measure:{table_name}.{measure_name}" if table_name else f"Measure:{measure_name}"
        expression = str(m.get("expression", ""))
        deps: set[str] = set()
        unknown_patterns: list[str] = []
        if expression:
            deps, unknown_patterns = extract_expression_dependencies(
                expression=expression,
                current_measure_id=obj_id,
                current_table=table_name or None,
                reference_registry=resolver_registry,
            )
        measure_inventory[obj_id] = {
            "type": "Measure",
            "name": measure_name,
            "table": table_name,
            "raw_expression": expression,
            "dependencies": deps,
            "unknown_patterns": unknown_patterns,
        }

    # --- Relationship inventory ---
    relationship_inventory: dict[str, dict[str, Any]] = {}
    col_id_to_name: dict[object, str] = {
        c.get("id"): str(c.get("name", ""))
        for c in schema.columns
        if c.get("id") is not None and str(c.get("name", "")).strip()
    }
    for rel in schema.relationships:
        from_table = str(id_to_table.get(rel["from_table_id"], ""))
        to_table = str(id_to_table.get(rel["to_table_id"], ""))
        from_col_id = rel.get("from_column_id")
        to_col_id = rel.get("to_column_id")
        from_col = col_id_to_name.get(from_col_id, str(from_col_id or ""))
        to_col = col_id_to_name.get(to_col_id, str(to_col_id or ""))
        if not all([from_table, to_table]):
            continue
        obj_id = f"Rel:{from_table}.{from_col}->{to_table}.{to_col}"
        relationship_inventory[obj_id] = {
            "type": "Rel",
            "from_table": from_table,
            "from_column": from_col,
            "to_table": to_table,
            "to_column": to_col,
            "is_active": bool(rel.get("is_active", True)),
            "dependencies": set(),
            "is_complete": bool(from_table and from_col and to_table and to_col),
        }

    objects = _merge_inventories(
        table_inventory,
        column_inventory,
        measure_inventory,
        relationship_inventory,
    )
    visual_inventory: dict[str, dict[str, Any]] = {}
    visual_diagnostics: dict[str, Any] = {}
    if workspace_dir:
        visual_inventory, visual_diagnostics = extract_desktop_visuals(
            Path(workspace_dir),
            model_object_ids=set(objects.keys()),
        )
        if visual_inventory:
            objects = _merge_inventories(objects, visual_inventory)
    unknown_patterns_list = _collect_unknown_patterns(objects)
    graph = build_dependency_graph(objects)
    object_type_counts = _object_type_counts(objects)
    edge_category_counts = _edge_category_counts(objects, graph)
    model_key = f"desktop::{catalog}"
    definition_folder = f"desktop://localhost:{port}/{catalog}"
    snapshot = build_snapshot(
        objects,
        graph,
        model_key=model_key,
        definition_path=definition_folder,
        unknown_patterns=unknown_patterns_list,
    )

    unresolved_measure_with_known_name = 0
    for meta in measure_inventory.values():
        patterns = meta.get("unknown_patterns", [])
        if not isinstance(patterns, list):
            continue
        for pattern in patterns:
            text = str(pattern)
            if not text.startswith("unresolved_measure:[") or not text.endswith("]"):
                continue
            query = text[len("unresolved_measure:[") : -1].strip().lower()
            known_names = {str(name).strip().lower() for _table, name in resolver_registry.get("all_measures", [])}
            if query in known_names:
                unresolved_measure_with_known_name += 1

    diagnostics = {
        "source": "desktop",
        "schema_counts": {
            "tables": len(schema.tables),
            "columns": len(schema.columns),
            "measures": len(schema.measures),
            "relationships": len(schema.relationships),
        },
        "inventory_counts": {
            "tables": len(table_inventory),
            "columns": len(column_inventory),
            "measures": len(measure_inventory),
            "relationships": len(relationship_inventory),
        },
        "resolver_index_counts": {
            "qualified_columns": len(resolver_registry.get("columns_by_table_lower", {})),
            "measure_name_keys": len(resolver_registry.get("measure_name_to_ids", {})),
            "measure_name_keys_canonical": len(resolver_registry.get("measure_name_to_ids_canonical", {})),
            "all_columns": len(resolver_registry.get("all_columns", [])),
            "all_measures": len(resolver_registry.get("all_measures", [])),
        },
        "expression_diagnostics": {
            "measures_with_empty_expression": sum(
                1 for m in schema.measures if not str(m.get("expression", "")).strip()
            ),
            "unresolved_measure_with_known_name": unresolved_measure_with_known_name,
        },
        "lookup_gaps": {
            "columns_without_table_match": sum(
                1 for c in schema.columns if not str(id_to_table.get(c.get("table_id"), "")).strip()
            ),
            "measures_without_table_match": sum(
                1 for m in schema.measures if not str(id_to_table.get(m.get("table_id"), "")).strip()
            ),
            "relationships_with_unmapped_column_ids": sum(
                1
                for rel in schema.relationships
                if rel.get("from_column_id") not in col_id_to_name
                or rel.get("to_column_id") not in col_id_to_name
            ),
        },
        "parity_notes": [
            "Desktop/PBIP parity is approximate because Desktop DMV metadata can differ from TMDL extraction.",
            "Use resolver_index_counts + lookup_gaps to identify edge-count divergence drivers.",
        ],
        "visual_lineage": {
            "status": str(visual_diagnostics.get("visual_lineage_status", "unknown")),
            "reason": str(visual_diagnostics.get("visual_lineage_reason", "")),
        },
        "semantic_inventory": {
            "object_type_counts": object_type_counts,
            "edge_category_counts": edge_category_counts,
            "desktop_column_classification": _classify_desktop_columns(column_inventory),
            "semantic_limitations": {
                "calc_groups_items_from_desktop_dmv": "not_extracted",
                "note": "Desktop semantic extraction currently excludes calculation groups/items from live DMV path.",
            },
        },
        "visual_mapping": visual_diagnostics.get("visual_mapping", {"total_visuals": len(visual_inventory)}),
        "visual_workspace": visual_diagnostics.get("workspace_dir", ""),
        "visual_report_root": visual_diagnostics.get("report_root", ""),
        "visual_discovery": {
            "strategies_tried": list(visual_diagnostics.get("strategies_tried", [])),
            "candidate_report_roots_checked": list(visual_diagnostics.get("candidate_report_roots_checked", [])),
            "standard_layout_exists": bool(visual_diagnostics.get("standard_layout_exists", False)),
            "visual_json_files_found": int(visual_diagnostics.get("visual_json_files_found", 0)),
            "page_json_files_found": int(visual_diagnostics.get("page_json_files_found", 0)),
            "report_json_files_found": int(visual_diagnostics.get("report_json_files_found", 0)),
            "pbix_layout_files_found": int(visual_diagnostics.get("pbix_layout_files_found", 0)),
            "desktop_live_pbix_layout_files_found": int(visual_diagnostics.get("desktop_live_pbix_layout_files_found", 0)),
            "desktop_process_correlated_layout_files_found": int(visual_diagnostics.get("desktop_process_correlated_layout_files_found", 0)),
            "desktop_process_correlated_pbix_files_found": int(visual_diagnostics.get("desktop_process_correlated_pbix_files_found", 0)),
            "layout_like_files_found": list(visual_diagnostics.get("layout_like_files_found", [])),
            "alternate_candidates_found": list(visual_diagnostics.get("alternate_candidates_found", [])),
            "alternate_parser_ran": bool(visual_diagnostics.get("alternate_parser_ran", False)),
            "recursive_visual_scan_used": bool(visual_diagnostics.get("recursive_visual_scan_used", False)),
            "pbix_layout_scan_used": bool(visual_diagnostics.get("pbix_layout_scan_used", False)),
            "desktop_live_pbix_layout_scan_used": bool(visual_diagnostics.get("desktop_live_pbix_layout_scan_used", False)),
            "desktop_process_correlated_layout_scan_used": bool(visual_diagnostics.get("desktop_process_correlated_layout_scan_used", False)),
            "desktop_live_search_roots": list(visual_diagnostics.get("desktop_live_search_roots", [])),
            "desktop_live_candidates_checked": list(visual_diagnostics.get("desktop_live_candidates_checked", [])),
            "desktop_live_candidates_accepted": list(visual_diagnostics.get("desktop_live_candidates_accepted", [])),
            "desktop_live_candidates_rejected": list(visual_diagnostics.get("desktop_live_candidates_rejected", [])),
            "desktop_live_signature_matches": list(visual_diagnostics.get("desktop_live_signature_matches", [])),
            "desktop_live_parser_ran": bool(visual_diagnostics.get("desktop_live_parser_ran", False)),
            "desktop_process_info": list(visual_diagnostics.get("desktop_process_info", [])),
            "desktop_process_search_roots": list(visual_diagnostics.get("desktop_process_search_roots", [])),
            "desktop_process_candidates_checked": list(visual_diagnostics.get("desktop_process_candidates_checked", [])),
            "desktop_process_candidates_accepted": list(visual_diagnostics.get("desktop_process_candidates_accepted", [])),
            "desktop_process_candidates_rejected": list(visual_diagnostics.get("desktop_process_candidates_rejected", [])),
            "desktop_process_signature_matches": list(visual_diagnostics.get("desktop_process_signature_matches", [])),
            "desktop_process_parser_ran": bool(visual_diagnostics.get("desktop_process_parser_ran", False)),
            "desktop_process_pbix_source_format": str(visual_diagnostics.get("desktop_process_pbix_source_format", "")),
            "empty_reason": str(visual_diagnostics.get("empty_reason", "")),
        },
    }

    return ModelArtifacts(
        definition_folder=definition_folder,
        scan_input_path=f"desktop:{port}",
        definition_path=definition_folder,
        model_key=model_key,
        selected_model_definition_path=definition_folder,
        models_detected_count=1,
        models_detected=[{"model_key": model_key, "definition_path": definition_folder}],
        documents=[],
        parsed_model=None,  # type: ignore[arg-type]
        table_inventory=table_inventory,
        column_inventory=column_inventory,
        measure_inventory=measure_inventory,
        relationship_inventory=relationship_inventory,
        calc_group_inventory={},
        field_param_inventory={},
        visual_inventory=visual_inventory,
        objects=objects,
        unknown_patterns=unknown_patterns_list,
        graph=graph,
        snapshot=snapshot,
        diagnostics=diagnostics,
    )


def _merge_inventories(
    *inventories: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for inventory in inventories:
        merged.update(inventory)
    return merged


def _collect_unknown_patterns(
    objects: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for object_id in sorted(objects.keys()):
        metadata = objects[object_id]
        patterns = metadata.get("unknown_patterns", [])
        if not isinstance(patterns, list):
            continue
        cleaned = sorted({str(item) for item in patterns if str(item).strip()})
        if not cleaned:
            continue
        output.append({"object_id": object_id, "patterns": cleaned})
    return output


def _object_type_counts(objects: dict[str, dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for metadata in objects.values():
        key = str(metadata.get("type", "Unknown"))
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: item[0]))


def _edge_category_counts(
    objects: dict[str, dict[str, Any]],
    graph: Graph,
) -> dict[str, int]:
    rel_pairs = _relationship_column_pairs(objects)
    counts = {
        "measure_to_measure": 0,
        "measure_to_column": 0,
        "calc_item_to_measure": 0,
        "calc_item_to_column": 0,
        "relationship_edges": 0,
        "visual_to_measure": 0,
        "visual_to_column": 0,
        "other": 0,
    }
    for edge in graph.edges:
        src = objects.get(edge.source, {})
        dst = objects.get(edge.target, {})
        src_type = str(src.get("type", "Unknown"))
        dst_type = str(dst.get("type", "Unknown"))
        pair_key = (edge.source, edge.target)

        if pair_key in rel_pairs:
            counts["relationship_edges"] += 1
            continue
        if src_type == "Measure" and dst_type == "Measure":
            counts["measure_to_measure"] += 1
            continue
        if src_type == "Measure" and dst_type == "Column":
            counts["measure_to_column"] += 1
            continue
        if src_type == "CalcItem" and dst_type == "Measure":
            counts["calc_item_to_measure"] += 1
            continue
        if src_type == "CalcItem" and dst_type == "Column":
            counts["calc_item_to_column"] += 1
            continue
        if src_type == "Visual" and dst_type == "Measure":
            counts["visual_to_measure"] += 1
            continue
        if src_type == "Visual" and dst_type == "Column":
            counts["visual_to_column"] += 1
            continue
        counts["other"] += 1
    return counts


def _relationship_column_pairs(objects: dict[str, dict[str, Any]]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for metadata in objects.values():
        if str(metadata.get("type", "")) != "Rel":
            continue
        from_table = str(metadata.get("from_table", "")).strip()
        from_column = str(metadata.get("from_column", "")).strip()
        to_table = str(metadata.get("to_table", "")).strip()
        to_column = str(metadata.get("to_column", "")).strip()
        if not all([from_table, from_column, to_table, to_column]):
            continue
        left = f"Column:{from_table}.{from_column}"
        right = f"Column:{to_table}.{to_column}"
        pairs.add((left, right))
        pairs.add((right, left))
    return pairs


def _classify_desktop_columns(
    column_inventory: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    hidden = 0
    visible = 0
    local_date = 0
    technical = 0
    local_date_samples: list[str] = []
    technical_samples: list[str] = []
    for object_id, metadata in column_inventory.items():
        table_name = str(metadata.get("table", "")).lower()
        column_name = str(metadata.get("name", "")).lower()
        is_hidden = bool(metadata.get("is_hidden", False))
        if is_hidden:
            hidden += 1
        else:
            visible += 1
        if table_name.startswith("localdatetable_") or "localdate" in table_name:
            local_date += 1
            if len(local_date_samples) < 10:
                local_date_samples.append(object_id)
        if column_name.startswith("rownumber") or column_name.startswith("__") or "autodate" in table_name:
            technical += 1
            if len(technical_samples) < 10:
                technical_samples.append(object_id)
    return {
        "total": len(column_inventory),
        "hidden": hidden,
        "visible": visible,
        "local_date_table_like": local_date,
        "technical_like": technical,
        "local_date_samples": local_date_samples,
        "technical_samples": technical_samples,
    }
