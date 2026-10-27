"""One guard for commands, tools, result presentation and confirmation."""

from .errors import MinekuaiError
from .models import Actor
from .settings import OPERATIONS, Settings


class Guard:
    def __init__(self, settings: Settings):
        self.settings = settings

    def check(self, actor: Actor, operation: str) -> None:
        if operation not in OPERATIONS:
            raise MinekuaiError("未知的实例操作。")
        if not actor.is_admin:
            raise MinekuaiError("实例管理仅限 AstrBot 管理员使用。")
        if self.settings.get("instance_enabled", False) is not True:
            raise MinekuaiError("实例管理尚未启用，请在插件配置面板启用。")
        if not self.settings.api_key.startswith("mkc_"):
            raise MinekuaiError("请在插件配置面板填写完整的 mkc_ 开头密钥。")
        permissions = self.settings.get("operation_permissions", {})
        item = permissions.get(operation, {}) if isinstance(permissions, dict) else {}
        if not isinstance(item, dict):
            raise MinekuaiError("该操作的权限配置无效，请检查配置面板。")
        scope = item.get("scope", "private")
        if scope not in {"disabled", "private", "group", "both"}:
            scope = "disabled"
        if scope == "disabled":
            raise MinekuaiError("管理员已禁用该实例操作。")
        if actor.is_private:
            if scope not in {"private", "both"}:
                raise MinekuaiError("该实例操作未允许在私聊中使用。")
            return
        if scope not in {"group", "both"}:
            raise MinekuaiError("该实例操作仅允许在管理员私聊中使用。")
        groups = item.get("allowed_groups", [])
        if not isinstance(groups, list):
            groups = []
        # Plain QQ group IDs apply to this QQ adapter; qualified IDs disambiguate bots.
        accepted = {str(g) for g in groups}
        if not actor.group_id or not (
            actor.group_id in accepted or f"{actor.platform_id}:{actor.group_id}" in accepted
        ):
            raise MinekuaiError("当前群未获准使用该实例操作。")
