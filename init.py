from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any, Callable, Iterator

from langgraph.prebuilt import create_react_agent

from logic.patched_chat_openai import PatchedChatOpenAI
from memory.memory_store import (
    DEFAULT_SESSION_ID,
    ensure_memory_layout,
    read_prompt_snapshot,
)
from skill.chat_base_skill import CHAT_TOOLS
from skill.chat_extra_skill import CHAT_EXTRA_TOOLS
from skill.heart_base_skill import HEART_TOOLS
from skill.heart_extra_skill import HEART_EXTRA_TOOLS
from skill.sleep_base_skill import SLEEP_TOOLS
from skill.sleep_extra_skill import SLEEP_EXTRA_TOOLS

BASE_DIR = Path(__file__).resolve().parent
MEMORY_DIR = BASE_DIR / "memory"
MD_DIR = MEMORY_DIR / "md"
CONGNITION_MD_DIR = BASE_DIR / "congnition" / "md"
EMOTION_MD_DIR = BASE_DIR / "emotion" / "md"
SLEEP_MD_DIR = BASE_DIR / "sleep" / "md"
CONFIG_PATH = BASE_DIR / "config.json"
CONTEXT_WINDOW_ROUNDS = 6

TEXT_SECTIONS: list[tuple[str, Path]] = [
    ("[系统信息]", MD_DIR / "AGENT.md"),
    ("[你的身份]", MD_DIR / "ROLE.md"),
    ("[你的关系网络]", MD_DIR / "RELATION.md"),
    ("[你的灵魂]", MD_DIR / "SOUL.md"),
]
HEART_SECTIONS: list[tuple[str, Path]] = [
    ("[主观中断规则]", CONGNITION_MD_DIR / "INTERRUPTS.md"),
]
SLEEP_SECTIONS: list[tuple[str, Path]] = [
    ("[睡眠整理规则]", SLEEP_MD_DIR / "SLEEP.md"),
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
IMAGE_RESOURCE_RULES = (
    "[图片资源规则]:\n"
    "如果用户消息或短期记忆里出现一个或多个 <image id=\"...\" />，说明当前会话里有可用图片资源。\n"
    "如果同一条消息里有多张图，它们通常会以 [图片1] <image id=\"...\" />、[图片2] <image id=\"...\" /> 这样的顺序标签出现。\n"
    "这个 <image id=\"...\" /> 是内部图片标记，不是给用户看的；正常回复时不要把这个标签原样展示给用户。\n"
    "你不要凭空猜测图片内容；只有在回复确实依赖图像内容时，才调用视觉工具查看。\n"
    "如果只需要看一张图，调用 inspect_image；如果需要结合、比较、排序、筛选多张图，调用 inspect_images。\n"
    "如果当前回复不需要图像内容，就直接忽略这个标签，不要主动把图片内容编造成事实。\n"
    "如果用户说“这张图”“刚才那张”“你发的那张”“上一张”这类指代，而最近对话里已经有 <image id=\"...\" />，默认优先理解为在指最近相关图片；若回答依赖图像内容，就直接调用 inspect_image 查看，不要先让用户重复发送。\n"
    "如果用户说“第一张”“第二张”“最后一张”“前两张”“这几张”“所有图片”“对比一下”这类多图指代，默认优先考虑 inspect_images。"
)
TOOL_EXECUTION_RULES = (
    "[工具执行规则]:\n"
    "当用户要求你拍照、截图、发送图片、查看图片内容时，必须先调用对应工具再回答。\n"
    "当用户要求比较多张图片、综合多张图片、或根据多张图片作答时，必须先调用 inspect_images 再回答。\n"
    "当用户要求联网搜索、搜索网页、查询今日热点、今日新闻、最新热点、新闻摘要时，必须先调用 search_web_duckduckgo 再回答；查普通网页优先用 text，查新闻/热点优先用 news。\n"
    "在工具真正成功之前，不要声称“已经发给你了”“我已经看到了”“我已经拍好了”。\n"
    "如果工具失败，要明确告诉用户失败原因，而不是假装已经完成。"
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


def _system_message(
    extra_sections: list[tuple[str, Path]] | None = None,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, str]:
    ensure_memory_layout()
    memory_snapshot = snapshot or read_prompt_snapshot(max_rounds=CONTEXT_WINDOW_ROUNDS)
    parts = _base_system_parts(memory_snapshot)

    for title, path in extra_sections or []:
        content = _read_text_section(path)
        if content:
            parts.append(f"{title}:\n{content}\n")

    parts.append(IMAGE_RESOURCE_RULES)
    parts.append(TOOL_EXECUTION_RULES)
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
    llm = PatchedChatOpenAI(
        model=config["gpt_model"],
        api_key=config["gpt_api_key"],
        base_url=config["gpt_base_url"],
        temperature=0,
        use_responses_api=False,
    )
    return create_react_agent(llm, tools=CHAT_TOOLS + CHAT_EXTRA_TOOLS)


def build_heart():
    llm = PatchedChatOpenAI(
        model=config["heart_model"],
        api_key=config["heart_api_key"],
        base_url=config["heart_base_url"],
        temperature=0,
        use_responses_api=False,
    )
    return create_react_agent(llm, tools=HEART_TOOLS + HEART_EXTRA_TOOLS)


def build_sleep():
    llm = PatchedChatOpenAI(
        model=config.get("sleep_model", config["heart_model"]),
        api_key=config.get("sleep_api_key", config["heart_api_key"]),
        base_url=config.get("sleep_base_url", config["heart_base_url"]),
        temperature=0,
        use_responses_api=False,
    )
    return create_react_agent(llm, tools=SLEEP_TOOLS + SLEEP_EXTRA_TOOLS)


def build_emotion():
    llm = PatchedChatOpenAI(
        model=config["emotion_model"],
        api_key=config["emotion_api_key"],
        base_url=config["emotion_base_url"],
        temperature=0.8,
        use_responses_api=False,
    )
    return create_react_agent(llm, tools=[])


def image_to_data_url(image_path: Path | str) -> str:
    raw_path = str(image_path)
    if raw_path.startswith(("http://", "https://", "data:", "base64://")):
        return raw_path

    path = Path(raw_path)
    mime_type, _ = mimetypes.guess_type(path.name)
    mime_type = mime_type or "application/octet-stream"
    image_base64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{image_base64}"


def build_input(
    user_prompt: str,
    session_id: str = DEFAULT_SESSION_ID,
    enable_picture: bool = False,
    image_path: str = "",
) -> dict[str, list[dict[str, str]]]:
    clean_prompt = normalize_user_prompt(user_prompt)
    snapshot = read_prompt_snapshot(max_rounds=CONTEXT_WINDOW_ROUNDS, session_id=session_id)
    messages = [_system_message(snapshot=snapshot)]
    messages.extend(snapshot["recent_messages"])

    if enable_picture:
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": clean_prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_to_data_url(image_path),
                        },
                    },
                ],
            }
        )
    else:
        messages.append({"role": "user", "content": clean_prompt})
    return {"messages": messages}


def build_heart_input(user_prompt: str) -> dict[str, list[dict[str, str]]]:
    snapshot = read_prompt_snapshot(max_rounds=CONTEXT_WINDOW_ROUNDS)
    return {
        "messages": [
            _system_message(extra_sections=HEART_SECTIONS, snapshot=snapshot),
            {"role": "user", "content": user_prompt},
        ]
    }


def build_sleep_input(user_prompt: str) -> dict[str, list[dict[str, str]]]:
    snapshot = read_prompt_snapshot(max_rounds=CONTEXT_WINDOW_ROUNDS)
    return {
        "messages": [
            _system_message(extra_sections=SLEEP_SECTIONS, snapshot=snapshot),
            {"role": "user", "content": user_prompt},
        ]
    }


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
    enable_picture: bool = False,
    image_path: str = "",
) -> Iterator[str]:
    clean_prompt = normalize_user_prompt(user_prompt)
    payload = build_input(clean_prompt, session_id=session_id,enable_picture=enable_picture,image_path=image_path)
    for chunk, metadata in agent.stream(payload, stream_mode="messages"):
        if should_interrupt and should_interrupt():
            return
        if metadata.get("langgraph_node") != "agent":
            continue
        for text in _iter_text_fragments(getattr(chunk, "content", "")):
            yield text


def stream_logic_events(
    agent,
    user_prompt: str,
    session_id: str = DEFAULT_SESSION_ID,
    should_interrupt: Callable[[], bool] | None = None,
    enable_picture: bool = False,
    image_path: str = "",
) -> Iterator[dict]:
    """yield 结构化事件: tool_call / tool_result / text"""
    clean_prompt = normalize_user_prompt(user_prompt)
    payload = build_input(clean_prompt, session_id=session_id, enable_picture=enable_picture, image_path=image_path)
    for chunk, metadata in agent.stream(payload, stream_mode="messages"):
        if should_interrupt and should_interrupt():
            return
        node = metadata.get("langgraph_node")
        if node == "agent":
            tool_calls = getattr(chunk, "tool_calls", None)
            if tool_calls:
                for tc in tool_calls:
                    yield {"type": "tool_call", "name": tc.get("name", ""), "input": tc.get("args", {})}
            for text in _iter_text_fragments(getattr(chunk, "content", "")):
                yield {"type": "text", "content": text}
        elif node == "tools":
            name = getattr(chunk, "name", "")
            content = getattr(chunk, "content", "")
            if isinstance(content, list):
                content = " ".join(str(c) for c in content)
            yield {"type": "tool_result", "name": name, "output": str(content)}


def run_logic(
    agent,
    user_prompt: str,
    session_id: str = DEFAULT_SESSION_ID,
    should_interrupt: Callable[[], bool] | None = None,
    enable_picture: bool = False,
    image_path: str = "",
) -> str:
    return "".join(stream_logic(agent, user_prompt, session_id=session_id, should_interrupt=should_interrupt,enable_picture=enable_picture,image_path=image_path)).strip()


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


def stream_emotion(
    agent,
    user_prompt: str,
    logic_reply: str,
    session_id: str = DEFAULT_SESSION_ID,
    should_interrupt: Callable[[], bool] | None = None,
) -> Iterator[str]:
    payload = build_emotion_input(user_prompt, logic_reply, session_id=session_id)
    for chunk, metadata in agent.stream(payload, stream_mode="messages"):
        if should_interrupt and should_interrupt():
            return
        if metadata.get("langgraph_node") != "agent":
            continue
        for text in _iter_text_fragments(getattr(chunk, "content", "")):
            yield text


def run_heart(
    agent,
    user_prompt: str,
    show_output: bool = False,
    should_interrupt: Callable[[], bool] | None = None,
) -> str:
    return _stream_agent_response(
        agent,
        build_heart_input(user_prompt),
        show_output=show_output,
        should_interrupt=should_interrupt,
    )


def run_sleep(
    agent,
    user_prompt: str,
    show_output: bool = False,
    should_interrupt: Callable[[], bool] | None = None,
) -> str:
    return _stream_agent_response(
        agent,
        build_sleep_input(user_prompt),
        show_output=show_output,
        should_interrupt=should_interrupt,
    )
