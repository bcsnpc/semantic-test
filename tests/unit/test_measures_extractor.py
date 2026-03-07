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

    def test_missing_measure_includes_did_you_mean_suggestions(self) -> None:
        docs = [
            (
                "tables/Metrics.tmdl",
                "\n".join(
                    [
                        "table Metrics",
                        "\tmeasure Some Measure = 1",
                        "\tmeasure Another Metric = 2",
                        "\tmeasure KPI = [Som Measure]",
                    ]
                ),
                "dummy",
            )
        ]
        parsed = parse_tmdl_documents(docs)
        inventory = extract_measures(parsed)
        kpi = inventory["Measure:Metrics.KPI"]

        unresolved = kpi["unresolved_references"][0]
        self.assertIn("did_you_mean", unresolved)
        self.assertTrue(unresolved["did_you_mean"])
        self.assertTrue(any(item.endswith("Some Measure") for item in unresolved["did_you_mean"]))

    def test_best_guess_threshold_applied_for_close_match(self) -> None:
        docs = [
            (
                "tables/Metrics.tmdl",
                "\n".join(
                    [
                        "table Metrics",
                        "\tmeasure Feedback Rating Measure1 = 1",
                        "\tmeasure KPI = [Feedback Rating Measure]",
                    ]
                ),
                "dummy",
            )
        ]
        parsed = parse_tmdl_documents(docs)
        inventory = extract_measures(parsed)
        issue = inventory["Measure:Metrics.KPI"]["unresolved_references"][0]

        self.assertIsNotNone(issue["best_guess"])
        self.assertGreaterEqual(int(issue["best_guess_score"]), 85)
        self.assertEqual(issue["action"], "RENAME_REFERENCE")
        self.assertIsInstance(issue.get("why_best_guess"), str)
        self.assertTrue(issue.get("why_best_guess"))

    def test_best_guess_null_when_score_below_threshold(self) -> None:
        docs = [
            (
                "tables/Metrics.tmdl",
                "\n".join(
                    [
                        "table Metrics",
                        "\tmeasure Revenue = 1",
                        "\tmeasure KPI = [ZZZZUnknownThing]",
                    ]
                ),
                "dummy",
            )
        ]
        parsed = parse_tmdl_documents(docs)
        inventory = extract_measures(parsed)
        issue = inventory["Measure:Metrics.KPI"]["unresolved_references"][0]

        self.assertIsNone(issue["best_guess"])
        self.assertIsNone(issue["best_guess_score"])
        self.assertIn(issue["action"], {"ADD_MISSING_OBJECT", "MANUAL_REVIEW"})

    def test_top3_ranked_candidates_follow_expected_type(self) -> None:
        docs = [
            (
                "tables/Metrics.tmdl",
                "\n".join(
                    [
                        "table Other",
                        "\tcolumn Feedback Rating Measure",
                        "table Metrics",
                        "\tmeasure Feedback Rating Measure1 = 1",
                        "\tmeasure KPI = [Feedback Rating Measure]",
                    ]
                ),
                "dummy",
            )
        ]
        parsed = parse_tmdl_documents(docs)
        inventory = extract_measures(parsed)
        issue = inventory["Measure:Metrics.KPI"]["unresolved_references"][0]

        top3 = issue.get("did_you_mean_top3_ranked", [])
        self.assertTrue(top3)
        self.assertTrue(all(str(item.get("candidate", "")).startswith("measure:") for item in top3))

    def test_var_local_symbol_is_not_reported_unresolved(self) -> None:
        docs = [
            (
                "tables/Metrics.tmdl",
                "\n".join(
                    [
                        "table Metrics",
                        "\tmeasure Base = 1",
                        "\tmeasure KPI = VAR [new period] = [Base] RETURN [new period]",
                    ]
                ),
                "dummy",
            )
        ]
        parsed = parse_tmdl_documents(docs)

        inventory = extract_measures(parsed)
        kpi = inventory["Measure:Metrics.KPI"]

        self.assertIn("Measure:Metrics.Base", kpi["dependencies"])
        self.assertEqual(kpi["unresolved_references"], [])
        self.assertFalse(any("new period" in item for item in kpi["unknown_patterns"]))

    def test_virtual_alias_from_addcolumns_is_not_reported_unresolved(self) -> None:
        docs = [
            (
                "tables/Metrics.tmdl",
                "\n".join(
                    [
                        "table Date",
                        "\tcolumn Date",
                        "table Metrics",
                        "\tmeasure Base = 1",
                        (
                            '\tmeasure KPI = COUNTROWS(FILTER('
                            "ADDCOLUMNS(VALUES('Date'[Date]), \"new period\", [Base]), "
                            "[new period] > 0))"
                        ),
                    ]
                ),
                "dummy",
            )
        ]
        parsed = parse_tmdl_documents(docs)

        inventory = extract_measures(parsed)
        kpi = inventory["Measure:Metrics.KPI"]

        self.assertIn("Measure:Metrics.Base", kpi["dependencies"])
        self.assertIn("Column:Date.Date", kpi["dependencies"])
        self.assertEqual(kpi["unresolved_references"], [])
        self.assertFalse(any("new period" in item for item in kpi["unknown_patterns"]))

    def test_virtual_alias_from_selectcolumns_and_summarize_not_reported_unresolved(self) -> None:
        docs = [
            (
                "tables/Metrics.tmdl",
                "\n".join(
                    [
                        "table Date",
                        "\tcolumn Date",
                        "table Metrics",
                        "\tmeasure Base = 1",
                        (
                            '\tmeasure KPI = COUNTROWS(FILTER('
                            "SELECTCOLUMNS(SUMMARIZE('Date', 'Date'[Date], \"alias1\", [Base]), "
                            "\"alias2\", [alias1]), [alias2] > 0))"
                        ),
                    ]
                ),
                "dummy",
            )
        ]
        parsed = parse_tmdl_documents(docs)

        inventory = extract_measures(parsed)
        kpi = inventory["Measure:Metrics.KPI"]

        self.assertIn("Measure:Metrics.Base", kpi["dependencies"])
        self.assertIn("Column:Date.Date", kpi["dependencies"])
        self.assertEqual(kpi["unresolved_references"], [])
        self.assertFalse(any("alias1" in item or "alias2" in item for item in kpi["unknown_patterns"]))

    def test_duplicate_unresolved_refs_are_deduplicated_per_expression(self) -> None:
        docs = [
            (
                "tables/Metrics.tmdl",
                "\n".join(
                    [
                        "table Metrics",
                        "\tmeasure KPI = [MissingX] + [MissingX] + IF([MissingX] > 0, 1, 0)",
                    ]
                ),
                "dummy",
            )
        ]
        parsed = parse_tmdl_documents(docs)
        inventory = extract_measures(parsed)
        kpi = inventory["Measure:Metrics.KPI"]

        self.assertEqual(
            [pattern for pattern in kpi["unknown_patterns"] if pattern == "unresolved_measure:[MissingX]"],
            ["unresolved_measure:[MissingX]"],
        )
        unresolved = [item for item in kpi["unresolved_references"] if item.get("ref") == "[MissingX]"]
        self.assertEqual(len(unresolved), 1)


if __name__ == "__main__":
    unittest.main()
