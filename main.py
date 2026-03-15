from __future__ import annotations

import time

from scheduler import AgentScheduler
from transport.openai_api import OpenAICompatServer
from transport.qq_bridge import QQBridge

if __name__ == "__main__":
    scheduler = AgentScheduler()
    openai_transport = OpenAICompatServer(scheduler)
    qq_bridge = QQBridge(scheduler)

    scheduler.start()
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
        scheduler.stop()
        print("[main] 已停止。")
