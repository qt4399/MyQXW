from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import yaml

from init import build_heart, run_heart
from memory.memory_store import ensure_memory_layout, note_temp_digest_prompted, now_iso, prepare_heartbeat_state

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
HEARTBEAT_LOG_PATH = LOG_DIR / "heartbeat_log.yaml"
HEARTBEAT_LOOP_POLL_SECONDS = 0.5
HEARTBEAT_IDLE_INTERVAL_SECONDS = 30.0
HEARTBEAT_TEMP_PENDING_INTERVAL_SECONDS = 10.0
HEARTBEAT_DIGEST_DUE_INTERVAL_SECONDS = 5.0
HEARTBEAT_LOG_MAX_ENTRIES = 100


def build_heartbeat_prompt(state: dict[str, Any]) -> str:
    reasons = state.get("reasons", [])
    reason_text = "、".join(reasons) if reasons else "无"
    play_text = "是" if state.get("play_triggered") else "否"
    rolled_text = "是" if state.get("rolled_day") else "否"
    oldest_text = state.get("temp_oldest_age_seconds")
    oldest_value = str(oldest_text) if oldest_text is not None else "无"
    digest_due = "临时对话整理" in reasons

    lines = [
        "Boom",
        "",
        "[本次心跳状态]",
        f"- 当前具体时间：{state.get('current_time')}",
        f"- 当前记忆日：{state.get('current_day')}",
        f"- 本次是否触发玩耍：{play_text}",
        f"- 本次是否发生归档：{rolled_text}",
        f"- 临时对话轮数：{state.get('temp_round_count')}",
        f"- 最旧临时对话等待秒数：{oldest_value}",
        f"- 本次关注原因：{reason_text}",
        "",
    ]

    if state.get("play_triggered"):
        lines.append("如果本次触发了玩耍，可以进行一次低风险探索。")

    if digest_due:
        lines.append("本次已经满足临时对话整理条件；你现在可以读取 temp_communicate，整理成熟主题到 day.md，并删除已处理对话。")
    else:
        lines.append("如果本次关注原因里没有“临时对话整理”，不要主动读取 temp_communicate，也不要因为一两句零散内容就写入 day.md。")

    lines.append("如果没有足够价值，直接回复 HEARTBEAT_OK。")
    return "\n".join(lines)


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


class HeartService:
    def __init__(self) -> None:
        ensure_memory_layout()
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
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self.heartbeat_thread.start()
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self.stop_event.set()
        self.heartbeat_thread.join(timeout=5)
        self._started = False

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

