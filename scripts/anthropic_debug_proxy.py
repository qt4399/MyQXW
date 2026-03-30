#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import requests

DEFAULT_LISTEN_HOST = "127.0.0.1"
DEFAULT_LISTEN_PORT = 18080
DEFAULT_UPSTREAM_BASE_URL = "https://newapis.xyz"
DEFAULT_TIMEOUT = 600
DEFAULT_LOG_PATH = "logs/anthropic_debug_proxy.log"

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}
SENSITIVE_HEADERS = {"authorization", "x-api-key", "api-key"}


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def truncate(text: Any, limit: int = 600) -> str:
    value = str(text)
    if len(value) <= limit:
        return value
    return f"{value[:limit]} ...<truncated {len(value) - limit} chars>"


def mask(value: str) -> str:
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:6]}...{value[-4:]}"


class Logger:
    def __init__(self, log_path: str) -> None:
        self.path = Path(log_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, text: str = "") -> None:
        print(text)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(text)
            f.write("\n")


LOGGER: Logger | None = None


def log(text: str = "") -> None:
    if LOGGER is None:
        print(text)
        return
    LOGGER.write(text)


def sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in headers.items():
        result[key] = mask(value) if key.lower() in SENSITIVE_HEADERS else value
    return result


def summarize_content(content: Any) -> Any:
    if isinstance(content, str):
        return truncate(content)
    if not isinstance(content, list):
        return content

    output: list[Any] = []
    for item in content:
        if isinstance(item, str):
            output.append(truncate(item))
            continue
        if not isinstance(item, dict):
            output.append(item)
            continue
        item_type = item.get("type")
        if item_type in {"text", "input_text"}:
            output.append({"type": item_type, "text": truncate(item.get("text", ""))})
            continue
        if item_type in {"image", "input_image", "image_url"}:
            output.append({"type": item_type, "detail": "[image omitted]"})
            continue
        copy = {}
        for key, value in item.items():
            if key in {"data", "source", "image_url"}:
                copy[key] = "[omitted]"
            elif isinstance(value, str):
                copy[key] = truncate(value)
            else:
                copy[key] = value
        output.append(copy)
    return output


def sanitize_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        result: dict[str, Any] = {}
        for key, value in payload.items():
            if key == "system":
                result[key] = summarize_content(value)
            elif key in {"messages", "input"} and isinstance(value, list):
                items: list[Any] = []
                for item in value:
                    if isinstance(item, dict) and "content" in item:
                        copy = dict(item)
                        copy["content"] = summarize_content(item.get("content"))
                        items.append(copy)
                    else:
                        items.append(sanitize_payload(item))
                result[key] = items
            elif key == "tools" and isinstance(value, list):
                items = []
                for tool in value:
                    if isinstance(tool, dict):
                        copy = dict(tool)
                        if "input_schema" in copy:
                            copy["input_schema"] = "[schema omitted]"
                        items.append(copy)
                    else:
                        items.append(tool)
                result[key] = items
            elif isinstance(value, str):
                result[key] = "[data url omitted]" if value.startswith("data:") else truncate(value)
            else:
                result[key] = sanitize_payload(value)
        return result
    if isinstance(payload, list):
        return [sanitize_payload(item) for item in payload]
    return payload


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    upstream_base_url = DEFAULT_UPSTREAM_BASE_URL
    timeout = DEFAULT_TIMEOUT
    session = requests.Session()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        log(f"[proxy] {self.address_string()} - {format % args}")

    def do_GET(self) -> None:  # noqa: N802
        self._proxy()

    def do_POST(self) -> None:  # noqa: N802
        self._proxy()

    def do_PUT(self) -> None:  # noqa: N802
        self._proxy()

    def do_PATCH(self) -> None:  # noqa: N802
        self._proxy()

    def do_DELETE(self) -> None:  # noqa: N802
        self._proxy()

    def _proxy(self) -> None:
        body = self._read_body()
        headers = self._build_forward_headers()
        self._log_request(headers, body)

        upstream_url = f"{self.upstream_base_url.rstrip('/')}{self.path}"
        try:
            response = self.session.request(
                method=self.command,
                url=upstream_url,
                headers=headers,
                data=body if body else None,
                stream=True,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            self._write_error(502, f"Upstream request failed: {type(exc).__name__}: {exc}")
            return

        try:
            self._log_response(response)
            self._relay_response(response)
        finally:
            response.close()

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        return self.rfile.read(length) if length > 0 else b""

    def _build_forward_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        for key, value in self.headers.items():
            lower = key.lower()
            if lower in HOP_BY_HOP_HEADERS or lower == "host":
                continue
            headers[key] = value
        return headers

    def _log_request(self, headers: dict[str, str], body: bytes) -> None:
        log()
        log("=" * 80)
        log(f"[{now()}] inbound {self.command} {self.path}")
        log(f"[{now()}] headers={json.dumps(sanitize_headers(headers), ensure_ascii=False, indent=2)}")
        if not body:
            log(f"[{now()}] body=<empty>")
            return
        content_type = self.headers.get("Content-Type", "")
        if "application/json" in content_type:
            try:
                payload = json.loads(body.decode('utf-8'))
            except Exception as exc:  # noqa: BLE001
                log(f"[{now()}] body_decode_error={type(exc).__name__}: {exc}")
                log(truncate(body.decode('utf-8', errors='replace')))
                return
            clean = sanitize_payload(payload)
            log(f"[{now()}] payload=\n{json.dumps(clean, ensure_ascii=False, indent=2)}")
            return
        log(f"[{now()}] raw_body={truncate(body.decode('utf-8', errors='replace'))}")

    def _log_response(self, response: requests.Response) -> None:
        log(f"[{now()}] upstream_status={response.status_code}")
        log(f"[{now()}] upstream_headers={json.dumps(sanitize_headers(dict(response.headers)), ensure_ascii=False, indent=2)}")
        if "text/event-stream" in response.headers.get("Content-Type", ""):
            log(f"[{now()}] upstream_body=<stream omitted>")
            return
        body = response.content.decode("utf-8", errors="replace")
        log(f"[{now()}] upstream_body={truncate(body)}")

    def _relay_response(self, response: requests.Response) -> None:
        is_stream = "text/event-stream" in response.headers.get("Content-Type", "")
        self.send_response(response.status_code)
        for key, value in response.headers.items():
            lower = key.lower()
            if lower in HOP_BY_HOP_HEADERS:
                continue
            if is_stream and lower == "content-length":
                continue
            self.send_header(key, value)
        self.send_header("Connection", "close")
        self.end_headers()

        try:
            for chunk in response.iter_content(chunk_size=4096):
                if not chunk:
                    continue
                self.wfile.write(chunk)
                self.wfile.flush()
        except BrokenPipeError:
            pass
        finally:
            self.close_connection = True

    def _write_error(self, status: int, message: str) -> None:
        data = json.dumps({"error": {"message": message}}, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)
        self.wfile.flush()
        self.close_connection = True


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-host", default=os.environ.get("PROXY_LISTEN_HOST", DEFAULT_LISTEN_HOST))
    parser.add_argument("--listen-port", type=int, default=int(os.environ.get("PROXY_LISTEN_PORT", DEFAULT_LISTEN_PORT)))
    parser.add_argument("--upstream-base-url", default=os.environ.get("UPSTREAM_BASE_URL", DEFAULT_UPSTREAM_BASE_URL))
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("PROXY_TIMEOUT", DEFAULT_TIMEOUT)))
    parser.add_argument("--log-path", default=os.environ.get("PROXY_LOG_PATH", DEFAULT_LOG_PATH))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    global LOGGER
    args = parse_args(argv or sys.argv[1:])
    LOGGER = Logger(args.log_path)
    handler_cls = type(
        "AnthropicDebugProxyHandler",
        (ProxyHandler,),
        {"upstream_base_url": args.upstream_base_url, "timeout": args.timeout},
    )
    server = ThreadingHTTPServer((args.listen_host, args.listen_port), handler_cls)
    log(
        f"[{now()}] proxy listening on http://{args.listen_host}:{args.listen_port} "
        f"-> {args.upstream_base_url.rstrip('/')} log={args.log_path}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log(f"[{now()}] stopping proxy")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
