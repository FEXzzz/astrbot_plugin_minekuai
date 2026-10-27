"""AstrBot entry point. Business logic is independently testable in minekuai/."""

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.agent.tool import FunctionTool
from astrbot.core.star.filter.command import GreedyStr
from pydantic.dataclasses import dataclass

from .minekuai.app import App
from .minekuai.commands import parse
from .minekuai.compat import (
    migrate_alias_config,
    plugin_logger,
    register_owned_tools,
    render_resource_card,
)
from .minekuai.errors import MinekuaiError, redact, redact_data
from .minekuai.http import ApiClient
from .minekuai.models import Actor
from .minekuai.panel import PanelService
from .minekuai.platforms import text_chunks
from .minekuai.rendering import LocalCards
from .minekuai.resources import ResourceService
from .minekuai.settings import Settings
from .minekuai.tool_specs import specs


@dataclass
class MinekuaiTool(FunctionTool):
    plugin: Any = None
    action: str = ""

    async def call(self, context, **kwargs):
        return await self.plugin.invoke_tool(context.context.event, self.action, kwargs)


class MinekuaiPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.logger = plugin_logger(self, logger)
        self.settings = Settings(config)
        self.data_dir = Path(StarTools.get_data_dir("astrbot_plugin_minekuai"))
        self.cards = LocalCards(self.data_dir, self.settings.get("local_font_path", ""))
        self.template = (Path(__file__).parent / "templates" / "card.html").read_text(
            encoding="utf-8"
        )
        public_api = ApiClient(self.settings)
        panel_api = ApiClient(self.settings, panel=True)
        panel = PanelService(
            panel_api, self.settings, save_cooldowns=self._save_cooldowns, audit=self._audit
        )
        self.app = App(ResourceService(public_api, self.settings), panel)
        self.tasks = set()
        self.tools = []
        self.closed = False

    async def initialize(self):
        if migrate_alias_config(self.settings.config):
            self.settings.config.save_config()
        stored = await self.get_kv_data("switch_cooldowns", {})
        self.app.panel.cooldowns = stored if isinstance(stored, dict) else {}
        self.tools = [
            MinekuaiTool(
                name=s.name,
                description=s.description,
                parameters=s.parameters,
                plugin=self,
                action=s.action,
            )
            for s in specs()
        ]
        register_owned_tools(self.context, self.tools, self.__class__.__module__)

    async def _save_cooldowns(self, value):
        await self.put_kv_data("switch_cooldowns", value)

    def _audit(self, entry):
        self.logger.info("minekuai_instance_audit " + json.dumps(entry, ensure_ascii=False))

    @staticmethod
    def _actor(event):
        return Actor(
            str(event.get_platform_id()),
            event.unified_msg_origin,
            str(event.get_sender_id()),
            str(event.get_group_id() or ""),
            bool(event.is_admin()),
            bool(event.is_private_chat()),
        )

    async def _send_result(self, event, actor, result_id, *, force_text=False):
        result = self.app.get_result(actor, result_id)
        use_card = not force_text and self.settings.get("cards_enabled", True)
        if result.private and result.operation not in {"list", "status"}:
            use_card = False
        if result.title.endswith("帮助") or not result.rows:
            use_card = False
        rendered = False
        if use_card:
            try:
                if result.private:
                    self.cards.font_path = self.settings.get("local_font_path", "")
                    path = await asyncio.to_thread(self.cards.render, result)
                else:
                    async with asyncio.timeout(self.settings.integer("render_timeout", 20, 1, 60)):
                        path = await render_resource_card(
                            self,
                            self.template,
                            redact_data(
                                {"title": result.title, "rows": result.rows, "note": result.note},
                                self.settings.api_key,
                            ),
                            actor.origin,
                        )
                self.app.get_result(self._actor(event), result_id)
                await event.send(event.image_result(path))
                rendered = True
            except asyncio.CancelledError:
                raise
            except MinekuaiError:
                # Permission changes must not be disguised as a render failure.
                self.app.get_result(self._actor(event), result_id)
            except Exception as exc:
                self.logger.warning("麦块卡片渲染／发送失败，回退文本：" + type(exc).__name__)
        if not rendered:
            self.app.get_result(self._actor(event), result_id)
            text = redact(result.text(), self.settings.api_key)
            await self._send_text(event, text, result_id)
        if result.links:
            self.app.get_result(self._actor(event), result_id)
            links = "\n".join(f"{link['label']}\n{link['url']}" for link in result.links)
            await self._send_text(event, links, result_id)

    async def _send_text(self, event, text, result_id=None):
        for chunk in text_chunks(text, event.get_platform_name()):
            if result_id is not None:
                self.app.get_result(self._actor(event), result_id)
            await event.send(event.plain_result(chunk))

    async def _run(self, event, command, args=""):
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            if self.closed:
                return
            # AstrBot's GreedyStr normalizes spaces. Recover the console payload from the original message.
            if command == "实例":
                match = re.search(r"(?:麦块|mk)\s+实例(?:\s+(.*))?$", event.get_message_str(), re.S)
                if match:
                    args = match.group(1) or ""
            action, kwargs = parse(command, str(args))
            actor = self._actor(event)
            result_id, _ = await self.app.execute(actor, action, **kwargs)
            await self._send_result(event, actor, result_id)
        except MinekuaiError as exc:
            await self._send_text(event, redact(str(exc), self.settings.api_key))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.error("麦块指令处理异常：" + type(exc).__name__)
            await self._send_text(
                event, "处理失败，请检查插件日志中的错误类型，或发送 /麦块 帮助。"
            )
        finally:
            self.tasks.discard(task)
            event.stop_event()

    async def invoke_tool(self, event, action, kwargs):
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            if self.closed:
                raise MinekuaiError("插件正在停用，请稍后重试。")
            # All actions are fixed in tool_specs; confirmation is deliberately absent.
            allowed = {spec.action for spec in specs()}
            if action not in allowed:
                raise MinekuaiError("此操作不能通过 AI 工具执行。")
            actor = self._actor(event)
            result_id, result = await self.app.execute(actor, action, **kwargs)
            if action in {"present", "instance_prepare"}:
                await self._send_result(
                    event, actor, result_id, force_text=action == "instance_prepare"
                )
            return json.dumps(
                redact_data(self.app.tool_output(result_id, result), self.settings.api_key),
                ensure_ascii=False,
            )
        except MinekuaiError as exc:
            return json.dumps(
                {"error": redact(str(exc), self.settings.api_key)}, ensure_ascii=False
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.error("麦块工具异常：" + type(exc).__name__)
            return json.dumps({"error": "工具处理失败，请检查插件日志。"}, ensure_ascii=False)
        finally:
            self.tasks.discard(task)

    @filter.command_group("麦块", alias={"mk"})
    def mk(self):
        """麦块资源查询与实例管理。"""

    @mk.command("搜索")
    async def search(self, event: AstrMessageEvent, args: GreedyStr):
        """搜索资源，可指定类型、来源、游戏版本和加载器。"""
        await self._run(event, "搜索", args)

    @mk.command("热门")
    async def popular(self, event: AstrMessageEvent, args: GreedyStr):
        """按下载量浏览指定类型资源。"""
        await self._run(event, "热门", args)

    @mk.command("详情")
    async def detail(self, event: AstrMessageEvent, args: GreedyStr):
        """查询资源详情。"""
        await self._run(event, "详情", args)

    @mk.command("版本")
    async def versions(self, event: AstrMessageEvent, args: GreedyStr):
        """查询兼容版本。"""
        await self._run(event, "版本", args)

    @mk.command("下载")
    async def download(self, event: AstrMessageEvent, args: GreedyStr):
        """获取兼容版本下载直链或项目页。"""
        await self._run(event, "下载", args)

    @mk.command("筛选")
    async def facets(self, event: AstrMessageEvent, args: GreedyStr):
        """查询可用筛选项。"""
        await self._run(event, "筛选", args)

    @mk.command("下一页")
    async def next_page(self, event: AstrMessageEvent):
        """查看当前用户最近查询的下一页。"""
        await self._run(event, "下一页")

    @mk.command("帮助")
    async def help_command(self, event: AstrMessageEvent):
        """查看完整帮助。"""
        await self._run(event, "帮助")

    @mk.command("实例")
    async def instances(self, event: AstrMessageEvent, args: GreedyStr):
        """实例列表、状态、电源、命令、变量、文件、切换及确认。"""
        await self._run(event, "实例", args)

    @mk.command("诊断")
    async def diagnostics(self, event: AstrMessageEvent):
        """管理员查询插件状态，不显示密钥。"""
        await self._run(event, "诊断")

    @mk.command("清理缓存")
    async def clear_cache(self, event: AstrMessageEvent):
        """管理员清理查询缓存。"""
        await self._run(event, "清理缓存")

    async def terminate(self):
        self.closed = True
        current = asyncio.current_task()
        tasks = [task for task in self.tasks if task is not current]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        # Remove only tool objects owned by this instance, never a newer reloaded instance.
        manager = self.context.provider_manager.llm_tools
        for tool in self.tools:
            if any(item is tool for item in manager.func_list):
                manager.remove_func(tool.name)
        self.tools.clear()
        await self.app.close()
