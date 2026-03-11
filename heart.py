import time

from init import build_heart, run_heart
from memory.memory_store import prepare_heartbeat_state


def build_heartbeat_prompt(state: dict) -> str:
    reasons = state.get("reasons", [])
    reason_text = "、".join(reasons) if reasons else "无"
    play_text = "是" if state.get("play_triggered") else "否"
    rolled_text = "是" if state.get("rolled_day") else "否"
    oldest_text = state.get("temp_oldest_age_seconds")
    oldest_value = str(oldest_text) if oldest_text is not None else "无"

    return "\n".join(
        [
            "Boom",
            "",
            "[本次心跳状态]",
            f"- 当前具体时间：{state.get('current_time')}",
            f"- 当前记忆日：{state.get('current_day')}",
            f"- 当前模式：{state.get('current_mode')}",
            f"- 本次是否触发玩耍：{play_text}",
            f"- 本次是否发生归档：{rolled_text}",
            f"- 临时对话轮数：{state.get('temp_round_count')}",
            f"- 最旧临时对话等待秒数：{oldest_value}",
            f"- 本次关注原因：{reason_text}",
            "",
            "如果本次触发了玩耍，可以进行一次低风险探索。",
            "如果 temp_communicate 里的内容已经形成两个及以上主题，或至少有一个完整主题，就整理有用事件和主题总结到 day.md，并删除已处理对话。",
            "如果没有足够价值，直接回复 HEARTBEAT_OK。",
        ]
    )


def main() -> None:
    agent = build_heart()
    while True:
        state = prepare_heartbeat_state()
        run_heart(agent, build_heartbeat_prompt(state))
        time.sleep(1)


if __name__ == "__main__":
    main()
