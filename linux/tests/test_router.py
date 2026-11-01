import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from gi.repository import GLib

from aethel import router


class FakeRouter(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        model = body["model"]
        if model == "broken":
            self._reply(400, "application/json", json.dumps({"error": {"message": "no such model"}}))
        elif model == "plain":
            payload = {
                "choices": [{"message": {"content": "whole answer"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            }
            self._reply(200, "application/json", json.dumps(payload))
        else:
            chunks = [
                {"choices": [{"delta": {"content": "Hel"}}]},
                {"choices": [{"delta": {"content": "lo"}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 5, "completion_tokens": 1}},
            ]
            lines = [": comment line\n"] + [f"data: {json.dumps(c)}\n\n" for c in chunks] + ["data: [DONE]\n\n"]
            self._reply(200, "text/event-stream", "".join(lines))

    def _reply(self, status, ctype, text):
        data = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ChatStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeRouter)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def stream(self, model):
        loop = GLib.MainLoop()
        text, end = [], {}

        def on_event(kind, payload):
            if kind == "delta":
                text.append(payload)
            else:
                end[kind] = payload
                loop.quit()

        router.ChatStream(self.base, model, "hi", 10, on_event).start()
        GLib.timeout_add(10000, loop.quit)
        loop.run()
        return "".join(text), end

    def test_sse_stream_with_usage(self):
        text, end = self.stream("good")
        self.assertEqual(text, "Hello")
        self.assertEqual(end["done"]["prompt_tokens"], 5)
        self.assertEqual(end["done"]["completion_tokens"], 1)
        self.assertIsNotNone(end["done"]["ttft_ms"])

    def test_plain_json_reply(self):
        text, end = self.stream("plain")
        self.assertEqual(text, "whole answer")
        self.assertEqual(end["done"]["completion_tokens"], 2)

    def test_http_error_is_a_sentence(self):
        _, end = self.stream("broken")
        self.assertEqual(end["error"], "The router answered HTTP 400 for broken: no such model")


if __name__ == "__main__":
    unittest.main()
