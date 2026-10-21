"""
Game Export 游戏层 — 无头测试。

链路: EmptyGame 夹具 → ProjectManager.open_project → export_project_bundle(include_player=True)
断言: 包结构（game.json / run_game.cmd / 引擎副本 / Resource 排除项 / wheelhouse / runtime 动态）
      + manifest "game" 段 + 覆盖保护行为保持

前置: Resource/wheels 已由 collect_wheels 收集; Resource/runtime 若已 prepare_runtime
      则一并断言 runtime/python.exe 存在（缺失时不失败, 记信息）。

用法:
    .venv-py314t\\Scripts\\python.exe Test/Application/Editor/test_export_game_bundle.py
"""

# TIER: core

from __future__ import annotations

import json
import os
import shutil
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

ROOT = os.path.dirname(_d)
FIXTURE_DIR = os.path.join(ROOT, "Test", "TestProject", "EmptyGame")
PROJECT = os.path.join(FIXTURE_DIR, "EmptyGame.myproj")
DIST_PARENT = os.path.join(FIXTURE_DIR, "dist")
OUT = os.path.join(DIST_PARENT, "EmptyGame")

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def main() -> int:
    print("=" * 60)
    print("Game Export — Headless Tests")
    print("=" * 60)

    # ── 引导（模拟编辑器上下文的必要子集）──
    from Application.Core.Engine import Engine
    from Application.Core.Scene.SceneManager import SceneManager
    from Application.Resource.ResourceManager import ResourceManager

    ResourceManager.Init(Engine)

    # NodeCanvas 契约注册（场景 node_graph 水合必需）
    import Application.Core.NodeGraph.canvas  # noqa: F401

    # 编辑器场景管理器（open_project 激活场景时需要有宿主的 SceneManager）
    SceneManager.Init(Engine)
    from Application.Editor.EditorHost import EditorHost

    SceneManager.Init(EditorHost)
    EditorHost.scene = SceneManager._state_for("EditorHost")

    # ── 打开工程 ──
    print("── Open project ──")
    from Application.Editor.ProjectManager import ProjectManager

    ok = ProjectManager.open_project(PROJECT)
    check("open_project returns True", ok)
    if not ok:
        check("abort", False, "open_project failed — see warnings above")
        return 1

    # ── 导出（先清掉上次测试产物 + 旧导出以测可用性）──
    print("── Export ──")
    os.makedirs(DIST_PARENT, exist_ok=True)
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    summary = ProjectManager.export_project_bundle(DIST_PARENT)
    check("export returns summary", summary is not None)
    if not summary:
        return 1

    game = summary.get("game")
    check("summary has game layer", isinstance(game, dict))

    def exists(rel: str) -> bool:
        return os.path.isfile(os.path.join(OUT, rel))

    # ── 结构断言 ──
    print("── Bundle structure ──")
    for rel in ("game.json", "run_game.cmd", "EmptyGame.myproj",
                "export_manifest.json", "scenes/Main.scene", "THIRD_PARTY_NOTICES.md",
                "Application/PlayerEntry.py", "Application/Runtime/PlayerBootstrap.py",
                "Application/Core/Project/RuntimeProjectLoader.py",
                "Resource/Fonts", "wheelhouse/requirements.export.txt",
                "Utils/User/player.bat"):
        check(f"has {rel}", os.path.exists(os.path.join(OUT, rel)))

    utils_out = os.path.join(OUT, "Utils")
    utils_top = ({e for e in os.listdir(utils_out) if e != "__pycache__"}
                 if os.path.isdir(utils_out) else set())
    check("bundle Utils/ top-level only User layer (dev toolchain excluded)",
          not (utils_top - {"User", "__init__.py"}), f"actual: {sorted(utils_top)}")

    check("Resource/wheels NOT inside engine Resource",
          not os.path.isdir(os.path.join(OUT, "Resource", "wheels")))
    check("Resource/runtime NOT inside engine Resource",
          not os.path.isdir(os.path.join(OUT, "Resource", "runtime")))

    runtime_src_exists = os.path.isdir(os.path.join(ROOT, "Resource", "runtime"))
    rt_py = [n for n in ("python3.14t.exe", "python.exe")
             if os.path.isfile(os.path.join(OUT, "runtime", n))]
    if runtime_src_exists:
        check(f"runtime bundled ({rt_py or 'NO EXE'})", bool(rt_py))
    else:
        print("  [info] Resource/runtime not prepared yet — runtime bundling skipped")

    # ── game.json / manifest 内容 ──
    print("── Manifests ──")
    with open(os.path.join(OUT, "game.json"), "r", encoding="utf-8") as fh:
        game_cfg = json.load(fh)
    check("game.json project = EmptyGame.myproj", game_cfg.get("project") == "EmptyGame.myproj")
    check("game.json startup = scenes/Main.scene", game_cfg.get("startup_scene") == "scenes/Main.scene")

    with open(os.path.join(OUT, "export_manifest.json"), "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    check("manifest has game section", isinstance(manifest.get("game"), dict))
    check("manifest status", manifest.get("status") != "in_progress")

    # run_game.cmd 保持 ASCII（代码页安全）
    with open(os.path.join(OUT, "run_game.cmd"), "rb") as fh:
        raw = fh.read()
    check("run_game.cmd is ASCII", all(b < 128 for b in raw))

    # ── include_player=False: 纯工程包（独立目标） ──
    print("── include_player=False ──")
    no_player_parent = os.path.join(DIST_PARENT, "noplayer")
    os.makedirs(no_player_parent, exist_ok=True)
    if os.path.isdir(os.path.join(no_player_parent, "EmptyGame")):
        shutil.rmtree(os.path.join(no_player_parent, "EmptyGame"))
    summary_np = ProjectManager.export_project_bundle(no_player_parent, include_player=False)
    check("no-player export returns summary", summary_np is not None)
    check("no-player export has game=None",
          summary_np is not None and summary_np.get("game") is None)
    check("no-player export has no game.json",
          not os.path.isfile(os.path.join(no_player_parent, "EmptyGame", "game.json")))
    check("no-player export still has project file",
          os.path.isfile(os.path.join(no_player_parent, "EmptyGame", "EmptyGame.myproj")))

    # ── 覆盖行为: 再次导出 → 干净重建（陈旧文件清除, output/ 保留）──
    print("── Overwrite / clean rebuild ──")
    stale = os.path.join(OUT, "stale_marker.txt")
    with open(stale, "w", encoding="utf-8") as fh:
        fh.write("leftover from previous export")
    keep = os.path.join(OUT, "output", "keep_me.txt")
    os.makedirs(os.path.dirname(keep), exist_ok=True)
    with open(keep, "w", encoding="utf-8") as fh:
        fh.write("experiment data")
    probe_dir = next(iter(sorted(ProjectManager._export_excluded_paths(ROOT))), None)
    probe = os.path.join(probe_dir, "_export_probe.txt") if probe_dir else ""
    probe_rel = (os.path.relpath(probe_dir, ROOT).replace("\\", "/")
                 if probe_dir else "")
    probe_made = False
    if probe_dir and os.path.isdir(probe_dir):
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("must not be exported")
        probe_made = True
    summary2 = ProjectManager.export_project_bundle(DIST_PARENT)
    check("re-export succeeds", summary2 is not None)
    check("re-export keeps game layer", summary2 is not None and isinstance(summary2.get("game"), dict))
    check("game.json still present after re-export", exists("game.json"))
    check("stale file removed on re-export", not os.path.isfile(stale))
    check("output/ preserved on re-export", os.path.isfile(keep))
    if probe_made:
        check("export:false extension is not copied",
              not os.path.isfile(os.path.join(OUT, probe_rel, "_export_probe.txt")))
        excluded = (summary2 or {}).get("export_excluded") or []
        check("manifest records export:false extension",
              any(str(p).replace("\\", "/").endswith(probe_rel) for p in excluded),
              str(excluded))
        os.remove(probe)

    print()
    print("=" * 60)
    total = _RESULTS["pass"] + _RESULTS["fail"]
    print(f"Results: {_RESULTS['pass']}/{total} passed, {_RESULTS['fail']} failed")
    if _RESULTS["fail"] == 0:
        print("ALL TESTS PASSED")
        return 0
    print("TESTS FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
