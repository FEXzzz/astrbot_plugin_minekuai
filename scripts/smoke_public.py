"""Read-only public API smoke test. Never loads or accepts a panel API key."""

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from minekuai.http import ApiClient  # noqa: E402
from minekuai.resources import GROUPS, ResourceService  # noqa: E402
from minekuai.settings import Settings  # noqa: E402


async def run():
    settings = Settings({})
    api = ApiClient(settings)
    service = ResourceService(api, settings)
    checks = []
    try:
        for group in GROUPS.values():
            result = await service.search(query="", kind=group.key)
            checks.append({"case": "list:" + group.key, "rows": len(result.rows), "ok": True})
        aggregate = await service.search("create")
        checks.append(
            {"case": "aggregate", "rows": len(aggregate.rows), "ok": len(aggregate.rows) == 9}
        )
        for key, version, loader in [
            ("mr_mod:jei", ["1.20.1"], ["forge"]),
            ("cf_mod:jei", ["1.20.1"], ["forge"]),
            ("mr_plugin:luckperms", [], ["paper"]),
        ]:
            result = await service.versions(key, version, loader)
            checks.append(
                {"case": "versions:" + key, "rows": len(result.rows), "ok": bool(result.rows)}
            )
        download = await service.download("mr_mod:jei", ["1.20.1"], ["forge"])
        checks.append({"case": "download-link-only", "ok": bool(download.links)})
        report = {
            "at": datetime.now(UTC).isoformat(),
            "read_only": True,
            "panel_requests": 0,
            "checks": checks,
        }
        destination = ROOT / ".dev" / "verification"
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "public-smoke.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not all(item["ok"] for item in checks):
            raise RuntimeError("One or more smoke checks failed")
    finally:
        await api.close()


if __name__ == "__main__":
    asyncio.run(run())
