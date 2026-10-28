from __future__ import annotations

import unittest

from benchmarks.score_exploration_protocol import ScorecardError, build_scorecard


class ExplorationScorecardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = {
            "cases": [
                {"id": "clean", "seeds": [1], "expected": {"static": {"finding": False}, "adaptive": {"finding": False}}},
                {"id": "easy-defect", "seeds": [1], "expected": {"static": {"finding": True}, "adaptive": {"finding": True}}},
                {"id": "adaptive-only", "seeds": [1], "expected": {"static": {"finding": False}, "adaptive": {"finding": True}}},
            ]
        }
        rows = []
        observed = {
            ("clean", "static"): False, ("clean", "adaptive"): True,
            ("easy-defect", "static"): True, ("easy-defect", "adaptive"): True,
            ("adaptive-only", "static"): False, ("adaptive-only", "adaptive"): True,
        }
        for (case_id, mode), finding in observed.items():
            rows.append({"case_id": case_id, "mode": mode, "seed": 1, "round": 1, "finding": finding})
        self.report = {"results": rows, "settings": {"rounds": 1}, "passed": True}

    def test_defect_missed_by_static_counts_as_false_negative(self) -> None:
        result = build_scorecard(self.manifest, self.report)
        static = result["modes"]["static"]
        adaptive = result["modes"]["adaptive"]
        self.assertEqual(static["false_negatives"], 1)
        self.assertEqual(static["true_positives"], 1)
        self.assertEqual(adaptive["true_positives"], 2)
        self.assertEqual(adaptive["false_positives"], 1)
        self.assertEqual(result["case_labels"]["adaptive-only"], "seeded_defect")

    def test_rejects_incomplete_report(self) -> None:
        self.report["results"].pop()
        with self.assertRaises(ScorecardError):
            build_scorecard(self.manifest, self.report)

    def test_refuses_failed_protocol(self) -> None:
        self.report["passed"] = False
        with self.assertRaises(ScorecardError):
            build_scorecard(self.manifest, self.report)


if __name__ == "__main__":
    unittest.main()
