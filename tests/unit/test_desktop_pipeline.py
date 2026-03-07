from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from semantic_test.cli.commands._pipeline import build_model_artifacts_from_desktop
from semantic_test.core.live.dmv_schema import DesktopSchema


class DesktopPipelineTests(unittest.TestCase):
    def test_desktop_measure_resolution_uses_canonical_registry(self) -> None:
        schema = DesktopSchema(
            catalog_name="SalesModel",
            tables=[
                {"id": 1, "name": "Sales", "is_hidden": False},
                {"id": 2, "name": "Date", "is_hidden": False},
            ],
            columns=[
                {"id": 101, "table_id": 1, "name": "Amount", "is_hidden": False},
                {"id": 102, "table_id": 2, "name": "Date", "is_hidden": False},
            ],
            measures=[
                {"table_id": 1, "name": "Total New Amount", "expression": "SUM('Sales'[Amount])"},
                {"table_id": 1, "name": "New Visits", "expression": "COUNTROWS(Sales)"},
                {
                    "table_id": 1,
                    "name": "Total Amount Comparision LY",
                    "expression": "[Total New Amount] + [New Visits]",
                },
            ],
            relationships=[
                {
                    "from_table_id": 1,
                    "from_column_id": 101,
                    "to_table_id": 2,
                    "to_column_id": 102,
                    "is_active": True,
                    "cross_filter": 1,
                    "from_cardinality": 2,
                    "to_cardinality": 1,
                }
            ],
        )

        with patch("semantic_test.core.live.dmv_schema.extract_desktop_schema", return_value=schema):
            artifacts = build_model_artifacts_from_desktop(54321)

        comparison = artifacts.measure_inventory["Measure:Sales.Total Amount Comparision LY"]
        self.assertIn("Measure:Sales.Total New Amount", comparison["dependencies"])
        self.assertIn("Measure:Sales.New Visits", comparison["dependencies"])
        self.assertEqual(comparison["unknown_patterns"], [])

        rel_id = "Rel:Sales.Amount->Date.Date"
        self.assertIn(rel_id, artifacts.relationship_inventory)
        self.assertIn("Column:Date.Date", artifacts.graph.forward["Column:Sales.Amount"])
        self.assertIn("Column:Sales.Amount", artifacts.graph.forward["Column:Date.Date"])

    def test_desktop_visuals_are_loaded_from_workspace_report_definition(self) -> None:
        schema = DesktopSchema(
            catalog_name="SalesModel",
            tables=[{"id": 1, "name": "Sales", "is_hidden": False}],
            columns=[{"id": 101, "table_id": 1, "name": "Amount", "is_hidden": False}],
            measures=[{"table_id": 1, "name": "Total New Amount", "expression": "SUM('Sales'[Amount])"}],
            relationships=[],
        )

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            visual_dir = ws / "Report" / "definition" / "pages" / "page1" / "visuals" / "visual123456789abc"
            visual_dir.mkdir(parents=True, exist_ok=True)
            (ws / "Report" / "definition" / "pages" / "page1" / "page.json").write_text(
                json.dumps({"displayName": "Overview", "filterConfig": {"filters": []}}),
                encoding="utf-8",
            )
            (visual_dir / "visual.json").write_text(
                json.dumps(
                    {
                        "name": "visual123456789abc",
                        "visual": {
                            "visualType": "card",
                            "query": {
                                "queryState": {
                                    "Values": {
                                        "projections": [
                                            {
                                                "field": {
                                                    "Measure": {
                                                        "Expression": {"SourceRef": {"Entity": "Sales"}},
                                                        "Property": "Total New Amount",
                                                    }
                                                }
                                            }
                                        ]
                                    }
                                }
                            },
                            "visualContainerObjects": {
                                "title": [
                                    {
                                        "properties": {
                                            "text": {
                                                "expr": {"Literal": {"Value": "'Revenue Card'"}}
                                            }
                                        }
                                    }
                                ]
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            with patch("semantic_test.core.live.dmv_schema.extract_desktop_schema", return_value=schema):
                artifacts = build_model_artifacts_from_desktop(54321, workspace_dir=str(ws))

        self.assertEqual(len(artifacts.visual_inventory), 1)
        visual = next(iter(artifacts.visual_inventory.values()))
        self.assertEqual(visual["page_name"], "Overview")
        self.assertEqual(visual["title"], "Revenue Card")
        self.assertEqual(visual["visual_name"], "visual123456789abc")
        self.assertIn("Measure:Sales.Total New Amount", visual["dependencies"])


if __name__ == "__main__":
    unittest.main()
