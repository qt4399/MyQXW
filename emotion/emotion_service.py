from __future__ import annotations

import time

from init import build_emotion, run_emotion
from memory.memory_store import DEFAULT_SESSION_ID, ensure_memory_layout


class EmotionService:
    def __init__(self) -> None:
        ensure_memory_layout()
        self.emotion_agent = build_emotion()

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def polish(
        self,
        user_prompt: str,
        logic_reply: str,
        session_id: str = DEFAULT_SESSION_ID,
    ) -> str:
        return run_emotion(
            self.emotion_agent,
            user_prompt,
            logic_reply,
            session_id=session_id,
        )


def main() -> None:
    emotion_service = EmotionService()
    emotion_service.start()
    print("[emotion_service] 已启动。当前仅提供 polish 调用能力。")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[emotion_service] 收到中断，准备退出。")
    finally:
        emotion_service.stop()
        print("[emotion_service] 已停止。")


if __name__ == "__main__":
    main()
