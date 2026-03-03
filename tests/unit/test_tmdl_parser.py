"""Unit tests for minimal TMDL parser extraction (Phase 1)."""

from __future__ import annotations

import unittest

from semantic_test.core.parse.tmdl_parser import parse_tmdl_documents


class TmdlParserTests(unittest.TestCase):
    def test_extracts_tables_columns_measures_relationships(self) -> None:
        table_doc = (
            "tables/Sales.tmdl",
            "\n".join(
                [
                    "table Sales",
                    "\tcolumn Amount",
                    "\tcolumn Flag = 1",
                    "\tmeasure 'Total Sales' =",
                    "\t\t",
                    "\t\tSUM(Sales[Amount])",
                    "\t\t+ 0",
                    "\tformatString: #,0",
                ]
            ),
            "dummy",
        )
        relationship_doc = (
            "relationships.tmdl",
            "\n".join(
                [
                    "relationship rel_1",
                    "\tfromColumn: Sales.Amount",
                    "\ttoColumn: Targets.Amount",
                ]
            ),
            "dummy",
        )

        parsed = parse_tmdl_documents([table_doc, relationship_doc])

        self.assertEqual([table.name for table in parsed.tables], ["Sales"])
        self.assertEqual([column.name for column in parsed.columns], ["Amount", "Flag"])
        self.assertEqual(parsed.columns[0].expression, None)
        self.assertEqual(parsed.columns[1].expression, "1")
        self.assertEqual([measure.name for measure in parsed.measures], ["Total Sales"])
        self.assertEqual(parsed.measures[0].table, "Sales")
        self.assertEqual(parsed.measures[0].expression, "SUM(Sales[Amount])\n+ 0")
        self.assertEqual(len(parsed.relationships), 1)
        self.assertEqual(parsed.relationships[0].from_table, "Sales")
        self.assertEqual(parsed.relationships[0].from_column, "Amount")
        self.assertEqual(parsed.relationships[0].to_table, "Targets")
        self.assertEqual(parsed.relationships[0].to_column, "Amount")

    def test_tolerates_missing_relationship_endpoints(self) -> None:
        doc = (
            "relationships.tmdl",
            "\n".join(
                [
                    "relationship rel_missing",
                    "\tannotation Note = no endpoints",
                ]
            ),
            "dummy",
        )

        parsed = parse_tmdl_documents([doc])

        self.assertEqual(len(parsed.relationships), 1)
        self.assertEqual(parsed.relationships[0].name, "rel_missing")
        self.assertIsNone(parsed.relationships[0].from_table)
        self.assertIsNone(parsed.relationships[0].to_table)


if __name__ == "__main__":
    unittest.main()
