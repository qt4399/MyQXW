from __future__ import annotations

import json
import subprocess

from langchain_core.tools import tool

from memory.memory_store import (
    append_day_md,
    delete_temp_rounds as remove_temp_rounds,
    ensure_memory_layout,
    read_month_day,
    read_state,
    read_temp_communicate,
    update_day_summary,
    update_state as patch_state,
)

ensure_memory_layout()


def _json_result(**payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool("run_command")
def run_command(command: str) -> str:
    """睡眠区工具：运行 Linux bash 命令，并返回 stdout、stderr 和 returncode 的 JSON 字符串。"""
    print(f"[sleep] 运行命令: {command}")
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


@tool("read_state")
def read_state_tool() -> str:
    """睡眠区工具：读取 state.yaml。"""
    print("[sleep] 正在读取 state.yaml")
    return _json_result(returncode=0, stderr="", data=read_state())


@tool("update_state")
def update_state_tool(patch_json: str) -> str:
    """睡眠区工具：以 JSON patch 的形式更新 state.yaml。"""
    print("[sleep] 正在更新 state.yaml")
    try:
        patch = json.loads(patch_json)
    except json.JSONDecodeError as exc:
        return _json_result(returncode=1, stderr=f"patch_json 不是合法 JSON: {exc}", stdout="")

    if not isinstance(patch, dict):
        return _json_result(returncode=1, stderr="patch_json 必须是 JSON 对象", stdout="")

    return _json_result(returncode=0, stderr="", data=patch_state(patch))


@tool("read_temp_communicate")
def read_temp_communicate_tool(session_id: str = "") -> str:
    """睡眠区工具：读取 temp_communicate.yaml，支持传入 session_id。留空时默认主会话。"""
    print(f"[sleep] 正在读取 temp_communicate.yaml: session_id={session_id or 'main:owner'}")
    return _json_result(returncode=0, stderr="", data=read_temp_communicate(session_id=session_id or None))


@tool("delete_temp_rounds")
def delete_temp_rounds_tool(payload_json: str) -> str:
    """睡眠区工具：删除 temp_communicate.yaml 中已处理轮次。支持 JSON 数组，或 {"session_id":"...", "ids":[...]}。"""
    print("[sleep] 正在删除 temp_communicate 里的轮次")
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        return _json_result(returncode=1, stderr=f"payload_json 不是合法 JSON: {exc}", stdout="")

    session_id = None
    ids: list[str] | None = None
    if isinstance(payload, list) and all(isinstance(item, str) for item in payload):
        ids = payload
    elif isinstance(payload, dict):
        raw_ids = payload.get("ids", [])
        if isinstance(raw_ids, list) and all(isinstance(item, str) for item in raw_ids):
            ids = raw_ids
            session_value = str(payload.get("session_id", "")).strip()
            session_id = session_value or None

    if ids is None:
        return _json_result(returncode=1, stderr="payload_json 必须是字符串数组，或包含 session_id 与 ids 的 JSON 对象", stdout="")

    return _json_result(returncode=0, stderr="", data=remove_temp_rounds(ids, session_id=session_id))


@tool("update_day_summary")
def update_day_summary_tool(summary: str) -> str:
    """睡眠区工具：更新 day.md 的概括部分。"""
    print("[sleep] 正在更新 day.md 概括")
    return _json_result(returncode=0, stderr="", data=update_day_summary(summary))


@tool("append_day_md")
def append_day_md_tool(content: str) -> str:
    """睡眠区工具：向 day.md 的详细部分追加一段 Markdown 内容。"""
    print("[sleep] 正在追加 day.md")
    try:
        updated = append_day_md(content)
    except ValueError as exc:
        return _json_result(returncode=1, stderr=str(exc), stdout="")
    return _json_result(returncode=0, stderr="", data=updated)


@tool("read_month_day")
def read_month_day_tool(date: str) -> str:
    """睡眠区工具：读取 month.md 中某一天的完整内容。参数必须是 YYYY-MM-DD。"""
    print(f"[sleep] 正在读取 month.md 中的 {date}")
    try:
        content = read_month_day(date)
    except ValueError as exc:
        return _json_result(returncode=1, stderr=str(exc), stdout="")
    return _json_result(returncode=0, stderr="", data=content)


SLEEP_TOOLS = [
    run_command,
    read_state_tool,
    update_state_tool,
    read_temp_communicate_tool,
    delete_temp_rounds_tool,
    update_day_summary_tool,
    append_day_md_tool,
    read_month_day_tool,
]
