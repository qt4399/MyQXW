"""WebSocket transport server — 自定义事件协议，替代 OpenAI 兼容 HTTP 接口。

事件格式（JSON）：
  {"type": "text",        "content": "..."}          # 流式文字片段
  {"type": "tool_call",  "name": "...", "input": {}} # 工具调用开始
  {"type": "tool_result","name": "...", "output": ""} # 工具调用结果
  {"type": "done",       "content": "..."}          # 完整回复（emotion 润色后）
  {"type": "error",      "message": "..."}          # 错误
  {"type": "proactive",  "content": "..."}          # heart 主动发送
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

import websockets
from websockets.asyncio.server import ServerConnection

HOST = "0.0.0.0"
PORT = 8765


class WSServer:
    def __init__(self, chat_service) -> None:
        self.chat_service = chat_service
        self._clients: set[ServerConnection] = set()
        self._clients_lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="ws-server")
        self._thread.start()

    def stop(self) -> None:
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def send_proactive(self, content: str) -> None:
        """从任意线程推送主动消息给所有已连接的客户端。"""
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast_proactive(content), self._loop)

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self) -> None:
        print(f"[ws_server] 启动于 ws://{HOST}:{PORT}")
        async with websockets.serve(self._handle_client, HOST, PORT):
            await asyncio.get_event_loop().create_future()  # run forever

    async def _handle_client(self, ws: ServerConnection) -> None:
        async with self._clients_lock:
            self._clients.add(ws)
        print(f"[ws_server] 客户端连接: {ws.remote_address}")
        try:
            async for raw in ws:
                await self._handle_message(ws, raw)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            async with self._clients_lock:
                self._clients.discard(ws)
            print(f"[ws_server] 客户端断开: {ws.remote_address}")

    async def _handle_message(self, ws: ServerConnection, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await ws.send(json.dumps({"type": "error", "message": "invalid json"}))
            return

        msg_type = msg.get("type", "chat")
        if msg_type == "chat":
            await self._handle_chat(ws, msg)
        elif msg_type == "ping":
            await ws.send(json.dumps({"type": "pong"}))

    async def _handle_chat(self, ws: ServerConnection, msg: dict[str, Any]) -> None:
        user_text = str(msg.get("content", "")).strip()
        image_path = str(msg.get("image_path", ""))
        session_id = str(msg.get("session_id", "")) or None

        if not user_text and not image_path:
            await ws.send(json.dumps({"type": "error", "message": "empty message"}))
            return

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._stream_reply, ws, loop, user_text, image_path, session_id)

    def _stream_reply(
        self,
        ws: ServerConnection,
        loop: asyncio.AbstractEventLoop,
        user_text: str,
        image_path: str,
        session_id: str | None,
    ) -> None:
        """在线程池中运行（chat_service 是同步阻塞的）。"""
        try:
            for event in self.chat_service.dispatch(session_id or "ws:default", user_text, image_path=image_path):
                asyncio.run_coroutine_threadsafe(ws.send(json.dumps(event, ensure_ascii=False)), loop).result(timeout=10)
        except Exception as exc:
            err = {"type": "error", "message": f"{type(exc).__name__}: {exc}"}
            asyncio.run_coroutine_threadsafe(ws.send(json.dumps(err, ensure_ascii=False)), loop).result(timeout=5)
            return


    async def _broadcast_proactive(self, content: str) -> None:
        if not self._clients:
            return
        payload = json.dumps({"type": "proactive", "content": content}, ensure_ascii=False)
        async with self._clients_lock:
            targets = list(self._clients)
        for client in targets:
            try:
                await client.send(payload)
            except Exception:
                pass
