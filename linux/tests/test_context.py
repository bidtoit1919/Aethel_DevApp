import json
import os
import tempfile
import unittest
from unittest import mock

from aethel import agents, context, transcripts


class PromptTests(unittest.TestCase):
    def test_empty_means_open_session(self):
        self.assertEqual(context.build_prompt("p", None, []), "")

    def test_sections_in_order(self):
        prompt = context.build_prompt("demo", "Fix it", [
            {"kind": "file", "path": "src/a.py"},
            {"kind": "issue", "number": 3, "title": "Crash", "body": "Stack trace"},
            {"kind": "summary", "event_id": 1, "title": "yesterday", "text": "Did X"},
        ])
        self.assertLess(prompt.index("## Task"), prompt.index("## Read these files first"))
        self.assertIn("- src/a.py", prompt)
        self.assertIn("## GitHub Issue #3: Crash\nStack trace", prompt)
        self.assertIn("Handoff from an earlier session (yesterday)\nDid X", prompt)

    def test_huge_context_is_trimmed_under_argv_limit(self):
        items = [{"kind": "note", "event_id": i, "text": "x" * 20000} for i in range(10)]
        prompt = context.build_prompt("p", "t", items)
        self.assertLessEqual(len(prompt), context.MAX_PROMPT + 100)

    def test_agent_receives_prompt_and_init(self):
        table = {a.id: a for a in agents.load()}
        argv = agents.build(table["opencode"], "signin", "m", prompt="Hello").argv
        self.assertEqual(argv[-2:], ["--prompt", "Hello"])
        argv = agents.build(table["codex"], "signin", "", init=True).argv
        self.assertEqual(argv[:4], ["codex", "exec", "--sandbox", "workspace-write"])
        self.assertTrue(argv[-1].startswith("Generate a file named AGENTS.md"))
        argv = agents.build(table["claude-code"], "anthropic", "m", "https://api.anthropic.com/v1", "k", init=True).argv
        self.assertEqual(argv[-4:], ["-p", "/init", "--permission-mode", "acceptEdits"])

    def test_clean_environ_strips_host_session_only(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}, clear=False):
            os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
            os.environ.pop("CLAUDE_CODE_ENTRYPOINT", None)
            self.assertIn("ANTHROPIC_API_KEY", agents.clean_environ())
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k", "CLAUDE_CODE_SESSION_ID": "s"}):
            env = agents.clean_environ()
            self.assertNotIn("ANTHROPIC_API_KEY", env)
            self.assertNotIn("CLAUDE_CODE_SESSION_ID", env)


class ClaudeTranscriptTests(unittest.TestCase):
    def test_reads_messages_tools_and_dedupes_streamed_records(self):
        home = tempfile.mkdtemp()
        cwd = "/work/my_app"
        folder = os.path.join(home, ".claude/projects/-work-my-app")
        os.makedirs(folder)
        records = [
            {"type": "user", "message": {"role": "user", "content": "Add tests"}},
            {"type": "assistant", "message": {"id": "m1", "role": "assistant", "model": "gpt-x",
                                              "content": [{"type": "text", "text": "Sure"}],
                                              "usage": {"input_tokens": 10, "output_tokens": 2}}},
            {"type": "assistant", "message": {"id": "m1", "role": "assistant", "model": "gpt-x",
                                              "content": [{"type": "tool_use", "name": "Edit"}],
                                              "usage": {"input_tokens": 10, "output_tokens": 5}}},
        ]
        with open(os.path.join(folder, "s.jsonl"), "w") as f:
            f.write("\n".join(json.dumps(r) for r in records))
        with mock.patch.dict(os.environ, {"HOME": home}):
            t = transcripts.load("claude", cwd, 0)
        self.assertEqual(t.messages, [("user", "Add tests"), ("assistant", "Sure")])
        self.assertEqual(t.tool_calls, {"Edit": 1})
        self.assertEqual(t.models, {"gpt-x": 1})
        self.assertEqual((t.input_tokens, t.output_tokens), (10, 5))
        self.assertIsNone(transcripts.load("claude", "/elsewhere", 0))


if __name__ == "__main__":
    unittest.main()
