"""Golden tests for unresolved-reference scan UX output."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from typer.testing import CliRunner

from semantic_test.cli.main import app


class ScanUnresolvedGoldenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.repo_root = Path(__file__).resolve().parents[2]
        self.golden_root = self.repo_root / "tests" / "fixtures" / "golden" / "scan_unresolved_v2"

    def test_console_includes_expected_fields_and_ranked_suggestions(self) -> None:
        with self.runner.isolated_filesystem():
            model_root = _write_model_missing_measure(Path("."), "ModelA")
            result = self.runner.invoke(app, ["scan", str(model_root)])
            self.assertEqual(result.exit_code, 0, msg=result.stdout)

            run_folder = _latest_run_folder(Path(".semantic-test") / "runs")
            report_text = (run_folder / "report.txt").read_text(encoding="utf-8")
            extracted = _extract_lines(
                report_text,
                [
                    "expected_type:",
                    "action:",
                    "why_best_guess:",
                    "referrers_count:",
                    "did_you_mean_top3:",
                    "likely_cause:",
                ],
            )
            expected = (self.golden_root / "expected_fields_and_scores.txt").read_text(encoding="utf-8")
            self.assertEqual(extracted, expected)

    def test_console_includes_suggested_fix_options(self) -> None:
        with self.runner.isolated_filesystem():
            model_root = _write_model_two_missing_refs(Path("."), "ModelB")
            result = self.runner.invoke(app, ["scan", str(model_root)])
            self.assertEqual(result.exit_code, 0, msg=result.stdout)

            run_folder = _latest_run_folder(Path(".semantic-test") / "runs")
            report_text = (run_folder / "report.txt").read_text(encoding="utf-8")
            extracted = _extract_lines(
                report_text,
                [
                    "Suggested fix (option 1, score",
                    "Suggested fix (option 2, score",
                ],
            )
            expected = (self.golden_root / "expected_fixit_options.txt").read_text(encoding="utf-8")
            self.assertEqual(extracted, expected)


def _extract_lines(text: str, prefixes: list[str]) -> str:
    rows: list[str] = []
    for line in text.splitlines():
        clean = line.strip()
        if any(prefix in clean for prefix in prefixes):
            # Normalize score numbers to keep deterministic across minor ranking changes.
            clean = re.sub(r"\(\d+\)", "(<SCORE>)", clean)
            rows.append(clean)
    return "\n".join(rows) + "\n"


def _write_model_missing_measure(base: Path, model_name: str) -> Path:
    model_root = base / f"{model_name}.SemanticModel"
    definition = model_root / "definition"
    definition.mkdir(parents=True, exist_ok=True)
    (definition / "model.tmdl").write_text(
        "\n".join(
            [
                "table Metrics",
                "\tmeasure Feedback Rating Measure1 = 1",
                "\tmeasure KPI = [Feedback Rating Measure]",
            ]
        ),
        encoding="utf-8",
    )
    return model_root


def _write_model_two_missing_refs(base: Path, model_name: str) -> Path:
    model_root = base / f"{model_name}.SemanticModel"
    definition = model_root / "definition"
    definition.mkdir(parents=True, exist_ok=True)
    (definition / "model.tmdl").write_text(
        "\n".join(
            [
                "table Metrics",
                "\tmeasure Feedback Rating Measure1 = 1",
                "\tmeasure Timeto resolve sum1 = 2",
                "\tmeasure KPI = DIVIDE([Feedback Rating Measure], [Timeto resolve sum])",
            ]
        ),
        encoding="utf-8",
    )
    return model_root


def _latest_run_folder(runs_root: Path) -> Path:
    run_folders = sorted([path for path in runs_root.iterdir() if path.is_dir()])
    if not run_folders:
        raise AssertionError(f"No run folders found under {runs_root}")
    return run_folders[-1]


if __name__ == "__main__":
    unittest.main()
