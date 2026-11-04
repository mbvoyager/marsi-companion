"""Estimated timing must stay honest when the server takes longer than expected."""
import unittest

from marsi_local.transmission import ResponseTimes, Transmission


class TransmissionTests(unittest.TestCase):
    def test_progress_is_estimated_and_never_claims_an_unfinished_reply_is_complete(self):
        pending = Transmission("chat", "A question", "", 100, 45)
        self.assertIn("ESTIMATE", pending.progress(100))
        self.assertIn("~0%", pending.progress(100))
        self.assertIn("~25s remaining", pending.progress(120))
        self.assertIn("~1s remaining", pending.progress(144.9))
        self.assertIn("a longer thought", pending.progress(180))
        self.assertIn("~95%", pending.progress(1000))
        self.assertNotIn("100%", pending.progress(1000))

    def test_estimates_use_bounded_recent_successes_and_separate_voice_cost(self):
        timings = ResponseTimes()
        initial_voice = timings.estimate("voice")
        for duration in (180, 160, 12, 14, 16, 18, 20):
            timings.observe("chat", duration)
        self.assertEqual(timings.estimate("chat"), 16)
        self.assertEqual(timings.estimate("voice"), initial_voice)
        timings.observe("rite", 0.1)
        self.assertEqual(timings.estimate("rite"), 5)
        timings.observe("voice", 500)
        self.assertEqual(timings.estimate("voice"), 180)


if __name__ == "__main__":
    unittest.main()
