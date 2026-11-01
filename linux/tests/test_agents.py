import json
import os
import tempfile
import unittest

from aethel import agents, terminal

BASE = "http://localhost:20128/v1"


class AgentTableTests(unittest.TestCase):
    def setUp(self):
        self.table = {a.id: a for a in agents.load()}

    def test_spec_agents_present(self):
        self.assertTrue({"claude-code", "codex", "opencode"} <= set(self.table))
        for agent_id in ("claude-code", "codex", "opencode"):
            self.assertTrue(self.table[agent_id].verified)

    def test_every_entry_builds(self):
        for agent in self.table.values():
            argv, env = agents.build(agent, "m/x", BASE, prompt="P")
            self.assertEqual(argv[0], agent.command)
            self.assertTrue(agent.install and agent.docs, agent.id)

    def test_claude_code(self):
        argv, env = agents.build(self.table["claude-code"], "cx/gpt-5.6-terra", BASE)
        self.assertEqual(argv[:3], ["claude", "--model", "cx/gpt-5.6-terra"])
        self.assertEqual(argv[3], "--settings")
        self.assertEqual(
            json.loads(argv[4]),
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "http://localhost:20128",
                    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "cx/gpt-5.6-terra",
                    "CLAUDE_CODE_SUBAGENT_MODEL": "cx/gpt-5.6-terra",
                }
            },
        )
        self.assertEqual(env, {})

    def test_codex(self):
        argv, env = agents.build(self.table["codex"], "m/x", BASE + "/")
        self.assertIn('model_providers.aethel.base_url="http://localhost:20128/v1"', argv)
        self.assertEqual(argv[-2:], ["-m", "m/x"])
        self.assertEqual(env, {})

    def test_opencode(self):
        argv, env = agents.build(self.table["opencode"], "m/x", BASE)
        self.assertEqual(argv, ["opencode", "-m", "aethel/m/x"])
        config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
        provider = config["provider"]["aethel"]
        self.assertEqual(provider["options"]["baseURL"], BASE)
        self.assertEqual(provider["models"], {"m/x": {"name": "m/x"}})

    def test_unknown_placeholder_is_an_error(self):
        bad = agents.Agent("bad", "Bad", "bad", args=["${nope}"])
        with self.assertRaises(agents.AgentTableError):
            agents.build(bad, "m", BASE)

    def test_broken_table_is_an_error(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write("[x]\nname = 'no command'\n")
        self.addCleanup(os.unlink, f.name)
        with self.assertRaises(agents.AgentTableError):
            agents.load(f.name)

    def test_root_url(self):
        self.assertEqual(agents.root_url("http://h:1/v1/"), "http://h:1")
        self.assertEqual(agents.root_url("http://h:1/api"), "http://h:1/api")


class TerminalTests(unittest.TestCase):
    def test_command_puts_directory_and_argv_in_place(self):
        cmd = terminal.command("gnome-terminal", "/p", ["claude", "--model", "m"])
        self.assertEqual(
            cmd,
            ["gnome-terminal", "--wait", "--working-directory=/p", "--", "claude", "--model", "m"],
        )

    def test_every_detected_terminal_has_a_recipe(self):
        self.assertEqual(set(terminal.DETECTION_ORDER), set(terminal.TERMINALS))


if __name__ == "__main__":
    unittest.main()
