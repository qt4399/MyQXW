from __future__ import annotations

import time
from typing import Iterator

from emotion.emotion_service import EmotionService
from init import normalize_user_prompt
from memory.memory_store import (
    DEFAULT_SESSION_ID,
    append_dialogue_round,
    ensure_memory_layout,
    now_iso,
    update_state,
)

from .logic_service import LogicService
from .runtime_context import bind_session_id

STREAM_CHUNK_SIZE = 24


def _iter_reply_chunks(text: str, chunk_size: int = STREAM_CHUNK_SIZE) -> Iterator[str]:
    if not text:
        return

    for start in range(0, len(text), chunk_size):
        yield text[start : start + chunk_size]


class ChatService:
    def __init__(self) -> None:
        ensure_memory_layout()
        self.logic_service = LogicService()
        self.emotion_service = EmotionService()

    def start(self) -> None:
        self.logic_service.start()
        self.emotion_service.start()

    def stop(self) -> None:
        self.emotion_service.stop()
        self.logic_service.stop()

    def _build_final_reply(self, user_prompt: str, session_id: str = DEFAULT_SESSION_ID) -> str:
        clean_prompt = normalize_user_prompt(user_prompt)
        update_state({"last_user_message_at": now_iso()})

        with bind_session_id(session_id):
            logic_reply = self.logic_service.logic(clean_prompt, session_id=session_id).strip()
        final_reply = logic_reply

        if logic_reply:
            try:
                polished_reply = self.emotion_service.polish(
                    clean_prompt,
                    logic_reply,
                    session_id=session_id,
                ).strip()
            except Exception as exc:
                print(f"[chat_service] 情感润色失败，回退到 logic 草稿: {type(exc).__name__}: {exc}")
            else:
                if polished_reply:
                    final_reply = polished_reply

        append_dialogue_round(clean_prompt, final_reply, session_id=session_id)
        update_state({"last_assistant_message_at": now_iso()})
        return final_reply

    def chat(self, user_prompt: str, session_id: str = DEFAULT_SESSION_ID) -> str:
        return self._build_final_reply(user_prompt, session_id=session_id)

    def chat_stream(self, user_prompt: str, session_id: str = DEFAULT_SESSION_ID) -> Iterator[str]:
        reply = self._build_final_reply(user_prompt, session_id=session_id)
        yield from _iter_reply_chunks(reply)


def main() -> None:
    chat_service = ChatService()
    chat_service.start()
    print("[chat_service] 已启动。当前会先经过 logic，再由 emotion 润色。")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[chat_service] 收到中断，准备退出。")
    finally:
        chat_service.stop()
        print("[chat_service] 已停止。")


if __name__ == "__main__":
    main()
