import plistlib
import tempfile
import unittest
from pathlib import Path

import install_sp9_launch_agent as installer


class LaunchAgentTests(unittest.TestCase):
    def test_weekday_schedule_and_send_time(self):
        payload = installer.build_plist("/tmp/python")

        self.assertEqual(payload["ProgramArguments"][0], "/tmp/python")
        self.assertIn("--skip-if-sent-today", payload["ProgramArguments"])
        self.assertIn("--attempts", payload["ProgramArguments"])
        self.assertEqual(
            sorted({item["Weekday"] for item in payload["StartCalendarInterval"]}),
            [1, 2, 3, 4, 5],
        )
        self.assertEqual(len(payload["StartCalendarInterval"]), 15)
        self.assertEqual(
            {(item["Hour"], item["Minute"]) for item in payload["StartCalendarInterval"]},
            {(10, 50), (11, 10), (11, 30)},
        )
        args = payload['ProgramArguments']
        self.assertEqual(args[args.index('--send-at') + 1], '11:50')

    def test_plist_is_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agent.plist"
            installer.write_plist(path, "/tmp/python")
            with path.open("rb") as handle:
                payload = plistlib.load(handle)

        self.assertEqual(payload["Label"], installer.LABEL)


if __name__ == "__main__":
    unittest.main()
