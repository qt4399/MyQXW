from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml

from memory.memory_store import YAML_DIR, ensure_memory_layout, now_dt, parse_iso

TASK_CONFIG_PATH = Path(__file__).resolve().parent / "learn_tasks.yaml"
TASK_STATE_PATH = YAML_DIR / "learn_task_state.yaml"


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _read_yaml(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        _write_yaml(path, default)
        return dict(default)

    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        _write_yaml(path, default)
        return dict(default)

    loaded = yaml.safe_load(raw)
    if not isinstance(loaded, dict):
        return dict(default)

    merged = dict(default)
    merged.update(loaded)
    return merged


def _default_task_config() -> dict[str, Any]:
    return {
        "version": 1,
        "tasks": [
            {
                "id": "literature_agent",
                "name": "Agent文献巡检",
                "enabled": False,
                "runner": "literature_poll",
                "interval_seconds": 21600,
                "options": {
                    "category": "agent",
                    "topic": "多智能体系统",
                    "search_queries_per_topic": 3,
                    "query_pool_size": 9,
                    "query_plan_refresh_seconds": 600,
                    "max_results": 100,
                    "max_new_papers_per_run": 3,
                    "max_analyzed_papers_per_run": 12,
                },
            }
        ],
    }


def _default_task_state() -> dict[str, Any]:
    return {
        "version": 1,
        "tasks": {},
    }


def _normalize_task_config_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None

    task_id = str(item.get("id", "")).strip()
    runner = str(item.get("runner", "")).strip()
    if not task_id or not runner:
        return None

    options = item.get("options", {})
    if not isinstance(options, dict):
        options = {}

    return {
        "id": task_id,
        "name": str(item.get("name", "")).strip() or task_id,
        "enabled": bool(item.get("enabled", False)),
        "runner": runner,
        "interval_seconds": max(5, int(item.get("interval_seconds", 60) or 60)),
        "options": dict(options),
    }


def _normalize_task_state_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        item = {}

    return {
        "last_run_at": item.get("last_run_at"),
        "next_run_at": item.get("next_run_at"),
        "last_success_at": item.get("last_success_at"),
        "last_status": str(item.get("last_status", "idle") or "idle"),
        "last_error": str(item.get("last_error", "") or ""),
        "last_response": str(item.get("last_response", "") or ""),
        "run_count": max(0, int(item.get("run_count", 0) or 0)),
    }


def ensure_learn_task_layout() -> None:
    ensure_memory_layout()
    _read_yaml(TASK_CONFIG_PATH, _default_task_config())
    _read_yaml(TASK_STATE_PATH, _default_task_state())


def read_learn_tasks_config() -> dict[str, Any]:
    ensure_learn_task_layout()
    raw = _read_yaml(TASK_CONFIG_PATH, _default_task_config())
    tasks = []
    for item in raw.get("tasks", []):
        normalized = _normalize_task_config_item(item)
        if normalized is not None:
            tasks.append(normalized)
    return {
        "version": 1,
        "tasks": tasks,
    }


def read_learn_task_state() -> dict[str, Any]:
    ensure_learn_task_layout()
    raw = _read_yaml(TASK_STATE_PATH, _default_task_state())
    tasks: dict[str, dict[str, Any]] = {}
    raw_tasks = raw.get("tasks", {})
    if isinstance(raw_tasks, dict):
        for task_id, item in raw_tasks.items():
            clean_id = str(task_id).strip()
            if not clean_id:
                continue
            tasks[clean_id] = _normalize_task_state_item(item)
    return {
        "version": 1,
        "tasks": tasks,
    }


def write_learn_task_state(payload: dict[str, Any]) -> dict[str, Any]:
    raw_tasks = payload.get("tasks", {})
    tasks: dict[str, dict[str, Any]] = {}
    if isinstance(raw_tasks, dict):
        for task_id, item in raw_tasks.items():
            clean_id = str(task_id).strip()
            if not clean_id:
                continue
            tasks[clean_id] = _normalize_task_state_item(item)
    data = {"version": 1, "tasks": tasks}
    _write_yaml(TASK_STATE_PATH, data)
    return data


def due_tasks() -> list[dict[str, Any]]:
    config = read_learn_tasks_config()
    state = read_learn_task_state()
    current = now_dt()
    due: list[dict[str, Any]] = []

    for task in config.get("tasks", []):
        if not task.get("enabled", False):
            continue

        runtime = state.get("tasks", {}).get(task["id"], {})
        next_run_at = parse_iso(runtime.get("next_run_at"))
        if next_run_at is not None and next_run_at > current:
            continue
        due.append(task)

    return due


def note_task_result(
    task_id: str,
    *,
    status: str,
    next_interval_seconds: int,
    response: str = "",
    error: str = "",
) -> dict[str, Any]:
    state = read_learn_task_state()
    tasks = dict(state.get("tasks", {}))
    runtime = _normalize_task_state_item(tasks.get(task_id, {}))
    current = now_dt()

    runtime["last_run_at"] = current.isoformat(timespec="seconds")
    runtime["next_run_at"] = (current + timedelta(seconds=max(1, int(next_interval_seconds)))).isoformat(timespec="seconds")
    runtime["last_status"] = str(status or "ok")
    runtime["last_error"] = str(error or "")
    runtime["last_response"] = str(response or "")
    runtime["run_count"] = int(runtime.get("run_count", 0) or 0) + 1
    if runtime["last_status"] == "ok":
        runtime["last_success_at"] = runtime["last_run_at"]

    tasks[str(task_id).strip()] = runtime
    state["tasks"] = tasks
    return write_learn_task_state(state)
