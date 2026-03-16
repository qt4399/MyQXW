from __future__ import annotations

import time

from congnition.heart_service import HeartService
from logic.chat_service import ChatService
from transport.openai_api import OpenAICompatServer
from transport.qq_bridge import QQBridge

if __name__ == "__main__":
    chat_service = ChatService()
    heart_service = HeartService()
    openai_transport = OpenAICompatServer(chat_service)
    qq_bridge = QQBridge(chat_service)

    chat_service.start()
    heart_service.start()
    openai_transport.start()
    qq_bridge.start()

    print("heartbeat 在后台运行。")
    print("OpenAI-compatible API: http://127.0.0.1:8000/v1/chat/completions")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[main] 收到中断，准备退出。")
    finally:
        qq_bridge.stop()
        openai_transport.stop()
        heart_service.stop()
        chat_service.stop()
        print("[main] 已停止。")
