import unittest

from aethel import scoring
from aethel.db import Event


def run(tag, *results):
    return Event(0, 0, "compare", "", "", {"tag": tag, "results": list(results)})


class ScoringTests(unittest.TestCase):
    def test_ranks_by_rating_then_count(self):
        events = [
            run("coding", {"model": "a", "outcome": "ok", "rating": 3, "total_ms": 1000, "cost_usd": 0.01},
                {"model": "b", "outcome": "ok", "rating": 5, "total_ms": 3000}),
            run("coding", {"model": "a", "outcome": "ok", "rating": 5, "total_ms": 2000, "cost_usd": 0.02},
                {"model": "b", "outcome": "error: boom"}),
            run("writing", {"model": "c", "outcome": "ok", "rating": 4}),
        ]
        board = scoring.leaderboard(events)
        self.assertEqual([r["model"] for r in board["coding"]], ["b", "a"])
        a = board["coding"][1]
        self.assertEqual((a["avg_rating"], a["rated"], a["runs"]), (4.0, 2, 2))
        self.assertAlmostEqual(a["cost_usd"], 0.03)
        self.assertEqual(a["avg_total_ms"], 1500)
        self.assertEqual(board["coding"][0]["success_rate"], 0.5)
        self.assertIsNone(board["coding"][0]["cost_usd"])

    def test_best_model_needs_a_rating(self):
        events = [run("coding", {"model": "a", "outcome": "ok"})]
        self.assertIsNone(scoring.best_model(events, "coding"))
        events.append(run("coding", {"model": "b", "outcome": "ok", "rating": 2}))
        self.assertEqual(scoring.best_model(events, "coding")["model"], "b")


if __name__ == "__main__":
    unittest.main()
