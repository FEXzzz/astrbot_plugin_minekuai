import asyncio
import re
from dataclasses import replace

import httpx
import pytest

from minekuai.errors import MinekuaiError
from minekuai.permissions import Guard
from minekuai.settings import OPERATIONS, Settings


def code(result):
    return re.search(r"确认 ([A-F0-9]{8})", result.note).group(1)


@pytest.mark.parametrize("operation", OPERATIONS)
def test_permission_scopes_for_every_operation(config, admin, operation):
    guard = Guard(Settings(config))
    group = replace(admin, origin="qq-main:GroupMessage:123", group_id="123", is_private=False)
    for scope in ["disabled", "private", "group", "both"]:
        entry = config["operation_permissions"][operation]
        entry.update(scope=scope, allowed_groups=["123"])
        for actor, allowed in [
            (admin, scope in {"private", "both"}),
            (group, scope in {"group", "both"}),
        ]:
            if allowed:
                guard.check(actor, operation)
            else:
                with pytest.raises(MinekuaiError):
                    guard.check(actor, operation)
        with pytest.raises(MinekuaiError):
            guard.check(replace(group, is_admin=False), operation)
        entry["allowed_groups"] = []
        with pytest.raises(MinekuaiError):
            guard.check(group, operation)


async def test_disabled_instance_module_does_not_break_resources(bundle, admin):
    app, _, config, *_ = bundle
    config["instance_enabled"] = False
    config["instance_api_key"] = ""
    await app.execute(admin, "search", query="jei")
    with pytest.raises(MinekuaiError):
        await app.execute(admin, "instance_list")


async def test_confirmation_is_bound_to_actor_session_key_and_expiry(bundle, admin):
    app, backend, config, clock, _ = bundle
    _, preview = await app.execute(
        admin, "instance_prepare", identifier="ab12cd34", operation="start"
    )
    token = code(preview)
    for changed in [
        replace(admin, user_id="other"),
        replace(admin, origin="different"),
        replace(admin, platform_id="qq-other"),
    ]:
        with pytest.raises(MinekuaiError):
            await app.execute(changed, "instance_confirm", code=token)
    assert not any(r.method == "POST" for r in backend.calls)
    clock.now += 61
    with pytest.raises(MinekuaiError):
        await app.execute(admin, "instance_confirm", code=token)
    _, preview = await app.execute(
        admin, "instance_prepare", identifier="ab12cd34", operation="start"
    )
    config["instance_api_key"] = "mkc_rotated"
    with pytest.raises(MinekuaiError, match="密钥已变化"):
        await app.execute(admin, "instance_confirm", code=code(preview))


async def test_duplicate_confirmation_writes_once(bundle, admin):
    app, backend, *_ = bundle
    _, preview = await app.execute(
        admin, "instance_prepare", identifier="ab12cd34", operation="start"
    )
    results = await asyncio.gather(
        *(app.execute(admin, "instance_confirm", code=code(preview)) for _ in range(2)),
        return_exceptions=True,
    )
    assert sum(isinstance(r, MinekuaiError) for r in results) == 1
    assert sum(r.method == "POST" for r in backend.calls) == 1


async def test_permission_revocation_blocks_confirmation_and_cached_display(bundle, admin):
    app, backend, config, *_ = bundle
    result_id, _ = await app.execute(admin, "instance_status", identifier="ab12cd34")
    config["operation_permissions"]["status"]["scope"] = "disabled"
    with pytest.raises(MinekuaiError):
        app.get_result(admin, result_id)
    _, preview = await app.execute(
        admin, "instance_prepare", identifier="ab12cd34", operation="stop"
    )
    config["operation_permissions"]["stop"]["scope"] = "disabled"
    with pytest.raises(MinekuaiError):
        await app.execute(admin, "instance_confirm", code=code(preview))
    assert not any(r.method == "POST" for r in backend.calls)


async def test_key_rotation_invalidates_cached_results(bundle, admin):
    app, _, config, *_ = bundle
    result_id, _ = await app.execute(admin, "instance_list")
    config["instance_api_key"] = "mkc_different_account"
    with pytest.raises(MinekuaiError, match="密钥已变化"):
        app.get_result(admin, result_id)


async def test_command_requires_running_and_does_not_claim_output(bundle, admin):
    app, backend, *_ = bundle
    backend.state = "offline"
    with pytest.raises(MinekuaiError, match="running"):
        await app.execute(
            admin,
            "instance_prepare",
            identifier="ab12cd34",
            operation="command",
            payload={"command": "say hi"},
        )
    backend.state = "running"
    _, preview = await app.execute(
        admin,
        "instance_prepare",
        identifier="ab12cd34",
        operation="command",
        payload={"command": "say hi"},
    )
    _, result = await app.execute(admin, "instance_confirm", code=code(preview))
    assert "已提交" in result.note and "不提供" in result.note


async def test_variable_names_are_live_validated_and_values_rechecked(bundle, admin):
    app, backend, *_ = bundle
    with pytest.raises(MinekuaiError, match="env_variable"):
        await app.execute(
            admin,
            "instance_prepare",
            identifier="ab12cd34",
            operation="startup_write",
            payload={"key": "UNKNOWN", "value": "1"},
        )
    _, preview = await app.execute(
        admin,
        "instance_prepare",
        identifier="ab12cd34",
        operation="startup_write",
        payload={"key": "MAX_PLAYERS", "value": "50"},
    )
    _, result = await app.execute(admin, "instance_confirm", code=code(preview))
    assert backend.variable == "50" and "值一致" in result.note
    _, startup = await app.execute(admin, "instance_startup", identifier="ab12cd34")
    assert "super-secret" not in startup.text()


async def test_game_and_modpack_share_persisted_cooldown(bundle, admin):
    app, backend, _, clock, saved = bundle
    with pytest.raises(MinekuaiError, match="允许"):
        await app.execute(
            admin,
            "instance_prepare",
            identifier="ab12cd34",
            operation="game_switch",
            payload={"game_type": "not-allowed"},
        )
    _, preview = await app.execute(
        admin,
        "instance_prepare",
        identifier="ab12cd34",
        operation="game_switch",
        payload={"game_type": "minecraft"},
    )
    assert "删除实例全部文件" in preview.note
    await app.execute(admin, "instance_confirm", code=code(preview))
    assert saved and next(iter(saved[-1].values())) == clock.now + 60
    with pytest.raises(MinekuaiError, match="冷却"):
        await app.execute(
            admin,
            "instance_prepare",
            identifier="ab12cd34",
            operation="modpack_switch",
            payload={"modpack_id": 1},
        )
    clock.now += 61
    await app.execute(
        admin,
        "instance_prepare",
        identifier="ab12cd34",
        operation="modpack_switch",
        payload={"file_name": "pack.zip"},
    )
    assert sum(r.method == "POST" for r in backend.calls) == 1


async def test_write_timeout_consumes_code_and_marks_switch_uncertain(bundle, admin):
    app, backend, _, _, saved = bundle
    _, preview = await app.execute(
        admin,
        "instance_prepare",
        identifier="ab12cd34",
        operation="modpack_switch",
        payload={"modpack_id": 1},
    )
    backend.write_failure = httpx.ReadTimeout
    with pytest.raises(MinekuaiError) as caught:
        await app.execute(admin, "instance_confirm", code=code(preview))
    assert caught.value.uncertain and saved
    with pytest.raises(MinekuaiError):
        await app.execute(admin, "instance_confirm", code=code(preview))
    assert sum(r.method == "POST" for r in backend.calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"modpack_id": 1, "file_name": "a.zip"},
        {"file_name": "https://example.com/a.zip"},
        {"file_name": "../pack.zip"},
        {"modpack_id": True},
    ],
)
async def test_modpack_invalid_identifiers_never_write(bundle, admin, payload):
    app, backend, *_ = bundle
    with pytest.raises(MinekuaiError):
        await app.execute(
            admin,
            "instance_prepare",
            identifier="ab12cd34",
            operation="modpack_switch",
            payload=payload,
        )
    assert not any(r.method == "POST" for r in backend.calls)


async def test_file_is_text_paginated_redacted_and_may_be_authorized_in_group(bundle, admin):
    app, backend, config, *_ = bundle
    backend.file = "rcon.password=do-not-disclose\n" + "a long line\n" * 800
    group = replace(admin, group_id="123", origin="qq-main:GroupMessage:123", is_private=False)
    config["operation_permissions"]["file_read"] = {"scope": "group", "allowed_groups": ["123"]}
    _, result = await app.execute(
        group, "instance_file", identifier="ab12cd34", path="/server.properties"
    )
    assert len(result.rows[0]["description"]) <= 4000
    assert "do-not-disclose" not in result.text()
    assert result.next_request is not None
    assert backend.calls[-1].url.params["file"] == "/server.properties"


async def test_unknown_instance_and_extra_payload_never_write(bundle, admin):
    app, backend, *_ = bundle
    for identifier, payload in [("ffffffff", {}), ("ab12cd34", {"unexpected": True})]:
        with pytest.raises(MinekuaiError):
            await app.execute(
                admin, "instance_prepare", identifier=identifier, operation="start", payload=payload
            )
    assert not any(r.method == "POST" for r in backend.calls)


async def test_restart_requires_observed_transition(bundle, admin):
    app, backend, _, clock, _ = bundle
    app.panel.poll_seconds = 6
    backend.states = ["running"] * 4
    note = await app.panel._poll_power("ab12cd34", "restart")
    assert "尚未确认" in note
    backend.states = ["starting", "running"]
    note = await app.panel._poll_power("ab12cd34", "restart")
    assert "已观察" in note


async def test_confirmation_expiring_while_waiting_for_instance_lock_does_not_write(bundle, admin):
    app, backend, _, clock, _ = bundle
    _, preview = await app.execute(
        admin, "instance_prepare", identifier="ab12cd34", operation="start"
    )
    lock = asyncio.Lock()
    await lock.acquire()
    app.panel.locks["ab12cd34"] = lock
    pending = asyncio.create_task(app.execute(admin, "instance_confirm", code=code(preview)))
    await asyncio.sleep(0)
    clock.now += 61
    lock.release()
    with pytest.raises(MinekuaiError, match="过期"):
        await pending
    assert not any(r.method == "POST" for r in backend.calls)


async def test_variable_204_is_read_back_instead_of_retried(bundle, admin):
    app, backend, *_ = bundle

    def handle(request):
        response = backend(request)
        return httpx.Response(204) if request.method == "PUT" else response

    await app.panel.api.client.aclose()
    app.panel.api.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    _, preview = await app.execute(
        admin,
        "instance_prepare",
        identifier="ab12cd34",
        operation="startup_write",
        payload={"key": "MAX_PLAYERS", "value": "42"},
    )
    _, result = await app.execute(admin, "instance_confirm", code=code(preview))
    assert "值一致" in result.note
    assert sum(r.method == "PUT" for r in backend.calls) == 1


async def test_cancelled_switch_keeps_cooldown_and_consumes_nonce(bundle, admin):
    app, backend, _, _, saved = bundle
    entered, never = asyncio.Event(), asyncio.Event()

    async def handle(request):
        if request.method == "POST":
            backend.calls.append(request)
            entered.set()
            await never.wait()
        return backend(request)

    await app.panel.api.client.aclose()
    app.panel.api.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    _, preview = await app.execute(
        admin,
        "instance_prepare",
        identifier="ab12cd34",
        operation="modpack_switch",
        payload={"modpack_id": 1},
    )
    task = asyncio.create_task(app.execute(admin, "instance_confirm", code=code(preview)))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert saved
    with pytest.raises(MinekuaiError):
        await app.execute(admin, "instance_confirm", code=code(preview))
