import time

from init import build_heart, run_heart
from memory.memory_store import note_temp_digest_prompted, prepare_heartbeat_state


DEBUG_HEARTBEAT_INTERVAL_SECONDS = 1.0


def build_heartbeat_prompt(state: dict) -> str:
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


def main() -> None:
    print("[heart] 调试模式。日常使用请运行 python main.py。")
    agent = build_heart()
    while True:
        state = prepare_heartbeat_state(commit_digest_prompted=False)
        run_heart(agent, build_heartbeat_prompt(state), show_output=True)
        if "临时对话整理" in set(state.get("reasons") or []):
            note_temp_digest_prompted(str(state.get("current_time") or ""))
        time.sleep(DEBUG_HEARTBEAT_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
