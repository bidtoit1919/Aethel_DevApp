import os
import stat
import tempfile
import unittest
from unittest import mock

from aethel import connectors, winplat


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.bin = tempfile.mkdtemp()

    def _exe(self, name, text="#!/bin/sh\n"):
        path = os.path.join(self.bin, name)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        return path

    def test_npm_shim_becomes_node_and_script(self):
        script_dir = os.path.join(self.bin, "node_modules", "@openai", "codex", "bin")
        os.makedirs(script_dir)
        script = os.path.join(script_dir, "codex.js")
        open(script, "w").close()
        # The last line of a real npm cmd-shim.
        shim = self._exe("codex.cmd", '@ECHO off\r\n"%_prog%"  "%dp0%\\node_modules\\@openai\\codex\\bin\\codex.js" %*\r\n')
        self.assertEqual(winplat._npm_shim_target(shim), script)

    def test_unknown_program_is_left_alone(self):
        self.assertEqual(winplat.resolve_argv(["aethel-no-such-tool", "x"]), ["aethel-no-such-tool", "x"])

    def test_program_is_resolved_on_path(self):
        self._exe("aethel-tool")
        argv = winplat.resolve_argv(["aethel-tool", "--flag"], {"PATH": self.bin})
        self.assertEqual(argv, [os.path.join(self.bin, "aethel-tool"), "--flag"])


class PromptTests(unittest.TestCase):
    def test_short_prompt_is_kept(self):
        self.assertEqual(winplat.fit_prompt("hello"), "hello")

    def test_long_prompt_goes_to_a_file(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"XDG_DATA_HOME": home}):
            text = "x" * (winplat.PROMPT_ARG_LIMIT + 1)
            short = winplat.fit_prompt(text)
            self.assertLess(len(short), 1000)
            path = short.split("saved them to ")[1].split(". Read")[0]
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), text)


class MiscTests(unittest.TestCase):
    def test_same_path_ignores_separators(self):
        self.assertTrue(winplat.same_path("/a/b/", "/a/b"))
        self.assertFalse(winplat.same_path("/a/b", None))

    def test_data_dir_follows_xdg_override(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"XDG_DATA_HOME": home}):
            self.assertEqual(winplat.data_dir(), os.path.join(home, "aethel"))

    def test_total_ram_is_positive(self):
        self.assertGreater(winplat.total_ram(), 0)

    def test_dev_secret_store_round_trip(self):
        if winplat.IS_WINDOWS:
            self.skipTest("uses the real Credential Manager on Windows")
        winplat.set_secret("/p", "API_KEY", "v")
        self.assertEqual(winplat.secret_names("/p"), ["API_KEY"])
        self.assertEqual(winplat.get_secret("/p", "API_KEY"), "v")
        winplat.delete_secret("/p", "API_KEY")
        self.assertEqual(winplat.secret_names("/p"), [])

    def test_oversized_secret_is_refused(self):
        with self.assertRaises(winplat.SecretStoreError):
            winplat.set_secret("/p", "BIG", "x" * (winplat.MAX_SECRET_BYTES + 1))

    def test_npx_servers_get_the_windows_wrapper(self):
        server = {"name": "io.example/files", "packages": [{"registryType": "npm", "identifier": "@x/files"}]}
        with mock.patch.object(winplat, "IS_WINDOWS", True):
            command, _ = connectors.claude_add_command(server)
        self.assertEqual(command[-5:], ["cmd", "/c", "npx", "-y", "@x/files"])


@unittest.skipUnless(winplat.IS_WINDOWS, "Credential Manager exists only on Windows")
class CredentialManagerTests(unittest.TestCase):
    def test_round_trip(self):
        project = "C:\\\\aethel-test-project"
        winplat.set_secret(project, "AETHEL_TEST", "value ü")
        try:
            self.assertIn("AETHEL_TEST", winplat.secret_names(project))
            self.assertEqual(winplat.get_secret(project, "AETHEL_TEST"), "value ü")
        finally:
            winplat.delete_secret(project, "AETHEL_TEST")
        self.assertIsNone(winplat.get_secret(project, "AETHEL_TEST"))


if __name__ == "__main__":
    unittest.main()
