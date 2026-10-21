"""
Light 图标测试 — GizmoQuery.get_light_gizmos + LightIconGizmo overlay (无 GL)。

锁定内容:
  1. get_light_gizmos: 仅返回含 Light+Transform 的 entity; 字段映射 (pos/rot/intensity/color/range/type)
  2. is_editor_visible 来自 SceneManager._editor_visible (眼图标, 与 camera 同规则)
  3. is_selected 命中 selected_ids
  4. build_icon_overlay: key = editor_light_icon_<eid>; texture_pixels (H,W,4) uint8;
     选中/未选中 uColor 不同; ignore_scene_matrices + model_is_ndc + render_layer=1 + 无深度测试
  5. 排序稳定 (按 entity_id)
  6. 方向公式钉死 (防静默回退): rot=0 ⇒ dir=(0,0,-1); rx=90° ⇒ (0,-1,0);
     点光 direction=(0,0,0) (不画方向线)
  7. 方向射线 overlay 契约 (NDC 段/同投影链)

运行: python Utils/Dev/test_runner.py --only light_gizmo
"""
# TIER: core

from __future__ import annotations

import os
import sys
import math

import numpy as np

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


def main() -> int:
    print("=" * 60)
    print("Light icon gizmo — GizmoQuery + LightIconGizmo overlay (headless)")
    print("=" * 60)

    import esper
    from Application.Core.Scene.SceneManager import SceneManager
    from Application.Core.Scene.BasicComponents import Transform, Light
    from Application.Core.Scene.GizmoQuery import GizmoQuery, LightGizmoData
    from Application.Editor.Gizmos.LightIconGizmo import (
        LightIconGizmo, OVERLAY_KEY_PREFIX,
    )

    # ── 夹具: 独立 SceneManager 实例注册为 EditorHost (不 Init → 无默认实体) ──
    orig_reg = SceneManager._registry.get("EditorHost")
    st = SceneManager("EditorHost")
    SceneManager._registry["EditorHost"] = st

    created: list[int] = []
    try:
        # ── 实体: 2 盏方向光 (1 个可见+选中) + 1 个无光实体 (不应出现) ──
        xform = Transform()
        xform.position_x, xform.position_y, xform.position_z = 1.0, 2.0, 3.0
        xform.rotation_x = 0.5

        e1 = esper.create_entity()
        esper.add_component(e1, xform)
        esper.add_component(e1, Light(
            color_r=1.0, color_g=0.8, color_b=0.4, intensity=0.75))
        created.append(e1)

        e2 = esper.create_entity()
        esper.add_component(e2, Transform())
        esper.add_component(e2, Light(
            color_r=0.2, color_g=0.3, color_b=0.9, intensity=1.5))
        created.append(e2)

        e3 = esper.create_entity()   # 无光实体
        esper.add_component(e3, Transform())
        created.append(e3)

        st._editor_visible.add(e1)   # e1 可见; e2 隐形 (眼图标关)

        # ── 1. 查询: 数量/字段/眼图标/选中 ──
        lst = GizmoQuery.get_light_gizmos(selected_ids={e1})
        check("仅返回带光的实体 (2 个)", len(lst) == 2, str(len(lst)))
        check("排序稳定 (按 entity_id)",
              [d.entity_id for d in lst] == sorted([e1, e2]))
        d1 = next(d for d in lst if d.entity_id == e1)
        d2 = next(d for d in lst if d.entity_id == e2)
        check("字段映射 (pos/rot/intensity/color)",
              d1.position == (1.0, 2.0, 3.0) and abs(d1.rotation[0] - 0.5) < 1e-6
              and d1.intensity == 0.75 and (d1.color_r, d1.color_g, d1.color_b) == (1.0, 0.8, 0.4),
              f"{d1}")
        check("is_selected 命中 selected_ids", d1.is_selected and not d2.is_selected)
        check("is_editor_visible 来自眼图标", d1.is_editor_visible and not d2.is_editor_visible)
        check("数据类为 LightGizmoData", isinstance(d1, LightGizmoData))
        check("light_type/range 透传 (默认平面光/range=10)",
              d1.light_type == "directional" and abs(d1.range - 10.0) < 1e-6,
              f"{d1.light_type}/{d1.range}")

        # ── 2. overlay: key / 纹理 / 语义标志 ──
        ov = LightIconGizmo.build_icon_overlay(e1, d1.position, is_selected=False)
        check("key 前缀 editor_light_icon_<eid>",
              ov.key == f"{OVERLAY_KEY_PREFIX}_{e1}"
              and LightIconGizmo.overlay_key_for(e1) == ov.key, ov.key)
        tp = np.asarray(ov.texture_pixels)
        check("texture_pixels 形状 (H,W,4) uint8",
              tp.ndim == 3 and tp.shape[2] == 4 and tp.dtype == np.uint8, str(tp.shape))
        check("语义: ignore_scene_matrices + model_is_ndc + render_layer=1 + 无深度",
              bool(ov.ignore_scene_matrices) and bool(ov.model_is_ndc)
              and int(ov.render_layer) == 1 and not bool(ov.depth_test))
        check("model_matrix_cb 可调用", callable(ov.model_matrix_cb))
        check("几何: 4 顶点 / 6 索引",
              len(ov.vertices) == 4 and len(ov.indices) == 6)

        # ── 3. 选中态 tint 变化 ──
        ov_sel = LightIconGizmo.build_icon_overlay(e1, d1.position, is_selected=True)
        c_un = np.asarray(ov.uniforms['uColor'], dtype=np.float32)
        c_sel = np.asarray(ov_sel.uniforms['uColor'], dtype=np.float32)
        check("选中/未选中 uColor 不同 (选中更亮)",
              not np.allclose(c_un, c_sel) and c_sel.max() >= c_un.max(),
              f"un={c_un.tolist()} sel={c_sel.tolist()}")

        # ── 4. 方向射线 overlay (NDC 屏幕段, 与图标同投影链) ──
        check("direction 为单位向量 (或默认向下)",
              abs(float(np.linalg.norm(d1.direction)) - 1.0) < 1e-4, str(d1.direction))
        # ★ 钉死方向公式 (防静默回退): rot=0 ⇒ dir=(0,0,-1); rx=90° ⇒ (0,-1,0)
        check("已知旋转钉死: rot=0 ⇒ dir=(0,0,-1)",
              abs(d2.direction[0]) < 1e-6 and abs(d2.direction[1]) < 1e-6
              and abs(d2.direction[2] + 1.0) < 1e-6, str(d2.direction))
        xf2 = esper.component_for_entity(e2, Transform)
        xf2.rotation_x = math.radians(90.0)
        d2b = next(d for d in GizmoQuery.get_light_gizmos(selected_ids=set())
                   if d.entity_id == e2)
        check("rx=90° ⇒ dir=(0,-1,0) (与渲染器同式)",
              abs(d2b.direction[0]) < 1e-6 and abs(d2b.direction[1] + 1.0) < 1e-6
              and abs(d2b.direction[2]) < 1e-6, str(d2b.direction))
        xf2.rotation_x = 0.0
        ray = LightIconGizmo.build_ray_overlay(
            e1, d1.position, d1.direction, is_selected=False)
        check("ray key = editor_light_ray_<eid>",
              ray.key == f"editor_light_ray_{e1}"
              and LightIconGizmo.ray_key_for(e1) == ray.key, ray.key)
        check("ray 语义: NDC 段 + ignore_scene_matrices + render_layer=1 + 无深度",
              bool(ray.ignore_scene_matrices) and bool(ray.model_is_ndc)
              and int(ray.render_layer) == 1 and not bool(ray.depth_test)
              and callable(ray.model_matrix_cb))
        check("ray 几何: 2 顶点 / 2 索引 / 线段",
              len(ray.vertices) == 2 and len(ray.indices) == 2
              and str(ray.draw_mode) == 'lines', str(ray.draw_mode))
        M = ray.model_matrix_cb(800, 450)
        check("ray cb 返回 4×4 齐次矩阵", tuple(M.shape) == (4, 4)
              and abs(float(M[3, 3]) - 1.0) < 1e-6, str(M.shape))
        # 旋转变化 → direction 变化 (方向射线语义务必跟随)
        ray_sel = LightIconGizmo.build_ray_overlay(
            e1, d1.position, d1.direction, is_selected=True)
        c_r_un = np.asarray(ray.uniforms['uColor'], dtype=np.float32)
        c_r_sel = np.asarray(ray_sel.uniforms['uColor'], dtype=np.float32)
        check("ray 选中/未选中颜色不同", not np.allclose(c_r_un, c_r_sel))

        # ── 5. 点光: light_type/range 透传 + direction=(0,0,0) (不画方向线) ──
        e_pt = esper.create_entity()
        esper.add_component(e_pt, Transform())
        esper.add_component(e_pt, Light(
            light_type="point", intensity=2.0, range=25.0))
        created.append(e_pt)
        dpt = next(d for d in GizmoQuery.get_light_gizmos(selected_ids=set())
                   if d.entity_id == e_pt)
        check("点光字段: type=point, range=25, direction=(0,0,0)",
              dpt.light_type == "point" and abs(dpt.range - 25.0) < 1e-6
              and dpt.direction == (0.0, 0.0, 0.0), f"{dpt.light_type}/{dpt.range}/{dpt.direction}")

    finally:
        # ── 清场: 实体 + 注册表还原 ──
        for eid in created:
            try:
                esper.delete_entity(eid)
            except Exception:
                pass
        if orig_reg is not None:
            SceneManager._registry["EditorHost"] = orig_reg
        else:
            SceneManager._registry.pop("EditorHost", None)

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
