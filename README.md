# semantic-test

`semantic-test` is a Python CLI for structural analysis of Power BI semantic models and report lineage.

It helps teams answer:
- What objects exist in the model?
- What changed between two model versions?
- What is the blast radius of those changes?
- Why unresolved references exist and what likely fixes are available?
- Which report visuals depend on a semantic object?

## Features

- Semantic model discovery from PBIP/TMDL definition folders
- Live Desktop semantic extraction (`scan desktop`) via local Analysis Services DMVs
- Report visual lineage extraction from:
  - PBIP/PBIR report definition folders
  - PBIX files
  - process-correlated live Desktop PBIX artifacts (when available)
- Canonical object inventory: tables, columns, measures, relationships, calc groups/items, field parameters, visuals
- Dependency graph build and deterministic snapshot hashing
- Snapshot comparison (`diff`) and blast radius analysis (`exposure`)
- Object lineage trace (`trace`) with downstream visual dependency details
- Mermaid trace export:
  - `--export mmd` (full)
  - `--export mmd-simple` (cleaned business-readable)
- Strict CI gating (`--strict` + exit code `2`)
- Rich unresolved diagnostics with ranked suggestions and fix hints

## Install

Requirements:
- Python 3.10+

Install from GitHub:

```bash
pip install "git+https://github.com/bcsnpc/semantic-test.git"
```

If command is not on PATH:

```bash
python -m semantic_test.cli.main --help
```

Install for local development:

```bash
pip install -e .
```

## Update

```bash
pip install --upgrade --no-cache-dir "git+https://github.com/bcsnpc/semantic-test.git"
```

Editable local clone update:

```bash
git pull
```

## Commands

```bash
python -m semantic_test.cli.main scan "<model_path>"
python -m semantic_test.cli.main scan desktop
python -m semantic_test.cli.main scan desktop:<port>
python -m semantic_test.cli.main diff "<before_path>" "<after_path>"
python -m semantic_test.cli.main exposure "<before_path>" "<after_path>" --json
python -m semantic_test.cli.main trace "<object_id>" "<model_path>" --depth 5
python -m semantic_test.cli.main trace "<object_id>" "<model_path>" --depth 5 --export mmd
python -m semantic_test.cli.main trace "<object_id>" "<model_path>" --depth 5 --export mmd-simple
```

## Output Artifacts

```text
.semantic-test/
  index.json
  runs/
    <RUN_ID>/
      manifest.json
      snapshot.json
      report.txt
      report.json
      trace_graph.mmd   # when trace --export is used
```

## Exit Codes

- `0`: success
- `1`: runtime/tool failure
- `2`: strict structural policy failure (`--strict`)

## Documentation

- [User Guide](docs/USER_GUIDE.md)
- [semantic-test Architecture](docs/SEMANTIC_TEST_ARCHITECTURE.md)
- [Coverage Matrix](docs/coverage.md)
- [Detailed Coverage Registry](COVERAGE.md)

## Development

Run tests from local source:

```bash
$env:PYTHONPATH="<repo>\\src"
python -m unittest
```
