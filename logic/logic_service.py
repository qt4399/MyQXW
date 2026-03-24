from __future__ import annotations

import time
from typing import Callable
from typing import Iterator

from init import build_logic, run_logic, stream_logic
from memory.memory_store import DEFAULT_SESSION_ID, ensure_memory_layout


class LogicService:
    def __init__(self) -> None:
        ensure_memory_layout()
        self.logic_agent = build_logic()

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def logic(
        self,
        user_prompt: str,
        session_id: str = DEFAULT_SESSION_ID,
        enable_picture: bool = False,
        image_path: str = "",
        should_interrupt: Callable[[], bool] | None = None,
    ) -> str:
        return run_logic(
            self.logic_agent,
            user_prompt,
            session_id=session_id,
            should_interrupt=should_interrupt,
            enable_picture=enable_picture,
            image_path=image_path,
        )

    def logic_stream(
        self,
        user_prompt: str,
        session_id: str = DEFAULT_SESSION_ID,
        enable_picture: bool = False,
        image_path: str = "",
        should_interrupt: Callable[[], bool] | None = None,
    ) -> Iterator[str]:
        return stream_logic(
            self.logic_agent,
            user_prompt,
            session_id=session_id,
            should_interrupt=should_interrupt,
            enable_picture=enable_picture,
            image_path=image_path,
        )


def main() -> None:
    logic_service = LogicService()
    logic_service.start()
    print("[logic_service] 已启动。当前仅提供 logic 调用能力。")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[logic_service] 收到中断，准备退出。")
    finally:
        logic_service.stop()
        print("[logic_service] 已停止。")


if __name__ == "__main__":
    main()
