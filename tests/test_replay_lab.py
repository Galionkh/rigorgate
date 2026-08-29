from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rigorgate.replay_lab import build_lab, build_replay_lab_data


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
            self.assertEqual(parsed["schema"], "rigorgate-replay-lab/v1")
            self.assertEqual(len(parsed["cases"]), 3)

    def test_every_contributor_quest_has_a_direct_start_url(self) -> None:
        report = build_replay_lab_data()
        self.assertEqual(
            {quest["track"] for quest in report["contributor_quests"]},
            {"RESEARCHER", "FIRST PR", "CORE ENGINEERING"},
        )
        for quest in report["contributor_quests"]:
            self.assertTrue(quest["href"].startswith(report["repository_url"]))
            self.assertIn("/issues", quest["href"])

    def test_researcher_track_accepts_a_no_code_counterexample(self) -> None:
        report = build_replay_lab_data()
        researcher = next(
            quest for quest in report["contributor_quests"] if quest["track"] == "RESEARCHER"
        )
        self.assertEqual(researcher["label"], "no code")
        self.assertIn("template=counterexample.yml", researcher["href"])

    def test_lab_surfaces_the_active_case_challenge_action(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "lab" / "index.html").read_text(encoding="utf-8")
        script = (root / "lab" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="challenge-case-link"', html)
        self.assertIn('challengeUrl.searchParams.set("template", "counterexample.yml")', script)
        self.assertIn('challengeUrl.searchParams.set("title", challengeTitle)', script)

    def test_lab_explains_the_product_before_the_replay_challenge(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "lab" / "index.html").read_text(encoding="utf-8")
        script = (root / "lab" / "app.js").read_text(encoding="utf-8")
        self.assertIn("From thousands of stocks", html)
        self.assertIn('id="engine"', html)
        self.assertIn('id="research-queue-body"', html)
        self.assertLess(html.index('id="engine"'), html.index('id="challenge"'))
        self.assertIn("function renderResearchQueue(cases)", script)
        self.assertIn("renderResearchQueue(state.data.cases)", script)


if __name__ == "__main__":
    unittest.main()
