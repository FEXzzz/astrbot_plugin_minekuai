"""Resource registry, source-specific normalization and compatible downloads."""

import html
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit

from .errors import MinekuaiError
from .models import Result
from .settings import Settings


@dataclass(frozen=True)
class Group:
    key: str
    path: str
    label: str
    kind: str
    source: str = "mr"
    categories: bool = True


GROUPS = {
    g.key: g
    for g in [
        Group("mr_mod", "mc-mods", "Modrinth 模组", "mod"),
        Group("cf_mod", "mc-cf-mods", "CurseForge 模组", "mod", "cf"),
        Group("mr_modpack", "mc-modpacks", "Modrinth 整合包", "modpack", categories=False),
        Group("cf_modpack", "mc-cf-modpacks", "CurseForge 整合包", "modpack", "cf"),
        Group("shader", "mc-shaders", "Modrinth 光影", "shader"),
        Group("resourcepack", "mc-resourcepacks", "Modrinth 资源包", "resourcepack"),
        Group("mr_plugin", "mc-plugins/modrinth", "Modrinth 插件", "plugin", categories=False),
        Group("cf_plugin", "mc-plugins/curseforge", "CurseForge 插件", "plugin", "cf", False),
        Group("spigot_plugin", "mc-plugins/spigot", "Spigot 插件", "plugin", "spigot", False),
    ]
}
AGGREGATE_TYPES = {
    "mod": "mr_mod",
    "modpack": "mr_modpack",
    "shader": "shader",
    "resourcepack": "resourcepack",
    "curseforge_mod": "cf_mod",
    "curseforge_modpack": "cf_modpack",
    "modrinth-plugins": "mr_plugin",
    "curseforge-plugins": "cf_plugin",
    "spigot-plugins": "spigot_plugin",
}
KINDS = {
    "模组": "mod",
    "mod": "mod",
    "整合包": "modpack",
    "modpack": "modpack",
    "光影": "shader",
    "光影包": "shader",
    "shader": "shader",
    "资源包": "resourcepack",
    "材质包": "resourcepack",
    "resourcepack": "resourcepack",
    "插件": "plugin",
    "plugin": "plugin",
    "全部": "all",
    "all": "all",
}
SOURCES = {"mr": "mr", "modrinth": "mr", "cf": "cf", "curseforge": "cf", "spigot": "spigot"}
MULTI_FILTERS = {"loader", "game_version", "category", "client_side", "server_side"}
ORDERS = {"source_index", "downloads", "follows", "date_modified", "date_created", "translation_at"}
LOADERS = {
    "fabric",
    "forge",
    "neoforge",
    "quilt",
    "paper",
    "spigot",
    "bukkit",
    "purpur",
    "folia",
    "velocity",
    "waterfall",
    "bungeecord",
    "iris",
    "optifine",
    "canvas",
    "minecraft",
    "vanilla",
    "datapack",
    "liteloader",
    "rift",
}


def plain(value, limit=800):
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]*>", "", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text[:limit] + ("…" if len(text) > limit else "")


def safe_url(value):
    value = str(value or "").strip()
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        return ""
    if any(c in value for c in "\r\n\t"):
        return ""
    return value


def group_for(kind="all", source=""):
    if kind in GROUPS:
        group = GROUPS[kind]
        if source and SOURCES.get(source.lower()) != group.source:
            raise MinekuaiError("资源类型和来源不匹配。")
        return group
    kind = KINDS.get(str(kind).lower())
    if kind is None:
        raise MinekuaiError("未知资源类型，可选：模组、整合包、光影、资源包、插件。")
    if kind == "all":
        if source:
            raise MinekuaiError("指定来源时也需要指定资源类型。")
        return None
    source = SOURCES.get(str(source or "mr").lower())
    for group in GROUPS.values():
        if group.kind == kind and group.source == source:
            return group
    raise MinekuaiError("该资源类型没有这个来源。")


def parse_key(key):
    group_key, separator, slug = str(key).partition(":")
    if not separator or group_key not in GROUPS or not re.fullmatch(r"[a-zA-Z0-9._-]{1,128}", slug):
        raise MinekuaiError("资源标识格式错误，例如 mr_mod:jei 或 cf_mod:jei。")
    return GROUPS[group_key], slug


def values(value):
    if isinstance(value, str):
        return list(dict.fromkeys(v.strip() for v in value.split(",") if v.strip()))
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(dict.fromkeys(v.strip() for v in value if v.strip()))
    raise MinekuaiError("多值筛选请填写字符串数组，或使用逗号分隔。")


def project_url(group, data):
    explicit = safe_url(data.get("external_url"))
    if explicit:
        return explicit
    slug = quote(str(data.get("slug", "")), safe="")
    if group.source == "mr" and slug:
        return f"https://modrinth.com/{group.kind}/{slug}"
    return ""


def normalize_version(group, data):
    tags = [str(v) for v in data.get("game_versions") or []]
    loaders = [str(v).lower() for v in data.get("loaders") or []]
    if group.source == "cf" and group.kind != "plugin":
        loaders = [v.lower() for v in tags if v.lower() in LOADERS]
        tags = [v for v in tags if v.lower() not in LOADERS | {"client", "server"}]
    files = data.get("files") or []
    if not isinstance(files, list):
        files = []
    if files:
        item = next((f for f in files if f.get("primary")), files[0])
        url, filename = item.get("url"), item.get("filename")
    else:
        url = data.get("download_url")
        filename = data.get("filename") or data.get("file_name")
    release = data.get("version_type") or data.get("release_type") or "unknown"
    release = {1: "release", 2: "beta", 3: "alpha"}.get(release, str(release).lower())
    return {
        "id": str(data.get("id", "")),
        "name": plain(
            data.get("name")
            or data.get("display_name")
            or data.get("version_number")
            or filename
            or "未命名版本",
            160,
        ),
        "number": str(data.get("version_number") or ""),
        "published": str(data.get("date_published") or data.get("file_date") or ""),
        "game_versions": tags,
        "loaders": loaders,
        "release": release,
        "url": safe_url(url),
        "filename": plain(filename, 220),
    }


class ResourceService:
    def __init__(self, api, settings: Settings):
        self.api = api
        self.settings = settings

    def _ttl(self, name, default):
        config = self.settings.get("resource_cache_seconds", {})
        try:
            return max(0, min(86400, int(config.get(name, default))))
        except (ValueError, TypeError, AttributeError):
            return default

    def _filters(self, group, filters):
        if not isinstance(filters, dict):
            raise MinekuaiError("filters 必须是对象。")
        params = []
        for key, value in filters.items():
            if key in MULTI_FILTERS:
                if group.source == "cf" and key in {"client_side", "server_side"}:
                    raise MinekuaiError("该来源没有客户端／服务端需求信息，不能使用此筛选。")
                params.extend((key + "[]", v) for v in sorted(values(value)))
            elif key == "status" and value in {"translated", "pending", "failed"}:
                params.append((key, value))
            elif key == "order" and value in ORDERS:
                params.append((key, value))
            elif key == "dir" and value in {"asc", "desc"}:
                params.append((key, value))
            else:
                raise MinekuaiError(f"不支持的筛选或取值：{key}。")
        if self.settings.get("only_translated", False) and "status" not in filters:
            params.append(("status", "translated"))
        return params

    @staticmethod
    def _row(group, item):
        slug = str(item.get("slug", ""))
        key = f"{group.key}:{slug}"
        title = plain(item.get("title_zh") or item.get("title") or slug, 120)
        original = plain(item.get("title"), 140)
        versions = [str(v) for v in item.get("game_versions") or []]
        loaders = [str(v) for v in item.get("loaders") or []]
        url = project_url(group, item)
        return {
            "title": title,
            "subtitle": f"{group.label} · {key}"
            + (f" · {original}" if original and original != title else ""),
            "description": plain(
                item.get("description_zh") or item.get("description_en") or item.get("description"),
                240,
            ),
            "meta": "  ".join(
                p
                for p in [
                    "加载器 " + ", ".join(loaders[:8]) if loaders else "",
                    "游戏版本 " + ", ".join(versions[-6:]) if versions else "",
                    f"下载 {item['downloads']:,}" if isinstance(item.get("downloads"), int) else "",
                ]
                if p
            ),
            "key": key,
            "url": url,
        }

    async def search(self, query="", kind="all", source="", filters=None, page=1, popular=False):
        query = str(query).strip()
        if len(query) > 200:
            raise MinekuaiError("关键词请控制在 200 字以内。")
        page = self._page(page)
        filters = filters or {}
        group = group_for(kind, source)
        if group is None:
            if filters or page != 1 or popular:
                raise MinekuaiError(
                    "高级筛选、热门浏览和分页需要指定类型，例如 类型=模组 来源=mr。"
                )
            if not query:
                raise MinekuaiError("请输入搜索关键词。")
            data = await self.api.request(
                "GET", "/mc-search", params={"q": query, "limit": 1}, ttl=self._ttl("search", 300)
            )
            rows, omitted = [], 0
            for bucket in data.get("groups", []):
                key = AGGREGATE_TYPES.get(bucket.get("type"))
                if key is None:
                    omitted += len(bucket.get("items", []))
                    continue
                for item in bucket.get("items", [])[:1]:
                    rows.append(self._row(GROUPS[key], item))
            note = "全站总览每类最多 1 条。需要更多结果时指定类型和来源。"
            if omitted:
                note += " 部分来源不明的结果已略过，请按明确来源查询。"
            return self._resource_result(f"搜索 · {query}", rows, note)
        params = self._filters(group, filters)
        if popular:
            params = [(k, v) for k, v in params if k not in {"order", "dir"}]
            params += [("order", "downloads"), ("dir", "desc")]
        elif not query and "order" not in filters:
            params += [("order", "downloads")]
        offset = (page - 1) * self.settings.page_size
        params += [("limit", self.settings.page_size), ("offset", offset)]
        if query:
            params.append(("q", query))
        data = await self.api.request(
            "GET", "/" + group.path, params=params, ttl=self._ttl("search", 300)
        )
        items = data.get("items", [])
        rows = [self._row(group, item) for item in items]
        total = int(data.get("total", len(items)))
        result = self._resource_result(
            f"{group.label} · {query or '热门资源'}",
            rows,
            f"第 {page} 页 · 共 {total} 条" + ("\n没有符合条件的资源。" if not rows else ""),
        )
        if items and offset + len(items) < total:
            result.next_request = {
                "action": "search",
                "query": query,
                "kind": group.key,
                "filters": filters,
                "page": page + 1,
                "popular": popular,
            }
            result.note += "\n发送 /麦块 下一页 查看更多。"
        return result

    async def detail(self, resource_key):
        group, slug = parse_key(resource_key)
        data = await self.api.request(
            "GET", f"/{group.path}/detail/{slug}", ttl=self._ttl("detail", 3600)
        )
        row = self._row(group, {**data, "slug": slug})
        row["description"] = plain(
            data.get("body_zh") or data.get("body_en") or row["description"], 1000
        )
        return self._resource_result("资源详情", [row], "中文内容由上游机器翻译，译名仅供参考。")

    async def _versions(self, resource_key, game_versions=None, loaders=None):
        group, slug = parse_key(resource_key)
        game_versions = values(game_versions or [])
        loaders = [v.lower() for v in values(loaders or [])]
        params = []
        if group.kind != "plugin":
            params += [("game_version[]", v) for v in game_versions]
            if group.source == "mr":
                params += [("loader[]", v) for v in loaders]
        data = await self.api.request(
            "GET",
            f"/{group.path}/detail/{slug}/versions",
            params=params,
            ttl=self._ttl("versions", 600),
        )
        if not isinstance(data, list):
            raise MinekuaiError("版本接口返回结构异常，应为数组。")
        versions = [normalize_version(group, item) for item in data if isinstance(item, dict)]
        versions = [
            v
            for v in versions
            if (not game_versions or set(game_versions) & set(v["game_versions"]))
            and (not loaders or set(loaders) & set(v["loaders"]))
        ]

        def published_at(version):
            try:
                return (
                    datetime.fromisoformat(version["published"].replace("Z", "+00:00"))
                    .replace(tzinfo=UTC)
                    .timestamp()
                )
            except (ValueError, TypeError):
                return 0

        versions.sort(key=published_at, reverse=True)
        return group, versions

    async def versions(self, resource_key, game_versions=None, loaders=None, page=1):
        page = self._page(page)
        group, versions = await self._versions(resource_key, game_versions, loaders)
        start = (page - 1) * self.settings.page_size
        rows = []
        for version in versions[start : start + self.settings.page_size]:
            rows.append(
                {
                    "title": version["name"],
                    "subtitle": f"版本 ID：{version['id']} · {version['release']}",
                    "description": "游戏版本："
                    + (", ".join(version["game_versions"]) or "未知")
                    + "\n加载器："
                    + (", ".join(version["loaders"]) or "未知"),
                    "meta": version["published"],
                }
            )
        result = Result(
            f"{group.label} · 版本列表",
            rows,
            f"第 {page} 页 · 本次接口返回范围内匹配 {len(versions)} 个版本。"
            + ("\n没有已知兼容的版本。" if not rows else ""),
        )
        if start + len(rows) < len(versions):
            result.next_request = {
                "action": "versions",
                "resource_key": resource_key,
                "game_versions": game_versions,
                "loaders": loaders,
                "page": page + 1,
            }
        return result

    async def download(
        self, resource_key, game_versions=None, loaders=None, version_id="", allow_prerelease=None
    ):
        group, slug = parse_key(resource_key)
        detail = await self.api.request(
            "GET", f"/{group.path}/detail/{slug}", ttl=self._ttl("detail", 3600)
        )
        project = project_url(group, {**detail, "slug": slug})
        if detail.get("allow_mod_distribution") is False:
            return self._download_result(
                resource_key,
                None,
                project,
                "作者限制第三方分发，请在原项目页获取。",
                "project_page",
            )
        group, versions = await self._versions(resource_key, game_versions, loaders)
        if version_id:
            versions = [v for v in versions if v["id"] == str(version_id)]
        else:
            include_pre = (
                self.settings.get("allow_prerelease", False)
                if allow_prerelease is None
                else allow_prerelease
            )
            if not include_pre:
                versions = [v for v in versions if v["release"] in {"release", "unknown"}]
        if not versions:
            raise MinekuaiError(
                "没有符合游戏版本、加载器及发布类型的文件。可查看版本列表，或显式开启 预览=是。"
            )
        version = versions[0]
        url = version["url"]
        if not url:
            return self._download_result(
                resource_key,
                version,
                project,
                "没有可用直链，可能为付费、外链或限制分发资源，请访问项目页。",
                "project_page" if project else "unavailable",
            )
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        is_project = (
            host == "curseforge.com" or host.endswith(".curseforge.com")
        ) and "/minecraft/" in parsed.path
        return self._download_result(
            resource_key,
            version,
            url,
            "链接类型：项目页" if is_project else "链接类型：文件直链",
            "project_page" if is_project else "direct",
        )

    @staticmethod
    def _download_result(key, version, url, note, link_kind):
        row = {"title": key, "description": note, "subtitle": link_kind}
        if version:
            row.update(
                {
                    "title": version["name"],
                    "subtitle": version["filename"] or version["id"],
                    "meta": f"游戏：{', '.join(version['game_versions']) or '未知'} · 加载器：{', '.join(version['loaders']) or '未知'} · 发布类型：{version['release']}",
                }
            )
        return Result(
            "下载链接",
            [row],
            note,
            [{"label": "项目页" if link_kind == "project_page" else "下载", "url": url}]
            if url
            else [],
        )

    async def filters(self, kind, source="", filters=None):
        group = group_for(kind, source)
        if group is None:
            raise MinekuaiError("查询筛选项需要指定资源类型。")
        data = await self.api.request(
            "GET",
            f"/{group.path}/facets",
            params=self._filters(group, filters or {}),
            ttl=self._ttl("search", 300),
        )
        rows = []
        labels = {
            "loaders": "加载器",
            "game_versions": "游戏版本",
            "categories": "分类",
            "client_sides": "客户端需求",
            "server_sides": "服务端需求",
        }
        for key, label in labels.items():
            entries = data.get(key, [])
            if entries:
                rows.append(
                    {
                        "title": label,
                        "description": "、".join(
                            f"{plain(i.get('value'), 60)} ({i.get('count', '?')})"
                            for i in entries[:30]
                        ),
                        "meta": f"共 {len(entries)} 项，最多展示 30 项",
                    }
                )
        if group.categories:
            categories = await self.api.request(
                "GET", f"/{group.path}/categories", ttl=self._ttl("categories", 86400)
            )
            if isinstance(categories, list):
                tags = [
                    i
                    for i in categories
                    if i.get("project_type", group.kind) == group.kind
                    and i.get("header", "categories") == "categories"
                ]
                rows.append(
                    {
                        "title": "分类标签表",
                        "description": "、".join(
                            plain(i.get("slug") or i.get("name"), 60) for i in tags[:30]
                        ),
                    }
                )
        return Result(
            group.label + " · 筛选项",
            rows,
            "同一维度多值为 OR，不同维度为 AND；分面数量采用自身维度排除统计，不等于组合命中总数。",
        )

    @staticmethod
    def _resource_result(title, rows, note):
        return Result(
            title,
            rows,
            note,
            [
                {"label": f"{i}. {row['title']}", "url": row["url"]}
                for i, row in enumerate(rows, 1)
                if row.get("url")
            ],
            resource_keys=[r["key"] for r in rows],
        )

    @staticmethod
    def _page(page):
        try:
            page = int(page)
        except (ValueError, TypeError) as exc:
            raise MinekuaiError("页码必须是正整数。") from exc
        if not 1 <= page <= 10000:
            raise MinekuaiError("页码需在 1 到 10000 之间。")
        return page
