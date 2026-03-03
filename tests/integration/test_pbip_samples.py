"""Integration coverage for realistic pbip_samples fixtures."""

from __future__ import annotations

import unittest
from pathlib import Path

from semantic_test.cli.commands._pipeline import build_model_artifacts


class PbipSamplesIntegrationTests(unittest.TestCase):
    def test_all_pbip_samples_are_covered(self) -> None:
        samples_root = Path(__file__).resolve().parents[1] / "fixtures" / "pbip_samples"
        self.assertTrue(samples_root.exists(), f"Missing fixture root: {samples_root}")

        fixture_dirs = {
            path.name for path in samples_root.iterdir() if path.is_dir()
        }
        expected = {"simple_model", "var_calculate", "calc_group", "field_parameter", "full_model"}
        self.assertEqual(fixture_dirs, expected)

        self._assert_simple_model(samples_root / "simple_model")
        self._assert_var_calculate(samples_root / "var_calculate")
        self._assert_calc_group(samples_root / "calc_group")
        self._assert_field_parameter(samples_root / "field_parameter")
        self._assert_full_model(samples_root / "full_model")

    def _assert_simple_model(self, fixture_root: Path) -> None:
        artifacts = build_model_artifacts(str(fixture_root))
        self.assertEqual(len(artifacts.table_inventory), 2)
        self.assertEqual(len(artifacts.measure_inventory), 2)

    def _assert_var_calculate(self, fixture_root: Path) -> None:
        artifacts = build_model_artifacts(str(fixture_root))
        measure_id = "Measure:Metrics.Var Calc KPI"
        self.assertIn(measure_id, artifacts.measure_inventory)
        dependencies = artifacts.measure_inventory[measure_id]["dependencies"]
        self.assertIn("Measure:Metrics.Base", dependencies)
        self.assertIn("Column:Metrics.Amount", dependencies)
        self.assertIn("Column:Metrics.Qty", dependencies)

    def _assert_calc_group(self, fixture_root: Path) -> None:
        artifacts = build_model_artifacts(str(fixture_root))
        self.assertIn("CalcGroup:Time Calc", artifacts.calc_group_inventory)
        self.assertIn("CalcItem:Time Calc.YTD", artifacts.calc_group_inventory)
        calc_item = artifacts.calc_group_inventory["CalcItem:Time Calc.YTD"]
        self.assertIn("Measure:Metrics.Base Measure", calc_item["dependencies"])

    def _assert_field_parameter(self, fixture_root: Path) -> None:
        artifacts = build_model_artifacts(str(fixture_root))
        field_param_id = "FieldParam:Selector Parameter"
        self.assertIn(field_param_id, artifacts.field_param_inventory)
        dependencies = artifacts.field_param_inventory[field_param_id]["dependencies"]
        self.assertIn("Measure:Metrics.Sales Amount", dependencies)

    def _assert_full_model(self, fixture_root: Path) -> None:
        artifacts = build_model_artifacts(str(fixture_root))
        # Tables
        self.assertIn("Table:Sales", artifacts.table_inventory)
        self.assertIn("Table:Date", artifacts.table_inventory)
        # Measures with cross-measure dependencies
        self.assertIn("Measure:Sales.Total Sales", artifacts.measure_inventory)
        self.assertIn("Measure:Sales.Sales YoY", artifacts.measure_inventory)
        self.assertIn("Measure:Sales.Running Total", artifacts.measure_inventory)
        # Relationship with properties
        rel_key = "Rel:Sales.DateKey->Date.DateKey"
        self.assertIn(rel_key, artifacts.relationship_inventory)
        rel = artifacts.relationship_inventory[rel_key]
        self.assertEqual(rel["cardinality"], "manyToOne")
        self.assertEqual(rel["cross_filter_direction"], "singleDirection")
        self.assertTrue(rel["is_active"])
        # Calc group with SELECTEDMEASURE()
        self.assertIn("CalcGroup:Time Calc", artifacts.calc_group_inventory)
        self.assertIn("CalcItem:Time Calc.YTD", artifacts.calc_group_inventory)
        # Field parameter
        self.assertIn("FieldParam:Selector Parameter", artifacts.field_param_inventory)
        # SELECTEDMEASURE() emitted as unsupported pattern
        pattern_objs = {e["object_id"] for e in artifacts.unknown_patterns}
        self.assertIn("CalcItem:Time Calc.YTD", pattern_objs)


if __name__ == "__main__":
    unittest.main()
