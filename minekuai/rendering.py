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
        for name, size in [("row", 25), ("text", 20), ("small", 16)]:
            fonts[name + "_regular"] = self._font(size)
            fonts[name + "_bold"] = self._font(size, True)

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

        def wrap_styled(runs, style, width):
            lines, line, x = [], [], 0
            for run in runs:
                font = style + ("_bold" if run.get("bold") else "_regular")
                for char in run["text"].expandtabs(4):
                    if char == "\n":
                        lines.append(line)
                        line, x = [], 0
                        continue
                    advance = probe.textlength(char, font=fonts[font])
                    if line and x + advance > width - 12:
                        lines.append(line)
                        line, x = [], 0
                    if line and line[-1][2] == font and line[-1][3] == run:
                        previous = line[-1]
                        line[-1] = (previous[0], previous[1] + char, font, run)
                    else:
                        line.append((x, char, font, run))
                    x += advance
            lines.append(line)
            return lines

        blocks = []
        styled_blocks = []
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
                left = 98 if key != "meta" else 108
                if row.get(key + "_runs"):
                    for line in wrap_styled(row[key + "_runs"], style, 742):
                        for offset, text, font, run in line:
                            styled_blocks.append((left + offset, y, text, font, color, run))
                        y += line_height
                else:
                    for line in wrap(row[key], fonts[style], 742):
                        blocks.append((left, y, line, style, color))
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
        for x, ty, text, font, default_color, run in styled_blocks:
            color = run.get("color", default_color)
            # Keep Minecraft white/yellow readable on the light card without changing their color.
            rgb = tuple(int(color[index : index + 2], 16) for index in (1, 3, 5))
            outline = 1 if sum(rgb) > 480 else 0
            options = {
                "font": fonts[font],
                "fill": color,
                "stroke_width": outline,
                "stroke_fill": "#425D53",
            }
            if run.get("italic"):
                width = int(probe.textlength(text, font=fonts[font])) + 6
                height = fonts[font].size * 2 + 6
                layer = Image.new("RGBA", (width, height))
                ImageDraw.Draw(layer).text((2, 2), text, **options)
                slanted = layer.transform(
                    (width + int(height * 0.22) + 1, height),
                    Image.Transform.AFFINE,
                    (1, 0.22, -height * 0.22, 0, 1, 0),
                    resample=Image.Resampling.BICUBIC,
                )
                image.paste(slanted, (int(x) - 2, ty - 2), slanted)
            else:
                draw.text((x, ty), text, **options)
            length = probe.textlength(text, font=fonts[font])
            for decoration, offset in [
                ("underlined", fonts[font].size + 4),
                ("strikethrough", fonts[font].size * 0.65 + 3),
            ]:
                if run.get(decoration):
                    draw.line((x, ty + offset, x + length, ty + offset), fill=color, width=2)
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
