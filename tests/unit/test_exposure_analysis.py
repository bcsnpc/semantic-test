"""Unit tests for exposure analysis engine."""

from __future__ import annotations

import unittest

from semantic_test.core.analysis.exposure import analyze_exposure
from semantic_test.core.diff.differ import DiffResult
from semantic_test.core.graph.builder import build_dependency_graph
from semantic_test.core.model.coverage import coverage_report
from semantic_test.core.report.schemas import build_report_schema_v1


class ExposureAnalysisTests(unittest.TestCase):
    def test_exposure_matches_expected_fixture(self) -> None:
        objects = {
            "Column:Sales.Amount": {
                "type": "Column",
                "name": "Amount",
                "dependencies": set(),
            },
            "Measure:Sales.Base": {
                "type": "Measure",
                "name": "Base",
                "dependencies": {"Column:Sales.Amount"},
            },
            "Measure:Sales.Total": {
                "type": "Measure",
                "name": "Total",
                "dependencies": {"Measure:Sales.Base"},
            },
            "Measure:Sales.Alt": {
                "type": "Measure",
                "name": "Alt",
                "dependencies": {"Column:Sales.Amount"},
            },
        }
        graph = build_dependency_graph(objects)
        diff = DiffResult(
            changes=[],
            added_object_ids=[],
            removed_object_ids=[],
            modified_object_ids=["Column:Sales.Amount"],
        )

        result = analyze_exposure(diff, graph, top_n=2)

        self.assertEqual(len(result.items), 1)
        item = result.items[0]
        self.assertEqual(item.changed_object_id, "Column:Sales.Amount")
        self.assertEqual(
            item.downstream_ids,
            {"Measure:Sales.Base", "Measure:Sales.Total", "Measure:Sales.Alt"},
        )
        self.assertEqual(item.downstream_by_type_counts, {"Measure": 3})
        self.assertEqual(
            [obj.object_id for obj in item.top_downstream_objects],
            ["Measure:Sales.Alt", "Measure:Sales.Base"],
        )

    def test_base_measure_change_exposes_derived_measures(self) -> None:
        objects = {
            "Measure:Metrics.Base": {
                "type": "Measure",
                "name": "Base",
                "dependencies": set(),
            },
            "Measure:Metrics.DerivedA": {
                "type": "Measure",
                "name": "DerivedA",
                "dependencies": {"Measure:Metrics.Base"},
            },
            "Measure:Metrics.DerivedB": {
                "type": "Measure",
                "name": "DerivedB",
                "dependencies": {"Measure:Metrics.DerivedA"},
            },
            "Column:Metrics.Flag": {
                "type": "Column",
                "name": "Flag",
                "dependencies": set(),
            },
        }
        graph = build_dependency_graph(objects)
        diff = DiffResult(
            changes=[],
            added_object_ids=[],
            removed_object_ids=[],
            modified_object_ids=["Measure:Metrics.Base"],
        )

        result = analyze_exposure(diff, graph, top_n=10)

        self.assertEqual(len(result.items), 1)
        item = result.items[0]
        self.assertEqual(item.changed_object_id, "Measure:Metrics.Base")
        self.assertEqual(
            item.downstream_ids,
            {"Measure:Metrics.DerivedA", "Measure:Metrics.DerivedB"},
        )
        self.assertEqual(item.downstream_by_type_counts, {"Measure": 2})
        self.assertEqual(
            [obj.object_id for obj in item.top_downstream_objects],
            ["Measure:Metrics.DerivedA", "Measure:Metrics.DerivedB"],
        )

    def test_blast_radius_names_all_downstream_objects_in_output(self) -> None:
        """ExposureEntryV1.downstream_ids must contain every downstream object ID
        with no truncation, even when there are more than top_n objects."""
        # Build 15 downstream measures: Base -> D1 -> D2 -> ... -> D14
        objects: dict = {
            "Measure:Sales.Base": {
                "type": "Measure",
                "name": "Base",
                "dependencies": set(),
            }
        }
        prev = "Measure:Sales.Base"
        for i in range(1, 15):
            mid = f"Measure:Sales.D{i}"
            objects[mid] = {
                "type": "Measure",
                "name": f"D{i}",
                "dependencies": {prev},
            }
            prev = mid

        graph = build_dependency_graph(objects)
        diff = DiffResult(
            changes=[],
            added_object_ids=[],
            removed_object_ids=[],
            modified_object_ids=["Measure:Sales.Base"],
        )

        # Use top_n=3 to confirm downstream_ids is NOT capped by top_n
        exposure_result = analyze_exposure(diff, graph, top_n=3)

        _cov_lines, cov_data = coverage_report()
        report = build_report_schema_v1(
            diff_result=diff,
            exposure_result=exposure_result,
            coverage_data=cov_data,
        )

        self.assertEqual(len(report.exposure), 1)
        entry = report.exposure[0]

        # downstream_ids must contain ALL 14 downstream measures (D1..D14)
        self.assertEqual(entry.downstream_count, 14)
        self.assertEqual(len(entry.downstream_ids), 14)
        for i in range(1, 15):
            self.assertIn(f"Measure:Sales.D{i}", entry.downstream_ids)

        # downstream_ids must be sorted
        self.assertEqual(entry.downstream_ids, sorted(entry.downstream_ids))

        # top_downstream_items is still capped at top_n=3 (backwards compat)
        self.assertEqual(len(entry.top_downstream_items), 3)


if __name__ == "__main__":
    unittest.main()
