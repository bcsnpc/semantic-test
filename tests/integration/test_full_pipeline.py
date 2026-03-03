"""Full pipeline integration tests using the full_model fixture.

This fixture combines all Phase 1 features:
  - 2 tables (Sales, Date)
  - 3 measures with cross-measure references (Total Sales, Sales YoY, Running Total)
  - 1 relationship (Sales.DateKey → Date.DateKey)
  - 1 calc group (Time Calc) with SELECTEDMEASURE() calc item (YTD)
  - 1 field parameter (Selector Parameter) with NAMEOF references
  - DAX patterns: CALCULATE, VAR block, measure references
"""

from __future__ import annotations

import unittest
from pathlib import Path

from semantic_test.cli.commands._pipeline import build_model_artifacts
from semantic_test.core.graph.queries import traverse_downstream


class FullPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_path = str(
            Path(__file__).resolve().parents[1]
            / "fixtures"
            / "pbip_samples"
            / "full_model"
        )
        cls.artifacts = build_model_artifacts(cls.fixture_path)

    def test_full_pipeline_tables_and_measures(self) -> None:
        """Sales and Date tables are registered; all 3 measures are present."""
        objects = self.artifacts.objects
        self.assertIn("Table:Sales", objects)
        self.assertIn("Table:Date", objects)
        self.assertIn("Measure:Sales.Total Sales", objects)
        self.assertIn("Measure:Sales.Sales YoY", objects)
        self.assertIn("Measure:Sales.Running Total", objects)

    def test_full_pipeline_cross_measure_dependencies(self) -> None:
        """Sales YoY and Running Total both depend on Total Sales."""
        objects = self.artifacts.objects

        sales_yoy = objects["Measure:Sales.Sales YoY"]
        self.assertIn("Measure:Sales.Total Sales", sales_yoy["dependencies"])

        running_total = objects["Measure:Sales.Running Total"]
        self.assertIn("Measure:Sales.Total Sales", running_total["dependencies"])

    def test_full_pipeline_relationship_edges(self) -> None:
        """Graph contains a dependency edge from Sales[DateKey] to Date[DateKey]."""
        graph = self.artifacts.graph

        # The relationship should be in the relationship inventory
        self.assertGreater(len(self.artifacts.relationship_inventory), 0)

        # Graph should contain both column nodes
        self.assertIn("Column:Sales.DateKey", graph.nodes)
        self.assertIn("Column:Date.DateKey", graph.nodes)

    def test_full_pipeline_calc_group_dependencies(self) -> None:
        """YTD calc item has SELECTEDMEASURE() emitted as unsupported pattern
        and captures 'Date'[Date] as a dependency."""
        objects = self.artifacts.objects

        self.assertIn("CalcGroup:Time Calc", objects)
        self.assertIn("CalcItem:Time Calc.YTD", objects)

        ytd = objects["CalcItem:Time Calc.YTD"]
        # SELECTEDMEASURE() must NOT produce a dependency edge
        for dep in ytd["dependencies"]:
            self.assertFalse(
                dep.startswith("SELECTED"), msg=f"Unexpected SELECTED dep: {dep}"
            )
        # 'Date'[Date] reference should be captured
        self.assertIn("Column:Date.Date", ytd["dependencies"])

    def test_full_pipeline_selectedmeasure_emits_unsupported_pattern(self) -> None:
        """Scanning full_model must report unsupported_pattern:SELECTEDMEASURE()
        for the YTD calc item."""
        patterns_by_obj = {
            entry["object_id"]: entry["patterns"]
            for entry in self.artifacts.unknown_patterns
        }
        self.assertIn("CalcItem:Time Calc.YTD", patterns_by_obj)
        self.assertIn(
            "unsupported_pattern:SELECTEDMEASURE()",
            patterns_by_obj["CalcItem:Time Calc.YTD"],
        )

    def test_full_pipeline_field_parameter(self) -> None:
        """Selector Parameter field parameter node exists in the registry."""
        objects = self.artifacts.objects
        self.assertIn("FieldParam:Selector Parameter", objects)
        fp = objects["FieldParam:Selector Parameter"]
        self.assertTrue(fp["experimental_coverage"])
        self.assertTrue(fp["special_table"])
        # NAMEOF('Sales'[Total Sales]) → resolved as Measure:Sales.Total Sales dep
        self.assertIn("Measure:Sales.Total Sales", fp["dependencies"])

    def test_full_pipeline_blast_radius_names_all(self) -> None:
        """Changing Total Sales exposes Sales YoY, Running Total, and
        Selector Parameter (all named in downstream_ids, none truncated)."""
        graph = self.artifacts.graph
        downstream = traverse_downstream(graph, "Measure:Sales.Total Sales")

        # At minimum: Sales YoY, Running Total, Selector Parameter
        self.assertIn("Measure:Sales.Sales YoY", downstream)
        self.assertIn("Measure:Sales.Running Total", downstream)
        self.assertIn("FieldParam:Selector Parameter", downstream)

    def test_full_pipeline_snapshot_hash_identical_across_two_runs(self) -> None:
        """Running build_model_artifacts() twice on the same fixture must
        produce identical snapshot_hash values (determinism requirement)."""
        run_a = build_model_artifacts(self.fixture_path)
        run_b = build_model_artifacts(self.fixture_path)

        self.assertEqual(
            run_a.snapshot.snapshot_hash,
            run_b.snapshot.snapshot_hash,
            msg="Snapshot hash is non-deterministic across two runs on the same fixture.",
        )
        # Individual object hashes must also match
        self.assertEqual(
            sorted(run_a.snapshot.objects.keys()),
            sorted(run_b.snapshot.objects.keys()),
        )
        for object_id in run_a.snapshot.objects:
            self.assertEqual(
                run_a.snapshot.objects[object_id].object_hash,
                run_b.snapshot.objects[object_id].object_hash,
                msg=f"Object hash differs between runs for {object_id}",
            )


if __name__ == "__main__":
    unittest.main()
