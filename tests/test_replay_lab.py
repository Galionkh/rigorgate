from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from galion.replay_lab import build_lab, build_replay_lab_data


class ReplayLabTests(unittest.TestCase):
    def test_replay_lab_is_deterministic_and_covers_all_decisions(self) -> None:
        first = build_replay_lab_data()
        second = build_replay_lab_data()
        self.assertEqual(first, second)
        self.assertEqual(first["source_posture"], "synthetic-demo-only")
        self.assertEqual(first["decision_status"], "NOT A BUY RECOMMENDATION")
        self.assertEqual(
            {case["correct_action"] for case in first["cases"]},
            {"research", "wait", "reject"},
        )

    def test_every_case_has_an_auditable_passport_and_hard_gates(self) -> None:
        report = build_replay_lab_data()
        for case in report["cases"]:
            self.assertGreaterEqual(len(case["gates"]), 4)
            self.assertTrue(case["passport"]["not_a_buy_recommendation"])
            self.assertFalse(case["passport"]["order_created"])
            self.assertIn("red_team", case)
            self.assertIn("missing_evidence", case)

    def test_build_lab_writes_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = build_lab(Path(tmp))
            parsed = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(parsed["schema"], "signalforge-replay-lab/v1")
            self.assertEqual(len(parsed["cases"]), 3)

    def test_every_contributor_quest_has_a_direct_start_url(self) -> None:
        report = build_replay_lab_data()
        for quest in report["contributor_quests"]:
            self.assertTrue(quest["href"].startswith(report["repository_url"]))
            self.assertIn("issues/new?template=", quest["href"])


if __name__ == "__main__":
    unittest.main()
