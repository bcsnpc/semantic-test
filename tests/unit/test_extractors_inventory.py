"""Unit tests for table/column inventory extractors."""

from __future__ import annotations

import unittest

from semantic_test.core.parse.extractors.columns import extract_columns
from semantic_test.core.parse.extractors.relationships import extract_relationships
from semantic_test.core.parse.extractors.tables import extract_tables
from semantic_test.core.parse.tmdl_parser import parse_tmdl_documents


class ExtractorInventoryTests(unittest.TestCase):
    def test_extracts_table_and_column_inventories(self) -> None:
        docs = [
            (
                "tables/Sales.tmdl",
                "\n".join(
                    [
                        "table Sales",
                        "\tcolumn Amount",
                        "\tcolumn Flag = 1",
                    ]
                ),
                "dummy",
            )
        ]
        parsed = parse_tmdl_documents(docs)

        table_inventory = extract_tables(parsed)
        column_inventory = extract_columns(parsed)

        self.assertIn("Table:Sales", table_inventory)
        self.assertIn("Column:Sales.Amount", column_inventory)
        self.assertIn("Column:Sales.Flag", column_inventory)
        self.assertEqual(table_inventory["Table:Sales"]["name"], "Sales")
        self.assertEqual(column_inventory["Column:Sales.Flag"]["expression"], "1")

    def test_column_without_table_uses_unknown_placeholder(self) -> None:
        docs = [("misc.tmdl", "column LooseColumn", "dummy")]
        parsed = parse_tmdl_documents(docs)

        column_inventory = extract_columns(parsed)

        self.assertIn("Column:<unknown>.LooseColumn", column_inventory)
        self.assertFalse(column_inventory["Column:<unknown>.LooseColumn"]["has_known_table"])

    def test_extracts_single_relationship_with_canonical_id(self) -> None:
        docs = [
            (
                "relationships.tmdl",
                "\n".join(
                    [
                        "relationship rel_1",
                        "\tfromColumn: Sales.CustomerId",
                        "\ttoColumn: Customer.Id",
                    ]
                ),
                "dummy",
            )
        ]
        parsed = parse_tmdl_documents(docs)

        relationship_inventory = extract_relationships(parsed)

        self.assertEqual(len(relationship_inventory), 1)
        rel_id = "Rel:Sales.CustomerId->Customer.Id"
        self.assertIn(rel_id, relationship_inventory)
        self.assertEqual(relationship_inventory[rel_id]["name"], "rel_1")
        self.assertTrue(relationship_inventory[rel_id]["is_complete"])

    def test_relationship_cardinality_extracted(self) -> None:
        """Cardinality property is parsed and stored in relationship metadata."""
        docs = [
            (
                "relationships.tmdl",
                "\n".join(
                    [
                        "relationship rel_many_to_one",
                        "\tfromColumn: Sales.DateKey",
                        "\ttoColumn: Date.DateKey",
                        "\tcardinality: manyToOne",
                    ]
                ),
                "dummy",
            )
        ]
        parsed = parse_tmdl_documents(docs)

        inventory = extract_relationships(parsed)

        rel_id = "Rel:Sales.DateKey->Date.DateKey"
        self.assertIn(rel_id, inventory)
        self.assertEqual(inventory[rel_id]["cardinality"], "manyToOne")

    def test_relationship_cross_filter_extracted(self) -> None:
        """Cross-filtering behavior property is parsed and stored."""
        docs = [
            (
                "relationships.tmdl",
                "\n".join(
                    [
                        "relationship rel_bidirectional",
                        "\tfromColumn: Sales.ProductId",
                        "\ttoColumn: Product.Id",
                        "\tcrossFilteringBehavior: bothDirections",
                    ]
                ),
                "dummy",
            )
        ]
        parsed = parse_tmdl_documents(docs)

        inventory = extract_relationships(parsed)

        rel_id = "Rel:Sales.ProductId->Product.Id"
        self.assertEqual(inventory[rel_id]["cross_filter_direction"], "bothDirections")

    def test_relationship_is_active_extracted(self) -> None:
        """isActive property defaults to True; explicit false is parsed."""
        active_docs = [
            (
                "relationships.tmdl",
                "\n".join(
                    [
                        "relationship rel_active",
                        "\tfromColumn: A.Key",
                        "\ttoColumn: B.Key",
                        "\tisActive: true",
                    ]
                ),
                "dummy",
            )
        ]
        inactive_docs = [
            (
                "relationships.tmdl",
                "\n".join(
                    [
                        "relationship rel_inactive",
                        "\tfromColumn: A.Key",
                        "\ttoColumn: B.Key",
                        "\tisActive: false",
                    ]
                ),
                "dummy",
            )
        ]
        no_prop_docs = [
            (
                "relationships.tmdl",
                "\n".join(
                    [
                        "relationship rel_default",
                        "\tfromColumn: A.Key",
                        "\ttoColumn: B.Key",
                    ]
                ),
                "dummy",
            )
        ]

        active_inventory = extract_relationships(parse_tmdl_documents(active_docs))
        inactive_inventory = extract_relationships(parse_tmdl_documents(inactive_docs))
        default_inventory = extract_relationships(parse_tmdl_documents(no_prop_docs))

        self.assertTrue(active_inventory["Rel:A.Key->B.Key"]["is_active"])
        self.assertFalse(inactive_inventory["Rel:A.Key->B.Key"]["is_active"])
        self.assertTrue(default_inventory["Rel:A.Key->B.Key"]["is_active"])

    def test_relationship_defaults_when_properties_absent(self) -> None:
        """When optional relationship properties are absent, defaults are used."""
        docs = [
            (
                "relationships.tmdl",
                "\n".join(
                    [
                        "relationship rel_minimal",
                        "\tfromColumn: Fact.Key",
                        "\ttoColumn: Dim.Key",
                    ]
                ),
                "dummy",
            )
        ]
        parsed = parse_tmdl_documents(docs)

        inventory = extract_relationships(parsed)

        rel = inventory["Rel:Fact.Key->Dim.Key"]
        self.assertIsNone(rel["cardinality"])
        self.assertIsNone(rel["cross_filter_direction"])
        self.assertTrue(rel["is_active"])


if __name__ == "__main__":
    unittest.main()
