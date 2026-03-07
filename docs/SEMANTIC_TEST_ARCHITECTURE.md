# semantic-test Architecture

Last updated: 2026-03-07

## 1. Purpose and Scope

`semantic-test` is a Python CLI for structural analysis of Power BI semantic models.

Primary scope in current codebase:
- Parse PBIP/TMDL semantic model metadata.
- Build object inventories and dependency graph.
- Produce deterministic snapshots and hashes.
- Compare snapshots (`diff`) and downstream impact (`exposure`).
- Trace lineage from latest snapshot (`trace`).
- Export trace lineage to Mermaid (`trace --export mmd|mmd-simple`).
- Scan live Power BI Desktop models via local Analysis Services DMVs (`scan desktop`).
- Persist run artifacts for CLI/CI workflows.

Out of scope:
- Runtime DAX evaluation.
- KPI correctness or business-rule validation.
- Cross-model lineage.
- YAML scenario test runner is available via the project workflow documentation and can be extended through CLI integration when needed.

## 2. Top-Level Architecture

Layers:
- CLI orchestration: `src/semantic_test/cli/commands/*.py`
- Pipeline composition: `src/semantic_test/cli/commands/_pipeline.py`
- Parsing/extraction: `src/semantic_test/core/parse/**`
- Live desktop ingestion: `src/semantic_test/core/live/**`
- Graph + analysis: `src/semantic_test/core/graph/**`, `src/semantic_test/core/analysis/exposure.py`
- Snapshot + diff: `src/semantic_test/core/diff/**`
- Reporting + contracts: `src/semantic_test/core/report/**`, `src/semantic_test/core/model/coverage.py`
- Exporters: `src/semantic_test/exporters/**`
- Output/index persistence: `src/semantic_test/core/io/**`

Entrypoint:
- `src/semantic_test/cli/main.py` registers commands:
  - `scan`
  - `diff`
  - `exposure`
  - `trace`

## 3. Data Flow (Normal File-Based Scan Path)

High-level sequence for `scan <path>`:
1. Resolve project root (`core/model/model_key.py`).
2. Discover/select `*.SemanticModel/definition` (`core/parse/pbip_locator.py`).
3. Read TMDL docs (`core/parse/tmdl_reader.py`).
4. Parse model (`core/parse/tmdl_parser.py`).
5. Extract inventories:
   - tables, columns, measures, relationships
   - calc groups/items, field params
   - report visuals (if adjacent `.Report` folder found)
6. Merge inventories into `objects` map keyed by canonical object IDs.
7. Build dependency graph (`core/graph/builder.py`).
8. Build deterministic snapshot + hash (`core/diff/snapshot.py`).
9. Compute unresolved/unsupported diagnostics and summary.
10. Write run artifacts (`.semantic-test/runs/<run_id>/...`) and update index.

Main orchestrator:
- `build_model_artifacts()` in `cli/commands/_pipeline.py`

## 4. Data Flow (Live Desktop Scan Path)

Sequence for `scan desktop` or `scan desktop:<port>`:
1. Resolve Desktop instance:
   - Auto-discover from `%LOCALAPPDATA%/.../AnalysisServicesWorkspaces`
   - Or parse explicit port
2. Connect to `localhost:<port>` via ADODB + `MSOLAP` provider.
3. Query DMVs:
   - catalogs
   - tables
   - columns
   - measures
   - relationships
4. Transform DMV rows into same internal inventory shape used by file-based path.
5. Run graph/snapshot/report pipeline identical to normal scan output path.

Key modules:
- Discovery: `core/live/desktop.py`
- DMV extraction: `core/live/dmv_schema.py`
- Bridge to normal artifacts: `build_model_artifacts_from_desktop()` in `_pipeline.py`

Note:
- Column DMV extraction is schema-tolerant in current code (fallback between `ExplicitName` and `Name`, optional `Type` handling).

## 5. Core Domain Model

Canonical object ID style (examples):
- Table: `Table:Sales`
- Column: `Column:Sales.Amount`
- Measure: `Measure:Sales.Total Sales`
- Relationship: `Rel:Sales.CustomerKey->Customer.CustomerKey`

`ModelArtifacts` (pipeline output) contains:
- source metadata (`model_key`, `definition_path`, detected models)
- extracted inventories (table/column/measure/relationship/calc/field-param/visual)
- merged `objects` dictionary
- `unknown_patterns`
- dependency `graph`
- deterministic `snapshot`

Object metadata conventions:
- `type`
- `name`, `table` (where relevant)
- `dependencies` (set of canonical IDs)
- optional expression fields (`expression` / `raw_expression`)
- diagnostics fields (`unknown_patterns`, unresolved metadata, assumptions)

## 6. Dependency Graph Design

Graph object (`core/graph/builder.py`):
- `nodes`: object_id -> `GraphNode`
- `edges`: set of `GraphEdge(source, target)`
- `forward`: source -> dependencies
- `reverse`: target -> dependents

Semantics:
- Edge `A -> B` means object `A` depends on object `B`.
- Relationship objects can add bidirectional edges between participating columns when complete.

Consumers:
- `trace` uses adjacency traversal.
- `exposure` uses reverse adjacency for blast-radius.

## 7. Snapshot and Diff Design

Snapshot (`core/diff/snapshot.py`):
- Deterministic normalization of object metadata, sets, expressions, and edges.
- Per-object hash + aggregate snapshot hash (`sha256` of stable JSON payload).
- Stores coverage, unknown patterns, unresolved refs.

Diff (`core/diff/differ.py`):
- Compares object IDs and object hashes.
- Emits:
  - `AddedObject`
  - `RemovedObject`
  - `ModifiedObject`
- Returns `DiffResult` with added/removed/modified lists and combined changed IDs.

## 8. Exposure and Trace

Exposure (`core/analysis/exposure.py`):
- Input: `DiffResult` + current graph.
- For each changed object:
  - all downstream dependents
  - counts by downstream type
  - top downstream objects (capped)

Trace (`cli/commands/trace.py`):
- Loads latest snapshot from index.
- Builds adjacency from snapshot edges.
- Walks upstream/downstream breadth-first to requested depth.
- Keeps text output contract unchanged.
- Optional Mermaid export (`trace_graph.mmd`) from the trace-scope induced subgraph.
- Mermaid display direction is dependency -> dependent (display-only reversal; internal graph is unchanged).
- `mmd-simple` mode suppresses technical helper noise (for example `LocalDateTable_*`, `RowNumber*`, column->column scaffolding) for business-readable flow.

## 9. Reporting and Contracts

Report schemas:
- Versioned schema builder in `core/report/schemas.py` (`REPORT_SCHEMA_VERSION = 1`).
- Text formatters in `core/report/format_text.py`.
- JSON formatter in `core/report/format_json.py`.

Coverage:
- Coverage matrix from `core/model/coverage.py`.
- surfaced in scan/exposure/diff outputs.
- unknown patterns and unresolved refs are included in report gaps.

Scan command report payload (high-level):
- status
- model selection metadata (`scan_input_path`, selected model, detected model list)
- summary counts
- issue groups:
  - unresolved references
  - unsupported reference patterns
- top dependency hubs
- optional debug block (when `--debug`)

## 10. Output and Persistence

Output root:
- default: `<project_root>/.semantic-test`
- overridable via `--outdir`

Per-run artifacts:
- `manifest.json`
- `snapshot.json`
- `report.txt`
- `report.json`
- command-specific extras (for example `diff_report.*`)

Run folder naming:
- `<timestamp>_<command>_<model_key_slug>_<snapshot_slug>`

Index:
- `.semantic-test/index.json`
- model entry fields:
  - `model_key`
  - `definition_path`
  - `latest_snapshot_hash`
  - `latest_run_id`
  - `latest_run_path`

Persistence behavior:
- Index save is atomic (`os.replace` temp file).

## 11. Command Behavior Summary

`scan`:
- Builds artifacts from model path or desktop live model.
- Writes snapshot/report/manifest.
- Updates index unless `--no-index`.
- `--strict` exits `2` for structural issues.

`diff`:
- Compares `before` vs `after` (or auto previous from index).
- Produces change list and coverage/gap summary.
- `--strict` exits `2` if unknown patterns/unresolved refs exist.

`exposure`:
- Same snapshot resolution as `diff`.
- Adds downstream blast-radius analysis.
- Emits PR-friendly text and JSON report.

`trace`:
- Uses latest indexed snapshot.
- Traverses upstream/downstream neighborhood.

Exit codes:
- `0`: success
- `1`: runtime/tool error
- `2`: strict policy failure

## 12. Testing Strategy in Repo

Test layout:
- `tests/unit`: extractors, graph, snapshots, report schema/formatters, model keys, strict policy, desktop DMV schema tests.
- `tests/integration`: CLI command behavior, scan UX, end-to-end and golden output stability.

Testing goals:
- deterministic hashing and diff behavior
- resolver diagnostics quality
- stable report contracts
- command exit-code and artifact guarantees

## 13. Current Known Technical Constraints

- DAX dependency extraction is pattern-based, not full semantic execution.
- Coverage intentionally marks partial/unsupported areas and surfaces unknown patterns.
- Desktop mode depends on Windows + pywin32 + accessible local Analysis Services workspace.
- Multi-model roots require explicit model selection in some workflows.

## 14. Extension Points

Likely extension points for upcoming bug fixes and future work:
- extractor tolerance in `core/parse/extractors/*`
- unresolved-reference ranking/suggestions in measure extractor logic
- desktop DMV query compatibility in `core/live/dmv_schema.py`
- strict policy criteria in CLI command handlers
- report schema/version evolution in `core/report/schemas.py`
