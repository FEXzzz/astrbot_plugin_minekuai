"""Authenticated instance management with one-use, session-bound confirmations."""

import asyncio
import hashlib
import json
import re
import secrets
import time
from dataclasses import dataclass

from .errors import MinekuaiError, redact
from .minecraft_text import display_text, server_row
from .models import Actor, Result
from .permissions import Guard
from .resources import plain
from .settings import OPERATIONS, WRITE_OPERATIONS, Settings
from .state import TTLCache


def attributes(item):
    if not isinstance(item, dict):
        return {}
    inner = item.get("attributes")
    if isinstance(inner, dict):
        return {**{k: v for k, v in item.items() if k != "attributes"}, **inner}
    return item


def data_object(data):
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        return attributes(data["data"])
    return attributes(data)


def collection(data, *keys):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in (*keys, "data"):
            candidate = data.get(key)
            if isinstance(candidate, list):
                return candidate
            if isinstance(candidate, dict):
                for nested_key in keys:
                    if isinstance(candidate.get(nested_key), list):
                        return candidate[nested_key]
    raise MinekuaiError("面板接口返回结构与规范不一致，请提供脱敏响应以适配；未执行修改。")


def metric(resources, names):
    for name in names:
        value = resources.get(name)
        if value is None:
            continue
        if isinstance(value, dict) and "value" in value:
            return f"{value['value']} {value.get('unit', '（单位未知）')}"
        if name.endswith("_bytes") and isinstance(value, (int, float)):
            return f"{value / 1024**2:.1f} MiB"
        return f"{value}（接口原值，未提供单位）"
    return "未知"


@dataclass
class Pending:
    actor_key: tuple
    identifier: str
    name: str
    operation: str
    payload: dict
    fingerprint: str
    expires_at: float


class PanelService:
    def __init__(
        self,
        api,
        settings: Settings,
        *,
        save_cooldowns=None,
        audit=None,
        clock=time.time,
        sleep=asyncio.sleep,
        poll_seconds=30,
    ):
        self.api = api
        self.settings = settings
        self.guard = Guard(settings)
        self.clock = clock
        self.sleep = sleep
        self.poll_seconds = poll_seconds
        self.pending = TTLCache(128, clock)
        self.cooldowns = {}
        self.save_cooldowns = save_cooldowns
        self.audit = audit
        self.locks = {}
        self.closed = False

    @property
    def fingerprint(self):
        return hashlib.sha256(self.settings.api_key.encode()).hexdigest()

    async def _list(self, page=1):
        return await self.api.request(
            "GET", "/servers", params={"page": page, "per_page": 100}, ttl=30
        )

    async def _resolve(self, reference):
        target = self.settings.aliases.get(reference, reference)
        if not isinstance(target, str) or not re.fullmatch(r"[A-Za-z0-9]{8}", target):
            raise MinekuaiError("请使用实例列表中的 8 位 identifier，或配置明确的实例别名。")
        for page in range(1, 101):
            data = await self._list(page)
            servers = [attributes(item) for item in collection(data, "servers")]
            for server in servers:
                if str(server.get("identifier", "")) == target:
                    return server
            pagination = (
                data.get("meta", {}).get("pagination", {}) if isinstance(data, dict) else {}
            )
            last = pagination.get("total_pages") or pagination.get("last_page")
            if (
                (last is not None and page >= int(last))
                or not servers
                or (last is None and len(servers) < 100)
            ):
                break
        raise MinekuaiError("该 identifier 不在当前密钥的实例列表中。")

    async def list_servers(self, actor, page=1):
        self.guard.check(actor, "list")
        try:
            page = int(page)
        except (ValueError, TypeError) as exc:
            raise MinekuaiError("页码必须为正整数。") from exc
        if not 1 <= page <= 10000:
            raise MinekuaiError("页码超出范围。")
        data = await self.api.request(
            "GET", "/servers", params={"page": page, "per_page": self.settings.page_size}, ttl=30
        )
        items = [attributes(i) for i in collection(data, "servers")]
        rows = [
            {
                **server_row(i, secret=self.settings.api_key),
                "subtitle": str(i.get("identifier", "标识缺失")),
            }
            for i in items
        ]
        result = Result("我的实例", rows, f"第 {page} 页", private=True, operation="list")
        pagination = data.get("meta", {}).get("pagination", {}) if isinstance(data, dict) else {}
        last = pagination.get("total_pages") or pagination.get("last_page")
        if (last is not None and page < int(last)) or (
            last is None and len(items) == self.settings.page_size
        ):
            result.next_request = {"action": "instance_list", "page": page + 1}
        return result

    async def _status(self, identifier, *, fresh=False):
        data = await self.api.request("GET", f"/servers/{identifier}", ttl=0 if fresh else 5)
        server = data_object(data)
        stats = attributes(server.get("stats", {}))
        state = stats.get("current_state", "未知")
        resources = stats.get("resources")
        if not isinstance(resources, dict):
            resources = server.get("resources", {})
        return server, str(state), resources if isinstance(resources, dict) else {}

    async def status(self, actor, identifier):
        self.guard.check(actor, "status")
        server = await self._resolve(identifier)
        identifier = server["identifier"]
        current, state, resources = await self._status(identifier)
        row = {
            **server_row({**server, **current}, identifier, secret=self.settings.api_key),
            "subtitle": identifier + " · " + state,
            "meta": "\n".join(
                [
                    "CPU：" + metric(resources, ["cpu_absolute", "cpu"]),
                    "内存：" + metric(resources, ["memory_bytes", "memory"]),
                    "磁盘：" + metric(resources, ["disk_bytes", "disk"]),
                ]
            ),
        }
        return Result(
            "实例状态", [row], "状态快照；缺失指标显示未知。", private=True, operation="status"
        )

    async def _startup(self, identifier):
        data = await self.api.request("GET", f"/servers/{identifier}/startup")
        variables = [attributes(i) for i in collection(data, "variables")]
        meta = data.get("meta", {}) if isinstance(data, dict) else {}
        obj = data_object(data)
        command = (
            meta.get("startup_command")
            or obj.get("startup_command")
            or obj.get("startup")
            or "未提供"
        )
        return variables, str(command)

    async def startup(self, actor, identifier):
        self.guard.check(actor, "startup_read")
        server = await self._resolve(identifier)
        variables, command = await self._startup(server["identifier"])
        rows = []
        for item in variables:
            key = str(item.get("env_variable", ""))
            value = item.get("server_value", item.get("value", item.get("default_value", "")))
            if re.search(r"password|passwd|secret|token|api.?key", key, re.I):
                value = "[已隐藏]"
            rows.append(
                {"title": key, "description": redact(str(value), self.settings.api_key)[:500]}
            )
        return Result(
            "启动配置 · " + server["identifier"],
            rows,
            "启动命令：" + redact(command, self.settings.api_key)[:2000],
            private=True,
            operation="startup_read",
        )

    async def _games(self, identifier):
        data = await self.api.request("GET", f"/servers/{identifier}/allowed-games")
        games = []
        for item in collection(data, "games", "allowed_games"):
            if isinstance(item, str):
                games.append({"game_type": item, "name": item})
            elif isinstance(item, dict):
                item = attributes(item)
                if isinstance(item.get("game_type"), str):
                    games.append(item)
        return games

    async def allowed_games(self, actor, identifier):
        self.guard.check(actor, "allowed_games")
        server = await self._resolve(identifier)
        games = await self._games(server["identifier"])
        return Result(
            "可切换游戏",
            [
                {"title": plain(g.get("name") or g["game_type"], 100), "subtitle": g["game_type"]}
                for g in games
            ],
            "切换游戏会清空实例全部文件并重装。",
            private=True,
            operation="allowed_games",
        )

    async def read_file(self, actor, identifier, path, page=1):
        self.guard.check(actor, "file_read")
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or "\x00" in path
            or len(path) > 1000
        ):
            raise MinekuaiError("文件路径必须是实例内的绝对路径，例如 /server.properties。")
        try:
            page = int(page)
        except (ValueError, TypeError) as exc:
            raise MinekuaiError("文件页码必须是正整数。") from exc
        if not 1 <= page <= 10000:
            raise MinekuaiError("文件页码超出范围。")
        server = await self._resolve(identifier)
        content = await self.api.request(
            "GET",
            f"/servers/{server['identifier']}/files/contents",
            params={"file": path},
            text=True,
        )
        # Limit the raw body at the transport, redact before caching/presentation, then split on lines.
        content = redact(content, self.settings.api_key)
        pages, current = [], ""
        for line in content.splitlines(keepends=True):
            while line:
                remaining = 4000 - len(current)
                if len(line) <= remaining:
                    current += line
                    line = ""
                else:
                    if current:
                        pages.append(current)
                        current = ""
                    elif len(line) > 4000:
                        pages.append(line[:4000])
                        line = line[4000:]
        if current or not pages:
            pages.append(current)
        if page > len(pages):
            raise MinekuaiError(f"文件共 {len(pages)} 页，请调整页码。")
        result = Result(
            "文件 · " + plain(path, 150),
            [
                {
                    "title": f"第 {page}/{len(pages)} 页",
                    "description": pages[page - 1] or "（空文件）",
                }
            ],
            "可能包含的密码和令牌已遮罩；翻页会重新读取文件。",
            private=True,
            operation="file_read",
        )
        if page < len(pages):
            result.next_request = {
                "action": "instance_file",
                "identifier": server["identifier"],
                "path": path,
                "page": page + 1,
            }
        return result

    def _cooldown_key(self, identifier):
        return f"{self.fingerprint}:{identifier}"

    def _check_cooldown(self, identifier):
        remaining = self.cooldowns.get(self._cooldown_key(identifier), 0) - self.clock()
        if remaining > 0:
            raise MinekuaiError(f"实例切换冷却中，请 {max(1, int(remaining + 0.999))} 秒后重试。")

    async def _mark_cooldown(self, identifier):
        self.cooldowns = {
            k: v
            for k, v in self.cooldowns.items()
            if isinstance(v, (int, float)) and v > self.clock()
        }
        self.cooldowns[self._cooldown_key(identifier)] = self.clock() + 60
        if self.save_cooldowns:
            await self.save_cooldowns(self.cooldowns)

    async def _validate(self, identifier, operation, payload):
        expected = {
            "start": set(),
            "stop": set(),
            "restart": set(),
            "kill": set(),
            "command": {"command"},
            "startup_write": {"key", "value"},
            "game_switch": {"game_type"},
            "modpack_switch": set(payload),
        }
        if operation not in expected or set(payload) != expected[operation]:
            raise MinekuaiError("操作参数不完整或包含不支持的字段。")
        if operation == "command":
            command = payload["command"]
            if (
                not isinstance(command, str)
                or not command.strip()
                or len(command) > 4096
                or any(c in command for c in "\r\n\x00")
            ):
                raise MinekuaiError("控制台命令必须是非空单行文本，最多 4096 字符。")
            _, state, _ = await self._status(identifier, fresh=True)
            if state != "running":
                raise MinekuaiError("实例必须处于 running 状态才能发送控制台命令。")
        elif operation == "startup_write":
            if (
                not isinstance(payload["key"], str)
                or not isinstance(payload["value"], str)
                or len(payload["value"]) > 4096
            ):
                raise MinekuaiError("启动变量的名称和值必须是字符串，值最多 4096 字符。")
            variables, _ = await self._startup(identifier)
            if payload["key"] not in {v.get("env_variable") for v in variables}:
                raise MinekuaiError("变量名不在该实例 /startup 返回的 env_variable 中。")
        elif operation == "game_switch":
            self._check_cooldown(identifier)
            if payload["game_type"] not in {g["game_type"] for g in await self._games(identifier)}:
                raise MinekuaiError("该游戏不在实例套餐允许的切换列表中。")
        elif operation == "modpack_switch":
            self._check_cooldown(identifier)
            if set(payload) == {"modpack_id"}:
                if type(payload["modpack_id"]) is not int or payload["modpack_id"] <= 0:
                    raise MinekuaiError("modpack_id 必须是面板提供的正整数。")
            elif set(payload) == {"file_name"}:
                name = payload["file_name"]
                if (
                    not isinstance(name, str)
                    or not re.fullmatch(r"[^/\\\x00-\x1f]{1,255}", name)
                    or name in {".", ".."}
                    or ":" in name
                ):
                    raise MinekuaiError("file_name 必须是面板提供的文件名，不能是路径或下载 URL。")
            else:
                raise MinekuaiError("modpack_id 和 file_name 必须且只能提供其中一个。")

    async def prepare(self, actor: Actor, identifier, operation, payload=None):
        self.guard.check(actor, operation)
        initial_fingerprint = self.fingerprint
        if operation not in WRITE_OPERATIONS:
            raise MinekuaiError("该动作不是可准备的写操作。")
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise MinekuaiError("操作参数必须是对象。")
        server = await self._resolve(identifier)
        identifier = server["identifier"]
        await self._validate(identifier, operation, payload)
        if initial_fingerprint != self.fingerprint:
            raise MinekuaiError("准备期间密钥发生变化，请重新准备操作。")
        code = secrets.token_hex(4).upper()
        ttl = self.settings.integer("confirmation_timeout", 60, 10, 300)
        pending = Pending(
            actor.key,
            identifier,
            display_text(server.get("name") or identifier, 160)[0],
            operation,
            dict(payload),
            self.fingerprint,
            self.clock() + ttl,
        )
        self.pending.put(code, pending, ttl)
        preview = dict(payload)
        if operation == "startup_write" and re.search(
            r"password|passwd|secret|token|api.?key", str(payload.get("key")), re.I
        ):
            preview["value"] = "[已隐藏]"
        warning = (
            "\n此操作将删除实例全部文件并重装，请先在面板完成备份。"
            if operation in {"game_switch", "modpack_switch"}
            else ""
        )
        note = (
            f"目标：{pending.name}（{identifier}）\n动作：{OPERATIONS[operation]}\n参数："
            + redact(json.dumps(preview, ensure_ascii=False), self.settings.api_key)
            + warning
            + f"\n{self.settings.integer('confirmation_timeout', 60, 10, 300)} 秒内在当前会话发送：\n/麦块 实例 确认 {code}\n取消：/麦块 实例 取消 {code}"
        )
        return Result("待确认操作", note=note, private=True, operation=operation)

    def _pending_for(self, actor, code):
        code = str(code).strip().upper()
        pending = self.pending.get(code)
        if pending is None or pending.actor_key != actor.key:
            raise MinekuaiError("确认码无效、已过期或不属于当前管理员和会话。")
        self.guard.check(actor, pending.operation)
        if pending.fingerprint != self.fingerprint:
            self.pending.items.pop(code, None)
            raise MinekuaiError("密钥已变化，请重新准备操作。")
        return code, pending

    def cancel(self, actor, code):
        code, pending = self._pending_for(actor, code)
        self.pending.items.pop(code, None)
        return Result(
            "操作已取消",
            note=OPERATIONS[pending.operation],
            private=True,
            operation=pending.operation,
        )

    async def confirm(self, actor, code):
        code, pending = self._pending_for(actor, code)
        # Consume synchronously before any await: duplicate concurrent confirmations cannot write twice.
        self.pending.items.pop(code, None)
        lock = self.locks.setdefault(pending.identifier, asyncio.Lock())
        async with lock:
            self.guard.check(actor, pending.operation)
            if self.clock() >= pending.expires_at:
                raise MinekuaiError("操作确认已过期，请重新准备。")
            if pending.fingerprint != self.fingerprint:
                raise MinekuaiError("密钥已变化，请重新准备操作。")
            await self._resolve(pending.identifier)
            await self._validate(pending.identifier, pending.operation, pending.payload)
            self.guard.check(actor, pending.operation)
            if self.clock() >= pending.expires_at:
                raise MinekuaiError("操作确认已过期，请重新准备。")
            if pending.fingerprint != self.fingerprint:
                raise MinekuaiError("密钥已变化，请重新准备操作。")
            operation, identifier = pending.operation, pending.identifier
            method, suffix, payload = "POST", "", pending.payload
            if operation in {"start", "stop", "restart", "kill"}:
                suffix, payload = "power", {"signal": operation}
            else:
                suffix = {
                    "command": "command",
                    "startup_write": "startup/variable",
                    "game_switch": "game-switch",
                    "modpack_switch": "modpack-switch",
                }[operation]
                if operation == "startup_write":
                    method = "PUT"
            switched = operation in {"game_switch", "modpack_switch"}
            try:
                response = await self.api.request(
                    method,
                    f"/servers/{identifier}/{suffix}",
                    body=payload,
                    empty_ok=operation == "startup_write",
                )
                acknowledged = (
                    not (
                        isinstance(response, dict)
                        and (response.get("success") is False or "error" in response)
                    )
                    if operation == "startup_write"
                    else isinstance(response, dict) and response.get("success") is True
                )
                if not acknowledged:
                    raise MinekuaiError(
                        "接口未明确确认操作成功，结果未知，请在面板核对后再操作。", uncertain=True
                    )
            except asyncio.CancelledError:
                # Reload may cancel a request after the panel accepted it. Retain switch cooldown.
                if switched:
                    await asyncio.shield(self._mark_cooldown(identifier))
                self._audit(actor, pending, "cancelled:unknown")
                raise
            except MinekuaiError as exc:
                if switched and exc.uncertain:
                    await self._mark_cooldown(identifier)
                self._audit(actor, pending, "unknown" if exc.uncertain else f"failed:{exc.status}")
                raise
            if switched:
                await self._mark_cooldown(identifier)
            self.api.clear()
            self._audit(actor, pending, "accepted")
            note = "请求已受理。"
            if operation == "command":
                note = "控制台命令已提交。此接口不提供命令执行输出。"
            elif operation in {"start", "stop", "restart", "kill"}:
                note = await self._poll_power(identifier, operation)
            elif operation == "startup_write":
                try:
                    variables, _ = await self._startup(identifier)
                    match = next(
                        (v for v in variables if v.get("env_variable") == payload["key"]), {}
                    )
                    actual = match.get("server_value", match.get("value"))
                    note = (
                        "变量修改已受理；重新读取后值一致。"
                        if actual is not None and str(actual) == payload["value"]
                        else "变量修改已受理，读取值尚未一致，请检查面板。"
                    )
                except MinekuaiError:
                    note = "变量修改已受理，暂时无法重新读取核验。"
            elif switched:
                note = "切换请求已受理，请查询实例状态检查重装进度。此实例切换冷却 60 秒。"
            return Result(
                "实例操作结果",
                [{"title": pending.name, "subtitle": identifier + " · " + OPERATIONS[operation]}],
                note,
                private=True,
                operation=operation,
            )

    async def _poll_power(self, identifier, operation):
        started = self.clock()
        transitioned = False
        last = "未知"
        target = "offline" if operation in {"stop", "kill"} else "running"
        for _ in range(11):
            remaining = self.poll_seconds - (self.clock() - started)
            if self.closed or remaining <= 0:
                break
            try:
                async with asyncio.timeout(remaining):
                    _, last, _ = await self._status(identifier, fresh=True)
            except (MinekuaiError, TimeoutError):
                break
            if last != "running":
                transitioned = True
            if last == target and (operation != "restart" or transitioned):
                return f"已观察到目标状态：{last}。"
            await self.sleep(min(3, max(0, self.poll_seconds - (self.clock() - started))))
        return f"请求已受理；当前观测状态：{last}。尚未确认操作完成，请稍后查询。"

    def _audit(self, actor, pending, outcome):
        if self.audit:
            self.audit(
                {
                    "actor": actor.user_id,
                    "platform": actor.platform_id,
                    "instance": pending.identifier,
                    "operation": pending.operation,
                    "time": int(self.clock()),
                    "outcome": outcome,
                }
            )

    def close(self):
        self.closed = True
        self.pending.clear()
