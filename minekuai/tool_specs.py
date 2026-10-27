"""Explicit JSON schemas. No function tool can commit a pending operation."""

from dataclasses import dataclass

from .resources import GROUPS
from .settings import WRITE_OPERATIONS


def string(description, **kwargs):
    return {"type": "string", "description": description, **kwargs}


def schema(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


@dataclass(frozen=True)
class ToolSpec:
    name: str
    action: str
    description: str
    parameters: dict


def specs():
    key = string("资源标识，必须来自查询结果，如 mr_mod:jei；也可为当前用户最近资源序号。")
    kind = string(
        "资源类型；高级筛选须指定类型。",
        enum=["all", "mod", "modpack", "shader", "resourcepack", "plugin", *GROUPS],
    )
    source = string("来源，默认 mr。", enum=["mr", "cf", "spigot"])
    array = {"type": "array", "items": {"type": "string"}, "maxItems": 20}
    page = {"type": "integer", "minimum": 1, "maximum": 10000, "description": "页码，从 1 开始。"}
    filters = schema(
        {
            **{
                k: {**array, "description": desc}
                for k, desc in {
                    "game_version": "Minecraft 游戏版本，多个值为 OR。",
                    "loader": "加载器，多个值为 OR。",
                    "category": "分类英文 slug；与加载器、版本跨维度为 AND。",
                    "client_side": "required/optional/unsupported/unknown",
                    "server_side": "required/optional/unsupported/unknown",
                }.items()
            },
            "status": string("翻译状态，默认不过滤。", enum=["translated", "pending", "failed"]),
            "order": string(
                "关键词搜索默认不传，以保留相关度。",
                enum=[
                    "source_index",
                    "downloads",
                    "follows",
                    "date_modified",
                    "date_created",
                    "translation_at",
                ],
            ),
            "dir": string("排序方向。", enum=["asc", "desc"]),
        }
    )
    version_properties = {
        "resource_key": key,
        "game_versions": {**array, "description": "需要的游戏版本。"},
        "loaders": {**array, "description": "需要的加载器。"},
    }
    tools = [
        ToolSpec(
            "minekuai_search",
            "search",
            "搜索 Minecraft 资源。未指定类型时仅做全站总览。高级筛选和分页须指定类型。结果需要展示时调用 minekuai_present。",
            schema(
                {
                    "query": string("中英文关键词，最多 200 字。", maxLength=200),
                    "kind": kind,
                    "source": source,
                    "filters": filters,
                    "page": page,
                    "popular": {"type": "boolean", "description": "按下载量浏览，需要指定类型。"},
                },
                ["query"],
            ),
        ),
        ToolSpec(
            "minekuai_detail",
            "detail",
            "获取一个明确来源的资源详情，返回可展示的结果引用。",
            schema({"resource_key": key}, ["resource_key"]),
        ),
        ToolSpec(
            "minekuai_versions",
            "versions",
            "查询资源发布版本，可筛选游戏版本和加载器。",
            schema({**version_properties, "page": page}, ["resource_key"]),
        ),
        ToolSpec(
            "minekuai_download",
            "download",
            "获取兼容的资源下载链接或原项目页。默认正式版；不下载或安装文件。",
            schema(
                {
                    **version_properties,
                    "version_id": string("指定接口返回的版本 ID。"),
                    "allow_prerelease": {
                        "type": "boolean",
                        "description": "用户明确需要预发布版时设为 true。",
                    },
                },
                ["resource_key"],
            ),
        ),
        ToolSpec(
            "minekuai_filters",
            "filters",
            "查询某一资源来源的可用游戏版本、加载器和分类。",
            schema({"kind": kind, "source": source, "filters": filters}, ["kind"]),
        ),
        ToolSpec(
            "minekuai_present",
            "present",
            "向用户展示之前查询生成的 result_id：发送卡片和文本链接。仅展示当前用户当前会话的结果。最终结果需要展示时调用一次，避免中间检索刷屏。",
            schema({"result_id": string("之前工具返回的 result_id。")}, ["result_id"]),
        ),
    ]
    identifier = string("8 位实例 identifier 或管理员配置的精确别名。")
    private_note = "仅 AstrBot 管理员可用，并受对应操作的群聊／私聊配置限制。"
    tools += [
        ToolSpec(
            "minekuai_instance_list",
            "instance_list",
            private_note + "查询当前面板密钥的实例列表。",
            schema({"page": page}),
        ),
        ToolSpec(
            "minekuai_instance_status",
            "instance_status",
            private_note + "查询实例实时状态与资源用量。",
            schema({"identifier": identifier}, ["identifier"]),
        ),
        ToolSpec(
            "minekuai_instance_startup",
            "instance_startup",
            private_note + "查询启动命令与变量，敏感内容会遮罩。",
            schema({"identifier": identifier}, ["identifier"]),
        ),
        ToolSpec(
            "minekuai_instance_allowed_games",
            "instance_allowed_games",
            private_note + "查询套餐允许切换的 game_type。",
            schema({"identifier": identifier}, ["identifier"]),
        ),
        ToolSpec(
            "minekuai_instance_read_file",
            "instance_file",
            private_note + "按路径读取不超过 1 MB 的实例文件，仅返回脱敏文本分页。",
            schema(
                {
                    "identifier": identifier,
                    "path": string("实例内绝对路径，如 /server.properties。"),
                    "page": page,
                },
                ["identifier", "path"],
            ),
        ),
        ToolSpec(
            "minekuai_instance_prepare_action",
            "instance_prepare",
            private_note
            + "仅生成操作预览并请用户手动确认，不直接修改。start/stop/restart/kill 的 payload={}；command 使用 command；startup_write 使用 key/value；game_switch 使用 game_type；modpack_switch 使用 modpack_id 或 file_name 二选一。切换会清空全部文件。不得尝试用其他工具执行确认。",
            schema(
                {
                    "identifier": identifier,
                    "operation": string("待准备的操作。", enum=sorted(WRITE_OPERATIONS)),
                    "payload": schema(
                        {
                            "command": string("单行控制台命令。"),
                            "key": string("startup 返回的 env_variable，不是 API 密钥。"),
                            "value": string("启动变量新值。"),
                            "game_type": string("allowed-games 返回的游戏类型。"),
                            "modpack_id": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "面板整合包 ID，不能用公共资源 ID。",
                            },
                            "file_name": string("面板已提供的整合包文件名，不能为 URL。"),
                        }
                    ),
                },
                ["identifier", "operation", "payload"],
            ),
        ),
    ]
    return tools
