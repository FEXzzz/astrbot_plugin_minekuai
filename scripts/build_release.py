"""Build a small, allowlisted AstrBot plugin archive (never include local keys)."""

import hashlib
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "__init__.py",
    "main.py",
    "metadata.yaml",
    "_conf_schema.json",
    "requirements.txt",
    "README.md",
    "LICENSE",
    "docs/client-api.md",
]


def build():
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    metadata = (ROOT / "metadata.yaml").read_text(encoding="utf-8")
    match = re.search(r"^version:\s*([0-9]+\.[0-9]+\.[0-9]+)\s*$", metadata, re.MULTILINE)
    if not match:
        raise ValueError("metadata.yaml requires a semantic version")
    target = output / f"astrbot_plugin_minekuai-v{match.group(1)}.zip"
    files = [ROOT / name for name in FILES]
    files += sorted((ROOT / "minekuai").glob("*.py"))
    files += sorted((ROOT / "templates").glob("*.html"))
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, "astrbot_plugin_minekuai/" + path.relative_to(ROOT).as_posix())
    if target.stat().st_size >= 16 * 1024 * 1024:
        raise RuntimeError("Archive exceeds AstrBot's 16 MiB limit")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (output / "SHA256SUMS.txt").write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    print(f"{target}\n{target.stat().st_size} bytes\nSHA256 {digest}")
    return target


if __name__ == "__main__":
    build()
