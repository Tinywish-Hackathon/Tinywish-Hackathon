import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from utils import tracker


class TrackerTests(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        tracker.init_tracker(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    def test_log_and_get_recent_applications(self):
        tracker.log_application(
            "Post-Matric OBC Scholarship",
            "NSP",
            "government",
            "handoff_completed",
            profile_name="Atharv",
        )
        tracker.log_application(
            "Open Merit Scholarship",
            "Buddy4Study",
            "private",
            "started",
        )

        recent = tracker.get_recent_applications()

        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[0]["scheme_name"], "Open Merit Scholarship")
        self.assertEqual(recent[1]["scheme_name"], "Post-Matric OBC Scholarship")
        self.assertEqual(recent[1]["profile_name"], "Atharv")

    def test_print_application_history_outputs_table(self):
        tracker.log_application(
            "Post-Matric OBC Scholarship",
            "NSP",
            "government",
            "handoff_completed",
        )

        stream = io.StringIO()
        with redirect_stdout(stream):
            tracker.print_application_history()

        output = stream.getvalue()
        self.assertIn("Application History", output)
        self.assertIn("Post-Matric OBC Scholarship", output)
        self.assertIn("Portal: NSP | Status: handoff_completed", output)


if __name__ == "__main__":
    unittest.main()
