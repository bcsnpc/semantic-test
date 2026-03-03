"""Unit tests for index manager."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from semantic_test.core.io.index_manager import (
    get_model_entry,
    load_index,
    save_index_atomic,
    upsert_model_entry,
)


class IndexManagerTests(unittest.TestCase):
    def test_load_index_defaults_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index = load_index(tmp)
            self.assertEqual(index["schema_version"], "1")
            self.assertEqual(index["models"], [])

    def test_upsert_and_get_model_entry(self) -> None:
        index = {"schema_version": "1", "models": []}
        upsert_model_entry(
            index,
            model_key="semanticmodel::/abs/model/definition",
            definition_path="MyModel.SemanticModel/definition",
            latest_snapshot_hash="abc123",
            latest_run_id="run_1",
            latest_run_path=".semantic-test/runs/run_1",
        )
        entry = get_model_entry(index, "semanticmodel::/abs/model/definition")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["latest_run_id"], "run_1")

        upsert_model_entry(
            index,
            model_key="semanticmodel::/abs/model/definition",
            definition_path="MyModel.SemanticModel/definition",
            latest_snapshot_hash="def456",
            latest_run_id="run_2",
            latest_run_path=".semantic-test/runs/run_2",
        )
        entry = get_model_entry(index, "semanticmodel::/abs/model/definition")
        self.assertEqual(entry["latest_snapshot_hash"], "def456")
        self.assertEqual(entry["latest_run_id"], "run_2")
        self.assertEqual(len(index["models"]), 1)

    def test_save_index_atomic_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = {"schema_version": "1", "models": [{"model_key": "m", "definition_path": "d", "latest_snapshot_hash": "h", "latest_run_id": "r", "latest_run_path": "p"}]}
            path = save_index_atomic(root, index)
            self.assertTrue(path.exists())
            loaded = load_index(root)
            self.assertEqual(loaded, index)


if __name__ == "__main__":
    unittest.main()
