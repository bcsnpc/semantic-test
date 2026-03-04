# semantic-test User Guide (Beginner-Friendly)

Last updated: 2026-03-04

This guide is written for first-time PowerShell users.
All commands are copy/paste ready.

## 1. What This Tool Is

`semantic-test` checks **model structure** for Power BI semantic models (PBIP/TMDL).

It answers:
- What objects exist?
- What changed?
- What is impacted downstream?
- What references are unresolved, and what are likely fixes?

It does **not** run DAX or validate KPI business correctness.

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

Do **not** run `scan .` in a folder containing many models.
Use a specific model path.

Example:

```powershell
python -m semantic_test.cli.main scan "D:\Projects\semantic_test\vc_test1"
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
python -m semantic_test.cli.main scan "D:\Projects\semantic_test\vc_test1"
python -m semantic_test.cli.main scan "D:\Projects\semantic_test\vc_test1" --strict
python -m semantic_test.cli.main scan "D:\Projects\semantic_test\vc_test1" --debug
```

### Diff

```powershell
python -m semantic_test.cli.main diff "D:\Projects\semantic_test\vc_test1" "D:\vc_test1"
python -m semantic_test.cli.main diff "D:\Projects\semantic_test\vc_test1" "D:\vc_test1" --format json
```

### Exposure

```powershell
python -m semantic_test.cli.main exposure "D:\Projects\semantic_test\vc_test1" "D:\vc_test1" --json
```

### Trace

```powershell
python -m semantic_test.cli.main trace "Measure:Metrics.Total CSR Chats" "D:\Projects\semantic_test\vc_test1" --depth 5
```

## 7. Understanding Scan Output

Common statuses:
- `CLEAN`
- `STRUCTURAL_ISSUES`
- `ERROR`

For unresolved references, scan now shows:
- reason + severity
- `expected_type`, `expected_scope`, `likely_cause`
- `action` (what to do next)
- `best_guess` and score (when confidence is high)
- scored `did_you_mean_top3`
- optional suggested fix options with combined score

Example action values:
- `RENAME_REFERENCE`
- `QUALIFY_REFERENCE`
- `ADD_MISSING_OBJECT`
- `MANUAL_REVIEW`

## 8. Next Actions Block (Important)

The tool now prints copy/paste commands that match how you ran it.

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

Index file:
- `<model_root>\.semantic-test\index.json`

## 10. Exit Codes

- `0` success
- `1` runtime/tool error
- `2` strict structural violations (`--strict`)

## 11. Canonical IDs for Trace

- Table: `Table:Sales`
- Column: `Column:Sales.Amount`
- Measure: `Measure:Sales.Total Sales`
- Relationship: `Relationship:Sales.DateKey->Date.DateKey`

## 12. Quick Troubleshooting

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

## 13. Architecture & Coverage Docs

- [Phase-1 Architecture](PHASE1_ARCHITECTURE.md)
- [Coverage Matrix](coverage.md)
- [Detailed DAX Coverage Registry](../COVERAGE.md)
