"""Unit tests for canonical object IDs."""

import unittest

from semantic_test.core.model.objects import ObjectRef, ObjectType, object_id


class ObjectIdTests(unittest.TestCase):
    def test_table_id_is_stable(self) -> None:
        expected = "Table:Sales"
        self.assertEqual(object_id(obj_type=ObjectType.TABLE, name="Sales"), expected)
        self.assertEqual(object_id(obj_type=ObjectType.TABLE, name="Sales"), expected)

    def test_column_id_is_stable(self) -> None:
        expected = "Column:Sales.Amount"
        self.assertEqual(
            object_id(obj_type=ObjectType.COLUMN, table="Sales", name="Amount"),
            expected,
        )
        self.assertEqual(
            object_id(obj_type=ObjectType.COLUMN, table="Sales", name="Amount"),
            expected,
        )

    def test_measure_id_with_table(self) -> None:
        self.assertEqual(
            object_id(obj_type=ObjectType.MEASURE, table="Sales", name="Total Revenue"),
            "Measure:Sales.Total Revenue",
        )

    def test_measure_id_without_table(self) -> None:
        self.assertEqual(
            object_id(obj_type=ObjectType.MEASURE, name="Global KPI"),
            "Measure:Global KPI",
        )

    def test_relationship_id_is_stable(self) -> None:
        expected = "Rel:Sales.CustomerId->Customer.Id"
        kwargs = {
            "obj_type": ObjectType.RELATIONSHIP,
            "from_table": "Sales",
            "from_column": "CustomerId",
            "to_table": "Customer",
            "to_column": "Id",
        }
        self.assertEqual(object_id(**kwargs), expected)
        self.assertEqual(object_id(**kwargs), expected)

    def test_object_ref_canonical_id(self) -> None:
        ref = ObjectRef(type=ObjectType.COLUMN, table="Sales", name="Amount")
        self.assertEqual(ref.canonical_id(), "Column:Sales.Amount")

    def test_missing_required_field_raises(self) -> None:
        with self.assertRaises(ValueError):
            object_id(obj_type=ObjectType.COLUMN, name="Amount")


if __name__ == "__main__":
    unittest.main()
