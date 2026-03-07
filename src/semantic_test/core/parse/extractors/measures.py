"""Measure inventory and dependency extraction (v1)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re
from typing import Any

from semantic_test.core.model.objects import ObjectRef, ObjectType
from semantic_test.core.parse.tmdl_parser import ParsedModel

_QUOTED_COLUMN_REF_RE = re.compile(r"'([^']+)'\[([^\]]+)\]")
_UNQUOTED_COLUMN_REF_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\[([^\]]+)\]")
_MEASURE_REF_RE = re.compile(r"(?<![A-Za-z0-9_'])\[([^\[\]]+)\]")
_SELECTED_MEASURE_RE = re.compile(r"\bSELECTEDMEASURE\s*\(", re.IGNORECASE)
_SELECTED_MEASURE_NAME_RE = re.compile(r"\bSELECTEDMEASUREName\s*\(", re.IGNORECASE)
_VAR_NAME_RE = re.compile(r"\bVAR\s+([A-Za-z_][A-Za-z0-9_]*)\s*=", re.IGNORECASE)
_VAR_BRACKET_NAME_RE = re.compile(r"\bVAR\s+\[([^\]]+)\]\s*=", re.IGNORECASE)
_STRING_LITERAL_RE = re.compile(r'"([^"]*)"')
_ROW_CONTEXT_FUNCTION_RE = re.compile(
    r"\b(SUMX|AVERAGEX|MINX|MAXX|FILTER|ADDCOLUMNS|SELECTCOLUMNS|ROW|SUMMARIZE|SUMMARIZECOLUMNS)\s*\(",
    re.IGNORECASE,
)
_VIRTUAL_ALIAS_FUNCTIONS = ("SUMMARIZE", "SUMMARIZECOLUMNS", "ADDCOLUMNS", "SELECTCOLUMNS", "ROW")


@dataclass(frozen=True, slots=True)
class ExpressionAnalysis:
    dependencies: set[str]
    unknown_patterns: list[str]
    unresolved_references: list[dict[str, Any]]
    resolution_assumptions: list[str]
    ambiguous_reference_count: int


def extract_measures(parsed: ParsedModel) -> dict[str, dict[str, Any]]:
    """Build measure inventory as ``{object_id: metadata}``."""
    inventory: dict[str, dict[str, Any]] = {}
    registry = build_reference_registry(parsed)

    for measure in parsed.measures:
        ref = ObjectRef(type=ObjectType.MEASURE, table=measure.table, name=measure.name)
        measure_id = ref.canonical_id()
        expression = measure.expression or ""
        analysis = extract_expression_analysis(
            expression=expression,
            current_measure_id=measure_id,
            current_table=measure.table,
            current_object_id=measure_id,
            current_object_name=measure.name,
            expression_context="measure",
            reference_registry=registry,
        )
        inventory[measure_id] = {
            "id": measure_id,
            "type": ObjectType.MEASURE.value,
            "name": measure.name,
            "table": measure.table,
            "raw_expression": expression,
            "dependencies": analysis.dependencies,
            "unknown_patterns": analysis.unknown_patterns,
            "unresolved_references": analysis.unresolved_references,
            "resolution_assumptions": analysis.resolution_assumptions,
            "ambiguous_reference_count": analysis.ambiguous_reference_count,
            "source_file": measure.source_file,
            "object_ref": ref,
        }
    return inventory


def build_measure_name_index(parsed: ParsedModel) -> dict[str, set[str]]:
    """Build ``measure name -> canonical measure IDs`` map."""
    name_to_ids: dict[str, set[str]] = defaultdict(set)
    for measure in parsed.measures:
        ref = ObjectRef(type=ObjectType.MEASURE, table=measure.table, name=measure.name)
        name_to_ids[measure.name].add(ref.canonical_id())
    return name_to_ids


def build_reference_registry(parsed: ParsedModel) -> dict[str, Any]:
    """Build global reference registry used for expression resolution."""
    table_names = [table.name for table in parsed.tables]
    columns = [
        (column.table, column.name)
        for column in parsed.columns
        if column.table
    ]
    measures = [
        (measure.table, measure.name)
        for measure in parsed.measures
    ]
    return build_reference_registry_from_inventory(
        table_names=table_names,
        columns=columns,
        measures=measures,
    )


def build_reference_registry_from_inventory(
    *,
    table_names: list[str],
    columns: list[tuple[str | None, str]],
    measures: list[tuple[str | None, str]],
) -> dict[str, Any]:
    """Build canonical resolver index from a normalized semantic inventory."""
    measure_name_to_ids: dict[str, set[str]] = defaultdict(set)
    measure_name_to_ids_canonical: dict[str, set[str]] = defaultdict(set)
    measure_key_to_id: dict[tuple[str, str], str] = {}
    tables_by_lower: dict[str, str] = {}
    columns_by_table_lower: dict[tuple[str, str], str] = {}
    column_names_by_table_lower: dict[str, set[str]] = defaultdict(set)
    column_name_to_ids_canonical: dict[str, set[str]] = defaultdict(set)
    all_columns: list[tuple[str, str]] = []
    all_measures: list[tuple[str, str]] = []
    measure_home_table_by_id: dict[str, str] = {}

    for table_name_raw in table_names:
        table_name = str(table_name_raw or "").strip()
        if not table_name:
            continue
        tables_by_lower.setdefault(table_name.lower(), table_name)

    for table_name_raw, column_name_raw in columns:
        table_name = str(table_name_raw or "").strip()
        column_name = str(column_name_raw or "").strip()
        if not table_name or not column_name:
            continue
        canonical_id = ObjectRef(
            type=ObjectType.COLUMN,
            table=table_name,
            name=column_name,
        ).canonical_id()
        table_key = table_name.lower()
        column_key = _canonical_symbol(column_name)
        columns_by_table_lower[(table_key, column_key)] = canonical_id
        column_names_by_table_lower[table_key].add(column_name)
        column_name_to_ids_canonical[column_key].add(canonical_id)
        all_columns.append((table_name, column_name))

    for table_name_raw, measure_name_raw in measures:
        measure_name = str(measure_name_raw or "").strip()
        table_name = str(table_name_raw or "").strip()
        if not measure_name:
            continue
        ref = ObjectRef(type=ObjectType.MEASURE, table=table_name or None, name=measure_name)
        canonical_id = ref.canonical_id()
        measure_name_to_ids[measure_name].add(canonical_id)
        measure_name_to_ids_canonical[_canonical_symbol(measure_name)].add(canonical_id)
        measure_key_to_id[(table_name.lower(), _canonical_symbol(measure_name))] = canonical_id
        measure_home_table_by_id[canonical_id] = table_name
        all_measures.append((table_name, measure_name))

    return {
        "tables_by_lower": tables_by_lower,
        "columns_by_table_lower": columns_by_table_lower,
        "column_names_by_table_lower": {
            table_key: sorted(names)
            for table_key, names in column_names_by_table_lower.items()
        },
        "column_name_to_ids_canonical": {
            key: set(value) for key, value in column_name_to_ids_canonical.items()
        },
        "measure_name_to_ids": dict(measure_name_to_ids),
        "measure_name_to_ids_canonical": {
            key: set(value) for key, value in measure_name_to_ids_canonical.items()
        },
        "measure_key_to_id": measure_key_to_id,
        "measure_home_table_by_id": measure_home_table_by_id,
        "all_columns": sorted(set(all_columns)),
        "all_measures": sorted(set(all_measures)),
    }


def extract_expression_dependencies(
    *,
    expression: str,
    current_measure_id: str | None = None,
    current_table: str | None,
    reference_registry: dict[str, Any] | None = None,
    measure_name_to_ids: dict[str, set[str]] | None = None,
) -> tuple[set[str], list[str]]:
    """Extract dependencies from an expression using v1 precision-first rules."""
    analysis = extract_expression_analysis(
        expression=expression,
        current_measure_id=current_measure_id,
        current_table=current_table,
        reference_registry=reference_registry,
        measure_name_to_ids=measure_name_to_ids,
        expression_context="measure",
    )
    return analysis.dependencies, analysis.unknown_patterns


def extract_expression_analysis(
    *,
    expression: str,
    current_measure_id: str | None = None,
    current_table: str | None,
    current_object_id: str | None = None,
    current_object_name: str | None = None,
    expression_context: str = "measure",
    reference_registry: dict[str, Any] | None = None,
    measure_name_to_ids: dict[str, set[str]] | None = None,
) -> ExpressionAnalysis:
    """Extract dependencies and detailed diagnostics from a DAX expression."""
    registry = reference_registry or _registry_from_name_index(measure_name_to_ids or {})
    tables_by_lower = registry["tables_by_lower"]
    columns_by_table_lower = registry["columns_by_table_lower"]
    column_name_to_ids_canonical = registry.get("column_name_to_ids_canonical", {})
    measure_key_to_id = registry["measure_key_to_id"]
    name_to_ids = registry["measure_name_to_ids"]
    name_to_ids_canonical = registry.get("measure_name_to_ids_canonical", {})

    dependencies: set[str] = set()
    unknown_patterns: list[str] = []
    unresolved_references: list[dict[str, Any]] = []
    resolution_assumptions: list[str] = []
    ambiguous_reference_count = 0

    local_vars = _extract_local_var_symbols(expression)
    virtual_aliases = _extract_virtual_aliases(expression)
    string_labels = _extract_double_quoted_literals(expression)
    masked_expression = _mask_double_quoted_strings(expression)

    if _SELECTED_MEASURE_RE.search(expression):
        unknown_patterns.append("unsupported_pattern:SELECTEDMEASURE()")
    if _SELECTED_MEASURE_NAME_RE.search(expression):
        unknown_patterns.append("unsupported_pattern:SELECTEDMEASURENAME()")

    for table_name, column_name in _QUOTED_COLUMN_REF_RE.findall(expression):
        _resolve_qualified_reference(
            table_name=table_name,
            object_name=column_name,
            dependencies=dependencies,
            unknown_patterns=unknown_patterns,
            tables_by_lower=tables_by_lower,
            columns_by_table_lower=columns_by_table_lower,
            measure_key_to_id=measure_key_to_id,
        )

    for table_name, column_name in _UNQUOTED_COLUMN_REF_RE.findall(expression):
        _resolve_qualified_reference(
            table_name=table_name,
            object_name=column_name,
            dependencies=dependencies,
            unknown_patterns=unknown_patterns,
            tables_by_lower=tables_by_lower,
            columns_by_table_lower=columns_by_table_lower,
            measure_key_to_id=measure_key_to_id,
        )

    seen_unresolved_keys: set[tuple[str, str]] = set()
    for ref_name in _MEASURE_REF_RE.findall(masked_expression):
        candidate = ref_name.strip()
        if not candidate:
            continue

        if _canonical_symbol(candidate) in local_vars:
            continue
        if _canonical_symbol(candidate) in virtual_aliases:
            continue
        if _canonical_symbol(candidate) in string_labels:
            continue
        if _looks_like_bracketed_table_ref(candidate, tables_by_lower):
            continue

        if expression_context == "calculated_column":
            local_column_id, assumption_message = _resolve_current_table_column(
                column_name=candidate,
                current_table=current_table,
                columns_by_table_lower=columns_by_table_lower,
                current_object_id=current_object_id,
                current_object_name=current_object_name,
            )
            if local_column_id is not None:
                dependencies.add(local_column_id)
                if assumption_message:
                    resolution_assumptions.append(assumption_message)
                continue

            resolved_measure, reason_code = _resolve_measure_reference(
                measure_name=candidate,
                current_table=current_table,
                measure_name_to_ids=name_to_ids,
                measure_name_to_ids_canonical=name_to_ids_canonical,
                measure_key_to_id=measure_key_to_id,
            )
            if resolved_measure is not None:
                dependencies.add(resolved_measure)
                continue

            unresolved_key = ("column", _canonical_symbol(candidate))
            if unresolved_key in seen_unresolved_keys:
                continue
            seen_unresolved_keys.add(unresolved_key)

            unknown_patterns.append(f"unresolved_column:[{candidate}]")
            base_reason = "Missing referenced column (not found in current table) and no measure found."
            if reason_code == "ambiguous_measure":
                ambiguous_reference_count += 1
                base_reason = "Ambiguous measure reference; appears in multiple tables."
            enriched = _enrich_unresolved_reference(
                query=candidate,
                reason=base_reason,
                expected_type="unknown",
                expected_scope="current_table",
                registry=registry,
                current_table=current_table,
                category="true_missing_model_object",
            )
            unresolved_references.append(enriched)
            continue

        resolved, reason_code = _resolve_measure_reference(
            measure_name=candidate,
            current_table=current_table,
            measure_name_to_ids=name_to_ids,
            measure_name_to_ids_canonical=name_to_ids_canonical,
            measure_key_to_id=measure_key_to_id,
        )
        if resolved is not None:
            dependencies.add(resolved)
            continue

        local_same_table_col, local_col_assumption = _resolve_current_table_column(
            column_name=candidate,
            current_table=current_table,
            columns_by_table_lower=columns_by_table_lower,
            current_object_id=current_object_id,
            current_object_name=current_object_name,
        )
        if local_same_table_col is not None:
            dependencies.add(local_same_table_col)
            if local_col_assumption:
                resolution_assumptions.append(local_col_assumption)
            continue

        any_table_col = _resolve_any_table_column(
            column_name=candidate,
            column_name_to_ids_canonical=column_name_to_ids_canonical,
            expression=expression,
        )
        if any_table_col is not None:
            dependencies.add(any_table_col)
            continue

        unresolved_key = ("measure", _canonical_symbol(candidate))
        if unresolved_key in seen_unresolved_keys:
            continue
        seen_unresolved_keys.add(unresolved_key)

        unknown_patterns.append(f"unresolved_measure:[{candidate}]")
        reason = _measure_resolution_reason(reason_code)
        category = _infer_unresolved_category(
            query=candidate,
            reason_code=reason_code,
            registry=registry,
        )
        enriched = _enrich_unresolved_reference(
            query=candidate,
            reason=reason,
            expected_type="measure",
            expected_scope="any_table",
            registry=registry,
            current_table=current_table,
            category=category,
        )
        unresolved_references.append(enriched)
        if reason_code == "ambiguous_measure":
            ambiguous_reference_count += 1

    if current_measure_id is not None:
        dependencies.discard(current_measure_id)
    unknown_patterns = _dedupe_preserve_order(unknown_patterns)
    return ExpressionAnalysis(
        dependencies=dependencies,
        unknown_patterns=unknown_patterns,
        unresolved_references=unresolved_references,
        resolution_assumptions=resolution_assumptions,
        ambiguous_reference_count=ambiguous_reference_count,
    )


def _resolve_current_table_column(
    *,
    column_name: str,
    current_table: str | None,
    columns_by_table_lower: dict[tuple[str, str], str],
    current_object_id: str | None,
    current_object_name: str | None,
) -> tuple[str | None, str | None]:
    if not current_table:
        return None, None
    local_id = columns_by_table_lower.get((current_table.strip().lower(), _canonical_symbol(column_name)))
    if local_id is None:
        return None, None
    object_label = current_object_name or current_object_id or "unknown"
    message = (
        f"Resolved [{column_name}] => {current_table}[{column_name}] "
        f"(implicit current-table scope, object={object_label})"
    )
    return local_id, message


def _enrich_unresolved_reference(
    *,
    query: str,
    reason: str,
    expected_type: str,
    expected_scope: str,
    registry: dict[str, Any],
    current_table: str | None,
    category: str = "true_missing_model_object",
) -> dict[str, Any]:
    reason_with_hint = _reason_with_hint(reason)
    ranked = _rank_candidates(
        query=query,
        expected_type=expected_type,
        expected_scope=expected_scope,
        registry=registry,
        current_table=current_table,
    )
    top = ranked[0] if ranked else None
    best_guess = top["candidate"] if top and int(top["score"]) >= 85 else None
    best_guess_score = int(top["score"]) if top and int(top["score"]) >= 85 else None
    why_best_guess = _why_best_guess(top, expected_type) if best_guess is not None else None

    likely_cause = category
    if "Unqualified" in reason or "implicit scope not applied" in reason:
        likely_cause = "local_symbol_misclassified"
    elif best_guess is not None:
        likely_cause = "renamed_object"
    elif likely_cause == "true_missing_model_object" and not ranked:
        likely_cause = "true_missing_model_object"

    action = "MANUAL_REVIEW"
    if likely_cause in {"local_symbol_misclassified", "virtual_alias_misclassified"}:
        action = "QUALIFY_REFERENCE"
    elif likely_cause == "renamed_object" and best_guess is not None:
        action = "RENAME_REFERENCE"
    elif likely_cause == "true_missing_model_object":
        action = "ADD_MISSING_OBJECT"

    did_you_mean = [entry["candidate"] for entry in ranked[:5]]
    top3_ranked = ranked[:3]
    if expected_type in {"measure", "column"}:
        filtered = [entry for entry in ranked if str(entry.get("candidate", "")).startswith(f"{expected_type}:")]
        top3_ranked = filtered[:3] if filtered else ranked[:3]

    return {
        "ref": f"[{query}]",
        "reason": reason_with_hint,
        "severity": "ERROR",
        "did_you_mean": did_you_mean,
        "did_you_mean_ranked": ranked[:5],
        "did_you_mean_top3_ranked": top3_ranked,
        "expected_type": expected_type,
        "expected_scope": expected_scope,
        "likely_cause": likely_cause,
        "category": likely_cause,
        "best_guess": best_guess,
        "best_guess_score": best_guess_score,
        "why_best_guess": why_best_guess,
        "action": action,
    }


def _reason_with_hint(reason: str) -> str:
    if "Missing referenced measure" in reason:
        return (
            f"{reason} Hint: likely rename or variant suffix (e.g., Measure1/Measure2)."
        )
    if "Unqualified" in reason or "implicit scope not applied" in reason:
        return (
            f"{reason} Hint: qualify with Table[Column] or ensure implicit scope logic "
            "supports current-table resolution."
        )
    return reason


def _rank_candidates(
    *,
    query: str,
    expected_type: str,
    expected_scope: str,
    registry: dict[str, Any],
    current_table: str | None,
) -> list[dict[str, Any]]:
    normalized_query = _normalize_name(query)
    if not normalized_query:
        return []

    measures: list[tuple[str, str]] = list(registry.get("all_measures", []))
    columns: list[tuple[str, str]] = list(registry.get("all_columns", []))
    query_tokens = _tokens(query)
    current_table_norm = (current_table or "").strip().lower()

    candidates: list[dict[str, Any]] = []

    if expected_type in {"measure", "unknown"}:
        for table_name, name in measures:
            normalized_name = _normalize_name(name)
            similarity = _similarity_score(normalized_query, normalized_name)
            token_overlap = len(query_tokens & _tokens(name))
            token_bonus = _token_overlap_bonus(query_tokens, _tokens(name))
            score = similarity + token_bonus
            score += 25 if expected_type == "measure" else 8
            suffix_tolerance = _normalize_name_no_suffix(query) == _normalize_name_no_suffix(name)
            candidate = {
                "candidate": f"measure:{name}",
                "score": min(100, max(0, score)),
                "type": "measure",
                "table": table_name,
                "name": name,
                "normalized_exact": normalized_query == normalized_name,
                "suffix_tolerance": suffix_tolerance,
                "token_overlap": token_overlap,
            }
            candidates.append(candidate)

    if expected_type in {"column", "unknown"}:
        for table_name, name in columns:
            normalized_name = _normalize_name(name)
            similarity = _similarity_score(normalized_query, normalized_name)
            token_overlap = len(query_tokens & _tokens(name))
            token_bonus = _token_overlap_bonus(query_tokens, _tokens(name))
            score = similarity + token_bonus
            if expected_type == "column":
                score += 25
            if expected_scope == "current_table" and table_name.lower() == current_table_norm:
                score += 15
            suffix_tolerance = _normalize_name_no_suffix(query) == _normalize_name_no_suffix(name)
            candidate = {
                "candidate": f"column:{table_name}[{name}]",
                "score": min(100, max(0, score)),
                "type": "column",
                "table": table_name,
                "name": name,
                "normalized_exact": normalized_query == normalized_name,
                "suffix_tolerance": suffix_tolerance,
                "token_overlap": token_overlap,
            }
            candidates.append(candidate)

    if expected_type == "unknown":
        has_measure = any(item["type"] == "measure" for item in candidates)
        if has_measure:
            candidates = [item for item in candidates if item["type"] == "measure"] + [
                item for item in candidates if item["type"] == "column"
            ]

    candidates.sort(
        key=lambda item: (
            -int(item["score"]),
            0 if _type_priority(item["type"], expected_type) else 1,
            0 if (expected_scope == "current_table" and item["table"].lower() == current_table_norm) else 1,
            item["candidate"],
        )
    )

    dedup: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in candidates:
        key = item["candidate"]
        if key in seen:
            continue
        seen.add(key)
        dedup.append(
            {
                "candidate": item["candidate"],
                "score": int(item["score"]),
                "type": item["type"],
                "normalized_exact": bool(item.get("normalized_exact", False)),
                "suffix_tolerance": bool(item.get("suffix_tolerance", False)),
                "token_overlap": int(item.get("token_overlap", 0)),
            }
        )

    return dedup


def _why_best_guess(top: dict[str, Any] | None, expected_type: str) -> str | None:
    if not isinstance(top, dict):
        return None
    kind = str(top.get("type", "unknown"))
    if bool(top.get("normalized_exact")) and bool(top.get("suffix_tolerance")):
        return (
            "Exact match after normalization + trailing digit suffix tolerance + "
            f"same type ({kind})."
        )
    if bool(top.get("normalized_exact")):
        return f"Exact match after normalization + same type ({kind})."
    if int(top.get("token_overlap", 0)) > 0:
        return f"High similarity token match + same type ({kind})."
    if expected_type in {"measure", "column"}:
        return f"Best available similarity match + same type ({expected_type})."
    return "Best available similarity match."


def _type_priority(candidate_type: str, expected_type: str) -> bool:
    if expected_type == "unknown":
        return candidate_type == "measure"
    return candidate_type == expected_type


def _normalize_name(value: str) -> str:
    value = re.sub(r"\d+$", "", value)
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _normalize_name_no_suffix(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _tokens(value: str) -> set[str]:
    parts = re.split(r"[\s_\-\./]+", value.lower())
    return {part for part in parts if part}


def _similarity_score(query: str, candidate: str) -> int:
    if not query or not candidate:
        return 0
    if query == candidate:
        return 100
    distance = _levenshtein_distance(query, candidate)
    max_len = max(len(query), len(candidate))
    base = int(round((1 - (distance / max_len)) * 100))
    return max(0, base)


def _token_overlap_bonus(query_tokens: set[str], candidate_tokens: set[str]) -> int:
    if not query_tokens or not candidate_tokens:
        return 0
    overlap = len(query_tokens & candidate_tokens)
    return min(20, overlap * 5)


def _levenshtein_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + cost,
                )
            )
        previous = current
    return previous[-1]


def _canonical_symbol(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("[") and text.endswith("]") and len(text) > 2:
        text = text[1:-1]
    if text.startswith("'") and text.endswith("'") and len(text) > 2:
        text = text[1:-1]
    return re.sub(r"\s+", " ", text).strip().lower()


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _mask_double_quoted_strings(expression: str) -> str:
    return re.sub(r'"[^"]*"', '""', expression)


def _extract_local_var_symbols(expression: str) -> set[str]:
    names = { _canonical_symbol(name) for name in _VAR_NAME_RE.findall(expression) }
    names.update(_canonical_symbol(name) for name in _VAR_BRACKET_NAME_RE.findall(expression))
    return {name for name in names if name}


def _extract_double_quoted_literals(expression: str) -> set[str]:
    return {_canonical_symbol(item) for item in _STRING_LITERAL_RE.findall(expression) if str(item).strip()}


def _extract_virtual_aliases(expression: str) -> set[str]:
    aliases: set[str] = set()
    masked = _mask_double_quoted_strings(expression)
    for func_name in _VIRTUAL_ALIAS_FUNCTIONS:
        for start, end in _function_call_spans(masked, func_name):
            segment = expression[start:end]
            for literal in _STRING_LITERAL_RE.findall(segment):
                normalized = _canonical_symbol(literal)
                if normalized:
                    aliases.add(normalized)
    return aliases


def _function_call_spans(expression: str, function_name: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    pattern = re.compile(rf"\b{re.escape(function_name)}\s*\(", re.IGNORECASE)
    for match in pattern.finditer(expression):
        open_index = match.end() - 1
        depth = 0
        for idx in range(open_index, len(expression)):
            char = expression[idx]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    spans.append((open_index + 1, idx))
                    break
    return spans


def _resolve_any_table_column(
    *,
    column_name: str,
    column_name_to_ids_canonical: dict[str, set[str]],
    expression: str,
) -> str | None:
    if not _ROW_CONTEXT_FUNCTION_RE.search(expression):
        return None
    key = _canonical_symbol(column_name)
    candidates = column_name_to_ids_canonical.get(key, set())
    if len(candidates) == 1:
        return next(iter(candidates))
    return None


def _looks_like_bracketed_table_ref(candidate: str, tables_by_lower: dict[str, str]) -> bool:
    key = _canonical_symbol(candidate)
    return key in tables_by_lower


def _infer_unresolved_category(
    *,
    query: str,
    reason_code: str,
    registry: dict[str, Any],
) -> str:
    if reason_code == "ambiguous_measure":
        return "extractor_parity_gap"
    query_normalized = _canonical_symbol(query)
    for _table, measure_name in registry.get("all_measures", []):
        if _canonical_symbol(str(measure_name)) == query_normalized:
            return "extractor_parity_gap"
    return "true_missing_model_object"


def _resolve_measure_reference(
    *,
    measure_name: str,
    current_table: str | None,
    measure_name_to_ids: dict[str, set[str]],
    measure_name_to_ids_canonical: dict[str, set[str]],
    measure_key_to_id: dict[tuple[str, str], str],
) -> tuple[str | None, str]:
    candidates = measure_name_to_ids.get(measure_name)
    if candidates is None:
        canonical_candidates = measure_name_to_ids_canonical.get(_canonical_symbol(measure_name))
        if canonical_candidates:
            candidates = set(canonical_candidates)
    if candidates is None:
        lowered = measure_name.lower()
        case_insensitive = [
            ids
            for key, ids in measure_name_to_ids.items()
            if key.lower() == lowered
        ]
        merged: set[str] = set()
        for ids in case_insensitive:
            merged.update(ids)
        candidates = merged if merged else None
    if not candidates:
        return None, "missing_measure"
    if len(candidates) == 1:
        return next(iter(candidates)), "resolved"

    if current_table:
        local_id = measure_key_to_id.get((current_table.strip().lower(), _canonical_symbol(measure_name)))
        if local_id is None:
            local_id = ObjectRef(
                type=ObjectType.MEASURE, table=current_table, name=measure_name
            ).canonical_id()
        if local_id in candidates:
            return local_id, "resolved_local_scope"
    return None, "ambiguous_measure"


def _measure_resolution_reason(reason_code: str) -> str:
    if reason_code == "ambiguous_measure":
        return "Ambiguous measure reference; appears in multiple tables."
    return "Missing referenced measure."


def _resolve_qualified_reference(
    *,
    table_name: str,
    object_name: str,
    dependencies: set[str],
    unknown_patterns: list[str],
    tables_by_lower: dict[str, str],
    columns_by_table_lower: dict[tuple[str, str], str],
    measure_key_to_id: dict[tuple[str, str], str],
) -> None:
    table_key = table_name.strip().strip("'").lower()
    object_key = _canonical_symbol(object_name)
    canonical_table = tables_by_lower.get(table_key, table_name.strip().strip("'"))

    column_id = columns_by_table_lower.get((table_key, object_key))
    if column_id:
        dependencies.add(column_id)
        return

    measure_id = measure_key_to_id.get((table_key, object_key))
    if measure_id:
        dependencies.add(measure_id)
        return

    fallback_column = ObjectRef(
        type=ObjectType.COLUMN,
        table=canonical_table,
        name=object_name.strip(),
    ).canonical_id()
    dependencies.add(fallback_column)
    _ = unknown_patterns


def _registry_from_name_index(measure_name_to_ids: dict[str, set[str]]) -> dict[str, Any]:
    measure_key_to_id: dict[tuple[str, str], str] = {}
    measure_name_to_ids_canonical: dict[str, set[str]] = defaultdict(set)
    all_measures: list[tuple[str, str]] = []
    for ids in measure_name_to_ids.values():
        for object_id in ids:
            if not object_id.startswith("Measure:"):
                continue
            body = object_id.split(":", maxsplit=1)[1]
            if "." not in body:
                continue
            table_name, measure_name = body.split(".", maxsplit=1)
            measure_key_to_id[(table_name.lower(), _canonical_symbol(measure_name))] = object_id
            measure_name_to_ids_canonical[_canonical_symbol(measure_name)].add(object_id)
            all_measures.append((table_name, measure_name))
    return {
        "tables_by_lower": {},
        "columns_by_table_lower": {},
        "column_names_by_table_lower": {},
        "column_name_to_ids_canonical": {},
        "measure_name_to_ids": measure_name_to_ids,
        "measure_name_to_ids_canonical": dict(measure_name_to_ids_canonical),
        "measure_key_to_id": measure_key_to_id,
        "measure_home_table_by_id": {},
        "all_columns": [],
        "all_measures": all_measures,
    }
