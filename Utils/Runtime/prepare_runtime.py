"""
prepare_runtime — 在 Resource/runtime 预制可搬运 Python 环境。

步骤:
  1. 定位 uv 管理的 3.14t 独立解释器（python-build-standalone, 可整目录搬运）
  2. 复制为 Resource/runtime（先清空旧镜像）
  3. uv pip install --python <runtime python> --no-index --find-links <wheels>
  4. 冒烟自检（核心依赖 import + free-threading 状态）

用法:
    .venv-py314t\\Scripts\\python.exe Utils/Runtime/prepare_runtime.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WHEELS = os.path.join(ROOT, "Resource", "wheels")
STAGE = os.path.join(ROOT, "Resource", "runtime")
REQUIREMENTS_FULL = os.path.join(WHEELS, "requirements.export.txt")
REQUIREMENTS_RUNTIME = os.path.join(WHEELS, "requirements.runtime.txt")

# 镜像瘦身: 与运行无关的 CPython 发行版内容（2026-09-28 引入; 实证安全）
_TRIM_DIRS = ("Lib/test", "Doc")

SMOKE_NOTE = "运行时子集的冒烟导入（imgui_bundle / mcp 链已在子集中排除）"


def _run(cmd: list[str], capture: bool = True) -> subprocess.CompletedProcess:
    print(f"[runtime] $ {' '.join(cmd)}")
    return subprocess.run(
        cmd, capture_output=capture, text=True, encoding="utf-8", errors="replace"
    )


def find_managed_python() -> str:
    """定位 uv 管理的 3.14t 解释器（python-build-standalone）。"""
    result = _run(["uv", "python", "find", "3.14t"])
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(
            "未找到 uv 管理的 3.14t 解释器 — 先运行: uv python install 3.14t"
        )
    py = result.stdout.strip().splitlines()[-1].strip()
    if not os.path.isfile(py):
        raise RuntimeError(f"解释器路径无效: {py}")
    print(f"[runtime] managed python: {py}")
    return py


def stage_runtime(source_python: str) -> str:
    """复制解释器安装目录 → Resource/runtime（清空旧镜像）。"""
    src_root = os.path.dirname(source_python)
    if os.path.isdir(STAGE):
        print(f"[runtime] removing old image: {STAGE}")
        shutil.rmtree(STAGE)
    os.makedirs(os.path.dirname(STAGE), exist_ok=True)
    print(f"[runtime] copying {src_root} → {STAGE} ...")
    shutil.copytree(src_root, STAGE)
    staged_py = os.path.join(STAGE, os.path.basename(source_python))
    if not os.path.isfile(staged_py):
        raise RuntimeError(f"复制后未找到解释器: {staged_py}")
    return staged_py


def install_deps(staged_python: str) -> None:
    """离线安装依赖（按**运行时子集** requirements.runtime.txt 装进镜像 site-packages）。"""
    if not os.path.isfile(REQUIREMENTS_RUNTIME):
        raise RuntimeError(
            f"缺少 {REQUIREMENTS_RUNTIME} — 先运行 collect_wheels.py"
        )
    result = _run([
        "uv", "pip", "install",
        "--python", staged_python,
        "--no-index",
        "--find-links", WHEELS,
        "-r", REQUIREMENTS_RUNTIME,
    ])
    if result.returncode != 0:
        print(result.stdout[-4000:] if result.stdout else "")
        print(result.stderr[-4000:] if result.stderr else "")
        raise RuntimeError("uv pip install 失败")


def _dir_size(path: str) -> int:
    total = 0
    for dp, _dn, fn in os.walk(path):
        for f in fn:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total


def trim_image() -> None:
    """删 Lib/test、Doc 与全部 *.pdb（运行时不需要的小型发行版内容）。"""
    for rel in _TRIM_DIRS:
        p = os.path.join(STAGE, rel)
        if os.path.isdir(p):
            size = _dir_size(p)
            shutil.rmtree(p)
            print(f"[runtime] trimmed {rel} ({size / (1 << 20):.0f} MiB)")

    pdb_count = 0
    pdb_bytes = 0
    for dp, _dn, fn in os.walk(STAGE):
        for f in fn:
            if f.lower().endswith(".pdb"):
                fp = os.path.join(dp, f)
                try:
                    pdb_bytes += os.path.getsize(fp)
                    os.remove(fp)
                    pdb_count += 1
                except OSError:
                    pass
    print(f"[runtime] trimmed {pdb_count} *.pdb files ({pdb_bytes / (1 << 20):.0f} MiB)")


def check_editor_only(staged_python: str) -> None:
    """断言编辑器专用包不在镜像中（导出运行时子集契约）。"""
    code = (
        "import importlib.util as u;"
        "print('absent' if u.find_spec('imgui_bundle') is None and u.find_spec('mcp') is None else 'present')"
    )
    result = _run([staged_python, "-c", code])
    verdict = (result.stdout or "").strip().splitlines()[-1] if result.stdout else ""
    ok = verdict == "absent"
    print(f"[runtime] editor-only excluded: {ok}")
    if not ok:
        raise RuntimeError("imgui_bundle/mcp 仍在镜像中 — 检查 requirements.runtime.txt")


def smoke(staged_python: str) -> None:
    """冒烟自检: 核心依赖可导入 + free-threading 状态。"""
    code = (
        "import sys;"
        "print('version:', sys.version.split()[0]);"
        "mods = ['numpy','glfw','esper','cffi','PIL','serial',"
        "'OpenGL','multipledispatch','trimesh'];"
        "[__import__(m) for m in mods];"
        "print('imports OK:', len(mods));"
        "print('GIL enabled:', getattr(sys, '_is_gil_enabled', lambda: 'n/a')())"
    )
    result = _run([staged_python, "-Xgil=0", "-c", code])
    print(result.stdout or "")
    if result.returncode != 0:
        print(result.stderr or "")
        raise RuntimeError("runtime 冒烟自检失败")


def main() -> int:
    print("=" * 60)
    print("prepare_runtime — Resource/runtime")
    print("=" * 60)
    try:
        managed_py = find_managed_python()
        staged_py = stage_runtime(managed_py)
        install_deps(staged_py)
        trim_image()
        smoke(staged_py)
        check_editor_only(staged_py)
    except RuntimeError as e:
        print(f"[ERROR] {e}")
        return 1

    total = sum(
        os.path.getsize(os.path.join(dp, f))
        for dp, _dn, fn in os.walk(STAGE)
        for f in fn
    )
    print("=" * 60)
    print(f"[runtime] image ready: {STAGE}  ({total / (1 << 20):.0f} MiB)")
    print("[runtime] COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
