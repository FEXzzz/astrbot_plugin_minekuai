from types import SimpleNamespace

import pytest

from minekuai.compat import (
    migrate_alias_config,
    plugin_logger,
    register_owned_tools,
    render_resource_card,
)
from minekuai.errors import MinekuaiError
from minekuai.settings import Settings


def test_legacy_star_uses_astrbot_logger():
    fallback = object()
    assert plugin_logger(SimpleNamespace(), fallback) is fallback
    dedicated = object()
    assert plugin_logger(SimpleNamespace(logger=dedicated), fallback) is dedicated


def test_tools_keep_exact_module_ownership_on_legacy_context():
    def old_register(*tools):
        for tool in tools:
            tool.handler_module_path = "data.plugins.astrbot_plugin_minekuai"

    tool = SimpleNamespace()
    module = "data.plugins.astrbot_plugin_minekuai.main"
    register_owned_tools(SimpleNamespace(add_llm_tools=old_register), [tool], module)
    assert tool.handler_module_path == module


async def test_astrbot_416_render_has_no_umo_parameter():
    captured = []

    async def old_render(tmpl, data, return_url=True, options=None):
        captured.append((tmpl, data, return_url, options))
        return "legacy.png"

    result = await render_resource_card(
        SimpleNamespace(html_render=old_render), "template", {"title": "test"}, "qq:private:1"
    )
    assert result == "legacy.png"
    assert captured == [("template", {"title": "test"}, False, {"type": "png", "full_page": True})]


async def test_recent_renderer_receives_session_origin():
    captured = []

    async def new_render(tmpl, data, return_url=True, options=None, umo=None):
        captured.append(umo)
        return "current.png"

    result = await render_resource_card(
        SimpleNamespace(html_render=new_render), "template", {}, "qq:private:2"
    )
    assert result == "current.png" and captured == ["qq:private:2"]


async def test_renderer_internal_typeerror_is_not_retried():
    calls = []

    async def broken_renderer(tmpl, data, **kwargs):
        calls.append(kwargs)
        raise TypeError("internal renderer bug")

    with pytest.raises(TypeError, match="internal renderer bug"):
        await render_resource_card(
            SimpleNamespace(html_render=broken_renderer), "template", {}, "qq:private:1"
        )
    assert len(calls) == 1


def test_existing_alias_config_migrates_without_losing_other_settings():
    config = {
        "instance_aliases": {"生存服": "ab12cd34", "创意服": "abcd1234"},
        "instance_api_key": "mkc_test",
        "operation_permissions": {"start": {"scope": "private"}},
    }
    previous_permissions = config["operation_permissions"]
    assert migrate_alias_config(config)
    assert Settings(config).aliases == {"生存服": "ab12cd34", "创意服": "abcd1234"}
    assert (
        config["instance_api_key"] == "mkc_test"
        and config["operation_permissions"] is previous_permissions
    )
    assert config["instance_aliases"][0]["__template_key"] == "instance"
    assert not migrate_alias_config(config)


def test_legacy_alias_mapping_is_accepted_by_services_before_migration():
    assert Settings({"instance_aliases": {"生存服": "ab12cd34"}}).aliases == {"生存服": "ab12cd34"}


def test_ambiguous_duplicate_aliases_are_rejected():
    settings = Settings(
        {
            "instance_aliases": [
                {"alias": "生存服", "identifier": "ab12cd34"},
                {"alias": "生存服", "identifier": "abcd1234"},
            ]
        }
    )
    with pytest.raises(MinekuaiError, match="重复"):
        _ = settings.aliases
