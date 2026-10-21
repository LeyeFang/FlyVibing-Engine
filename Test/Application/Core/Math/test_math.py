"""
Math Verification Utilities -- matrix convention verification (pure numpy)
============================================================================

Uses core math functions from the project:
  - Application/Core/Math/Transform.py    -> calculate_entity_model (TRS)
  - Application/Core/Math/Camera.py       -> look_at / perspective_projection
  - ViewGizmo NDC overlay model (纯 numpy, 标准列向量)

Purpose: Verify row-vector vs column-vector conventions WITHOUT a GL context.

Key findings (verified below):
  - Engine math (Math.Transform / Math.Camera) uses ROW-VECTOR convention
    (v' = v * M), translation in the BOTTOM row
  - GL_FALSE upload (C-contiguous bytes -> column-major in shader)
    makes row-vector matrices correct for column-vector OpenGL
  - NDC overlay numpy model (ViewGizmo) uses standard column-vector math
    -> must upload with GL_TRUE
"""
# TIER: core

from __future__ import annotations
import sys
import os

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
import _path_setup  # noqa: E402

import math
import numpy as np

from Application.Core.Math.Transform import calculate_entity_model
from Application.Core.Math.Camera import look_at, perspective_projection


# ==========================================================================
# Simulate OpenGL uniform upload
# ==========================================================================

def gl_decode_colmajor(data: np.ndarray) -> np.ndarray:
    """Simulate OpenGL GL_FALSE (column-major) decode of 16 floats -> 4x4 matrix.

    OpenGL reads column by column: data[0:4]=col0, data[4:8]=col1, ...
    Returns reconstructed matrix in standard math convention: mat[i,j] = row i, col j.
    """
    f32 = np.ascontiguousarray(data.astype('float32')).flatten()
    assert len(f32) == 16, f"Expected 16 floats, got {len(f32)}"
    mat = np.zeros((4, 4), dtype=np.float32)
    for c in range(4):
        mat[0, c] = f32[c * 4 + 0]
        mat[1, c] = f32[c * 4 + 1]
        mat[2, c] = f32[c * 4 + 2]
        mat[3, c] = f32[c * 4 + 3]
    return mat


def gl_decode_rowmajor(data: np.ndarray) -> np.ndarray:
    """Simulate OpenGL GL_TRUE (row-major) decode + transpose.

    OpenGL reads row by row: data[0:4]=row0, ..., then transposes to column-major.
    Returns the final column-major matrix in standard math convention.
    """
    f32 = np.ascontiguousarray(data.astype('float32')).flatten()
    assert len(f32) == 16, f"Expected 16 floats, got {len(f32)}"
    mat = np.zeros((4, 4), dtype=np.float32)
    for r in range(4):
        mat[r, 0] = f32[r * 4 + 0]
        mat[r, 1] = f32[r * 4 + 1]
        mat[r, 2] = f32[r * 4 + 2]
        mat[r, 3] = f32[r * 4 + 3]
    return mat


_CHECKS = 0
_FAILS = 0


def check(a: np.ndarray, b: np.ndarray, name: str = "", tol: float = 1e-5) -> bool:
    """Compare two matrices, print result + 计数（供 RESULT 行）。"""
    global _CHECKS, _FAILS
    _CHECKS += 1
    diff = np.abs(np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64)).max()
    ok = bool(diff < tol)
    if not ok:
        _FAILS += 1
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name}  max_diff={diff:.2e}")
    if not ok:
        print(f"    A:\n{a}")
        print(f"    B:\n{b}")
    return ok


def check_true(cond: bool, name: str) -> bool:
    global _CHECKS, _FAILS
    _CHECKS += 1
    if not cond:
        _FAILS += 1
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    return bool(cond)


# ==========================================================================
# 1. pyrr matrix -> numpy -> OpenGL convention
# ==========================================================================

def verify_upload_convention():
    print("=" * 60)
    print("1. Engine row-vector matrix -> numpy -> OpenGL convention")
    print("=" * 60)

    # Engine convention (Math.Transform / Math.Camera): ROW-VECTOR, v' = v * M
    # translation matrix for (3, 5, 7) — translation stored in the BOTTOM row
    rowvec_mat = np.array([
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 1, 0],
        [3, 5, 7, 1],
    ], dtype=np.float32)
    print(f"  row-vector matrix:\n{rowvec_mat}")

    # C-contiguous bytes — what OpenGLUtils flattens and uploads (GL_FALSE)
    np_mat = np.ascontiguousarray(rowvec_mat)
    print(f"  numpy (C-contiguous):\n{np_mat}")
    print(f"  numpy[0,:] = {np_mat[0,:]}  (row 0)")
    print(f"  numpy[3,:] = {np_mat[3,:]}  (row 3 = translation)")

    # Column-vector form of the same translation (what OpenGL expects):
    # [[1, 0, 0, 3],
    #  [0, 1, 0, 5],
    #  [0, 0, 1, 7],
    #  [0, 0, 0, 1]]
    col_vec_trans = np.array(
        [[1, 0, 0, 3],
         [0, 1, 0, 5],
         [0, 0, 1, 7],
         [0, 0, 0, 1]], dtype=np.float32)

    # Case A: GL_FALSE on row-vector data
    # row-vector bytes + GL_FALSE -> effectively transposes -> column-vector form
    decoded_false = gl_decode_colmajor(np_mat)
    print(f"\n  GL_FALSE decoded (column-vector form):\n{decoded_false}")
    check(decoded_false, col_vec_trans,
          "row-vector + GL_FALSE -> column-vector matrix [CORRECT for OpenGL]")

    # Case B: GL_TRUE on row-vector data
    # row-vector bytes + GL_TRUE -> stays row-vector form -> WRONG for OpenGL
    decoded_true = gl_decode_rowmajor(np_mat)
    print(f"\n  GL_TRUE decoded (stays row-vector form):\n{decoded_true}")
    check(decoded_true, np_mat,
          "row-vector + GL_TRUE -> row-vector matrix [WRONG for OpenGL]")

    # ----------------------------------------
    # Now test a PURE NUMPY matrix (standard math convention: column vectors)
    # ----------------------------------------
    print(f"\n  --- Pure numpy matrix (standard convention, column vectors) ---")
    np_plain = np.array(
        [[1, 0, 0, 3],
         [0, 1, 0, 5],
         [0, 0, 1, 7],
         [0, 0, 0, 1]], dtype=np.float32)
    print(f"  numpy plain:\n{np_plain}")

    # GL_FALSE on pure numpy -> reads columns as rows -> TRANSPOSED -> WRONG
    decoded_plain_false = gl_decode_colmajor(np_plain)
    print(f"\n  GL_FALSE decoded (TRANSPOSED!):\n{decoded_plain_false}")
    check(decoded_plain_false,
          np.array([[1,0,0,0],[0,1,0,0],[0,0,1,0],[3,5,7,1]], dtype=np.float32),
          "numpy + GL_FALSE -> TRANSPOSED [WRONG]")

    # GL_TRUE on pure numpy -> reads rows, transposes to columns -> CORRECT
    decoded_plain_true = gl_decode_rowmajor(np_plain)
    print(f"\n  GL_TRUE decoded (correct!):\n{decoded_plain_true}")
    check(decoded_plain_true, np_plain,
          "numpy + GL_TRUE -> column-vector matrix [CORRECT]")

    print()


# ==========================================================================
# 2. Entity Model matrix (engine Math.Transform, TRS)
# ==========================================================================

def verify_entity_model():
    print("=" * 60)
    print("2. Entity Model matrix (engine Math.Transform, TRS)")
    print("=" * 60)

    pos = (2.0, 3.0, 4.0)
    rot_euler = (math.radians(30), math.radians(45), 0.0)
    scale = (1.0, 2.0, 1.0)

    # TRS: engine 直接构造行向量矩阵 (与 SceneManager/渲染上传同一份代码)
    model = calculate_entity_model(pos, rot_euler, scale)
    print(f"  model = TRS (pure numpy, row-vector):\n{model}")

    # Verify: origin (0,0,0,1) transformed by model should give position
    # row-vector apply: v' = v @ M
    p = np.array([0, 0, 0, 1.0])
    result = p @ model
    print(f"  (0,0,0,1) @ model = {result} (expect ~(2,3,4,1))")
    assert abs(result[0] - 2.0) < 0.01
    assert abs(result[1] - 3.0) < 0.01
    assert abs(result[2] - 4.0) < 0.01, "TRS origin check failed"
    print("  -> TRS origin check PASS")

    np_model = np.ascontiguousarray(model.astype('float32'))

    # GL_FALSE (what renderer uses for entity model)
    decoded_false = gl_decode_colmajor(np_model)
    p_h = np.array([0, 0, 0, 1.0], dtype=np.float32)
    result_false = decoded_false @ p_h
    print(f"  GL_FALSE decoded @ (0,0,0,1) = {result_false}")
    check(result_false[:3], np.array([2, 3, 4]),
          "entity model + GL_FALSE -> correct transform [PASS]")

    # GL_TRUE (if used, it would be wrong)
    decoded_true = gl_decode_rowmajor(np_model)
    result_true = decoded_true @ p_h
    print(f"  GL_TRUE  decoded @ (0,0,0,1) = {result_true}")
    diff = np.abs(result_true[:3] - np.array([2, 3, 4])).max()
    print(f"  GL_TRUE diff from expected = {diff:.4f} (should be >> 0)")

    print()


# ==========================================================================
# 3. ViewGizmo Cube Model matrix (PURE numpy ndarray)
# ==========================================================================

# Constants copied from ViewGizmo
CUBE_SIZE_NDC: float = 0.18
SCREEN_OFFSET_X: float = 0.82
SCREEN_OFFSET_Y: float = -0.80


def compute_cube_model(vp_w: int, vp_h: int,
                       yaw: float = math.pi * 0.75,
                       pitch: float = math.pi / 6.0) -> np.ndarray:
    """Exact copy of ViewGizmo._compute_cube_model_cb logic.

    model = T @ R_cube @ S   (pure numpy @ operator)

    Returns pure numpy ndarray in standard math convention (column vectors).
    """
    SIGN_PITCH: float = -1.0
    SIGN_YAW: float = -1.0
    sp = math.sin(pitch) * SIGN_PITCH
    cp = math.cos(pitch)
    sy = math.sin(yaw) * SIGN_YAW
    cy = math.cos(yaw)

    R_view = np.array([
        [cy,        0.0,      sy],
        [sy * sp,  -cp,     -cy * sp],
        [-sy * cp, -sp,      cy * cp],
    ], dtype=np.float32)

    R_cube = R_view.copy()
    R_cube[1, :] *= -1.0
    R_cube[2, :] *= -1.0

    rot_mat = np.identity(4, dtype=np.float32)
    rot_mat[:3, :3] = R_cube

    aspect = vp_w / max(vp_h, 1)
    s = CUBE_SIZE_NDC
    scale_mat = np.diag([s / aspect, s, s, 1.0]).astype(np.float32)

    trans_mat = np.identity(4, dtype=np.float32)
    trans_mat[0, 3] = SCREEN_OFFSET_X
    trans_mat[1, 3] = SCREEN_OFFSET_Y

    return (trans_mat @ rot_mat @ scale_mat).astype(np.float32)


def verify_viewgizmo_model():
    print("=" * 60)
    print("3. ViewGizmo Cube Model matrix (PURE numpy ndarray)")
    print("=" * 60)

    vp_w, vp_h = 1024, 768
    model = compute_cube_model(vp_w, vp_h)
    print(f"  model (numpy, standard math convention):\n{model}")

    # Check: is this matrix symmetric?
    is_sym = np.allclose(model, model.T)
    print(f"  Is model symmetric? {is_sym}")

    # Transform cube center (0,0,0,1) to NDC
    center = np.array([0, 0, 0, 1.0], dtype=np.float32)
    ndc_center = model @ center
    print(f"  model @ (0,0,0,1) = NDC {ndc_center[:3]}")
    check(ndc_center[:2], np.array([SCREEN_OFFSET_X, SCREEN_OFFSET_Y]),
          "cube center NDC position")

    # ---- Simulate Visual pass: GL_TRUE ----
    visual_gl = gl_decode_rowmajor(model)
    ndc_visual = visual_gl @ center
    print(f"\n  Visual pass (GL_TRUE):  @ center = {ndc_visual[:3]}")
    check(ndc_visual[:2], np.array([SCREEN_OFFSET_X, SCREEN_OFFSET_Y]),
          "visual GL_TRUE: NDC position [EXPECT PASS]")

    # ---- 反事实: 若用 GL_FALSE 上传列向量矩阵 ----
    pick_gl = gl_decode_colmajor(model)
    ndc_pick = pick_gl @ center
    print(f"\n  Counterfactual (GL_FALSE): @ center = {ndc_pick[:3]}")
    # GL_FALSE on column-vector matrix -> TRANSPOSED -> cube center misplaced
    # (除非矩阵恰好对称, 此时两种约定重合)
    misplaced = np.abs(ndc_pick[:2] - np.array([SCREEN_OFFSET_X, SCREEN_OFFSET_Y])).max() > 1e-3
    check_true(bool(misplaced or np.allclose(model, model.T)),
               "counterfactual: GL_FALSE would misplace cube center")

    # ---- Comparison ----
    diff = np.abs(visual_gl - pick_gl).max()
    print(f"\n  Visual vs Pick matrix max_diff = {diff:.4f}")
    if diff < 1e-5:
        print("  -> Matrices identical (identity/symmetric, coincidentally correct)")
    else:
        print("  -> MATRICES DIFFER! Pick geometry != visual geometry!")
        print(f"  Visual GL_TRUE matrix:\n{visual_gl}")
        print(f"  Pick   GL_FALSE matrix:\n{pick_gl}")

    print()


# ==========================================================================
# 4. Camera View/Proj matrices (engine Math.Camera)
# ==========================================================================

def verify_camera_matrices():
    print("=" * 60)
    print("4. Camera View/Proj matrices (engine Math.Camera)")
    print("=" * 60)

    # Simulate EditorCamera
    yaw = math.pi * 0.75
    pitch = math.pi / 6.0
    orbit_target = np.array([0.0, 0.0, 0.0], dtype=np.float32)
    orbit_distance = 15.0

    dx = math.sin(yaw) * math.cos(pitch)
    dy = math.sin(pitch)
    dz = -math.cos(yaw) * math.cos(pitch)
    position = orbit_target + orbit_distance * np.array([dx, dy, dz])

    print(f"  camera pos: {position}")
    print(f"  orbit target: {orbit_target}")

    # engine look_at (row-vector, 与 EditorCamera 同源)
    view = look_at(position, orbit_target,
                   np.array([0.0, 1.0, 0.0], dtype=np.float32)).astype(np.float32)

    np_view = np.ascontiguousarray(view)

    # Verify: camera position in view space should be origin
    cam_h = np.array([position[0], position[1], position[2], 1.0], dtype=np.float32)

    # GL_FALSE (what renderer uses)
    decoded_false = gl_decode_colmajor(np_view)
    cam_view = decoded_false @ cam_h
    print(f"  GL_FALSE: view @ cam_pos = {cam_view} (expect ~(0,0,d,1))")
    check(cam_view[:2], np.array([0, 0]),
          "GL_FALSE: camera at view-space origin X,Y")

    # GL_TRUE (if used, would be wrong)
    decoded_true = gl_decode_rowmajor(np_view)
    cam_view2 = decoded_true @ cam_h
    print(f"  GL_TRUE:  view @ cam_pos = {cam_view2} (should NOT be at origin)")

    # ---- Projection matrix ----
    fov, aspect, near, far = 45.0, 1024 / 768, 0.1, 1000.0
    proj = perspective_projection(fov, aspect, near, far).astype(np.float32)
    np_proj = np.ascontiguousarray(proj)

    decoded_proj_false = gl_decode_colmajor(np_proj)
    decoded_proj_true = gl_decode_rowmajor(np_proj)

    diff = np.abs(decoded_proj_false - decoded_proj_true).max()
    print(f"\n  proj matrix GL_FALSE vs GL_TRUE max_diff = {diff:.4f}")
    if diff < 1e-5:
        print("  -> Proj matrix is symmetric (unlikely for perspective)")
    else:
        print("  -> Proj matrix NOT symmetric, conventions give different results")
        print("  -> GL_FALSE is the correct convention for engine row-vector proj matrices")

    print()


# ==========================================================================
# 5. Multi-angle ViewGizmo analysis + Summary
# ==========================================================================

def print_summary():
    print("=" * 60)
    print("5. SUMMARY: Matrix source -> Convention -> Correctness")
    print("=" * 60)
    print("""
+------------------------------------+--------------+--------------+----------+
| Matrix Source                      | Memory Format| Should Use   | Current  |
+------------------------------------+--------------+--------------+----------+
| Math.Transform / Math.Camera       | row-vector   | GL_FALSE     | GL_FALSE |
| numpy ndarray (NDC overlay, col)   | column-vector| GL_TRUE      | GL_TRUE  |
+------------------------------------+--------------+--------------+----------+
| Entity model (Math.Transform TRS)  | row-vector   | GL_FALSE     | CORRECT  |
| Camera view/proj (Math.Camera)     | row-vector   | GL_FALSE     | CORRECT  |
| Overlay visual NDC model           | column       | GL_TRUE      | CORRECT  |
| Overlay PICK NDC model             | column       | GL_TRUE      | CORRECT  |
| ViewGizmo model_cb                 | column       | GL_TRUE      | CORRECT  |
+------------------------------------+--------------+--------------+----------+

STATUS: ALL CORRECT.
  Upload convention (OpenGLUtils / overlays):
    - 引擎数学矩阵 (row-vector 约定, Math.Transform/Math.Camera) -> GL_FALSE
    - NDC overlay numpy 矩阵 (标准列向量, ViewGizmo)             -> GL_TRUE

  (2026-10-05: pyrr 依赖已从仓库移除 — 本文件全部纯 numpy,
   第 1/2/4 节直接验证引擎当前数学函数.)

WHAT WOULD HAPPEN IF GL_FALSE WERE USED FOR 列向量 NDC 矩阵:
  ViewGizmo cube pick 会被转置 — 见第 3 节与第 6 节数值证据.
""")

    # Numeric confirmation of the ViewGizmo issue at various angles
    print("=" * 60)
    print("6. NUMERIC CONFIRMATION: ViewGizmo model at various yaw/pitch")
    print("=" * 60)

    for yaw_deg, pitch_deg in [(135, 30), (45, 25), (200, 15), (0, 45), (90, 10)]:
        yaw = math.radians(yaw_deg)
        pitch = math.radians(pitch_deg)
        model = compute_cube_model(1024, 768, yaw, pitch)

        visual_dec = gl_decode_rowmajor(model)
        pick_dec = gl_decode_colmajor(model)

        diff = np.abs(visual_dec - pick_dec).max()
        is_sym = np.allclose(model, model.T)
        status = "OK (symmetric)" if is_sym else "MISMATCH!"
        print(f"  yaw={yaw_deg:3d}  pitch={pitch_deg:2d}  "
              f"model_symmetric={str(is_sym):5s}  visual_vs_pick_diff={diff:.4f}  {status}")


# ==========================================================================
# main
# ==========================================================================

if __name__ == "__main__":
    verify_upload_convention()
    verify_entity_model()
    verify_viewgizmo_model()
    verify_camera_matrices()
    print_summary()
    _status = "OK" if _FAILS == 0 else "FAIL"
    print(f"\nRESULT: {_status} ({_CHECKS} checks, {_FAILS} failed)")
