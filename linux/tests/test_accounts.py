import json
import os
import tempfile
import unittest
from unittest import mock

from aethel import accounts, agents


class ReferenceTests(unittest.TestCase):
    def tearDown(self):
        accounts.configure_custom("")

    def test_parse_and_make(self):
        self.assertEqual(accounts.parse("anthropic:claude-x"), ("anthropic", "claude-x"))
        self.assertEqual(accounts.parse("signin:"), ("signin", ""))
        self.assertEqual(accounts.parse("local:llama3:8b"), ("local", "llama3:8b"))
        self.assertEqual(accounts.parse(None), ("", ""))
        self.assertEqual(accounts.make("xai", "grok-4"), "xai:grok-4")

    def test_older_router_models_fall_back_to_the_signin(self):
        self.assertEqual(accounts.parse("cx/gpt-5.6-luna-low"), ("custom", "cx/gpt-5.6-luna-low"))
        self.assertEqual(accounts.effective("cx/gpt-5.6-luna-low"), ("", ""))
        accounts.configure_custom("http://localhost:20128/v1", "OmniRoute")
        self.assertEqual(accounts.effective("cx/gpt-5.6-luna-low"), ("custom", "cx/gpt-5.6-luna-low"))

    def test_labels(self):
        self.assertEqual(accounts.label("openai:gpt-5"), "gpt-5 (OpenAI API)")
        self.assertEqual(accounts.label("signin:"), "sign-in default")
        claude = agents.Agent("c", "Claude Code", "claude", signin=agents.Signin("Claude"))
        self.assertEqual(accounts.project_label("signin:opus", claude), "Claude sign-in · opus")
        self.assertEqual(accounts.project_label(None, claude), "Claude sign-in")

    def test_only_api_models_are_callable(self):
        self.assertTrue(accounts.callable_ref("google:gemini-x"))
        self.assertFalse(accounts.callable_ref("signin:opus"))
        self.assertFalse(accounts.callable_ref(None))

    def test_signin_models_cannot_get_an_endpoint(self):
        with self.assertRaises(accounts.AccountError):
            accounts.endpoint("signin")


class ModelListTests(unittest.TestCase):
    def test_codex_catalogue_keeps_listed_models_in_priority_order(self):
        text = json.dumps({"models": [
            {"slug": "hidden", "visibility": "hide", "priority": 1},
            {"slug": "b", "visibility": "list", "priority": 9},
            {"slug": "a", "visibility": "list", "priority": 8},
        ]})
        self.assertEqual(accounts.parse_model_list(text, "codex"), ["a", "b"])

    def test_columns_and_lines(self):
        text = "MODEL                 NAME\ngemini-3.1-pro-high   Gemini 3.1 Pro (High)\n\nflash-x  Flash\n"
        self.assertEqual(accounts.parse_model_list(text, "columns"), ["gemini-3.1-pro-high", "flash-x"])
        self.assertEqual(accounts.parse_model_list("opencode/a\nanthropic/b\n", "lines"), ["opencode/a", "anthropic/b"])

    def test_status_detail(self):
        detail = accounts._status_detail(json.dumps({"authMethod": "claude.ai", "email": "me@example.com"}))
        self.assertEqual(detail, "Signed in as me@example.com with subscription")
        self.assertEqual(accounts._status_detail("Logged in using ChatGPT\n"), "Logged in using ChatGPT")


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.table = {a.id: a for a in agents.load()}

    def test_every_agent_has_a_way_in(self):
        for agent in self.table.values():
            self.assertTrue(agent.signin is not None or agent.routes, agent.id)
            self.assertTrue(agent.docs, agent.id)

    def test_official_signins(self):
        self.assertEqual(self.table["claude-code"].signin.login, ["auth", "login"])
        self.assertEqual(self.table["claude-code"].signin.status, ["auth", "status"])
        self.assertEqual(self.table["codex"].signin.login, ["login"])
        self.assertEqual(self.table["codex"].signin.status, ["login", "status"])
        self.assertEqual(self.table["grok"].signin.login, ["login"])
        self.assertEqual(self.table["antigravity"].signin.models_command, ["models"])

    def test_route_choice(self):
        claude, aider = self.table["claude-code"], self.table["aider"]
        self.assertEqual(claude.route_for("signin"), "signin")
        self.assertEqual(claude.route_for("anthropic", "anthropic"), "anthropic")
        self.assertIsNone(claude.route_for("openai"))
        self.assertEqual(claude.route_for("custom"), "custom")
        self.assertEqual(aider.route_for("mistral"), "compatible")
        self.assertEqual(aider.route_for("local"), "compatible")
        self.assertIsNone(aider.route_for("signin"))
        self.assertFalse(self.table["grok"].takes_model("xai"))

    def test_signin_launch_clears_competing_keys(self):
        launch = agents.build(self.table["claude-code"], "signin", "opus", prompt="P")
        self.assertEqual(launch.argv, ["claude", "--model", "opus", "P"])
        self.assertIn("ANTHROPIC_API_KEY", launch.unset)
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "stray"}):
            self.assertNotIn("ANTHROPIC_API_KEY", agents.environment(launch))

    def test_signin_default_model_adds_no_flag(self):
        self.assertEqual(agents.build(self.table["codex"], "signin", "").argv, ["codex"])

    def test_key_route_keeps_the_key_out_of_the_ledger(self):
        launch = agents.build(self.table["claude-code"], "anthropic", "claude-x", "https://api.anthropic.com/v1",
                              "sk-ant-secret")
        self.assertEqual(launch.env, {"ANTHROPIC_API_KEY": "sk-ant-secret"})
        self.assertEqual(launch.secret_env, ["ANTHROPIC_API_KEY"])
        self.assertNotIn("sk-ant-secret", json.dumps(launch.ledger_env()))
        self.assertNotIn("sk-ant-secret", json.dumps(launch.argv))

    def test_codex_openai_key_uses_its_own_provider(self):
        launch = agents.build(self.table["codex"], "openai", "gpt-x", "https://api.openai.com/v1", "sk-o")
        self.assertIn('model_providers.aethel-openai.env_key="AETHEL_OPENAI_API_KEY"', launch.argv)
        self.assertEqual(launch.env, {"AETHEL_OPENAI_API_KEY": "sk-o"})
        self.assertEqual(launch.argv[-2:], ["-m", "gpt-x"])

    def test_custom_endpoint_without_key(self):
        launch = agents.build(self.table["claude-code"], "custom", "m/x", "http://localhost:20128/v1")
        settings = json.loads(launch.argv[launch.argv.index("--settings") + 1])
        self.assertEqual(settings["env"]["ANTHROPIC_BASE_URL"], "http://localhost:20128")
        self.assertEqual(launch.env, {"ANTHROPIC_AUTH_TOKEN": agents.LOCAL_KEY})
        self.assertEqual(launch.secret_env, [])

    def test_opencode_compatible_route(self):
        launch = agents.build(self.table["opencode"], "compatible", "m/x", "https://api.x.ai/v1", "xai-key")
        provider = json.loads(launch.env["OPENCODE_CONFIG_CONTENT"])["provider"]["aethel"]
        self.assertEqual(provider["options"], {"baseURL": "https://api.x.ai/v1", "apiKey": "xai-key"})
        self.assertEqual(launch.secret_env, ["OPENCODE_CONFIG_CONTENT"])

    def test_unknown_placeholder_is_an_error(self):
        bad = agents.Agent("bad", "Bad", "bad", routes={"custom": agents.Route(args=["${nope}"])})
        with self.assertRaises(agents.AgentTableError):
            agents.build(bad, "custom", "m")


class SigninStatusTests(unittest.TestCase):
    def test_status_file_is_only_checked_for_existence(self):
        with tempfile.TemporaryDirectory() as home:
            agent = agents.Agent("g", "Grok Build", "sh", signin=agents.Signin(
                "Grok", status_file=os.path.join(home, "auth.json")))
            self.assertEqual(accounts.signin_status(agent).state, "out")
            open(os.path.join(home, "auth.json"), "w").close()
            self.assertEqual(accounts.signin_status(agent).state, "in")

    def test_status_command_exit_code(self):
        ok = agents.Agent("t", "T", "sh", signin=agents.Signin("T", status=["-c", "true"]))
        bad = agents.Agent("f", "F", "sh", signin=agents.Signin("F", status=["-c", "false"]))
        self.assertEqual(accounts.signin_status(ok).state, "in")
        self.assertEqual(accounts.signin_status(bad).state, "out")

    def test_missing_cli(self):
        agent = agents.Agent("x", "X", "aethel-no-such-cli", signin=agents.Signin("X"))
        self.assertEqual(accounts.signin_status(agent).state, "missing")


if __name__ == "__main__":
    unittest.main()
