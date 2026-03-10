from __future__ import annotations
import os
import sys
import json
from pathlib import Path
#--------------------------------------------------------------------------------
from skills import run_command
#--------------------------------------------------------------------------------
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
#--------------------------------------------------------------------------------
system_message = {"role": "system", "content": ""}
history_messages = []

CONFIG_PATH = Path(__file__).with_name("config.json")
with CONFIG_PATH.open("r", encoding="utf-8") as f:
    config = json.load(f)
with open("memory/ROLE.md", "r", encoding="utf-8") as f:
    system_message["content"] += "[你的身份]:\n" + f.read()+ "\n"
with open("memory/RELATION.md", "r", encoding="utf-8") as f:
    system_message["content"] += "[你的关系网络]:\n" + f.read()+ "\n"
with open("memory/SOUL.md", "r", encoding="utf-8") as f:
    system_message["content"] += "[你的灵魂]:\n" + f.read()+ "\n"
with open("memory/MOMERY.md", "r", encoding="utf-8") as f:
    system_message["content"] += "[你的长期记忆]:\n" + f.read()+ "\n"
system_message["content"] += "[当前发言人]:" + "秦滔" + "\n"
def build_agent():
    llm = ChatOpenAI(
        model=config["model"],
        api_key=config["api_key"],
        base_url=config["base_url"],
        temperature=0,
    )
    return create_react_agent(llm, tools=[run_command])

def build_input(user_prompt: str) -> dict:
    global history_messages,system_message
    messages = [system_message] + history_messages + [{"role": "user", "content": user_prompt}]
    return {
        "messages": messages
    }
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
    global history_messages,system_message
    full_response = ""
    print("秦熹微：", end="", flush=True)
    for chunk, metadata in agent.stream(build_input(user_prompt), stream_mode="messages"):
        if metadata.get("langgraph_node") != "agent":
            continue
        for text in _iter_text_fragments(getattr(chunk, "content", "")):
            print(text, end="", flush=True)
            full_response += text
    history_messages.extend([
        {"role": "user", "content": user_prompt},
        {"role": "assistant", "content": full_response}
    ])
    print("\n")