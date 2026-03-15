from __future__ import annotations

import threading

from memory.memory_store import build_session_id
from qq_api_reference.napcat_api import NapCatAPI
from qq_api_reference.napcat_listener import Event, NapCatListener


class QQBridge:
    def __init__(
        self,
        scheduler,
        *,
        enable_private: bool = True,
        enable_group: bool = True,
        require_at_in_group: bool = True,
    ) -> None:
        self.scheduler = scheduler
        self.enable_private = enable_private
        self.enable_group = enable_group
        self.require_at_in_group = require_at_in_group
        self._listener = NapCatListener(self._on_event)
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        try:
            self._listener.start(blocking=False)
        except Exception as exc:
            print(f"[qq_bridge] 启动失败: {type(exc).__name__}: {exc}")
            return

        self._started = True
        print("[qq_bridge] 已启动，正在监听 NapCat 消息事件。")

    def stop(self) -> None:
        if not self._started:
            return
        self._listener.stop()
        self._started = False

    def _on_event(self, event: Event) -> None:
        if not self._started:
            return
        if event.user_id is not None and event.self_id is not None and str(event.user_id) == str(event.self_id):
            return
        if not event.is_private() and not event.is_group():
            return

        threading.Thread(
            target=self._handle_message_event,
            args=(event,),
            name="qq-bridge-handler",
            daemon=True,
        ).start()

    def _handle_message_event(self, event: Event) -> None:
        try:
            if event.is_private():
                self._handle_private_message(event)
                return
            if event.is_group():
                self._handle_group_message(event)
        except Exception as exc:
            print(f"[qq_bridge] 处理消息失败: {type(exc).__name__}: {exc}")

    def _handle_private_message(self, event: Event) -> None:
        if not self.enable_private or event.user_id is None:
            return

        prompt = self._extract_prompt(event)
        if not prompt:
            return

        session_id = build_session_id("qq", "private", event.user_id)
        reply = self.scheduler.chat(prompt, session_id=session_id).strip()
        if not reply:
            return

        with NapCatAPI() as api:
            api.send_private_msg(event.user_id, reply)

    def _handle_group_message(self, event: Event) -> None:
        if not self.enable_group or event.group_id is None:
            return
        if self.require_at_in_group and not event.is_at_self():
            return

        prompt = self._extract_prompt(event)
        if not prompt:
            return

        session_id = build_session_id("qq", "group", event.group_id)
        reply = self.scheduler.chat(prompt, session_id=session_id).strip()
        if not reply:
            return

        with NapCatAPI() as api:
            api.send_group_msg(event.group_id, reply)

    @staticmethod
    def _extract_prompt(event: Event) -> str:
        text = event.get_text_content().strip()
        return text
