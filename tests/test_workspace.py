import json
import os
import tempfile
import unittest

from aethel import workspace


class WorkspaceTests(unittest.TestCase):
    def test_detects_test_commands(self):
        d = tempfile.mkdtemp()
        self.assertIsNone(workspace.detect_test_command(d))
        with open(os.path.join(d, "package.json"), "w") as f:
            json.dump({"scripts": {"test": "jest"}}, f)
        self.assertEqual(workspace.detect_test_command(d), "npm test")
        e = tempfile.mkdtemp()
        open(os.path.join(e, "Cargo.toml"), "w").close()
        self.assertEqual(workspace.detect_test_command(e), "cargo test")

    def test_env_files_are_parsed_and_masked(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, ".env"), "w") as f:
            f.write("# comment\nexport API_KEY='sk-1234567890'\nEMPTY=\nBAD LINE\n")
        [(name, pairs)] = workspace.env_files(d)
        self.assertEqual(name, ".env")
        self.assertEqual(pairs, [("API_KEY", "sk-1234567890"), ("EMPTY", "")])
        self.assertEqual(workspace.mask("sk-1234567890"), "sk•••••••••90")

    def test_run_tests_reports_pass_and_fail(self):
        d = tempfile.mkdtemp()
        self.assertTrue(workspace.run_tests(d, "true")["passed"])
        failed = workspace.run_tests(d, "echo boom; exit 3")
        self.assertEqual((failed["passed"], failed["exit_code"]), (False, 3))
        self.assertIn("boom", failed["output"])


if __name__ == "__main__":
    unittest.main()
