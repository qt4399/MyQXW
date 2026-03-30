from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from memory.image_store import build_image_tag, save_image_ref
from memory.memory_store import build_session_id
from qq_api_reference.napcat_api import NapCatAPI
from qq_api_reference.napcat_listener import Event, NapCatListener


@dataclass
class _QueuedQQPrompt:
    prompt: str
    chat_type: str
    target_id: int


class _SessionInbox:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.pending: list[_QueuedQQPrompt] = []
        self.version = 0
        self.worker_running = False


class QQBridge:
    def __init__(
        self,
        chat_service,
        *,
        enable_private: bool = True,
        enable_group: bool = True,
        require_at_in_group: bool = True,
    ) -> None:
        self.chat_service = chat_service
        self.enable_private = enable_private
        self.enable_group = enable_group
        self.require_at_in_group = require_at_in_group
        self._listener = NapCatListener(self._on_event)
        self._inboxes: dict[str, _SessionInbox] = {}
        self._inboxes_lock = threading.Lock()
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

        session_id = build_session_id("qq", "private", event.user_id)
        prompt = self._build_prompt(event, session_id=session_id)
        if not prompt:
            return

        self._enqueue_prompt(
            session_id=session_id,
            prompt=prompt,
            chat_type="private",
            target_id=int(event.user_id),
        )

    def _handle_group_message(self, event: Event) -> None:
        if not self.enable_group or event.group_id is None:
            return
        if self.require_at_in_group and not event.is_at_self():
            return

        session_id = build_session_id("qq", "group", event.group_id)
        prompt = self._build_prompt(event, session_id=session_id)
        if not prompt:
            return

        self._enqueue_prompt(
            session_id=session_id,
            prompt=prompt,
            chat_type="group",
            target_id=int(event.group_id),
        )

    def _get_inbox(self, session_id: str) -> _SessionInbox:
        with self._inboxes_lock:
            inbox = self._inboxes.get(session_id)
            if inbox is None:
                inbox = _SessionInbox()
                self._inboxes[session_id] = inbox
            return inbox

    def _enqueue_prompt(self, *, session_id: str, prompt: str, chat_type: str, target_id: int) -> None:
        inbox = self._get_inbox(session_id)
        start_worker = False
        with inbox.lock:
            inbox.pending.append(
                _QueuedQQPrompt(
                    prompt=prompt,
                    chat_type=chat_type,
                    target_id=target_id,
                )
            )
            inbox.version += 1
            if not inbox.worker_running:
                inbox.worker_running = True
                start_worker = True

        if start_worker:
            threading.Thread(
                target=self._session_worker_loop,
                args=(session_id,),
                name=f"qq-session-{session_id}",
                daemon=True,
            ).start()

    def _session_worker_loop(self, session_id: str) -> None:
        inbox = self._get_inbox(session_id)
        while self._started:
            with inbox.lock:
                batch = list(inbox.pending)
                inbox.pending.clear()
                generation = inbox.version

            if not batch:
                with inbox.lock:
                    inbox.worker_running = False
                    if inbox.pending:
                        inbox.worker_running = True
                        continue
                break

            merged_prompt = self._merge_prompts(batch)
            should_interrupt = self._make_interrupt_checker(session_id, generation)
            clean_reply = ""
            interrupted = False
            for event in self.chat_service.dispatch(
                session_id,
                merged_prompt,
                should_interrupt=should_interrupt,
            ):
                etype = event.get("type")
                if etype == "interrupted":
                    interrupted = True
                    break
                if etype == "done":
                    clean_reply = str(event.get("content") or "").strip()
            if interrupted or should_interrupt():
                self._prepend_batch(session_id, batch)
                continue

            if not clean_reply:
                continue
            self._send_reply(batch[-1], clean_reply)

    def _make_interrupt_checker(self, session_id: str, generation: int):
        def _checker() -> bool:
            inbox = self._get_inbox(session_id)
            with inbox.lock:
                return inbox.version != generation

        return _checker

    def _prepend_batch(self, session_id: str, batch: list[_QueuedQQPrompt]) -> None:
        if not batch:
            return
        inbox = self._get_inbox(session_id)
        with inbox.lock:
            inbox.pending = list(batch) + list(inbox.pending)

    @staticmethod
    def _merge_prompts(batch: list[_QueuedQQPrompt]) -> str:
        if len(batch) == 1:
            return batch[0].prompt

        parts = ["[以下是用户连续发来的多条消息，请结合整个序列再回复]"]
        for index, item in enumerate(batch, start=1):
            parts.append(f"[消息{index}]")
            parts.append(item.prompt)
        return "\n".join(part for part in parts if part).strip()

    @staticmethod
    def _send_reply(item: _QueuedQQPrompt, reply: str) -> None:
        with NapCatAPI() as api:
            if item.chat_type == "private":
                api.send_private_msg(item.target_id, reply)
            else:
                api.send_group_msg(item.target_id, reply)

    @staticmethod
    def _extract_prompt(event: Event) -> str:
        text = event.get_text_content().strip()
        return text

    def _build_prompt(self, event: Event, *, session_id: str) -> str:
        text = self._extract_prompt(event)
        image_tags: list[str] = []
        for image_ref in self._extract_pictures(event):
            image_record = save_image_ref(image_ref, session_id=session_id, source="qq")
            image_tags.append(build_image_tag(image_record["id"]))

        parts: list[str] = []
        if text:
            parts.append(text)
        if image_tags:
            parts.append("[本条消息附带图片]")
            for index, image_tag in enumerate(image_tags, start=1):
                parts.append(f"[图片{index}] {image_tag}")
        return "\n".join(parts).strip()

    @staticmethod
    def _extract_pictures(event: Event) -> list[str]:
        message = event.message
        if not isinstance(message, list):
            return []

        pictures: list[str] = []

        for seg in message:
            if not isinstance(seg, dict) or seg.get("type") != "image":
                continue

            data = seg.get("data", {})
            if not isinstance(data, dict):
                continue

            # NapCat 接收图片时通常会直接带 path；拿本地文件最稳。
            for key in ("path", "file"):
                value = str(data.get(key, "")).strip()
                if not value:
                    continue
                if Path(value).exists():
                    pictures.append(value)
                    break
            else:
                url = str(data.get("url", "")).strip()
                if url:
                    pictures.append(url)

        return pictures
