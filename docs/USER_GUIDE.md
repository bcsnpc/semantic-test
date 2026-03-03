# semantic-test User Guide (Beginner-Friendly)

Last updated: 2026-03-03

This guide is written for users who are new to PowerShell.
It gives exact commands to copy and run.

## 1. What This Tool Does

`semantic-test` checks the **structure** of a Power BI semantic model (PBIP/TMDL).

It helps you answer:
- What tables/columns/measures exist?
- What changed between two model folders?
- Which downstream objects are impacted by those changes?
- What dependencies does a specific measure/object have?

It does **not** execute DAX and does not validate business KPI correctness.

## 2. Before You Start

You need:
- Windows PowerShell
- Python 3.10+
- Internet access (for install from GitHub)

Check Python:

```powershell
python --version
```

If Python is not found, install Python first.

## 3. Install the Tool from GitHub

Install:

```powershell
pip install "git+https://github.com/bcsnpc/semantic-test.git"
```

## 3A. Update the Tool Later (No Manual Uninstall Needed)

If you already installed once, run this to get latest code from GitHub:

```powershell
pip install --upgrade --no-cache-dir "git+https://github.com/bcsnpc/semantic-test.git"
```

Notes:
- You do NOT need to uninstall first.
- This updates your current installed package to the latest commit/tag available.

If you installed from a local clone using `pip install -e .`, then update by:

```powershell
cd <your-local-semantic-test-repo>
git pull
```

## 4. First Command to Try

Try this first:

```powershell
python -m semantic_test.cli.main --help
```

Why this command?
- It works even when `semantic-test` is not in PATH.
- It is the safest default command style for beginners.

## 5. If `semantic-test` Command Is Not Found

You may see:
- `semantic-test : The term 'semantic-test' is not recognized...`

This means your Python Scripts folder is not on PATH.

### Option A (recommended): keep using module style

Use this pattern always:

```powershell
python -m semantic_test.cli.main <command> ...
```

### Option B: add Scripts folder to PATH

Run this once:

```powershell
$scriptPath = "C:\Users\$env:USERNAME\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\LocalCache\local-packages\Python312\Scripts"
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";$scriptPath", "User")
```

Then close PowerShell and open a new window.

Now test:

```powershell
semantic-test --help
```

## 6. Most Important Rule (Avoid Common Error)

Do **not** run `scan .` in a repo that has multiple models.

If you do, you can get:
- `Multiple definition folders found ...`

Always pass a specific model folder path, for example:

```powershell
python -m semantic_test.cli.main scan D:\Projects\semantic_test\vc_test1
```

## 7. Commands (All Current Functions)

Current commands in v0.1.0:
- `scan`
- `diff`
- `exposure`
- `trace`

`semantic-test test ...` is not implemented yet.

### 7.1 `scan` - Analyze one model

Purpose:
- Builds inventory and dependency graph
- Finds unresolved references and unsupported patterns
- Writes reports

Run:

```powershell
python -m semantic_test.cli.main scan <model_path>
```

Example:

```powershell
python -m semantic_test.cli.main scan D:\Projects\semantic_test\vc_test1
```

Useful options:

```powershell
python -m semantic_test.cli.main scan <model_path> --strict
python -m semantic_test.cli.main scan <model_path> --debug
python -m semantic_test.cli.main scan <model_path> --show-all
python -m semantic_test.cli.main scan <model_path> --stdout json
python -m semantic_test.cli.main scan <model_path> --stdout none
python -m semantic_test.cli.main scan <model_path> --no-index
python -m semantic_test.cli.main scan <model_path> --outdir D:\temp\semantic-out
```

Expected status values:
- `CLEAN`
- `STRUCTURAL_ISSUES`
- `ERROR`

### 7.2 `diff` - Compare two model folders

Purpose:
- Shows added/removed/modified objects between two model versions

Run:

```powershell
python -m semantic_test.cli.main diff <before_path> <after_path>
```

Example:

```powershell
python -m semantic_test.cli.main diff D:\Projects\semantic_test\vc_test1 D:\vc_test1
```

Useful options:

```powershell
python -m semantic_test.cli.main diff <before> <after> --format json
python -m semantic_test.cli.main diff <before> <after> --strict
python -m semantic_test.cli.main diff <before> <after> --out D:\temp\diff.json
```

Auto-previous mode (single argument):

```powershell
python -m semantic_test.cli.main scan <model_path> --stdout none
python -m semantic_test.cli.main diff <model_path>
```

### 7.3 `exposure` - Blast radius from changes

Purpose:
- Lists downstream impacted objects for each changed object

Run:

```powershell
python -m semantic_test.cli.main exposure <before_path> <after_path>
```

Example:

```powershell
python -m semantic_test.cli.main exposure D:\Projects\semantic_test\vc_test1 D:\vc_test1 --json
```

Useful options:

```powershell
python -m semantic_test.cli.main exposure <before> <after> --json
python -m semantic_test.cli.main exposure <before> <after> --strict
python -m semantic_test.cli.main exposure <before> <after> --out D:\temp\exposure.json --json
```

### 7.4 `trace` - Upstream/downstream dependencies for one object

Purpose:
- Shows what an object depends on and what depends on it

Run:

```powershell
python -m semantic_test.cli.main trace "<object_id>" <model_path>
```

Example:

```powershell
python -m semantic_test.cli.main trace "Measure:Metrics.Total CSR Chats" D:\Projects\semantic_test\vc_test1 --depth 5
```

Useful options:

```powershell
python -m semantic_test.cli.main trace "<object_id>" <model_path> --upstream
python -m semantic_test.cli.main trace "<object_id>" <model_path> --downstream
python -m semantic_test.cli.main trace "<object_id>" <model_path> --format json
```

Note:
- If `trace` says no snapshot found, run `scan` first.

## 8. Canonical Object ID Format (for `trace`)

Use these exact formats:
- Table: `Table:Sales`
- Column: `Column:Sales.Amount`
- Measure: `Measure:Sales.Total Sales`
- Relationship: `Relationship:Sales.DateKey->Date.DateKey`

## 9. Output Files You Will Get

By default, output is written under the model root:

- `<model_path>\.semantic-test\index.json`
- `<model_path>\.semantic-test\runs\<RUN_ID>\manifest.json`
- `<model_path>\.semantic-test\runs\<RUN_ID>\snapshot.json`
- `<model_path>\.semantic-test\runs\<RUN_ID>\report.txt`
- `<model_path>\.semantic-test\runs\<RUN_ID>\report.json`

Use `report.txt` for human reading.
Use `report.json` + exit code for automation.

## 10. Exit Codes (Important for CI)

- `0` = success
- `1` = runtime error
- `2` = strict policy failure (`--strict`)

## 11. Beginner Workflow (Copy-Paste)

Use this exact sequence:

```powershell
# 1) Scan current model
python -m semantic_test.cli.main scan D:\Projects\semantic_test\vc_test1 --strict

# 2) Compare with another folder
python -m semantic_test.cli.main diff D:\Projects\semantic_test\vc_test1 D:\vc_test1 --format json

# 3) See blast radius
python -m semantic_test.cli.main exposure D:\Projects\semantic_test\vc_test1 D:\vc_test1 --json

# 4) Trace one critical measure
python -m semantic_test.cli.main trace "Measure:Metrics.Total CSR Chats" D:\Projects\semantic_test\vc_test1 --depth 5
```

## 12. Troubleshooting Quick Fixes

### Error: `semantic-test` not recognized
Use:

```powershell
python -m semantic_test.cli.main --help
```

### Error: `No module named semantic-test`
Use underscore module path:

```powershell
python -m semantic_test.cli.main --help
```

### Error: `Multiple definition folders found`
You scanned too high-level a folder.
Run with a specific model path:

```powershell
python -m semantic_test.cli.main scan D:\Projects\semantic_test\vc_test1
```

### `trace` shows no previous run
Run scan first:

```powershell
python -m semantic_test.cli.main scan D:\Projects\semantic_test\vc_test1 --stdout none
python -m semantic_test.cli.main trace "Measure:Metrics.Total CSR Chats" D:\Projects\semantic_test\vc_test1
```

## 13. Current Limitations

- No `semantic-test test <yaml>` command yet (Phase 2 not implemented).
- Dependency extraction is structural and conservative; some uncommon DAX patterns may be partial.
- Experimental coverage areas include calc groups/items and field parameters.
- Tool does not validate business correctness of measures.
