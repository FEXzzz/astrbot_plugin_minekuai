"""Live configuration access; permissions never use a stale copied config."""

from collections.abc import Mapping

from .errors import MinekuaiError

OPERATIONS = {
    "list": "实例列表",
    "status": "实例状态",
    "start": "启动",
    "stop": "停止",
    "restart": "重启",
    "kill": "强停",
    "command": "控制台命令",
    "startup_read": "读取启动配置",
    "startup_write": "修改启动变量",
    "allowed_games": "可切换游戏",
    "game_switch": "切换游戏",
    "modpack_switch": "切换整合包",
    "file_read": "读取文件",
}
WRITE_OPERATIONS = {
    "start",
    "stop",
    "restart",
    "kill",
    "command",
    "startup_write",
    "game_switch",
    "modpack_switch",
}


class Settings:
    def __init__(self, config: Mapping):
        self.config = config

    def get(self, key, default=None):
        return self.config.get(key, default)

    @property
    def aliases(self):
        configured = self.get("instance_aliases", [])
        if isinstance(configured, Mapping):
            return dict(configured)
        if not isinstance(configured, list):
            raise MinekuaiError("实例别名配置无效，请在配置面板使用别名列表。")
        aliases = {}
        for entry in configured:
            if not isinstance(entry, Mapping):
                raise MinekuaiError("实例别名条目必须包含 alias 和 identifier。")
            alias, identifier = entry.get("alias"), entry.get("identifier")
            if not isinstance(alias, str) or not alias or not isinstance(identifier, str):
                raise MinekuaiError("请补全实例别名和 identifier。")
            if alias in aliases:
                raise MinekuaiError("实例别名重复，请在配置面板为每个实例设置唯一别名。")
            aliases[alias] = identifier
        return aliases

    def integer(self, key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            return max(minimum, min(maximum, int(self.get(key, default))))
        except (ValueError, TypeError):
            return default

    @property
    def api_key(self) -> str:
        return str(self.get("instance_api_key", "")).strip()

    @property
    def page_size(self) -> int:
        return self.integer("page_size", 5, 1, 10)

    @property
    def read_timeout(self) -> int:
        return self.integer("read_timeout", 10, 1, 60)

    @property
    def write_timeout(self) -> int:
        return self.integer("write_timeout", 30, 1, 120)
