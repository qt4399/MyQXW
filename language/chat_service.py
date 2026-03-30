from __future__ import annotations

import re
import time
from typing import Callable
from typing import Iterator

from emotion.emotion_service import EmotionService
from init import normalize_user_prompt
from memory.image_store import build_image_tag, extract_image_ids, strip_image_tags
from memory.memory_store import (
    DEFAULT_SESSION_ID,
    append_dialogue_round,
    ensure_memory_layout,
    now_iso,
    update_state,
)

from logic.logic_service import LogicService
from logic.runtime_context import (
    bind_session_id,
    clear_assistant_image_tags,
    consume_assistant_image_tags,
)

STREAM_CHUNK_SIZE = 24
MULTI_BLANK_LINES_PATTERN = re.compile(r"\n{3,}")
MULTI_SPACES_PATTERN = re.compile(r"[ \t]{2,}")


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

    @staticmethod
    def _sanitize_visible_reply(reply: str) -> str:
        text = strip_image_tags(reply)
        text = "\n".join(line.rstrip() for line in text.splitlines())
        text = MULTI_SPACES_PATTERN.sub(" ", text)
        text = MULTI_BLANK_LINES_PATTERN.sub("\n\n", text)
        return text.strip()

    def _build_memory_reply(self, raw_reply: str, session_id: str) -> str:
        clean_visible_reply = self._sanitize_visible_reply(raw_reply)
        image_tags = consume_assistant_image_tags(session_id=session_id)
        image_tags.extend(build_image_tag(image_id) for image_id in extract_image_ids(raw_reply))

        deduped_tags: list[str] = []
        for image_tag in image_tags:
            clean_tag = str(image_tag or "").strip()
            if clean_tag and clean_tag not in deduped_tags:
                deduped_tags.append(clean_tag)

        if not deduped_tags:
            return clean_visible_reply

        memory_parts: list[str] = []
        if clean_visible_reply:
            memory_parts.append(clean_visible_reply)
        memory_parts.extend(deduped_tags)
        return "\n".join(memory_parts)

    def _build_final_reply(
        self,
        user_prompt: str,
        session_id: str = DEFAULT_SESSION_ID,
        enable_picture: bool = False,
        image_path: str = "",
        should_interrupt: Callable[[], bool] | None = None,
    ) -> tuple[str, bool]:
        clean_prompt = normalize_user_prompt(user_prompt)
        update_state({"last_user_message_at": now_iso()})
        clear_assistant_image_tags(session_id=session_id)

        with bind_session_id(session_id):
            logic_reply = self.logic_service.logic(
                clean_prompt,
                session_id=session_id,
                enable_picture=enable_picture,
                image_path=image_path,
                should_interrupt=should_interrupt,
            ).strip()
        if should_interrupt and should_interrupt():
            return "", True
        final_reply = logic_reply

        if logic_reply:
            try:
                polished_reply = self.emotion_service.polish(
                    clean_prompt,
                    logic_reply,
                    session_id=session_id,
                    should_interrupt=should_interrupt,
                ).strip()
            except Exception as exc:
                print(f"[chat_service] 情感润色失败，回退到 logic 草稿: {type(exc).__name__}: {exc}")
            else:
                if polished_reply:
                    final_reply = polished_reply
        if should_interrupt and should_interrupt():
            return "", True

        visible_reply = self._sanitize_visible_reply(final_reply)
        memory_reply = self._build_memory_reply(final_reply, session_id=session_id)
        append_dialogue_round(clean_prompt, memory_reply, session_id=session_id)
        update_state({"last_assistant_message_at": now_iso()})
        return visible_reply, False

    def _build_logic_reply(
        self,
        clean_prompt: str,
        session_id: str,
        enable_picture: bool = False,
        image_path: str = "",
        should_interrupt: Callable[[], bool] | None = None,
    ) -> str:
        with bind_session_id(session_id):
            return self.logic_service.logic(
                clean_prompt,
                session_id=session_id,
                enable_picture=enable_picture,
                image_path=image_path,
                should_interrupt=should_interrupt,
            ).strip()

    def chat(
        self,
        user_prompt: str,
        session_id: str = DEFAULT_SESSION_ID,
        enable_picture: bool = False,
        image_path: str = "",
    ) -> str:
        reply, _ = self._build_final_reply(
            user_prompt,
            session_id=session_id,
            enable_picture=enable_picture,
            image_path=image_path,
        )
        return reply

    def chat_interruptible(
        self,
        user_prompt: str,
        session_id: str = DEFAULT_SESSION_ID,
        enable_picture: bool = False,
        image_path: str = "",
        should_interrupt: Callable[[], bool] | None = None,
    ) -> tuple[str, bool]:
        return self._build_final_reply(
            user_prompt,
            session_id=session_id,
            enable_picture=enable_picture,
            image_path=image_path,
            should_interrupt=should_interrupt,
        )

    def chat_stream(self, user_prompt: str, session_id: str = DEFAULT_SESSION_ID,enable_picture: bool = False,image_path: str = "") -> Iterator[str]:
        clean_prompt = normalize_user_prompt(user_prompt)
        update_state({"last_user_message_at": now_iso()})
        clear_assistant_image_tags(session_id=session_id)

        logic_reply = self._build_logic_reply(
            clean_prompt,
            session_id=session_id,
            enable_picture=enable_picture,
            image_path=image_path,
        )
        final_reply = logic_reply

        if logic_reply:
            try:
                chunks: list[str] = []
                for text in self.emotion_service.polish_stream(
                    clean_prompt,
                    logic_reply,
                    session_id=session_id,
                ):
                    chunks.append(text)
                    yield text
                polished_reply = "".join(chunks).strip()
            except Exception as exc:
                print(f"[chat_service] 情感润色流式输出失败，回退到 logic 草稿: {type(exc).__name__}: {exc}")
            else:
                if polished_reply:
                    final_reply = polished_reply
                    memory_reply = self._build_memory_reply(final_reply, session_id=session_id)
                    append_dialogue_round(clean_prompt, memory_reply, session_id=session_id)
                    update_state({"last_assistant_message_at": now_iso()})
                    return

        sanitized_reply = self._sanitize_visible_reply(final_reply)
        for text in _iter_reply_chunks(sanitized_reply):
            yield text

        memory_reply = self._build_memory_reply(final_reply, session_id=session_id)
        append_dialogue_round(clean_prompt, memory_reply, session_id=session_id)
        update_state({"last_assistant_message_at": now_iso()})


    def stream_reply_events(
        self,
        user_prompt: str,
        session_id: str = DEFAULT_SESSION_ID,
        enable_picture: bool = False,
        image_path: str = "",
        should_interrupt: Callable[[], bool] | None = None,
    ) -> Iterator[dict]:
        """yield 结构化事件：tool_call / tool_result / text / done / interrupted"""
        clean_prompt = normalize_user_prompt(user_prompt)
        update_state({"last_user_message_at": now_iso()})
        clear_assistant_image_tags(session_id=session_id)

        # 1. logic 阶段：yield tool_call / tool_result / text 事件
        logic_chunks: list[str] = []
        with bind_session_id(session_id):
            for event in self.logic_service.logic_stream_events(
                clean_prompt,
                session_id=session_id,
                enable_picture=enable_picture,
                image_path=image_path,
                should_interrupt=should_interrupt,
            ):
                if should_interrupt and should_interrupt():
                    yield {"type": "interrupted"}
                    return
                yield event
                if event.get("type") == "text":
                    logic_chunks.append(event["content"])

        if should_interrupt and should_interrupt():
            yield {"type": "interrupted"}
            return

        logic_reply = "".join(logic_chunks).strip()
        final_reply = logic_reply

        # 2. emotion 流式润色
        if logic_reply:
            yield {"type": "emotion_start"}
            emotion_chunks: list[str] = []
            try:
                for chunk in self.emotion_service.polish_stream(
                    clean_prompt, logic_reply, session_id=session_id
                ):
                    if should_interrupt and should_interrupt():
                        yield {"type": "interrupted"}
                        return
                    yield {"type": "text", "content": chunk, "stage": "emotion"}
                    emotion_chunks.append(chunk)
                polished = "".join(emotion_chunks).strip()
                if polished:
                    final_reply = polished
            except Exception as exc:
                print(f"[chat_service] emotion 润色失败: {type(exc).__name__}: {exc}")

        visible_reply = self._sanitize_visible_reply(final_reply)
        memory_reply = self._build_memory_reply(final_reply, session_id=session_id)
        append_dialogue_round(clean_prompt, memory_reply, session_id=session_id)
        update_state({"last_assistant_message_at": now_iso()})

        yield {"type": "done", "content": visible_reply}

    def dispatch(
        self,
        session_id: str,
        content: str,
        image_path: str = "",
        should_interrupt: Callable[[], bool] | None = None,
    ) -> Iterator[dict]:
        """统一消息入口：上层 transport 调此方法，传 session_id / content / image_path。"""
        yield from self.stream_reply_events(
            content,
            session_id=session_id,
            enable_picture=bool(image_path),
            image_path=image_path,
            should_interrupt=should_interrupt,
        )


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
