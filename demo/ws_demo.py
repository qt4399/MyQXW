#!/usr/bin/env python3
"""WebSocket 调用 demo — 连接 ws_server 发送消息并显示事件流。"""
import asyncio
import json
import sys

import websockets

WS_URL = "ws://127.0.0.1:8765"

COLORS = {
    "tool_call":   "\033[33m",   # 黄
    "tool_result": "\033[36m",   # 青
    "text":        "\033[0m",    # 默认
    "done":        "\033[32m",   # 绿
    "error":       "\033[31m",   # 红
    "proactive":   "\033[35m",   # 紫
}
RESET = "\033[0m"


async def chat(prompt: str) -> None:
    print(f"连接 {WS_URL} ...\n")
    async with websockets.connect(WS_URL) as ws:
        await ws.send(json.dumps({"type": "chat", "content": prompt}, ensure_ascii=False))
        print("--- 事件流开始 ---")
        async for raw in ws:
            event = json.loads(raw)
            etype = event.get("type", "unknown")
            color = COLORS.get(etype, "")

            if etype == "text":
                print(event.get("content", ""), end="", flush=True)
            elif etype == "tool_call":
                inp = json.dumps(event.get("input", {}), ensure_ascii=False)
                print(f"\n{color}[工具调用] {event.get('name')}  输入: {inp}{RESET}")
            elif etype == "tool_result":
                output = str(event.get("output", ""))
                preview = output[:120] + "..." if len(output) > 120 else output
                print(f"{color}[工具结果] {event.get('name')}  → {preview}{RESET}")
            elif etype == "done":
                print(f"\n{color}\n--- 完整回复 ---\n{event.get('content', '')}{RESET}")
                break
            elif etype == "error":
                print(f"{color}[错误] {event.get('message')}{RESET}")
                break
            else:
                print(f"[{etype}] {event}")


if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]) or "今天有什么新闻啊"
    asyncio.run(chat(prompt))
