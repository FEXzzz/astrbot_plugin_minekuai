"""Bounded expiring state. Private results cannot cross an actor's session."""

import copy
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from .errors import MinekuaiError
from .models import Actor, Result


class TTLCache:
    def __init__(self, capacity=512, clock=time.monotonic):
        self.capacity = capacity
        self.clock = clock
        self.items = OrderedDict()

    def get(self, key, default=None):
        entry = self.items.get(key)
        if entry is None:
            return default
        expires, value = entry
        if self.clock() >= expires:
            self.items.pop(key, None)
            return default
        self.items.move_to_end(key)
        return copy.deepcopy(value)

    def put(self, key, value, ttl):
        self.items[key] = (self.clock() + ttl, copy.deepcopy(value))
        self.items.move_to_end(key)
        while len(self.items) > self.capacity:
            self.items.popitem(last=False)

    def clear(self):
        self.items.clear()


@dataclass
class StoredResult:
    result: Result
    request: dict[str, Any] | None
    credential_fingerprint: str = ""


class Results:
    def __init__(self, clock=time.monotonic):
        self.cache = TTLCache(512, clock)
        self.latest = TTLCache(256, clock)
        self.latest_resources = TTLCache(256, clock)

    def save(self, actor: Actor, result: Result, request=None, credential_fingerprint="") -> str:
        result_id = secrets.token_hex(8)
        self.cache.put(
            (actor.key, result_id), StoredResult(result, request, credential_fingerprint), 900
        )
        if (
            result.resource_keys
            or result.next_request
            or (request or {}).get("action")
            in {"search", "versions", "instance_list", "instance_file"}
        ):
            self.latest.put(actor.key, result_id, 900)
        if result.resource_keys:
            self.latest_resources.put(actor.key, result_id, 900)
        return result_id

    def get(self, actor: Actor, result_id: str) -> StoredResult:
        stored = self.cache.get((actor.key, result_id))
        if stored is None:
            raise MinekuaiError("查询结果已过期或不属于当前用户和会话，请重新查询。")
        return stored

    def last(self, actor: Actor) -> StoredResult:
        result_id = self.latest.get(actor.key)
        if not result_id:
            raise MinekuaiError("没有最近的查询结果，请先搜索资源。")
        return self.get(actor, result_id)

    def resolve_resource(self, actor: Actor, reference: str) -> str:
        if not str(reference).isdigit():
            return reference
        result_id = self.latest_resources.get(actor.key)
        if not result_id:
            raise MinekuaiError("没有最近的资源结果，请先搜索资源。")
        keys = self.get(actor, result_id).result.resource_keys
        index = int(reference) - 1
        if not 0 <= index < len(keys):
            raise MinekuaiError("结果序号超出范围，请使用卡片中的序号。")
        return keys[index]

    def clear(self):
        self.cache.clear()
        self.latest.clear()
        self.latest_resources.clear()
