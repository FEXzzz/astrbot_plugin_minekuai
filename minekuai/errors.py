"""Errors safe to expose to chat clients."""

import re


class MinekuaiError(Exception):
    """A user-facing error, without request headers or raw response bodies."""

    def __init__(self, message: str, *, status: int = 0, uncertain: bool = False):
        super().__init__(message)
        self.status = status
        self.uncertain = uncertain


def redact(text: object, secret: str = "") -> str:
    value = str(text)
    if secret:
        value = value.replace(secret, "[已隐藏]")
    value = re.sub(r"mkc_[\w-]+", "[已隐藏]", value, flags=re.I)
    value = re.sub(
        r"(?im)((?:[\"']?[\w.-]*(?:password|passwd|secret|token|api[_-]?key)[\w.-]*[\"']?)"
        r"\s*[=:]\s*)([^\r\n,;}]+)",
        r"\1[已隐藏]",
        value,
    )
    value = re.sub(r"(?i)(Bearer\s+)\S+", r"\1[已隐藏]", value)
    return value


def redact_data(value, secret: str = ""):
    """Redact strings before JSON serialization, preserving valid JSON structure."""
    if isinstance(value, str):
        return redact(value, secret)
    if isinstance(value, dict):
        return {key: redact_data(item, secret) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_data(item, secret) for item in value]
    return value
