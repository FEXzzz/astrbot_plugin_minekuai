"""Small serializable models shared by commands, tools and renderers."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Actor:
    platform_id: str
    origin: str
    user_id: str
    group_id: str = ""
    is_admin: bool = False
    is_private: bool = True

    @property
    def key(self) -> tuple[str, str, str]:
        return self.platform_id, self.origin, self.user_id


@dataclass
class Result:
    title: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""
    links: list[dict[str, str]] = field(default_factory=list)
    private: bool = False
    operation: str = ""
    next_request: dict[str, Any] | None = None
    resource_keys: list[str] = field(default_factory=list)

    def text(self) -> str:
        parts = [self.title]
        for index, row in enumerate(self.rows, 1):
            parts.append(f"{index}. {row.get('title', '')}")
            for key in ("subtitle", "description", "meta"):
                if row.get(key):
                    parts.append(str(row[key]))
        if self.note:
            parts.append(self.note)
        return "\n".join(parts)
