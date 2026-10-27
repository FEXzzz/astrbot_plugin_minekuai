"""Exercise the real AstrBot loader/SDK with synthetic platform transport and panel.

Example: python scripts/check_astrbot_sdk.py --sdk .dev/astrbot-sdk --deps .dev/sdkdeps
"""

import argparse
import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import MethodType, SimpleNamespace
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


def configure():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--sdk", type=Path)
    parser.add_argument("--deps", type=Path)
    parser.add_argument("--runtime", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    if args.sdk:
        sys.path.insert(0, str(args.sdk.resolve()))
    if args.deps:
        sys.path.insert(0, str(args.deps.resolve()))
    runtime = (args.runtime or ROOT / ".dev" / "astrbot-run").resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    os.environ["ASTRBOT_ROOT"] = str(runtime)
    sys.path.insert(0, str(runtime))
    return runtime


async def check(runtime):
    import httpx
    from astrbot.api.event import AstrMessageEvent
    from astrbot.core import astrbot_config, db_helper
    from astrbot.core.config.default import VERSION
    from astrbot.core.platform.astrbot_message import AstrBotMessage
    from astrbot.core.platform.message_type import MessageType
    from astrbot.core.platform.platform_metadata import PlatformMetadata
    from astrbot.core.provider.register import llm_tools
    from astrbot.core.star.context import Context
    from astrbot.core.star.star import star_registry
    from astrbot.core.star.star_handler import star_handlers_registry
    from astrbot.core.star.star_manager import PluginManager

    from scripts.build_release import build

    archive = build()
    plugins = runtime / "data" / "plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    (runtime / "data" / "__init__.py").touch()
    (plugins / "__init__.py").touch()
    with ZipFile(archive) as z:
        for item in z.infolist():
            target = (plugins / item.filename).resolve()
            if not target.is_relative_to(plugins.resolve()):
                raise RuntimeError("Unsafe package member")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(item))

    context = SimpleNamespace(provider_manager=SimpleNamespace(llm_tools=llm_tools))
    context.add_llm_tools = MethodType(Context.add_llm_tools, context)
    context.get_all_stars = lambda: list(star_registry)
    manager = PluginManager(context, astrbot_config)
    config_path = runtime / "data" / "config" / "astrbot_plugin_minekuai_config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    old_config = (
        json.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.exists() else {}
    )
    old_config["instance_aliases"] = {"生存服": "ab12cd34"}
    config_path.write_text(json.dumps(old_config, ensure_ascii=False), encoding="utf-8")
    success, error = await manager.load(specified_dir_name="astrbot_plugin_minekuai")
    assert success, error
    metadata = next(s for s in star_registry if s.root_dir_name == "astrbot_plugin_minekuai")
    assert metadata.display_name == "麦块资源与实例助手"
    assert metadata.desc.startswith("支持九类")
    plugin = metadata.star_cls
    assert isinstance(plugin.settings.config["instance_aliases"], list)
    assert plugin.settings.aliases == {"生存服": "ab12cd34"}
    assert len(plugin.tools) == 12
    assert len([t for t in llm_tools.func_list if t.name.startswith("minekuai_")]) == 12
    assert all(t.handler_module_path == metadata.module_path for t in plugin.tools)

    spec = importlib.util.spec_from_file_location(
        "minekuai_synthetic_fixtures", ROOT / "tests" / "conftest.py"
    )
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    backend = fixtures.Backend()
    for api in [plugin.app.resources.api, plugin.app.panel.api]:
        await api.client.aclose()
        api.client = httpx.AsyncClient(
            transport=httpx.MockTransport(backend), follow_redirects=False
        )
    plugin.settings.config["cards_enabled"] = False

    class RecordingEvent(AstrMessageEvent):
        def __init__(self, text, admin=True, group="", platform="aiocqhttp"):
            msg = AstrBotMessage()
            msg.type = MessageType.GROUP_MESSAGE if group else MessageType.FRIEND_MESSAGE
            msg.sender = SimpleNamespace(user_id="10001", nickname="测试管理员")
            msg.group_id = group
            msg.self_id = "90000"
            msg.message_id = "synthetic-message"
            msg.message = []
            msg.message_str = text
            super().__init__(
                text,
                msg,
                PlatformMetadata(platform, "合成测试", platform + "-test"),
                group or "10001",
            )
            self.role = "admin" if admin else "member"
            self.is_at_or_wake_command = True
            self.sent = []

        async def send(self, result):
            self.sent.append(result)

    event = RecordingEvent("麦块 搜索 jei 类型=模组")
    handler = next(
        h
        for h in star_handlers_registry.get_handlers_by_module_name(metadata.module_path)
        if h.handler_name == "search"
    )
    for event_filter in handler.event_filters:
        assert event_filter.filter(event, astrbot_config)
    await handler.handler(event, **event.get_extra("parsed_params", {}))
    assert event.sent

    # Exercise the actual version's Star.html_render signature without using an external service.
    # 4.16 uses a module-global renderer; recent versions use context.html_renderer.
    class RecordingRenderer:
        def __init__(self):
            self.calls = []

        async def render_custom_template(self, tmpl, data, return_url=True, options=None, **kwargs):
            self.calls.append((return_url, options))
            return "https://example.invalid/synthetic-card.png"

    renderer = RecordingRenderer()
    context.get_config = lambda umo=None: {}
    context.html_renderer = renderer
    render_globals = plugin.html_render.__func__.__globals__
    previous_renderer = render_globals.get("html_renderer")
    if "html_renderer" in render_globals:
        render_globals["html_renderer"] = renderer
    from minekuai.compat import render_resource_card

    try:
        rendered = await render_resource_card(
            plugin, "<div>{{title}}</div>", {"title": "合成测试"}, event.unified_msg_origin
        )
        assert rendered.endswith("synthetic-card.png")
        assert renderer.calls == [(False, {"type": "png", "full_page": True})]
        plugin.settings.config["cards_enabled"] = True
        card_id, _ = await plugin.app.execute(
            plugin._actor(event), "search", query="jei", kind="mod"
        )
        before = len(event.sent)
        await plugin._send_result(event, plugin._actor(event), card_id)
        assert len(renderer.calls) == 2 and len(event.sent) > before
    finally:
        plugin.settings.config["cards_enabled"] = False
        if previous_renderer is not None:
            render_globals["html_renderer"] = previous_renderer
    query = next(t for t in plugin.tools if t.name == "minekuai_search")
    wrapper = SimpleNamespace(context=SimpleNamespace(event=event))
    response = json.loads(await query.call(wrapper, query="jei", kind="mod"))
    assert response["rows"] and response["result_id"]
    display = next(t for t in plugin.tools if t.name == "minekuai_present")
    response = json.loads(await display.call(wrapper, result_id=response["result_id"]))
    assert "error" not in response
    plugin.settings.config["instance_enabled"] = True
    plugin.settings.config["instance_api_key"] = "mkc_test_key_never_real"
    status_tool = next(t for t in plugin.tools if t.name == "minekuai_instance_status")
    denied = json.loads(
        await status_tool.call(
            SimpleNamespace(context=SimpleNamespace(event=RecordingEvent("test", admin=False))),
            identifier="ab12cd34",
        )
    )
    assert "error" in denied
    allowed = json.loads(await status_tool.call(wrapper, identifier="生存服"))
    assert allowed["rows"] and "running" in allowed["rows"][0]["subtitle"]

    # Platform adapters expose the same event interface. Exercise actual SDK filters,
    # plugin message chains and tools using each platform's channel/private semantics.
    from minekuai.models import Result

    platform_checks = []
    for platform, group, limit in [
        ("aiocqhttp", "123456", 4000),
        ("qq_official", "GROUP_OPENID", 1500),
        ("qq_official_webhook", "WEBHOOK_OPENID", 1500),
        ("discord", "123456789012345678", 2000),
    ]:
        for channel in ("", group):
            evt = RecordingEvent("麦块 搜索 jei 类型=模组", group=channel, platform=platform)
            for event_filter in handler.event_filters:
                assert event_filter.filter(evt, astrbot_config)
            await handler.handler(evt, **evt.get_extra("parsed_params", {}))
            assert evt.sent
            actor = plugin._actor(evt)
            assert actor.is_private == (not channel) and actor.group_id == channel
            config = plugin.settings.config["operation_permissions"]["status"]
            config.update(scope="both", allowed_groups=[f"{actor.platform_id}:{group}"])
            tool_context = SimpleNamespace(context=SimpleNamespace(event=evt))
            status = json.loads(await status_tool.call(tool_context, identifier="ab12cd34"))
            assert status["rows"] and "error" not in status
            denied = RecordingEvent("test", admin=False, group=channel, platform=platform)
            denied_output = json.loads(
                await status_tool.call(
                    SimpleNamespace(context=SimpleNamespace(event=denied)), identifier="ab12cd34"
                )
            )
            assert "error" in denied_output

            body = Result(
                "长消息",
                note="配置内容🙂\n" * 900,
                links=[{"label": "下载", "url": "https://example.invalid/mod.jar"}],
            )
            body_id = plugin.app.results.save(actor, body, {"action": "help"})
            evt.sent.clear()
            await plugin._send_result(evt, actor, body_id, force_text=True)
            parts = [part.text for message in evt.sent for part in message.chain]
            assert "".join(parts) == body.text() + "下载\nhttps://example.invalid/mod.jar"
            assert all(len(part.encode("utf-16-le")) // 2 <= limit for part in parts)

            # Use the same presentation path as minekuai_present for cards and failures.
            previous_render = plugin.html_render

            async def fake_render(*args, **kwargs):
                return "https://example.invalid/card.png"

            plugin.html_render = fake_render
            plugin.settings.config["cards_enabled"] = True
            card = Result("资源卡片", rows=[{"title": "测试资源"}], links=body.links)
            card_id = plugin.app.results.save(actor, card, {"action": "help"})
            evt.sent.clear()
            await plugin._send_result(evt, actor, card_id)
            assert any(part.type == "Image" for message in evt.sent for part in message.chain)

            async def broken_render(*args, **kwargs):
                raise RuntimeError("synthetic render failure")

            plugin.html_render = broken_render
            evt.sent.clear()
            await plugin._send_result(evt, actor, card_id)
            assert "".join(part.text for message in evt.sent for part in message.chain).startswith(
                card.text()
            )
            plugin.html_render = previous_render
            plugin.settings.config["cards_enabled"] = False
        platform_checks.append(platform)

    # Validate real SDK KV persistence as well as cleanup of both transports.
    await plugin.put_kv_data("switch_cooldowns", {"synthetic:ab12cd34": 1})
    assert await plugin.get_kv_data("switch_cooldowns", {}) == {"synthetic:ab12cd34": 1}
    old_plugin = plugin
    success, error = await manager.reload(metadata.name)
    assert success, error
    assert (
        old_plugin.closed
        and old_plugin.app.resources.api.client.is_closed
        and old_plugin.app.panel.api.client.is_closed
    )
    assert len([t for t in llm_tools.func_list if t.name.startswith("minekuai_")]) == 12
    metadata = next(s for s in star_registry if s.root_dir_name == "astrbot_plugin_minekuai")
    assert metadata.star_cls.app.panel.cooldowns == {"synthetic:ab12cd34": 1}
    reloaded = metadata.star_cls
    for api in [reloaded.app.resources.api, reloaded.app.panel.api]:
        await api.client.aclose()
        api.client = httpx.AsyncClient(
            transport=httpx.MockTransport(backend), follow_redirects=False
        )
    reloaded.settings.config["cards_enabled"] = False
    reloaded_query = next(t for t in reloaded.tools if t.name == "minekuai_search")
    assert all(t.handler_module_path == metadata.module_path for t in reloaded.tools)
    assert json.loads(await reloaded_query.call(wrapper, query="jei", kind="mod"))["rows"]
    await manager._terminate_plugin(metadata)
    assert not any(t.name.startswith("minekuai_") for t in llm_tools.func_list)
    await db_helper.engine.dispose()
    report = {
        "astrbot_version": VERSION,
        "real_sdk_loader": True,
        "tool_count": 12,
        "load": True,
        "command_filter_and_dispatch": True,
        "function_tool_call": True,
        "html_render_signature": True,
        "card_dispatch": True,
        "tool_module_ownership": True,
        "legacy_alias_config_migration": True,
        "admin_permission": True,
        "kv_persistence": True,
        "reload_without_duplicates": True,
        "query_after_reload": True,
        "terminate_closes_clients": True,
        "synthetic_platform_matrix": platform_checks,
        "platform_text_chunking_and_links": True,
        "platform_cards_and_text_fallback": True,
        "live_qq": False,
        "live_discord": False,
        "live_panel": False,
    }
    destination = ROOT / ".dev" / "verification"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "sdk-check.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (destination / f"sdk-check-{VERSION}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(check(configure()))
