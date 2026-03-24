from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from typing import Iterator

CURRENT_SESSION_ID: ContextVar[str | None] = ContextVar("current_session_id", default=None)
PENDING_ASSISTANT_IMAGE_TAGS: dict[str, list[str]] = {}
PENDING_ASSISTANT_IMAGE_TAGS_LOCK = Lock()


def get_current_session_id() -> str | None:
    return CURRENT_SESSION_ID.get()


def clear_assistant_image_tags(session_id: str | None = None) -> None:
    clean_session_id = str(session_id or get_current_session_id() or "").strip()
    if not clean_session_id:
        return

    with PENDING_ASSISTANT_IMAGE_TAGS_LOCK:
        PENDING_ASSISTANT_IMAGE_TAGS.pop(clean_session_id, None)


def record_assistant_image_tag(tag: str, session_id: str | None = None) -> None:
    clean_tag = str(tag or "").strip()
    clean_session_id = str(session_id or get_current_session_id() or "").strip()
    if not clean_tag or not clean_session_id:
        return

    with PENDING_ASSISTANT_IMAGE_TAGS_LOCK:
        current_tags = list(PENDING_ASSISTANT_IMAGE_TAGS.get(clean_session_id, []))
        if clean_tag not in current_tags:
            current_tags.append(clean_tag)
            PENDING_ASSISTANT_IMAGE_TAGS[clean_session_id] = current_tags


def consume_assistant_image_tags(session_id: str | None = None) -> list[str]:
    clean_session_id = str(session_id or get_current_session_id() or "").strip()
    if not clean_session_id:
        return []

    with PENDING_ASSISTANT_IMAGE_TAGS_LOCK:
        return list(PENDING_ASSISTANT_IMAGE_TAGS.pop(clean_session_id, []))


@contextmanager
def bind_session_id(session_id: str | None) -> Iterator[None]:
    token = CURRENT_SESSION_ID.set(session_id)
    try:
        yield
    finally:
        CURRENT_SESSION_ID.reset(token)
