"""End-to-end CLI integration tests for run artifacts, outputs, and strict exits."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from typer.testing import CliRunner

from semantic_test.cli.main import app


class CliEndToEndIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_scan_creates_run_files_updates_index_and_prints_sections(self) -> None:
        with self.runner.isolated_filesystem():
            model_root = _write_model(Path("."), "ModelA", "1")
            result = self.runner.invoke(app, ["scan", str(model_root)])

            self.assertEqual(result.exit_code, 0, msg=result.stdout)
            self.assertIn("Status: CLEAN", result.stdout)
            self.assertIn("Top Dependency Hubs", result.stdout)

            run_folder = _latest_run_folder(Path(".semantic-test") / "runs")
            self.assertTrue((run_folder / "snapshot.json").exists())
            self.assertTrue((run_folder / "report.txt").exists())
            self.assertTrue((run_folder / "report.json").exists())
            self.assertTrue((run_folder / "manifest.json").exists())

            index_path = Path(".semantic-test") / "index.json"
            self.assertTrue(index_path.exists())
            index_obj = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(index_obj["schema_version"], "1")
            self.assertGreaterEqual(len(index_obj["models"]), 1)

    def test_diff_creates_run_files_and_prints_sections(self) -> None:
        with self.runner.isolated_filesystem():
            before_root = _write_model(Path("before"), "ModelA", "1")
            after_root = _write_model(Path("after"), "ModelA", "2")

            text_result = self.runner.invoke(
                app,
                ["diff", str(before_root), str(after_root), "--format", "text", "--outdir", ".semantic-test"],
            )
            self.assertEqual(text_result.exit_code, 0, msg=text_result.stdout)
            self.assertIn("Diff Report", text_result.stdout)
            self.assertIn("Changed Objects", text_result.stdout)
            self.assertIn("Coverage", text_result.stdout)
            run_folder_text = _latest_run_folder(Path(".semantic-test") / "runs")
            self.assertTrue((run_folder_text / "snapshot.json").exists())
            self.assertTrue((run_folder_text / "report.txt").exists())
            self.assertTrue((run_folder_text / "report.json").exists())
            self.assertTrue((run_folder_text / "diff_report.txt").exists())
            self.assertTrue((run_folder_text / "manifest.json").exists())

            json_result = self.runner.invoke(
                app,
                ["diff", str(before_root), str(after_root), "--format", "json", "--outdir", ".semantic-test"],
            )
            self.assertEqual(json_result.exit_code, 0, msg=json_result.stdout)
            payload = json.loads(json_result.stdout)
            self.assertEqual(payload["schema_version"], 1)
            self.assertIn("changes", payload)
            self.assertIn("exposure", payload)
            run_folder_json = _latest_run_folder(Path(".semantic-test") / "runs")
            self.assertTrue((run_folder_json / "snapshot.json").exists())
            self.assertTrue((run_folder_json / "report.txt").exists())
            self.assertTrue((run_folder_json / "report.json").exists())
            self.assertTrue((run_folder_json / "diff_report.json").exists())
            self.assertTrue((run_folder_json / "manifest.json").exists())

    def test_exposure_creates_run_files_and_prints_sections(self) -> None:
        with self.runner.isolated_filesystem():
            before_root = _write_model(Path("before"), "ModelA", "1")
            after_root = _write_model(Path("after"), "ModelA", "2")

            result = self.runner.invoke(
                app,
                ["exposure", str(before_root), str(after_root), "--outdir", ".semantic-test"],
            )
            self.assertEqual(result.exit_code, 0, msg=result.stdout)
            self.assertIn("semantic-test Exposure Report", result.stdout)
            self.assertIn("Detected Changes", result.stdout)
            self.assertIn("Coverage Summary", result.stdout)
            self.assertIn("Unknown Patterns", result.stdout)
            self.assertIn("Unresolved Refs", result.stdout)

            run_folder = _latest_run_folder(Path(".semantic-test") / "runs")
            self.assertTrue((run_folder / "snapshot.json").exists())
            self.assertTrue((run_folder / "report.txt").exists())
            self.assertTrue((run_folder / "report.json").exists())
            self.assertTrue((run_folder / "manifest.json").exists())

    def test_strict_mode_exit_codes(self) -> None:
        with self.runner.isolated_filesystem():
            # (a) scan --strict on fixture with unresolved refs → exit 2
            policy_fail_model = _write_model(Path("broken"), "ModelA", "[MissingMeasure]")
            strict_fail = self.runner.invoke(
                app,
                ["scan", str(policy_fail_model), "--strict"],
            )
            self.assertEqual(strict_fail.exit_code, 2, msg=strict_fail.stdout)

            # (b) scan --strict on clean fixture → exit 0
            clean_model = _write_model(Path("clean"), "ModelA", "1")
            strict_clean = self.runner.invoke(
                app,
                ["scan", str(clean_model), "--strict"],
            )
            self.assertEqual(strict_clean.exit_code, 0, msg=strict_clean.stdout)

            # (c) scan on non-existent path → exit 1
            runtime_error = self.runner.invoke(app, ["scan", "does-not-exist"])
            self.assertEqual(runtime_error.exit_code, 1, msg=runtime_error.stdout)

    def test_strict_mode_exit_codes_for_diff_and_exposure(self) -> None:
        """Diff and exposure commands must also exit with code 2 in strict mode
        when the after-model has structural issues (unresolved refs)."""
        with self.runner.isolated_filesystem():
            clean_model = _write_model(Path("clean"), "ModelA", "1")
            broken_model = _write_model(Path("broken"), "ModelA", "[MissingMeasure]")

            # diff --strict on before=clean, after=broken → exit 2
            diff_strict = self.runner.invoke(
                app,
                ["diff", str(clean_model), str(broken_model), "--strict"],
            )
            self.assertEqual(diff_strict.exit_code, 2, msg=diff_strict.stdout)

            # diff --strict on two clean models → exit 0
            clean_model_b = _write_model(Path("clean_b"), "ModelA", "2")
            diff_clean = self.runner.invoke(
                app,
                ["diff", str(clean_model), str(clean_model_b), "--strict"],
            )
            self.assertEqual(diff_clean.exit_code, 0, msg=diff_clean.stdout)

            # exposure --strict on before=clean, after=broken → exit 2
            exposure_strict = self.runner.invoke(
                app,
                ["exposure", str(clean_model), str(broken_model), "--strict"],
            )
            self.assertEqual(exposure_strict.exit_code, 2, msg=exposure_strict.stdout)


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
