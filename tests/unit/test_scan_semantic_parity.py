from __future__ import annotations

import unittest
from types import SimpleNamespace

from semantic_test.cli.commands.scan import _compute_semantic_parity_diff


class ScanSemanticParityTests(unittest.TestCase):
    def test_compute_semantic_parity_diff_reports_object_and_edge_gaps(self) -> None:
        pbip_artifacts = SimpleNamespace(
            definition_folder="D:/repo/Model.SemanticModel/definition",
            objects={
                "Table:Sales": {"type": "Table"},
                "Column:Sales.Amount": {"type": "Column"},
                "Measure:Sales.Total": {"type": "Measure"},
                "CalcGroup:Time Intelligence": {"type": "CalcGroup"},
                "CalcItem:Time Intelligence.YTD": {"type": "CalcItem"},
            },
            diagnostics={
                "semantic_inventory": {
                    "object_type_counts": {"Table": 1, "Column": 1, "Measure": 1, "CalcGroup": 1, "CalcItem": 1},
                    "edge_category_counts": {"measure_to_column": 1, "calc_item_to_measure": 1},
                }
            },
            column_inventory={"Column:Sales.Amount": {"name": "Amount", "table": "Sales", "is_hidden": False}},
        )

        desktop_artifacts = SimpleNamespace(
            definition_folder="desktop://localhost:64078/model",
            objects={
                "Table:Sales": {"type": "Table"},
                "Column:Sales.Amount": {"type": "Column"},
                "Column:LocalDateTable_abc.Date": {"type": "Column"},
                "Measure:Sales.Total": {"type": "Measure"},
                "Measure:Sales.New Visits": {"type": "Measure"},
            },
            diagnostics={
                "semantic_inventory": {
                    "object_type_counts": {"Table": 1, "Column": 2, "Measure": 2},
                    "edge_category_counts": {"measure_to_column": 2, "measure_to_measure": 1},
                    "semantic_limitations": {"calc_groups_items_from_desktop_dmv": "not_extracted"},
                }
            },
            column_inventory={
                "Column:Sales.Amount": {"name": "Amount", "table": "Sales", "is_hidden": False},
                "Column:LocalDateTable_abc.Date": {
                    "name": "Date",
                    "table": "LocalDateTable_abc",
                    "is_hidden": True,
                },
            },
        )

        parity = _compute_semantic_parity_diff(pbip_artifacts, desktop_artifacts)

        self.assertEqual(parity["status"], "available")
        self.assertIn("Column:LocalDateTable_abc.Date", parity["object_id_differences"]["columns_only_in_desktop"])
        self.assertIn("Measure:Sales.New Visits", parity["object_id_differences"]["measures_only_in_desktop"])
        self.assertIn("CalcGroup:Time Intelligence", parity["object_id_differences"]["calc_groups_only_in_pbip"])
        self.assertIn("CalcItem:Time Intelligence.YTD", parity["object_id_differences"]["calc_items_only_in_pbip"])
        self.assertEqual(parity["edge_category_counts"]["diff_desktop_minus_pbip"]["measure_to_column"], 1)
        self.assertEqual(
            parity["desktop_extra_columns_classification"]["local_date_table_like"],
            1,
        )
        self.assertEqual(
            parity["desktop_extra_columns_classification"]["hidden"],
            1,
        )
        self.assertEqual(parity["calc_group_support"]["desktop"], "not_extracted")


if __name__ == "__main__":
    unittest.main()
