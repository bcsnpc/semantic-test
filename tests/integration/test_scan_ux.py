"""Integration tests for Phase-1 scan UX/report contracts."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch
from pathlib import Path

from typer.testing import CliRunner

from semantic_test.cli.main import app


class ScanUxIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_scan_output_order_and_no_coverage_matrix_without_debug(self) -> None:
        with self.runner.isolated_filesystem():
            model_root = _write_model_with_unresolved(Path("."), "ModelA")
            result = self.runner.invoke(app, ["scan", str(model_root)])
            self.assertEqual(result.exit_code, 0, msg=result.stdout)

            run_folder = _latest_run_folder(Path(".semantic-test") / "runs")
            report_text = (run_folder / "report.txt").read_text(encoding="utf-8")

            self.assertTrue(report_text.startswith("semantic-test Scan Report"))
            self.assertLess(report_text.find("Status:"), report_text.find("Issues"))
            self.assertLess(report_text.find("Issues"), report_text.find("Top Dependency Hubs"))
            self.assertLess(report_text.find("Top Dependency Hubs"), report_text.find("Next Actions"))
            self.assertNotIn("Coverage Matrix", report_text)

    def test_truncation_and_show_all(self) -> None:
        with self.runner.isolated_filesystem():
            model_root = _write_model_many_unresolved(Path("."), "ModelB", count=12)

            default_result = self.runner.invoke(app, ["scan", str(model_root)])
            self.assertEqual(default_result.exit_code, 0, msg=default_result.stdout)
            run_default = _latest_run_folder(Path(".semantic-test") / "runs")
            default_text = (run_default / "report.txt").read_text(encoding="utf-8")
            self.assertIn("(+2 more; re-run with --show-all)", default_text)

            show_all_result = self.runner.invoke(app, ["scan", str(model_root), "--show-all"])
            self.assertEqual(show_all_result.exit_code, 0, msg=show_all_result.stdout)
            run_all = _latest_run_folder(Path(".semantic-test") / "runs")
            show_all_text = (run_all / "report.txt").read_text(encoding="utf-8")
            self.assertNotIn("(+2 more; re-run with --show-all)", show_all_text)

    def test_strict_exit_codes(self) -> None:
        with self.runner.isolated_filesystem():
            issue_model = _write_model_with_unresolved(Path("."), "IssueModel")
            clean_model = _write_model_clean(Path("."), "CleanModel")

            non_strict_issue = self.runner.invoke(app, ["scan", str(issue_model)])
            self.assertEqual(non_strict_issue.exit_code, 0, msg=non_strict_issue.stdout)

            strict_issue = self.runner.invoke(app, ["scan", str(issue_model), "--strict"])
            self.assertEqual(strict_issue.exit_code, 2, msg=strict_issue.stdout)

            strict_clean = self.runner.invoke(app, ["scan", str(clean_model), "--strict"])
            self.assertEqual(strict_clean.exit_code, 0, msg=strict_clean.stdout)

            runtime_error = self.runner.invoke(app, ["scan", "does-not-exist"])
            self.assertEqual(runtime_error.exit_code, 1, msg=runtime_error.stdout)

    def test_json_schema_alignment(self) -> None:
        with self.runner.isolated_filesystem():
            model_root = _write_model_with_unresolved(Path("."), "JsonModel")
            result = self.runner.invoke(app, ["scan", str(model_root), "--stdout", "none"])
            self.assertEqual(result.exit_code, 0, msg=result.stdout)

            run_folder = _latest_run_folder(Path(".semantic-test") / "runs")
            payload = json.loads((run_folder / "report.json").read_text(encoding="utf-8"))

            self.assertIn("status", payload)
            self.assertIn("summary", payload)
            self.assertIn("issues", payload)
            self.assertIn("unresolved_references", payload["issues"])
            self.assertIn("unsupported_reference_patterns", payload["issues"])
            self.assertIn("top_dependency_hubs", payload)

            unresolved_targets = {
                item["target"]
                for group in payload["issues"]["unresolved_references"]
                for item in group.get("items", [])
            }
            unsupported_targets = {
                item["target"]
                for group in payload["issues"]["unsupported_reference_patterns"]
                for item in group.get("items", [])
            }
            self.assertTrue(unresolved_targets.isdisjoint(unsupported_targets))
            self.assertEqual(payload["scan_input_path"], str(model_root))
            self.assertIn("selected_model_definition_path", payload)
            self.assertIn("models_detected_count", payload)
            unresolved_items = [
                item
                for group in payload["issues"]["unresolved_references"]
                for item in group.get("items", [])
            ]
            self.assertTrue(any("did_you_mean" in item for item in unresolved_items))

    def test_debug_mode_includes_coverage_matrix(self) -> None:
        with self.runner.isolated_filesystem():
            model_root = _write_model_with_unresolved(Path("."), "DebugModel")
            result = self.runner.invoke(app, ["scan", str(model_root), "--debug"])
            self.assertEqual(result.exit_code, 0, msg=result.stdout)

            run_folder = _latest_run_folder(Path(".semantic-test") / "runs")
            report_text = (run_folder / "report.txt").read_text(encoding="utf-8")
            report_json = json.loads((run_folder / "report.json").read_text(encoding="utf-8"))

            self.assertIn("Coverage Matrix", report_text)
            self.assertIn("debug", report_json)
            self.assertIn("coverage_matrix", report_json["debug"])
            self.assertIn("resolution_traces", report_json["debug"])

    def test_multi_model_next_actions_uses_explicit_model_path(self) -> None:
        with self.runner.isolated_filesystem():
            root = Path(".")
            model_a = _write_model_with_unresolved(root / "A", "ModelA")
            _write_model_clean(root / "B", "ModelB")

            result = self.runner.invoke(app, ["scan", str(model_a)])
            self.assertEqual(result.exit_code, 0, msg=result.stdout)

            run_folder = _latest_run_folder(Path("A") / ".semantic-test" / "runs")
            report_text = (run_folder / "report.txt").read_text(encoding="utf-8")
            definition_path = (model_a / "definition").resolve()

            self.assertIn(
                f'python -m semantic_test.cli.main scan "{definition_path}" --strict',
                report_text,
            )
            self.assertNotIn("semantic-test scan . --strict", report_text)
            self.assertIn(f'"{definition_path}"', report_text)

    def test_multi_model_root_error_shows_specific_model_rerun_hint(self) -> None:
        with self.runner.isolated_filesystem():
            _write_model_clean(Path("A"), "ModelA")
            _write_model_clean(Path("B"), "ModelB")

            result = self.runner.invoke(app, ["scan", "."])
            self.assertEqual(result.exit_code, 1, msg=result.stdout)
            self.assertIn("Multiple definition folders found", result.stdout)

            run_folder = _latest_run_folder(Path(".semantic-test") / "runs")
            report_text = (run_folder / "report.txt").read_text(encoding="utf-8")
            self.assertIn("Next Actions", report_text)
            self.assertIn("python -m semantic_test.cli.main scan", report_text)
            self.assertNotIn("semantic-test scan . --strict", report_text)

    def test_next_actions_includes_cli_install_hint_when_semantic_test_missing(self) -> None:
        with self.runner.isolated_filesystem():
            model_root = _write_model_with_unresolved(Path("."), "ModelA")
            with patch("semantic_test.cli.commands.scan.shutil.which", return_value=None):
                result = self.runner.invoke(app, ["scan", str(model_root)])
            self.assertEqual(result.exit_code, 0, msg=result.stdout)

            run_folder = _latest_run_folder(Path(".semantic-test") / "runs")
            report_text = (run_folder / "report.txt").read_text(encoding="utf-8")
            self.assertIn("Install CLI entrypoint (dev): pip install -e .", report_text)


def _write_model_clean(base: Path, model_name: str) -> Path:
    model_root = base / f"{model_name}.SemanticModel"
    definition = model_root / "definition"
    definition.mkdir(parents=True, exist_ok=True)
    (definition / "model.tmdl").write_text(
        "\n".join(
            [
                "table Metrics",
                "\tcolumn Amount",
                "\tmeasure KPI = SUM(Metrics[Amount])",
            ]
        ),
        encoding="utf-8",
    )
    return model_root


def _write_model_with_unresolved(base: Path, model_name: str) -> Path:
    model_root = base / f"{model_name}.SemanticModel"
    definition = model_root / "definition"
    definition.mkdir(parents=True, exist_ok=True)
    (definition / "model.tmdl").write_text(
        "\n".join(
            [
                "table Metrics",
                "\tcolumn Amount",
                "\tmeasure KPI = [MissingMeasure] + SUM(Metrics[Amount])",
            ]
        ),
        encoding="utf-8",
    )
    return model_root


def _write_model_many_unresolved(base: Path, model_name: str, count: int) -> Path:
    model_root = base / f"{model_name}.SemanticModel"
    definition = model_root / "definition"
    definition.mkdir(parents=True, exist_ok=True)
    lines = ["table Metrics", "\tcolumn Amount"]
    for idx in range(1, count + 1):
        lines.append(f"\tmeasure KPI {idx} = [Missing {idx}] + SUM(Metrics[Amount])")
    (definition / "model.tmdl").write_text("\n".join(lines), encoding="utf-8")
    return model_root


def _latest_run_folder(runs_root: Path) -> Path:
    run_folders = sorted([path for path in runs_root.iterdir() if path.is_dir()])
    if not run_folders:
        raise AssertionError(f"No run folders found under {runs_root}")
    return run_folders[-1]


if __name__ == "__main__":
    unittest.main()
