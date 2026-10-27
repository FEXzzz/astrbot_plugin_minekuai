import json
from pathlib import Path

import jsonschema
import pytest
from jinja2 import Environment

from minekuai.commands import parse
from minekuai.errors import MinekuaiError, redact
from minekuai.models import Result
from minekuai.rendering import LocalCards
from minekuai.settings import OPERATIONS
from minekuai.tool_specs import specs

ROOT = Path(__file__).resolve().parents[1]


def test_command_quoting_and_console_payload_are_preserved():
    action, args = parse("搜索", '"Just Enough Items" 类型=模组 加载器=fabric,forge 版本=1.20.1')
    assert action == "search" and args["query"] == "Just Enough Items"
    assert args["filters"]["loader"] == "fabric,forge"
    action, args = parse("实例", '命令 ab12cd34 tellraw @a {"text":"hello  world"}')
    assert args["payload"]["command"] == 'tellraw @a {"text":"hello  world"}'
    _, args = parse("实例", '设置变量 ab12cd34 MOTD "欢迎 来到服务器"')
    assert args["payload"]["value"] == "欢迎 来到服务器"


@pytest.mark.parametrize(
    "command,text",
    [
        ("搜索", "jei 未知=1"),
        ("下载", "mr_mod:jei 预览=不知道"),
        ("实例", "切换整合包 ab12cd34 https://example.com/pack.zip"),
        ("实例", "启动 ab12cd34 extra"),
        ("详情", "mr_mod:jei extra"),
        ("搜索", '"unclosed'),
    ],
)
def test_invalid_commands_are_explained(command, text):
    with pytest.raises(MinekuaiError):
        parse(command, text)


def test_schemas_are_explicit_and_never_expose_confirm_or_credentials():
    tools = specs()
    assert len({t.name for t in tools}) == len(tools)
    assert len(tools) == 12
    for tool in tools:
        jsonschema.Draft202012Validator.check_schema(tool.parameters)
        assert tool.parameters["additionalProperties"] is False
        assert tool.action not in {"instance_confirm", "instance_cancel"}
        assert "instance_api_key" not in json.dumps(tool.parameters)
    config = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    assert config["instance_api_key"]["secret"] is True
    assert set(config["operation_permissions"]["items"]) == set(OPERATIONS)


def test_template_escapes_every_untrusted_text_field():
    template = Environment(autoescape=False).from_string(
        (ROOT / "templates/card.html").read_text(encoding="utf-8")
    )
    rendered = template.render(
        title="<script>evil()</script>",
        rows=[
            {
                "title": "<img src=x onerror=bad>",
                "description": "<script>bad</script>",
                "subtitle": "test",
                "meta": "<b>meta</b>",
            }
        ],
        note="<iframe>",
    )
    assert "<script>" not in rendered and "<iframe>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_local_card_is_900px_and_does_not_need_a_network_renderer(tmp_path):
    from PIL import Image

    cards = LocalCards(tmp_path)
    try:
        path = cards.render(
            Result(
                "实例状态",
                [
                    {
                        "title": "生存服",
                        "subtitle": "ab12cd34 · running",
                        "description": "CPU：未知\n内存：256 MiB\n磁盘：未知",
                    }
                ],
                private=True,
                operation="status",
            )
        )
    except MinekuaiError:
        pytest.skip("No local Chinese font installed; runtime will return text")
    with Image.open(path) as img:
        assert img.width == 900 and 250 < img.height < 1500


def test_redaction_covers_properties_json_and_key_tokens():
    assert "actual-password" not in redact("rcon.password=actual-password")
    assert "secret-value" not in redact('{"api_key": "secret-value"}')
    assert "mkc_real_key" not in redact("Bearer mkc_real_key")


def test_redaction_before_json_serialization_preserves_valid_tool_output():
    from minekuai.errors import redact_data

    original = {"rows": [{"description": 'password="secret-value"\nline two'}], "count": 2}
    encoded = json.dumps(redact_data(original), ensure_ascii=False)
    decoded = json.loads(encoded)
    assert decoded["count"] == 2
    assert "secret-value" not in decoded["rows"][0]["description"]
    assert original["rows"][0]["description"].startswith('password="secret-value"')


def test_file_paths_containing_equal_sign_are_query_values():
    _, args = parse("实例", '读取文件 ab12cd34 "/config=prod.properties" 页=2')
    assert args["path"] == "/config=prod.properties" and args["page"] == 2
