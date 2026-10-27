"""Local card rendering: private data never reaches a hosted HTML renderer."""

import secrets
import time
from pathlib import Path

from .errors import MinekuaiError


class LocalCards:
    def __init__(self, data_dir, font_path=""):
        self.directory = Path(data_dir) / "cards"
        self.font_path = font_path

    def _font(self, size, bold=False):
        from PIL import ImageFont

        candidates = [self.font_path] if self.font_path else []
        candidates += [
            "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
            if bold
            else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/System/Library/Fonts/PingFang.ttc",
        ]
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return ImageFont.truetype(candidate, size)
        raise MinekuaiError("未找到本地中文字体，已回退文本。可在配置中设置 local_font_path。")

    def render(self, result):
        from PIL import Image, ImageDraw

        self.directory.mkdir(parents=True, exist_ok=True)
        self.cleanup()
        probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        fonts = {
            "title": self._font(34, True),
            "row": self._font(25, True),
            "text": self._font(20),
            "small": self._font(16),
            "brand": self._font(14, True),
        }

        def wrap(text, font, width):
            lines = []
            for paragraph in str(text or "").split("\n"):
                current = ""
                for char in paragraph:
                    if current and probe.textlength(current + char, font=font) > width:
                        lines.append(current)
                        current = char
                    else:
                        current += char
                lines.append(current)
            return lines

        blocks = []
        y = 102
        for line in wrap(result.title, fonts["title"], 745):
            blocks.append((95, y - 45, line, "title", "#172D25"))
            y += 46
        header_bottom = y - 15
        y += 8
        separators, slots, backgrounds = [], [], []
        for index, row in enumerate(result.rows, 1):
            y += 22
            slots.append((y, str(index)))
            for key, style, color, line_height in [
                ("title", "row", "#172D25", 36),
                ("subtitle", "small", "#174D36", 25),
                ("description", "text", "#172D25", 31),
                ("meta", "small", "#425D53", 25),
            ]:
                if not row.get(key):
                    continue
                if key == "description":
                    y += 8
                meta_start = y
                if key == "meta":
                    y += 9
                for line in wrap(row[key], fonts[style], 742):
                    blocks.append((98 if key != "meta" else 108, y, line, style, color))
                    y += line_height
                if key == "meta":
                    y += 9
                    backgrounds.append((98, meta_start, 860, y, "#EDF3F7"))
                y += 5
            y += 15
            separators.append(y)
        y += 20
        if result.note:
            for line in wrap(result.note, fonts["small"], 820):
                blocks.append((40, y, line, "small", "#50665B"))
                y += 27
        y += 22
        blocks.append(
            (
                40,
                y,
                "麦块实例助手 · 私有数据仅本地绘制"
                if result.private
                else "麦块资源助手 · 链接见随附文本",
                "brand",
                "#50665B",
            )
        )
        height = max(240, y + 48)
        if height > 6000:
            raise MinekuaiError("结果过长，已回退文本。")
        image = Image.new("RGB", (900, height), "#F6F8F5")
        draw = ImageDraw.Draw(image)
        draw.rectangle((48, 28, 89, 69), fill="#D8E5B9")
        draw.rectangle((40, 36, 81, 77), fill="#174D36")
        draw.text(
            (95, 27),
            "MINEKUAI / INSTANCE" if result.private else "MINEKUAI / RESOURCE INDEX",
            font=fonts["brand"],
            fill="#174D36",
        )
        draw.line((40, header_bottom, 860, header_bottom), fill="#174D36", width=2)
        for left, top, right, bottom, color in backgrounds:
            draw.rectangle((left, top, right, bottom), fill=color)
        for top, number in slots:
            draw.rectangle((40, top, 78, top + 38), fill="#D8E5B9", outline="#174D36", width=2)
            draw.text((51, top + 5), number, font=fonts["text"], fill="#174D36")
        for sy in separators:
            draw.line((40, sy, 860, sy), fill="#D9E2D8")
        for x, ty, text, font, color in blocks:
            draw.text((x, ty), text, font=fonts[font], fill=color)
        path = self.directory / f"mk_card_{secrets.token_hex(12)}.png"
        image.save(path)
        return str(path)

    def cleanup(self):
        if not self.directory.exists():
            return
        # Only our explicitly named generated PNGs are eligible for cleanup.
        files = sorted(
            self.directory.glob("mk_card_*.png"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for index, path in enumerate(files):
            if index >= 63 or time.time() - path.stat().st_mtime >= 900:
                path.unlink(missing_ok=True)
