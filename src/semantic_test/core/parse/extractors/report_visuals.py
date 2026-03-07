"""Extractor for Power BI report visual field dependencies."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Any
import zipfile

from semantic_test.core.model.objects import ObjectType, object_id as make_object_id

# All known visual query-state role keys that contain field projections
_PROJECTION_ROLES = {
    "Values",
    "Category",
    "Y",
    "X",
    "Series",
    "Legend",
    "Tooltips",
    "Size",
    "Color",
    "Details",
    "Group",
    "Rows",
    "Columns",
    "Fields",
    "Small multiples",
    "Play axis",
    "xaxis",
    "yaxis",
    "values",
    "legend",
    "tooltip",
    "tooltips",
    "smallmultiples",
    "small multiples",
    "category",
    "series",
}

# Regex to parse "Sum(table.column)" style metadata selectors
_METADATA_RE = re.compile(r"^(?:\w+\()?([^.()\s]+)\.(.+?)(?:\))?$")
_BRACKETED_REF_RE = re.compile(r"^'?(?P<table>[^'\[]+)'?\[(?P<name>[^\]]+)\]$")
_QUERYREF_SIMPLE_RE = re.compile(r"^(?P<table>[^.]+)\.(?P<name>.+)$")


@dataclass(frozen=True, slots=True)
class VisualBinding:
    role: str
    target: str
    source_kind: str
    raw: str


@dataclass(frozen=True, slots=True)
class VisualExtractionDiagnostics:
    total_visuals: int
    total_bindings_extracted: int
    bindings_resolved_measures: int
    bindings_resolved_columns: int
    unresolved_binding_count: int
    unresolved_examples: list[str]


@dataclass(frozen=True, slots=True)
class PbixVisualExtractionDiagnostics:
    source_format: str
    total_visuals: int
    total_bindings_extracted: int
    bindings_resolved_measures: int
    bindings_resolved_columns: int
    unresolved_binding_count: int
    unresolved_examples: list[str]
    layout_entries_checked: list[str]


def extract_report_visuals(
    report_folder: Path,
    model_object_ids: set[str],
) -> dict[str, dict[str, Any]]:
    inventory, _diag = extract_report_visuals_with_diagnostics(report_folder, model_object_ids)
    return inventory


def extract_pbix_visuals(
    pbix_path: Path,
    model_object_ids: set[str],
) -> dict[str, dict[str, Any]]:
    inventory, _diag = extract_pbix_visuals_with_diagnostics(pbix_path, model_object_ids)
    return inventory


def extract_pbix_visuals_with_diagnostics(
    pbix_path: Path,
    model_object_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], PbixVisualExtractionDiagnostics]:
    """Extract visual lineage from a PBIX file (legacy Layout or PBIR-like entries)."""
    if not pbix_path.exists() or not pbix_path.is_file():
        empty = PbixVisualExtractionDiagnostics(
            source_format="not_found",
            total_visuals=0,
            total_bindings_extracted=0,
            bindings_resolved_measures=0,
            bindings_resolved_columns=0,
            unresolved_binding_count=0,
            unresolved_examples=[],
            layout_entries_checked=[],
        )
        return {}, empty

    try:
        with zipfile.ZipFile(pbix_path, "r") as zf:
            names = zf.namelist()
            legacy_layout_entries = [name for name in names if name.lower().endswith("report/layout")]
            legacy_layout_json_entries = [name for name in names if name.lower().endswith("report/layout.json")]
            pbir_visual_entries = [name for name in names if name.lower().endswith("visual.json")]

            if pbir_visual_entries:
                inventory, diag = _extract_from_pbir_zip_entries(
                    zf,
                    visual_entries=pbir_visual_entries,
                    model_object_ids=model_object_ids,
                )
                return inventory, PbixVisualExtractionDiagnostics(
                    source_format="pbir_in_pbix",
                    total_visuals=diag.total_visuals,
                    total_bindings_extracted=diag.total_bindings_extracted,
                    bindings_resolved_measures=diag.bindings_resolved_measures,
                    bindings_resolved_columns=diag.bindings_resolved_columns,
                    unresolved_binding_count=diag.unresolved_binding_count,
                    unresolved_examples=diag.unresolved_examples,
                    layout_entries_checked=pbir_visual_entries[:50],
                )

            for entry in [*legacy_layout_entries, *legacy_layout_json_entries]:
                payload = _load_layout_payload_from_zip_entry(zf, entry)
                if payload is None:
                    continue
                inventory, diag = _extract_from_legacy_layout_payload(
                    payload=payload,
                    model_object_ids=model_object_ids,
                )
                if inventory:
                    return inventory, PbixVisualExtractionDiagnostics(
                        source_format="pbix_legacy_layout",
                        total_visuals=diag["total_visuals"],
                        total_bindings_extracted=diag["total_field_bindings"],
                        bindings_resolved_measures=diag["bindings_resolved_measures"],
                        bindings_resolved_columns=diag["bindings_resolved_columns"],
                        unresolved_binding_count=diag["unresolved_visual_bindings"],
                        unresolved_examples=diag["unresolved_examples"],
                        layout_entries_checked=[entry],
                    )
    except Exception:  # noqa: BLE001
        pass

    empty = PbixVisualExtractionDiagnostics(
        source_format="none",
        total_visuals=0,
        total_bindings_extracted=0,
        bindings_resolved_measures=0,
        bindings_resolved_columns=0,
        unresolved_binding_count=0,
        unresolved_examples=[],
        layout_entries_checked=[],
    )
    return {}, empty


def extract_report_visuals_with_diagnostics(
    report_folder: Path,
    model_object_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], VisualExtractionDiagnostics]:
    """Parse all pages and visuals in a .Report folder.

    Returns a visual inventory compatible with the existing model object format::

        {
            "Visual:PageName.visual_id_short": {
                "type": "Visual",
                "visual_id": "full_visual_id",
                "visual_type": "barChart",
                "page_id": "07f281208d044a1a6ad6",
                "page_name": "Client Feedback",
                "dependencies": {"Measure:Metrics.Total", "Column:Sales.Amount"},
                "unknown_patterns": [],
            },
            ...
        }

    Parameters
    ----------
    report_folder:
        Root of the ``.Report`` directory (contains ``definition/pages/``).
    model_object_ids:
        Set of all known object IDs from the semantic model.  Used to validate
        field references; unresolved refs are still included in dependencies.
    """
    pages_root = report_folder / "definition" / "pages"
    if not pages_root.exists():
        empty = VisualExtractionDiagnostics(
            total_visuals=0,
            total_bindings_extracted=0,
            bindings_resolved_measures=0,
            bindings_resolved_columns=0,
            unresolved_binding_count=0,
            unresolved_examples=[],
        )
        return {}, empty

    inventory: dict[str, dict[str, Any]] = {}
    total_bindings = 0
    resolved_measures = 0
    resolved_columns = 0
    unresolved_count = 0
    unresolved_examples: list[str] = []

    for page_dir in sorted(pages_root.iterdir()):
        if not page_dir.is_dir():
            continue
        page_id = page_dir.name
        page_name, page_filters = _parse_page(page_dir)

        visuals_dir = page_dir / "visuals"
        if not visuals_dir.exists():
            continue

        for visual_dir in sorted(visuals_dir.iterdir()):
            if not visual_dir.is_dir():
                continue
            visual_json_path = visual_dir / "visual.json"
            if not visual_json_path.exists():
                continue

            visual_id = visual_dir.name
            visual_data = _load_json(visual_json_path)
            if visual_data is None:
                continue

            visual_section = visual_data.get("visual", {})
            visual_type: str = visual_section.get("visualType", "unknown")
            visual_name = str(visual_data.get("name", visual_id))
            visual_title = _extract_visual_title(visual_data)
            deps = set(page_filters)  # inherit page-level filter fields
            bindings: list[VisualBinding] = []
            unresolved_bindings: list[str] = []

            # Walk queryState projection roles
            query_state = (
                visual_section
                .get("query", {})
                .get("queryState", {})
            )
            for role, role_data in query_state.items():
                role_norm = _normalize_role(role)
                if role_norm == "sortdefinition":
                    # Sort refs are also field references
                    for sort_item in role_data.get("sort", []):
                        resolved = _resolve_binding(
                            sort_item.get("field", {}),
                            sort_item.get("queryRef"),
                            role="sort",
                            model_object_ids=model_object_ids,
                        )
                        if resolved is not None:
                            deps.add(resolved.target)
                            bindings.append(VisualBinding(role="sort", target=resolved.target, source_kind=resolved.source_kind, raw=resolved.raw))
                        elif sort_item.get("queryRef"):
                            unresolved_bindings.append(str(sort_item.get("queryRef")))
                    continue
                if role in _PROJECTION_ROLES or role_norm in _PROJECTION_ROLES:
                    for proj in role_data.get("projections", []):
                        resolved = _resolve_binding(
                            proj.get("field", {}),
                            proj.get("queryRef"),
                            role=role,
                            model_object_ids=model_object_ids,
                        )
                        if resolved is not None:
                            deps.add(resolved.target)
                            bindings.append(VisualBinding(role=role, target=resolved.target, source_kind=resolved.source_kind, raw=resolved.raw))
                        else:
                            unresolved_bindings.append(str(proj.get("queryRef", "")))

            # Visual-level filters
            for f in visual_section.get("filterConfig", {}).get("filters", []):
                resolved = _resolve_binding(
                    f.get("field", {}),
                    None,
                    role="filter",
                    model_object_ids=model_object_ids,
                )
                if resolved is not None:
                    deps.add(resolved.target)
                    bindings.append(VisualBinding(role="filter", target=resolved.target, source_kind=resolved.source_kind, raw=resolved.raw))

            # Remove self-references to objects that don't exist (keep all for graph edges)
            short_id = visual_id[:12]
            obj_id = make_object_id(
                obj_type=ObjectType.VISUAL,
                parent=page_name or page_id,
                name=short_id,
            )

            inventory[obj_id] = {
                "type": "Visual",
                "visual_id": visual_id,
                "visual_name": visual_name,
                "title": visual_title,
                "visual_type": visual_type,
                "page_id": page_id,
                "page_name": page_name or page_id,
                "dependencies": deps,
                "bindings": [
                    {
                        "role": b.role,
                        "target": b.target,
                        "source_kind": b.source_kind,
                        "raw": b.raw,
                    }
                    for b in bindings
                ],
                "unresolved_bindings": sorted({item for item in unresolved_bindings if item}),
                "unknown_patterns": [],
            }
            total_bindings += len(bindings)
            resolved_measures += sum(1 for b in bindings if b.target.startswith("Measure:"))
            resolved_columns += sum(1 for b in bindings if b.target.startswith("Column:"))
            unresolved_count += len(inventory[obj_id]["unresolved_bindings"])
            for unresolved in inventory[obj_id]["unresolved_bindings"]:
                unresolved_examples.append(unresolved)

    diagnostics = VisualExtractionDiagnostics(
        total_visuals=len(inventory),
        total_bindings_extracted=total_bindings,
        bindings_resolved_measures=resolved_measures,
        bindings_resolved_columns=resolved_columns,
        unresolved_binding_count=unresolved_count,
        unresolved_examples=sorted(dict.fromkeys(unresolved_examples))[:10],
    )
    return inventory, diagnostics


def _parse_page(page_dir: Path) -> tuple[str, set[str]]:
    """Return (display_name, filter_field_ids) for a page."""
    page_json_path = page_dir / "page.json"
    if not page_json_path.exists():
        return page_dir.name, set()

    data = _load_json(page_json_path)
    if data is None:
        return page_dir.name, set()

    display_name: str = data.get("displayName") or page_dir.name
    filter_refs: set[str] = set()
    for f in data.get("filterConfig", {}).get("filters", []):
        ref = _extract_field_ref(f.get("field", {}))
        if ref:
            filter_refs.add(ref)

    return display_name, filter_refs


def _extract_field_ref(field: dict[str, Any]) -> str | None:
    """Extract canonical object ID from a visual field dict.

    Handles both::

        {"Column": {"Expression": {"SourceRef": {"Entity": "T"}}, "Property": "C"}}
        {"Measure": {"Expression": {"SourceRef": {"Entity": "T"}}, "Property": "M"}}
    """
    if not field:
        return None

    for field_kind, obj_type_enum in (
        ("Column", ObjectType.COLUMN),
        ("Measure", ObjectType.MEASURE),
    ):
        if field_kind not in field:
            continue
        inner = field[field_kind]
        entity: str = (
            inner.get("Expression", {})
            .get("SourceRef", {})
            .get("Entity", "")
        )
        prop: str = inner.get("Property", "")
        if not prop:
            return None
        if obj_type_enum is ObjectType.COLUMN:
            if entity:
                return f"Column:{entity}.{prop}"
            return None
        # Measure
        if entity:
            return f"Measure:{entity}.{prop}"
        return f"Measure:{prop}"

    return None


def _resolve_binding(
    field: dict[str, Any],
    query_ref: str | None,
    *,
    role: str,
    model_object_ids: set[str],
) -> VisualBinding | None:
    direct = _extract_field_ref(field)
    if direct:
        return VisualBinding(role=role, target=direct, source_kind="entity_property", raw=str(field))
    if query_ref:
        resolved = _queryref_to_object_id(
            str(query_ref),
            role=role,
            model_object_ids=model_object_ids,
        )
        if resolved:
            return VisualBinding(role=role, target=resolved, source_kind="query_ref", raw=str(query_ref))
    return None


def _queryref_to_object_id(
    query_ref: str,
    *,
    role: str,
    model_object_ids: set[str],
) -> str | None:
    raw = query_ref.strip()
    if not raw:
        return None
    bracketed = _BRACKETED_REF_RE.match(raw)
    if bracketed:
        table = bracketed.group("table").strip().strip("'")
        name = bracketed.group("name").strip()
        if table and name:
            return f"Column:{table}.{name}"
    if "(" in raw:
        metadata = _METADATA_RE.match(raw)
        if metadata:
            table = metadata.group(1).strip().strip("'")
            name = metadata.group(2).strip()
            if table and name:
                return f"Column:{table}.{name}"
    simple = _QUERYREF_SIMPLE_RE.match(raw)
    if simple:
        table = simple.group("table").strip().strip("'")
        name = simple.group("name").strip()
        if not table or not name:
            return None
        measure_candidate = f"Measure:{table}.{name}"
        column_candidate = f"Column:{table}.{name}"
        if model_object_ids:
            measure_exists = measure_candidate in model_object_ids
            column_exists = column_candidate in model_object_ids
            if measure_exists and not column_exists:
                return measure_candidate
            if column_exists and not measure_exists:
                return column_candidate
            if measure_exists and column_exists:
                return measure_candidate if _prefer_measure_role(role) else column_candidate
        return measure_candidate if _prefer_measure_role(role) else column_candidate
    return None


def _normalize_role(role: str) -> str:
    return str(role or "").strip().lower().replace(" ", "")


def _prefer_measure_role(role: str) -> bool:
    normalized = _normalize_role(role)
    return normalized in {
        "values",
        "y",
        "tooltips",
        "tooltip",
        "size",
        "color",
        "details",
    }


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _extract_visual_title(visual_data: dict[str, Any]) -> str:
    """Best-effort extraction of visual display title from visual JSON."""
    title_paths = [
        ("visual", "visualContainerObjects", "title"),
        ("visual", "objects", "title"),
        ("visual", "objects", "header"),
    ]
    for path in title_paths:
        node: Any = visual_data
        for key in path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        if not isinstance(node, list):
            continue
        for entry in node:
            value = (
                entry.get("properties", {})
                .get("text", {})
                .get("expr", {})
                .get("Literal", {})
                .get("Value")
            )
            if isinstance(value, str) and value.strip():
                return value.strip().strip("'")
    return ""


def _extract_from_pbir_zip_entries(
    zf: zipfile.ZipFile,
    *,
    visual_entries: list[str],
    model_object_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], VisualExtractionDiagnostics]:
    inventory: dict[str, dict[str, Any]] = {}
    total_bindings = 0
    resolved_measures = 0
    resolved_columns = 0
    unresolved_count = 0
    unresolved_examples: list[str] = []

    for visual_entry in sorted(visual_entries):
        visual_data = _load_json_from_zip_entry(zf, visual_entry)
        if not isinstance(visual_data, dict):
            continue
        parts = visual_entry.replace("\\", "/").split("/")
        page_id = _path_segment_after(parts, "pages") or "unknown_page"
        visual_id = _path_segment_after(parts, "visuals") or str(visual_data.get("name", "unknown_visual"))
        page_json_entry = "/".join(parts[:-3] + ["page.json"])
        page_data = _load_json_from_zip_entry(zf, page_json_entry) or {}
        page_name = str(page_data.get("displayName", page_id))
        visual_name = str(visual_data.get("name", visual_id))
        visual_title = _extract_visual_title(visual_data)
        visual_type = str(visual_data.get("visual", {}).get("visualType", "unknown"))

        deps: set[str] = set()
        bindings: list[dict[str, str]] = []
        unresolved_bindings: list[str] = []
        query_state = (
            visual_data.get("visual", {})
            .get("query", {})
            .get("queryState", {})
        )
        if isinstance(query_state, dict):
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
                            if sort_item.get("queryRef"):
                                unresolved_bindings.append(str(sort_item.get("queryRef")))
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
        obj_id = make_object_id(obj_type=ObjectType.VISUAL, parent=page_name, name=short_id)
        inventory[obj_id] = {
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
        unresolved_count += len(inventory[obj_id]["unresolved_bindings"])
        unresolved_examples.extend(inventory[obj_id]["unresolved_bindings"])

    return inventory, VisualExtractionDiagnostics(
        total_visuals=len(inventory),
        total_bindings_extracted=total_bindings,
        bindings_resolved_measures=resolved_measures,
        bindings_resolved_columns=resolved_columns,
        unresolved_binding_count=unresolved_count,
        unresolved_examples=sorted(dict.fromkeys(unresolved_examples))[:10],
    )


def _load_json_from_zip_entry(zf: zipfile.ZipFile, entry: str) -> dict[str, Any] | None:
    try:
        with zf.open(entry, "r") as handle:
            raw = handle.read()
    except KeyError:
        return None
    for encoding in ("utf-8", "utf-8-sig", "utf-16", "latin-1"):
        try:
            return json.loads(raw.decode(encoding))
        except Exception:  # noqa: BLE001
            continue
    return None


def _load_layout_payload_from_zip_entry(zf: zipfile.ZipFile, entry: str) -> dict[str, Any] | None:
    try:
        with zf.open(entry, "r") as handle:
            raw = handle.read()
    except KeyError:
        return None
    for encoding in ("utf-16-le", "utf-16", "utf-8", "utf-8-sig", "latin-1"):
        try:
            parsed = json.loads(raw.decode(encoding))
            if isinstance(parsed, dict):
                return parsed
        except Exception:  # noqa: BLE001
            continue
    return None


def _extract_from_legacy_layout_payload(
    *,
    payload: dict[str, Any],
    model_object_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    inventory: dict[str, dict[str, Any]] = {}
    total_bindings = 0
    resolved_measures = 0
    resolved_columns = 0
    unresolved_count = 0
    unresolved_examples: list[str] = []

    sections = payload.get("sections", [])
    if not isinstance(sections, list):
        return {}, {
            "total_visuals": 0,
            "total_field_bindings": 0,
            "bindings_resolved_measures": 0,
            "bindings_resolved_columns": 0,
            "unresolved_visual_bindings": 0,
            "unresolved_examples": [],
        }

    for section_index, section in enumerate(sections):
        if not isinstance(section, dict):
            continue
        page_name = str(section.get("displayName") or section.get("name") or f"Section {section_index + 1}")
        page_id = str(section.get("name") or f"section_{section_index + 1}")
        containers = section.get("visualContainers", [])
        if not isinstance(containers, list):
            continue
        for container_index, container in enumerate(containers):
            if not isinstance(container, dict):
                continue
            config_payload = _parse_maybe_json_layout(container.get("config"))
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
            visual_title = _extract_layout_title_from_payload(single_visual, config_payload)
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
                        if not query_ref:
                            continue
                        resolved = _resolve_binding(
                            field={},
                            query_ref=query_ref,
                            role=str(role),
                            model_object_ids=model_object_ids,
                        )
                        if resolved is None:
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

            for query_ref in _extract_queryrefs_from_layout_payload(single_visual):
                resolved = _resolve_binding(
                    field={},
                    query_ref=query_ref,
                    role="query",
                    model_object_ids=model_object_ids,
                )
                if resolved is None:
                    unresolved_bindings.append(query_ref)
                    continue
                deps.add(resolved.target)
                bindings.append(
                    {
                        "role": "query",
                        "target": resolved.target,
                        "source_kind": "pbix_layout_query",
                        "raw": query_ref,
                    }
                )

            short_id = visual_id[:12]
            obj_id = make_object_id(
                obj_type=ObjectType.VISUAL,
                parent=page_name,
                name=short_id,
            )
            dedup_bindings = _dedupe_bindings(bindings)
            inventory[obj_id] = {
                "type": "Visual",
                "visual_id": visual_id,
                "visual_name": visual_name,
                "title": visual_title,
                "visual_type": visual_type,
                "page_id": page_id,
                "page_name": page_name,
                "dependencies": deps,
                "bindings": dedup_bindings,
                "unresolved_bindings": sorted({item for item in unresolved_bindings if item}),
                "unknown_patterns": [],
            }
            total_bindings += len(dedup_bindings)
            resolved_measures += sum(1 for b in dedup_bindings if str(b.get("target", "")).startswith("Measure:"))
            resolved_columns += sum(1 for b in dedup_bindings if str(b.get("target", "")).startswith("Column:"))
            unresolved_count += len(inventory[obj_id]["unresolved_bindings"])
            unresolved_examples.extend(inventory[obj_id]["unresolved_bindings"])

    return inventory, {
        "total_visuals": len(inventory),
        "total_field_bindings": total_bindings,
        "bindings_resolved_measures": resolved_measures,
        "bindings_resolved_columns": resolved_columns,
        "unresolved_visual_bindings": unresolved_count,
        "unresolved_examples": sorted(dict.fromkeys(unresolved_examples))[:10],
    }


def _extract_queryrefs_from_layout_payload(payload: Any) -> list[str]:
    refs: list[str] = []

    def _walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, inner in value.items():
                if key == "queryRef" and isinstance(inner, str) and inner.strip():
                    refs.append(inner.strip())
                else:
                    _walk(inner)
        elif isinstance(value, list):
            for item in value:
                _walk(item)

    _walk(payload)
    return sorted(dict.fromkeys(refs))


def _parse_maybe_json_layout(value: Any) -> Any:
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


def _extract_layout_title_from_payload(single_visual: dict[str, Any], config_payload: dict[str, Any] | None) -> str:
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


def _path_segment_after(parts: list[str], token: str) -> str | None:
    lowered = [part.lower() for part in parts]
    if token.lower() not in lowered:
        return None
    idx = lowered.index(token.lower())
    if idx + 1 < len(parts):
        return parts[idx + 1]
    return None


def _dedupe_bindings(bindings: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for entry in bindings:
        key = (
            str(entry.get("role", "")),
            str(entry.get("target", "")),
            str(entry.get("raw", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out
