from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from memory.memory_store import (
    STORAGE_LOCK,
    YAML_DIR,
    _read_yaml,
    _write_yaml,
    ensure_memory_layout,
    normalize_session_id,
    now_iso,
)

IMAGE_STORE_PATH = YAML_DIR / "images.yaml"
IMAGE_TAG_PATTERN = re.compile(r'<image\s+id="([^"]+)"\s*/?>')


def _default_image_store() -> dict[str, Any]:
    return {
        "version": 1,
        "images": {},
    }


def _normalize_image_store(data: dict[str, Any]) -> dict[str, Any]:
    root = dict(_default_image_store())
    root.update(data if isinstance(data, dict) else {})

    images: dict[str, dict[str, Any]] = {}
    raw_images = root.get("images")
    if isinstance(raw_images, dict):
        for image_id, item in raw_images.items():
            if not isinstance(item, dict):
                continue
            image_key = str(image_id).strip()
            if not image_key:
                continue
            payload = dict(item)
            payload["id"] = image_key
            payload["image_ref"] = str(payload.get("image_ref", "")).strip()
            payload["session_id"] = normalize_session_id(payload.get("session_id"))
            images[image_key] = payload

    root["images"] = images
    return root


def ensure_image_store() -> None:
    with STORAGE_LOCK:
        ensure_memory_layout()
        _read_yaml(IMAGE_STORE_PATH, _default_image_store())


def save_image_ref(image_ref: str, *, session_id: str | None = None, source: str = "unknown") -> dict[str, Any]:
    clean_ref = str(image_ref or "").strip()
    if not clean_ref:
        raise ValueError("image_ref 不能为空")

    with STORAGE_LOCK:
        ensure_image_store()
        root = _normalize_image_store(_read_yaml(IMAGE_STORE_PATH, _default_image_store()))
        image_id = f"img_{uuid4().hex[:12]}"
        record = {
            "id": image_id,
            "created_at": now_iso(),
            "session_id": normalize_session_id(session_id),
            "source": str(source or "unknown").strip() or "unknown",
            "image_ref": clean_ref,
        }
        root["images"][image_id] = record
        _write_yaml(IMAGE_STORE_PATH, root)
        return dict(record)


def find_image_by_ref(image_ref: str, *, session_id: str | None = None) -> dict[str, Any] | None:
    clean_ref = str(image_ref or "").strip()
    if not clean_ref:
        return None

    session_key = normalize_session_id(session_id)

    with STORAGE_LOCK:
        ensure_image_store()
        root = _normalize_image_store(_read_yaml(IMAGE_STORE_PATH, _default_image_store()))
        images = list(root.get("images", {}).values())
        for record in reversed(images):
            if not isinstance(record, dict):
                continue
            if str(record.get("image_ref", "")).strip() != clean_ref:
                continue
            if session_key and str(record.get("session_id", "")).strip() != session_key:
                continue
            return dict(record)

    return None


def read_image(image_id: str) -> dict[str, Any]:
    clean_id = str(image_id or "").strip()
    if not clean_id:
        raise ValueError("image_id 不能为空")

    with STORAGE_LOCK:
        ensure_image_store()
        root = _normalize_image_store(_read_yaml(IMAGE_STORE_PATH, _default_image_store()))
        record = root.get("images", {}).get(clean_id)
        if not isinstance(record, dict):
            raise KeyError(f"图片不存在: {clean_id}")
        return dict(record)


def extract_image_ids(text: str) -> list[str]:
    return IMAGE_TAG_PATTERN.findall(str(text or ""))


def strip_image_tags(text: str) -> str:
    return IMAGE_TAG_PATTERN.sub("", str(text or ""))


def build_image_tag(image_id: str) -> str:
    clean_id = str(image_id or "").strip()
    if not clean_id:
        raise ValueError("image_id 不能为空")
    return f'<image id="{clean_id}" />'


def resolve_image_ref(value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise ValueError("图片引用不能为空")

    candidates = [clean]
    candidates.extend(extract_image_ids(clean))

    for candidate in candidates:
        try:
            return str(read_image(candidate).get("image_ref", "")).strip()
        except (KeyError, ValueError):
            continue

    return clean
