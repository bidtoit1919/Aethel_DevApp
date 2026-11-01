import os
import subprocess
import tempfile
import unittest

from aethel import agents, gitinfo, ledger, terminal
from aethel.db import Project

ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=ENV)


class SessionChangesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self._tmp.name, "repo")
        os.mkdir(self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        with open(os.path.join(self.repo, "a.txt"), "w") as f:
            f.write("one\n")
        git(self.repo, "add", "a.txt")
        git(self.repo, "commit", "-q", "-m", "start")

    def tearDown(self):
        self._tmp.cleanup()

    def test_commits_and_edits_since_launch(self):
        start = gitinfo.head_state(self.repo)
        remote = os.path.join(self._tmp.name, "remote.git")
        git(self._tmp.name, "init", "-q", "--bare", remote)
        git(self.repo, "remote", "add", "origin", remote)
        git(self.repo, "push", "-q", "-u", "origin", "main")
        with open(os.path.join(self.repo, "a.txt"), "a") as f:
            f.write("two\n")
        git(self.repo, "commit", "-q", "-am", "during session")
        with open(os.path.join(self.repo, "b.txt"), "w") as f:
            f.write("new\n")
        end = gitinfo.session_changes(self.repo, start["head"])
        self.assertEqual(end["new_commits"], 1)
        self.assertEqual(end["unpushed_commits"], 1)
        self.assertEqual(end["untracked_files"], 1)
        self.assertIn("1 file changed", end["diff_shortstat"])
        summary = ledger.end_summary(
            {"duration_seconds": 125, "git_end": end}
        )
        self.assertEqual(
            summary,
            "Session ended after 2 minutes · 1 file changed, 1 insertion(+) · "
            "1 new commit · 1 not on any remote",
        )

    def test_no_remote_is_said_plainly(self):
        start = gitinfo.head_state(self.repo)
        end = gitinfo.session_changes(self.repo, start["head"])
        summary = ledger.end_summary({"duration_seconds": 10, "git_end": end})
        self.assertIn("no changes to tracked files", summary)
        self.assertIn("no remote configured", summary)

    def test_not_a_repo(self):
        plain = os.path.join(self._tmp.name, "plain")
        os.mkdir(plain)
        self.assertEqual(gitinfo.head_state(plain), {"repo": False})
        summary = ledger.end_summary(
            {"duration_seconds": 4000, "git_end": gitinfo.session_changes(plain, None)}
        )
        self.assertEqual(summary, "Session ended after 1 h 06 min · not a git repo")


class PlanLaunchTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Project(1, "p", self._tmp.name, "", preferred_model="m/x")
        self.agent = agents.Agent("sh", "Shell", "sh")

    def tearDown(self):
        self._tmp.cleanup()

    def plan(self, **kw):
        args = dict(
            project=self.project,
            agent_table=[self.agent],
            agent_error=None,
            agent_id="sh",
            global_terminal=None,
            base_url="http://r/v1",
        )
        args.update(kw)
        return ledger.plan_launch(**args)

    def test_ready(self):
        plan = self.plan()
        if "problem" in plan and "terminal" in plan["problem"]:
            self.skipTest("no terminal emulator installed")
        self.assertEqual(plan["model"], "m/x")
        self.assertIn("Opens Shell with m/x", plan["summary"])

    def test_embedded_by_default_when_available(self):
        plan = self.plan(embedded=True)
        self.assertEqual(plan["terminal"], terminal.EMBEDDED)
        self.assertIn("inside Aethel", plan["summary"])

    def test_external_choice_wins_over_embedded(self):
        self.project.preferred_terminal = "aethel-no-such-terminal"
        plan = self.plan(embedded=True)
        self.assertNotEqual(plan.get("terminal"), terminal.EMBEDDED)

    def test_embedded_choice_falls_back_without_widget(self):
        self.project.preferred_terminal = terminal.EMBEDDED
        plan = self.plan(embedded=False)
        self.assertNotEqual(plan.get("terminal"), terminal.EMBEDDED)

    def test_missing_model(self):
        self.project.preferred_model = None
        self.assertIn("preferred model", self.plan()["problem"])

    def test_agent_not_installed(self):
        missing = agents.Agent("x", "Ghost", "aethel-no-such-binary")
        plan = self.plan(agent_table=[missing], agent_id="x")
        self.assertIn("Ghost is not installed", plan["problem"])

    def test_folder_gone(self):
        self.project.path = os.path.join(self._tmp.name, "gone")
        self.assertIn("no longer exists", self.plan()["problem"])


if __name__ == "__main__":
    unittest.main()
