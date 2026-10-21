"""材质绑定保存循环压力测试 — 在"多材质/多场景/共享引用"的类 MI-SSSEP 工程上
反复执行 open -> (编辑材质) -> save 循环，量化材质引用错绑（串扰）的发生概率。

背景（Paradigm 现场：cue 与 task cue 全变绿）:
  场景文件里的 MeshRenderer.material_id 是"会话活 id 空间"的整数；
  .myproj 的 resources.materials 记录的是"上一次保存时的 id"（重映射基准）。
  两者一旦错位（编辑克隆 / 引擎新增内置材质 / 历史漂移），下一次加载时
  id_map 重映射落空 -> 引用解析到错误材质（或缺失）-> 串扰。

仪器结构（驱动程序在父进程，所有引擎操作在子进程 = 真·跨会话）:
  场景 A `stable`  : 纯净 open/save 循环（无编辑）——测"隐性漂移"是否自愈/恶化
  场景 B `legacy`  : 初始即已漂移（task 引用=3 而非记录 4, 复刻现场）——测自愈
  场景 C `edit`    : 每轮编辑共享材质一个实体（Inspector/MCP 路径, 触发克隆）
  场景 D `shift`   : 第 K 轮起引擎"新增 1 个内置材质"（模拟 DefaultLit 式演进）

判定:
  绑定存活 = 每个哨兵实体解析到的材质名匹配预期家族
             (a*=A 或 A_copy*, task=B 或 B_copy*, cross=Default)
  对齐     = 场景引用的每个活 id 都在 myproj 记录中有条目
             (记录 id == 场景引用 id == 活 id; 编辑克隆会新增记录而非破坏对齐)

预期 (2026-10-15 引擎修复后):
  stable / edit / shift → 0 绑定失败 + 0 漂移 (记录刷新 + 克隆落盘 + 提交点凝固)
  legacy               → 保持损坏 (已污染数据不自愈; 需数据级修复 — 不阻断 RESULT)

用法:
  python Test/Application/stress/test_material_cycle_stress.py [--scale 1.0] [--scenarios stable,legacy,edit,shift]
  内部: 同文件 --worker cycle <workdir> <scenario> <idx> <extra_builtin:0|1>
产物: Test/_runs/mat_cycle_<ts>/<scenario>/  (工作工程 + obs_*.json) + summary.json
"""
# TIER: heavy

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

# ── 路径引导 ──
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: E402

ROOT = os.path.dirname(_d) if _d else ""

# 预期绑定: 实体名 -> 材质名
INTENT = {
    "a1": "A", "a2": "A", "a3": "A",
    "task1": "B", "cross": "Default",
    "s2_a1": "A", "s2_a2": "A", "s2_task": "B",
}
# myproj 记录（与 master MI-SSSEP 同风格: cue=2, task=4）
RECORD_A, RECORD_B = 2, 4


# ════════════════════════════════════════════════════════════════
# 夹具（纯 JSON, 由驱动直接写盘; 格式对齐真实 .scene/.mat）
# ════════════════════════════════════════════════════════════════

def _transform() -> dict:
    return {
        "position_x": 0.0, "position_y": 0.0, "position_z": 0.0,
        "rotation_x": 0.0, "rotation_y": 0.0, "rotation_z": 0.0,
        "scale_x": 1.0, "scale_y": 1.0, "scale_z": 1.0,
        "local_pos_x": 0, "local_pos_y": 0, "local_pos_z": 0,
        "local_rot_x": 0, "local_rot_y": 0, "local_rot_z": 0,
        "local_scl_x": 1, "local_scl_y": 1, "local_scl_z": 1,
    }


def _entity(name: str, material: int) -> dict:
    return {
        "name": name,
        "components": {
            "Transform": _transform(),
            "MeshRenderer": {"mesh_id": 3, "material_id": material, "visible": True},
        },
    }


def _scene(name: str, ents: list[tuple[str, int]]) -> dict:
    return {
        "version": "0.1.0",
        "scene": {
            "name": name,
            "game_type": "2d",
            "ambient_color": [0.5, 0.5, 0.5],
            "lighting_fallback": True,
            "entities": {str(i + 1): _entity(n, m) for i, (n, m) in enumerate(ents)},
            "main_camera_entity_id": None,
            "next_eid": len(ents) + 1,
        },
    }


def write_fixture(root: str, legacy: bool = False) -> None:
    """写初始工程: 记录 {A:2, B:4}; 引用默认 = 记录值 (legacy: task 引用=3 的已漂移态)。"""
    os.makedirs(os.path.join(root, "scenes"), exist_ok=True)
    os.makedirs(os.path.join(root, "assets"), exist_ok=True)

    def mat(name: str, rgba: list) -> dict:
        return {"name": name, "shader_id": 1, "texture_ids": [1],
                "uniforms": {"uColor": rgba}}

    with open(os.path.join(root, "assets", "A.mat"), "w", encoding="utf-8") as fh:
        json.dump(mat("A", [0.0, 1.0, 0.0, 1.0]), fh, indent=2)   # 绿 (cue)
    with open(os.path.join(root, "assets", "B.mat"), "w", encoding="utf-8") as fh:
        json.dump(mat("B", [1.0, 1.0, 0.0, 1.0]), fh, indent=2)   # 黄 (task)

    task_ref = 3 if legacy else RECORD_B   # 已漂移态: 引用 3 (上一代活 id), 记录仍是 4

    s1 = _scene("S1", [("a1", RECORD_A), ("a2", RECORD_A), ("a3", RECORD_A),
                       ("task1", task_ref), ("cross", 1)])
    s2 = _scene("S2", [("s2_a1", RECORD_A), ("s2_a2", RECORD_A),
                       ("s2_task", task_ref)])
    with open(os.path.join(root, "scenes", "S1.scene"), "w", encoding="utf-8") as fh:
        json.dump(s1, fh, indent=2)
    with open(os.path.join(root, "scenes", "S2.scene"), "w", encoding="utf-8") as fh:
        json.dump(s2, fh, indent=2)

    myproj = {
        "version": "0.1.0", "name": "matcycle",
        "startup_scene": "scenes/S1.scene",
        "scenes": ["scenes/S1.scene", "scenes/S2.scene"],
        "resources": {
            "materials": [
                {"path": "assets/A.mat", "material_id": RECORD_A},
                {"path": "assets/B.mat", "material_id": RECORD_B},
            ],
            "shaders": [], "textures": [], "meshes": [], "prefabs": [],
        },
    }
    with open(os.path.join(root, "matcycle.myproj"), "w", encoding="utf-8") as fh:
        json.dump(myproj, fh, indent=2)


# ════════════════════════════════════════════════════════════════
# Worker（子进程 = 真·新会话）
# ════════════════════════════════════════════════════════════════

def _scaffold():
    """无头编辑器子集引导（test_export_game_bundle 同款 + 事件桩）。"""
    import importlib
    from Application.Core.Engine import Engine
    from Application.Core.Scene.SceneManager import SceneManager
    from Application.Resource.ResourceManager import ResourceManager

    ResourceManager.Init(Engine)
    import Application.Core.NodeGraph.canvas  # noqa: F401 — NodeCanvas 契约注册
    import Application.Core.Scene.BasicComponents  # noqa: F401 — 组件契约注册
    SceneManager.Init(Engine)
    from Application.Editor.EditorHost import EditorHost

    SceneManager.Init(EditorHost)
    EditorHost.scene = SceneManager._state_for("EditorHost")
    _ev = importlib.import_module("Application.Core.Events.Event")
    _ev.app_callback_func = lambda _e: None   # headless: 事件无宿主回调
    return EditorHost, ResourceManager


def _resolve_name(ResourceManager, mid):
    if mid is None:
        return None
    mat = None
    try:
        mat = ResourceManager.GetMaterial(int(mid))
    except Exception:
        mat = getattr(ResourceManager, "loaded_material", {}).get(str(mid))
    return getattr(mat, "name", None) if mat is not None else None


def _observe_bindings(EditorHost, ResourceManager) -> dict:
    import esper
    from Application.Core.Scene.BasicComponents import MeshRenderer

    out: dict = {}
    for eid, mr in esper.get_component(MeshRenderer):
        try:
            nm = EditorHost.scene.GetEntityName(eid)
        except Exception:
            continue
        out[nm] = _resolve_name(ResourceManager, mr.material_id)
    # 非活跃场景: 读场景对象引用（= 下次激活时的绑定来源）
    for _sname, scene in EditorHost._scenes.items():
        if scene is EditorHost._active_scene:
            continue
        for ed in scene.entities.values():
            comp = ed.components.get("MeshRenderer")
            mid = comp.get("material_id") if isinstance(comp, dict) \
                else getattr(comp, "material_id", None)
            if mid is not None and ed.name not in out:
                out[ed.name] = _resolve_name(ResourceManager, mid)
    return out


def _find_eid(EditorHost, name: str):
    import esper
    from Application.Core.Scene.BasicComponents import MeshRenderer

    for eid, _mr in esper.get_component(MeshRenderer):
        try:
            if EditorHost.scene.GetEntityName(eid) == name:
                return eid
        except Exception:
            continue
    return None


def _read_scene_refs(root: str) -> dict:
    out: dict = {}
    sdir = os.path.join(root, "scenes")
    for fn in sorted(os.listdir(sdir)):
        if not fn.endswith(".scene"):
            continue
        with open(os.path.join(sdir, fn), encoding="utf-8") as fh:
            d = json.load(fh)
        refs = {}
        for _eid, ed in d.get("scene", {}).get("entities", {}).items():
            mr = ed.get("components", {}).get("MeshRenderer")
            if isinstance(mr, dict):
                refs[ed.get("name", "?")] = mr.get("material_id")
        out[fn.replace(".scene", "")] = refs
    return out


def _read_records(root: str) -> dict:
    with open(os.path.join(root, "matcycle.myproj"), encoding="utf-8") as fh:
        d = json.load(fh)
    return {os.path.basename(e.get("path", "?")): e.get("material_id")
            for e in d.get("resources", {}).get("materials", [])}


def worker_cycle(workdir: str, scenario: str, idx: int, extra_builtin: bool) -> int:
    EditorHost, ResourceManager = _scaffold()

    if extra_builtin:
        # 模拟引擎演进: 新增 1 个内置材质 (DefaultLit 式 +1)
        from Application.Resource.Material import Material
        ResourceManager.material_count += 1
        m = Material(shader_id=1, uniforms_name_type={"uColor": "vec4"})
        m.name = "ExtraBuiltin"
        ResourceManager.loaded_material[str(ResourceManager.material_count)] = m

    from Application.Editor.ProjectManager import ProjectManager

    proj = os.path.join(workdir, "matcycle.myproj")
    opened = bool(ProjectManager.open_project(proj))
    bindings = _observe_bindings(EditorHost, ResourceManager)

    edits: list = []
    if scenario == "edit":
        targets = ["a1", "a2", "a3"]
        tname = targets[(idx - 1) % len(targets)]
        eid = _find_eid(EditorHost, tname)
        if eid is None:
            edits.append(f"{tname}:not-found")
        else:
            import esper
            from Application.Core.Scene.BasicComponents import MeshRenderer
            from Application.Editor.UI.controllers.SceneBrowserController import (
                SceneBrowserController,
            )
            mr = esper.component_for_entity(eid, MeshRenderer)
            if _resolve_name(ResourceManager, mr.material_id) is None:
                edits.append(f"{tname}:skip-orphan")
            else:
                try:
                    if idx % 2 == 1:
                        SceneBrowserController.set_material_color(eid, 1.0, 0.0, 0.0, 1.0)
                        edits.append(f"{tname}:color")
                    else:
                        SceneBrowserController.set_material_blend(eid, "alpha")
                        edits.append(f"{tname}:blend")
                except Exception as e:  # noqa: BLE001
                    edits.append(f"{tname}:err:{type(e).__name__}")

    saved = bool(ProjectManager.save_project())

    obs = {
        "cycle": idx, "scenario": scenario, "opened": opened, "saved": saved,
        "extra_builtin": extra_builtin, "edits": edits,
        "bindings": bindings,
        "refs": _read_scene_refs(workdir),
        "records": _read_records(workdir),
    }
    with open(os.path.join(workdir, f"obs_{idx:03d}.json"), "w", encoding="utf-8") as fh:
        json.dump(obs, fh, ensure_ascii=False, indent=1)
    sys.stdout.write("OBS:" + json.dumps(obs, ensure_ascii=False) + "\n")
    return 0


# ════════════════════════════════════════════════════════════════
# 驱动（父进程）
# ════════════════════════════════════════════════════════════════

SCENARIOS = [
    # (name, base_cycles, legacy_init, edit, shift_from_cycle)
    ("stable", 8, False, False, None),
    ("legacy", 5, True, False, None),
    ("edit", 6, False, True, None),
    ("shift", 7, False, False, 3),
]


def _binding_ok(name: str | None, expected: str) -> bool:
    """家族匹配: 编辑克隆 (A_copy*, B_copy*) 仍属原家族, 视为绑定存活。"""
    if name is None:
        return False
    if expected == "A":
        return name == "A" or name.startswith("A_copy")
    if expected == "B":
        return name == "B" or name.startswith("B_copy")
    return name == expected


def _evaluate(obs: dict) -> dict:
    bindings = obs.get("bindings", {})
    broken = [n for n, exp in INTENT.items() if not _binding_ok(bindings.get(n), exp)]
    refs, records = obs.get("refs", {}), obs.get("records", {})
    a_refs = [v for s in refs.values() for n, v in s.items()
              if n in ("a1", "a2", "a3", "s2_a1", "s2_a2")]
    b_refs = [v for s in refs.values() for n, v in s.items()
              if n in ("task1", "s2_task")]
    uniform = (len(set(a_refs)) <= 1) and (len(set(b_refs)) <= 1)
    # 对齐不变量: 由工程材质支撑的哨兵引用 (a*/task*, 不含内置 Default 的 cross)
    # 每个活 id 都必须有对应记录条目; 反向不要求 (记录可多于引用, 如旧克隆文件仍在案)
    sentinel_refs = [v for v in (a_refs + b_refs) if v is not None]
    aligned = bool(sentinel_refs) and set(sentinel_refs) <= set(records.values())
    return {"broken": broken, "uniform": uniform, "aligned": aligned,
            "a_refs": sorted(set(a_refs)), "b_refs": sorted(set(b_refs)),
            "records": records}


def _run_worker(workdir: str, scenario: str, idx: int, extra: bool) -> dict | None:
    cmd = [sys.executable, "-X", "utf8", os.path.abspath(__file__),
           "--worker", "cycle", workdir, scenario, str(idx), "1" if extra else "0"]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180, env=env)
    except subprocess.TimeoutExpired:
        print(f"    [worker] TIMEOUT cycle {idx}")
        return None
    for line in (p.stdout or "").splitlines():
        if line.startswith("OBS:"):
            try:
                return json.loads(line[4:])
            except ValueError:
                continue
    print(f"    [worker] rc={p.returncode} no OBS (tail):")
    tail = "\n".join(((p.stdout or "") + (p.stderr or "")).splitlines()[-6:])
    print("      " + tail.replace("\n", "\n      "))
    return None


def main() -> int:
    scale = 1.0
    only = None
    if "--scale" in sys.argv:
        scale = float(sys.argv[sys.argv.index("--scale") + 1])
    if "--scenarios" in sys.argv:
        only = set(sys.argv[sys.argv.index("--scenarios") + 1].split(","))

    ts = time.strftime("%Y%m%d_%H%M%S")
    base = os.path.join(ROOT, "Test", "_runs", f"mat_cycle_{ts}")
    os.makedirs(base, exist_ok=True)
    print("=" * 68)
    print("材质绑定 保存循环压力测试  (子进程=真跨会话; N 轮 open->save)")
    print(f"工作目录: {base}")
    print("=" * 68)

    summary = {}
    t0 = time.time()
    for name, cycles, legacy, edit, shift_from in SCENARIOS:
        if only and name not in only:
            continue
        n = max(2, int(round(cycles * scale)))
        workdir = os.path.join(base, name)
        if os.path.isdir(workdir):
            shutil.rmtree(workdir, ignore_errors=True)
        os.makedirs(workdir, exist_ok=True)
        # 夹具写初始状态（判空后只建一次: run1 建夹具; 后续轮保存接管）
        write_fixture(workdir, legacy=legacy)
        print(f"-- scenario {name}: {n} cycles (legacy={legacy}, edit={edit}, shift_from={shift_from}) --")

        rows = []
        for i in range(1, n + 1):
            extra = bool(shift_from is not None and i > shift_from)
            obs = _run_worker(workdir, name, i, extra)
            if obs is None:
                rows.append({"cycle": i, "broken": ["<worker-failed>"],
                             "uniform": False, "aligned": False})
                break
            ev = _evaluate(obs)
            rows.append({"cycle": i, **ev})
            mark = "ok" if not ev["broken"] else "BROKEN:" + ",".join(ev["broken"])
            extra_s = " +builtin" if extra else ""
            align_s = "aligned" if ev["aligned"] else "drifted"
            print(f"   c{i:02d}{extra_s:<9} {align_s:<8} {mark}")

        fail_cycles = [r for r in rows if r.get("broken")]
        first = fail_cycles[0] if fail_cycles else None
        drift_cycles = [r for r in rows if not r.get("aligned", False)]
        summary[name] = {
            "cycles": len(rows),
            "binding_fail_cycles": len(fail_cycles),
            "first_fail_cycle": first["cycle"] if first else None,
            "first_fail_entities": first["broken"] if first else [],
            "drift_cycles": len(drift_cycles),
            "final_refs": {"a": rows[-1].get("a_refs"), "b": rows[-1].get("b_refs"),
                           "records": rows[-1].get("records")} if rows else {},
            "prob_binding_fail": round(len(fail_cycles) / max(1, len(rows)), 3),
        }

    # ── 汇总表 ──
    print()
    print(f"{'scenario':<10}{'cycles':<8}{'bindFail':<10}{'firstFail':<11}"
          f"{'failEntities':<34}{'prob':<8}{'drift'}")
    for name, s in summary.items():
        print(f"{name:<10}{s['cycles']:<8}{s['binding_fail_cycles']:<10}"
              f"{str(s['first_fail_cycle'] or '-'):<11}"
              f"{','.join(s['first_fail_entities'])[:32]:<34}"
              f"{s['prob_binding_fail']:<8}{s['drift_cycles']}")
    with open(os.path.join(base, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print()
    print(f"elapsed={time.time() - t0:.1f}s  summary={os.path.join(base, 'summary.json')}")

    # ── 预期门 (2026-10-15 修复后): stable/edit/shift 必须 0 绑定失败 + 0 漂移 ──
    #    legacy 为已污染数据 (不自愈) — 仅记录, 不阻断
    EXPECT_CLEAN = ("stable", "edit", "shift")
    gate_fail = []
    for name, s in summary.items():
        if name in EXPECT_CLEAN and (s["binding_fail_cycles"] > 0 or s["drift_cycles"] > 0):
            gate_fail.append(f"{name}: bindFail={s['binding_fail_cycles']} drift={s['drift_cycles']}")
    legacy_s = summary.get("legacy")
    legacy_note = (f"legacy {legacy_s['binding_fail_cycles']}/{legacy_s['cycles']} fail "
                   "(已知脏数据, 不自愈)") if legacy_s else "legacy: n/a"
    if gate_fail:
        print(f"RESULT: FAIL ({'; '.join(gate_fail)})")
        return 1
    print(f"RESULT: OK (stable/edit/shift 0 失败 0 漂移; {legacy_note})")
    return 0


if __name__ == "__main__":
    if "--worker" in sys.argv:
        i = sys.argv.index("--worker")
        _mode = sys.argv[i + 1]
        _wd, _sc, _ix, _ex = sys.argv[i + 2], sys.argv[i + 3], int(sys.argv[i + 4]), sys.argv[i + 5] == "1"
        sys.exit(worker_cycle(_wd, _sc, _ix, _ex))
    sys.exit(main())
