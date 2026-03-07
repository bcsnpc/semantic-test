# Phase-1 Architecture

Last updated: 2026-03-07

## 1. Objective

Phase-1 provides deterministic **structural analysis** for PBIP/TMDL semantic models.
It focuses on model metadata and dependency behavior, not runtime DAX execution.

Primary outcomes:
- detect structural issues early
- produce stable snapshots for compare/review
- provide CI gating via strict policy
- give actionable unresolved-reference diagnostics

## 2. Scope (Delivered)

Phase-1 commands:
- `scan`
- `diff`
- `exposure`
- `trace`

Delivered capabilities:
- PBIP model definition discovery (`*.SemanticModel/definition`)
- PBIX report parsing for visual lineage
- Desktop semantic scan from local Analysis Services DMVs
- inventory extraction for tables, columns, measures, relationships, calc groups/items, field parameters
- dependency graph build for upstream/downstream analysis
- snapshot creation and deterministic hashing
- snapshot differencing between two versions
- blast-radius (`exposure`) report
- point trace from object id (`trace`)
- trace Mermaid export (`--export mmd`, `--export mmd-simple`)
- strict-mode CI policy (`--strict` with exit code `2`)

## 3. High-Level Flow

1. Locate semantic model definition path from input root.
2. Parse TMDL objects into a normalized in-memory registry.
3. Extract references from expressions and relationships.
4. Resolve references to canonical object IDs.
5. Build dependency graph (nodes + edges).
6. Emit scan report (`report.txt` + `report.json`) and snapshot artifacts.
7. Reuse snapshots for `diff`, `exposure`, and `trace`.

## 4. Core Components

### 4.1 CLI Layer

Location: `src/semantic_test/cli/commands/`

Responsibilities:
- parse command options
- determine invocation style for Next Actions (module vs CLI entrypoint)
- orchestrate core services
- format terminal output and write run artifacts

### 4.2 Model Locator + Reader

Responsibilities:
- discover candidate `definition` folders
- handle single-model and multi-model roots safely
- return selected model metadata (key + definition path)

### 4.3 Extractor Layer

Location: `src/semantic_test/core/parse/extractors/`

Responsibilities:
- inventory extraction of model objects
- expression token extraction for dependencies
- coverage tracking per object type

### 4.4 Reference Resolver

Responsibilities:
- resolve references into canonical IDs
- record unresolved references with context
- apply calculated-column implicit resolution rules:
  - unqualified `[X]` in calc column tries current-table column first
  - if missing in current table, tries measure lookup
  - unresolved reason differentiates column-vs-measure absence
- produce diagnostics metadata and ranked suggestions

### 4.5 Graph + Snapshot

Responsibilities:
- construct directed dependency graph
- materialize normalized snapshot payload
- compute stable hash to support deterministic comparison

### 4.6 Diff/Exposure/Trace Services

Responsibilities:
- compare snapshots across model versions (`diff`)
- quantify downstream impact (`exposure`)
- show object-level lineage neighborhoods (`trace`)

## 5. Unresolved Reference UX (Phase-1 Improvements)

For each unresolved token, report now includes:
- object context (type + full name)
- expression snippet
- severity
- reason + short hint
- `expected_type`, `expected_scope`, `likely_cause`, `action`
- `did_you_mean` ranked candidates
- `did_you_mean_top3` with scores
- `best_guess` + `best_guess_score` (thresholded)
- `why_best_guess` when applicable
- `referrers_count` impact hint
- optional suggested fix options (up to 3) with combined score

Additional scan summary fields:
- resolution assumptions applied count
- ambiguous references count
- strict fail reason breakdown

## 6. Next Actions UX

Phase-1 now emits copy/paste-safe guidance:
- preserves user invocation mode (`python -m ...` or `semantic-test`)
- always quotes paths with spaces
- avoids `scan .` recommendations in multi-model roots
- prefers exact model definition path for rerun clarity
- includes optional install hint for CLI entrypoint:
  - `pip install -e .`

## 7. Reports and Data Contracts

Each run writes:
- `manifest.json`
- `snapshot.json`
- `report.txt`
- `report.json`

`report.json` includes model-selection metadata:
- `scan_input_path`
- `selected_model_key`
- `selected_model_definition_path`
- `models_detected_count`
- `models_detected` (key + path list)

Backward compatibility principle:
- existing fields remain intact
- new diagnostics are additive
- exit codes unchanged (`0`, `1`, `2`)

## 8. Current Limitations (Intentional)

- no runtime DAX evaluation
- no KPI/business correctness checks
- no cross-model lineage
- no Phase-2 YAML scenario testing yet

## 9. Testing Strategy (Phase-1)

- unit tests for resolver, ranking, extractors, strict policy, IDs
- integration tests for scan UX, CLI behavior, end-to-end flows
- golden output tests for unresolved-reference console formatting

## 10. Phase-1 Outcome

Phase-1 is now a reliable structural quality gate and analysis toolkit for semantic model pull requests and release checks.
It provides deterministic artifacts, actionable diagnostics, and CI-friendly strict enforcement while keeping architecture simple for future Phase-2 expansion.
