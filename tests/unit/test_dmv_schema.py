from __future__ import annotations

import unittest
from unittest.mock import patch

from semantic_test.core.live.dmv_schema import _query_columns


class DmvSchemaTests(unittest.TestCase):
    def test_query_columns_uses_explicit_name_and_type_filter(self) -> None:
        rows = [
            {
                "TableID": 10,
                "ExplicitName": "SalesAmount",
                "Name": "IgnoredName",
                "DataType": 8,
                "IsHidden": 0,
                "Type": 1,
            },
            {
                "TableID": 10,
                "ExplicitName": "RowNumber",
                "DataType": 2,
                "IsHidden": 1,
                "Type": 3,
            },
        ]
        with patch("semantic_test.core.live.dmv_schema._recordset_dicts", return_value=rows):
            columns = _query_columns(conn=object())

        self.assertEqual(len(columns), 1)
        self.assertEqual(columns[0]["table_id"], 10)
        self.assertEqual(columns[0]["name"], "SalesAmount")
        self.assertEqual(columns[0]["data_type"], 8)
        self.assertEqual(columns[0]["is_hidden"], False)

    def test_query_columns_falls_back_to_name_when_explicit_name_missing(self) -> None:
        rows = [
            {
                "tableid": 21,
                "name": "OrderDate",
                "datatype": 9,
                "ishidden": "true",
            }
        ]
        with patch("semantic_test.core.live.dmv_schema._recordset_dicts", return_value=rows):
            columns = _query_columns(conn=object())

        self.assertEqual(len(columns), 1)
        self.assertEqual(columns[0]["table_id"], 21)
        self.assertEqual(columns[0]["name"], "OrderDate")
        self.assertEqual(columns[0]["data_type"], 9)
        self.assertEqual(columns[0]["is_hidden"], True)


if __name__ == "__main__":
    unittest.main()
