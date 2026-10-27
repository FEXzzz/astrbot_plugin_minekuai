"""Separate authenticated/public transports with bounded GET retries."""

import asyncio
import copy
import time
from collections import deque

import httpx

from .errors import MinekuaiError, redact
from .settings import Settings
from .state import TTLCache

PUBLIC_BASE = "https://api.minekuai.cn/panel/public"
PANEL_BASE = "https://api.minekuai.cn/panel/client-api"


class RateLimiter:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.calls = deque()
        self.blocked_until = 0.0

    def take(self, limit: int):
        now = self.clock()
        while self.calls and now - self.calls[0] >= 60:
            self.calls.popleft()
        if now < self.blocked_until:
            raise MinekuaiError(
                f"接口限流中，请约 {max(1, int(self.blocked_until - now))} 秒后重试。", status=429
            )
        if len(self.calls) >= limit:
            raise MinekuaiError("已达到插件本分钟的请求预算，请稍后重试。", status=429)
        self.calls.append(now)


class ApiClient:
    def __init__(self, settings: Settings, *, panel=False, transport=None, sleep=asyncio.sleep):
        self.settings = settings
        self.panel = panel
        self.base = PANEL_BASE if panel else PUBLIC_BASE
        # Never attach panel credentials to a shared client or follow redirects.
        self.client = httpx.AsyncClient(transport=transport, follow_redirects=False)
        self.cache = TTLCache()
        self.rate = RateLimiter()
        self.semaphore = asyncio.Semaphore(4)
        self.sleep = sleep
        self.inflight = {}

    async def close(self):
        tasks = list(self.inflight.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.inflight.clear()
        self.cache.clear()
        await self.client.aclose()

    def clear(self):
        self.cache.clear()

    async def request(
        self, method, path, *, params=None, body=None, ttl=0, text=False, empty_ok=False
    ):
        if self.settings.get("cache_enabled", True) is False:
            ttl = 0
        if not path.startswith("/") or "://" in path or ".." in path:
            raise MinekuaiError("无效的接口路径。")
        method = method.upper()
        params = params or []
        pairs = list(params.items()) if isinstance(params, dict) else list(params)
        # Credentials partition cached/in-flight results when a key is rotated.
        import hashlib

        api_key = self.settings.api_key if self.panel else ""
        identity = hashlib.sha256(api_key.encode()).hexdigest() if self.panel else "public"
        cache_key = (identity, path, tuple(sorted((str(k), str(v)) for k, v in pairs)), text)
        if method != "GET" or not ttl:
            return await self._send(method, path, pairs, body, text, api_key, empty_ok)
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        if cache_key not in self.inflight:
            self.inflight[cache_key] = asyncio.create_task(
                self._fetch_cached(cache_key, path, pairs, text, ttl, api_key)
            )
        return copy.deepcopy(await asyncio.shield(self.inflight[cache_key]))

    async def _fetch_cached(self, key, path, params, text, ttl, api_key):
        try:
            value = await self._send("GET", path, params, None, text, api_key)
            self.cache.put(key, value, ttl)
            return value
        finally:
            self.inflight.pop(key, None)

    async def _send(self, method, path, params, body, as_text, api_key, empty_ok=False):
        is_read = method == "GET"
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.panel:
            if not api_key.startswith("mkc_"):
                raise MinekuaiError("实例 API 密钥未配置。")
            headers["Authorization"] = f"Bearer {api_key}"
        limit = self.settings.integer(
            "instance_requests_per_minute" if self.panel else "resource_requests_per_minute",
            120,
            1,
            300 if self.panel else 600,
        )
        attempts = 3 if is_read else 1
        for attempt in range(attempts):
            try:
                async with self.semaphore:
                    self.rate.take(limit)
                    async with self.client.stream(
                        method,
                        self.base + path,
                        params=params,
                        json=body,
                        headers=headers,
                        timeout=self.settings.read_timeout
                        if is_read
                        else self.settings.write_timeout,
                    ) as response:
                        # Bound streamed responses before decoding; file contents have a 1 MiB ceiling.
                        ceiling = 1024 * 1024 if as_text else 12 * 1024 * 1024
                        chunks, size = [], 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > ceiling:
                                raise MinekuaiError(
                                    "文件超过 1 MB，请在面板网页下载。"
                                    if as_text
                                    else "接口响应过大，请缩小查询范围。",
                                    uncertain=not is_read,
                                )
                            chunks.append(chunk)
                        raw = b"".join(chunks)
                        status = response.status_code
                        if status == 429:
                            try:
                                delay = float(response.headers.get("Retry-After", "60"))
                            except ValueError:
                                delay = 60
                            self.rate.blocked_until = self.rate.clock() + max(1, min(delay, 3600))
                        if status >= 500 and is_read and attempt < attempts - 1:
                            await self.sleep(2**attempt)
                            continue
                        if not 200 <= status < 300:
                            raise self._http_error(status, raw, api_key, not is_read)
                        if as_text:
                            return raw.decode("utf-8", errors="replace")
                        if not raw and empty_ok and not is_read:
                            return None
                        import json

                        try:
                            return json.loads(raw)
                        except (ValueError, UnicodeError) as exc:
                            if is_read and attempt < attempts - 1:
                                await self.sleep(2**attempt)
                                continue
                            raise MinekuaiError(
                                "接口返回了非 JSON 内容。"
                                + (
                                    " 操作结果未知，请先查询实例状态，勿直接重复操作。"
                                    if not is_read
                                    else ""
                                ),
                                uncertain=not is_read,
                            ) from exc
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                if is_read and attempt < attempts - 1:
                    await self.sleep(2**attempt)
                    continue
                raise MinekuaiError(
                    "读取接口超时或网络不可用，请稍后重试。"
                    if is_read
                    else "写请求超时或连接中断，操作结果未知。请先检查面板或实例状态，勿直接重复操作。",
                    uncertain=not is_read,
                ) from exc

    @staticmethod
    def _http_error(status, raw, api_key, writing):
        messages = {
            400: "请求参数错误，文件也可能超过 1 MB。",
            401: "密钥无效或已撤销，请检查插件配置。",
            403: "访问被拒绝，请检查面板权限及密钥 IP 白名单。",
            404: "实例、资源或接口不存在。",
            409: "实例当前状态不允许操作，或仍处于切换冷却中。",
            422: "请求参数不符合接口要求。",
            429: "接口调用频率超限，请稍后重试。",
        }
        message = messages.get(status, f"上游接口暂不可用（HTTP {status}）。")
        try:
            import json

            detail = json.loads(raw).get("error", "")
            if isinstance(detail, str) and detail:
                message += " " + redact(detail[:300], api_key)
        except (ValueError, AttributeError, UnicodeError):
            pass
        uncertain = writing and (status >= 500 or 300 <= status < 400)
        if uncertain:
            message += " 操作结果未知，请先查询状态，勿直接重复操作。"
        return MinekuaiError(message, status=status, uncertain=uncertain)
