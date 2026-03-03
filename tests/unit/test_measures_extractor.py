"""Unit tests for measure extractor and dependency parsing v1."""

from __future__ import annotations

import unittest

from semantic_test.core.parse.extractors.measures import extract_measures
from semantic_test.core.parse.tmdl_parser import parse_tmdl_documents


class MeasureExtractorTests(unittest.TestCase):
    def test_extracts_common_dependency_patterns(self) -> None:
        docs = [
            (
                "tables/Metrics.tmdl",
                "\n".join(
                    [
                        "table Metrics",
                        "\tmeasure 'Total Orders' = 42",
                        "\tmeasure KPI = [Total Orders] + SUM('Sales'[Amount]) + SUM(Sales[Qty])",
                    ]
                ),
                "dummy",
            )
        ]
        parsed = parse_tmdl_documents(docs)

        inventory = extract_measures(parsed)
        kpi = inventory["Measure:Metrics.KPI"]

        self.assertEqual(kpi["raw_expression"], "[Total Orders] + SUM('Sales'[Amount]) + SUM(Sales[Qty])")
        self.assertIn("Measure:Metrics.Total Orders", kpi["dependencies"])
        self.assertIn("Column:Sales.Amount", kpi["dependencies"])
        self.assertIn("Column:Sales.Qty", kpi["dependencies"])
        self.assertEqual(kpi["unknown_patterns"], [])

    def test_records_unknown_patterns_for_unresolved_or_ambiguous_refs(self) -> None:
        docs = [
            (
                "tables/A.tmdl",
                "\n".join(
                    [
                        "table A",
                        "\tmeasure Dup = 1",
                    ]
                ),
                "dummy",
            ),
            (
                "tables/B.tmdl",
                "\n".join(
                    [
                        "table B",
                        "\tmeasure Dup = 2",
                        "\tmeasure KPI = [Dup] + [MissingMeasure]",
                    ]
                ),
                "dummy",
            ),
        ]
        parsed = parse_tmdl_documents(docs)

        inventory = extract_measures(parsed)
        kpi = inventory["Measure:B.KPI"]

        # [Dup] resolves to local table measure B.Dup
        self.assertIn("Measure:B.Dup", kpi["dependencies"])
        # [MissingMeasure] cannot be resolved and must be disclosed.
        self.assertIn("unresolved_measure:[MissingMeasure]", kpi["unknown_patterns"])

    def test_ambiguous_measure_reference_is_recorded(self) -> None:
        docs = [
            ("tables/A.tmdl", "table A\n\tmeasure Dup = 1", "dummy"),
            ("tables/B.tmdl", "table B\n\tmeasure Dup = 2", "dummy"),
            ("tables/C.tmdl", "table C\n\tmeasure KPI = [Dup]", "dummy"),
        ]
        parsed = parse_tmdl_documents(docs)

        inventory = extract_measures(parsed)
        kpi = inventory["Measure:C.KPI"]

        self.assertEqual(kpi["dependencies"], set())
        self.assertIn("unresolved_measure:[Dup]", kpi["unknown_patterns"])

    def test_selectedmeasure_emits_unsupported_pattern(self) -> None:
        docs = [
            (
                "tables/Calc.tmdl",
                "table Calc\n\tmeasure Growth = SELECTEDMEASURE() * 1.1",
                "dummy",
            )
        ]
        parsed = parse_tmdl_documents(docs)

        inventory = extract_measures(parsed)
        growth = inventory["Measure:Calc.Growth"]

        self.assertIn("unsupported_pattern:SELECTEDMEASURE()", growth["unknown_patterns"])
        # SELECTEDMEASURE() must NOT produce a dependency edge
        self.assertEqual(growth["dependencies"], set())

    def test_selectedmeasurename_emits_unsupported_pattern(self) -> None:
        docs = [
            (
                "tables/Calc.tmdl",
                'table Calc\n\tmeasure Label = IF(SELECTEDMEASURENAME()="Sales", 1, 0)',
                "dummy",
            )
        ]
        parsed = parse_tmdl_documents(docs)

        inventory = extract_measures(parsed)
        label = inventory["Measure:Calc.Label"]

        self.assertIn("unsupported_pattern:SELECTEDMEASURENAME()", label["unknown_patterns"])
        self.assertEqual(label["dependencies"], set())

    def test_selectedmeasure_coexists_with_bracket_ref_dependencies(self) -> None:
        """SELECTEDMEASURE() emits unsupported pattern; bracket refs in same
        expression still resolve normally."""
        docs = [
            (
                "tables/Metrics.tmdl",
                "table Metrics\n\tmeasure Base = 1\n\tmeasure Growth = SELECTEDMEASURE() * [Base]",
                "dummy",
            )
        ]
        parsed = parse_tmdl_documents(docs)

        inventory = extract_measures(parsed)
        growth = inventory["Measure:Metrics.Growth"]

        self.assertIn("unsupported_pattern:SELECTEDMEASURE()", growth["unknown_patterns"])
        # [Base] should still be resolved as a dependency
        self.assertIn("Measure:Metrics.Base", growth["dependencies"])


if __name__ == "__main__":
    unittest.main()
