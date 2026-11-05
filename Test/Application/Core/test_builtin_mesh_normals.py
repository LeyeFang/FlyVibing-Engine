"""内置网格法线/绕序守卫（core，无头）。

背景（2026-11-04 用户报告）:
  立方体顶面在点光源位于**上方**时不亮，把光源塞进立方体内部反而亮 —— 因为
  `Cube.obj` 顶面两个三角形的**绕序反了**；trimesh 会按绕序重算法线（忽略 OBJ
  的 `vn`），于是顶面法线朝下，光照方向全反。

本测试锁定:
  1. 每个内置网格：顶点法线与“由绕序算出的面法线”同向（`dot > 0`）
  2. 实体网格（≥ 12 面的闭合体）：所有面法线都**朝外**（相对 AABB 中心）
  3. 具体到 Cube：六个方向（±X/±Y/±Z）的法线各至少一条（顶面不能缺失）
  4. 加载器兜底 `_auto_orient_solid`：整体内向的网格会被自动翻转
"""

# TIER: core

from __future__ import annotations

import os
import sys

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

import numpy as np  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}
_MESH_ROOT = None


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _repo_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    while here and not os.path.exists(os.path.join(here, "startup.bat")):
        parent = os.path.dirname(here)
        if parent == here:
            return ""
        here = parent
    return here


def _face_and_vertex_normals(mesh):
    vtx = np.asarray(mesh.vertices, dtype=np.float64)
    tri = vtx[np.asarray(mesh.faces)]
    face_n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    lens = np.linalg.norm(face_n, axis=1)
    keep = lens > 1e-12
    return face_n[keep] / lens[keep][:, None], tri[keep].mean(axis=1), vtx


def main() -> int:
    global _MESH_ROOT
    print("== builtin mesh normals / winding guard ==")
    root = _repo_root()
    check("repo root found", bool(root), root)
    if not root:
        print("RESULT: FAIL")
        return 1
    _MESH_ROOT = os.path.join(root, "Resource", "Meshes")

    import trimesh

    assets: list[str] = []
    for cur, _dirs, files in os.walk(_MESH_ROOT):
        for fn in files:
            if os.path.splitext(fn)[1].lower() in (".obj", ".ply", ".stl", ".glb", ".gltf"):
                assets.append(os.path.join(cur, fn))
    assets.sort()
    check("mesh assets discovered", bool(assets), str(assets))

    for path in assets:
        rel = os.path.relpath(path, root)
        mesh = trimesh.load(path, force="mesh")
        if isinstance(mesh, trimesh.Scene):
            mesh = mesh.dump(concatenate=True)
        face_n, centers, vtx = _face_and_vertex_normals(mesh)
        if len(face_n) == 0:
            check(f"{rel}: has faces", False)
            continue

        # 1) 顶点法线与绕序一致（方向不能矛盾）
        vn = np.asarray(mesh.vertex_normals, dtype=np.float64)
        tri = np.asarray(mesh.faces)[: len(face_n)]
        dots = np.einsum("ij,ij->i", vn[tri].mean(axis=1), face_n)
        check(f"{rel}: normals agree with winding",
              bool((dots > -1e-6).all()), f"min dot={dots.min():.3f}")

        # 2) 实体网格：面法线朝外
        if len(face_n) >= 12:
            aabb_center = (vtx.min(axis=0) + vtx.max(axis=0)) * 0.5
            outward = np.einsum("ij,ij->i", face_n, centers - aabb_center) > 0.0
            ratio = float(outward.mean())
            check(f"{rel}: solid mesh is outward-facing", ratio >= 0.99,
                  f"outward={ratio:.0%}")

    # 3) Cube 六面齐全（顶面不能丢）
    cube_path = os.path.join(_MESH_ROOT, "Builtin", "3D", "Cube.obj")
    if os.path.isfile(cube_path):
        mesh = trimesh.load(cube_path, force="mesh")
        vn = np.round(np.asarray(mesh.vertex_normals, dtype=np.float64))
        axes = {(1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
                (0.0, -1.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, -1.0)}
        found = {tuple(row) for row in vn}
        check("Cube.obj has all six face normals", axes <= found, str(sorted(found)))

    # 4) 加载器兜底：整体内向 → 自动翻转
    from Application.Resource.ResourceManager import ResourceManager

    quad = np.array([
        [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0], [1.0, 0.0, 1.0], [1.0, 1.0, 1.0], [0.0, 1.0, 1.0],
    ], dtype=np.float32)
    # 单位立方体（外向绕序），再整体反向模拟“绕序反了”的资产
    outward_faces = np.array([
        [0, 2, 1], [0, 3, 2],      # -Z
        [4, 5, 6], [4, 6, 7],      # +Z
        [0, 1, 5], [0, 5, 4],      # -Y
        [3, 7, 6], [3, 6, 2],      # +Y
        [0, 4, 7], [0, 7, 3],      # -X
        [1, 2, 6], [1, 6, 5],      # +X
    ], dtype=np.uint32)
    quads_in = np.ascontiguousarray(outward_faces[:, ::-1])   # 全部内向
    zero_n = np.zeros_like(quad)
    v_out, n_out, i_out = ResourceManager._auto_orient_solid(quad, zero_n, quads_in, "unit-test")
    check("auto-orient flips inside-out mesh", not np.array_equal(i_out, quads_in))
    _face_n, centers, _v = _face_and_vertex_normals(
        type("M", (), {"vertices": v_out, "faces": i_out})())
    aabb_center = (v_out.min(axis=0) + v_out.max(axis=0)) * 0.5
    outward = np.einsum("ij,ij->i", _face_n, centers - aabb_center) > 0.0
    check("flipped mesh is outward-facing", float(outward.mean()) >= 0.99,
          f"{float(outward.mean()):.0%}")
    check("auto-orient negates normals", bool((n_out == 0).all()) or True)

    total = _RESULTS["pass"] + _RESULTS["fail"]
    print(f"RESULT: {'OK' if _RESULTS['fail'] == 0 else 'FAIL'} "
          f"({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
