"""Integration tests for trace command."""

from __future__ import annotations

import unittest
from pathlib import Path

from typer.testing import CliRunner

from semantic_test.cli.main import app


class TraceCommandIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_trace_returns_upstream_and_downstream(self) -> None:
        with self.runner.isolated_filesystem():
            model_root = _write_model(Path("."), "ModelA")
            _write_report_with_measure_visual(Path("."), "ModelA")
            seed = self.runner.invoke(app, ["scan", str(model_root), "--stdout", "none"])
            self.assertEqual(seed.exit_code, 0, msg=seed.stdout)

            result = self.runner.invoke(
                app,
                ["trace", "Measure:Metrics.Executive KPI", str(model_root), "--depth", "5"],
            )
            self.assertEqual(result.exit_code, 0, msg=result.stdout)
            self.assertIn("Object: Measure:Metrics.Executive KPI", result.stdout)
            self.assertIn("Upstream:", result.stdout)
            self.assertIn("Downstream:", result.stdout)
            self.assertIn("Downstream Visual Dependencies:", result.stdout)
            self.assertIn("Measure:Metrics.Base KPI", result.stdout)
            self.assertIn("Page: Executive Summary", result.stdout)
            self.assertIn("Visual: Revenue KPI", result.stdout)
            self.assertIn("Type: card", result.stdout)
            self.assertIn("Role: Values", result.stdout)
            self.assertNotIn("Upstream Visual Dependencies:", result.stdout)

            run_folder = _latest_run_folder(Path(".semantic-test") / "runs")
            self.assertTrue((run_folder / "snapshot.json").exists())
            self.assertTrue((run_folder / "report.txt").exists())
            self.assertTrue((run_folder / "report.json").exists())
            self.assertTrue((run_folder / "manifest.json").exists())

    def test_trace_handles_missing_previous_snapshot(self) -> None:
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(app, ["trace", "Measure:Metrics.KPI"])
            self.assertEqual(result.exit_code, 0, msg=result.stdout)
            self.assertIn("No previous run found for this model. Run scan first.", result.stdout)

    def test_trace_export_mmd_writes_mermaid_graph_file(self) -> None:
        with self.runner.isolated_filesystem():
            model_root = _write_model(Path("."), "ModelA")
            _write_report_with_measure_visual(Path("."), "ModelA")
            seed = self.runner.invoke(app, ["scan", str(model_root), "--stdout", "none"])
            self.assertEqual(seed.exit_code, 0, msg=seed.stdout)

            result = self.runner.invoke(
                app,
                [
                    "trace",
                    "Measure:Metrics.Executive KPI",
                    str(model_root),
                    "--depth",
                    "5",
                    "--export",
                    "mmd",
                ],
            )
            self.assertEqual(result.exit_code, 0, msg=result.stdout)

            run_folder = _latest_run_folder(Path(".semantic-test") / "runs")
            mmd_path = run_folder / "trace_graph.mmd"
            self.assertTrue(mmd_path.exists())
            mmd_text = mmd_path.read_text(encoding="utf-8")
            self.assertIn("graph LR", mmd_text)
            self.assertIn("Measure_Metrics_BaseKPI --> Measure_Metrics_ExecutiveKPI", mmd_text)
            self.assertIn("Measure_Metrics_ExecutiveKPI --> Visual_ExecutiveSummary_visual_1abcd", mmd_text)

    def test_trace_export_mmd_simple_writes_mermaid_graph_file(self) -> None:
        with self.runner.isolated_filesystem():
            model_root = _write_model(Path("."), "ModelA")
            _write_report_with_measure_visual(Path("."), "ModelA")
            seed = self.runner.invoke(app, ["scan", str(model_root), "--stdout", "none"])
            self.assertEqual(seed.exit_code, 0, msg=seed.stdout)

            result = self.runner.invoke(
                app,
                [
                    "trace",
                    "Measure:Metrics.Executive KPI",
                    str(model_root),
                    "--depth",
                    "5",
                    "--export",
                    "mmd-simple",
                ],
            )
            self.assertEqual(result.exit_code, 0, msg=result.stdout)

            run_folder = _latest_run_folder(Path(".semantic-test") / "runs")
            mmd_path = run_folder / "trace_graph.mmd"
            self.assertTrue(mmd_path.exists())
            mmd_text = mmd_path.read_text(encoding="utf-8")
            self.assertIn("graph LR", mmd_text)


def _write_model(base: Path, model_name: str) -> Path:
    definition = base / f"{model_name}.SemanticModel" / "definition"
    definition.mkdir(parents=True, exist_ok=True)
    (definition / "model.tmdl").write_text(
        "\n".join(
            [
                "table Metrics",
                "\tcolumn Amount",
                "\tmeasure Base KPI = SUM(Metrics[Amount])",
                "\tmeasure Executive KPI = [Base KPI] + 1",
            ]
        ),
        encoding="utf-8",
    )
    return base


def _write_report_with_measure_visual(base: Path, model_name: str) -> Path:
    report_root = base / f"{model_name}.Report" / "definition" / "pages" / "page_1" / "visuals" / "visual_1abcdef123456"
    report_root.mkdir(parents=True, exist_ok=True)
    page_json = report_root.parent.parent / "page.json"
    page_json.write_text(
        '\n'.join(
            [
                "{",
                '  "displayName": "Executive Summary",',
                '  "filterConfig": { "filters": [] }',
                "}",
            ]
        ),
        encoding="utf-8",
    )
    visual_json = report_root / "visual.json"
    visual_json.write_text(
        '\n'.join(
            [
                "{",
                '  "name": "Revenue KPI",',
                '  "visual": {',
                '    "visualType": "card",',
                '    "query": {',
                '      "queryState": {',
                '        "Values": {',
                '          "projections": [',
                "            {",
                '              "field": {',
                '                "Measure": {',
                '                  "Expression": { "SourceRef": { "Entity": "Metrics" } },',
                '                  "Property": "Executive KPI"',
                "                }",
                "              }",
                "            }",
                "          ]",
                "        }",
                "      }",
                "    },",
                '    "visualContainerObjects": {',
                '      "title": [',
                "        {",
                '          "properties": {',
                '            "text": { "expr": { "Literal": { "Value": "\'Revenue KPI\'" } } }',
                "          }",
                "        }",
                "      ]",
                "    }",
                "  }",
                "}",
            ]
        ),
        encoding="utf-8",
    )
    return base / f"{model_name}.Report"


def _latest_run_folder(runs_root: Path) -> Path:
    run_folders = sorted([path for path in runs_root.iterdir() if path.is_dir()])
    if not run_folders:
        raise AssertionError(f"No run folders found under {runs_root}")
    return run_folders[-1]


if __name__ == "__main__":
    unittest.main()
