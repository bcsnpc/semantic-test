"""Integration tests for CLI command wiring."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from typer.testing import CliRunner

from semantic_test.cli.main import app


class CliCommandsIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_scan_outputs_inventory_coverage_and_graph_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_root = _write_model(Path(tmp), "ModelA", "1")
            result = self.runner.invoke(app, ["scan", str(model_root)])

            self.assertEqual(result.exit_code, 0, msg=result.stdout)
            self.assertIn("Status: CLEAN", result.stdout)
            self.assertIn("Graph: Nodes:", result.stdout)
            self.assertIn("Top Dependency Hubs", result.stdout)

    def test_diff_outputs_changes_text_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            before_root = _write_model(base / "before", "ModelA", "1")
            after_root = _write_model(base / "after", "ModelA", "2")

            text_result = self.runner.invoke(
                app, ["diff", str(before_root), str(after_root)]
            )
            self.assertEqual(text_result.exit_code, 0, msg=text_result.stdout)
            self.assertIn("Diff Report", text_result.stdout)
            self.assertIn("ModifiedObject", text_result.stdout)

            json_result = self.runner.invoke(
                app,
                [
                    "diff",
                    str(before_root),
                    str(after_root),
                    "--format",
                    "json",
                ],
            )
            self.assertEqual(json_result.exit_code, 0, msg=json_result.stdout)
            payload = json.loads(json_result.stdout)
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["detected_changes"]["modified"], 1)

    def test_diff_auto_previous_first_run_message(self) -> None:
        with self.runner.isolated_filesystem():
            model_root = _write_model(Path("."), "ModelA", "1")
            result = self.runner.invoke(app, ["diff", str(model_root)])
            self.assertEqual(result.exit_code, 0, msg=result.stdout)
            self.assertIn("No previous run found for this model. Run scan first.", result.stdout)

    def test_exposure_supports_json_flag_and_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            before_root = _write_model(base / "before", "ModelA", "1")
            after_root = _write_model(base / "after", "ModelA", "2")
            out_file = base / "exposure.json"

            result = self.runner.invoke(
                app,
                [
                    "exposure",
                    str(before_root),
                    str(after_root),
                    "--json",
                    "--out",
                    str(out_file),
                ],
            )

            self.assertEqual(result.exit_code, 0, msg=result.stdout)
            self.assertTrue(out_file.exists())
            payload = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 1)
            self.assertGreaterEqual(payload["detected_changes"]["total"], 1)

    def test_exposure_auto_previous_creates_run_folder_and_prints_location(self) -> None:
        with self.runner.isolated_filesystem():
            model_root = _write_model(Path("."), "ModelA", "1")
            seed = self.runner.invoke(app, ["scan", str(model_root), "--stdout", "none"])
            self.assertEqual(seed.exit_code, 0, msg=seed.stdout)

            result = self.runner.invoke(app, ["exposure", str(model_root)])
            self.assertEqual(result.exit_code, 0, msg=result.stdout)
            self.assertIn("Saved: report.txt, report.json to", result.stdout)

            run_folder = _latest_run_folder(Path(".semantic-test") / "runs")
            self.assertTrue((run_folder / "snapshot.json").exists())
            self.assertTrue((run_folder / "report.json").exists())
            self.assertTrue((run_folder / "report.txt").exists())
            self.assertTrue((run_folder / "manifest.json").exists())

    def test_unknown_patterns_warn_and_strict_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_root = _write_model(Path(tmp), "ModelA", "[MissingMeasure]")
            warn_result = self.runner.invoke(app, ["scan", str(model_root)])
            self.assertEqual(warn_result.exit_code, 0, msg=warn_result.stdout)
            self.assertIn("Status: STRUCTURAL_ISSUES", warn_result.stdout)
            self.assertIn("Unsupported Reference Patterns", warn_result.stdout)
            self.assertIn("- missing: [MissingMeasure]", warn_result.stdout)

            strict_result = self.runner.invoke(
                app,
                ["scan", str(model_root), "--strict"],
            )
            self.assertEqual(strict_result.exit_code, 2, msg=strict_result.stdout)

    def test_run_folder_and_manifest_created_on_success(self) -> None:
        with self.runner.isolated_filesystem():
            model_root = _write_model(Path("."), "ModelA", "1")
            result = self.runner.invoke(app, ["scan", str(model_root)])

            self.assertEqual(result.exit_code, 0, msg=result.stdout)
            run_folder = _latest_run_folder(Path(".semantic-test") / "runs")
            self.assertTrue(run_folder.exists())
            manifest = json.loads((run_folder / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["command"], "scan")
            self.assertEqual(manifest["status"], "CLEAN")
            index_path = Path(".semantic-test") / "index.json"
            self.assertTrue(index_path.exists())
            index_obj = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(index_obj["schema_version"], "1")
            self.assertEqual(len(index_obj["models"]), 1)
            entry = index_obj["models"][0]
            self.assertEqual(entry["latest_run_id"], run_folder.name)
            self.assertEqual(entry["latest_run_path"], run_folder.as_posix())
            self.assertIn(".SemanticModel/definition", entry["definition_path"])
            self.assertTrue(entry["model_key"].startswith("semanticmodel::"))

    def test_manifest_created_even_when_parse_fails(self) -> None:
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(app, ["scan", "missing-model"])

            self.assertEqual(result.exit_code, 1)
            self.assertIn("Status: ERROR", result.stdout)
            run_folder = _latest_run_folder(Path(".semantic-test") / "runs")
            self.assertTrue(run_folder.exists())
            manifest = json.loads((run_folder / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["command"], "scan")
            self.assertEqual(manifest["status"], "ERROR")
            self.assertIn("missing-model", manifest["error"])

    def test_same_model_key_across_different_working_directories(self) -> None:
        with self.runner.isolated_filesystem():
            project_root = Path(".").resolve()
            model_root = _write_model(project_root, "ModelA", "1")

            result_a = self.runner.invoke(app, ["scan", str(model_root)])
            self.assertEqual(result_a.exit_code, 0, msg=result_a.stdout)

            subdir = project_root / "nested" / "work"
            subdir.mkdir(parents=True, exist_ok=True)
            previous_cwd = Path.cwd()
            os.chdir(subdir)
            try:
                result_b = self.runner.invoke(app, ["scan", "..\\.."])
            finally:
                os.chdir(previous_cwd)
            self.assertEqual(result_b.exit_code, 0, msg=result_b.stdout)

            index_obj = json.loads((project_root / ".semantic-test" / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(len(index_obj["models"]), 1)
            entry = index_obj["models"][0]
            self.assertEqual(entry["definition_path"], "ModelA.SemanticModel/definition")

    def test_scan_writes_full_run_artifacts_and_supports_no_index(self) -> None:
        with self.runner.isolated_filesystem():
            model_root = _write_model(Path("."), "ModelA", "1")
            result = self.runner.invoke(
                app,
                [
                    "scan",
                    str(model_root),
                    "--format",
                    "both",
                    "--stdout",
                    "none",
                    "--no-index",
                ],
            )

            self.assertEqual(result.exit_code, 0, msg=result.stdout)
            run_folder = _latest_run_folder(Path(".semantic-test") / "runs")
            self.assertTrue((run_folder / "snapshot.json").exists())
            self.assertTrue((run_folder / "report.txt").exists())
            self.assertTrue((run_folder / "report.json").exists())
            self.assertTrue((run_folder / "manifest.json").exists())
            self.assertIn("Saved reports to:", result.stdout)
            self.assertFalse((Path(".semantic-test") / "index.json").exists())


def _write_model(base: Path, model_name: str, measure_expression: str) -> Path:
    definition = base / f"{model_name}.SemanticModel" / "definition"
    definition.mkdir(parents=True, exist_ok=True)
    (definition / "model.tmdl").write_text(
        "\n".join(
            [
                "table Metrics",
                f"\tmeasure KPI = {measure_expression}",
            ]
        ),
        encoding="utf-8",
    )
    return base


def _latest_run_folder(runs_root: Path) -> Path:
    run_folders = sorted([path for path in runs_root.iterdir() if path.is_dir()])
    if not run_folders:
        raise AssertionError(f"No run folders found under {runs_root}")
    return run_folders[-1]


if __name__ == "__main__":
    unittest.main()
