"""Generate reproducible public HTML previews and a synthetic local instance card."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jinja2 import Environment  # noqa: E402

from minekuai.models import Result  # noqa: E402
from minekuai.rendering import LocalCards  # noqa: E402


def run():
    output = ROOT / "output" / "playwright"
    output.mkdir(parents=True, exist_ok=True)
    template = Environment(autoescape=True).from_string(
        (ROOT / "templates/card.html").read_text(encoding="utf-8")
    )
    rows = [
        {
            "title": "机械动力",
            "subtitle": "Modrinth 模组 · mr_mod:create · Create",
            "description": "用旋转与齿轮建造自动化机械，让传送带、风车和火车成为你的创造工具。",
            "meta": "加载器 forge, neoforge, fabric  ·  游戏版本 1.20.1, 1.21.1",
        },
        {
            "title": "应有尽有",
            "subtitle": "CurseForge 模组 · cf_mod:jei · Just Enough Items",
            "description": "查看物品和合成配方。选择你的游戏版本与加载器，再获取对应的正式版文件。",
            "meta": "加载器 forge, neoforge, fabric  ·  游戏版本 1.20.1, 1.21.1",
        },
    ]
    examples = {
        "resource-search": {
            "title": "搜索 · 我的世界模组",
            "rows": rows,
            "note": "第 1 页 · 每页 5 条\n发送 /麦块 详情 1 查看资源；下载链接随附文本发送。",
        },
        "resource-detail": {
            "title": "资源详情",
            "rows": [{**rows[0], "description": rows[0]["description"] * 8}],
            "note": "中文内容由上游机器翻译，译名仅供参考。",
        },
        "resource-versions": {
            "title": "Modrinth 模组 · 版本列表",
            "rows": [
                {
                    "title": "15.74.0.230 for Forge 1.20.1",
                    "subtitle": "版本 ID：example-release · release",
                    "description": "游戏版本：1.20.1\n加载器：forge",
                    "meta": "2026-10-25T15:32:47Z",
                }
            ],
            "note": "第 1 页 · 已按游戏版本与加载器筛选",
        },
        "resource-download": {
            "title": "下载链接",
            "rows": [
                {
                    "title": "Just Enough Items · Forge 1.20.1",
                    "subtitle": "jei-1.20.1-forge-release.jar",
                    "description": "文件直链见随附文本",
                    "meta": "游戏：1.20.1 · 加载器：forge · 发布类型：release",
                }
            ],
            "note": "链接类型：文件直链",
        },
        "resource-stress": {
            "title": "长标题测试" * 15,
            "rows": [
                {
                    "title": "超长项目名称" * 20,
                    "subtitle": "very-long-source-id-" * 30,
                    "description": "中文与 English 混排测试 <script>不会执行</script>\n" * 15,
                    "meta": "abcdefghijklmnopqrstuvwxyz" * 20,
                }
            ],
            "note": "边界测试，不应水平溢出。",
        },
    }
    for name, data in examples.items():
        (output / (name + ".html")).write_text(template.render(**data), encoding="utf-8")
    local = LocalCards(ROOT / ".dev" / "verification")
    private_path = local.render(
        Result(
            "实例状态",
            [
                {
                    "title": "测试生存服",
                    "subtitle": "ab12cd34 · running",
                    "description": "CPU：7.2（接口原值，未提供单位）\n内存：256.0 MiB\n磁盘：未知",
                }
            ],
            "本地合成数据，仅用于验证版式。",
            private=True,
            operation="status",
        )
    )
    print(f"HTML previews: {output}\nSynthetic local card: {private_path}")


if __name__ == "__main__":
    run()
