"""Synthetic panel fixtures: never connect to or mutate a real instance."""

import httpx
import pytest

from minekuai.app import App
from minekuai.http import ApiClient
from minekuai.models import Actor
from minekuai.panel import PanelService
from minekuai.resources import ResourceService
from minekuai.settings import OPERATIONS, Settings


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds


class Backend:
    def __init__(self):
        self.calls = []
        self.state = "running"
        self.states = []
        self.file = "max-players=20\nrcon.password=do-not-disclose\n"
        self.variable = "20"
        self.server_name = "测试生存服"
        self.server_description = ""
        self.server_details = {}
        self.write_failure = None
        self.detail = {
            "slug": "jei",
            "title": "Just Enough Items",
            "title_zh": "应有尽有",
            "external_url": "https://www.curseforge.com/minecraft/mc-mods/jei",
            "allow_mod_distribution": True,
        }
        self.versions = [
            {
                "id": "beta-new",
                "name": "新版 Beta",
                "version_type": "beta",
                "date_published": "2026-10-25T12:00:00Z",
                "game_versions": ["1.20.1"],
                "loaders": ["forge"],
                "files": [
                    {
                        "url": "https://cdn.modrinth.com/beta.jar",
                        "filename": "beta.jar",
                        "primary": True,
                    }
                ],
            },
            {
                "id": "release",
                "name": "稳定版",
                "version_type": "release",
                "date_published": "2026-10-24T12:00:00Z",
                "game_versions": ["1.20.1"],
                "loaders": ["forge"],
                "files": [
                    {
                        "url": "https://cdn.modrinth.com/release.jar",
                        "filename": "release.jar",
                        "primary": True,
                    }
                ],
            },
            {
                "id": "fabric",
                "name": "Fabric 版",
                "version_type": "release",
                "date_published": "2026-10-26T12:00:00Z",
                "game_versions": ["1.21.1"],
                "loaders": ["fabric"],
                "files": [{"url": "https://cdn.modrinth.com/fabric.jar", "filename": "fabric.jar"}],
            },
        ]
        self.resource_items = [
            {
                "slug": "jei",
                "title": "JEI",
                "title_zh": "应有尽有",
                "loaders": ["forge"],
                "game_versions": ["1.20.1"],
            }
        ]

    def __call__(self, request):
        import json

        self.calls.append(request)
        path = request.url.path
        if path.startswith("/panel/client-api"):
            suffix = path.removeprefix("/panel/client-api")
            if request.method != "GET":
                if self.write_failure:
                    raise self.write_failure("simulated network failure", request=request)
                if suffix.endswith("/startup/variable"):
                    self.variable = json.loads(request.content)["value"]
                    return httpx.Response(
                        200,
                        json={
                            "data": {
                                "attributes": {
                                    "env_variable": "MAX_PLAYERS",
                                    "server_value": self.variable,
                                }
                            }
                        },
                    )
                return httpx.Response(200, json={"success": True})
            if suffix == "/servers":
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "attributes": {
                                    "identifier": "ab12cd34",
                                    "name": self.server_name,
                                    "description": self.server_description,
                                }
                            }
                        ],
                        "meta": {"pagination": {"total_pages": 1}},
                    },
                )
            if suffix == "/servers/ab12cd34":
                state = self.states.pop(0) if self.states else self.state
                return httpx.Response(
                    200,
                    json={
                        "attributes": {
                            "name": self.server_name,
                            "description": self.server_description,
                            **self.server_details,
                        },
                        "stats": {
                            "attributes": {
                                "current_state": state,
                                "resources": {"cpu_absolute": 7.2, "memory_bytes": 104857600},
                            }
                        },
                    },
                )
            if suffix.endswith("/startup"):
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "attributes": {
                                    "env_variable": "MAX_PLAYERS",
                                    "server_value": self.variable,
                                }
                            },
                            {
                                "attributes": {
                                    "env_variable": "RCON_PASSWORD",
                                    "server_value": "super-secret",
                                }
                            },
                        ],
                        "meta": {"startup_command": "java -jar server.jar"},
                    },
                )
            if suffix.endswith("/allowed-games"):
                return httpx.Response(
                    200, json={"games": [{"game_type": "minecraft", "name": "Minecraft"}]}
                )
            if suffix.endswith("/files/contents"):
                return httpx.Response(200, text=self.file)
            return httpx.Response(404, json={"error": "not found"})
        suffix = path.removeprefix("/panel/public")
        if suffix == "/mc-search":
            from minekuai.resources import AGGREGATE_TYPES

            return httpx.Response(
                200,
                json={
                    "groups": [
                        {"type": key, "items": self.resource_items} for key in AGGREGATE_TYPES
                    ]
                },
            )
        if suffix.endswith("/versions"):
            return httpx.Response(200, json=self.versions)
        if "/detail/" in suffix:
            return httpx.Response(200, json=self.detail)
        if suffix.endswith("/facets"):
            return httpx.Response(200, json={"loaders": [{"value": "fabric", "count": 20}]})
        if suffix.endswith("/categories"):
            return httpx.Response(
                200, json=[{"name": "utility", "project_type": "mod", "header": "categories"}]
            )
        return httpx.Response(
            200, json={"total": 100, "limit": 0, "offset": 0, "items": self.resource_items}
        )


@pytest.fixture
def config():
    return {
        "instance_enabled": True,
        "instance_api_key": "mkc_test_key_never_real",
        "operation_permissions": {
            key: {"scope": "private", "allowed_groups": []} for key in OPERATIONS
        },
    }


@pytest.fixture
def admin():
    return Actor("qq-main", "qq-main:FriendMessage:10001", "10001", is_admin=True)


@pytest.fixture
async def bundle(config):
    backend = Backend()
    clock = Clock()
    settings = Settings(config)

    async def no_sleep(_):
        pass

    public = ApiClient(settings, transport=httpx.MockTransport(backend), sleep=no_sleep)
    panel_api = ApiClient(
        settings, panel=True, transport=httpx.MockTransport(backend), sleep=no_sleep
    )
    saved = []

    async def save(value):
        saved.append(dict(value))

    panel = PanelService(
        panel_api, settings, clock=clock, sleep=clock.sleep, poll_seconds=0, save_cooldowns=save
    )
    app = App(ResourceService(public, settings), panel)
    yield app, backend, config, clock, saved
    await app.close()
