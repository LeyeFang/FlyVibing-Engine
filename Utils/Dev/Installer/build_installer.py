"""
build_installer.py — FlyVibingEngine 离线安装包构建（staging + Inno Setup 编译）。

流程:
  1. 校验 Resource/runtime/python3.14t.exe 存在（缺失 → 先运行 Utils/Dev/prepare_runtime.py）
  2. staging → Utils/Dev/Installer/build/stage
       - 引擎树: Application/ Resource/ Doc/ Utils/User/ startup.bat（排除 __pycache__ 等;
         Application/Functions 仅保留 official_extensions.json allowlist;
         Application/Editor/Config 本地状态不进包; Dev 工具链不进安装包）
       - 引擎依赖补齐: pip --no-index -r Resource/wheels/requirements.export.txt
         --target <stage>/Resource/runtime/Lib/site-packages（安装版 = 开发版环境）
       - 独立包: FlyVibing-User-And-Developer-Utils/packages/editor-mcp/src/engine_editor_mcp → runtime site-packages
       - 启动器: <stage>/engine-editor-mcp.cmd（PATH 注册后可供 agent 工作区直接调用）
  3. ISCC 编译 installer.iss → Utils/Dev/Installer/dist/build/FlyVibingEngine-Setup-<ver>-Windows-x64.exe
   （再执行 package_release.py 进入 dist/releases/v<ver>/windows-x64/）

用法:
  .venv-py314t\\Scripts\\python.exe Utils/Dev/Installer/build_installer.py [--skip-runtime] [--no-compile] [--keep-stage]

参数:
  --skip-runtime  快速布局验证（stage 不含 runtime; 产出的安装包不可运行 — 仅调试用）
  --no-compile    只做 staging, 不调用 ISCC
  --keep-stage    保留已有 build/stage（增量, 不先清空）
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess

from release_layout import ARCH, BUILD_DIR, PLATFORM, installer_name

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
BUILD = os.path.join(HERE, "build")
STAGE = os.path.join(BUILD, "stage")
ISS = os.path.join(HERE, "installer.iss")
VENV_PY = os.path.join(ROOT, ".venv-py314t", "Scripts", "python.exe")
WHEELS = os.path.join(ROOT, "Resource", "wheels")
RUNTIME = os.path.join(ROOT, "Resource", "runtime")

_SKIP_DIRS = {"__pycache__", ".git", ".venv-py314t", ".vscode", "build", "dist", "tmp"}
_SKIP_SUFFIX = (".pyc", ".pyo")
_OFFICIAL_MANIFEST = "official_extensions.json"

# 编辑器本地状态（git-ignored；扩展启用表、PIE/UI 布局、插件数据）不进安装包。
# 与 Application/Editor/ProjectManager.LOCAL_STATE_DIRS 保持同一契约；
# 守卫: Test/Application/Editor/test_release_layout.py。
_LOCAL_STATE_DIRS = ("Application/Editor/Config",)


def _version() -> str:
    import tomllib

    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as fh:
        data = tomllib.load(fh)
    return str(data["project"]["version"])


def _copy_tree(src: str, dst: str, skip_top: tuple[str, ...] = (),
               exclude_paths: set[str] | None = None) -> None:
    blocked = {os.path.normcase(os.path.abspath(p)) for p in (exclude_paths or ())}
    for base, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS
                   and os.path.normcase(os.path.abspath(os.path.join(base, d))) not in blocked]
        if base == src and skip_top:
            dirs[:] = [d for d in dirs if d not in skip_top]
        rel = os.path.relpath(base, src)
        out = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(out, exist_ok=True)
        for fname in files:
            if fname.endswith(_SKIP_SUFFIX):
                continue
            shutil.copy2(os.path.join(base, fname), os.path.join(out, fname))


def _official_extension_dirs(functions_root: str) -> set[str]:
    """读取 mainline allowlist，返回允许进入安装包的扩展目录（绝对路径）。

    安装包是版权边界更严格的发行物：只允许 `Application/Functions` 下
    `official_extensions.json` 明确列出的官方扩展。`export:false` 只控制
    游戏导出，不在这里生效（官方扩展可能对 game 关闭但仍是主线安装包的一部分）。
    """
    manifest = os.path.join(functions_root, _OFFICIAL_MANIFEST)
    if not os.path.isfile(manifest):
        raise RuntimeError(
            f"installer allowlist missing: {manifest} "
            "(mainline installer must not fall back to scanning local extensions)"
        )
    try:
        with open(manifest, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"installer allowlist unreadable: {manifest}: {exc}") from exc

    entries = data.get("extensions") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        raise RuntimeError(f"installer allowlist has no extensions: {manifest}")

    base = os.path.abspath(functions_root)
    official: set[str] = set()
    for entry in entries:
        dir_name = str((entry or {}).get("dir") or "").strip() if isinstance(entry, dict) else ""
        ext_id = str((entry or {}).get("id") or "").strip() if isinstance(entry, dict) else ""
        if not dir_name or not ext_id:
            raise RuntimeError(f"installer allowlist entry requires id+dir: {entry!r}")
        directory = os.path.abspath(os.path.join(base, dir_name))
        try:
            if os.path.commonpath([directory, base]) != base:
                raise ValueError("path escapes Functions")
        except ValueError as exc:
            raise RuntimeError(f"installer allowlist path escapes Functions: {dir_name}") from exc
        ext_manifest = os.path.join(directory, "extension.json")
        if not os.path.isfile(ext_manifest):
            raise RuntimeError(f"official extension missing manifest: {ext_manifest}")
        try:
            with open(ext_manifest, "r", encoding="utf-8") as fh:
                actual = str(json.load(fh).get("id") or "")
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"official extension manifest unreadable: {ext_manifest}: {exc}") from exc
        if actual != ext_id:
            raise RuntimeError(
                f"official extension id mismatch: {dir_name} declares {actual!r}, "
                f"allowlist wants {ext_id!r}"
            )
        official.add(directory)
    return official


def _nonofficial_extension_dirs(functions_root: str) -> set[str]:
    """返回不在 mainline allowlist 内的顶层扩展目录（安装包 staging 必须排除）。"""
    official = _official_extension_dirs(functions_root)
    base = os.path.abspath(functions_root)
    blocked: set[str] = set()
    if not os.path.isdir(base):
        return blocked
    for name in os.listdir(base):
        path = os.path.abspath(os.path.join(base, name))
        if os.path.isdir(path) and path not in official:
            blocked.add(path)
    return blocked


def _stage_engine_tree(skip_runtime: bool) -> None:
    # Application/Doc/Utils 完全由源树生成 — 即使 --keep-stage 也先清空，
    # 避免旧插件/已删除文件残留进安装包。安装包只允许 mainline allowlist 中的官方扩展；
    # `export:false` 只属于游戏导出语义，不在这里“错杀”官方扩展。
    for item in ("Application", "Doc", "Utils"):
        dst = os.path.join(STAGE, item)
        if os.path.isdir(dst):
            shutil.rmtree(dst)
    installer_blocked = _nonofficial_extension_dirs(
        os.path.join(ROOT, "Application", "Functions"))
    local_state = {os.path.abspath(os.path.join(ROOT, *rel.split("/")))
                   for rel in _LOCAL_STATE_DIRS}
    app_blocked = installer_blocked | local_state
    for item in ("Application", "Resource", "Doc", "Examples"):
        src = os.path.join(ROOT, item)
        skip_top = ("runtime",) if (skip_runtime and item == "Resource") else ()
        _copy_tree(src, os.path.join(STAGE, item), skip_top=skip_top,
                   exclude_paths=app_blocked if item == "Application" else None)
    # Utils: 安装版只收 User 层（Dev 工具链 = 开发者专用, 不进产品）
    utils_src = os.path.join(ROOT, "Utils")
    _copy_tree(os.path.join(utils_src, "User"), os.path.join(STAGE, "Utils", "User"))
    shutil.copy2(os.path.join(utils_src, "__init__.py"),
                 os.path.join(STAGE, "Utils", "__init__.py"))
    shutil.copy2(os.path.join(ROOT, "startup.bat"), os.path.join(STAGE, "startup.bat"))
    for name in ("LICENSE", "README.md", "CHANGELOG.md", "THIRD_PARTY_NOTICES.md"):
        src = os.path.join(ROOT, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(STAGE, name))


def _install_engine_deps() -> None:
    """把开发环境全量依赖（离线 wheelhouse）装进 staged runtime。"""
    site_packages = os.path.join(STAGE, "Resource", "runtime", "Lib", "site-packages")
    requirements = os.path.join(WHEELS, "requirements.export.txt")
    if not os.path.isfile(requirements):
        raise SystemExit(f"requirements not found: {requirements}")
    cmd = [
        VENV_PY, "-m", "pip", "install", "--quiet", "--no-index",
        "--find-links", WHEELS,
        "--target", site_packages,
        "--upgrade",
        "-r", requirements,
    ]
    print("[installer] pip install --target <stage runtime> -r requirements.export.txt ...")
    subprocess.run(cmd, check=True)


def _install_editor_mcp() -> None:
    """工具链 wheel → staged runtime site-packages + PATH 启动器。

    优先使用同级工具仓 dist/ 的最新 wheel；工具仓不在时回退到历史内嵌
    source，保证单仓 checkout 也能做布局验证。
    """
    site_packages = os.path.join(STAGE, "Resource", "runtime", "Lib", "site-packages")
    tools_dist = os.path.join(os.path.dirname(ROOT),
                              "FlyVibing-User-And-Developer-Utils", "dist")
    installed: list[str] = []
    if os.path.isdir(tools_dist):
        for pattern in ("engine_editor_mcp-*.whl", "flyvibing_node_editor-*.whl"):
            wheels = sorted(glob.glob(os.path.join(tools_dist, pattern)))
            if not wheels:
                continue
            wheel = wheels[-1]
            print(f"[installer] install {os.path.basename(wheel)} -> staged runtime")
            subprocess.run([VENV_PY, "-m", "pip", "install", "--quiet", "--no-deps",
                            "--target", site_packages, "--upgrade", wheel], check=True)
            installed.append(os.path.basename(wheel))
    if not installed:
        src = os.path.join(ROOT, "Utils", "ExtDev", "EditorMcp", "src", "engine_editor_mcp")
        dst = os.path.join(site_packages, "engine_editor_mcp")
        shutil.copytree(src, dst, dirs_exist_ok=True)
        print("[installer] WARNING: toolchain wheels not found; used embedded engine_editor_mcp")
    cmd_path = os.path.join(STAGE, "engine-editor-mcp.cmd")
    with open(cmd_path, "w", encoding="ascii", newline="") as fh:
        fh.write("@echo off\r\n"
                 "set \"PYEXE=%~dp0Resource\\runtime\\python3.14t.exe\"\r\n"
                 "if not exist \"%PYEXE%\" set \"PYEXE=%~dp0Resource\\runtime\\python.exe\"\r\n"
                 "\"%PYEXE%\" -m engine_editor_mcp %*\r\n")
    print("[installer] editor MCP + node editor toolchain staged", installed)


def _write_quickstart(version: str) -> None:
    text = (
        "FlyVibingEngine - Quick Start\r\n"
        "==========================\r\n"
        f"Version: {version}\r\n"
        "\r\n"
        "1) Launch the editor: double-click startup.bat (or the Start menu shortcut).\r\n"
        "2) Projects: use File > Open Project (.myproj), or File > Open Example\r\n"
        "   for the bundled MI / RestingState examples under Examples/.\r\n"
        "3) AI agent (MCP): while the editor is running, register in your agent workspace\r\n"
        "   .vscode/mcp.json:\r\n"
        "     { \"servers\": { \"engine-editor-live\": {\r\n"
        "         \"type\": \"stdio\", \"command\": \"engine-editor-mcp\" } } }\r\n"
        "   (engine-editor-mcp.cmd lives in the install folder; enable the PATH task\r\n"
        "    or use its absolute path.)\r\n"
        "Docs: Doc\\User\\editor_mcp_guide.md  |  Doc\\Dev\\*.md\r\n"
    )
    with open(os.path.join(STAGE, "README-INSTALL.txt"), "w", encoding="ascii", newline="") as fh:
        fh.write(text)


def _find_iscc() -> str | None:
    candidates = [
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     "Inno Setup 6", "ISCC.exe"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                     "Inno Setup 6", "ISCC.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
    ]
    which = shutil.which("ISCC")
    if which:
        candidates.insert(0, which)
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the FlyVibingEngine offline installer")
    parser.add_argument("--skip-runtime", action="store_true",
                        help="layout test only (no bundled runtime in the package)")
    parser.add_argument("--no-compile", action="store_true", help="stage only, skip ISCC")
    parser.add_argument("--keep-stage", action="store_true", help="reuse existing build/stage")
    args = parser.parse_args()

    version = _version()
    print(f"[installer] engine version: {version}")

    if not args.skip_runtime:
        runtime_py = os.path.join(RUNTIME, "python3.14t.exe")
        if not os.path.isfile(runtime_py):
            print(f"[installer] ERROR: bundled runtime (3.14t) missing: {runtime_py}")
            print("  prepare it first: .venv-py314t\\Scripts\\python.exe Utils/Dev/prepare_runtime.py")
            print("  (wheelhouse required — wheels are not in git: run Utils/Dev/collect_wheels.py)")
            return 2

    if os.path.isdir(BUILD) and not args.keep_stage:
        shutil.rmtree(BUILD)
    os.makedirs(STAGE, exist_ok=True)

    print("[installer] staging engine tree ...")
    _stage_engine_tree(args.skip_runtime)

    if args.skip_runtime:
        print("[installer] (skip-runtime) runtime excluded from stage")
    else:
        _install_engine_deps()
        _install_editor_mcp()

    _write_quickstart(version)

    if args.no_compile:
        print(f"[installer] stage ready: {STAGE}")
        return 0

    iscc = _find_iscc()
    if not iscc:
        print("[installer] WARNING: ISCC.exe (Inno Setup 6) not found — stage is ready, compile skipped.")
        print("  install Inno Setup then re-run:  winget install -e --id JRSoftware.InnoSetup")
        return 3

    os.makedirs(BUILD_DIR, exist_ok=True)
    print(f"[installer] compiling with {iscc} ...")
    subprocess.run(
        [iscc, f"/DStageDir={STAGE}", f"/DAppVersion={version}",
         f"/DPlatformTag={PLATFORM}-{ARCH}", f"/DOutputDir={BUILD_DIR}", ISS],
        check=True,
    )
    exe = os.path.join(BUILD_DIR, installer_name(version))
    if os.path.isfile(exe):
        print(f"[installer] DONE: {exe}  ({os.path.getsize(exe) / 1e6:.0f} MB)")
        return 0
    print("[installer] ERROR: expected output not found")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
