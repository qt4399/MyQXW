from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterator

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from memory.memory_store import (
    DEFAULT_SESSION_ID,
    ensure_memory_layout,
    read_prompt_snapshot,
    update_state,
)
from skills.chat_base_skills import CHAT_TOOLS
from skills.heart_base_skills import HEART_TOOLS

BASE_DIR = Path(__file__).resolve().parent
MEMORY_DIR = BASE_DIR / "memory"
MD_DIR = MEMORY_DIR / "md"
CONGNITION_MD_DIR = BASE_DIR / "congnition" / "md"
EMOTION_MD_DIR = BASE_DIR / "emotion" / "md"
CONFIG_PATH = BASE_DIR / "config.json"
CONTEXT_WINDOW_ROUNDS = 6

TEXT_SECTIONS = [
    ("[系统信息]", MD_DIR / "AGENT.md"),
    ("[你的身份]", MD_DIR / "ROLE.md"),
    ("[你的关系网络]", MD_DIR / "RELATION.md"),
    ("[你的灵魂]", MD_DIR / "SOUL.md"),
]
HEARTBEAT_SECTIONS = [
    ("[心跳规则]", CONGNITION_MD_DIR / "HEARTBEATS.md"),
]
EMOTION_SECTIONS = [
    ("[情感润色规则]", EMOTION_MD_DIR / "EMOTION.md"),
]
DEFAULT_EMOTION_RULES = (
    "你会收到[用户原话]和[逻辑层草稿]。\n"
    "不要改变事实、结论、承诺和关键信息。\n"
    "只做语气、节奏、情绪温度和表达顺滑度的润色。\n"
    "输出必须是可以直接发给用户的最终回复，不要解释。"
)

with CONFIG_PATH.open("r", encoding="utf-8") as f:
    config = json.load(f)


def _read_text_section(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _dynamic_sections(snapshot: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        ("[今日记忆]", snapshot["day_md"]),
        ("[最近30天概括]", snapshot["month_summaries"]),
    ]


def normalize_user_prompt(user_prompt: str) -> str:
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


def _base_system_parts(snapshot: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    for title, path in TEXT_SECTIONS:
        content = _read_text_section(path)
        if content:
            parts.append(f"{title}:\n{content}\n")

    for title, content in _dynamic_sections(snapshot):
        if content:
            parts.append(f"{title}:\n{content}\n")

    return parts


def _system_message(include_heartbeat: bool, snapshot: dict[str, Any] | None = None) -> dict[str, str]:
    ensure_memory_layout()
    memory_snapshot = snapshot or read_prompt_snapshot(max_rounds=CONTEXT_WINDOW_ROUNDS)
    parts = _base_system_parts(memory_snapshot)

    if include_heartbeat:
        for title, path in HEARTBEAT_SECTIONS:
            content = _read_text_section(path)
            if content:
                parts.append(f"{title}:\n{content}\n")

    parts.append("[当前发言人]:秦滔")
    return {"role": "system", "content": "\n".join(parts)}


def _emotion_system_message(snapshot: dict[str, Any] | None = None) -> dict[str, str]:
    ensure_memory_layout()
    memory_snapshot = snapshot or read_prompt_snapshot(max_rounds=CONTEXT_WINDOW_ROUNDS)
    parts = _base_system_parts(memory_snapshot)

    rules = []
    for _, path in EMOTION_SECTIONS:
        content = _read_text_section(path)
        if content:
            rules.append(content)
    rules_text = "\n\n".join(rules).strip() or DEFAULT_EMOTION_RULES
    parts.append(f"[情感润色规则]:\n{rules_text}\n")
    parts.append("[当前发言人]:秦滔")
    return {"role": "system", "content": "\n".join(parts)}


def build_logic():
    llm = ChatOpenAI(
        model=config["gpt_model"],
        api_key=config["gpt_api_key"],
        base_url=config["gpt_base_url"],
        temperature=0,
    )
    return create_react_agent(llm, tools=CHAT_TOOLS)


def build_heart():
    llm = ChatOpenAI(
        model=config["heart_model"],
        api_key=config["heart_api_key"],
        base_url=config["heart_base_url"],
        temperature=0,
    )
    return create_react_agent(llm, tools=HEART_TOOLS)


def build_emotion():
    llm = ChatOpenAI(
        model=config["emotion_model"],
        api_key=config["emotion_api_key"],
        base_url=config["emotion_base_url"],
        temperature=0.8,
    )
    return create_react_agent(llm, tools=[])


def build_input(user_prompt: str, session_id: str = DEFAULT_SESSION_ID) -> dict[str, list[dict[str, str]]]:
    clean_prompt = normalize_user_prompt(user_prompt)
    snapshot = read_prompt_snapshot(max_rounds=CONTEXT_WINDOW_ROUNDS, session_id=session_id)
    messages = [_system_message(include_heartbeat=False, snapshot=snapshot)]
    messages.extend(snapshot["recent_messages"])
    messages.append({"role": "user", "content": clean_prompt})
    return {"messages": messages}


def build_heart_input(user_prompt: str) -> dict[str, list[dict[str, str]]]:
    snapshot = read_prompt_snapshot(max_rounds=CONTEXT_WINDOW_ROUNDS)
    return {"messages": [_system_message(include_heartbeat=True, snapshot=snapshot), {"role": "user", "content": user_prompt}]}


def build_emotion_input(
    user_prompt: str,
    logic_reply: str,
    session_id: str = DEFAULT_SESSION_ID,
) -> dict[str, list[dict[str, str]]]:
    clean_prompt = normalize_user_prompt(user_prompt)
    snapshot = read_prompt_snapshot(max_rounds=CONTEXT_WINDOW_ROUNDS, session_id=session_id)
    content = "\n".join(
        [
            "[用户原话]",
            clean_prompt,
            "",
            "[逻辑层草稿]",
            logic_reply.strip(),
            "",
            "请在不改变事实、判断、承诺和关键信息的前提下，",
            "把逻辑层草稿润色成最终发送给用户的回复。",
            "以一个女儿的非常活泼可爱的口吻润色，"
            "只输出最终回复，不要解释。",
        ]
    ).strip()
    return {
        "messages": [
            _emotion_system_message(snapshot=snapshot),
            {"role": "user", "content": content},
        ]
    }


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


def stream_logic(
    agent,
    user_prompt: str,
    session_id: str = DEFAULT_SESSION_ID,
    should_interrupt: Callable[[], bool] | None = None,
) -> Iterator[str]:
    clean_prompt = normalize_user_prompt(user_prompt)
    payload = build_input(clean_prompt, session_id=session_id)
    for chunk, metadata in agent.stream(payload, stream_mode="messages"):
        if should_interrupt and should_interrupt():
            return
        if metadata.get("langgraph_node") != "agent":
            continue
        for text in _iter_text_fragments(getattr(chunk, "content", "")):
            yield text


def run_logic(
    agent,
    user_prompt: str,
    session_id: str = DEFAULT_SESSION_ID,
    should_interrupt: Callable[[], bool] | None = None,
) -> str:
    return "".join(stream_logic(agent, user_prompt, session_id=session_id, should_interrupt=should_interrupt)).strip()


def chat_stream(
    agent,
    user_prompt: str,
    session_id: str = DEFAULT_SESSION_ID,
    should_interrupt: Callable[[], bool] | None = None,
) -> Iterator[str]:
    return stream_logic(agent, user_prompt, session_id=session_id, should_interrupt=should_interrupt)


def chat(
    agent,
    user_prompt: str,
    session_id: str = DEFAULT_SESSION_ID,
    should_interrupt: Callable[[], bool] | None = None,
) -> str:
    return run_logic(agent, user_prompt, session_id=session_id, should_interrupt=should_interrupt)


def run_emotion(
    agent,
    user_prompt: str,
    logic_reply: str,
    session_id: str = DEFAULT_SESSION_ID,
    show_output: bool = False,
    should_interrupt: Callable[[], bool] | None = None,
) -> str:
    return _stream_agent_response(
        agent,
        build_emotion_input(user_prompt, logic_reply, session_id=session_id),
        show_output=show_output,
        should_interrupt=should_interrupt,
    )


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
