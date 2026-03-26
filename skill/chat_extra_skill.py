from __future__ import annotations

import json


from langchain_core.tools import tool

from logic.runtime_context import get_current_session_id, record_assistant_image_tag
from memory.image_store import (
    build_image_tag,
    extract_image_ids,
    find_image_by_ref,
    read_image,
    save_image_ref,
)
from memory.memory_store import ensure_memory_layout
from qq_api_reference.napcat_api import NapCatAPI
from skill.tools.visual_tools import (
    DEFAULT_IMAGE_PROMPT,
    DEFAULT_MULTI_IMAGE_PROMPT,
    _build_picture_message,
    _capture_photo_result,
    _capture_screenshot_result,
    _extract_image_ref,
    _inspect_image_result,
    _inspect_images_result,
)
from skill.tools.web_search_tools import search_web_duckduckgo_result
from skill.tools.qq_tools import _parse_qq_session_id
import cv2

ensure_memory_layout()

def _json_result(**payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _extract_nested_image_id(value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""

    extracted_ids = extract_image_ids(clean)
    if extracted_ids:
        return extracted_ids[0]

    try:
        payload = json.loads(clean)
    except json.JSONDecodeError:
        return ""

    if not isinstance(payload, dict):
        return ""

    image_id = str(payload.get("image_id") or payload.get("id") or "").strip()
    if image_id:
        return image_id

    image_tag = str(payload.get("image_tag", "")).strip()
    extracted_ids = extract_image_ids(image_tag)
    if extracted_ids:
        return extracted_ids[0]

    return ""


@tool("obtain_photo")
def obtain_photo() -> str:
    """额外工具：截取电脑外置摄像头画面并保存为 JPEG 文件，返回图片路径和拍摄状态。"""
    print(f"[chat] 获取摄像头画面")
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        return _json_result(
            returncode=1,
            stdout="",
            stderr="无法打开摄像头",
            image_path="",
        )

    result = _capture_photo_result(cap)
    if int(result.get("returncode", 1)) != 0:
        return _json_result(**result)

    image_path = str(result.get("image_path", "")).strip()
    image_record = save_image_ref(
        image_path,
        session_id=get_current_session_id(),
        source="camera",
    )
    result["image_id"] = image_record["id"]
    result["image_tag"] = build_image_tag(image_record["id"])
    return _json_result(**result)


@tool("capture_screenshot")
def capture_screenshot() -> str:
    """额外工具：截取当前电脑屏幕并保存为 PNG 文件，返回图片路径和截图状态。"""
    print("[chat] 截取当前屏幕")
    result = _capture_screenshot_result()
    if int(result.get("returncode", 1)) != 0:
        return _json_result(**result)

    image_path = str(result.get("image_path", "")).strip()
    image_record = save_image_ref(
        image_path,
        session_id=get_current_session_id(),
        source="screenshot",
    )
    result["image_id"] = image_record["id"]
    result["image_tag"] = build_image_tag(image_record["id"])
    return _json_result(**result)


@tool("inspect_image")
def inspect_image(image_input: str, prompt: str = DEFAULT_IMAGE_PROMPT) -> str:
    """视觉工具：查看一张图片。image_input 支持 image_id、图片路径、URL、data URL 或 base64。多图请改用 inspect_images。"""
    print(f"[chat] 查看图片: {image_input}")
    try:
        clean_image_input = str(image_input or "").strip()
        clean_prompt = str(prompt or "").strip() or DEFAULT_IMAGE_PROMPT
        return _json_result(**_inspect_image_result(clean_image_input, clean_prompt))
    except Exception as exc:
        return _json_result(
            returncode=1,
            stdout="",
            stderr=f"{type(exc).__name__}: {exc}",
        )


@tool("inspect_images")
def inspect_images(image_input: str, prompt: str = DEFAULT_MULTI_IMAGE_PROMPT) -> str:
    """视觉工具：联合查看多张图片。image_input 支持 JSON 数组/对象，或包含多个 <image id=\"...\" /> 的文本。"""
    print(f"[chat] 联合查看多张图片: {image_input}")
    try:
        clean_image_input = str(image_input or "").strip()
        clean_prompt = str(prompt or "").strip() or DEFAULT_MULTI_IMAGE_PROMPT
        return _json_result(**_inspect_images_result(clean_image_input, clean_prompt))
    except Exception as exc:
        return _json_result(
            returncode=1,
            stdout="",
            stderr=f"{type(exc).__name__}: {exc}",
        )



@tool("search_web_duckduckgo")
def search_web_duckduckgo(query: str, search_type: str = "text", max_results: int = 10) -> str:
    """使用 DuckDuckGo 联网搜索。search_type 支持 text 和 news；查普通网页用 text，查新闻/热点用 news。返回标题、摘要和链接。"""
    print(f"[chat] DuckDuckGo 搜索: query={query}, search_type={search_type}, max_results={max_results}")
    try:
        return _json_result(
            **search_web_duckduckgo_result(
                query=query,
                search_type=search_type,
                max_results=max_results,
            )
        )
    except Exception as exc:
        return _json_result(
            returncode=1,
            stdout="",
            stderr=f"{type(exc).__name__}: {exc}",
            query=str(query or "").strip(),
            total=0,
            results=[],
        )


@tool("send_picture_qq")
def send_picture_qq(image_input: str, session_id: str = "") -> str:
    """额外工具：把图片发送到 QQ 会话。image_input 支持 image_id、图片路径、URL、data URL 或 base64；未提供 session_id 时默认发送到当前会话。"""
    print(f"[chat] 发送 QQ 图片: image_input={image_input}, session_id={session_id}")

    image_id = ""
    image_tag = ""
    try:
        current_session_id = str(get_current_session_id() or "").strip()
        clean_session_id = str(session_id or "").strip() or current_session_id
        clean_image_input = str(image_input or "").strip()

        chat_type, target_id = _parse_qq_session_id(clean_session_id)
        image_ref = _extract_image_ref(clean_image_input)
        image_id = _extract_nested_image_id(clean_image_input)
        if not image_id:
            extracted_ids = extract_image_ids(clean_image_input)
            if extracted_ids:
                image_id = extracted_ids[0]

        if image_id:
            try:
                read_image(image_id)
            except (KeyError, ValueError):
                image_id = ""

        if not image_id:
            image_record = find_image_by_ref(
                image_ref,
                session_id=clean_session_id or current_session_id or None,
            )
            if image_record is None:
                image_record = save_image_ref(
                    image_ref,
                    session_id=clean_session_id or current_session_id or None,
                    source="assistant_send",
                )
            image_id = str(image_record["id"]).strip()

        image_tag = build_image_tag(image_id)
        message = _build_picture_message(image_ref, "")
    except Exception as exc:
        return _json_result(
            returncode=1,
            stdout="",
            stderr=f"{type(exc).__name__}: {exc}",
            session_id=clean_session_id if "clean_session_id" in locals() else "",
            image_id=image_id,
        )

    with NapCatAPI() as api:
        if chat_type == "private":
            result = api.send_private_msg(target_id, message)
        else:
            result = api.send_group_msg(target_id, message)

    record_assistant_image_tag(image_tag, session_id=clean_session_id)
    return _json_result(
        returncode=0,
        stdout="图片发送成功",
        stderr="",
        session_id=clean_session_id,
        chat_type=chat_type,
        target_id=target_id,
        data=result,
    )


CHAT_EXTRA_TOOLS = [
    obtain_photo,
    capture_screenshot,
    inspect_image,
    inspect_images,
    search_web_duckduckgo,
    send_picture_qq,
]
