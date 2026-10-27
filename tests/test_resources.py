import pytest

from minekuai.errors import MinekuaiError
from minekuai.resources import GROUPS, normalize_version


async def test_aggregate_keeps_nine_source_identities(bundle, admin):
    app, *_ = bundle
    result_id, result = await app.execute(admin, "search", query="jei")
    assert len(result.rows) == 9
    assert set(k.split(":")[0] for k in result.resource_keys) == set(GROUPS)
    assert len(set(result.resource_keys)) == 9
    assert app.get_result(admin, result_id).next_request is None


async def test_filtered_search_keeps_relevance_and_encodes_arrays(bundle, admin):
    app, backend, *_ = bundle
    _, result = await app.execute(
        admin,
        "search",
        query="jei",
        kind="mod",
        filters={"loader": ["fabric", "forge"], "game_version": ["1.20.1"]},
    )
    request = backend.calls[-1]
    assert request.url.params.get_list("loader[]") == ["fabric", "forge"]
    assert request.url.params.get_list("game_version[]") == ["1.20.1"]
    assert "order" not in request.url.params
    assert result.rows[0]["title"] == "应有尽有"
    await app.execute(admin, "next")
    assert backend.calls[-1].url.params["offset"] == "5"


async def test_aggregate_rejects_ignored_filters(bundle, admin):
    app, *_ = bundle
    with pytest.raises(MinekuaiError, match="指定类型"):
        await app.execute(admin, "search", query="jei", filters={"loader": "forge"})


async def test_download_matches_loader_and_defaults_to_release(bundle, admin):
    app, *_ = bundle
    _, result = await app.execute(
        admin, "download", resource_key="mr_mod:jei", game_versions=["1.20.1"], loaders=["forge"]
    )
    assert result.links[0]["url"].endswith("release.jar")
    _, pre = await app.execute(
        admin,
        "download",
        resource_key="mr_mod:jei",
        game_versions=["1.20.1"],
        loaders=["forge"],
        allow_prerelease=True,
    )
    assert pre.links[0]["url"].endswith("beta.jar")
    with pytest.raises(MinekuaiError, match="没有符合"):
        await app.execute(
            admin,
            "download",
            resource_key="mr_mod:jei",
            game_versions=["1.20.1"],
            loaders=["fabric"],
        )


async def test_explicit_version_and_distribution_restriction(bundle, admin):
    app, backend, *_ = bundle
    _, exact = await app.execute(
        admin, "download", resource_key="mr_mod:jei", version_id="beta-new"
    )
    assert exact.links[0]["url"].endswith("beta.jar")
    backend.detail["allow_mod_distribution"] = False
    app.resources.api.clear()
    backend.calls.clear()
    _, result = await app.execute(admin, "download", resource_key="cf_mod:jei")
    assert result.links[0]["label"] == "项目页"
    assert not any(r.url.path.endswith("versions") for r in backend.calls)


def test_curseforge_and_flat_plugin_versions():
    cf = normalize_version(
        GROUPS["cf_mod"],
        {
            "id": 1,
            "display_name": "CF",
            "file_name": "cf.jar",
            "file_date": "2026-10-01T00:00:00Z",
            "release_type": "release",
            "download_url": "https://edge.forgecdn.net/cf.jar",
            "game_versions": ["1.20.1", "NeoForge", "Client", "Server"],
        },
    )
    assert cf["game_versions"] == ["1.20.1"]
    assert cf["loaders"] == ["neoforge"]
    plugin = normalize_version(
        GROUPS["spigot_plugin"],
        {
            "id": "2",
            "name": "Plugin",
            "download_url": "https://api.spiget.org/v2/resources/1/download",
        },
    )
    assert plugin["release"] == "unknown"
    assert plugin["game_versions"] == []
    assert plugin["url"].endswith("download")


async def test_curseforge_loader_filters_locally_and_only_sends_supported_params(bundle, admin):
    app, backend, *_ = bundle
    backend.versions = [
        {"id": 1, "display_name": "NeoForge", "game_versions": ["NeoForge", "1.20.1"]},
        {"id": 2, "display_name": "Forge", "game_versions": ["Forge", "1.20.1"]},
    ]
    _, result = await app.execute(
        admin, "versions", resource_key="cf_mod:jei", game_versions=["1.20.1"], loaders=["neoforge"]
    )
    assert len(result.rows) == 1 and result.rows[0]["title"] == "NeoForge"
    assert "loader[]" not in backend.calls[-1].url.params


async def test_plugin_unknown_compatibility_is_not_treated_as_match(bundle, admin):
    app, backend, *_ = bundle
    backend.versions = [{"id": "1", "name": "Unknown", "download_url": "https://example.com/a.jar"}]
    with pytest.raises(MinekuaiError):
        await app.execute(admin, "download", resource_key="spigot_plugin:demo-1", loaders=["paper"])


async def test_no_nonexistent_category_endpoints(bundle, admin):
    app, backend, *_ = bundle
    await app.execute(admin, "filters", kind="plugin", source="spigot")
    assert not any(r.url.path.endswith("categories") for r in backend.calls)
    await app.execute(admin, "filters", kind="mod", source="mr")
    assert backend.calls[-1].url.path.endswith("categories")


async def test_resource_numbers_do_not_cross_users_or_get_replaced_by_instance_pages(bundle, admin):
    from dataclasses import replace

    app, *_ = bundle
    await app.execute(admin, "search", query="jei")
    await app.execute(admin, "instance_list")
    _, result = await app.execute(admin, "detail", resource_key="1")
    assert result.rows[0]["key"] == "mr_mod:jei"
    with pytest.raises(MinekuaiError):
        await app.execute(replace(admin, user_id="other"), "detail", resource_key="1")


async def test_last_page_does_not_repeat_previous_next_request(bundle, admin):
    app, backend, *_ = bundle
    await app.execute(admin, "search", query="jei", kind="mod")
    backend.versions = backend.versions[:1]
    _, result = await app.execute(admin, "versions", resource_key="mr_mod:jei")
    assert result.next_request is None
    with pytest.raises(MinekuaiError):
        await app.execute(admin, "next")
