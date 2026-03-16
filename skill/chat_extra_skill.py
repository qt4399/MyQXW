from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from logic.runtime_context import get_current_session_id
from memory.memory_store import ensure_memory_layout
from qq_api_reference.napcat_api import NapCatAPI

try:
    import cv2
except ImportError:
    cv2 = None

ensure_memory_layout()
BASE_DIR = Path(__file__).resolve().parent.parent
CAPTURE_DIR = BASE_DIR / "logs" / "captures"


def _json_result(**payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool("obtain_photo")
def obtain_photo(command: str) -> str:
    """额外工具：截取摄像头画面并保存为 JPEG 文件，返回图片路径和拍摄状态。"""
    print(f"[chat] 获取摄像头画面: {command}")
    if cv2 is None:
        return _json_result(
            command=command,
            returncode=1,
            stdout="",
            stderr="当前环境未安装 opencv-python，无法调用摄像头",
            image_path="",
        )

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        return _json_result(
            command=command,
            returncode=1,
            stdout="",
            stderr="无法打开摄像头",
            image_path="",
        )

    return _json_result(
        **_capture_photo_result(cap, command)
    )


def _capture_photo_result(cap, command: str) -> dict[str, object]:
    try:
        ret, frame = cap.read()
        if not ret or frame is None:
            return {
                "command": command,
                "returncode": 1,
                "stdout": "",
                "stderr": "摄像头拍照失败",
                "image_path": "",
            }

        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        output_path = CAPTURE_DIR / f"capture_{timestamp}.jpg"

        encoded = cv2.imwrite(str(output_path), frame)
        if not encoded:
            return {
                "command": command,
                "returncode": 1,
                "stdout": "",
                "stderr": "图片写入文件失败",
                "image_path": "",
            }

        height, width = frame.shape[:2]
        return {
            "command": command,
            "returncode": 0,
            "stdout": f"拍照成功，图片已保存到 {output_path}",
            "stderr": "",
            "image_path": str(output_path),
            "image_format": "jpeg",
            "width": width,
            "height": height,
        }
    finally:
        cap.release()


def _parse_qq_session_id(session_id: str | None) -> tuple[str, str]:
    clean = str(session_id or "").strip()
    parts = clean.split(":", 2)
    if len(parts) != 3 or parts[0] != "qq" or parts[1] not in {"private", "group"}:
        raise ValueError(f"当前会话不是可发送图片的 QQ 会话: {clean or '空'}")
    return parts[1], parts[2]


def _extract_image_ref(image_input: str) -> str:
    clean = str(image_input or "").strip()
    if not clean:
        raise ValueError("image_input 不能为空")

    try:
        payload = json.loads(clean)
    except json.JSONDecodeError:
        payload = None

    if isinstance(payload, dict):
        for key in ("image_path", "image_file", "file"):
            value = str(payload.get(key, "")).strip()
            if value:
                return _normalize_image_ref(value)

        base64_value = str(payload.get("image_base64", "")).strip()
        if base64_value:
            return _normalize_image_ref(base64_value)

    return _normalize_image_ref(clean)


def _normalize_image_ref(value: str) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError("图片引用不能为空")

    if clean.startswith(("base64://", "data:image/", "http://", "https://")):
        return clean

    candidate = Path(clean).expanduser()
    if candidate.exists():
        return str(candidate.resolve())

    # 允许直接传裸 base64，自动补成 NapCat 可识别的格式
    return f"base64://{clean}"


def _build_picture_message(image_ref: str, text: str) -> list[dict[str, Any]]:
    message: list[dict[str, Any]] = []
    clean_text = text.strip()
    if clean_text:
        message.append({"type": "text", "data": {"text": clean_text}})
    message.append({"type": "image", "data": {"file": image_ref}})
    return message


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
