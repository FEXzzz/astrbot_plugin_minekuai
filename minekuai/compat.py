"""AstrBot 4.16+ compatibility without catching/retrying real renderer errors."""

import inspect
from collections.abc import Mapping


def migrate_alias_config(config):
    """Keep 1.0's alias dictionaries when adopting 4.16's template_list editor."""
    previous = config.get("instance_aliases")
    if not isinstance(previous, Mapping):
        return False
    config["instance_aliases"] = [
        {"__template_key": "instance", "alias": str(alias), "identifier": str(identifier)}
        for alias, identifier in previous.items()
    ]
    return True


def plugin_logger(plugin, fallback):
    """Per-plugin logger was added after 4.16; older Star only exposes context."""
    return getattr(plugin, "logger", None) or fallback


def register_owned_tools(context, tools, module_path):
    context.add_llm_tools(*tools)
    # Older Context.add_llm_tools() records the package path instead of main's module.
    # Core tool activation/cleanup uses the exact plugin module path.
    for tool in tools:
        tool.handler_module_path = module_path


async def render_resource_card(plugin, template, data, origin):
    renderer = plugin.html_render
    parameters = inspect.signature(renderer).parameters
    accepts_kwargs = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values())
    candidates = {
        "return_url": False,
        "options": {"type": "png", "full_page": True},
        "umo": origin,
    }
    kwargs = {
        key: value for key, value in candidates.items() if key in parameters or accepts_kwargs
    }
    return await renderer(template, data, **kwargs)
