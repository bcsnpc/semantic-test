"""Shared CLI pipeline utilities for model loading and analysis."""

from __future__ import annotations

from dataclasses import dataclass
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
from semantic_test.core.parse.pbip_locator import locate_definition_folder
from semantic_test.core.parse.tmdl_parser import ParsedModel, parse_tmdl_documents
from semantic_test.core.parse.tmdl_reader import TmdlDocument, read_tmdl_documents


@dataclass(frozen=True, slots=True)
class ModelArtifacts:
    """All derived artifacts for a single model input."""

    definition_folder: str
    definition_path: str
    model_key: str
    documents: list[TmdlDocument]
    parsed_model: ParsedModel
    table_inventory: dict[str, dict[str, Any]]
    column_inventory: dict[str, dict[str, Any]]
    measure_inventory: dict[str, dict[str, Any]]
    relationship_inventory: dict[str, dict[str, Any]]
    calc_group_inventory: dict[str, dict[str, Any]]
    field_param_inventory: dict[str, dict[str, Any]]
    objects: dict[str, dict[str, Any]]
    unknown_patterns: list[dict[str, Any]]
    graph: Graph
    snapshot: Snapshot


def build_model_artifacts(input_path: str) -> ModelArtifacts:
    """Build parsed/extracted/graph/snapshot artifacts from a model path."""
    project_root = resolve_project_root(input_path)
    definition_folder = str(locate_definition_folder(input_path))
    definition_path = normalize_definition_path(definition_folder, project_root=project_root)
    model_key = build_model_key(definition_folder, project_root=project_root)
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
    unknown_patterns = _collect_unknown_patterns(objects)
    graph = build_dependency_graph(objects)
    snapshot = build_snapshot(
        objects,
        graph,
        model_key=model_key,
        definition_path=definition_path,
        unknown_patterns=unknown_patterns,
    )
    return ModelArtifacts(
        definition_folder=definition_folder,
        definition_path=definition_path,
        model_key=model_key,
        documents=documents,
        parsed_model=parsed_model,
        table_inventory=table_inventory,
        column_inventory=column_inventory,
        measure_inventory=measure_inventory,
        relationship_inventory=relationship_inventory,
        calc_group_inventory=calc_group_inventory,
        field_param_inventory=field_param_inventory,
        objects=objects,
        unknown_patterns=unknown_patterns,
        graph=graph,
        snapshot=snapshot,
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
