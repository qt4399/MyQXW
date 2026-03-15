from __future__ import annotations

import json
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import websocket
from websocket import WebSocketTimeoutException


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "local_config.json"


@dataclass
class NapCatConfig:
    ws_url: str
    api_only_ws_url: str
    token: str
    timeout: float = 10.0


def load_config() -> NapCatConfig:
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return NapCatConfig(
        ws_url=data["ws_url"],
        api_only_ws_url=data.get("api_only_ws_url", data["ws_url"]),
        token=data.get("token", ""),
        timeout=float(data.get("timeout", 10)),
    )


class NapCatWSClient:
    def __init__(self, config: NapCatConfig | None = None, *, api_only: bool = False) -> None:
        self.config = config or load_config()
        self.api_only = api_only
        self.ws: websocket.WebSocket | None = None
        self.event_buffer: deque[dict[str, Any]] = deque()

    @property
    def url(self) -> str:
        return self.config.api_only_ws_url if self.api_only else self.config.ws_url

    def connect(self) -> "NapCatWSClient":
        headers = []
        if self.config.token:
            headers.append(f"Authorization: Bearer {self.config.token}")

        self.ws = websocket.create_connection(
            self.url,
            header=headers,
            timeout=self.config.timeout,
        )
        return self

    def close(self) -> None:
        if self.ws is not None:
            self.ws.close()
            self.ws = None

    def __enter__(self) -> "NapCatWSClient":
        return self.connect()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _require_ws(self) -> websocket.WebSocket:
        if self.ws is None:
            raise RuntimeError("NapCat WS 尚未连接，请先调用 connect()")
        return self.ws

    def _recv_json(self) -> dict[str, Any]:
        raw = self._require_ws().recv()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        return json.loads(raw)

    def _recv_json_blocking(self) -> dict[str, Any]:
        """接收 JSON，并临时关闭 socket 超时以实现真正阻塞等待"""
        ws = self._require_ws()
        old_timeout = ws.gettimeout()
        try:
            ws.settimeout(None)
            raw = ws.recv()
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            return json.loads(raw)
        finally:
            ws.settimeout(old_timeout)

    def _recv_json_with_timeout(self, timeout: float | None = None) -> dict[str, Any] | None:
        """接收 JSON，超时返回 None 而不是抛异常"""
        ws = self._require_ws()
        old_timeout = ws.gettimeout()
        try:
            if timeout is not None:
                ws.settimeout(timeout)
            raw = ws.recv()
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            return json.loads(raw)
        except WebSocketTimeoutException:
            return None
        finally:
            ws.settimeout(old_timeout)

    @staticmethod
    def _is_action_response(data: dict[str, Any]) -> bool:
        return "status" in data and "retcode" in data

    def call_api(
        self,
        action: str,
        params: dict[str, Any] | None = None,
        *,
        echo: str | None = None,
    ) -> dict[str, Any]:
        ws = self._require_ws()
        request_echo = echo or f"{action}-{uuid.uuid4().hex[:8]}"
        payload = {
            "action": action,
            "params": params or {},
            "echo": request_echo,
        }
        ws.send(json.dumps(payload, ensure_ascii=False))

        while True:
            data = self._recv_json()
            if self._is_action_response(data) and data.get("echo") == request_echo:
                return data
            self.event_buffer.append(data)

    def recv_event(self, timeout: float | None = None) -> dict[str, Any] | None:
        """接收事件，超时返回 None

        Args:
            timeout: 超时秒数，None 使用默认配置，0 表示立即返回
        """
        if self.event_buffer:
            return self.event_buffer.popleft()
        return self._recv_json_with_timeout(timeout)

    def recv_event_blocking(self) -> dict[str, Any]:
        """阻塞式接收事件，无限等待直到收到事件"""
        if self.event_buffer:
            return self.event_buffer.popleft()
        return self._recv_json_blocking()


def pretty_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
