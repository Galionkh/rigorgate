from __future__ import annotations

import unittest

from galion.demo import build_demo_report


class DemoTests(unittest.TestCase):
    def test_offline_demo_is_deterministic_and_cannot_be_a_buy_recommendation(self) -> None:
        first = build_demo_report()
        second = build_demo_report()
        self.assertEqual(first, second)
        self.assertEqual(first["source_posture"], "synthetic-demo-only")
        self.assertEqual(first["decision_status"], "NOT A BUY RECOMMENDATION")
        self.assertGreaterEqual(len(first["research_queue"]), 1)


if __name__ == "__main__":
    unittest.main()
