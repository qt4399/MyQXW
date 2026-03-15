from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Iterator

import yaml

from heart import build_heartbeat_prompt
from init import build_agent, build_heart, chat as run_chat_response, chat_stream as stream_chat_response, run_heart
from memory.memory_store import DEFAULT_SESSION_ID, ensure_memory_layout, note_temp_digest_prompted, now_iso, prepare_heartbeat_state

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
HEARTBEAT_LOG_PATH = LOG_DIR / "heartbeat_log.yaml"
HEARTBEAT_LOOP_POLL_SECONDS = 0.5
HEARTBEAT_IDLE_INTERVAL_SECONDS = 30.0
HEARTBEAT_TEMP_PENDING_INTERVAL_SECONDS = 10.0
HEARTBEAT_DIGEST_DUE_INTERVAL_SECONDS = 5.0
HEARTBEAT_LOG_MAX_ENTRIES = 100


class HeartbeatLogStore:
    def __init__(self, path: Path, max_entries: int = HEARTBEAT_LOG_MAX_ENTRIES) -> None:
        self.path = path
        self.max_entries = max_entries
        self._lock = threading.Lock()
        self._entries = self._load_entries()
        self._write_entries()

    def _load_entries(self) -> list[dict[str, Any]]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            return []
        try:
            raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        except Exception:
            return []
        entries = raw.get("entries", [])
        if not isinstance(entries, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in entries:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "time": item.get("time"),
                    "status": item.get("status", "ok") or "ok",
                    "reasons": list(item.get("reasons", []) or []),
                    "response": item.get("response", "") or "",
                    "error": item.get("error", "") or "",
                }
            )
        return normalized[-self.max_entries :]

    def _write_entries(self) -> None:
        payload = {
            "version": 1,
            "max_entries": self.max_entries,
            "entries": self._entries[-self.max_entries :],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def append(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self._entries.append(
                {
                    "time": entry.get("time"),
                    "status": entry.get("status", "ok") or "ok",
                    "reasons": list(entry.get("reasons", []) or []),
                    "response": entry.get("response", "") or "",
                    "error": entry.get("error", "") or "",
                }
            )
            self._entries = self._entries[-self.max_entries :]
            self._write_entries()


class AgentScheduler:
    def __init__(self) -> None:
        ensure_memory_layout()
        self.chat_agent = build_agent()
        self.heart_agent = build_heart()
        self.stop_event = threading.Event()
        self.control_lock = threading.Lock()
        self.next_heartbeat_at = time.monotonic()
        self.heartbeat_logs = HeartbeatLogStore(HEARTBEAT_LOG_PATH)
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="heartbeat-worker",
            daemon=True,
        )

    def start(self) -> None:
        self.heartbeat_thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.heartbeat_thread.join(timeout=5)

    def _heartbeat_due(self) -> bool:
        with self.control_lock:
            return time.monotonic() >= self.next_heartbeat_at

    def _schedule_next_heartbeat(self, state: dict[str, Any] | None = None) -> None:
        interval = HEARTBEAT_IDLE_INTERVAL_SECONDS
        if state is not None:
            reasons = set(state.get("reasons") or [])
            if "临时对话整理" in reasons:
                interval = HEARTBEAT_DIGEST_DUE_INTERVAL_SECONDS
            elif int(state.get("temp_round_count") or 0) > 0:
                interval = HEARTBEAT_TEMP_PENDING_INTERVAL_SECONDS

        with self.control_lock:
            self.next_heartbeat_at = time.monotonic() + interval

    def _heartbeat_loop(self) -> None:
        while not self.stop_event.is_set():
            if self.stop_event.wait(HEARTBEAT_LOOP_POLL_SECONDS):
                break

            if not self._heartbeat_due():
                continue

            state: dict[str, Any] | None = None
            try:
                response = ""
                error = ""
                timestamp = now_iso()
                reasons: list[str] = []
                try:
                    state = prepare_heartbeat_state(commit_digest_prompted=False)
                    timestamp = str(state.get("current_time") or timestamp)
                    reasons = list(state.get("reasons") or [])
                    prompt = build_heartbeat_prompt(state)
                    response = run_heart(
                        self.heart_agent,
                        prompt,
                        show_output=False,
                    )
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"

                if not error and state is not None and "临时对话整理" in reasons:
                    note_temp_digest_prompted(timestamp)

                self.heartbeat_logs.append(
                    {
                        "time": timestamp,
                        "status": "error" if error else "ok",
                        "reasons": reasons,
                        "response": response,
                        "error": error,
                    }
                )
            finally:
                self._schedule_next_heartbeat(state)

    def chat(self, user_prompt: str, session_id: str = DEFAULT_SESSION_ID) -> str:
        return run_chat_response(self.chat_agent, user_prompt, session_id=session_id)

    def chat_stream(self, user_prompt: str, session_id: str = DEFAULT_SESSION_ID) -> Iterator[str]:
        return stream_chat_response(self.chat_agent, user_prompt, session_id=session_id)


def main() -> None:
    scheduler = AgentScheduler()
    scheduler.start()
    print(f"[调度器] 已启动。heartbeat 在后台静默运行。")
    print(f"[调度器] heartbeat 日志文件：{HEARTBEAT_LOG_PATH}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[调度器] 收到中断，准备退出。")
    finally:
        scheduler.stop()
        print("[调度器] 已停止。")


if __name__ == "__main__":
    main()
