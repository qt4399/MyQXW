from __future__ import annotations

import json
from pathlib import Path

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from memory.memory_store import (
    append_dialogue_round,
    ensure_memory_layout,
    now_iso,
    read_day_md,
    read_month_summaries,
    recent_conversation_messages,
    update_state,
)
from skills.baseskills import (
    append_day_md_tool,
    delete_temp_rounds_tool,
    read_month_day_tool,
    read_state_tool,
    read_temp_communicate_tool,
    run_command,
    update_day_summary_tool,
    update_state_tool,
)

BASE_DIR = Path(__file__).resolve().parent
MEMORY_DIR = BASE_DIR / "memory"
MD_DIR = MEMORY_DIR / "md"
CONFIG_PATH = BASE_DIR / "config.json"

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


AGENT_TOOLS = [
    run_command,
    read_state_tool,
    update_state_tool,
    read_temp_communicate_tool,
    delete_temp_rounds_tool,
    update_day_summary_tool,
    append_day_md_tool,
    read_month_day_tool,
]


def _read_text_section(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _dynamic_sections() -> list[tuple[str, str]]:
    return [
        ("[今日记忆]", read_day_md().strip()),
        ("[最近30天概括]", read_month_summaries().strip()),
    ]


def _system_message(include_heartbeat: bool) -> dict[str, str]:
    ensure_memory_layout()
    parts: list[str] = []

    for title, path in TEXT_SECTIONS:
        parts.append(f"{title}:\n{_read_text_section(path)}\n")

    for title, content in _dynamic_sections():
        parts.append(f"{title}:\n{content}\n")

    if include_heartbeat:
        for title, path in HEARTBEAT_SECTIONS:
            parts.append(f"{title}:\n{_read_text_section(path)}\n")

    parts.append("[当前发言人]:用户")
    return {"role": "system", "content": "\n".join(parts)}


def build_agent():
    llm = ChatOpenAI(
        model=config["model"],
        api_key=config["api_key"],
        base_url=config["base_url"],
        temperature=0,
    )
    return create_react_agent(llm, tools=AGENT_TOOLS)


def build_heart():
    llm = ChatOpenAI(
        model=config["model"],
        api_key=config["api_key"],
        base_url=config["base_url"],
        temperature=0,
    )
    return create_react_agent(llm, tools=AGENT_TOOLS)


def build_input(user_prompt: str) -> dict:
    messages = [_system_message(include_heartbeat=False)]
    messages.extend(recent_conversation_messages())
    messages.append({"role": "user", "content": user_prompt})
    return {"messages": messages}


def build_heart_input(user_prompt: str) -> dict:
    return {"messages": [_system_message(include_heartbeat=True), {"role": "user", "content": user_prompt}]}


def _iter_text_fragments(content):
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


def run_stream(agent, user_prompt: str) -> None:
    update_state(
        {
            "current_mode": "chat",
            "last_user_message_at": now_iso(),
        }
    )

    full_response = ""
    print("小智：", end="", flush=True)
    for chunk, metadata in agent.stream(build_input(user_prompt), stream_mode="messages"):
        if metadata.get("langgraph_node") != "agent":
            continue
        for text in _iter_text_fragments(getattr(chunk, "content", "")):
            print(text, end="", flush=True)
            full_response += text

    append_dialogue_round(user_prompt, full_response)
    update_state(
        {
            "current_mode": "idle",
            "last_assistant_message_at": now_iso(),
        }
    )
    print("\n")


def run_heart(agent, user_prompt: str) -> str:
    full_response = ""
    print("小智：", end="", flush=True)
    for chunk, metadata in agent.stream(build_heart_input(user_prompt), stream_mode="messages"):
        if metadata.get("langgraph_node") != "agent":
            continue
        for text in _iter_text_fragments(getattr(chunk, "content", "")):
            print(text, end="", flush=True)
            full_response += text

    update_state({"current_mode": "idle", "play": {"active": False}})
    print("\n")
    return full_response.strip()
