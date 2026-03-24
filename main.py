from __future__ import annotations

import time

from congnition.heart_service import HeartService
from language.chat_service import ChatService
from learn.learn_service import LearnService
from scheduler.scheduler_service import SchedulerService
from sleep.sleep_service import SleepService
from transport.openai_api import OpenAICompatServer
from transport.qq_bridge import QQBridge

if __name__ == "__main__":
    chat_service = ChatService()
    heart_service = HeartService()
    sleep_service = SleepService()
    learn_service = LearnService()
    scheduler_service = SchedulerService(heart_service=heart_service, sleep_service=sleep_service)
    openai_transport = OpenAICompatServer(chat_service)
    qq_bridge = QQBridge(chat_service)

    chat_service.start()
    heart_service.start()
    sleep_service.start()
    learn_service.start()
    scheduler_service.start()
    openai_transport.start()
    qq_bridge.start()

    print("heart / sleep / learn / scheduler 在后台运行。")
    print("OpenAI-compatible API: http://127.0.0.1:8000/v1/chat/completions")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[main] 收到中断，准备退出。")
    finally:
        qq_bridge.stop()
        openai_transport.stop()
        scheduler_service.stop()
        learn_service.stop()
        sleep_service.stop()
        heart_service.stop()
        chat_service.stop()
        print("[main] 已停止。")
