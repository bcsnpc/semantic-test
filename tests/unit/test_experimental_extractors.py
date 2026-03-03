"""Unit tests for calc-group and field-parameter experimental extractors."""

from __future__ import annotations

import unittest

from semantic_test.core.parse.extractors.calc_groups import extract_calc_groups
from semantic_test.core.parse.extractors.field_params import extract_field_params
from semantic_test.core.parse.tmdl_parser import parse_tmdl_documents


class ExperimentalExtractorsTests(unittest.TestCase):
    def test_calc_group_nodes_and_dependencies(self) -> None:
        docs = [
            (
                "tables/Time Calc.tmdl",
                "\n".join(
                    [
                        "table 'Time Calc'",
                        "\tcalculationGroup",
                        "\tcalculationItem YTD = [Sales Amount] + SUM('Date'[Day])",
                    ]
                ),
                "dummy",
            ),
            ("tables/Metrics.tmdl", "table Metrics\n\tmeasure 'Sales Amount' = 1", "dummy"),
        ]
        parsed = parse_tmdl_documents(docs)

        inventory = extract_calc_groups(parsed, docs)

        self.assertIn("CalcGroup:Time Calc", inventory)
        self.assertIn("CalcItem:Time Calc.YTD", inventory)
        calc_item = inventory["CalcItem:Time Calc.YTD"]
        self.assertTrue(calc_item["experimental_coverage"])
        self.assertIn("Measure:Metrics.Sales Amount", calc_item["dependencies"])
        self.assertIn("Column:Date.Day", calc_item["dependencies"])

    def test_field_param_nodes_and_dependencies(self) -> None:
        docs = [
            (
                "tables/My Param.tmdl",
                "\n".join(
                    [
                        "table 'My Param'",
                        "\tcolumn ParameterField",
                        "\t\textendedProperty ParameterMetadata = {\"kind\":2}",
                        "\tpartition 'My Param' = calculated",
                        "\t\tsource =",
                        "\t\t\t{",
                        "\t\t\t\t(\"A\", NAMEOF('Metrics'[Sales Amount]), 0)",
                        "\t\t\t}",
                    ]
                ),
                "dummy",
            )
        ]
        parsed = parse_tmdl_documents(docs)

        inventory = extract_field_params(parsed, docs)

        self.assertIn("FieldParam:My Param", inventory)
        field_param = inventory["FieldParam:My Param"]
        self.assertTrue(field_param["experimental_coverage"])
        self.assertTrue(field_param["special_table"])
        self.assertIn("Column:Metrics.Sales Amount", field_param["dependencies"])

    def test_calc_item_selectedmeasure_emits_unsupported_pattern(self) -> None:
        """SELECTEDMEASURE() in a calc item expression must emit
        unsupported_pattern:SELECTEDMEASURE() and NOT produce a dependency edge."""
        docs = [
            (
                "tables/Time Calc.tmdl",
                "\n".join(
                    [
                        "table 'Time Calc'",
                        "\tcalculationGroup",
                        "\tcalculationItem YTD = CALCULATE(SELECTEDMEASURE(), DATESYTD('Date'[Date]))",
                    ]
                ),
                "dummy",
            ),
            ("tables/Metrics.tmdl", "table Metrics\n\tmeasure 'Growth Rate' = 1", "dummy"),
        ]
        parsed = parse_tmdl_documents(docs)

        inventory = extract_calc_groups(parsed, docs)

        self.assertIn("CalcItem:Time Calc.YTD", inventory)
        ytd = inventory["CalcItem:Time Calc.YTD"]

        # SELECTEDMEASURE() must be emitted as an unsupported pattern
        self.assertIn("unsupported_pattern:SELECTEDMEASURE()", ytd["unknown_patterns"])
        # 'Date'[Date] should still be captured as a column dependency
        self.assertIn("Column:Date.Date", ytd["dependencies"])
        # SELECTEDMEASURE() itself must NOT add any dependency edge
        for dep in ytd["dependencies"]:
            self.assertFalse(dep.startswith("SELECTED"), msg=f"Unexpected dependency: {dep}")

    def test_calc_item_selectedmeasure_coexists_with_measure_ref(self) -> None:
        """SELECTEDMEASURE() + [MeasureName] in same expression: both behaviors apply."""
        docs = [
            (
                "tables/Time Calc.tmdl",
                "\n".join(
                    [
                        "table 'Time Calc'",
                        "\tcalculationGroup",
                        "\tcalculationItem Scaled = SELECTEDMEASURE() * [Growth Rate]",
                    ]
                ),
                "dummy",
            ),
            ("tables/Metrics.tmdl", "table Metrics\n\tmeasure 'Growth Rate' = 1", "dummy"),
        ]
        parsed = parse_tmdl_documents(docs)

        inventory = extract_calc_groups(parsed, docs)

        scaled = inventory["CalcItem:Time Calc.Scaled"]
        self.assertIn("unsupported_pattern:SELECTEDMEASURE()", scaled["unknown_patterns"])
        # [Growth Rate] must still resolve to its measure dependency
        self.assertIn("Measure:Metrics.Growth Rate", scaled["dependencies"])


if __name__ == "__main__":
    unittest.main()
