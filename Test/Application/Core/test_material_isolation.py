"""
材质隔离回归 — 内置材质模板保护（无 GL 无头）。

背景 (2026-10-06 live 演示逮到的真实 bug):
  `_ensure_unique_material` 旧逻辑「仅当 >1 entity 共享才 clone」——
  当内置 Default 恰好只剩 1 个引用者时 (如默认 Cube 已改用 DefaultLit 之后),
  颜色/混合编辑会就地写进共享模板, 污染未来所有新建实体;
  且克隆体会继承 builtin_name, 导致「每次编辑都克隆」。

锁定:
  1. 内置材质 (builtin_name 非空) 一律先 clone 再改 — 即使当前独占;
  2. 克隆体屏蔽 builtin_name;
  3. 编辑 A 的颜色/混合后, 默认材质与后建实体 B 外观不受影响;
  4. 非内置独占材质后续编辑不重复克隆。

运行: python Utils/Dev/test_runner.py --only material_isolation
"""
# TIER: core

from __future__ import annotations

import os
import sys

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


class FakeEngine:
    """最小引擎替身 — SceneManager 路径不依赖渲染器。"""
    renderer = None
    scene = None


def main() -> int:
    print("=" * 60)
    print("Material isolation — builtin template protection (headless)")
    print("=" * 60)

    import numpy as np
    import esper
    from Application.Core.Events.Event import BindPackCallback
    from Application.Resource.ResourceManager import ResourceManager
    from Application.Core.Scene.SceneManager import SceneManager
    from Application.Core.Scene.BasicComponents import Transform, MeshRenderer

    BindPackCallback(lambda e: None)
    ResourceManager.Init(FakeEngine)
    SceneManager.Init(FakeEngine)
    st = SceneManager._state_for("FakeEngine")

    # ── 1. 前置: 内置 Default 模板 ──
    print("── builtin template ──")
    default_mid = ResourceManager.GetDefaultMaterial()
    default_mat = ResourceManager.GetMaterial(default_mid)
    check("Default 是内置模板 (builtin_name='Default')",
          getattr(default_mat, 'builtin_name', None) == 'Default',
          str(getattr(default_mat, 'builtin_name', None)))
    base_color = np.array(default_mat.uniforms_data['uColor'], dtype=np.float32)
    base_blend = getattr(default_mat, 'blend', 'opaque')

    # ── 2. 实体 A 复用默认材质 → 编辑触发克隆 (独占也不例外) ──
    print("── edit triggers clone (even when exclusive) ──")
    eid_a = st.AddEntity("matA", Transform(), MeshRenderer())
    mr_a = esper.component_for_entity(eid_a, MeshRenderer)
    check("新实体引用 Default", mr_a.material_id == default_mid, str(mr_a.material_id))

    SceneManager._ensure_unique_material(st, eid_a, mr_a)
    check("内置模板独占也克隆", mr_a.material_id != default_mid,
          f"still {mr_a.material_id}")
    mat_a = ResourceManager.GetMaterial(mr_a.material_id)
    check("克隆体屏蔽 builtin_name", getattr(mat_a, 'builtin_name', None) is None,
          str(getattr(mat_a, 'builtin_name', None)))
    check("克隆体名称 _copy 后缀", mat_a.name.endswith('_copy'), mat_a.name)

    # ── 3. 编辑 A (颜色 + 混合) → 默认模板不受污染 ──
    print("── template not polluted ──")
    ResourceManager.SetMaterialColor(mr_a.material_id, 0.0, 1.0, 0.0, 0.5)
    mat_a.blend = 'alpha'
    check("Default 颜色未污染 (仍为白)",
          np.allclose(default_mat.uniforms_data['uColor'], [1, 1, 1, 1]),
          str(default_mat.uniforms_data['uColor']))
    check("Default blend 未污染 (仍为 opaque)",
          getattr(default_mat, 'blend', 'opaque') == base_blend,
          getattr(default_mat, 'blend', 'opaque'))

    # ── 4. 后建实体 B → 洁净默认外观 ──
    print("── later entity stays clean ──")
    eid_b = st.AddEntity("matB", Transform(), MeshRenderer())
    mr_b = esper.component_for_entity(eid_b, MeshRenderer)
    check("B 引用 Default", mr_b.material_id == default_mid)
    mat_b0 = ResourceManager.GetMaterial(mr_b.material_id)
    check("B 外观洁净 (白 + opaque)",
          np.allclose(mat_b0.uniforms_data['uColor'], [1, 1, 1, 1])
          and getattr(mat_b0, 'blend', 'opaque') == 'opaque')

    # ── 5. 克隆体后续编辑不重复克隆; B 编辑得独立克隆 ──
    print("── clone semantics ──")
    mid_before = mr_a.material_id
    SceneManager._ensure_unique_material(st, eid_a, mr_a)
    check("A 克隆体 (非内置独占) 再编辑不重复克隆", mr_a.material_id == mid_before,
          f"{mid_before} -> {mr_a.material_id}")
    SceneManager._ensure_unique_material(st, eid_b, mr_b)
    check("B 编辑得独立克隆 (≠ Default, ≠ A)",
          mr_b.material_id not in (default_mid, mr_a.material_id),
          str(mr_b.material_id))

    # ── 清场 ──
    st.DeleteEntity(eid_a)
    st.DeleteEntity(eid_b)

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
