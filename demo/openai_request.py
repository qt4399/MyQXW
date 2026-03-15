#!/usr/bin/env python3

from __future__ import annotations
import readline
from openai import OpenAI

BASE_URL = "http://127.0.0.1:8000/v1"
MODEL = "myqxw"


def chat_once(client: OpenAI, message: str) -> None:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": message}],
        stream=False,
    )
    print("assistant:", response.choices[0].message.content)


def chat_stream(client: OpenAI, message: str) -> None:
    stream = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": message}],
        stream=True,
    )
    print("assistant: ", end="", flush=True)
    for chunk in stream:
        delta = chunk.choices[0].delta.content or ""
        if delta:
            print(delta, end="", flush=True)
    print()


def main() -> None:
    client = OpenAI(base_url=BASE_URL, api_key="dummy")
    while True:
        message = input("you: ").strip()
        if not message:
            continue
        if message.lower() == "quit":
            break
        try:
            chat_stream(client, message)
        except Exception as exc:
            print(f"[error] {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
