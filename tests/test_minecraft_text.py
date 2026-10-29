import json

import pytest

from minekuai.errors import MinekuaiError
from minekuai.minecraft_text import COLORS, display_text, server_row
from minekuai.models import Result
from minekuai.rendering import LocalCards


def test_screenshot_title_uses_minecraft_palette_instead_of_literal_codes():
    text, runs = display_text("§0来§1制§2造§3一§4点§5恐§6慌§7吧")
    assert text == "来制造一点恐慌吧"
    assert [r["color"] for r in runs] == [COLORS[code] for code in "01234567"]


@pytest.mark.parametrize(
    "value", ["§#12abCD服务器", "&#12abCD服务器", "§x§1§2§a§b§c§d服务器", "&x&1&2&a&b&c&d服务器"]
)
def test_hex_colors_are_consumed_as_a_single_color(value):
    assert display_text(value) == ("服务器", [{"text": "服务器", "color": "#12ABCD"}])


def test_reset_and_color_transitions_do_not_leak_styles():
    text, runs = display_text("&A&L粗体§o斜体§n下划线§m删除线§c红色§r正常§z原样")
    assert text == "粗体斜体下划线删除线红色正常§z原样"
    assert runs[0]["color"] == "#55FF55" and runs[0]["bold"]
    assert runs[3]["italic"] and runs[3]["underlined"] and runs[3]["strikethrough"]
    assert runs[4] == {"text": "红色", "color": "#FF5555"}
    assert runs[5] == {"text": "正常§z原样"}


def test_escaped_motd_keeps_chinese_and_line_breaks():
    text, runs = display_text(r"\u00A7a欢迎\n第二行" + "\r\n第三行")
    assert text == "欢迎\n第二行\n第三行"
    assert all(run["color"] == "#55FF55" for run in runs)
    assert display_text("正常 <服务器> &q") == ("正常 <服务器> &q", [{"text": "正常 <服务器> &q"}])


def test_json_text_components_inherit_style_and_ignore_interactive_payloads():
    value = {
        "text": "欢迎",
        "color": "gold",
        "bold": True,
        "extra": [
            {"text": "\n生存", "bold": False},
            {"text": "服", "color": "#abcdef", "italic": True},
        ],
        "clickEvent": {"action": "run_command", "value": "/secret"},
    }
    text, runs = display_text(json.dumps(value, ensure_ascii=False))
    assert text == "欢迎\n生存服"
    assert runs[0]["bold"]
    assert runs[1]["bold"] is False and runs[1]["color"] == "#FFAA00"
    assert runs[2]["color"] == "#ABCDEF" and runs[2]["italic"]
    assert "/secret" not in str(runs)
    array_text, array_runs = display_text([{"text": "父", "color": "green"}, {"text": "子"}])
    assert array_text == "父子" and array_runs[0]["color"] == "#55FF55"


def test_formatting_does_not_consume_visible_text_limit_and_deep_inputs_are_bounded():
    text, _ = display_text("§a甲§b乙§c丙", 2)
    assert text == "甲乙…"
    nested = {"text": "end"}
    for _ in range(30):
        nested = {"extra": [nested]}
    assert display_text(nested)[0] == "…"


def test_private_card_fields_redact_secrets_even_when_components_split_the_value():
    row = server_row(
        {"name": "§a生存服", "description": {"text": "mkc_", "extra": [{"text": "never_show_me"}]}}
    )
    assert "mkc_" not in json.dumps(row)
    assert row["description"] == "[已隐藏]"


async def test_instance_list_and_status_show_description_and_plain_fallback(bundle, admin):
    app, backend, *_ = bundle
    backend.server_name = "§0来§1制§2造§3一§4点§5恐§6慌§7吧"
    backend.server_description = "§e欢迎来到服务器\\n§b第二行描述"
    for action in ("instance_list", "instance_status"):
        kwargs = {} if action == "instance_list" else {"identifier": "ab12cd34"}
        _, result = await app.execute(admin, action, **kwargs)
        row = result.rows[0]
        assert row["title"] == "来制造一点恐慌吧"
        assert row["description"] == "欢迎来到服务器\n第二行描述"
        assert "仅此密钥可访问" not in result.text() and "§" not in result.text()
        assert row["description_runs"][0]["color"] == "#FFFF55"
        if action == "instance_status":
            assert "CPU：7.2" in row["meta"] and "内存：100.0 MiB" in row["meta"]


async def test_missing_and_explicitly_cleared_descriptions_are_honest(bundle, admin):
    app, backend, *_ = bundle
    backend.server_description = "列表旧描述"
    backend.server_details = {"description": ""}
    _, result = await app.execute(admin, "instance_status", identifier="ab12cd34")
    assert result.rows[0]["description"] == "未提供服务器描述"
    assert "列表旧描述" not in result.text()


def test_local_card_contains_real_palette_and_multiline_description(tmp_path):
    from PIL import Image

    cards = LocalCards(tmp_path)
    row = server_row(
        {
            "name": "§c红色§a绿色§f白色",
            "description": "§b§l欢迎来到服务器\n§6§o第二行\n§e§n下划线 §m删除线",
        }
    )
    try:
        path = cards.render(Result("我的实例", [row], private=True, operation="list"))
    except MinekuaiError:
        pytest.skip("No local CJK font; runtime falls back to text")
    with Image.open(path) as card:
        palette = dict((color, count) for count, color in card.getcolors(card.width * card.height))
        for color in [(255, 85, 85), (85, 255, 85), (85, 255, 255), (255, 255, 255)]:
            assert palette[color] > 10
        assert card.width == 900 and card.height > 350
