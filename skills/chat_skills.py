from __future__ import annotations

import json
import subprocess

from langchain_core.tools import tool

from memory.memory_store import ensure_memory_layout, read_month_day

ensure_memory_layout()


def _json_result(**payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool("run_command")
def run_command(command: str) -> str:
    """对话区工具：运行 Linux bash 命令，并返回 stdout、stderr 和 returncode 的 JSON 字符串。"""
    print(f"[chat] 运行命令: {command}")
    completed = subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return _json_result(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
    )


@tool("read_month_day")
def read_month_day_tool(date: str) -> str:
    """对话区工具：读取 month.md 中某一天的完整内容。参数必须是 YYYY-MM-DD。"""
    print(f"[chat] 正在读取 month.md 中的 {date}")
    try:
        content = read_month_day(date)
    except ValueError as exc:
        return _json_result(returncode=1, stderr=str(exc), stdout="")
    return _json_result(returncode=0, stderr="", data=content)


CHAT_TOOLS = [
    run_command,
    read_month_day_tool,
]
