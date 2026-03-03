"""Unit tests for stable snapshot generation."""

from __future__ import annotations

import unittest

from semantic_test.core.diff.snapshot import build_snapshot
from semantic_test.core.graph.builder import build_dependency_graph


class SnapshotBuilderTests(unittest.TestCase):
    def test_identical_model_yields_identical_snapshot_hash(self) -> None:
        objects_a = {
            "Measure:Sales.Total": {
                "type": "Measure",
                "raw_expression": "SUM(Sales[Amount])\n\n+ 0  ",
                "dependencies": {"Column:Sales.Amount"},
                "source_file": "tables/Sales.tmdl",
            },
            "Column:Sales.Amount": {
                "type": "Column",
                "dependencies": set(),
                "source_file": "tables/Sales.tmdl",
            },
        }
        objects_b = {
            "Column:Sales.Amount": {
                "type": "Column",
                "source_file": "tables/Sales.tmdl",
                "dependencies": set(),
            },
            "Measure:Sales.Total": {
                "type": "Measure",
                "source_file": "tables/Sales.tmdl",
                "dependencies": {"Column:Sales.Amount"},
                "raw_expression": "SUM(Sales[Amount])\r\n\r\n+ 0",
            },
        }

        graph_a = build_dependency_graph(objects_a)
        graph_b = build_dependency_graph(objects_b)
        snapshot_a = build_snapshot(
            objects_a,
            graph_a,
            model_key="semanticmodel::Sample.SemanticModel/definition",
            definition_path="Sample.SemanticModel/definition",
            unknown_patterns=[{"object_id": "Measure:Sales.Total", "patterns": ["unresolved_measure:[Missing]"]}],
        )
        snapshot_b = build_snapshot(
            objects_b,
            graph_b,
            model_key="semanticmodel::Sample.SemanticModel/definition",
            definition_path="Sample.SemanticModel/definition",
            unknown_patterns=[{"object_id": "Measure:Sales.Total", "patterns": ["unresolved_measure:[Missing]"]}],
        )

        self.assertEqual(snapshot_a.snapshot_hash, snapshot_b.snapshot_hash)
        self.assertEqual(snapshot_a.objects["Measure:Sales.Total"].object_hash, snapshot_b.objects["Measure:Sales.Total"].object_hash)
        self.assertEqual(snapshot_a.node_count, 2)
        self.assertEqual(snapshot_a.edge_count, 1)
        self.assertEqual(snapshot_a.model_key, "semanticmodel::Sample.SemanticModel/definition")
        self.assertEqual(snapshot_a.definition_path, "Sample.SemanticModel/definition")
        self.assertEqual(snapshot_a.edges, [("Measure:Sales.Total", "Column:Sales.Amount", "depends_on")])
        self.assertEqual(snapshot_a.unresolved_refs, [{"object_id": "Measure:Sales.Total", "ref": "unresolved_measure:[Missing]"}])


if __name__ == "__main__":
    unittest.main()
