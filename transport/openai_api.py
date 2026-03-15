#!/usr/bin/env python3
"""Minimal OpenAI-compatible chat completions server."""

from __future__ import annotations

import json
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

HOST = "127.0.0.1"
PORT = 8000
DEFAULT_MODEL = "myqxw"


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if text:
                    parts.append(str(text))
            elif isinstance(item, str) and item:
                parts.append(item)
        return "".join(parts)
    return ""


def _extract_prompt(messages: Any) -> str:
    if not isinstance(messages, list):
        raise ValueError("messages 必须是数组")

    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        if message.get("role") != "user":
            continue
        text = _message_text(message.get("content"))
        if text.strip():
            return text.strip()
    raise ValueError("messages 中至少需要一条 user 消息")


class _OpenAIHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    scheduler = None
    server_model = DEFAULT_MODEL

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        print(f"[openai_api] {self.address_string()} - {format % args}")

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()
        self.close_connection = True

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/v1/models":
            self._write_json(HTTPStatus.NOT_FOUND, {"error": {"message": "Not found"}})
            return

        payload = {
            "object": "list",
            "data": [
                {
                    "id": self.server_model,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "myqxw",
                }
            ],
        }
        self._write_json(HTTPStatus.OK, payload)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self._write_json(HTTPStatus.NOT_FOUND, {"error": {"message": "Not found"}})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": {"message": "非法 Content-Length"}})
            return

        try:
            raw = self.rfile.read(content_length)
            request = json.loads(raw.decode("utf-8"))
            prompt = _extract_prompt(request.get("messages"))
        except Exception as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": {"message": str(exc)}})
            return

        request_model = str(request.get("model") or self.server_model)
        request_id = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())
        stream = bool(request.get("stream"))

        if stream:
            self._handle_stream(prompt, request_id, request_model, created)
            return

        try:
            reply = self.scheduler.chat(prompt)
        except Exception as exc:
            self._write_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": {"message": f"{type(exc).__name__}: {exc}"}},
            )
            return

        payload = {
            "id": request_id,
            "object": "chat.completion",
            "created": created,
            "model": request_model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": reply},
                    "finish_reason": "stop",
                }
            ],
        }
        self._write_json(HTTPStatus.OK, payload)

    def _handle_stream(self, prompt: str, request_id: str, request_model: str, created: int) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.close_connection = True

        def write_sse(payload: dict[str, Any] | str) -> None:
            if isinstance(payload, str):
                body = payload
            else:
                body = json.dumps(payload, ensure_ascii=False)
            self.wfile.write(f"data: {body}\n\n".encode("utf-8"))
            self.wfile.flush()

        try:
            first_chunk = {
                "id": request_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": request_model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant"},
                        "finish_reason": None,
                    }
                ],
            }
            write_sse(first_chunk)

            for text in self.scheduler.chat_stream(prompt):
                chunk = {
                    "id": request_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": request_model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": text},
                            "finish_reason": None,
                        }
                    ],
                }
                write_sse(chunk)

            final_chunk = {
                "id": request_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": request_model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    }
                ],
            }
            write_sse(final_chunk)
            write_sse("[DONE]")
        except Exception as exc:
            error_chunk = {
                "error": {
                    "message": f"{type(exc).__name__}: {exc}",
                }
            }
            write_sse(error_chunk)


class OpenAICompatServer:
    def __init__(
        self,
        scheduler,
        host: str = HOST,
        port: int = PORT,
        model: str = DEFAULT_MODEL,
    ) -> None:
        self.scheduler = scheduler
        self.host = host
        self.port = port
        self.model = model
        self._thread = threading.Thread(target=self._serve_loop, name="openai-api", daemon=True)
        self._httpd: ThreadingHTTPServer | None = None

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        httpd = self._httpd
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        self._thread.join(timeout=5)

    def _serve_loop(self) -> None:
        handler_cls = type(
            "MyQXWOpenAIHandler",
            (_OpenAIHandler,),
            {
                "scheduler": self.scheduler,
                "server_model": self.model,
            },
        )
        httpd = ThreadingHTTPServer((self.host, self.port), handler_cls)
        httpd.daemon_threads = True
        self._httpd = httpd
        print(f"OpenAICompat 已启动，监听 http://{self.host}:{self.port}")
        try:
            httpd.serve_forever(poll_interval=0.5)
        finally:
            self._httpd = None
