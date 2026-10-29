"""Bounded Minecraft display text parsing; never interpret HTML or click events."""

import html
import json
import re

from .errors import redact

COLORS = dict(
    zip(
        "0123456789abcdef",
        [
            "#000000",
            "#0000AA",
            "#00AA00",
            "#00AAAA",
            "#AA0000",
            "#AA00AA",
            "#FFAA00",
            "#AAAAAA",
            "#555555",
            "#5555FF",
            "#55FF55",
            "#55FFFF",
            "#FF5555",
            "#FF55FF",
            "#FFFF55",
            "#FFFFFF",
        ],
        strict=True,
    )
)
NAMED_COLORS = dict(
    zip(
        [
            "black",
            "dark_blue",
            "dark_green",
            "dark_aqua",
            "dark_red",
            "dark_purple",
            "gold",
            "gray",
            "dark_gray",
            "blue",
            "green",
            "aqua",
            "red",
            "light_purple",
            "yellow",
            "white",
        ],
        COLORS.values(),
        strict=True,
    )
)
DECORATIONS = {"l": "bold", "m": "strikethrough", "n": "underlined", "o": "italic"}
TOKEN = re.compile(r"([§&])(?:x(?:\1[0-9a-f]){6}|#[0-9a-f]{6}|[0-9a-fk-or])", re.I)


def display_text(value, limit=1000):
    """Return plain text plus serializable styled runs for local instance cards.

    Accept legacy §/& codes, both common hex forms and JSON text/extra components.
    Unknown codes stay visible; §k is consumed without animating/obscuring content.
    """
    runs = []
    remaining = limit
    truncated = False
    nodes = 0

    def emit(text, style):
        nonlocal remaining, truncated
        if not text:
            return
        if len(text) > remaining:
            truncated = True
            text = text[:remaining]
        if not text:
            return
        remaining -= len(text)
        if runs and {k: v for k, v in runs[-1].items() if k != "text"} == style:
            runs[-1]["text"] += text
        else:
            runs.append({"text": text, **style})

    def legacy(text, inherited):
        nonlocal truncated
        # HTML's permissive numeric-entity decoder otherwise eats the start of &#RRGGBB.
        text = re.sub(r"&#([0-9a-fA-F]{6})(?!;)", r"§#\1", str(text))
        text = html.unescape(text)
        if len(text) > 32768:
            truncated = True
            text = text[:32768]
        text = re.sub(r"\\u00a7", "§", text, flags=re.I)
        text = text.replace("\\n", "\n").replace("\\r", "\r")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        style = dict(inherited)
        position = 0
        for match in TOKEN.finditer(text):
            emit(text[position : match.start()], style)
            token = match.group().lower()
            code = token[1:]
            if code[0] == "x":
                style = {"color": "#" + token[3::2].upper()}
            elif code[0] == "#":
                style = {"color": code.upper()}
            elif code in COLORS:
                style = {"color": COLORS[code]}
            elif code == "r":
                style = {}
            elif code in DECORATIONS:
                style[DECORATIONS[code]] = True
            position = match.end()
        emit(text[position:], style)

    def component(node, inherited, depth=0):
        nonlocal nodes, truncated
        nodes += 1
        if nodes > 1024 or depth > 20:
            truncated = True
            return
        if isinstance(node, list):
            # In Minecraft's array shorthand, the first component is the parent.
            base = inherited
            for index, child in enumerate(node[:1024]):
                component(child, base, depth + 1)
                if index == 0 and isinstance(child, dict):
                    base = component_style(child, inherited)
            if len(node) > 1024:
                truncated = True
        elif isinstance(node, dict):
            style = component_style(node, inherited)
            text = node.get("text", node.get("fallback", node.get("translate", "")))
            if isinstance(text, (str, int, float)):
                legacy(text, style)
            extra = node.get("extra", [])
            if isinstance(extra, list):
                for child in extra[:1024]:
                    component(child, style, depth + 1)
                if len(extra) > 1024:
                    truncated = True
        elif isinstance(node, (str, int, float)):
            legacy(node, inherited)

    if isinstance(value, str):
        stripped = value.strip()
        if len(value) <= 32768 and stripped.startswith(("{", "[")):
            try:
                parsed = json.loads(value)
            except (ValueError, RecursionError):
                parsed = None
            if isinstance(parsed, list) or (
                isinstance(parsed, dict) and {"text", "extra", "translate"} & parsed.keys()
            ):
                value = parsed
    component(value, {})
    if truncated:
        runs.append({"text": "…"})
    return "".join(run["text"] for run in runs), runs


def component_style(node, inherited):
    style = dict(inherited)
    color = node.get("color")
    if isinstance(color, str):
        if color.lower() in NAMED_COLORS:
            style["color"] = NAMED_COLORS[color.lower()]
        elif re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            style["color"] = color.upper()
    for key in DECORATIONS.values():
        if isinstance(node.get(key), bool):
            style[key] = node[key]
    return style


def server_row(server, fallback_name="未命名实例", *, secret=""):
    def field(value, limit):
        text, runs = display_text(value, limit)
        clean = redact(text, secret)
        # Redact after flattening too: format codes/components must not split a secret.
        return (clean, [{"text": clean}]) if clean != text else (text, runs)

    title, title_runs = field(server.get("name") or fallback_name, 160)
    description, description_runs = field(server.get("description"), 2000)
    return {
        "title": title or fallback_name,
        "title_runs": title_runs,
        "description": description or "未提供服务器描述",
        "description_runs": description_runs,
    }
