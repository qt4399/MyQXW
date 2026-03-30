from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Any

import yaml

from init import build_heart, run_heart
from memory.memory_store import DEFAULT_SESSION_ID, append_dialogue_round, ensure_memory_layout, now_iso, update_state

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
HEART_LOG_PATH = LOG_DIR / "heart_log.yaml"
HEART_LOG_MAX_ENTRIES = 100


def build_interrupt_prompt(task: dict[str, Any]) -> str:
    runner = str(task.get("runner", "")).strip() or "interrupt"
    source = str(task.get("source", "")).strip() or "unknown"
    impulse = float(task.get("impulse", 0.0) or 0.0)
    payload = task.get("payload", {}) if isinstance(task.get("payload"), dict) else {}

    lines = [
        "[本次主观中断]",
        f"- runner: {runner}",
        f"- source: {source}",
        f"- impulse: {impulse:.3f}",
        f"- current_time: {task.get('time') or now_iso()}",
    ]

    if payload:
        lines.append("- payload:")
        for key, value in payload.items():
            lines.append(f"  - {key}: {value}")

    lines.extend(
        [
            "",
            "这是一次主观中断，而不是后台整理或学习任务。",
            "你可以做一次简短的主观响应或轻量状态更新。",
            "如果没有必要动作，直接回复 HEART_OK。",
        ]
    )
    return "\n".join(lines)


# Backward-compatible alias for older imports.
build_heartbeat_prompt = build_interrupt_prompt


class HeartLogStore:
    def __init__(self, path: Path, max_entries: int = HEART_LOG_MAX_ENTRIES) -> None:
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


class HeartService:
    def __init__(self) -> None:
        ensure_memory_layout()
        self.heart_agent = build_heart()
        self.heart_logs = HeartLogStore(HEART_LOG_PATH)
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stop_event = threading.Event()
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="heart-worker",
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

    def submit_interrupt(
        self,
        *,
        runner: str = "interrupt",
        source: str = "external",
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

    def set_ws_server(self, ws_server) -> None:
        self._ws_server = ws_server

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            task = self._queue.get()
            runner = str(task.get("runner", "")).strip()
            if runner == "__stop__":
                break

            error = ""
            response = ""
            prompt = build_interrupt_prompt(task)
            try:
                response = run_heart(
                    self.heart_agent,
                    prompt,
                    show_output=False,
                )
                update_state({"last_heartbeat_at": now_iso()})

                # 写入对话历史（heart 回应可见于下次上下文）
                clean_response = response.strip()
                is_heart_ok = clean_response.upper().startswith("HEART_OK")
                if clean_response and not is_heart_ok:
                    append_dialogue_round(
                        f"[heart] {str(task.get('source', 'impulse')).strip()}",
                        clean_response,
                        session_id=DEFAULT_SESSION_ID,
                    )
                    # 推送到 WebSocket 前端
                    ws = getattr(self, "_ws_server", None)
                    if ws is not None:
                        ws.send_proactive(clean_response)

            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"

            self.heart_logs.append(
                {
                    "time": task.get("time") or now_iso(),
                    "runner": runner,
                    "source": str(task.get("source", "")).strip(),
                    "status": "error" if error else "ok",
                    "response": response,
                    "error": error,
                }
            )
