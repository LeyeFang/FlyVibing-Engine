"""
E2E: 项目导入 → 场景切换 → 画布干跑校验（引擎内服务）— 目标驱动验收。

流程:
  1. project.open  Paradigm 的 MI-SSSEP 工程（资源 + 场景全加载）
  2. scene.switch  "MI-SSSEP" 场景
  3. graph.list    画布快照规模
  4. editor_graph_validate(source="canvas", 360 帧) → 静态 + 干跑报告（落盘 .txt）
  5. graph.export / graph.import 回灌（roundtrip 验证导入导出链路）
  6. editor.quit（--keep-open 可保留）

用法（需 startup.bat 运行中）:
    .venv-py314t\\Scripts\\python.exe Test/Application/Editor/e2e_mcp_validate_mi_sssep.py [--keep-open]
"""

from __future__ import annotations

import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

ROOT = os.path.dirname(_d)

from engine_editor_mcp import mcp_server as m  # noqa: E402

PROJECT = r"C:\WorkSpace\FLY\MI-SSSEP\Experiment\Paradigm\project\MI-SSSEP\MI-SSSEP.myproj"
SCENE = "MI-SSSEP"
TMP = os.path.join(ROOT, "Utils", "ExtDev", "EditorMcp", "tmp")

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def main() -> int:
    keep_open = "--keep-open" in sys.argv
    print("=" * 62)
    print("  E2E: project → scene → graph validate (MI-SSSEP)")
    print("=" * 62)

    # ── 1. 打开工程 ──
    r = m._send("project.open", {"path": PROJECT}, timeout=120.0)
    check("project.open ok", "error" not in r and r.get("opened") is True, str(r)[:220])
    scenes = r.get("scenes") or []
    print(f"  project={r.get('name')}  scenes={scenes}  active={r.get('active')}")
    check(f"scenes loaded ({len(scenes)})", len(scenes) >= 4, str(scenes))
    check("'MI-SSSEP' in scenes", SCENE in scenes, str(scenes))

    # ── 2. 切场景 ──
    r = m._send("scene.switch", {"name": SCENE}, timeout=60.0)
    check("scene.switch ok", "error" not in r and r.get("switched") is True, str(r))
    check("active == MI-SSSEP", str(r.get("active") or "") == SCENE, str(r))

    # ── 3. 画布快照 ──
    r = m._send("graph.list")
    n_nodes = len(r.get("nodes") or [])
    n_links = len(r.get("links") or [])
    check(f"graph.list ok ({n_nodes} nodes, {n_links} links)", n_nodes > 0)

    # ── 4. 干跑校验（阻塞编排: start → poll → report）──
    report_txt = os.path.join(TMP, "validation_mi_sssep.txt")
    r = m.editor_graph_validate(source="canvas", frames=360, save_path=report_txt, timeout_s=180.0)
    rep = r.get("report") or {}
    check("validate pipeline ok", "error" not in r and bool(rep), str(r)[:300])

    static = rep.get("static") or {}
    runtime = rep.get("runtime") or {}
    counts = rep.get("counts") or {}
    print(
        f"  static: {len(static.get('errors') or [])}E / {len(static.get('warnings') or [])}W · "
        f"runtime: {len(runtime.get('errors') or [])}E · "
        f"frames={runtime.get('frames_simulated')} events={runtime.get('total_events')} · "
        f"{rep.get('timing', {}).get('duration_ms')} ms"
    )
    for e in (static.get("errors") or [])[:10]:
        print(f"    ✗ [s] {e.get('message')}")
    for e in (static.get("warnings") or [])[:5]:
        print(f"    ⚠ [s] {e.get('message')}")
    for e in (runtime.get("errors") or [])[:5]:
        print(f"    ✗ [r] {e}")

    check("report file saved", os.path.isfile(report_txt), report_txt)
    check("validation ok=True", rep.get("ok") is True, f"counts={counts}")

    # ── 5. 导出 / 回灌 roundtrip ──
    exp_path = os.path.join(TMP, "exported_mi_sssep_graph.json")
    r = m._send("graph.export", {"path": exp_path}, timeout=30.0)
    check("graph.export saved", "error" not in r and os.path.isfile(exp_path), str(r)[:200])
    before = (r.get("nodes"), r.get("links"))

    r = m._send("graph.import", {"path": exp_path, "validate_first": True}, timeout=60.0)
    check("graph.import roundtrip", "error" not in r and r.get("imported") is True, str(r)[:200])
    check("import counts match", (r.get("nodes"), r.get("links")) == before,
          f"before={before} after={(r.get('nodes'), r.get('links'))}")

    r = m._send("graph.list")
    check("canvas intact after import", len(r.get("nodes") or []) == before[0],
          f"nodes={len(r.get('nodes') or [])}")

    # ── 6. 收尾 ──
    total = _RESULTS["pass"] + _RESULTS["fail"]
    print("-" * 62)
    print(f"RESULT: {'OK' if _RESULTS['fail'] == 0 else 'FAIL'} "
          f"({_RESULTS['pass']}/{total})")
    if not keep_open:
        m._send("editor.quit")
        print("  editor.quit sent")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
