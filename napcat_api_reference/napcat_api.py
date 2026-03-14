"""
NapCat API 简洁封装 - 方便在其他代码中直接导入使用

使用示例:
    from napcat_api import NapCatAPI

    # 方式1: 使用 with 语句（推荐）
    with NapCatAPI() as api:
        api.send_private_msg(user_id="123456789", message="你好")
        result = api.get_login_info()

    # 方式2: 手动管理连接
    api = NapCatAPI()
    api.connect()
    api.send_private_msg(user_id="123456789", message="你好")
    api.close()

    # 方式3: 单次调用（自动连接和关闭）
    result = NapCatAPI.call("send_private_msg", {"user_id": "123456789", "message": "你好"})
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .napcat_ws_client import NapCatWSClient, NapCatConfig, load_config


class NapCatAPI:
    """NapCat API 简洁封装类

    提供常用 QQ 操作的快捷方法，也支持调用任意 API。
    """

    def __init__(self, config: NapCatConfig | None = None) -> None:
        self._client = NapCatWSClient(config, api_only=True)

    def connect(self) -> "NapCatAPI":
        """建立连接"""
        self._client.connect()
        return self

    def close(self) -> None:
        """关闭连接"""
        self._client.close()

    def __enter__(self) -> "NapCatAPI":
        return self.connect()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ==================== 底层 API 调用 ====================

    def call(self, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """调用任意 API

        Args:
            action: API 名称，如 "send_private_msg"
            params: 参数字典

        Returns:
            API 响应结果
        """
        return self._client.call_api(action, params)

    # ==================== 消息发送 ====================

    def send_private_msg(self, user_id: str | int, message: str | list) -> dict[str, Any]:
        """发送私聊消息

        Args:
            user_id: 目标用户 ID
            message: 消息内容（字符串或消息段数组）

        Returns:
            {"message_id": 123456}
        """
        return self.call("send_private_msg", {
            "user_id": str(user_id),
            "message": message
        })

    def send_group_msg(self, group_id: str | int, message: str | list) -> dict[str, Any]:
        """发送群消息

        Args:
            group_id: 目标群 ID
            message: 消息内容（字符串或消息段数组）

        Returns:
            {"message_id": 123456}
        """
        return self.call("send_group_msg", {
            "group_id": str(group_id),
            "message": message
        })

    def send_msg(
        self,
        message: str | list,
        *,
        user_id: str | int | None = None,
        group_id: str | int | None = None,
    ) -> dict[str, Any]:
        """智能发送消息（自动判断私聊或群聊）

        Args:
            message: 消息内容
            user_id: 私聊目标用户 ID
            group_id: 群聊目标群 ID

        Returns:
            {"message_id": 123456}
        """
        if group_id:
            return self.send_group_msg(group_id, message)
        if user_id:
            return self.send_private_msg(user_id, message)
        raise ValueError("必须指定 user_id 或 group_id")

    def delete_msg(self, message_id: int) -> dict[str, Any]:
        """撤回消息"""
        return self.call("delete_msg", {"message_id": message_id})

    def get_msg(self, message_id: int) -> dict[str, Any]:
        """获取消息详情"""
        return self.call("get_msg", {"message_id": message_id})

    # ==================== 用户信息 ====================

    def get_login_info(self) -> dict[str, Any]:
        """获取登录号信息

        Returns:
            {"user_id": "123456", "nickname": "昵称"}
        """
        return self.call("get_login_info")

    def get_status(self) -> dict[str, Any]:
        """获取运行状态"""
        return self.call("get_status")

    def get_stranger_info(self, user_id: str | int) -> dict[str, Any]:
        """获取陌生人信息"""
        return self.call("get_stranger_info", {"user_id": str(user_id)})

    def get_friend_list(self, no_cache: bool = False) -> dict[str, Any]:
        """获取好友列表"""
        return self.call("get_friend_list", {"no_cache": no_cache})

    # ==================== 群组操作 ====================

    def get_group_list(self, no_cache: bool = False) -> dict[str, Any]:
        """获取群列表"""
        return self.call("get_group_list", {"no_cache": no_cache})

    def get_group_info(self, group_id: str | int, no_cache: bool = False) -> dict[str, Any]:
        """获取群信息"""
        return self.call("get_group_info", {
            "group_id": str(group_id),
            "no_cache": no_cache
        })

    def get_group_member_list(self, group_id: str | int, no_cache: bool = False) -> dict[str, Any]:
        """获取群成员列表"""
        return self.call("get_group_member_list", {
            "group_id": str(group_id),
            "no_cache": no_cache
        })

    def get_group_member_info(
        self, group_id: str | int, user_id: str | int, no_cache: bool = False
    ) -> dict[str, Any]:
        """获取群成员信息"""
        return self.call("get_group_member_info", {
            "group_id": str(group_id),
            "user_id": str(user_id),
            "no_cache": no_cache
        })

    def set_group_name(self, group_id: str | int, group_name: str) -> dict[str, Any]:
        """设置群名称"""
        return self.call("set_group_name", {
            "group_id": str(group_id),
            "group_name": group_name
        })

    def set_group_card(
        self, group_id: str | int, user_id: str | int, card: str = ""
    ) -> dict[str, Any]:
        """设置群名片"""
        return self.call("set_group_card", {
            "group_id": str(group_id),
            "user_id": str(user_id),
            "card": card
        })

    def set_group_kick(
        self, group_id: str | int, user_id: str | int, reject_add_request: bool = False
    ) -> dict[str, Any]:
        """踢出群成员"""
        return self.call("set_group_kick", {
            "group_id": str(group_id),
            "user_id": str(user_id),
            "reject_add_request": reject_add_request
        })

    def set_group_ban(
        self, group_id: str | int, user_id: str | int, duration: int = 1800
    ) -> dict[str, Any]:
        """禁言群成员

        Args:
            group_id: 群 ID
            user_id: 用户 ID
            duration: 禁言时长（秒），0 表示解禁
        """
        return self.call("set_group_ban", {
            "group_id": str(group_id),
            "user_id": str(user_id),
            "duration": duration
        })

    def set_group_whole_ban(self, group_id: str | int, enable: bool) -> dict[str, Any]:
        """群全体禁言"""
        return self.call("set_group_whole_ban", {
            "group_id": str(group_id),
            "enable": enable
        })

    def set_group_admin(
        self, group_id: str | int, user_id: str | int, enable: bool = True
    ) -> dict[str, Any]:
        """设置群管理员"""
        return self.call("set_group_admin", {
            "group_id": str(group_id),
            "user_id": str(user_id),
            "enable": enable
        })

    # ==================== 个人设置 ====================

    def set_qq_avatar(self, file: str) -> dict[str, Any]:
        """设置 QQ 头像

        Args:
            file: 图片路径、URL 或 base64://...
        """
        return self.call("set_qq_avatar", {"file": file})

    def set_qq_profile(
        self,
        nickname: str | None = None,
        personal_note: str | None = None,
        sex: int | None = None,
    ) -> dict[str, Any]:
        """设置 QQ 资料

        Args:
            nickname: 昵称
            personal_note: 个人签名
            sex: 性别 (0=未知, 1=男, 2=女)
        """
        params: dict[str, Any] = {}
        if nickname is not None:
            params["nickname"] = nickname
        if personal_note is not None:
            params["personal_note"] = personal_note
        if sex is not None:
            params["sex"] = sex
        return self.call("set_qq_profile", params)

    def set_friend_remark(self, user_id: str | int, remark: str) -> dict[str, Any]:
        """设置好友备注"""
        return self.call("set_friend_remark", {
            "user_id": str(user_id),
            "remark": remark
        })

    # ==================== 互动操作 ====================

    def friend_poke(self, user_id: str | int) -> dict[str, Any]:
        """发送私聊戳一戳"""
        return self.call("friend_poke", {"user_id": str(user_id)})

    def group_poke(self, group_id: str | int, user_id: str | int) -> dict[str, Any]:
        """发送群聊戳一戳"""
        return self.call("group_poke", {
            "group_id": str(group_id),
            "user_id": str(user_id)
        })

    # ==================== 消息标记 ====================

    def mark_private_msg_as_read(self, user_id: str | int) -> dict[str, Any]:
        """标记私聊已读"""
        return self.call("mark_private_msg_as_read", {"user_id": str(user_id)})

    def mark_group_msg_as_read(self, group_id: str | int) -> dict[str, Any]:
        """标记群聊已读"""
        return self.call("mark_group_msg_as_read", {"group_id": str(group_id)})

    # ==================== 文件操作 ====================

    def get_image(self, file: str) -> dict[str, Any]:
        """获取图片信息"""
        return self.call("get_image", {"file": file})

    def get_record(self, file: str, out_format: str = "mp3") -> dict[str, Any]:
        """获取语音信息"""
        return self.call("get_record", {"file": file, "out_format": out_format})

    def get_file(self, file_id: str, group_id: str | int | None = None) -> dict[str, Any]:
        """获取文件信息"""
        params = {"file_id": file_id}
        if group_id:
            params["group_id"] = str(group_id)
        return self.call("get_file", params)

    # ==================== 类方法：单次调用 ====================

    @classmethod
    def call_once(cls, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """单次调用 API（自动连接和关闭）

        适用于只需调用一次 API 的场景。
        """
        with cls() as api:
            return api.call(action, params)


# 便捷函数
def quick_call(action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """快捷调用 API"""
    return NapCatAPI.call_once(action, params)


def send_private(user_id: str | int, message: str) -> dict[str, Any]:
    """快捷发送私聊消息"""
    with NapCatAPI() as api:
        return api.send_private_msg(user_id, message)


def send_group(group_id: str | int, message: str) -> dict[str, Any]:
    """快捷发送群消息"""
    with NapCatAPI() as api:
        return api.send_group_msg(group_id, message)
