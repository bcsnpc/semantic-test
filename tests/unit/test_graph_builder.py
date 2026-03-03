"""Unit tests for dependency graph builder and traversal."""

from __future__ import annotations

import unittest

from semantic_test.core.graph.builder import build_dependency_graph
from semantic_test.core.graph.queries import (
    downstream,
    downstream_by_type,
    traverse_downstream,
    traverse_upstream,
)


class GraphBuilderTests(unittest.TestCase):
    def test_graph_stats_and_downstream_traversal(self) -> None:
        objects = {
            "Measure:Sales.Total": {
                "type": "Measure",
                "dependencies": {"Column:Sales.Amount", "Measure:Sales.Base"},
            },
            "Measure:Sales.Base": {
                "type": "Measure",
                "dependencies": {"Column:Sales.Amount"},
            },
            "Column:Sales.Amount": {
                "type": "Column",
                "dependencies": set(),
            },
        }

        graph = build_dependency_graph(objects)

        self.assertEqual(graph.node_count, 3)
        self.assertEqual(graph.edge_count, 3)
        self.assertEqual(
            traverse_downstream(graph, "Column:Sales.Amount"),
            {"Measure:Sales.Base", "Measure:Sales.Total"},
        )
        self.assertEqual(
            traverse_upstream(graph, "Measure:Sales.Total"),
            {"Measure:Sales.Base", "Column:Sales.Amount"},
        )
        self.assertEqual(
            downstream("Column:Sales.Amount", graph.reverse),
            {"Measure:Sales.Base", "Measure:Sales.Total"},
        )
        self.assertEqual(
            downstream_by_type(
                "Column:Sales.Amount",
                graph.reverse,
                {node_id: node.type for node_id, node in graph.nodes.items()},
            ),
            {"Measure": 2},
        )


if __name__ == "__main__":
    unittest.main()
