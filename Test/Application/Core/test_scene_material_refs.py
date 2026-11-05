"""材质引用跨会话自愈（core，无头）。

背景（ISSUE 2026-11-03）:
  材质 id 是**会话级自增**的，却被写进了 `.scene` 当持久化身份用。只要 id 空间
  漂移（会话里先开过别的工程、旧 `.myproj` 没记 `material_id`、手改场景…），
  实体就会拿到"存在但不对"的材质 —— 渲染成默认白，而且一句提示都没有。

本测试锁定修复后的契约:
  1. `ResourceManager.Init()` 幂等（重复调用不会把内置材质再注册一遍 → 不再位移 id 空间）
  2. `MaterialRef(id)` / `ResolveMaterialRef(ref)` 双向解析（builtin + 磁盘路径 + 文件名回退）
  3. `Scene.to_dict()` 给每个 MeshRenderer 写 `material_path`
  4. `Scene.from_dict()` 用 `material_path` 把引用还原到**当前会话**的 live id
     （模拟漂移：同一批材质换一套 id 注册，引用仍然正确）
  5. 引用解析不到 → `scene.reference_warnings` 有记录（不静默）
"""

# TIER: core

from __future__ import annotations

import os
import sys
import tempfile

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _parent = os.path.dirname(_d)
    if _parent == _d:
        _d = ""
        break
    _d = _parent
if _d:
    sys.path.insert(0, _d)
import _path_setup  # noqa: E402,F401

from Application.Core.Scene.Scene import Scene  # noqa: E402
from Application.Core.Scene.BasicComponents import (  # noqa: E402
    MeshRenderer,
    Transform,
)
from Application.Resource.Material import Material  # noqa: E402
from Application.Resource.ResourceManager import ResourceManager  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


class _FakeApp:
    pass


def _register_material(name: str, path: str) -> int:
    """按 ResourceManager 的正式口径注册一个材质，返回 live id。"""
    mat = Material(1, {})
    mat.name = name
    mat._file_path = path
    ResourceManager.material_count += 1
    new_id = ResourceManager.material_count
    ResourceManager.loaded_material[str(new_id)] = mat
    return new_id


def _reset_materials() -> None:
    ResourceManager.loaded_material.clear()
    ResourceManager.material_count = 0


def main() -> int:
    print("== material reference self-healing tests ==")

    ResourceManager.Init(_FakeApp())
    base = ResourceManager.material_count
    ResourceManager.Init(_FakeApp())
    check("ResourceManager.Init 幂等（重复调用不再追加内置材质）",
          ResourceManager.material_count == base, f"{base} -> {ResourceManager.material_count}")
    check("builtin material ref", ResourceManager.MaterialRef(1) == "builtin://Default",
          ResourceManager.MaterialRef(1))
    check("builtin ref resolves", ResourceManager.ResolveMaterialRef("builtin://Default") == 1)
    check("unknown id -> empty ref", ResourceManager.MaterialRef(9999) == "")

    # ── 会话 A: cue 拿到 id 3 ──
    tmp = tempfile.mkdtemp(prefix="matref_")
    cue_path = os.path.join(tmp, "assets", "materials", "cue.mat")
    os.makedirs(os.path.dirname(cue_path), exist_ok=True)
    with open(cue_path, "w", encoding="utf-8") as fh:
        fh.write("{}")
    a_id = _register_material("cue", cue_path)
    check("session A: cue id", a_id == base + 1, str(a_id))
    ref = ResourceManager.MaterialRef(a_id)
    check("MaterialRef -> normalized path", ref.endswith("assets/materials/cue.mat"), ref)
    check("path ref resolves in same session",
          ResourceManager.ResolveMaterialRef(ref) == a_id, str(ResourceManager.ResolveMaterialRef(ref)))

    scene = Scene(name="RefTest")
    eid = scene.add_entity("Cue", Transform=Transform(), MeshRenderer=MeshRenderer(material_id=a_id))
    data = scene.to_dict()
    mr = data["entities"][str(eid)]["components"]["MeshRenderer"]
    check("to_dict writes material_path", str(mr.get("material_path", "")).endswith("cue.mat"),
          str(mr.get("material_path")))

    # ── 会话 B: 先加载 4 个别的材质 → cue 的 live id 变成 8 ──
    _reset_materials()
    ResourceManager.Init(_FakeApp())
    for i in range(4):
        _register_material(f"filler{i}", os.path.join(tmp, f"assets/materials/filler{i}.mat"))
    b_id = _register_material("cue", cue_path)
    check("session B: cue shifted to a new id", b_id != a_id, f"{a_id} -> {b_id}")

    restored = Scene.from_dict(data)
    mr2 = restored.entities[eid].components["MeshRenderer"]
    got = mr2.material_id if not isinstance(mr2, dict) else mr2["material_id"]
    check("from_dict self-heals drifted material id", got == b_id, f"{got} != {b_id}")
    check("no reference warnings on successful heal",
          not getattr(restored, "reference_warnings", []), str(getattr(restored, "reference_warnings", [])))

    # ── 会话 C: 材质缺失 → 记录告警，不静默 ──
    _reset_materials()
    ResourceManager.Init(_FakeApp())
    broken = Scene.from_dict(data)
    warnings = list(getattr(broken, "reference_warnings", []))
    check("unresolvable ref -> reference_warnings", bool(warnings), str(warnings))
    check("warning names the entity", any("Cue" in w for w in warnings), str(warnings))

    total = _RESULTS["pass"] + _RESULTS["fail"]
    print(f"RESULT: {'OK' if _RESULTS['fail'] == 0 else 'FAIL'} "
          f"({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
