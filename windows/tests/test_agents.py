import os
import tempfile
import unittest

from aethel import agents, terminal

BASE = "http://localhost:20128/v1"


class AgentTableTests(unittest.TestCase):
    def setUp(self):
        self.table = {a.id: a for a in agents.load()}

    def test_spec_agents_present(self):
        self.assertTrue({"claude-code", "codex", "opencode", "antigravity", "grok", "gemini-cli"} <= set(self.table))
        for agent_id in ("claude-code", "codex", "opencode"):
            self.assertTrue(self.table[agent_id].verified)

    def test_every_route_builds(self):
        for agent in self.table.values():
            self.assertTrue(agent.install or agent.docs, agent.id)
            routes = list(agent.routes) + (["signin"] if agent.signin else [])
            for route in routes:
                launch = agents.build(agent, route, "m/x", BASE, "key", prompt="P")
                self.assertEqual(launch.argv[0], agent.command, (agent.id, route))

    def test_broken_table_is_an_error(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write("[x]\nname = 'no command'\n")
        self.addCleanup(os.unlink, f.name)
        with self.assertRaises(agents.AgentTableError):
            agents.load(f.name)

    def test_signin_needs_an_account_name(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write("[x]\ncommand = 'x'\n[x.signin]\nlogin = []\n")
        self.addCleanup(os.unlink, f.name)
        with self.assertRaises(agents.AgentTableError):
            agents.load(f.name)

    def test_root_url(self):
        self.assertEqual(agents.root_url("http://h:1/v1/"), "http://h:1")
        self.assertEqual(agents.root_url("http://h:1/api"), "http://h:1/api")


class TerminalTests(unittest.TestCase):
    def test_console_window_is_always_available(self):
        self.assertEqual(terminal.installed(), [terminal.CONSOLE])
        self.assertEqual(terminal.pick("gnome-terminal", None), terminal.CONSOLE)
        self.assertEqual(terminal.label(terminal.CONSOLE), "Console window")
        self.assertEqual(terminal.label(terminal.EMBEDDED), "Inside Aethel")


if __name__ == "__main__":
    unittest.main()
