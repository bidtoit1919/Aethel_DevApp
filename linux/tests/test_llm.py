import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from gi.repository import GLib

from aethel import accounts, llm


class FakeProvider(BaseHTTPRequestHandler):
    seen_headers: list = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        FakeProvider.seen_headers.append(dict(self.headers))
        if self.path.startswith("/v1/models"):
            self._reply(200, "application/json", json.dumps({"data": [
                {"id": "chat-model", "context_length": 128000},
                {"id": "text-embedding-3-small"},
                {"id": "models/gemini-x"},
            ]}))
        else:
            self._reply(404, "application/json", "{}")

    def do_POST(self):
        FakeProvider.seen_headers.append(dict(self.headers))
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        model = body["model"]
        if self.path.endswith("/messages"):
            self._anthropic(model, body)
        elif model == "broken":
            self._reply(400, "application/json", json.dumps({"error": {"message": "no such model"}}))
        elif model == "refused":
            self._reply(401, "application/json", json.dumps({"error": {"message": "bad key"}}))
        elif model == "plain" or not body.get("stream"):
            payload = {"choices": [{"message": {"content": "whole answer"}}],
                       "usage": {"prompt_tokens": 3, "completion_tokens": 2}}
            self._reply(200, "application/json", json.dumps(payload))
        else:
            chunks = [
                {"choices": [{"delta": {"content": "Hel"}}]},
                {"choices": [{"delta": {"content": "lo"}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 5, "completion_tokens": 1}},
            ]
            lines = [": comment line\n"] + [f"data: {json.dumps(c)}\n\n" for c in chunks] + ["data: [DONE]\n\n"]
            self._reply(200, "text/event-stream", "".join(lines))

    def _anthropic(self, model, body):
        if not body.get("stream"):
            payload = {"content": [{"type": "text", "text": "claude says hi"}],
                       "usage": {"input_tokens": 7, "output_tokens": 4}}
            self._reply(200, "application/json", json.dumps(payload))
            return
        events = [
            ("message_start", {"type": "message_start", "message": {"usage": {"input_tokens": 9}}}),
            ("content_block_delta", {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Bon"}}),
            ("content_block_delta", {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "jour"}}),
            ("message_delta", {"type": "message_delta", "usage": {"output_tokens": 2}}),
            ("message_stop", {"type": "message_stop"}),
        ]
        text = "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events)
        self._reply(200, "text/event-stream", text)

    def _reply(self, status, ctype, text):
        data = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class LlmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeProvider)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def endpoint(self, wire="openai", key="sk-test"):
        return mock.patch.object(accounts, "endpoint",
                                 lambda provider: accounts.Endpoint(self.base, key, wire, "Fake"))

    def stream(self, ref, wire="openai"):
        loop = GLib.MainLoop()
        text, end = [], {}

        def on_event(kind, payload):
            if kind == "delta":
                text.append(payload)
            else:
                end[kind] = payload
                loop.quit()

        with self.endpoint(wire):
            llm.ChatStream(ref, "hi", 10, on_event).start()
            GLib.timeout_add(10000, loop.quit)
            loop.run()
        return "".join(text), end

    def test_openai_stream_with_usage_and_bearer_key(self):
        FakeProvider.seen_headers.clear()
        text, end = self.stream("openai:good")
        self.assertEqual(text, "Hello")
        self.assertEqual((end["done"]["prompt_tokens"], end["done"]["completion_tokens"]), (5, 1))
        self.assertIsNotNone(end["done"]["ttft_ms"])
        self.assertEqual(FakeProvider.seen_headers[-1].get("Authorization"), "Bearer sk-test")

    def test_anthropic_stream(self):
        FakeProvider.seen_headers.clear()
        text, end = self.stream("anthropic:claude-x", wire="anthropic")
        self.assertEqual(text, "Bonjour")
        self.assertEqual((end["done"]["prompt_tokens"], end["done"]["completion_tokens"]), (9, 2))
        headers = FakeProvider.seen_headers[-1]
        self.assertEqual(headers.get("x-api-key"), "sk-test")
        self.assertEqual(headers.get("anthropic-version"), "2023-06-01")

    def test_plain_json_reply(self):
        text, end = self.stream("openai:plain")
        self.assertEqual(text, "whole answer")

    def test_http_error_is_a_sentence(self):
        _, end = self.stream("openai:broken")
        self.assertEqual(end["error"], "broken (OpenAI API) answered HTTP 400: no such model")

    def test_refused_key_points_to_settings(self):
        _, end = self.stream("openai:refused")
        self.assertIn("Settings > Accounts", end["error"])

    def test_signin_models_cannot_be_called(self):
        with self.assertRaises(llm.CompletionError):
            llm.complete("signin:opus", "hi")

    def test_complete_both_wires(self):
        with self.endpoint("openai"):
            self.assertEqual(llm.complete("openai:plain", "hi")[0], "whole answer")
        with self.endpoint("anthropic"):
            text, metrics = llm.complete("anthropic:c", "hi")
        self.assertEqual(text, "claude says hi")
        self.assertEqual(metrics["completion_tokens"], 4)

    def test_model_list_filters_non_chat_models(self):
        models = accounts.list_models("openai", "sk-test", self.base)
        self.assertEqual([m["id"] for m in models], ["chat-model", "gemini-x"])
        self.assertEqual(models[0]["context"], 128000)


if __name__ == "__main__":
    unittest.main()
