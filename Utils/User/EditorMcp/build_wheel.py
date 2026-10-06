"""
build_wheel.py — 零依赖 wheel 构建器（离线环境用, 不依赖 setuptools/build）。

用法:
    python Utils/User/EditorMcp/build_wheel.py
产物:
    Utils/User/EditorMcp/dist/engine_editor_mcp-<version>-py3-none-any.whl

说明: 纯 Python 包, 手工组装 wheel 结构（包目录[含 skills/ 数据] + dist-info + RECORD）;
新增 op 后记得先跑 `python -m engine_editor_mcp.docgen` 重生成 ops.md（测试会校验新鲜度）。
如后续需要 PyPI 生态标准构建, 安装 setuptools 后可直接 `pip wheel`。
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import zipfile

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(PKG_DIR, "src", "engine_editor_mcp")
DIST = os.path.join(PKG_DIR, "dist")
NAME = "engine-editor-mcp"
DIST_NAME = "engine_editor_mcp"


def _version() -> str:
    with open(os.path.join(SRC, "__init__.py"), encoding="utf-8") as fh:
        match = re.search(r'__version__\s*=\s*"([^"]+)"', fh.read())
    if not match:
        raise SystemExit("version not found in src/engine_editor_mcp/__init__.py")
    return match.group(1)


def _hash(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def main() -> None:
    version = _version()
    wheel_name = f"{DIST_NAME}-{version}-py3-none-any.whl"
    os.makedirs(DIST, exist_ok=True)
    wheel_path = os.path.join(DIST, wheel_name)

    with open(os.path.join(PKG_DIR, "README.md"), encoding="utf-8") as fh:
        readme = fh.read()

    metadata = (
        "Metadata-Version: 2.1\n"
        f"Name: {NAME}\n"
        f"Version: {version}\n"
        "Summary: MyGameEngine Editor Live MCP — standalone stdio bridge to a running engine editor\n"
        "License: MIT\n"
        "Requires-Python: >=3.10\n"
        "Requires-Dist: mcp>=1.10\n"
        "Requires-Dist: Pillow>=10\n"
        "Requires-Dist: numpy>=1.26\n"
        "Description-Content-Type: text/markdown\n"
        "\n" + readme + "\n"
    ).encode("utf-8")
    wheel_meta = (
        "Wheel-Version: 1.0\n"
        "Generator: engine-editor-mcp build_wheel.py\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n"
    ).encode("utf-8")
    entry_points = (
        "[console_scripts]\n"
        "engine-editor-mcp = engine_editor_mcp.__main__:main\n"
        "engine-editor-cli = engine_editor_mcp.cli:main\n"
    ).encode("utf-8")

    dist_info = f"{DIST_NAME}-{version}.dist-info"
    files: list[tuple[str, bytes]] = []
    for root, dirs, fnames in os.walk(SRC):
        dirs[:] = [d for d in sorted(dirs) if d != "__pycache__"]
        for fname in sorted(fnames):
            if fname.endswith((".pyc", ".pyo")):
                continue
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, SRC).replace(os.sep, "/")
            with open(full, "rb") as fh:
                files.append((f"{DIST_NAME}/{rel}", fh.read()))
    files.append((f"{dist_info}/METADATA", metadata))
    files.append((f"{dist_info}/WHEEL", wheel_meta))
    files.append((f"{dist_info}/entry_points.txt", entry_points))

    record_lines = [f"{path},{_hash(data)},{len(data)}" for path, data in files]
    record_lines.append(f"{dist_info}/RECORD,,")
    files.append((f"{dist_info}/RECORD", ("\n".join(record_lines) + "\n").encode("utf-8")))

    with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, data in files:
            zf.writestr(path, data)

    print(f"[wheel] {wheel_path}")
    print(f"[wheel] files: {len(files)}  size: {os.path.getsize(wheel_path)} bytes")


if __name__ == "__main__":
    main()
