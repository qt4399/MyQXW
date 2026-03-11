from __future__ import annotations

import json
import subprocess

from langchain_core.tools import tool

from memory.memory_store import (
    append_day_md,
    delete_temp_rounds as remove_temp_rounds,
    ensure_memory_layout,
    read_communicate,
    read_day_md,
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
    """基本技能 运行 Linux bash 命令，并返回 stdout、stderr 和 returncode 的 JSON 字符串。"""
    print(f"运行命令: {command}")
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
    """基本技能 读取 state.yaml。"""
    print("正在读取 state.yaml")
    return _json_result(returncode=0, stderr="", data=read_state())


@tool("update_state")
def update_state_tool(patch_json: str) -> str:
    """基本技能 以 JSON patch 的形式更新 state.yaml。"""
    print("正在更新 state.yaml")
    try:
        patch = json.loads(patch_json)
    except json.JSONDecodeError as exc:
        return _json_result(returncode=1, stderr=f"patch_json 不是合法 JSON: {exc}", stdout="")

    if not isinstance(patch, dict):
        return _json_result(returncode=1, stderr="patch_json 必须是 JSON 对象", stdout="")

    return _json_result(returncode=0, stderr="", data=patch_state(patch))

@tool("read_temp_communicate")
def read_temp_communicate_tool() -> str:
    """基本技能 读取 temp_communicate.yaml，里面是等待心跳整理的溢出对话。"""
    print("正在读取 temp_communicate.yaml")
    return _json_result(returncode=0, stderr="", data=read_temp_communicate())


@tool("delete_temp_rounds")
def delete_temp_rounds_tool(ids_json: str) -> str:
    """基本技能 删除 temp_communicate.yaml 中已经处理过的轮次，参数是 JSON 数组。"""
    print("正在删除 temp_communicate 里的轮次")
    try:
        ids = json.loads(ids_json)
    except json.JSONDecodeError as exc:
        return _json_result(returncode=1, stderr=f"ids_json 不是合法 JSON: {exc}", stdout="")

    if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
        return _json_result(returncode=1, stderr="ids_json 必须是字符串数组", stdout="")

    return _json_result(returncode=0, stderr="", data=remove_temp_rounds(ids))


@tool("update_day_summary")
def update_day_summary_tool(summary: str) -> str:
    """基本技能 更新 day.md 的概括部分。"""
    print("正在更新 day.md 概括")
    return _json_result(returncode=0, stderr="", data=update_day_summary(summary))


@tool("append_day_md")
def append_day_md_tool(content: str) -> str:
    """基本技能 向 day.md 的详细部分追加一段 Markdown 内容。"""
    print("正在追加 day.md")
    try:
        updated = append_day_md(content)
    except ValueError as exc:
        return _json_result(returncode=1, stderr=str(exc), stdout="")
    return _json_result(returncode=0, stderr="", data=updated)


@tool("read_month_day")
def read_month_day_tool(date: str) -> str:
    """基本技能 读取 month.md 中某一天的完整内容。参数必须是 YYYY-MM-DD，例如 2026-03-10。
    调用前先查看系统提示中的“最近30天概括”，从里面挑一个已出现过的精确日期再来读取详细内容；不要传“前几天”“上周某天”这类模糊说法。"""
    print(f"正在读取 month.md 中的 {date}")
    try:
        content = read_month_day(date)
    except ValueError as exc:
        return _json_result(returncode=1, stderr=str(exc), stdout="")
    return _json_result(returncode=0, stderr="", data=content)
