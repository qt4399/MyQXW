from langchain_core.tools import tool
import subprocess
import json
@tool
def run_command(command: str) -> str:
    """运行Linux系统的bash命令，并返回包含 stdout/stderr/returncode 的 JSON 字符串。"""
    print(f"运行命令: {command}")
    completed = subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return json.dumps(
        {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        },
        ensure_ascii=False,
        indent=2,
)