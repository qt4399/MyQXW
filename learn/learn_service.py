from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import yaml

from learn.learn_task_store import due_tasks, ensure_learn_task_layout, note_task_result
from memory.memory_store import ensure_memory_layout, now_iso
from workspace.literature import LiteratureService

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
LEARN_LOG_PATH = LOG_DIR / "learn_log.yaml"
LEARN_LOOP_POLL_SECONDS = 1.0
LEARN_LOG_MAX_ENTRIES = 100


class LearnLogStore:
    def __init__(self, path: Path, max_entries: int = LEARN_LOG_MAX_ENTRIES) -> None:
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
                    "task_id": item.get("task_id", "") or "",
                    "task_name": item.get("task_name", "") or "",
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
                    "task_id": entry.get("task_id", "") or "",
                    "task_name": entry.get("task_name", "") or "",
                    "status": entry.get("status", "ok") or "ok",
                    "response": entry.get("response", "") or "",
                    "error": entry.get("error", "") or "",
                }
            )
            self._entries = self._entries[-self.max_entries :]
            self._write_entries()


class LearnService:
    def __init__(self) -> None:
        ensure_memory_layout()
        ensure_learn_task_layout()
        self.literature_service = LiteratureService()
        self.stop_event = threading.Event()
        self.learn_logs = LearnLogStore(LEARN_LOG_PATH)
        self.learn_thread = threading.Thread(
            target=self._learn_loop,
            name="learn-worker",
            daemon=True,
        )
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self.learn_thread.start()
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self.stop_event.set()
        self.learn_thread.join(timeout=5)
        self._started = False

    def _run_literature_task(self, task: dict[str, Any]) -> dict[str, Any]:
        options = task.get("options", {}) if isinstance(task.get("options"), dict) else {}
        base_interval = max(5, int(task.get("interval_seconds", 60) or 60))
        result = self.literature_service.run_task(
            category=str(options.get("category", "")).strip(),
            topic=str(options.get("topic", "")).strip(),
            query=str(options.get("query", "")).strip(),
            search_queries_per_topic=options.get("search_queries_per_topic"),
            query_pool_size=options.get("query_pool_size"),
            query_plan_refresh_seconds=options.get("query_plan_refresh_seconds"),
            max_results=options.get("max_results"),
            max_new_papers_per_run=options.get("max_new_papers_per_run"),
            max_analyzed_papers_per_run=options.get("max_analyzed_papers_per_run"),
        )
        return {
            "time": now_iso(),
            "status": str(result.get("status", "ok") or "ok"),
            "response": str(result.get("summary", "") or ""),
            "error": str(result.get("error", "") or ""),
            "next_interval_seconds": base_interval,
        }

    def _run_task(self, task: dict[str, Any]) -> dict[str, Any]:
        runner = str(task.get("runner", "")).strip()
        if runner == "literature_poll":
            return self._run_literature_task(task)
        return {
            "time": now_iso(),
            "status": "error",
            "response": "",
            "error": f"未知 learn runner: {runner}",
            "next_interval_seconds": max(5, int(task.get("interval_seconds", 60) or 60)),
        }

    def _learn_loop(self) -> None:
        while not self.stop_event.is_set():
            if self.stop_event.wait(LEARN_LOOP_POLL_SECONDS):
                break

            tasks = due_tasks()
            if not tasks:
                continue

            for task in tasks:
                result = self._run_task(task)
                self.learn_logs.append(
                    {
                        "time": result["time"],
                        "task_id": str(task.get("id", "")).strip(),
                        "task_name": str(task.get("name", "")).strip(),
                        "status": result["status"],
                        "response": result.get("response", ""),
                        "error": result.get("error", ""),
                    }
                )
                note_task_result(
                    str(task.get("id", "")).strip(),
                    status=result["status"],
                    next_interval_seconds=int(result.get("next_interval_seconds", task.get("interval_seconds", 60)) or 60),
                    response=str(result.get("response", "") or ""),
                    error=str(result.get("error", "") or ""),
                )
