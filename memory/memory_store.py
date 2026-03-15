from __future__ import annotations

import math
import os
import random
import re
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

BASE_DIR = Path(__file__).resolve().parent
MEMORY_DIR = BASE_DIR
MD_DIR = MEMORY_DIR / "md"
YAML_DIR = MEMORY_DIR / "yaml"

STATE_PATH = YAML_DIR / "state.yaml"
COMMUNICATE_PATH = YAML_DIR / "communicate.yaml"
TEMP_COMMUNICATE_PATH = YAML_DIR / "temp_communicate.yaml"
DAY_MD_PATH = MD_DIR / "day.md"
MONTH_MD_PATH = MD_DIR / "month.md"
DEFAULT_SESSION_ID = "main:owner"

STORAGE_LOCK = threading.RLock()

COMMUNICATE_WINDOW = 20
DAY_ROLLOVER_HOUR = 4
TEMP_DIGEST_MIN_ROUNDS = 4
TEMP_DIGEST_MIN_AGE_SECONDS = 10 * 60
TEMP_DIGEST_COOLDOWN_SECONDS = 10 * 60
DEFAULT_PLAY_MEAN_INTERVAL_SECONDS = 3600
MONTH_WINDOW_DAYS = 30


def now_dt() -> datetime:
    return datetime.now().astimezone()


def now_iso() -> str:
    return now_dt().isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def seconds_since(value: str | None, now: datetime | None = None) -> float | None:
    parsed = parse_iso(value)
    if parsed is None:
        return None
    current = now or now_dt()
    return max(0.0, (current - parsed).total_seconds())


def active_memory_day(now: datetime | None = None) -> str:
    current = now or now_dt()
    if current.hour < DAY_ROLLOVER_HOUR:
        current = current - timedelta(days=1)
    return current.date().isoformat()


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _atomic_write_text(path: Path, content: str) -> None:
    _ensure_parent(path)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    with STORAGE_LOCK:
        _atomic_write_text(path, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))


def _read_yaml(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    with STORAGE_LOCK:
        _ensure_parent(path)
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
        for key, value in loaded.items():
            merged[key] = value
        return merged


def _read_text(path: Path, default: str) -> str:
    with STORAGE_LOCK:
        _ensure_parent(path)
        if not path.exists():
            _atomic_write_text(path, default)
            return default
        return path.read_text(encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    with STORAGE_LOCK:
        _atomic_write_text(path, content)


def _default_state() -> dict[str, Any]:
    return {
        "version": 1,
        "current_day": active_memory_day(),
        "last_user_message_at": None,
        "last_assistant_message_at": None,
        "last_heartbeat_at": None,
        "last_day_rollup_at": None,
        "last_temp_digest_prompted_at": None,
        "last_temp_digest_completed_at": None,
        "play": {
            "enabled": True,
            "active": False,
            "last_triggered_at": None,
            "mean_interval_seconds": DEFAULT_PLAY_MEAN_INTERVAL_SECONDS,
        },
    }


def _default_communicate() -> dict[str, Any]:
    return {
        "version": 2,
        "default_session_id": DEFAULT_SESSION_ID,
        "max_rounds": COMMUNICATE_WINDOW,
        "rounds": [],
        "sessions": {},
    }


def _default_temp_communicate() -> dict[str, Any]:
    return {
        "version": 2,
        "default_session_id": DEFAULT_SESSION_ID,
        "rounds": [],
        "sessions": {},
    }


def _default_session_communicate() -> dict[str, Any]:
    return {
        "max_rounds": COMMUNICATE_WINDOW,
        "rounds": [],
    }


def _default_session_temp() -> dict[str, Any]:
    return {
        "rounds": [],
    }


def normalize_session_id(session_id: str | None = None) -> str:
    clean = str(session_id or "").strip()
    return clean or DEFAULT_SESSION_ID


def build_session_id(source: str, chat_type: str | None = None, target_id: str | int | None = None) -> str:
    clean_source = str(source or "").strip().lower()
    if clean_source in {"", "main", "local"}:
        return DEFAULT_SESSION_ID

    if clean_source == "qq":
        clean_type = str(chat_type or "").strip().lower()
        if clean_type not in {"private", "group"}:
            raise ValueError("qq 会话类型必须是 private 或 group")

        clean_target = str(target_id or "").strip()
        if not clean_target:
            raise ValueError("qq 会话必须提供有效的 target_id")

        return f"qq:{clean_type}:{clean_target}"

    raise ValueError(f"不支持的会话来源: {source}")


def _normalize_round_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _normalize_communicate_root(data: dict[str, Any]) -> dict[str, Any]:
    root = dict(_default_communicate())
    root.update(data)

    default_session_id = normalize_session_id(root.get("default_session_id"))
    sessions: dict[str, dict[str, Any]] = {}
    raw_sessions = root.get("sessions")
    if isinstance(raw_sessions, dict):
        for session_key, session_data in raw_sessions.items():
            if not isinstance(session_data, dict):
                continue
            sessions[str(session_key)] = {
                "max_rounds": int(session_data.get("max_rounds", COMMUNICATE_WINDOW) or COMMUNICATE_WINDOW),
                "rounds": _normalize_round_items(session_data.get("rounds", [])),
            }

    legacy_rounds = _normalize_round_items(root.get("rounds", []))
    if default_session_id not in sessions:
        sessions[default_session_id] = {
            "max_rounds": int(root.get("max_rounds", COMMUNICATE_WINDOW) or COMMUNICATE_WINDOW),
            "rounds": legacy_rounds,
        }

    main_session = sessions[default_session_id]
    root["version"] = 2
    root["default_session_id"] = default_session_id
    root["sessions"] = sessions
    root["max_rounds"] = int(main_session.get("max_rounds", COMMUNICATE_WINDOW) or COMMUNICATE_WINDOW)
    root["rounds"] = _normalize_round_items(main_session.get("rounds", []))
    return root


def _normalize_temp_root(data: dict[str, Any]) -> dict[str, Any]:
    root = dict(_default_temp_communicate())
    root.update(data)

    default_session_id = normalize_session_id(root.get("default_session_id"))
    sessions: dict[str, dict[str, Any]] = {}
    raw_sessions = root.get("sessions")
    if isinstance(raw_sessions, dict):
        for session_key, session_data in raw_sessions.items():
            if not isinstance(session_data, dict):
                continue
            sessions[str(session_key)] = {
                "rounds": _normalize_round_items(session_data.get("rounds", [])),
            }

    legacy_rounds = _normalize_round_items(root.get("rounds", []))
    if default_session_id not in sessions:
        sessions[default_session_id] = {
            "rounds": legacy_rounds,
        }

    main_session = sessions[default_session_id]
    root["version"] = 2
    root["default_session_id"] = default_session_id
    root["sessions"] = sessions
    root["rounds"] = _normalize_round_items(main_session.get("rounds", []))
    return root


def _day_template(date_value: str | None = None) -> str:
    current_day = date_value or active_memory_day()
    return (
        "# day.md - 当日记录\n\n"
        f"日期: {current_day}\n\n"
        "## 概括\n"
        "- （待整理）\n\n"
        "## 详细\n"
        "- （待补充）\n"
    )


def _month_template() -> str:
    return "# month.md - 最近30天记录\n\n"


def ensure_memory_layout() -> None:
    with STORAGE_LOCK:
        MD_DIR.mkdir(parents=True, exist_ok=True)
        YAML_DIR.mkdir(parents=True, exist_ok=True)
        _read_yaml(STATE_PATH, _default_state())
        _read_yaml(COMMUNICATE_PATH, _default_communicate())
        _read_yaml(TEMP_COMMUNICATE_PATH, _default_temp_communicate())
        _read_text(DAY_MD_PATH, _day_template())
        _read_text(MONTH_MD_PATH, _month_template())


def read_state() -> dict[str, Any]:
    with STORAGE_LOCK:
        state = _read_yaml(STATE_PATH, _default_state())

        state.pop("current_mode", None)
        legacy_digest_at = state.pop("last_temp_digest_at", None)
        if legacy_digest_at and not state.get("last_temp_digest_prompted_at"):
            state["last_temp_digest_prompted_at"] = legacy_digest_at

        play = dict(_default_state()["play"])
        if isinstance(state.get("play"), dict):
            play.update(state["play"])
        state["play"] = play
        return state


def write_state(data: dict[str, Any]) -> dict[str, Any]:
    with STORAGE_LOCK:
        _write_yaml(STATE_PATH, data)
        return data


def update_state(patch: dict[str, Any]) -> dict[str, Any]:
    with STORAGE_LOCK:
        state = read_state()
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(state.get(key), dict):
                merged = dict(state[key])
                merged.update(value)
                state[key] = merged
            else:
                state[key] = value
        return write_state(state)


def read_communicate(session_id: str | None = None) -> dict[str, Any]:
    with STORAGE_LOCK:
        root = _normalize_communicate_root(_read_yaml(COMMUNICATE_PATH, _default_communicate()))
        session_key = normalize_session_id(session_id)
        session = dict(root.get("sessions", {}).get(session_key, _default_session_communicate()))
        session["version"] = root["version"]
        session["session_id"] = session_key
        session["max_rounds"] = int(session.get("max_rounds", COMMUNICATE_WINDOW) or COMMUNICATE_WINDOW)
        session["rounds"] = _normalize_round_items(session.get("rounds", []))
        return session


def write_communicate(data: dict[str, Any], session_id: str | None = None) -> dict[str, Any]:
    with STORAGE_LOCK:
        root = _normalize_communicate_root(_read_yaml(COMMUNICATE_PATH, _default_communicate()))
        session_key = normalize_session_id(session_id or data.get("session_id"))
        session_payload = {
            "max_rounds": int(data.get("max_rounds", COMMUNICATE_WINDOW) or COMMUNICATE_WINDOW),
            "rounds": _normalize_round_items(data.get("rounds", [])),
        }
        root["sessions"][session_key] = session_payload
        if session_key == root["default_session_id"]:
            root["max_rounds"] = session_payload["max_rounds"]
            root["rounds"] = list(session_payload["rounds"])
        _write_yaml(COMMUNICATE_PATH, root)
        return {
            "version": root["version"],
            "session_id": session_key,
            "max_rounds": session_payload["max_rounds"],
            "rounds": list(session_payload["rounds"]),
        }


def read_temp_communicate(session_id: str | None = None) -> dict[str, Any]:
    with STORAGE_LOCK:
        root = _normalize_temp_root(_read_yaml(TEMP_COMMUNICATE_PATH, _default_temp_communicate()))
        session_key = normalize_session_id(session_id)
        session = dict(root.get("sessions", {}).get(session_key, _default_session_temp()))
        session["version"] = root["version"]
        session["session_id"] = session_key
        session["rounds"] = _normalize_round_items(session.get("rounds", []))
        return session


def write_temp_communicate(data: dict[str, Any], session_id: str | None = None) -> dict[str, Any]:
    with STORAGE_LOCK:
        root = _normalize_temp_root(_read_yaml(TEMP_COMMUNICATE_PATH, _default_temp_communicate()))
        session_key = normalize_session_id(session_id or data.get("session_id"))
        session_payload = {
            "rounds": _normalize_round_items(data.get("rounds", [])),
        }
        root["sessions"][session_key] = session_payload
        if session_key == root["default_session_id"]:
            root["rounds"] = list(session_payload["rounds"])
        _write_yaml(TEMP_COMMUNICATE_PATH, root)
        return {
            "version": root["version"],
            "session_id": session_key,
            "rounds": list(session_payload["rounds"]),
        }


def _new_round(user_text: str, assistant_text: str) -> dict[str, Any]:
    return {
        "id": uuid4().hex[:12],
        "created_at": now_iso(),
        "user": user_text.strip(),
        "assistant": assistant_text.strip(),
    }


def append_dialogue_round(user_text: str, assistant_text: str, session_id: str | None = None) -> dict[str, Any]:
    with STORAGE_LOCK:
        session_key = normalize_session_id(session_id)
        communicate = read_communicate(session_key)
        temp = read_temp_communicate(session_key)

        round_item = _new_round(user_text, assistant_text)
        rounds = list(communicate.get("rounds", []))
        rounds.append(round_item)

        max_rounds = int(communicate.get("max_rounds", COMMUNICATE_WINDOW) or COMMUNICATE_WINDOW)
        overflow_count = max(0, len(rounds) - max_rounds)
        overflow_rounds = rounds[:overflow_count]
        communicate["rounds"] = rounds[overflow_count:]
        write_communicate(communicate, session_id=session_key)

        if overflow_rounds:
            temp_rounds = list(temp.get("rounds", []))
            moved_at = now_iso()
            for item in overflow_rounds:
                overflow_item = dict(item)
                overflow_item["moved_at"] = moved_at
                temp_rounds.append(overflow_item)
            temp["rounds"] = temp_rounds
            write_temp_communicate(temp, session_id=session_key)

        return round_item


def recent_conversation_messages(max_rounds: int | None = None, session_id: str | None = None) -> list[dict[str, str]]:
    with STORAGE_LOCK:
        messages: list[dict[str, str]] = []
        rounds = list(read_communicate(session_id=session_id).get("rounds", []))
        if max_rounds is not None and max_rounds > 0:
            rounds = rounds[-max_rounds:]
        for round_item in rounds:
            user_text = str(round_item.get("user", "")).strip()
            assistant_text = str(round_item.get("assistant", "")).strip()
            if user_text:
                messages.append({"role": "user", "content": user_text})
            if assistant_text:
                messages.append({"role": "assistant", "content": assistant_text})
        return messages


def read_prompt_snapshot(max_rounds: int | None = None, session_id: str | None = None) -> dict[str, Any]:
    with STORAGE_LOCK:
        return {
            "recent_messages": recent_conversation_messages(max_rounds=max_rounds, session_id=session_id),
            "day_md": read_day_md().strip(),
            "month_summaries": read_month_summaries().strip(),
        }


def delete_temp_rounds(ids: list[str]) -> dict[str, Any]:
    with STORAGE_LOCK:
        temp = read_temp_communicate()
        original_rounds = list(temp.get("rounds", []))
        id_set = {item.strip() for item in ids if item.strip()}
        temp["rounds"] = [item for item in original_rounds if str(item.get("id", "")) not in id_set]

        updated = write_temp_communicate(temp)
        if len(updated.get("rounds", [])) < len(original_rounds):
            update_state({"last_temp_digest_completed_at": now_iso()})

        return updated


def note_temp_digest_prompted(prompted_at: str | None = None) -> dict[str, Any]:
    return update_state({"last_temp_digest_prompted_at": prompted_at or now_iso()})


def temp_stats() -> dict[str, Any]:
    with STORAGE_LOCK:
        rounds = list(read_temp_communicate().get("rounds", []))
        oldest_age = None
        if rounds:
            oldest = min(rounds, key=lambda item: item.get("moved_at") or item.get("created_at") or "")
            oldest_age = seconds_since(oldest.get("moved_at") or oldest.get("created_at"))
        return {
            "count": len(rounds),
            "oldest_age_seconds": int(oldest_age) if oldest_age is not None else None,
        }


def read_day_md() -> str:
    with STORAGE_LOCK:
        return _read_text(DAY_MD_PATH, _day_template())


def write_day_md(content: str) -> str:
    with STORAGE_LOCK:
        _write_text(DAY_MD_PATH, content.rstrip() + "\n")
        return read_day_md()


def _extract_date_line(text: str) -> str | None:
    match = re.search(r"^日期:\s*(\d{4}-\d{2}-\d{2})$", text, flags=re.MULTILINE)
    return match.group(1) if match else None


def _extract_level2_section(text: str, heading: str) -> str:
    pattern = re.compile(rf"^{re.escape(heading)}\s*$\n?(.*?)(?=^## |\Z)", flags=re.MULTILINE | re.DOTALL)
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def _replace_level2_section(text: str, heading: str, new_body: str) -> str:
    pattern = re.compile(rf"^{re.escape(heading)}\s*$\n?(.*?)(?=^## |\Z)", flags=re.MULTILINE | re.DOTALL)
    replacement = f"{heading}\n{new_body.strip()}\n"
    if pattern.search(text):
        return pattern.sub(replacement, text, count=1)
    return text.rstrip() + f"\n\n{replacement}"


def _extract_level3_section(text: str, heading: str) -> str:
    pattern = re.compile(rf"^{re.escape(heading)}\s*$\n?(.*?)(?=^### |\Z)", flags=re.MULTILINE | re.DOTALL)
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def read_day_summary() -> str:
    with STORAGE_LOCK:
        summary = _extract_level2_section(read_day_md(), "## 概括")
        return summary or "- （待整理）"


def read_day_details() -> str:
    with STORAGE_LOCK:
        details = _extract_level2_section(read_day_md(), "## 详细")
        return details or "- （待补充）"


def update_day_summary(summary: str) -> str:
    with STORAGE_LOCK:
        content = summary.strip() or "- （待整理）"
        updated = _replace_level2_section(read_day_md(), "## 概括", content)
        return write_day_md(updated)


def append_day_md(content: str) -> str:
    with STORAGE_LOCK:
        block = content.strip()
        if not block:
            raise ValueError("content 不能为空")

        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        first_line = lines[0]
        tail_lines = lines[1:]
        entry_lines = [f"- [{now_iso()}] {first_line}"]
        entry_lines.extend(f"  {line}" for line in tail_lines)
        entry = "\n".join(entry_lines)

        current = read_day_md()
        details = read_day_details()
        normalized_details = "" if details == "- （待补充）" else details.strip()
        if normalized_details:
            new_details = f"{normalized_details}\n{entry}"
        else:
            new_details = entry
        updated = _replace_level2_section(current, "## 详细", new_details)
        return write_day_md(updated)


def read_month_md() -> str:
    with STORAGE_LOCK:
        return _read_text(MONTH_MD_PATH, _month_template())


def write_month_md(content: str) -> str:
    with STORAGE_LOCK:
        _write_text(MONTH_MD_PATH, content.rstrip() + "\n")
        return read_month_md()


def _parse_month_entries(month_text: str) -> dict[str, dict[str, str]]:
    pattern = re.compile(r"^## (\d{4}-\d{2}-\d{2})$", flags=re.MULTILINE)
    matches = list(pattern.finditer(month_text))
    entries: dict[str, dict[str, str]] = {}
    for index, match in enumerate(matches):
        date_value = match.group(1)
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(month_text)
        body = month_text[start:end].strip()
        entries[date_value] = {
            "summary": _extract_level3_section(body, "### 概括") or "- （暂无概括）",
            "details": _extract_level3_section(body, "### 详细") or "- （暂无详细内容）",
        }
    return entries


def _build_month_entry(summary: str, details: str) -> str:
    clean_summary = summary.strip() or "- （暂无概括）"
    clean_details = details.strip() or "- （暂无详细内容）"
    return f"### 概括\n{clean_summary}\n\n### 详细\n{clean_details}\n"


def _build_month_text(entries: dict[str, dict[str, str]]) -> str:
    parts = ["# month.md - 最近30天记录", ""]
    for date_value in sorted(entries.keys())[-MONTH_WINDOW_DAYS:]:
        parts.append(f"## {date_value}")
        parts.append(_build_month_entry(entries[date_value]["summary"], entries[date_value]["details"]).strip())
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def read_month_summaries() -> str:
    with STORAGE_LOCK:
        entries = _parse_month_entries(read_month_md())
        if not entries:
            return "- （最近30天暂无归档）"

        lines: list[str] = []
        for date_value in sorted(entries.keys(), reverse=True)[:MONTH_WINDOW_DAYS]:
            summary = re.sub(r"\s+", " ", entries[date_value]["summary"].replace("- ", "")).strip()
            summary = summary or "（暂无概括）"
            lines.append(f"- {date_value}：{summary}")
        return "\n".join(lines)


def read_month_day(date_value: str) -> str:
    with STORAGE_LOCK:
        clean_date = date_value.strip()
        entries = _parse_month_entries(read_month_md())
        entry = entries.get(clean_date)
        if entry is None:
            raise ValueError(f"month.md 中不存在 {clean_date} 的记录；请先查看最近30天概括里的精确日期，再传入 YYYY-MM-DD")
        return f"## {clean_date}\n{_build_month_entry(entry['summary'], entry['details']).strip()}"


def archive_day_to_month(now: datetime | None = None) -> bool:
    with STORAGE_LOCK:
        current = now or now_dt()
        target_day = active_memory_day(current)
        day_text = read_day_md()
        day_date = _extract_date_line(day_text)
        if not day_date or day_date == target_day:
            return False

        summary = read_day_summary()
        details = read_day_details()
        entries = _parse_month_entries(read_month_md())
        entries[day_date] = {
            "summary": summary,
            "details": details,
        }
        trimmed_entries = {date_value: entries[date_value] for date_value in sorted(entries.keys())[-MONTH_WINDOW_DAYS:]}
        write_month_md(_build_month_text(trimmed_entries))
        write_day_md(_day_template(target_day))
        update_state(
            {
                "current_day": target_day,
                "last_day_rollup_at": current.isoformat(timespec="seconds"),
            }
        )
        return True


def _temp_digest_due(state: dict[str, Any], stats: dict[str, Any], now: datetime) -> bool:
    if stats["count"] < TEMP_DIGEST_MIN_ROUNDS:
        return False
    if (stats["oldest_age_seconds"] or 0) < TEMP_DIGEST_MIN_AGE_SECONDS:
        return False
    last_prompted_age = seconds_since(state.get("last_temp_digest_prompted_at"), now)
    return last_prompted_age is None or last_prompted_age >= TEMP_DIGEST_COOLDOWN_SECONDS


def _play_should_trigger(state: dict[str, Any], now: datetime) -> bool:
    play = state.get("play", {}) if isinstance(state.get("play"), dict) else {}
    if not bool(play.get("enabled", True)):
        return False

    mean_interval = max(60, int(play.get("mean_interval_seconds", DEFAULT_PLAY_MEAN_INTERVAL_SECONDS)))
    elapsed = seconds_since(state.get("last_heartbeat_at"), now)
    elapsed_seconds = max(1.0, elapsed if elapsed is not None else 1.0)
    probability = 1 - math.exp(-elapsed_seconds / mean_interval)
    return random.random() < probability


def prepare_heartbeat_state(commit_digest_prompted: bool = True) -> dict[str, Any]:
    with STORAGE_LOCK:
        ensure_memory_layout()
        current = now_dt()
        current_time = current.isoformat(timespec="seconds")
        current_day = active_memory_day(current)
        rolled_day = archive_day_to_month(current)
        state = read_state()
        stats = temp_stats()

        reasons: list[str] = []
        digest_due = _temp_digest_due(state, stats, current)
        if digest_due:
            reasons.append("临时对话整理")

        play_triggered = _play_should_trigger(state, current)
        if play_triggered:
            reasons.append("玩耍")

        play_patch = dict(state.get("play", {}))
        play_patch["active"] = play_triggered
        if play_triggered:
            play_patch["last_triggered_at"] = current_time

        patch: dict[str, Any] = {
            "current_day": current_day,
            "last_heartbeat_at": current_time,
            "play": play_patch,
        }
        if digest_due and commit_digest_prompted:
            patch["last_temp_digest_prompted_at"] = current_time
        state = update_state(patch)

        return {
            "current_time": current_time,
            "current_day": state.get("current_day"),
            "rolled_day": rolled_day,
            "temp_round_count": stats["count"],
            "temp_oldest_age_seconds": stats["oldest_age_seconds"],
            "play_triggered": play_triggered,
            "reasons": reasons,
        }
