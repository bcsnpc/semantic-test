"""Integration tests for snapshot differ."""

from __future__ import annotations

import unittest

from semantic_test.core.diff.change_types import ModifiedObject
from semantic_test.core.diff.differ import diff_snapshots
from semantic_test.core.diff.snapshot import build_snapshot
from semantic_test.core.graph.builder import build_dependency_graph
from semantic_test.core.parse.extractors.measures import extract_measures
from semantic_test.core.parse.tmdl_parser import parse_tmdl_documents


def _build_measure_snapshot(expression: str):
    docs = [
        (
            "tables/Metrics.tmdl",
            "\n".join(
                [
                    "table Metrics",
                    f"\tmeasure KPI = {expression}",
                ]
            ),
            "dummy",
        )
    ]
    parsed = parse_tmdl_documents(docs)
    measures = extract_measures(parsed)
    graph = build_dependency_graph(measures)
    return build_snapshot(measures, graph)


class DifferIntegrationTests(unittest.TestCase):
    def test_measure_expression_change_produces_modified_object(self) -> None:
        before = _build_measure_snapshot("1")
        after = _build_measure_snapshot("2")

        result = diff_snapshots(before, after)

        self.assertEqual(result.added_object_ids, [])
        self.assertEqual(result.removed_object_ids, [])
        self.assertEqual(result.modified_object_ids, ["Measure:Metrics.KPI"])
        self.assertEqual(len(result.changes), 1)
        self.assertIsInstance(result.changes[0], ModifiedObject)
        self.assertEqual(result.changes[0].object_id, "Measure:Metrics.KPI")
        self.assertEqual(result.changes[0].object_type, "Measure")
        self.assertEqual(result.changes[0].change_type, "ModifiedObject")


if __name__ == "__main__":
    unittest.main()
