from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Any

import yaml

from init import build_sleep, run_sleep
from memory.memory_store import ensure_memory_layout, now_iso

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
SLEEP_LOG_PATH = LOG_DIR / "sleep_log.yaml"
SLEEP_LOG_MAX_ENTRIES = 100


def build_sleep_task_prompt(task: dict[str, Any]) -> str:
    runner = str(task.get("runner", "")).strip() or "unknown"
    source = str(task.get("source", "")).strip() or "unknown"
    impulse = float(task.get("impulse", 0.0) or 0.0)
    payload = task.get("payload", {}) if isinstance(task.get("payload"), dict) else {}
    session_id = str(payload.get("session_id", "")).strip()

    lines = [
        "[本次睡眠任务]",
        f"- runner: {runner}",
        f"- source: {source}",
        f"- impulse: {impulse:.3f}",
        f"- current_time: {now_iso()}",
    ]

    if session_id:
        lines.append(f"- session_id: {session_id}")

    if payload:
        lines.append("- payload:")
        for key, value in payload.items():
            lines.append(f"  - {key}: {value}")

    lines.append("")

    if runner == "temp_digest":
        lines.extend(
            [
                "这是一次后台记忆整理任务。",
                "请优先读取指定 session 的 temp_communicate；如果 session_id 为空，则默认主会话。",
                "如果这些旧对话已经形成值得沉淀的事件、主题或稳定信息，就整理进 day.md，并删除对应轮次。",
                "如果还不成熟，直接回复 SLEEP_OK。",
            ]
        )
    elif runner == "daily_summary":
        lines.extend(
            [
                "这是一次每日概括收束任务。",
                "请结合今日记忆、今天的对话和 day.md 当前内容，必要时更新 day.md 的 `## 概括`。",
                "如果没有更好的概括可写，直接回复 SLEEP_OK。",
            ]
        )
    else:
        lines.extend(
            [
                "这是一次通用睡眠整理任务。",
                "如果任务信息不足或没有明确整理价值，直接回复 SLEEP_OK。",
            ]
        )

    return "\n".join(lines)


class SleepLogStore:
    def __init__(self, path: Path, max_entries: int = SLEEP_LOG_MAX_ENTRIES) -> None:
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
                    "runner": item.get("runner", "") or "",
                    "source": item.get("source", "") or "",
                    "status": item.get("status", "ok") or "ok",
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
                    "runner": entry.get("runner", "") or "",
                    "source": entry.get("source", "") or "",
                    "status": entry.get("status", "ok") or "ok",
                    "response": entry.get("response", "") or "",
                    "error": entry.get("error", "") or "",
                }
            )
            self._entries = self._entries[-self.max_entries :]
            self._write_entries()


class SleepService:
    def __init__(self) -> None:
        ensure_memory_layout()
        self.sleep_agent = build_sleep()
        self.sleep_logs = SleepLogStore(SLEEP_LOG_PATH)
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stop_event = threading.Event()
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="sleep-worker",
            daemon=True,
        )
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._worker.start()
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self._stop_event.set()
        self._queue.put({"runner": "__stop__"})
        self._worker.join(timeout=5)
        self._started = False

    def submit_task(
        self,
        *,
        runner: str,
        source: str,
        impulse: float = 0.0,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._queue.put(
            {
                "runner": runner,
                "source": source,
                "impulse": float(impulse or 0.0),
                "payload": dict(payload or {}),
                "time": now_iso(),
            }
        )

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            task = self._queue.get()
            runner = str(task.get("runner", "")).strip()
            if runner == "__stop__":
                break

            error = ""
            response = ""
            try:
                response = run_sleep(
                    self.sleep_agent,
                    build_sleep_task_prompt(task),
                    show_output=False,
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"

            self.sleep_logs.append(
                {
                    "time": task.get("time") or now_iso(),
                    "runner": runner,
                    "source": str(task.get("source", "")).strip(),
                    "status": "error" if error else "ok",
                    "response": response,
                    "error": error,
                }
            )
