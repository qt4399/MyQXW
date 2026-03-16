from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

CURRENT_SESSION_ID: ContextVar[str | None] = ContextVar("current_session_id", default=None)


def get_current_session_id() -> str | None:
    return CURRENT_SESSION_ID.get()


@contextmanager
def bind_session_id(session_id: str | None) -> Iterator[None]:
    token = CURRENT_SESSION_ID.set(session_id)
    try:
        yield
    finally:
        CURRENT_SESSION_ID.reset(token)
