


def _parse_qq_session_id(session_id: str | None) -> tuple[str, str]:
    """ 解析 QQ 会话 ID，返回会话类型和会话 ID ,如果是私聊则返回 "private" 和 QQ 号，否则返回 "group" 和 群号 """
    clean = str(session_id or "").strip()
    parts = clean.split(":", 2)
    if len(parts) != 3 or parts[0] != "qq" or parts[1] not in {"private", "group"}:
        raise ValueError(f"当前会话不是可发送图片的 QQ 会话: {clean or '空'}")
    return parts[1], parts[2]