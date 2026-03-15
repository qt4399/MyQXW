"""
NapCat 事件监听器

使用示例:
    from napcat_listener import NapCatListener

    # 方式1: 使用装饰器注册事件处理器
    listener = NapCatListener()

    @listener.on_private_message
    def handle_private(event):
        print(f"收到私聊: {event['raw_message']}")

    @listener.on_group_message
    def handle_group(event):
        print(f"收到群消息: {event['raw_message']}")

    listener.start()  # 阻塞运行

    # 方式2: 使用回调函数
    def on_event(event):
        print(event)

    listener = NapCatListener(on_event)
    listener.start()

    # 方式3: 在其他线程中运行
    listener.start(blocking=False)
    # ... 做其他事情 ...
    listener.stop()
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

try:
    from .napcat_ws_client import NapCatWSClient, NapCatConfig, load_config
except ImportError:
    from napcat_ws_client import NapCatWSClient, NapCatConfig, load_config


# 事件类型常量
class EventType:
    MESSAGE = "message"
    PRIVATE_MESSAGE = "private"
    GROUP_MESSAGE = "group"
    NOTICE = "notice"
    REQUEST = "request"
    META_EVENT = "meta_event"


# 消息类型
class MessageType:
    TEXT = "text"
    IMAGE = "image"
    AT = "at"
    REPLY = "reply"
    FACE = "face"
    RECORD = "record"
    VIDEO = "video"


@dataclass
class Event:
    """事件封装类，提供便捷属性访问"""
    raw: dict[str, Any]

    @property
    def post_type(self) -> str:
        """事件类型: message/notice/request/meta_event"""
        return self.raw.get("post_type", "")

    @property
    def message_type(self) -> str:
        """消息类型: private/group"""
        return self.raw.get("message_type", "")

    @property
    def notice_type(self) -> str:
        """通知类型"""
        return self.raw.get("notice_type", "")

    @property
    def request_type(self) -> str:
        """请求类型"""
        return self.raw.get("request_type", "")

    @property
    def sub_type(self) -> str:
        """子类型"""
        return self.raw.get("sub_type", "")

    @property
    def user_id(self) -> int | None:
        """发送者 ID"""
        return self.raw.get("user_id")

    @property
    def group_id(self) -> int | None:
        """群 ID"""
        return self.raw.get("group_id")

    @property
    def message_id(self) -> int | None:
        """消息 ID"""
        return self.raw.get("message_id")

    @property
    def raw_message(self) -> str:
        """原始消息文本"""
        value = self.raw.get("raw_message", "")
        return value if isinstance(value, str) else str(value or "")

    @property
    def message(self) -> list | str:
        """消息内容（数组或字符串）"""
        value = self.raw.get("message", [])
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return value
        return []

    @property
    def sender(self) -> dict:
        """发送者信息"""
        value = self.raw.get("sender", {})
        return value if isinstance(value, dict) else {}

    @property
    def nickname(self) -> str:
        """发送者昵称"""
        return self.sender.get("nickname", "")

    @property
    def card(self) -> str:
        """发送者群名片"""
        return self.sender.get("card", "")

    @property
    def display_name(self) -> str:
        """显示名称（优先群名片，其次昵称）"""
        return self.card or self.nickname

    @property
    def self_id(self) -> int | None:
        """机器人自身 ID"""
        return self.raw.get("self_id")

    @property
    def time(self) -> int | None:
        """事件时间戳"""
        return self.raw.get("time")

    def is_private(self) -> bool:
        """是否私聊消息"""
        return self.post_type == EventType.MESSAGE and self.message_type == EventType.PRIVATE_MESSAGE

    def is_group(self) -> bool:
        """是否群消息"""
        return self.post_type == EventType.MESSAGE and self.message_type == EventType.GROUP_MESSAGE

    def is_at_self(self) -> bool:
        """是否 @ 了机器人"""
        if not self.is_group():
            return False
        for seg in self.message if isinstance(self.message, list) else []:
            if not isinstance(seg, dict):
                continue
            if seg.get("type") == MessageType.AT:
                data = seg.get("data", {})
                if not isinstance(data, dict):
                    continue
                if str(data.get("qq", "")) == str(self.self_id):
                    return True
        return False

    def get_text_content(self) -> str:
        """获取纯文本内容（去除其他消息段）"""
        if isinstance(self.message, str):
            return self.message
        texts = []
        for seg in self.message:
            if not isinstance(seg, dict):
                continue
            if seg.get("type") == MessageType.TEXT:
                data = seg.get("data", {})
                if isinstance(data, dict):
                    texts.append(str(data.get("text", "")))
        return "".join(texts)

    def _format_timestamp(self) -> str | None:
        if self.time is None:
            return None
        try:
            return datetime.fromtimestamp(self.time).astimezone().isoformat(timespec="seconds")
        except (OSError, OverflowError, ValueError):
            return None

    def _format_message_segments(self) -> list[dict[str, Any]] | str:
        if isinstance(self.message, str):
            return self.message

        segments: list[dict[str, Any]] = []
        for seg in self.message if isinstance(self.message, list) else []:
            if not isinstance(seg, dict):
                segments.append({"type": "unknown", "value": seg})
                continue
            seg_type = str(seg.get("type", ""))
            raw_data = seg.get("data", {}) or {}
            data = raw_data if isinstance(raw_data, dict) else {"value": raw_data}
            item: dict[str, Any] = {"type": seg_type}

            if seg_type == MessageType.TEXT:
                item["text"] = data.get("text", "")
            elif seg_type == MessageType.AT:
                item["qq"] = data.get("qq")
            elif seg_type == MessageType.REPLY:
                item["reply_id"] = data.get("id")
            else:
                item["data"] = data

            segments.append(item)
        return segments

    def to_dict(self, *, include_raw: bool = False) -> dict[str, Any]:
        """返回更适合阅读和序列化的事件字典"""
        payload = {
            "event_type": {
                "post_type": self.post_type,
                "message_type": self.message_type or None,
                "notice_type": self.notice_type or None,
                "request_type": self.request_type or None,
                "sub_type": self.sub_type or None,
            },
            "time": {
                "timestamp": self.time,
                "iso": self._format_timestamp(),
            },
            "self_id": self.self_id,
            "user_id": self.user_id,
            "group_id": self.group_id,
            "message_id": self.message_id,
            "sender": {
                "nickname": self.nickname or None,
                "card": self.card or None,
                "display_name": self.display_name or None,
                "details": self.sender,
            },
            "message": {
                "raw_message": self.raw_message or None,
                "text": self.get_text_content() or None,
                "segments": self._format_message_segments(),
            },
            "flags": {
                "is_private": self.is_private(),
                "is_group": self.is_group(),
                "is_at_self": self.is_at_self(),
            },
        }
        if include_raw:
            payload["raw"] = self.raw
        return payload

    def pretty_json(self, *, include_raw: bool = False, indent: int = 2) -> str:
        return json.dumps(self.to_dict(include_raw=include_raw), ensure_ascii=False, indent=indent)

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    def __repr__(self) -> str:
        return f"Event(post_type={self.post_type!r}, user_id={self.user_id!r}, group_id={self.group_id!r}, text={self.get_text_content()!r})"

    def __str__(self) -> str:
        return self.pretty_json()


class NapCatListener:
    """NapCat 事件监听器"""

    def __init__(
        self,
        callback: Callable[[Event], None] | None = None,
        config: NapCatConfig | None = None,
    ) -> None:
        """
        Args:
            callback: 通用事件回调函数
            config: NapCat 配置
        """
        self._config = config or load_config()
        self._client: NapCatWSClient | None = None
        self._running = False
        self._thread: threading.Thread | None = None

        # 事件处理器
        self._callback = callback
        self._handlers: dict[str, list[Callable[[Event], None]]] = {
            EventType.MESSAGE: [],
            EventType.PRIVATE_MESSAGE: [],
            EventType.GROUP_MESSAGE: [],
            EventType.NOTICE: [],
            EventType.REQUEST: [],
            EventType.META_EVENT: [],
            "all": [],  # 所有事件
        }

    # ==================== 装饰器注册 ====================

    def on(self, event_type: str = "all"):
        """注册事件处理器装饰器

        Args:
            event_type: 事件类型，可选 message/private/group/notice/request/meta_event/all
        """
        def decorator(func: Callable[[Event], None]) -> Callable[[Event], None]:
            self._handlers.setdefault(event_type, []).append(func)
            return func
        return decorator

    def on_private_message(self, func: Callable[[Event], None]) -> Callable[[Event], None]:
        """注册私聊消息处理器"""
        self._handlers[EventType.PRIVATE_MESSAGE].append(func)
        return func

    def on_group_message(self, func: Callable[[Event], None]) -> Callable[[Event], None]:
        """注册群消息处理器"""
        self._handlers[EventType.GROUP_MESSAGE].append(func)
        return func

    def on_message(self, func: Callable[[Event], None]) -> Callable[[Event], None]:
        """注册消息处理器（私聊+群聊）"""
        self._handlers[EventType.MESSAGE].append(func)
        return func

    def on_notice(self, func: Callable[[Event], None]) -> Callable[[Event], None]:
        """注册通知处理器"""
        self._handlers[EventType.NOTICE].append(func)
        return func

    def on_request(self, func: Callable[[Event], None]) -> Callable[[Event], None]:
        """注册请求处理器"""
        self._handlers[EventType.REQUEST].append(func)
        return func

    def on_meta_event(self, func: Callable[[Event], None]) -> Callable[[Event], None]:
        """注册元事件处理器"""
        self._handlers[EventType.META_EVENT].append(func)
        return func

    # ==================== 连接控制 ====================

    def start(self, blocking: bool = True) -> None:
        """开始监听事件

        Args:
            blocking: 是否阻塞主线程。False 时在后台线程运行
        """
        if self._running:
            return

        self._running = True
        self._client = NapCatWSClient(self._config, api_only=False)
        self._client.connect()

        if blocking:
            self._listen_loop()
        else:
            self._thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """停止监听"""
        self._running = False
        if self._client:
            self._client.close()
            self._client = None

    def _listen_loop(self) -> None:
        """监听循环"""
        try:
            while self._running:
                event = self._client.recv_event_blocking()
                if event:
                    self._dispatch(event)
        except Exception as e:
            if self._running:
                print(f"监听错误: {e}")
        finally:
            self.stop()

    def _dispatch(self, raw_event: dict[str, Any]) -> None:
        """分发事件到处理器"""
        event = Event(raw_event)

        # 通用回调
        if self._callback:
            try:
                self._callback(event)
            except Exception as e:
                print(f"回调执行错误: {e}")

        # 所有事件处理器
        for handler in self._handlers.get("all", []):
            try:
                handler(event)
            except Exception as e:
                print(f"处理器执行错误: {e}")

        # 按类型分发
        if event.post_type == EventType.MESSAGE:
            for handler in self._handlers.get(EventType.MESSAGE, []):
                try:
                    handler(event)
                except Exception as e:
                    print(f"处理器执行错误: {e}")

            if event.is_private():
                for handler in self._handlers.get(EventType.PRIVATE_MESSAGE, []):
                    try:
                        handler(event)
                    except Exception as e:
                        print(f"处理器执行错误: {e}")
            elif event.is_group():
                for handler in self._handlers.get(EventType.GROUP_MESSAGE, []):
                    try:
                        handler(event)
                    except Exception as e:
                        print(f"处理器执行错误: {e}")

        elif event.post_type == EventType.NOTICE:
            for handler in self._handlers.get(EventType.NOTICE, []):
                try:
                    handler(event)
                except Exception as e:
                    print(f"处理器执行错误: {e}")

        elif event.post_type == EventType.REQUEST:
            for handler in self._handlers.get(EventType.REQUEST, []):
                try:
                    handler(event)
                except Exception as e:
                    print(f"处理器执行错误: {e}")

        elif event.post_type == EventType.META_EVENT:
            for handler in self._handlers.get(EventType.META_EVENT, []):
                try:
                    handler(event)
                except Exception as e:
                    print(f"处理器执行错误: {e}")

    def __enter__(self) -> "NapCatListener":
        self.start(blocking=False)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()


# ==================== 命令行入口 ====================

def main() -> None:
    """命令行运行事件监听"""
    import argparse

    parser = argparse.ArgumentParser(description="NapCat 事件监听器")
    parser.add_argument("--filter", choices=["private", "group", "notice", "request"], help="只显示指定类型事件")
    args = parser.parse_args()

    def on_event(event: Event) -> None:
        # 过滤
        if args.filter:
            if args.filter == "private" and not event.is_private():
                return
            if args.filter == "group" and not event.is_group():
                return
            if args.filter == "notice" and event.post_type != EventType.NOTICE:
                return
            if args.filter == "request" and event.post_type != EventType.REQUEST:
                return
        # print(event.to_dict())
        # print(event.to_dict()["event_type"]["post_type"])
        if event.to_dict()["event_type"]["post_type"]=="message":
            if event.to_dict()["flags"]["is_group"]:
                print("【是群聊】")
                print(event.to_dict()["message"]["raw_message"])
                print(event.to_dict()["sender"]["details"]["user_id"])
            elif event.to_dict()["flags"]["is_private"]:
                print("【是私聊】")
                print(event.to_dict()["message"]["raw_message"])
                print(event.to_dict()["sender"]["details"]["user_id"])

    listener = NapCatListener(on_event)

    try:
        print("开始监听事件，按 Ctrl+C 停止...")
        listener.start(blocking=True)
    except KeyboardInterrupt:
        print("\n已停止监听")


if __name__ == "__main__":
    main()
