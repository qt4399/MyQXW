from pathlib import Path
import json
import subprocess

from langchain_core.tools import tool

BASE_DIR = Path(__file__).resolve().parent
MEMORY_DIR = BASE_DIR / "memory"
MEMORY_PATH = MEMORY_DIR / "MEMORY.md"
DEFAULT_MEMORY_HEADER = "# MEMORY.md - 我的记忆\n"


def _ensure_memory_file() -> Path:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    if MEMORY_PATH.exists():
        return MEMORY_PATH
    MEMORY_PATH.write_text(DEFAULT_MEMORY_HEADER, encoding="utf-8")
    return MEMORY_PATH


def _json_result(**payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool("run_command")
def run_command(command: str) -> str:
    """运行 Linux bash 命令，并返回 stdout、stderr 和 returncode 的 JSON 字符串。"""
    print(f"运行命令: {command}")
    completed = subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=BASE_DIR,
    )
    return _json_result(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
    )


@tool("update_memory")
def update_memory(content: str, mode: str = "append") -> str:
    """更新 MEMORY.md。mode 仅支持 append 或 replace。append 为追加，replace 为整篇覆盖。"""
    print("正在更新记忆")
    memory_path = _ensure_memory_file()

    normalized_mode = mode.strip().lower()
    if normalized_mode not in {"append", "replace"}:
        return _json_result(
            returncode=1,
            stderr="mode 仅支持 append 或 replace",
            stdout="",
            path=str(memory_path),
        )

    new_content = content.rstrip()
    if normalized_mode == "replace":
        memory_path.write_text(new_content + "\n", encoding="utf-8")
    else:
        existing = memory_path.read_text(encoding="utf-8").rstrip()
        if existing:
            updated = f"{existing}\n\n{new_content}\n"
        else:
            updated = new_content + "\n"
        memory_path.write_text(updated, encoding="utf-8")

    return _json_result(
        returncode=0,
        stderr="",
        stdout=memory_path.read_text(encoding="utf-8").strip(),
        path=str(memory_path),
        mode=normalized_mode,
    )


@tool("read_memory")
def read_memory() -> str:
    """读取 MEMORY.md，并返回包含内容的 JSON 字符串。"""
    print("正在阅读记忆")
    memory_path = _ensure_memory_file()
    return _json_result(
        returncode=0,
        stdout=memory_path.read_text(encoding="utf-8").strip(),
        stderr="",
        path=str(memory_path),
    )
@tool("update_day")
def update_day(content: str, mode: str = "append") -> str:
    """更新 DAY.md。mode 仅支持 append 或 replace。append 为追加，replace 为整篇覆盖。"""
    print("正在更新每日记录")
    day_path = MEMORY_DIR / "DAY.md"
    _ensure_memory_file()
    normalized_mode = mode.strip().lower()
    if normalized_mode not in {"append", "replace"}:
        return _json_result(
            returncode=1,
            stderr="mode 仅支持 append 或 replace",
            stdout="",
            path=str(day_path),
        )
@tool("read_day")
def read_day() -> str:
    """读取 DAY.md，并返回包含内容的 JSON 字符串。"""
    print("正在阅读每日记录")
    day_path = MEMORY_DIR / "DAY.md"
    return _json_result(
        returncode=0,
        stdout=day_path.read_text(encoding="utf-8").strip(),
        stderr="",
        path=str(day_path),
    )

@tool("update_heartbeat")
def update_heartbeat(content: str, mode: str = "append") -> str:
    """更新 HEARTBEATS.md。mode 仅支持 append 或 replace。append 为追加，replace 为整篇覆盖。"""
    print("正在更新心跳提示")
    heartbeat_path = MEMORY_DIR / "HEARTBEATS.md"
    _ensure_memory_file()
    normalized_mode = mode.strip().lower()
    if normalized_mode not in {"append", "replace"}:
        return _json_result(
            returncode=1,
            stderr="mode 仅支持 append 或 replace",
            stdout="",
            path=str(heartbeat_path),
        )

@tool("read_heartbeat")
def read_heartbeat() -> str:
    """读取 HEARTBEATS.md，并返回包含内容的 JSON 字符串。"""
    print("正在阅读心跳提示")
    heartbeat_path = MEMORY_DIR / "HEARTBEATS.md"
    return _json_result(
        returncode=0,
        stdout=heartbeat_path.read_text(encoding="utf-8").strip(),
        stderr="",
        path=str(heartbeat_path),
    )

