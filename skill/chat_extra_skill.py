from __future__ import annotations

import json
from datetime import datetime

from langchain_core.tools import tool

from logic.runtime_context import get_current_session_id
from memory.memory_store import ensure_memory_layout
from qq_api_reference.napcat_api import NapCatAPI
from skill.tools.visual_tools import _extract_image_ref, _build_picture_message, _capture_photo_result
from skill.tools.qq_tools import _parse_qq_session_id
import cv2

ensure_memory_layout()

def _json_result(**payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool("obtain_photo")
def obtain_photo() -> str:
    """额外工具：截取摄像头画面并保存为 JPEG 文件，返回图片路径和拍摄状态。"""
    print(f"[chat] 获取摄像头画面")
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        return _json_result(
            returncode=1,
            stdout="",
            stderr="无法打开摄像头",
            image_path="",
        )

    return _json_result(
        **_capture_photo_result(cap)
    )




@tool("send_picture_qq")
def send_picture_qq(command: str) -> str:
    """额外工具：把图片发送到 QQ 会话。参数必须是 JSON 字符串，包含 image_input，可选 text 和 session_id。未提供 session_id 时默认发送到当前会话。"""
    print(f"[chat] 发送 QQ 图片: {command}")

    session_id = ""
    try:
        payload = json.loads(command)
        if not isinstance(payload, dict):
            raise ValueError("command 必须是 JSON 对象")

        current_session_id = str(get_current_session_id() or "").strip()
        session_id = str(payload.get("session_id", "")).strip() or current_session_id
        image_input = str(payload.get("image_input", "")).strip()
        text = str(payload.get("text", "")).strip()

        chat_type, target_id = _parse_qq_session_id(session_id)
        image_ref = _extract_image_ref(image_input)
        message = _build_picture_message(image_ref, text)
    except Exception as exc:
        return _json_result(
            returncode=1,
            stdout="",
            stderr=f"{type(exc).__name__}: {exc}",
            session_id=session_id,
        )

    with NapCatAPI() as api:
        if chat_type == "private":
            result = api.send_private_msg(target_id, message)
        else:
            result = api.send_group_msg(target_id, message)

    return _json_result(
        returncode=0,
        stdout="图片发送成功",
        stderr="",
        session_id=session_id,
        chat_type=chat_type,
        target_id=target_id,
        data=result,
    )


CHAT_EXTRA_TOOLS = [
    obtain_photo,
    send_picture_qq,
]
