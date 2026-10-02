"""
collect_wheels — 收集 wheelhouse 到 Resource/wheels（离线可重建环境的材料）。

以 .venv-py314t 实际安装为真源（而不是手维护清单）:
  1. pip freeze → requirements.export.txt
     （git 依赖如 imgui-bundle 换成 Resource/wheels 内本地 wheel 的版本号）
  2. pip download → Resource/wheels（已存在的本地 wheel 不删除, 与下载结果共存）
  3. 核对: 每条需求都有对应 wheel（sdist 单独标注; 缺失则报错）
  4. 生成 CHECKSUMS.sha256

注: Resource/wheels 不进 git（仅保留 requirements 两份 + 自建 imgui 引导轮）——
本脚本负责在新机器上从 PyPI 重建 wheelhouse。

用法:
    .venv-py314t\\Scripts\\python.exe Utils/Dev/collect_wheels.py
"""

from __future__ import annotations

import glob
import hashlib
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
VENV_PY = os.path.join(ROOT, ".venv-py314t", "Scripts", "python.exe")
WHEELS = os.path.join(ROOT, "Resource", "wheels")
REQUIREMENTS = os.path.join(WHEELS, "requirements.export.txt")
REQUIREMENTS_RUNTIME = os.path.join(WHEELS, "requirements.runtime.txt")

# 编辑器专用包 — 播放器/导出游戏运行时零依赖（2026-09-28 实证: 包内隐藏后
# dry-run + 窗口运行全绿; 静态守卫: Test/Application/Core/test_node_graph_boundary.py
# 的运行时树扫描, Editor 与 Vulkan 目录除外）。wheelhouse 仍保留全量轮子用于重建。
_EDITOR_ONLY = [
    "imgui-bundle",           # 编辑器 UI 全家桶
    # MCP 工具链（Utils/User/NodeEditor mcp_server 专用）
    "mcp", "starlette", "uvicorn", "sse-starlette",
    "httpx", "httpx-sse", "httpcore", "h11", "anyio",
    "pydantic", "pydantic-core", "pydantic-settings",
    "typing-inspection", "annotated-types",
    "jsonschema", "jsonschema-specifications", "referencing", "rpds-py", "attrs",
    "python-dotenv", "python-multipart", "click", "colorama",
    "certifi", "idna",
]
_RUN_EXCLUDED_NORM = {n.lower().replace("-", "_") for n in _EDITOR_ONLY}


def _norm(name: str) -> str:
    return name.lower().replace("-", "_").replace(".", "_")


def _run(cmd: list[str], capture: bool = True) -> subprocess.CompletedProcess:
    print(f"[collect] $ {' '.join(cmd)}")
    return subprocess.run(
        cmd, capture_output=capture, text=True, encoding="utf-8", errors="replace"
    )


def freeze_requirements() -> list[str]:
    """venv 实际安装 → 需求行（git 依赖替换为本地 wheel 版本）。"""
    result = _run([VENV_PY, "-m", "pip", "freeze"])
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise RuntimeError("pip freeze 失败")

    reqs: list[str] = []
    git_deps: list[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "@" in line:  # 直链/git 依赖 — 由本地 wheel 提供
            git_deps.append(line.split("@", 1)[0].strip())
            continue
        reqs.append(line)

    # git 依赖 → 用本地 wheel 文件名解析版本
    for dep in git_deps:
        found = glob.glob(os.path.join(WHEELS, f"{_norm(dep)}-*.whl"))
        if not found:
            raise RuntimeError(
                f"git 依赖 '{dep}' 在 Resource/wheels 没有本地 wheel — "
                f"请先放入构建好的 .whl"
            )
        fname = os.path.basename(found[0])
        ver = fname.split("-")[1]
        reqs.append(f"{dep}=={ver}")
        print(f"[collect] local wheel for git dep: {dep}=={ver} ({fname})")

    # pip 自身（供包内离线修复能力）
    pip_ver = _run([VENV_PY, "-m", "pip", "--version"]).stdout.split()[1]
    if not any(r.lower().startswith("pip==") for r in reqs):
        reqs.append(f"pip=={pip_ver}")

    reqs.sort(key=str.lower)
    os.makedirs(WHEELS, exist_ok=True)
    with open(REQUIREMENTS, "w", encoding="utf-8") as fh:
        fh.write("\n".join(reqs) + "\n")
    print(f"[collect] wrote {REQUIREMENTS} ({len(reqs)} requirements)")

    # 游戏运行时子集（编辑器专用包除外）
    runtime_reqs = [
        r for r in reqs
        if r.split("==", 1)[0].lower().replace("-", "_") not in _RUN_EXCLUDED_NORM
    ]
    with open(REQUIREMENTS_RUNTIME, "w", encoding="utf-8") as fh:
        fh.write("\n".join(runtime_reqs) + "\n")
    print(
        f"[collect] wrote {REQUIREMENTS_RUNTIME} ({len(runtime_reqs)} requirements, "
        f"{len(reqs) - len(runtime_reqs)} editor-only excluded)"
    )
    return reqs


def download(reqs: list[str]) -> list[str]:
    """逐包下载（--no-deps, 可断点续传）—— freeze 列表已是完整闭包, 无需解析器。

    逐包方式的好处:
      - 进度可视（每包一行结果 + 耗时）
      - 不受解析器网络悬挂影响（单包失败不阻塞其余）
      - 已就位/已缓存的包瞬时跳过
    """
    to_download = [
        r for r in reqs if not r.lower().startswith("imgui-bundle")
    ]
    index = os.environ.get("PIP_INDEX_URL") or "(default PyPI)"
    print(f"[collect] index: {index}")

    import time as _time

    shipped = {_norm(os.path.basename(p)) for p in glob.glob(os.path.join(WHEELS, "*.whl"))}
    failed: list[str] = []
    for req in to_download:
        name, _, version = req.partition("==")
        n, v = _norm(name), _norm(version)
        if any(f.startswith(f"{n}_{v}_") and f.endswith("_whl") for f in shipped):
            print(f"[collect] have : {req}")
            continue
        t0 = _time.monotonic()
        result = _run([
            VENV_PY, "-m", "pip", "download",
            "--disable-pip-version-check",
            "--prefer-binary",
            "--no-deps",
            "--timeout", "30",
            "--retries", "2",
            "-d", WHEELS,
            req,
        ])
        dt = _time.monotonic() - t0
        if result.returncode != 0:
            print(f"[collect] FAIL : {req} ({dt:.0f}s)")
            if result.stdout:
                print("    " + "\n    ".join(result.stdout.strip().splitlines()[-3:]))
            failed.append(req)
        else:
            # 更新 shipped 集合（新落盘文件）
            shipped = {_norm(os.path.basename(p)) for p in glob.glob(os.path.join(WHEELS, "*.whl"))}
            print(f"[collect] got  : {req} ({dt:.0f}s)")
    return failed


def verify(reqs: list[str]) -> tuple[list[str], list[str]]:
    """核对 wheelhouse 覆盖度。返回 (缺失, 仅源码)。"""
    missing: list[str] = []
    sdist_only: list[str] = []
    files = [os.path.basename(p) for p in glob.glob(os.path.join(WHEELS, "*"))]
    norm_files = [_norm(f) for f in files]

    for req in reqs:
        name, _, version = req.partition("==")
        n = _norm(name)
        v = _norm(version)
        # 文件名整体归一化后比较（_norm 已把 - 和 . 转为 _）
        prefix = f"{n}_{v}_"
        has_wheel = any(
            f.startswith(prefix) and f.endswith("_whl") for f in norm_files
        )
        has_sdist = any(
            f.startswith(prefix) and (f.endswith("tar_gz") or f.endswith("_zip"))
            for f in norm_files
        )
        if not has_wheel:
            if has_sdist:
                sdist_only.append(req)
            else:
                missing.append(req)
    return missing, sdist_only


def write_checksums() -> int:
    lines: list[str] = []
    for path in sorted(glob.glob(os.path.join(WHEELS, "*.whl"))):
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        lines.append(f"{h.hexdigest()}  {os.path.basename(path)}")
    out = os.path.join(WHEELS, "CHECKSUMS.sha256")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"[collect] wrote {out} ({len(lines)} wheels)")
    return len(lines)


def main() -> int:
    print("=" * 60)
    print("collect_wheels — Resource/wheels")
    print("=" * 60)
    if not os.path.isfile(VENV_PY):
        print(f"[ERROR] venv python 不存在: {VENV_PY}")
        return 1

    reqs = freeze_requirements()
    download_failed = download(reqs)
    missing, sdist_only = verify(reqs)
    if download_failed:
        missing = sorted(set(missing) | set(download_failed))
    n = write_checksums()

    total_bytes = sum(
        os.path.getsize(p)
        for p in glob.glob(os.path.join(WHEELS, "*"))
        if os.path.isfile(p)
    )
    print("=" * 60)
    print(f"[collect] wheels: {n} | total: {total_bytes / (1 << 20):.1f} MiB")
    if sdist_only:
        print(f"[collect] SOURCE-ONLY ({len(sdist_only)}) — 安装时需要编译工具链:")
        for s in sdist_only:
            print(f"  ~ {s}")
    if missing:
        print(f"[collect] MISSING ({len(missing)}):")
        for m in missing:
            print(f"  ✗ {m}")
        return 1
    print("[collect] COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
