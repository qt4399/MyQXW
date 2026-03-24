from __future__ import annotations

import base64
import json
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
from openai import OpenAI

from memory.image_store import extract_image_ids, resolve_image_ref

PROJECT_DIR = Path(__file__).resolve().parents[2]
CAPTURE_DIR = PROJECT_DIR / "logs" / "captures"
SCREENSHOT_DIR = PROJECT_DIR / "logs" / "screenshots"
CONFIG_PATH = PROJECT_DIR / "config.json"
DEFAULT_IMAGE_PROMPT = "请识别这张图片里有什么，并尽量详细描述关键信息。"
DEFAULT_MULTI_IMAGE_PROMPT = "请结合这些图片一起分析，并根据用户要求作答；如果存在差异、顺序或对应关系，也请明确指出。"


def _load_config() -> dict[str, str]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _timestamped_image_path(directory: Path, prefix: str, suffix: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return directory / f"{prefix}_{timestamp}{suffix}"

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

        output_path = _timestamped_image_path(CAPTURE_DIR, "capture", ".jpg")

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


def _capture_screenshot_result() -> dict[str, object]:
    """截取当前桌面屏幕并保存为 PNG 文件。"""
    try:
        from mss import mss
        from mss import tools as mss_tools
    except ImportError:
        return {
            "returncode": 1,
            "stdout": "",
            "stderr": "缺少依赖 mss，请先执行 pip install -r requirements.txt",
            "image_path": "",
        }

    output_path = _timestamped_image_path(SCREENSHOT_DIR, "screenshot", ".png")

    try:
        with mss() as sct:
            monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            screenshot = sct.grab(monitor)
            mss_tools.to_png(screenshot.rgb, screenshot.size, output=str(output_path))
            return {
                "returncode": 0,
                "stdout": f"截图成功，图片已保存到 {output_path}",
                "stderr": "",
                "image_path": str(output_path),
                "image_format": "png",
                "width": int(screenshot.width),
                "height": int(screenshot.height),
            }
    except Exception as exc:
        return {
            "returncode": 1,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
            "image_path": "",
        }

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
        for key in ("image_input", "image_path", "image_file", "file", "image_id", "id"):
            value = str(payload.get(key, "")).strip()
            if value:
                return _normalize_image_ref(value)

        base64_value = str(payload.get("image_base64", "")).strip()
        if base64_value:
            return _normalize_image_ref(base64_value)

    return _normalize_image_ref(clean)


def _collect_image_inputs(payload: Any) -> list[str]:
    values: list[str] = []

    if isinstance(payload, list):
        for item in payload:
            values.extend(_collect_image_inputs(item))
        return values

    if isinstance(payload, dict):
        for key in ("image_inputs", "images", "image_refs", "image_paths", "image_ids", "ids"):
            raw = payload.get(key)
            if isinstance(raw, list):
                values.extend(_collect_image_inputs(raw))
                return values

        for key in ("image_input", "image_path", "image_file", "file", "image_id", "id", "image_ref"):
            value = str(payload.get(key, "")).strip()
            if value:
                values.append(value)
                return values

        base64_value = str(payload.get("image_base64", "")).strip()
        if base64_value:
            values.append(base64_value)
        return values

    value = str(payload or "").strip()
    if value:
        values.append(value)
    return values


def _extract_image_refs(image_input: str) -> list[str]:
    clean = str(image_input or "").strip()
    if not clean:
        raise ValueError("image_input 不能为空")

    refs: list[str] = []
    try:
        payload = json.loads(clean)
    except json.JSONDecodeError:
        payload = None

    if payload is not None:
        refs.extend(_collect_image_inputs(payload))
    else:
        extracted_ids = extract_image_ids(clean)
        if extracted_ids:
            refs.extend(extracted_ids)
        else:
            refs.append(clean)

    normalized_refs: list[str] = []
    for value in refs:
        normalized = _normalize_image_ref(str(value or "").strip())
        if normalized and normalized not in normalized_refs:
            normalized_refs.append(normalized)

    if not normalized_refs:
        raise ValueError("未找到可用的图片引用")
    return normalized_refs


def _normalize_image_ref(value: str) -> str:
    """ 标准化图片引用，支持 base64、URL 和文件路径 """
    clean = resolve_image_ref(value.strip())
    if not clean:
        raise ValueError("图片引用不能为空")

    if clean.startswith(("base64://", "data:image/", "http://", "https://")):
        return clean

    candidate = Path(clean).expanduser()
    if candidate.exists():
        return str(candidate.resolve())

    if any(sep in clean for sep in ("/", "\\")) or Path(clean).suffix:
        raise FileNotFoundError(f"图片文件不存在: {clean}")

    # 允许直接传裸 base64，自动补成 NapCat 可识别的格式
    return f"base64://{clean}"


def _image_ref_to_model_url(image_ref: str) -> str:
    clean = _normalize_image_ref(image_ref)
    if clean.startswith(("http://", "https://", "data:")):
        return clean

    if clean.startswith("base64://"):
        return f"data:image/jpeg;base64,{clean[len('base64://'):]}"

    path = Path(clean).expanduser().resolve()
    mime_type, _ = mimetypes.guess_type(path.name)
    mime_type = mime_type or "application/octet-stream"
    image_base64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{image_base64}"


def _build_picture_message(image_ref: str, text: str) -> list[dict[str, Any]]:
    """ 构建包含图片和文本的消息 """
    message: list[dict[str, Any]] = []
    clean_text = text.strip()
    if clean_text:
        message.append({"type": "text", "data": {"text": clean_text}})
    message.append({"type": "image", "data": {"file": image_ref}})
    return message


def _inspect_image_result(image_input: str, prompt: str = DEFAULT_IMAGE_PROMPT) -> dict[str, object]:
    image_refs = _extract_image_refs(image_input)
    if len(image_refs) != 1:
        raise ValueError("inspect_image 只支持单张图片；如果要联合查看多张图片，请改用 inspect_images")
    image_ref = image_refs[0]
    config = _load_config()
    client = OpenAI(
        api_key=config["gpt_api_key"],
        base_url=config["gpt_base_url"],
    )

    response = client.responses.create(
        model=config["gpt_model"],
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt.strip() or DEFAULT_IMAGE_PROMPT},
                    {"type": "input_image", "image_url": _image_ref_to_model_url(image_ref)},
                ],
            }
        ],
    )

    return {
        "returncode": 0,
        "stdout": response.output_text.strip(),
        "stderr": "",
        "image_ref": image_ref,
        "model": config["gpt_model"],
    }


def _inspect_images_result(image_input: str, prompt: str = DEFAULT_MULTI_IMAGE_PROMPT) -> dict[str, object]:
    image_refs = _extract_image_refs(image_input)
    config = _load_config()
    client = OpenAI(
        api_key=config["gpt_api_key"],
        base_url=config["gpt_base_url"],
    )

    content: list[dict[str, Any]] = [
        {"type": "input_text", "text": prompt.strip() or DEFAULT_MULTI_IMAGE_PROMPT},
    ]
    for index, image_ref in enumerate(image_refs, start=1):
        content.append({"type": "input_text", "text": f"[图片{index}]"})
        content.append({"type": "input_image", "image_url": _image_ref_to_model_url(image_ref)})

    response = client.responses.create(
        model=config["gpt_model"],
        input=[
            {
                "role": "user",
                "content": content,
            }
        ],
    )

    return {
        "returncode": 0,
        "stdout": response.output_text.strip(),
        "stderr": "",
        "image_refs": image_refs,
        "image_count": len(image_refs),
        "model": config["gpt_model"],
    }
