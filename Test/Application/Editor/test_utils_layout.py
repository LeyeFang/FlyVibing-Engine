"""
Utils 布局守卫 — 「引擎仓库只留引擎研发工具」+「使用侧工具链在独立仓库」（无头）。

两仓分工（2026-10-13/14 落地）:
    引擎仓库 Utils/Dev      引擎研发：环境/测试/打包/安装器（不发布）
    引擎仓库 Utils/User     随成品走：player.bat 等运行时辅助（导出游戏只带这一层）
    工具仓库 FlyVibing-User-And-Developer-Utils
                            引擎使用侧：editor-mcp / node-editor / extension-kit + skills
                            （实验设计者、扩展开发者、以及引擎团队自己都用它）

锁定:
  1. `Utils/` 顶层只有 Dev / User（+ `__init__.py` / `README.md`）——工具目录不得回迁
  2. `Utils/User/**` 登记制白名单（加文件要登记用途）
  3. 全仓源码/文档无 `Utils/ExtDev`、`Utils.ExtDev` 残留（引用应指向工具包名或工具仓库）
  4. 导出卫生: `Utils/User` 下 `dist/` / `tmp/` / `__pycache__` 不进游戏包（真调导出函数验证）
  5. 工具仓库可见时: `.github/skills/**`（引擎本地 agent 用）与工具仓库 `skills/**` 逐字节一致

运行: python Utils/Dev/test_runner.py --only utils_layout
"""
# TIER: core

from __future__ import annotations

import os
import shutil
import sys
import tempfile

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "startup.bat")):
    _d = os.path.dirname(_d)
_ROOT = _d or ""
if _ROOT:
    sys.path.insert(0, _ROOT)

from Application.Editor.ProjectManager import (                     # noqa: E402
    UTILS_EXPORT_SKIP_DIRS, ProjectManager)

_RESULTS = {"pass": 0, "fail": 0}
_TOOLS_ENV = "FLYVIBING_UTILS_DIR"
_TOOLS_DEFAULT = os.path.join(os.path.dirname(_ROOT), "FlyVibing-User-And-Developer-Utils")

UTILS_TOP_ALLOWED = {"Dev", "User", "ExtDev", "__init__.py", "README.md", "__pycache__"}
USER_ALLOWED_FILES = {
    "__init__.py": "包标识",
    "player.bat": "成品游戏的启动脚本（实验员入口）",
}
_PRUNE_DIRS = {"__pycache__", "dist", "tmp", "build", "stage", "_runs", "site-packages"}
_SCAN_TREES = ("Application", "Utils", "Doc", ".github", "Test")
_FORBIDDEN = ("Utils/ExtDev", "Utils\\ExtDev", "Utils.ExtDev")
_SKILL_PAIRS = (("engine-editor", "engine-editor"), ("node-graph", "node-graph"))


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _tools_dir() -> str | None:
    cand = os.environ.get(_TOOLS_ENV) or _TOOLS_DEFAULT
    return cand if os.path.isdir(os.path.join(cand, "skills")) else None


def _iter_text(exts: tuple[str, ...]):
    for top in _SCAN_TREES:
        base = os.path.join(_ROOT, *top.split("/"))
        for dp, dn, fn in os.walk(base):
            if any(part in _PRUNE_DIRS for part in dp.split(os.sep)):
                dn[:] = []
                continue
            for f in fn:
                if f.endswith(exts):
                    yield os.path.join(dp, f)


def main() -> int:
    print("=" * 60)
    print("Utils layout guard — engine repo vs tools repo")
    print("=" * 60)

    # ── 1. 引擎仓库只留 Dev / User ────────────────────────────
    print("-- 1. Utils/ top level --")
    top = {e for e in os.listdir(os.path.join(_ROOT, "Utils")) if e != "__pycache__"}
    check("顶层只有 Dev / User（+ __init__.py / README.md）",
          not (top - UTILS_TOP_ALLOWED), f"unexpected: {sorted(top - UTILS_TOP_ALLOWED)}")

    user_dir = os.path.join(_ROOT, "Utils", "User")
    actual_user = set()
    for dp, dn, fn in os.walk(user_dir):
        dn[:] = [d for d in dn if d not in _PRUNE_DIRS]
        for f in fn:
            actual_user.add(os.path.relpath(os.path.join(dp, f), user_dir).replace(os.sep, "/"))
    check("Utils/User 文件均在登记表内",
          not (actual_user - set(USER_ALLOWED_FILES)),
          f"未登记: {sorted(actual_user - set(USER_ALLOWED_FILES))}")
    check("player.bat 仍在（成品入口没丢）", "player.bat" in actual_user)

    # ── 2. 工具目录不得回迁 ──────────────────────────────────
    print("-- 2. toolchain stays external --")
    extdev = os.path.join(_ROOT, "Utils", "ExtDev")
    if os.path.exists(extdev):
        # 允许“开发链接”（junction/symlink 指向工具仓库）—— 禁止真目录回迁。
        # 判定用哨兵文件（Windows junction 的 realpath 不解析，别靠路径字符串）。
        sentinels = ("EditorMcp/src/engine_editor_mcp/server.py",
                     "NodeEditor/graph_builder.py",
                     "ExtensionKit/review_extension.py")
        missing = [s for s in sentinels
                   if not os.path.isfile(os.path.join(extdev, *s.split("/")))]
        check("Utils/ExtDev 指向工具仓库（哨兵文件可见）", not missing, f"missing={missing}")
        gitignore = open(os.path.join(_ROOT, ".gitignore"),
                         encoding="utf-8", errors="ignore").read()
        check("Utils/ExtDev/ 已进 .gitignore（链接内容不会被误提交）", "Utils/ExtDev/" in gitignore)
    else:
        check("Utils/ExtDev 不存在（或为开发链接）", True)
    offenders: list[str] = []
    _self = os.path.abspath(__file__)
    for path in _iter_text((".py", ".bat", ".json", ".toml", ".iss")):
        if os.path.abspath(path) == _self:
            continue                    # 本守卫自己会写这些禁词（政策定义处）
        if os.sep + "_runs" + os.sep in path:
            continue
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        if any(tok in text for tok in _FORBIDDEN):
            offenders.append(os.path.relpath(path, _ROOT))
    check("代码/脚本里无 Utils/ExtDev 硬路径（应指向工具仓库或包名）", not offenders,
          f"{offenders[:3]}（文档正文可以提及该词 —— 只扫代码）")
    utils_readme = os.path.join(_ROOT, "Utils", "README.md")
    pointer = ""
    if os.path.isfile(utils_readme):
        pointer = open(utils_readme, encoding="utf-8").read()
    check("Utils/README.md 指向工具仓库",
          "FlyVibing-User-And-Developer-Utils" in pointer)

    # ── 3. 导出卫生（行为验证）───────────────────────────────
    print("-- 3. export hygiene --")
    check("UTILS_EXPORT_SKIP_DIRS 覆盖 dist/tmp",
          {"dist", "tmp"} <= set(UTILS_EXPORT_SKIP_DIRS), str(UTILS_EXPORT_SKIP_DIRS))
    sandbox = tempfile.mkdtemp(prefix="utils_export_")
    src = os.path.join(sandbox, "User")
    os.makedirs(os.path.join(src, "dist"))
    os.makedirs(os.path.join(src, "tmp"))
    os.makedirs(os.path.join(src, "__pycache__"))
    for rel in ("player.bat", "dist/engine_x-0.4.0-py3-none-any.whl", "tmp/frame.png",
                "__pycache__/player.cpython-314.pyc"):
        with open(os.path.join(src, rel.replace("/", os.sep)), "w", encoding="utf-8") as fh:
            fh.write("x")
    dst = os.path.join(sandbox, "out")
    ProjectManager._copy_tree_for_export(src, dst, [], exclude_dirs=UTILS_EXPORT_SKIP_DIRS)
    copied = set()
    for _dp, _dn, fn in os.walk(dst):
        for f in fn:
            copied.add(os.path.relpath(os.path.join(dst, f), dst).replace(os.sep, "/"))
    check("导出只带运行时文件（无 whl / png / pyc）", copied == {"player.bat"}, str(sorted(copied)))
    shutil.rmtree(sandbox, ignore_errors=True)

    # ── 4. skills 双副本（工具仓库可见时）────────────────────
    print("-- 4. skills single-source --")
    tools = _tools_dir()
    if tools is None:
        print(f"  [SKIP] 工具仓库不可见（{os.environ.get(_TOOLS_ENV) or _TOOLS_DEFAULT}）"
              f"—— 设 {_TOOLS_ENV} 指向克隆目录后可校验")
    else:
        for name, _pkg in _SKILL_PAIRS:
            a = os.path.join(_ROOT, ".github", "skills", name)
            b = os.path.join(tools, "skills", name)
            drift: list[str] = []
            if not os.path.isdir(a):
                drift.append("引擎副本缺失")
            elif not os.path.isdir(b):
                drift.append("工具仓库副本缺失")
            else:
                for dp, _dn, fn in os.walk(b):
                    for f in fn:
                        bp = os.path.join(dp, f)
                        rel = os.path.relpath(bp, b)
                        ap = os.path.join(a, rel)
                        if not os.path.isfile(ap):
                            drift.append(f"引擎缺 {rel}")
                        elif open(ap, "rb").read() != open(bp, "rb").read():
                            drift.append(f"内容漂移 {rel}")
            check(f"skills/{name} 与工具仓库一致（权威源=工具仓库）", not drift,
                  "; ".join(drift[:2]))

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print("-" * 60)
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
