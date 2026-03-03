# semantic-test

`semantic-test` performs structural analysis for Power BI semantic models (PBIP/TMDL):
- object inventory (tables, columns, measures, relationships, calc groups, field parameters)
- deterministic snapshot generation
- snapshot diffing (added/removed/modified objects)
- downstream exposure enumeration for changed objects

## What It Does

- Parses model definitions from `*.SemanticModel/definition/`.
- Extracts dependency links and builds a directed dependency graph.
- Produces PR-friendly text reports and machine-readable JSON artifacts.
- Persists run artifacts under `.semantic-test/runs/<RUN_ID>/` for traceability.

## What It Does Not Do

- Does not assign severity labels (`High`, `Medium`, `Low`).
- Does not predict KPI/business impact correctness.
- Does not execute DAX or validate report visuals.

All outputs should be interpreted as structural exposure only.

## Offline Security Model

- Runs locally against files on disk.
- No outbound network calls are required for scan/trace/diff/exposure workflows.
- Artifacts are written locally under `.semantic-test/` (or `--outdir`).
- Suitable for restricted CI environments where internet egress is blocked.

## Install

Requirements:
- Python 3.10+

Install from GitHub:

```bash
pip install "git+https://github.com/bcsnpc/semantic-test.git"
```

If `semantic-test` is not available on PATH, run with module style:

```bash
python -m semantic_test.cli.main --help
```

Install for local development (editable):

```bash
pip install -e .
semantic-test --help
```

## Update (Without Manual Uninstall)

If already installed from GitHub, update in place:

```bash
pip install --upgrade --no-cache-dir "git+https://github.com/bcsnpc/semantic-test.git"
```

If using editable clone (`pip install -e .`), just pull latest code:

```bash
git pull
```

## Commands and Examples

The commands below are copy-paste runnable from repo root.

### Scan

```bash
semantic-test scan tests/fixtures/regression_models/model_a
```

```bash
semantic-test scan tests/fixtures/regression_models/model_a --format both --stdout text
```

Strict policy gate:

```bash
semantic-test scan tests/fixtures/regression_models/model_a --strict
```

### Diff

```bash
semantic-test diff tests/fixtures/regression_models/model_a tests/fixtures/regression_models/model_b
```

```bash
semantic-test diff tests/fixtures/regression_models/model_a tests/fixtures/regression_models/model_b --format json
```

Auto-previous mode (uses index):

```bash
semantic-test diff tests/fixtures/regression_models/model_a
```

### Trace

```bash
semantic-test trace "Measure:Metrics.Executive KPI" tests/fixtures/regression_models/model_a --depth 5
```

```bash
semantic-test trace "Measure:Metrics.Executive KPI" tests/fixtures/regression_models/model_a --upstream --depth 3
```

### Exposure

```bash
semantic-test exposure tests/fixtures/regression_models/model_a tests/fixtures/regression_models/model_b
```

```bash
semantic-test exposure tests/fixtures/regression_models/model_a tests/fixtures/regression_models/model_b --json
```

Auto-previous mode (uses index):

```bash
semantic-test exposure tests/fixtures/regression_models/model_a
```

## Output Artifacts

Default output root:

```text
.semantic-test/
  index.json
  runs/
    <RUN_ID>/
      manifest.json
      snapshot.json
      report.txt
      report.json
```

Command-specific files:
- `scan`: `report.txt`, `report.json`, `snapshot.json`, `manifest.json`
- `trace`: `report.txt`, `report.json`, `snapshot.json`, `manifest.json`
- `diff`: `report.txt`, `report.json`, `snapshot.json`, `manifest.json` (`diff_report.*` legacy copies are also emitted)
- `exposure`: `report.txt`, `report.json`, `snapshot.json`, `manifest.json`

## Exit Codes

- `0`: success
- `1`: runtime error (invalid path, parse/runtime failure)
- `2`: strict policy failure (`--strict`)

Strict policy currently fails when:
- unknown patterns are found
- unresolved refs are found

## Coverage and Limitations

- Coverage matrix is printed in command outputs.
- Detailed coverage status: [docs/coverage.md](docs/coverage.md)
- Known gaps, unknown patterns, and unresolved refs are always disclosed in reports.
- Parsing and dependency extraction are intentionally conservative and may under-report uncommon syntax.
- Calculation groups and field parameters are included with experimental coverage notes.

## How To Use In PR Review

Recommended flow:

```bash
semantic-test scan <model_path> --strict
semantic-test exposure <model_path> --format text
```

Review checklist:
- Confirm changed object list is expected.
- Review downstream dependents for affected tables/measures.
- Check unknown patterns and unresolved refs sections (must be empty for clean gate).
- Attach `report.txt` (and optionally `report.json`) to the PR discussion.

Phase 2 preview: severity scoring and policy profiles can be layered on top of these artifacts without changing core snapshot/exposure format contracts.

## Development

Run tests locally:

```bash
pytest -q
```
