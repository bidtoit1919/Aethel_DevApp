import os
import subprocess
import tempfile
import unittest

from aethel import gitinfo


def run(cwd, *args):
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        },
    )


def write(path, text):
    with open(path, "w") as f:
        f.write(text)


class GitInfoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.repo = os.path.join(self.tmp, "repo")
        os.mkdir(self.repo)

    def tearDown(self):
        self._tmp.cleanup()

    def init_with_commit(self):
        run(self.repo, "init", "-q", "-b", "main")
        write(os.path.join(self.repo, "a.txt"), "one\n")
        run(self.repo, "add", "a.txt")
        run(self.repo, "commit", "-q", "-m", "First commit")

    def add_upstream(self):
        remote = os.path.join(self.tmp, "remote.git")
        run(self.tmp, "init", "-q", "--bare", remote)
        run(self.repo, "remote", "add", "origin", remote)
        run(self.repo, "push", "-q", "-u", "origin", "main")
        return remote

    def test_not_a_repo(self):
        info = gitinfo.fetch(self.repo)
        self.assertEqual(info.kind, "no-repo")
        self.assertIn("not a git repository", info.message)

    def test_no_commits(self):
        run(self.repo, "init", "-q", "-b", "main")
        info = gitinfo.fetch(self.repo)
        self.assertEqual(info.kind, "no-commits")
        self.assertEqual(info.branch, "main")
        self.assertFalse(info.dirty)

    def test_clean_with_upstream(self):
        self.init_with_commit()
        self.add_upstream()
        info = gitinfo.fetch(self.repo)
        self.assertEqual(info.kind, "ok")
        self.assertEqual(info.branch, "main")
        self.assertFalse(info.dirty)
        self.assertEqual(info.subject, "First commit")
        self.assertEqual(len(info.last_hash), 7)
        self.assertTrue(info.has_upstream)
        self.assertFalse(info.upstream_gone)
        self.assertEqual(info.upstream, "origin/main")
        self.assertEqual((info.ahead, info.behind), (0, 0))

    def test_ahead_of_upstream(self):
        self.init_with_commit()
        self.add_upstream()
        write(os.path.join(self.repo, "a.txt"), "two\n")
        run(self.repo, "commit", "-q", "-am", "Second commit")
        info = gitinfo.fetch(self.repo)
        self.assertEqual((info.ahead, info.behind), (1, 0))
        self.assertEqual(info.subject, "Second commit")

    def test_dirty_no_upstream(self):
        self.init_with_commit()
        write(os.path.join(self.repo, "a.txt"), "changed\n")
        write(os.path.join(self.repo, "new.txt"), "untracked\n")
        info = gitinfo.fetch(self.repo)
        self.assertEqual(info.kind, "ok")
        self.assertTrue(info.dirty)
        self.assertEqual(info.changed_files, 2)
        self.assertFalse(info.has_upstream)

    def test_detached_head(self):
        self.init_with_commit()
        run(self.repo, "checkout", "-q", "--detach")
        info = gitinfo.fetch(self.repo)
        self.assertEqual(info.kind, "ok")
        self.assertTrue(info.detached)
        self.assertEqual(info.branch, "")

    def test_upstream_deleted_on_remote(self):
        self.init_with_commit()
        remote = self.add_upstream()
        run(remote, "branch", "-q", "-m", "main", "renamed")
        run(self.repo, "fetch", "-q", "--prune")
        info = gitinfo.fetch(self.repo)
        self.assertTrue(info.has_upstream)
        self.assertTrue(info.upstream_gone)

    def test_does_not_modify_repo(self):
        self.init_with_commit()
        write(os.path.join(self.repo, "a.txt"), "changed\n")
        before = self.snapshot()
        gitinfo.fetch(self.repo)
        self.assertEqual(before, self.snapshot())

    def snapshot(self):
        result = {}
        for root, _, files in os.walk(self.repo):
            for name in files:
                path = os.path.join(root, name)
                with open(path, "rb") as f:
                    result[path] = (os.stat(path).st_mtime_ns, f.read())
        return result


if __name__ == "__main__":
    unittest.main()
