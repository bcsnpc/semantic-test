"""Golden-file tests for report formatters."""

from __future__ import annotations

import unittest
from pathlib import Path

from semantic_test.core.analysis.exposure import analyze_exposure
from semantic_test.core.diff.differ import diff_snapshots
from semantic_test.core.diff.snapshot import build_snapshot
from semantic_test.core.graph.builder import build_dependency_graph
from semantic_test.core.model.coverage import coverage_report
from semantic_test.core.report.format_json import format_report_json
from semantic_test.core.report.format_text import format_pr_text


class ReportFormatterGoldenTests(unittest.TestCase):
    def test_text_output_matches_golden(self) -> None:
        (
            diff_result,
            exposure_result,
            coverage_lines,
            coverage_data,
            old_hash,
            new_hash,
        ) = _fixture_inputs()
        rendered = format_pr_text(
            diff_result=diff_result,
            exposure_result=exposure_result,
            run_id="20260302_214533_exposure_fixture_1234abcd",
            model_key="semanticmodel::fixtures/report_model/definition",
            old_snapshot_hash=old_hash,
            new_snapshot_hash=new_hash,
            coverage_lines=coverage_lines,
            coverage_data=coverage_data,
            unresolved_refs=[],
        )
        expected = _load_golden("report_text_v1.txt")
        self.assertEqual(rendered, expected)

    def test_json_output_matches_golden(self) -> None:
        (
            diff_result,
            exposure_result,
            _coverage_lines,
            coverage_data,
            old_hash,
            new_hash,
        ) = _fixture_inputs()
        rendered = format_report_json(
            diff_result=diff_result,
            exposure_result=exposure_result,
            coverage_data=coverage_data,
            run_id="20260302_214533_exposure_fixture_1234abcd",
            model_key="semanticmodel::fixtures/report_model/definition",
            old_snapshot_hash=old_hash,
            new_snapshot_hash=new_hash,
            unresolved_refs=[],
        )
        expected = _load_golden("report_json_v1.json")
        self.assertEqual(rendered, expected)


def _fixture_inputs():
    before_objects = {
        "Column:Sales.Amount": {"type": "Column", "name": "Amount", "dependencies": set()},
        "Measure:Sales.Base": {
            "type": "Measure",
            "name": "Base",
            "raw_expression": "SUM(Sales[Amount])",
            "dependencies": {"Column:Sales.Amount"},
        },
        "Measure:Sales.Total": {
            "type": "Measure",
            "name": "Total",
            "raw_expression": "[Base] + 1",
            "dependencies": {"Measure:Sales.Base"},
        },
    }
    after_objects = {
        "Column:Sales.Amount": {"type": "Column", "name": "Amount", "dependencies": set()},
        "Measure:Sales.Base": {
            "type": "Measure",
            "name": "Base",
            "raw_expression": "SUM(Sales[Amount]) + 0",
            "dependencies": {"Column:Sales.Amount"},
        },
        "Measure:Sales.Total": {
            "type": "Measure",
            "name": "Total",
            "raw_expression": "[Base] + 1",
            "dependencies": {"Measure:Sales.Base"},
        },
        "Measure:Sales.NewKpi": {
            "type": "Measure",
            "name": "NewKpi",
            "raw_expression": "[Base]",
            "dependencies": {"Measure:Sales.Base"},
        },
    }
    before_graph = build_dependency_graph(before_objects)
    after_graph = build_dependency_graph(after_objects)
    before_snapshot = build_snapshot(
        before_objects,
        before_graph,
        model_key="semanticmodel::fixtures/report_model/definition",
        definition_path="fixtures/report_model/definition",
    )
    after_snapshot = build_snapshot(
        after_objects,
        after_graph,
        model_key="semanticmodel::fixtures/report_model/definition",
        definition_path="fixtures/report_model/definition",
    )
    diff_result = diff_snapshots(before_snapshot, after_snapshot)
    exposure_result = analyze_exposure(diff_result, after_graph, top_n=3)
    coverage_lines, coverage_data = coverage_report()
    return (
        diff_result,
        exposure_result,
        coverage_lines,
        coverage_data,
        before_snapshot.snapshot_hash,
        after_snapshot.snapshot_hash,
    )


def _load_golden(filename: str) -> str:
    path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "golden" / filename
    )
    return path.read_text(encoding="utf-8").rstrip("\n")


if __name__ == "__main__":
    unittest.main()
