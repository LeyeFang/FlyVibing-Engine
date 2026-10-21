"""
VertexLayout 标准布局测试 — 不变式 + 后端适配 + shader 一致性快照（无 GL）。

覆盖:
  1. STD_LAYOUT 全部布局满足不变式（offset 4 对齐 / stride 覆盖 / loc0=position）
  2. 关键布局钉死（ENTITY_POS_UV_NORMAL = pos3+uv2+normal3, stride 32）
  3. 后端适配: to_zengl_format / to_zengl_locations / to_gl_attribs
  4. frozen 不可变
  5. check_shader_consistency 警告快照 — 当前已知状态被钉死;
     Basic/SSVEP 的 "location 2 浪费" (布局有 aNormal, shader 不用) 为已知状态;
     Lighting 全用三个属性 → 无浪费 (修复/变更 layout 或 shader 属性时, 这个测试必须同步更新)

运行: python Utils/Dev/test_runner.py --only vertex_layout
"""
# TIER: core

from __future__ import annotations

import os
import sys
import warnings

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: E402

ROOT = os.path.dirname(_d)
SHADER_DIR = os.path.join(ROOT, "Resource", "Shaders", "Builtin")

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _warnings_for(layout, vs_src: str) -> list[str]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        from Application.Core.Renderer.VertexLayout import VertexLayout
        VertexLayout.check_shader_consistency(layout, vs_src, "test")
    return [str(w.message) for w in caught]


def main() -> int:
    print("=" * 60)
    print("VertexLayout — invariants / adapters / shader-consistency snapshot")
    print("=" * 60)

    from Application.Core.Renderer.VertexLayout import STD_LAYOUT, VertexLayout

    layouts = {k: v for k, v in vars(STD_LAYOUT).items() if isinstance(v, VertexLayout)}

    # ── 1. 不变式 ──
    print("── invariants ──")
    check("layout count >= 5", len(layouts) >= 5, str(sorted(layouts)))
    ok_empty = ok_align = ok_stride = ok_pos = True
    for name, ly in layouts.items():
        if not ly.attributes:
            ok_empty = False
        for loc, count, off in ly.attributes:
            if off % 4 != 0:
                ok_align = False
            if off + count * 4 > ly.stride:
                ok_stride = False
        if not any(loc == 0 for loc, _, _ in ly.attributes):
            ok_pos = False
    check("all non-empty", ok_empty)
    check("all offsets 4-byte aligned", ok_align)
    check("all strides cover attributes", ok_stride)
    check("all have location 0", ok_pos)

    # ── 2. 关键布局钉死 ──
    print("── pinned layouts ──")
    ent = STD_LAYOUT.ENTITY_POS_UV_NORMAL
    check("ENTITY attrs", ent.attributes == ((0, 3, 0), (1, 2, 12), (2, 3, 20)),
          str(ent.attributes))
    check("ENTITY stride 32", ent.stride == 32, str(ent.stride))
    check("POSITION_ONLY", STD_LAYOUT.POSITION_ONLY.attributes == ((0, 3, 0),)
          and STD_LAYOUT.POSITION_ONLY.stride == 12)

    # ── 3. 后端适配 ──
    print("── backend adapters ──")
    check("zengl format", ent.to_zengl_format() == "3f 2f 3f", ent.to_zengl_format())
    check("zengl locations", ent.to_zengl_locations() == [0, 1, 2], str(ent.to_zengl_locations()))
    check("gl attribs", ent.to_gl_attribs() == [(0, 3, 32, 0), (1, 2, 32, 12), (2, 3, 32, 20)],
          str(ent.to_gl_attribs()))
    no_pos = VertexLayout(attributes=((1, 3, 0),), stride=12)
    check("get_position_attr fallback", no_pos.get_position_attr() == (0, 3, 0))

    # ── 4. frozen ──
    print("── immutability ──")
    try:
        ent.stride = 99
        frozen_ok = False
    except Exception:
        frozen_ok = True
    check("frozen dataclass", frozen_ok)

    # ── 5. shader 一致性快照（当前已知状态 — 变更即失败, 需有意更新） ──
    print("── shader consistency snapshot ──")
    vs_basic = open(os.path.join(SHADER_DIR, "Basic.vert"), encoding="utf-8").read()
    vs_ssvep = open(os.path.join(SHADER_DIR, "SSVEP.vert"), encoding="utf-8").read()
    vs_lighting = open(os.path.join(SHADER_DIR, "Lighting.vert"), encoding="utf-8").read()

    table = [
        # (label, shader src, layout, 期望 waste 警告数, 期望其他警告数)
        ("Basic×ENTITY", vs_basic, STD_LAYOUT.ENTITY_POS_UV_NORMAL, 1, 0),
        ("SSVEP×ENTITY", vs_ssvep, STD_LAYOUT.ENTITY_POS_UV_NORMAL, 1, 0),
        ("Basic×POSITION_ONLY", vs_basic, STD_LAYOUT.POSITION_ONLY, 0, 1),
        #   ^ shader 声明并使用 aTexCoord(loc1), 而 POSITION_ONLY 无 loc1 → “使用但未定义” 1 条
        ("Basic×TRANSFORM_GIZMO", vs_basic, STD_LAYOUT.TRANSFORM_GIZMO, 0, 0),
        ("Basic×VIEW_GIZMO", vs_basic, STD_LAYOUT.VIEW_GIZMO, 2, 0),
        # ── Lighting: 全用 loc0/1/2 (法线生效 — location 2 浪费在该 shader 上不存在) ──
        ("Lighting×ENTITY", vs_lighting, STD_LAYOUT.ENTITY_POS_UV_NORMAL, 0, 0),
        ("Lighting×POSITION_ONLY", vs_lighting, STD_LAYOUT.POSITION_ONLY, 0, 2),
        #   ^ 使用 aTexCoord(loc1) + aNormal(loc2), POSITION_ONLY 均无 → 2 条
    ]
    for label, src, ly, expect_waste, expect_other in table:
        msgs = _warnings_for(ly, src)
        waste = [m for m in msgs if "数据被浪费" in m]
        other = [m for m in msgs if "数据被浪费" not in m]
        check(f"{label}: waste == {expect_waste}", len(waste) == expect_waste, str(msgs))
        check(f"{label}: other == {expect_other}", len(other) == expect_other, str(other))

    check("known issue: location 2 (normal) unused by Basic/SSVEP",
          any("location 2" in m for m in _warnings_for(STD_LAYOUT.ENTITY_POS_UV_NORMAL, vs_basic)))

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
