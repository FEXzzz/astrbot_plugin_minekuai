import asyncio

import httpx
import pytest

from minekuai.errors import MinekuaiError
from minekuai.http import ApiClient
from minekuai.settings import Settings


async def test_public_and_panel_headers_never_mix(bundle, admin):
    app, backend, *_ = bundle
    await app.execute(admin, "search", query="jei")
    await app.execute(admin, "instance_list")
    for request in backend.calls:
        if request.url.path.startswith("/panel/public"):
            assert "Authorization" not in request.headers
        else:
            assert request.headers["Authorization"] == "Bearer mkc_test_key_never_real"


async def test_get_retries_but_post_timeout_never_retries():
    calls = []

    def handle(request):
        calls.append(request)
        if request.method == "POST":
            raise httpx.ReadTimeout("simulated", request=request)
        return httpx.Response(502 if len(calls) < 3 else 200, json={"ok": True})

    async def no_sleep(_):
        pass

    api = ApiClient(Settings({}), transport=httpx.MockTransport(handle), sleep=no_sleep)
    try:
        assert await api.request("GET", "/mc-mods") == {"ok": True}
        assert len(calls) == 3
        with pytest.raises(MinekuaiError) as caught:
            await api.request("POST", "/mc-mods", body={})
        assert caught.value.uncertain
        assert len(calls) == 4
    finally:
        await api.close()


async def test_identical_gets_share_one_request():
    count = 0

    async def handle(request):
        nonlocal count
        count += 1
        await asyncio.sleep(0.01)
        return httpx.Response(200, json={"items": []})

    api = ApiClient(Settings({}), transport=httpx.MockTransport(handle))
    try:
        results = await asyncio.gather(
            *(api.request("GET", "/mc-mods", params={"q": "jei"}, ttl=300) for _ in range(8))
        )
        results[0]["items"].append("mutation")
        assert count == 1
        assert results[1]["items"] == []
    finally:
        await api.close()


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422, 429])
async def test_status_errors_are_safe(status):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(
            status, json={"error": "bad mkc_secret_exposure"}, headers={"Retry-After": "30"}
        )

    api = ApiClient(Settings({}), transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(MinekuaiError) as caught:
            await api.request("GET", "/mc-mods")
        assert caught.value.status == status
        assert "mkc_secret" not in str(caught.value)
        assert len(calls) == 1
        if status == 429:
            with pytest.raises(MinekuaiError):
                await api.request("GET", "/mc-mods")
            assert len(calls) == 1
    finally:
        await api.close()


async def test_redirect_is_not_followed_and_file_limit_is_enforced():
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.path.endswith("large"):
            return httpx.Response(200, content=b"x" * (1024 * 1024 + 1))
        return httpx.Response(302, headers={"Location": "https://evil.invalid/collect"})

    api = ApiClient(
        Settings({"instance_api_key": "mkc_test"}),
        panel=True,
        transport=httpx.MockTransport(handle),
    )
    try:
        with pytest.raises(MinekuaiError):
            await api.request("GET", "/servers")
        assert len(calls) == 1
        with pytest.raises(MinekuaiError, match="1 MB"):
            await api.request("GET", "/large", text=True)
    finally:
        await api.close()


async def test_non_json_get_is_reported_and_empty_write_is_uncertain():
    count = 0

    def handle(request):
        nonlocal count
        count += 1
        return httpx.Response(200, text="<html>not JSON</html>")

    async def no_sleep(_):
        pass

    api = ApiClient(Settings({}), transport=httpx.MockTransport(handle), sleep=no_sleep)
    try:
        with pytest.raises(MinekuaiError, match="非 JSON"):
            await api.request("GET", "/mc-mods")
        assert count == 3
        with pytest.raises(MinekuaiError) as caught:
            await api.request("POST", "/mc-mods")
        assert caught.value.uncertain and count == 4
    finally:
        await api.close()


async def test_cache_identity_is_bound_to_the_key_used_for_the_request():
    config = {"instance_api_key": "mkc_first"}
    headers = []
    entered, release = asyncio.Event(), asyncio.Event()

    async def handle(request):
        headers.append(request.headers["Authorization"])
        if len(headers) == 1:
            entered.set()
            await release.wait()
        return httpx.Response(200, json={"account": request.headers["Authorization"]})

    api = ApiClient(Settings(config), panel=True, transport=httpx.MockTransport(handle))
    try:
        first = asyncio.create_task(api.request("GET", "/servers", ttl=30))
        await entered.wait()
        config["instance_api_key"] = "mkc_second"
        release.set()
        assert (await first)["account"] == "Bearer mkc_first"
        second = await api.request("GET", "/servers", ttl=30)
        assert second["account"] == "Bearer mkc_second"
        assert len(headers) == 2
    finally:
        await api.close()
