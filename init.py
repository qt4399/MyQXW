from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from memory.memory_store import (
    append_dialogue_round,
    ensure_memory_layout,
    now_iso,
    read_prompt_snapshot,
    update_state,
)
from skills.chat_skills import CHAT_TOOLS
from skills.heart_skills import HEART_TOOLS

BASE_DIR = Path(__file__).resolve().parent
MEMORY_DIR = BASE_DIR / "memory"
MD_DIR = MEMORY_DIR / "md"
CONFIG_PATH = BASE_DIR / "config.json"
CONTEXT_WINDOW_ROUNDS = 6

TEXT_SECTIONS = [
    ("[系统信息]", MD_DIR / "AGENT.md"),
    ("[你的身份]", MD_DIR / "ROLE.md"),
    ("[你的关系网络]", MD_DIR / "RELATION.md"),
    ("[你的灵魂]", MD_DIR / "SOUL.md"),
]
HEARTBEAT_SECTIONS = [
    ("[心跳规则]", MD_DIR / "HEARTBEATS.md"),
]

with CONFIG_PATH.open("r", encoding="utf-8") as f:
    config = json.load(f)


def _read_text_section(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _dynamic_sections(snapshot: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        ("[今日记忆]", snapshot["day_md"]),
        ("[最近30天概括]", snapshot["month_summaries"]),
    ]


def _normalize_user_prompt(user_prompt: str) -> str:
    clean = user_prompt.strip()
    prefixes = ("用户：", "用户:", "秦滔：", "秦滔:", "秦熹微：", "秦熹微:")
    changed = True
    while changed and clean:
        changed = False
        for prefix in prefixes:
            if clean.startswith(prefix):
                clean = clean[len(prefix) :].lstrip()
                changed = True
    return clean or user_prompt.strip()


def _system_message(include_heartbeat: bool, snapshot: dict[str, Any] | None = None) -> dict[str, str]:
    ensure_memory_layout()
    memory_snapshot = snapshot or read_prompt_snapshot(max_rounds=CONTEXT_WINDOW_ROUNDS)
    parts: list[str] = []
    for title, path in TEXT_SECTIONS:
        parts.append(f"{title}:\n{_read_text_section(path)}\n")

    for title, content in _dynamic_sections(memory_snapshot):
        parts.append(f"{title}:\n{content}\n")

    if include_heartbeat:
        for title, path in HEARTBEAT_SECTIONS:
            parts.append(f"{title}:\n{_read_text_section(path)}\n")

    parts.append("[当前发言人]:秦滔")
    return {"role": "system", "content": "\n".join(parts)}


def build_agent():
    llm = ChatOpenAI(
        model=config["gpt_model"],
        api_key=config["gpt_api_key"],
        base_url=config["gpt_base_url"],
        temperature=0,
    )
    return create_react_agent(llm, tools=CHAT_TOOLS)


def build_heart():
    llm = ChatOpenAI(
        model=config["model"],
        api_key=config["api_key"],
        base_url=config["base_url"],
        temperature=0,
    )
    return create_react_agent(llm, tools=HEART_TOOLS)


def build_input(user_prompt: str) -> dict[str, list[dict[str, str]]]:
    clean_prompt = _normalize_user_prompt(user_prompt)
    snapshot = read_prompt_snapshot(max_rounds=CONTEXT_WINDOW_ROUNDS)
    messages = [_system_message(include_heartbeat=False, snapshot=snapshot)]
    messages.extend(snapshot["recent_messages"])
    messages.append({"role": "user", "content": clean_prompt})
    return {"messages": messages}


def build_heart_input(user_prompt: str) -> dict[str, list[dict[str, str]]]:
    snapshot = read_prompt_snapshot(max_rounds=CONTEXT_WINDOW_ROUNDS)
    return {"messages": [_system_message(include_heartbeat=True, snapshot=snapshot), {"role": "user", "content": user_prompt}]}


def _iter_text_fragments(content: Any):
    if isinstance(content, str):
        if content:
            yield content
        return
    if isinstance(content, list):
        for item in content:
            if isinstance(item, str) and item:
                yield item
            elif isinstance(item, dict):
                text = item.get("text")
                if text:
                    yield text


def _stream_agent_response(
    agent,
    payload: dict[str, Any],
    show_output: bool,
    should_interrupt: Callable[[], bool] | None = None,
) -> str:
    full_response = ""
    if show_output:
        print("秦熹微：", end="", flush=True)
    try:
        for chunk, metadata in agent.stream(payload, stream_mode="messages"):
            if should_interrupt and should_interrupt():
                return full_response.strip()
            if metadata.get("langgraph_node") != "agent":
                continue
            for text in _iter_text_fragments(getattr(chunk, "content", "")):
                if show_output:
                    print(text, end="", flush=True)
                full_response += text
    finally:
        if show_output:
            print("\n")
    return full_response.strip()


def run_stream(agent, user_prompt: str, show_output: bool = True) -> str:
    clean_prompt = _normalize_user_prompt(user_prompt)
    update_state({"last_user_message_at": now_iso()})

    response_text = ""
    stream_completed = False
    try:
        response_text = _stream_agent_response(agent, build_input(clean_prompt), show_output=show_output)
        append_dialogue_round(clean_prompt, response_text)
        stream_completed = True
        return response_text
    finally:
        if stream_completed:
            update_state({"last_assistant_message_at": now_iso()})


def run_heart(
    agent,
    user_prompt: str,
    show_output: bool = False,
    should_interrupt: Callable[[], bool] | None = None,
) -> str:
    try:
        return _stream_agent_response(
            agent,
            build_heart_input(user_prompt),
            show_output=show_output,
            should_interrupt=should_interrupt,
        )
    finally:
        update_state({"play": {"active": False}})
