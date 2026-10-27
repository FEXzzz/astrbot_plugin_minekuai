"""Strict command parsing, shared with the framework-free integration tests."""

import shlex

from .errors import MinekuaiError

OPTIONS = {
    "类型": "kind",
    "kind": "kind",
    "来源": "source",
    "source": "source",
    "页": "page",
    "page": "page",
    "版本": "game_version",
    "game_version": "game_version",
    "加载器": "loader",
    "loader": "loader",
    "分类": "category",
    "category": "category",
    "客户端": "client_side",
    "client_side": "client_side",
    "服务端": "server_side",
    "server_side": "server_side",
    "排序": "order",
    "order": "order",
    "方向": "dir",
    "dir": "dir",
    "翻译": "status",
    "status": "status",
    "版本ID": "version_id",
    "version_id": "version_id",
    "预览": "allow_prerelease",
    "allow_prerelease": "allow_prerelease",
    "id": "modpack_id",
    "文件": "file_name",
    "file_name": "file_name",
}


def tokens(text):
    try:
        return shlex.split(text)
    except ValueError as exc:
        raise MinekuaiError("引号未闭合，请检查指令。") from exc


def options(parts, allowed):
    positional, result = [], {}
    for item in parts:
        if "=" not in item:
            positional.append(item)
            continue
        name, value = item.split("=", 1)
        key = OPTIONS.get(name)
        if key not in allowed:
            raise MinekuaiError(f"该指令不支持参数 {name}。")
        if key in result:
            raise MinekuaiError(f"参数 {name} 重复，多值请用逗号分隔。")
        if key == "allow_prerelease":
            lowered = value.lower()
            if lowered not in {"是", "否", "true", "false", "yes", "no", "1", "0"}:
                raise MinekuaiError("预览参数请填写 是 或 否。")
            result[key] = lowered in {"是", "true", "yes", "1"}
        elif key in {"page", "modpack_id"}:
            try:
                result[key] = int(value)
            except ValueError as exc:
                raise MinekuaiError(f"参数 {name} 必须为整数。") from exc
        else:
            result[key] = value
    return positional, result


def parse(command, text=""):
    if command == "实例":
        first = text.strip().split(maxsplit=1)
        if not first:
            return "help", {}
        return parse_instance(first[0], first[1] if len(first) > 1 else "")
    if command in {"帮助", "下一页", "诊断", "清理缓存"}:
        if text.strip():
            raise MinekuaiError("此指令不接受额外参数。")
        return {"帮助": "help", "下一页": "next", "诊断": "diagnostics", "清理缓存": "clear_cache"}[
            command
        ], {}
    if command in {"搜索", "热门", "筛选"}:
        filters = {
            "game_version",
            "loader",
            "category",
            "client_side",
            "server_side",
            "status",
            "order",
            "dir",
        }
        positional, opts = options(tokens(text), filters | {"kind", "source", "page"})
        args = {"kind": opts.pop("kind", "all"), "source": opts.pop("source", "")}
        page = opts.pop("page", 1)
        args["filters"] = opts
        if command == "筛选":
            if positional or page != 1:
                raise MinekuaiError("筛选项查询仅接受 类型、来源和筛选条件。")
            return "filters", args
        args.update(query=" ".join(positional), page=page, popular=command == "热门")
        return "search", args
    if command in {"详情", "版本", "下载"}:
        parts = tokens(text)
        if not parts:
            raise MinekuaiError("请提供资源标识或最近结果序号。")
        reference = parts.pop(0)
        allowed = set() if command == "详情" else {"game_version", "loader", "page"}
        if command == "下载":
            allowed = {"game_version", "loader", "version_id", "allow_prerelease"}
        positional, opts = options(parts, allowed)
        if positional:
            raise MinekuaiError("额外筛选请使用 参数=值 的格式。")
        if "game_version" in opts:
            opts["game_versions"] = opts.pop("game_version")
        if "loader" in opts:
            opts["loaders"] = opts.pop("loader")
        return {"详情": "detail", "版本": "versions", "下载": "download"}[command], {
            "resource_key": reference,
            **opts,
        }
    raise MinekuaiError("未知指令，请发送 /麦块 帮助。")


def parse_instance(command, text):
    if command in {"确认", "取消"}:
        parts = tokens(text)
        if len(parts) != 1:
            raise MinekuaiError("请提供一个确认码。")
        return ("instance_confirm" if command == "确认" else "instance_cancel"), {"code": parts[0]}
    if command == "列表":
        positional, opts = options(tokens(text), {"page"})
        if positional:
            raise MinekuaiError("实例列表使用 页=1 指定页码。")
        return "instance_list", opts
    pieces = text.strip().split(maxsplit=1)
    if not pieces:
        raise MinekuaiError("请提供 8 位实例 identifier 或已配置的别名。")
    identifier, tail = pieces[0], pieces[1] if len(pieces) > 1 else ""
    read_actions = {
        "状态": "instance_status",
        "启动配置": "instance_startup",
        "可切换游戏": "instance_allowed_games",
    }
    if command in read_actions:
        if tail:
            raise MinekuaiError("此指令只接受一个实例标识。")
        return read_actions[command], {"identifier": identifier}
    if command == "读取文件":
        parts = tokens(tail)
        if not parts:
            raise MinekuaiError("格式：读取文件 <实例> /server.properties [页=1]。")
        path = parts.pop(0)
        positional, opts = options(parts, {"page"})
        if positional:
            raise MinekuaiError("格式：读取文件 <实例> /server.properties [页=1]。")
        return "instance_file", {"identifier": identifier, "path": path, **opts}
    operations = {
        "启动": "start",
        "停止": "stop",
        "重启": "restart",
        "强停": "kill",
        "命令": "command",
        "设置变量": "startup_write",
        "切换游戏": "game_switch",
        "切换整合包": "modpack_switch",
    }
    operation = operations.get(command)
    if operation is None:
        raise MinekuaiError("未知实例指令，请发送 /麦块 帮助。")
    payload = {}
    if operation == "command":
        payload = {"command": tail}
    elif operation == "startup_write":
        parts = tokens(tail)
        if len(parts) != 2:
            raise MinekuaiError("格式：设置变量 <实例> 变量名 值；含空格的值请加引号。")
        payload = {"key": parts[0], "value": parts[1]}
    elif operation == "game_switch":
        parts = tokens(tail)
        if len(parts) != 1:
            raise MinekuaiError("请指定 allowed-games 中的一个 game_type。")
        payload = {"game_type": parts[0]}
    elif operation == "modpack_switch":
        positional, payload = options(tokens(tail), {"modpack_id", "file_name"})
        if positional:
            raise MinekuaiError("切换整合包使用 id=1 或 文件=xxx.zip。")
    elif tail:
        raise MinekuaiError("电源操作只接受一个实例标识。")
    return "instance_prepare", {
        "identifier": identifier,
        "operation": operation,
        "payload": payload,
    }
