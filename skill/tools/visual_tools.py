from typing import Any
from pathlib import Path
import cv2
from datetime import datetime
import json

BASE_DIR = Path(__file__).resolve().parent.parent
CAPTURE_DIR = BASE_DIR / "logs" / "captures"

def _capture_photo_result(cap) -> dict[str, object]:
    """ 拍照并保存到文件 """
    try:
        ret, frame = cap.read()
        if not ret or frame is None:
            return {
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
                "returncode": 1,
                "stdout": "",
                "stderr": "图片写入文件失败",
                "image_path": "",
            }

        height, width = frame.shape[:2]
        return {
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

def _extract_image_ref(image_input: str) -> str:
    """ 从用户输入中提取图片引用 ,标准输出 """
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
    """ 标准化图片引用，支持 base64、URL 和文件路径 """
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
    """ 构建包含图片和文本的消息 """
    message: list[dict[str, Any]] = []
    clean_text = text.strip()
    if clean_text:
        message.append({"type": "text", "data": {"text": clean_text}})
    message.append({"type": "image", "data": {"file": image_ref}})
    return message