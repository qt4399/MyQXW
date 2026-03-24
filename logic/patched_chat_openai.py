from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI


def _normalize_tool_call_id(value: str) -> str:
    clean = str(value or "").strip()
    if clean.startswith("call_"):
        return f"fc_{clean[5:]}"
    return clean


def _normalize_chat_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for message in messages:
        item = dict(message)

        tool_calls = item.get("tool_calls")
        if isinstance(tool_calls, list):
            normalized_tool_calls = []
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    normalized_tool_calls.append(tool_call)
                    continue
                updated_tool_call = dict(tool_call)
                if isinstance(updated_tool_call.get("id"), str):
                    updated_tool_call["id"] = _normalize_tool_call_id(updated_tool_call["id"])
                normalized_tool_calls.append(updated_tool_call)
            item["tool_calls"] = normalized_tool_calls

        if isinstance(item.get("tool_call_id"), str):
            item["tool_call_id"] = _normalize_tool_call_id(item["tool_call_id"])

        normalized.append(item)
    return normalized


def _normalize_responses_input(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            normalized.append(item)
            continue

        updated = dict(item)
        if isinstance(updated.get("call_id"), str):
            updated["call_id"] = _normalize_tool_call_id(updated["call_id"])
        if updated.get("type") == "function_call" and isinstance(updated.get("id"), str):
            updated["id"] = _normalize_tool_call_id(updated["id"])
        normalized.append(updated)
    return normalized


class PatchedChatOpenAI(ChatOpenAI):
    """兼容上游要求 fc_ 前缀 tool-call id 的 OpenAI 聊天模型封装。"""

    def _get_request_payload(
        self,
        input_: Any,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)

        messages = payload.get("messages")
        if isinstance(messages, list):
            payload["messages"] = _normalize_chat_messages(messages)

        input_items = payload.get("input")
        if isinstance(input_items, list):
            payload["input"] = _normalize_responses_input(input_items)

        return payload
