# semantic-test User Guide

Last updated: 2026-03-03

This guide explains `semantic-test` from a user perspective:
- what the tool is for
- what each command does
- what output to expect
- what limitations to be aware of
- how to run it in local workflows and CI

## 1. What This Tool Is

`semantic-test` is a structural analysis CLI for Power BI semantic models (PBIP/TMDL).

It is built to answer:
- what objects exist in this model?
- what changed between two model versions?
- what downstream objects are exposed by those changes?
- what depends on this object (upstream/downstream trace)?

It is intentionally not a semantic correctness validator for business logic and not a DAX execution engine.

## 2. Scope and Non-Scope

### In Scope
- Locate a model definition folder from:
  - a repo root (only if exactly one definition folder is discoverable)
  - a `.SemanticModel` folder
  - a direct `definition/` path
- Parse and inventory:
  - tables
  - columns
  - measures
  - relationships
  - calc groups/items (experimental)
  - field parameters (experimental)
- Build dependency graph (nodes/edges)
- Generate deterministic snapshots
- Diff snapshots (`AddedObject`, `RemovedObject`, `ModifiedObject`)
- Exposure/blast-radius analysis for changed objects
- Dependency tracing for a selected object
- Output human-readable (`report.txt`) and machine-readable (`report.json`) artifacts
- Strict policy gate (`--strict`) with exit code `2` for structural issues

### Out of Scope
- Severity scoring (`High`, `Medium`, `Low`)
- Executing DAX or validating runtime results
- Business KPI correctness checks
- Visual rendering/runtime validation
- Cross-model lineage
- Phase 2 semantic YAML assertions (`semantic-test test ...`) - not implemented yet

## 3. Installation and Invocation

### Option A: Install directly from GitHub (recommended for users)

```powershell
pip install "git+https://github.com/bcsnpc/semantic-test.git"
semantic-test --help
```

### Option B: Clone then install editable (recommended for contributors)

```powershell
git clone https://github.com/bcsnpc/semantic-test.git
cd semantic-test
pip install -e .
semantic-test --help
```

If script entrypoint is unavailable in your shell, use module invocation:

```powershell
python -m semantic_test.cli.main --help
```

Note:
- `python -m semantic-test` is invalid (hyphen cannot be used in module import).
- Correct module path is `semantic_test.cli.main`.

## 4. Commands: User-Facing Behavior

Current commands:
- `scan`
- `diff`
- `exposure`
- `trace`

No `test` command exists yet in v0.1.0.

### 4.1 scan

Purpose:
- Analyze one model and report inventory, graph stats, issues, and dependency hubs.

Common usage:

```powershell
semantic-test scan <model_path>
semantic-test scan <model_path> --strict
semantic-test scan <model_path> --debug
semantic-test scan <model_path> --stdout json
```

Typical statuses:
- `CLEAN`: no unresolved refs and no unsupported patterns
- `STRUCTURAL_ISSUES`: unresolved refs and/or unsupported patterns detected
- `ERROR`: path/parse/runtime failure

`--strict` behavior:
- exit `0` for `CLEAN`
- exit `2` for `STRUCTURAL_ISSUES`
- exit `1` for runtime failures

### 4.2 diff

Purpose:
- Compare two model snapshots and list changed objects.

Modes:
- explicit two-path mode:
  - `semantic-test diff <before_path> <after_path>`
- auto-previous mode (uses index):
  - `semantic-test diff <path_after>`

Common usage:

```powershell
semantic-test diff <before> <after>
semantic-test diff <before> <after> --format json
semantic-test diff <before> <after> --strict
```

Output includes:
- change list (`AddedObject`, `RemovedObject`, `ModifiedObject`)
- change counts
- merged unknown patterns/unresolved refs from compared snapshots
- coverage summary

### 4.3 exposure

Purpose:
- For changed objects, enumerate downstream impacted objects (blast radius).

Modes:
- explicit two-path mode:
  - `semantic-test exposure <before_path> <after_path>`
- auto-previous mode:
  - `semantic-test exposure <path_after>`

Common usage:

```powershell
semantic-test exposure <before> <after>
semantic-test exposure <before> <after> --json
semantic-test exposure <before> <after> --strict
```

Output includes:
- changed objects
- downstream count and IDs
- downstream grouped by type
- top downstream items

### 4.4 trace

Purpose:
- Show dependency neighborhood for one object from latest snapshot.

Usage:

```powershell
semantic-test trace "<object_id>" <path> --depth 5
semantic-test trace "<object_id>" <path> --upstream
semantic-test trace "<object_id>" <path> --downstream
semantic-test trace "<object_id>" <path> --format json
```

Important:
- `trace` uses latest indexed snapshot for that model.
- Run `scan` first if no snapshot exists.

## 5. Canonical Object IDs

Examples:
- Table: `Table:Sales`
- Column: `Column:Sales.Amount`
- Measure: `Measure:Sales.Total Sales`
- Relationship: `Relationship:Sales.DateKey->Date.DateKey`

Use exact canonical IDs in `trace` and for interpreting diff/exposure output.

## 6. Report Artifacts and Locations

Default output root:
- `<model_root>\.semantic-test\`

Per run:
- `<model_root>\.semantic-test\runs\<RUN_ID>\manifest.json`
- `<model_root>\.semantic-test\runs\<RUN_ID>\snapshot.json`
- `<model_root>\.semantic-test\runs\<RUN_ID>\report.txt`
- `<model_root>\.semantic-test\runs\<RUN_ID>\report.json`

Index:
- `<model_root>\.semantic-test\index.json`

Notes:
- `diff` also writes legacy `diff_report.txt` and `diff_report.json`.
- `--outdir` can override the output root.

## 7. Exit Codes (Automation Contract)

- `0`: success
- `1`: runtime error (path missing, parse failure, model discovery error, etc.)
- `2`: strict policy failure (`--strict` with unresolved refs/unsupported patterns)

This is the key contract for CI/CD gating.

## 8. Practical User Workflow

### Local single-model quality gate

```powershell
semantic-test scan <model_path> --strict
```

If exit code is `2`, inspect unresolved refs/unknown patterns and fix before merge.

### PR comparison workflow (recommended)

```powershell
semantic-test diff <before_model_path> <after_model_path> --format text
semantic-test exposure <before_model_path> <after_model_path> --format text
```

Review:
- changed objects list
- downstream impacted objects
- unresolved refs and unknown patterns sections

### Trace a sensitive measure before changing it

```powershell
semantic-test scan <model_path> --stdout none
semantic-test trace "Measure:Metrics.Total Sales" <model_path> --depth 5
```

## 9. Example Commands for Your Folders

Paths:
- `D:\Projects\semantic_test\vc_test1`
- `D:\vc_test1`

Run set:

```powershell
python -m semantic_test.cli.main scan D:\Projects\semantic_test\vc_test1 --debug
python -m semantic_test.cli.main scan D:\vc_test1 --debug

python -m semantic_test.cli.main diff D:\Projects\semantic_test\vc_test1 D:\vc_test1 --format json
python -m semantic_test.cli.main exposure D:\Projects\semantic_test\vc_test1 D:\vc_test1 --json

python -m semantic_test.cli.main trace "Measure:Metrics.Total CSR Chats" D:\Projects\semantic_test\vc_test1 --depth 5
```

## 10. Known Limitations

### Model discovery constraints
- Running `scan .` in a repo with multiple semantic models will fail with:
  - `Multiple definition folders found ...`
- Fix: pass explicit model path.

### Coverage status (current)
- Supported: parser path discovery, table extraction
- Partial: columns, measures, relationships, calc groups/items (experimental), field parameters (experimental)
- Unsupported count in matrix can be zero even when partial areas still have practical gaps

See:
- `docs/coverage.md`
- `COVERAGE.md` (full registry)

### DAX parsing limits
- Conservative dependency extraction; uncommon syntax may be under-reported.
- Some unsupported patterns are disclosed explicitly.
- Unresolved/ambiguous references are reported and can fail strict mode.

### Not implemented yet
- `semantic-test test <*.semantic-test.yaml>` runner (Phase 2)

## 11. Troubleshooting

### "command not found" for `semantic-test`
Use module invocation:

```powershell
python -m semantic_test.cli.main <command> ...
```

### "No module named semantic-test"
Use underscore module path:

```powershell
python -m semantic_test.cli.main --help
```

### "Multiple definition folders found"
Do not scan repo root. Pass specific model path:

```powershell
semantic-test scan D:\Projects\semantic_test\vc_test1
```

### `trace` says no previous run found
Seed snapshot first:

```powershell
semantic-test scan <model_path> --stdout none
semantic-test trace "<object_id>" <model_path>
```

## 12. What Users Should Treat as Source of Truth

For humans:
- `report.txt`

For automation/CI:
- exit code
- `report.json`
- `manifest.json`

For historical reproducibility:
- `snapshot.json` and `run_id` under `.semantic-test/runs/`
