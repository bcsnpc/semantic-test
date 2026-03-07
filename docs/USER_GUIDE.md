# semantic-test User Guide (Beginner-Friendly)

Last updated: 2026-03-07

This guide is written for first-time PowerShell users.
All commands are copy/paste ready.

## 1. What This Tool Is

`semantic-test` checks model structure for Power BI semantic models.

It answers:
- What objects exist?
- What changed?
- What is impacted downstream?
- What references are unresolved, and what are likely fixes?
- Which report visuals depend on a semantic object?

It does not run DAX or validate KPI business correctness.

## 2. Install

```powershell
pip install "git+https://github.com/bcsnpc/semantic-test.git"
```

If `semantic-test` is not found, use module mode (always works):

```powershell
python -m semantic_test.cli.main --help
```

## 3. Update Later (No Uninstall Needed)

```powershell
pip install --upgrade --no-cache-dir "git+https://github.com/bcsnpc/semantic-test.git"
```

If you use editable local repo install (`pip install -e .`):

```powershell
cd <repo>
git pull
```

## 4. Most Important Rule

Do not run `scan .` in a folder containing many models.
Use a specific model path.

Example:

```powershell
python -m semantic_test.cli.main scan "D:\path\to\YourModelRoot"
```

## 5. Phase-1 Commands

- `scan`
- `diff`
- `exposure`
- `trace`

Phase-2 `semantic-test test` is not implemented yet.

## 6. Command Examples

### Scan

```powershell
python -m semantic_test.cli.main scan "D:\path\to\YourModelRoot"
python -m semantic_test.cli.main scan "D:\path\to\YourModelRoot" --strict
python -m semantic_test.cli.main scan "D:\path\to\YourModelRoot" --debug
```

Desktop scan:

```powershell
python -m semantic_test.cli.main scan desktop
python -m semantic_test.cli.main scan desktop:64078
```

### Diff

```powershell
python -m semantic_test.cli.main diff "D:\path\to\ModelA" "D:\path\to\ModelB"
python -m semantic_test.cli.main diff "D:\path\to\ModelA" "D:\path\to\ModelB" --format json
```

### Exposure

```powershell
python -m semantic_test.cli.main exposure "D:\path\to\ModelA" "D:\path\to\ModelB" --json
```

### Trace

```powershell
python -m semantic_test.cli.main trace "Measure:Sales.Total Revenue" "D:\path\to\YourModelRoot" --depth 5
```

Trace with Mermaid export:

```powershell
python -m semantic_test.cli.main trace "Measure:Sales.Total Revenue" "D:\path\to\YourModelRoot" --depth 5 --export mmd
python -m semantic_test.cli.main trace "Measure:Sales.Total Revenue" "D:\path\to\YourModelRoot" --depth 5 --export mmd-simple
```

## 7. Understanding Scan Output

Common statuses:
- `CLEAN`
- `STRUCTURAL_ISSUES`
- `ERROR`

For unresolved references, scan shows:
- reason + severity
- `expected_type`, `expected_scope`, `likely_cause`
- `action` (what to do next)
- `best_guess` and score (when confidence is high)
- scored `did_you_mean_top3`
- optional suggested fix options with combined score

## 8. Next Actions Block

The tool prints copy/paste commands that match how you ran it.

If you run with module mode, it will suggest:
- `python -m semantic_test.cli.main ...`

If CLI is installed, it may also show:
- `semantic-test ...`

All paths are quoted to handle spaces.

If CLI is missing, scan shows this quick hint:
- `Install CLI entrypoint (dev): pip install -e .`

## 9. Output Files

Per run, files are written to:

- `<model_root>\.semantic-test\runs\<RUN_ID>\report.txt`
- `<model_root>\.semantic-test\runs\<RUN_ID>\report.json`
- `<model_root>\.semantic-test\runs\<RUN_ID>\snapshot.json`
- `<model_root>\.semantic-test\runs\<RUN_ID>\manifest.json`
- `<model_root>\.semantic-test\runs\<RUN_ID>\trace_graph.mmd` (only when `trace --export` is used)

Index file:
- `<model_root>\.semantic-test\index.json`

## 10. Exit Codes

- `0` success
- `1` runtime/tool error
- `2` strict structural violations (`--strict`)

## 11. Canonical IDs for Trace

- Table: `Table:Sales`
- Column: `Column:Sales.Amount`
- Measure: `Measure:Sales.Total Revenue`
- Relationship: `Relationship:Sales.DateKey->Date.DateKey`

## 12. Visual Lineage Notes

- PBIP/PBIR report definitions are supported for visual lineage.
- PBIX files on disk are supported for visual lineage.
- Desktop semantic extraction works from local Analysis Services DMVs.
- Desktop visual lineage is available when a report artifact (for example PBIX) can be linked to the active Desktop session.
- If live visual artifacts are not discoverable in the current environment, `scan desktop --debug` reports this explicitly.

## 13. Quick Troubleshooting

### `semantic-test` not recognized
Use:

```powershell
python -m semantic_test.cli.main --help
```

### Multiple definition folders found
Use a specific model path, not repo root.

### `trace` says no previous snapshot
Run scan first:

```powershell
python -m semantic_test.cli.main scan "<model_path>" --stdout none
python -m semantic_test.cli.main trace "<object_id>" "<model_path>"
```

### `scan desktop --debug` shows visual lineage unavailable

Run:

```powershell
python -m semantic_test.cli.main scan desktop --debug --stdout json
```

Check:
- `debug.parity_diagnostics.visual_lineage.status`
- `debug.parity_diagnostics.visual_lineage.reason`
- `debug.parity_diagnostics.visual_discovery`

For same-model parity comparison, set:

```powershell
$env:SEMANTIC_TEST_PARITY_COMPARE_PATH="D:\path\to\YourModelRoot"
python -m semantic_test.cli.main scan desktop --debug --stdout json
```

## 14. Architecture & Coverage Docs

- [Phase-1 Architecture](PHASE1_ARCHITECTURE.md)
- [Architecture (Consolidated)](ARCHITECTURE.md)
- [Coverage Matrix](coverage.md)
- [Detailed DAX Coverage Registry](../COVERAGE.md)
