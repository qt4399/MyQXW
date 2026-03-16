#!/usr/bin/env python3

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path

from openai import OpenAI

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"

# 直接改这两行就能测试
IMAGE_PATH = BASE_DIR / "2.png"
PROMPT = "请识别这张图片里有什么。简略一点"


def load_config() -> dict[str, str]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def image_to_data_url(image_path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(image_path.name)
    mime_type = mime_type or "application/octet-stream"
    image_base64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{image_base64}"


config = load_config()
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
                {"type": "input_text", "text": PROMPT},
                {"type": "input_image", "image_url": image_to_data_url(IMAGE_PATH)},
            ],
        }
    ],
)

print(response.output_text)
