import re
from dataclasses import replace

import pytest

from minekuai.errors import MinekuaiError
from minekuai.permissions import Guard
from minekuai.platforms import text_chunks
from minekuai.settings import Settings


@pytest.mark.parametrize(
    "platform,limit",
    [("aiocqhttp", 4000), ("qq_official", 1500), ("qq_official_webhook", 1500), ("discord", 2000)],
)
def test_long_text_and_supplementary_characters_arrive_without_truncation(platform, limit):
    text = "配置🙂" * 1800 + "\n" + "长行" * 2200 + "\n结束\n"
    chunks = text_chunks(text, platform)
    assert "".join(chunks) == text
    assert len(chunks) > 1
    assert all(0 < len(chunk.encode("utf-16-le")) // 2 <= limit for chunk in chunks)
    assert text_chunks("", platform) == []


@pytest.mark.parametrize("platform", ["qq_official", "qq_official_webhook", "discord"])
def test_copyable_urls_stay_on_one_line_when_they_fit(platform):
    link = "https://cdn.modrinth.com/data/project/versions/version/example.jar"
    chunks = text_chunks("版本详情\n" * 140 + link + "\n", platform)
    assert any(link in chunk for chunk in chunks)
    assert "".join(chunks) == "版本详情\n" * 140 + link + "\n"


@pytest.mark.parametrize(
    "platform,group",
    [
        ("qq_official", "OPENID_A"),
        ("qq_official_webhook", "OPENID_B"),
        ("discord", "123456789012345678"),
    ],
)
async def test_channel_permissions_and_private_results_stay_bound_to_platform(
    bundle, admin, platform, group
):
    app, backend, config, *_ = bundle
    actor = replace(
        admin,
        platform_id=platform + "-bot",
        origin=f"{platform}-bot:GroupMessage:{group}",
        group_id=group,
        is_private=False,
    )
    for operation in ("status", "command"):
        config["operation_permissions"][operation] = {
            "scope": "group",
            "allowed_groups": [f"{actor.platform_id}:{group}"],
        }
    guard = Guard(Settings(config))
    guard.check(actor, "status")
    for other in [
        replace(actor, platform_id="other-bot"),
        replace(actor, group_id="guild-id"),
        replace(actor, is_admin=False),
    ]:
        with pytest.raises(MinekuaiError):
            guard.check(other, "status")
    result_id, _ = await app.execute(actor, "instance_status", identifier="ab12cd34")
    with pytest.raises(MinekuaiError):
        app.get_result(replace(actor, origin="another-channel"), result_id)
    _, preview = await app.execute(
        actor,
        "instance_prepare",
        identifier="ab12cd34",
        operation="command",
        payload={"command": "say test"},
    )
    token = re.search(r"确认 ([A-F0-9]{8})", preview.note).group(1)
    with pytest.raises(MinekuaiError):
        await app.execute(replace(actor, platform_id="other-bot"), "instance_confirm", code=token)
    assert not any(r.method == "POST" for r in backend.calls)
    await app.execute(actor, "instance_confirm", code=token)
    assert sum(r.method == "POST" for r in backend.calls) == 1
