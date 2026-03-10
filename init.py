from __future__ import annotations

import json
from pathlib import Path

from skills import read_memory, run_command, update_memory, read_heartbeat      
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

system_message = {"role": "system", "content": ""}
history_messages = []

BASE_DIR = Path(__file__).resolve().parent
MEMORY_DIR = BASE_DIR / "memory"
CONFIG_PATH = BASE_DIR / "config.json"
MEMORY_PATH = MEMORY_DIR / "MEMORY.md"

with CONFIG_PATH.open("r", encoding="utf-8") as f:
    config = json.load(f)

memory_sections = [
    ("[系统信息]", MEMORY_DIR / "AGENT.md"),
    ("[你的身份]", MEMORY_DIR / "ROLE.md"),
    ("[你的关系网络]", MEMORY_DIR / "RELATION.md"),
    ("[你的灵魂]", MEMORY_DIR / "SOUL.md"),
    ("[你的长期记忆]", MEMORY_PATH),
    ("[你的经验和教训]", MEMORY_DIR / "LEARN.md"),
]

for title, path in memory_sections:
    with path.open("r", encoding="utf-8") as f:
        system_message["content"] += f"[{title}]:\n{f.read()}\n"

system_message["content"] += "[当前发言人]:秦滔\n"


def build_agent():
    llm = ChatOpenAI(
        model=config["model"],
        api_key=config["api_key"],
        base_url=config["base_url"],
        temperature=0,
    )
    return create_react_agent(llm, tools=[run_command, read_memory, update_memory, read_heartbeat])



def build_input(user_prompt: str) -> dict:
    global history_messages, system_message
    messages = [system_message] + history_messages + [{"role": "user", "content": user_prompt}]
    return {"messages": messages}



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



def run_once(agent, user_prompt: str) -> None:
    result = agent.invoke(build_input(user_prompt))
    print("\n=== LangGraph 消息轨迹 ===")
    for message in result["messages"]:
        try:
            print(message.pretty_repr())
        except AttributeError:
            print(message)

    final_message = result["messages"][-1]
    final_content = getattr(final_message, "content", final_message)

    print("\n=== 最终回答 ===")
    print(final_content)



def run_stream(agent, user_prompt: str) -> None:
    global history_messages, system_message
    full_response = ""
    print("秦熹微：", end="", flush=True)
    for chunk, metadata in agent.stream(build_input(user_prompt), stream_mode="messages"):
        if metadata.get("langgraph_node") != "agent":
            continue
        for text in _iter_text_fragments(getattr(chunk, "content", "")):
            print(text, end="", flush=True)
            full_response += text
    history_messages.extend(
        [
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": full_response},
        ]
    )
    print("\n")
