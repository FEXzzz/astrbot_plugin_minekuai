"""Single application boundary for all chat and function-tool entry points."""

from dataclasses import asdict

from .errors import MinekuaiError
from .models import Result
from .state import Results

HELP = """麦块资源助手
/麦块 搜索 机械动力
/麦块 搜索 优化 类型=模组 来源=mr 版本=1.20.1 加载器=fabric
/麦块 热门 类型=整合包 来源=cf
/麦块 详情 mr_mod:jei（也可使用最近资源序号）
/麦块 版本 mr_mod:jei 版本=1.20.1 加载器=forge
/麦块 下载 mr_mod:jei 版本=1.20.1 加载器=forge [预览=是] [版本ID=...]
/麦块 筛选 类型=模组 来源=mr
/麦块 下一页
来源：mr / cf / spigot；类型：模组 / 整合包 / 光影 / 资源包 / 插件。
多值用英文逗号分隔；含空格的关键词和参数值可加引号。

实例管理（仅 AstrBot 管理员，各项群聊／私聊权限由配置面板决定）
/麦块 实例 列表 [页=1]
/麦块 实例 状态 <8位identifier或别名>
/麦块 实例 启动|停止|重启|强停 <实例>
/麦块 实例 命令 <实例> say hello
/麦块 实例 启动配置 <实例>
/麦块 实例 设置变量 <实例> MAX_PLAYERS 20
/麦块 实例 可切换游戏 <实例>
/麦块 实例 切换游戏 <实例> minecraft
/麦块 实例 切换整合包 <实例> id=1 或 文件=xxx.zip
/麦块 实例 读取文件 <实例> /server.properties [页=1]
/麦块 实例 确认|取消 <确认码>
所有修改先预览再确认，切换游戏／整合包会清空全部文件。

/麦块 诊断、/麦块 清理缓存（仅 AstrBot 管理员）"""


class App:
    def __init__(self, resources, panel):
        self.resources = resources
        self.panel = panel
        self.results = Results()

    def get_result(self, actor, result_id):
        stored = self.results.get(actor, result_id)
        if stored.result.private:
            self.panel.guard.check(actor, stored.result.operation)
            if stored.credential_fingerprint != self.panel.fingerprint:
                raise MinekuaiError("密钥已变化，旧实例结果已失效，请重新查询。")
        return stored.result

    async def execute(self, actor, action, **kwargs):
        if action == "present":
            result_id = kwargs.get("result_id", "")
            return result_id, self.get_result(actor, result_id)
        if action == "next":
            stored = self.results.last(actor)
            if stored.result.private:
                self.panel.guard.check(actor, stored.result.operation)
                if stored.credential_fingerprint != self.panel.fingerprint:
                    raise MinekuaiError("密钥已变化，请重新查询。")
            if not stored.result.next_request:
                raise MinekuaiError("当前结果没有下一页。聚合搜索请指定类型和来源后查询。")
            request = dict(stored.result.next_request)
            return await self.execute(actor, request.pop("action"), **request)
        if action in {"detail", "versions", "download"}:
            kwargs["resource_key"] = self.results.resolve_resource(
                actor, str(kwargs.get("resource_key", ""))
            )
        initial_fingerprint = self.panel.fingerprint
        if action in {"search", "detail", "versions", "download", "filters"}:
            result = await getattr(self.resources, action)(**kwargs)
        elif action == "instance_list":
            result = await self.panel.list_servers(actor, **kwargs)
        elif action in {
            "instance_status",
            "instance_startup",
            "instance_allowed_games",
            "instance_file",
            "instance_prepare",
            "instance_confirm",
            "instance_cancel",
        }:
            method = {
                "instance_status": self.panel.status,
                "instance_startup": self.panel.startup,
                "instance_allowed_games": self.panel.allowed_games,
                "instance_file": self.panel.read_file,
                "instance_prepare": self.panel.prepare,
                "instance_confirm": self.panel.confirm,
                "instance_cancel": self.panel.cancel,
            }[action]
            if action == "instance_cancel":
                result = method(actor, **kwargs)
            else:
                result = await method(actor, **kwargs)
        elif action == "help":
            result = Result("麦块助手 · 帮助", note=HELP)
        elif action in {"diagnostics", "clear_cache"}:
            if not actor.is_admin:
                raise MinekuaiError("此指令仅限 AstrBot 管理员。")
            if action == "clear_cache":
                self.resources.api.clear()
                self.panel.api.clear()
                self.results.clear()
                result = Result("查询缓存已清理", note="待确认操作和切换冷却保持有效。")
            else:
                settings = self.panel.settings
                result = Result(
                    "插件诊断",
                    note=(
                        f"资源接口：已就绪\n实例模块：{'已启用' if settings.get('instance_enabled', False) else '未启用'}"
                        f"\n密钥：{'已配置' if settings.api_key.startswith('mkc_') else '未配置'}"
                        f"\n资源缓存：{len(self.resources.api.cache.items)} 项\n实例缓存：{len(self.panel.api.cache.items)} 项"
                    ),
                )
        else:
            raise MinekuaiError("未知操作，请发送 /麦块 帮助。")
        if result.private:
            self.panel.guard.check(actor, result.operation)
            if initial_fingerprint != self.panel.fingerprint:
                raise MinekuaiError("请求期间密钥发生变化，请重新查询或在面板核对操作状态。")
        result_id = self.results.save(
            actor,
            result,
            {"action": action, **kwargs},
            self.panel.fingerprint if result.private else "",
        )
        return result_id, result

    @staticmethod
    def tool_output(result_id, result):
        data = asdict(result)
        data.pop("next_request", None)
        data.update({"result_id": result_id, "next_available": result.next_request is not None})
        return data

    async def close(self):
        self.panel.close()
        self.results.clear()
        await self.resources.api.close()
        await self.panel.api.close()
