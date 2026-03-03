"""Integration tests for TMDL file loading from fixture trees."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from semantic_test.core.parse.pbip_locator import locate_definition_folder
from semantic_test.core.parse.tmdl_reader import read_tmdl_documents, read_tmdl_files


class TmdlReaderIntegrationTests(unittest.TestCase):
    def test_reads_expected_file_count_from_vc_test1(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        vc_root = repo_root / "vc_test1"
        self.assertTrue(vc_root.exists(), f"Missing integration data folder: {vc_root}")
        definition = locate_definition_folder(vc_root)

        files = read_tmdl_files(definition)
        expected_count = 23

        self.assertEqual(len(files), expected_count)
        self.assertEqual(files[0][0], "cultures/en-US.tmdl")
        self.assertEqual(files[-1][0], "tables/Time.tmdl")
        self.assertTrue(all(len(item) == 3 for item in files))

    def test_normalizes_content_and_preserves_raw(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            definition = Path(tmp) / "X.SemanticModel" / "definition"
            definition.mkdir(parents=True)
            file_path = definition / "crlf.tmdl"
            file_path.write_bytes(b"line1\r\nline2\r\n")

            docs = read_tmdl_documents(definition)

            self.assertEqual(len(docs), 1)
            self.assertEqual(docs[0].content, "line1\nline2\n")
            self.assertEqual(docs[0].raw_content, "line1\r\nline2\r\n")
            expected_hash = hashlib.sha256("line1\nline2\n".encode("utf-8")).hexdigest()
            self.assertEqual(docs[0].sha256, expected_hash)


if __name__ == "__main__":
    unittest.main()
