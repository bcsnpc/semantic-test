# semantic-test User Guide

Last updated: 2026-03-07

This guide is step-by-step for installing and running all current `semantic-test` capabilities.

## 1. What the Tool Does

`semantic-test` analyzes Power BI semantic structure and report lineage.

It supports:
- Scan semantic metadata and dependencies
- Scan live Desktop model metadata
- Extract visual lineage from PBIP/PBIX/desktop-correlated artifacts
- Compare versions (`diff`)
- Analyze downstream impact (`exposure`)
- Trace object lineage (`trace`)
- Export trace graphs to Mermaid (`mmd`, `mmd-simple`)

## 2. Install

```powershell
pip install "git+https://github.com/bcsnpc/semantic-test.git"
```

If `semantic-test` command is unavailable, use module mode:

```powershell
python -m semantic_test.cli.main --help
```

## 3. Upgrade

```powershell
pip install --upgrade --no-cache-dir "git+https://github.com/bcsnpc/semantic-test.git"
```

## 4. Local Dev Install

```powershell
cd <repo>
pip install -e .
```

## 5. Model Path Rule

Avoid `scan .` if your folder has multiple semantic models.
Use an explicit model path.

```powershell
python -m semantic_test.cli.main scan "D:\path\to\YourModelRoot"
```

## 6. Commands

### 6.1 Scan (PBIP/TMDL)

```powershell
python -m semantic_test.cli.main scan "D:\path\to\YourModelRoot"
python -m semantic_test.cli.main scan "D:\path\to\YourModelRoot" --strict
python -m semantic_test.cli.main scan "D:\path\to\YourModelRoot" --debug --stdout json
```

### 6.2 Scan (Live Desktop)

```powershell
python -m semantic_test.cli.main scan desktop
python -m semantic_test.cli.main scan desktop:64078
python -m semantic_test.cli.main scan desktop --debug --stdout json
```

### 6.3 Diff

```powershell
python -m semantic_test.cli.main diff "D:\path\to\ModelA" "D:\path\to\ModelB"
python -m semantic_test.cli.main diff "D:\path\to\ModelA" "D:\path\to\ModelB" --format json
```

### 6.4 Exposure

```powershell
python -m semantic_test.cli.main exposure "D:\path\to\ModelA" "D:\path\to\ModelB"
python -m semantic_test.cli.main exposure "D:\path\to\ModelA" "D:\path\to\ModelB" --json
```

### 6.5 Trace

```powershell
python -m semantic_test.cli.main trace "Measure:Sales.Total Revenue" "D:\path\to\YourModelRoot" --depth 5
python -m semantic_test.cli.main trace "Measure:Sales.Total Revenue" "D:\path\to\YourModelRoot" --upstream --downstream --depth 5
```

### 6.6 Trace Mermaid Export

```powershell
python -m semantic_test.cli.main trace "Measure:Sales.Total Revenue" "D:\path\to\YourModelRoot" --depth 5 --export mmd
python -m semantic_test.cli.main trace "Measure:Sales.Total Revenue" "D:\path\to\YourModelRoot" --depth 5 --export mmd-simple
```

Output file:
- `<model_root>\.semantic-test\runs\<RUN_ID>\trace_graph.mmd`

## 7. Canonical Object IDs

- Table: `Table:Sales`
- Column: `Column:Sales.Amount`
- Measure: `Measure:Sales.Total Revenue`
- Relationship: `Rel:Sales.CustomerKey->Customer.CustomerKey`
- Visual: `Visual:PageName.VisualId`

## 8. Output Files

Per run:
- `report.txt`
- `report.json`
- `snapshot.json`
- `manifest.json`
- `trace_graph.mmd` (trace export only)

Stored under:
- `<model_root>\.semantic-test\runs\<RUN_ID>\...`

Index:
- `<model_root>\.semantic-test\index.json`

## 9. Exit Codes

- `0` success
- `1` runtime/tool error
- `2` strict policy failure

## 10. Troubleshooting

### 10.1 `semantic-test` not recognized

```powershell
python -m semantic_test.cli.main --help
```

### 10.2 Multiple models detected

Use an explicit model path instead of repo root.

### 10.3 Trace says no snapshot found

Run scan first:

```powershell
python -m semantic_test.cli.main scan "<model_path>" --stdout none
python -m semantic_test.cli.main trace "<object_id>" "<model_path>"
```

### 10.4 Desktop visual lineage unavailable

Run debug and inspect:

```powershell
python -m semantic_test.cli.main scan desktop --debug --stdout json
```

Useful keys:
- `debug.parity_diagnostics.visual_lineage.status`
- `debug.parity_diagnostics.visual_lineage.reason`
- `debug.parity_diagnostics.visual_discovery`

Optional same-model parity compare target:

```powershell
$env:SEMANTIC_TEST_PARITY_COMPARE_PATH="D:\path\to\YourModelRoot"
python -m semantic_test.cli.main scan desktop --debug --stdout json
```

## 11. Documentation

- [semantic-test Architecture](SEMANTIC_TEST_ARCHITECTURE.md)
- [Coverage Matrix](coverage.md)
- [Detailed DAX Coverage Registry](../COVERAGE.md)
