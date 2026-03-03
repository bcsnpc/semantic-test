"""Unit tests for strict mode policy evaluation."""

from __future__ import annotations

import unittest

from semantic_test.core.model.coverage import strict_policy_violations


class StrictPolicyTests(unittest.TestCase):
    def test_unknown_patterns_trigger_violation(self) -> None:
        coverage_data = {"items": [], "summary": {"supported": 0, "partial": 0, "unsupported": 0}}
        failures = strict_policy_violations(
            coverage_data=coverage_data,
            unknown_patterns=[{"object_id": "Measure:KPI", "patterns": ["x"]}],
            unresolved_refs=[],
        )
        self.assertEqual(failures, ["unknown_patterns:1"])

    def test_unresolved_refs_trigger_violation(self) -> None:
        coverage_data = {"items": [], "summary": {"supported": 0, "partial": 0, "unsupported": 0}}
        failures = strict_policy_violations(
            coverage_data=coverage_data,
            unknown_patterns=[],
            unresolved_refs=[{"object_id": "Measure:KPI", "ref": "unresolved_measure:[X]"}],
        )
        self.assertEqual(failures, ["unresolved_refs:1"])

    def test_unsupported_critical_area_triggers_violation(self) -> None:
        coverage_data = {
            "summary": {"supported": 0, "partial": 0, "unsupported": 1},
            "items": [
                {
                    "area": "parser",
                    "pattern": "Locate PBIP/TMDL files",
                    "status": "unsupported",
                    "icon": "",
                    "notes": "",
                }
            ],
        }
        failures = strict_policy_violations(
            coverage_data=coverage_data,
            unknown_patterns=[],
            unresolved_refs=[],
            critical_areas={"parser"},
        )
        self.assertEqual(failures, ["unsupported_coverage:parser"])


if __name__ == "__main__":
    unittest.main()
