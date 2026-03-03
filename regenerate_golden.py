"""One-time script to regenerate golden test fixtures after schema changes."""
import io
import json
import re
import sys
import tempfile
from pathlib import Path

# Force UTF-8 stdout so coverage icons render as emoji (matching pytest env)
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, "src")

from typer.testing import CliRunner  # noqa: E402
from semantic_test.cli.main import app  # noqa: E402
from semantic_test.core.analysis.exposure import analyze_exposure  # noqa: E402
from semantic_test.core.diff.differ import diff_snapshots  # noqa: E402
from semantic_test.core.diff.snapshot import build_snapshot  # noqa: E402
from semantic_test.core.graph.builder import build_dependency_graph  # noqa: E402
from semantic_test.core.model.coverage import coverage_report  # noqa: E402
from semantic_test.core.report.format_json import format_report_json  # noqa: E402
from semantic_test.core.report.format_text import format_pr_text  # noqa: E402

runner = CliRunner()
repo_root = Path(".").resolve()
fixture_root = repo_root / "tests/fixtures/regression_models"
golden_root = Path("tests/fixtures/golden/regression_v1")
base_golden = Path("tests/fixtures/golden")


def normalize_text(text: str) -> str:
    repo_str = str(repo_root)
    repo_posix = repo_root.as_posix()
    normalized = text.replace(repo_str, "<REPO>").replace(repo_posix, "<REPO>")
    normalized = normalized.replace("\\", "/")
    normalized = re.sub(r"Run ID: .*", "Run ID: <RUN_ID>", normalized)
    normalized = re.sub(
        r"Old Snapshot Hash: .*", "Old Snapshot Hash: <SNAPSHOT_HASH>", normalized
    )
    normalized = re.sub(
        r"New Snapshot Hash: .*", "New Snapshot Hash: <SNAPSHOT_HASH>", normalized
    )
    return normalized.rstrip("\n") + "\n"


def normalize_json(text: str) -> str:
    repo_str = str(repo_root)
    repo_posix = repo_root.as_posix()
    payload = json.loads(text)

    def walk(value, key=None):
        if isinstance(value, dict):
            return {k: walk(value[k], key=k) for k in sorted(value.keys())}
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, str):
            if key == "run_folder":
                return "<RUN_FOLDER>"
            if key in {"run_id"}:
                return "<RUN_ID>"
            if key in {"old_snapshot_hash", "new_snapshot_hash", "snapshot_hash"}:
                return "<SNAPSHOT_HASH>"
            out = value.replace(repo_str, "<REPO>").replace(repo_posix, "<REPO>")
            out = out.replace("\\", "/")
            return out
        return value

    normalized = walk(payload)
    return json.dumps(normalized, indent=2, sort_keys=True) + "\n"


def get_new_run_folder(runs_root, before):
    after = set(runs_root.iterdir()) if runs_root.exists() else set()
    new_dirs = sorted([p for p in (after - before) if p.is_dir()], key=lambda p: p.name)
    return new_dirs[-1]


# --- Report formatter goldens (unit tests) ---
before_objects = {
    "Column:Sales.Amount": {"type": "Column", "name": "Amount", "dependencies": set()},
    "Measure:Sales.Base": {
        "type": "Measure", "name": "Base",
        "raw_expression": "SUM(Sales[Amount])", "dependencies": {"Column:Sales.Amount"},
    },
    "Measure:Sales.Total": {
        "type": "Measure", "name": "Total",
        "raw_expression": "[Base] + 1", "dependencies": {"Measure:Sales.Base"},
    },
}
after_objects = {
    "Column:Sales.Amount": {"type": "Column", "name": "Amount", "dependencies": set()},
    "Measure:Sales.Base": {
        "type": "Measure", "name": "Base",
        "raw_expression": "SUM(Sales[Amount]) + 0", "dependencies": {"Column:Sales.Amount"},
    },
    "Measure:Sales.Total": {
        "type": "Measure", "name": "Total",
        "raw_expression": "[Base] + 1", "dependencies": {"Measure:Sales.Base"},
    },
    "Measure:Sales.NewKpi": {
        "type": "Measure", "name": "NewKpi",
        "raw_expression": "[Base]", "dependencies": {"Measure:Sales.Base"},
    },
}
before_graph = build_dependency_graph(before_objects)
after_graph = build_dependency_graph(after_objects)
before_snapshot = build_snapshot(
    before_objects, before_graph,
    model_key="semanticmodel::fixtures/report_model/definition",
    definition_path="fixtures/report_model/definition",
)
after_snapshot = build_snapshot(
    after_objects, after_graph,
    model_key="semanticmodel::fixtures/report_model/definition",
    definition_path="fixtures/report_model/definition",
)
diff_result = diff_snapshots(before_snapshot, after_snapshot)
exposure_result = analyze_exposure(diff_result, after_graph, top_n=3)
coverage_lines, coverage_data = coverage_report()

text_out = format_pr_text(
    diff_result=diff_result, exposure_result=exposure_result,
    run_id="20260302_214533_exposure_fixture_1234abcd",
    model_key="semanticmodel::fixtures/report_model/definition",
    old_snapshot_hash=before_snapshot.snapshot_hash,
    new_snapshot_hash=after_snapshot.snapshot_hash,
    coverage_lines=coverage_lines, coverage_data=coverage_data, unresolved_refs=[],
)
json_out = format_report_json(
    diff_result=diff_result, exposure_result=exposure_result, coverage_data=coverage_data,
    run_id="20260302_214533_exposure_fixture_1234abcd",
    model_key="semanticmodel::fixtures/report_model/definition",
    old_snapshot_hash=before_snapshot.snapshot_hash,
    new_snapshot_hash=after_snapshot.snapshot_hash,
    unresolved_refs=[],
)
(base_golden / "report_text_v1.txt").write_text(text_out, encoding="utf-8")
(base_golden / "report_json_v1.json").write_text(json_out, encoding="utf-8")
print("Written report_text_v1.txt and report_json_v1.json")

# --- Regression golden files ---
pairs = [
    ("model_a", "model_b"),
    ("model_a", "model_c"),
    ("model_a", "model_d"),
    ("model_a", "model_e"),
]

with tempfile.TemporaryDirectory() as tmp:
    outdir = Path(tmp) / ".semantic-test"
    runs_root = outdir / "runs"

    for old_model, new_model in pairs:
        pair_key = f"{old_model}_to_{new_model}"
        old_path = (fixture_root / old_model).as_posix()
        new_path = (fixture_root / new_model).as_posix()

        # Diff JSON
        before = set(runs_root.iterdir()) if runs_root.exists() else set()
        runner.invoke(app, ["diff", old_path, new_path, "--format", "json", "--outdir", outdir.as_posix()])
        run_folder = get_new_run_folder(runs_root, before)
        (golden_root / "diff" / pair_key / "diff_report.json").write_text(
            normalize_json((run_folder / "diff_report.json").read_text(encoding="utf-8")),
            encoding="utf-8",
        )

        # Diff TEXT
        before = set(runs_root.iterdir()) if runs_root.exists() else set()
        runner.invoke(app, ["diff", old_path, new_path, "--format", "text", "--outdir", outdir.as_posix()])
        run_folder = get_new_run_folder(runs_root, before)
        (golden_root / "diff" / pair_key / "diff_report.txt").write_text(
            normalize_text((run_folder / "diff_report.txt").read_text(encoding="utf-8")),
            encoding="utf-8",
        )

        # Exposure TEXT + JSON
        before = set(runs_root.iterdir()) if runs_root.exists() else set()
        runner.invoke(app, ["exposure", old_path, new_path, "--format", "text", "--outdir", outdir.as_posix()])
        run_folder = get_new_run_folder(runs_root, before)
        (golden_root / "exposure" / pair_key / "exposure_report.txt").write_text(
            normalize_text((run_folder / "report.txt").read_text(encoding="utf-8")),
            encoding="utf-8",
        )
        (golden_root / "exposure" / pair_key / "exposure_report.json").write_text(
            normalize_json((run_folder / "report.json").read_text(encoding="utf-8")),
            encoding="utf-8",
        )

        print(f"Regenerated all golden files for {pair_key}")

print("All golden files updated.")
