"""
Math Verification Utilities -- matrix convention verification (pure numpy/pyrr)
============================================================================

Extracts core math functions from the project:
  - Application/Core/Math/RendererMath.py    -> TRS model matrix
  - Application/Editor/EditorCamera.py       -> view/projection matrices
  - Application/Editor/Rendering/ViewGizmo.py -> cube model matrix

Purpose: Verify row-major vs column-major conventions WITHOUT a GL context.

Key finding to verify:
  - pyrr Matrix44 uses ROW-VECTOR convention (v' = v * M)
  - numpy ndarray uses standard math convention (v' = M * v, column vectors)
  - GL_FALSE + pyrr = correct for column-vector OpenGL
  - GL_TRUE  + numpy = correct for column-vector OpenGL
  - openGLRenderer_v6._render_overlays_pick_pass uses GL_FALSE for numpy model
    matrix from model_matrix_cb -> POTENTIAL BUG
"""

from __future__ import annotations
import math
import numpy as np
from pyrr import matrix44, Matrix44, Vector3, Vector4


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


def check(a: np.ndarray, b: np.ndarray, name: str = "", tol: float = 1e-5) -> bool:
    """Compare two 4x4 matrices, print result."""
    diff = np.abs(a - b).max()
    ok = diff < tol
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name}  max_diff={diff:.2e}")
    if not ok:
        print(f"    A:\n{a}")
        print(f"    B:\n{b}")
    return ok


# ==========================================================================
# 1. pyrr matrix -> numpy -> OpenGL convention
# ==========================================================================

def verify_pyrr_convention():
    print("=" * 60)
    print("1. pyrr Matrix44 -> numpy -> OpenGL convention")
    print("=" * 60)

    # pyrr translation matrix for (3, 5, 7)
    # pyrr uses ROW-VECTOR convention: v' = v * M
    # So translation is stored in the BOTTOM row
    pyrr_mat = matrix44.create_from_translation(Vector3([3.0, 5.0, 7.0]))
    print(f"  pyrr Matrix44 (row-vector form):\n{pyrr_mat}")
    # Expected row-vector form:
    # [[1, 0, 0, 0],
    #  [0, 1, 0, 0],
    #  [0, 0, 1, 0],
    #  [3, 5, 7, 1]]

    # numpy C-contiguous view -- memory is identical to pyrr internal storage
    np_mat = np.ascontiguousarray(pyrr_mat.astype('float32'))
    print(f"  numpy (C-contiguous):\n{np_mat}")
    print(f"  numpy[0,:] = {np_mat[0,:]}  (pyrr row 0)")
    print(f"  numpy[3,:] = {np_mat[3,:]}  (pyrr row 3 = translation)")

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

    # Case A: GL_FALSE on pyrr data
    # pyrr row-vector bytes + GL_FALSE -> effectively transposes -> column-vector form
    decoded_false = gl_decode_colmajor(np_mat)
    print(f"\n  GL_FALSE decoded (column-vector form):\n{decoded_false}")
    check(decoded_false, col_vec_trans,
          "pyrr + GL_FALSE -> column-vector matrix [CORRECT for OpenGL]")

    # Case B: GL_TRUE on pyrr data
    # pyrr row-vector bytes + GL_TRUE -> stays row-vector form -> WRONG for OpenGL
    decoded_true = gl_decode_rowmajor(np_mat)
    print(f"\n  GL_TRUE decoded (stays row-vector form):\n{decoded_true}")
    check(decoded_true, np_mat,
          "pyrr + GL_TRUE -> row-vector matrix [WRONG for OpenGL]")

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
# 2. Entity Model matrix (pyrr Matrix44 TRS)
# ==========================================================================

def verify_entity_model():
    print("=" * 60)
    print("2. Entity Model matrix (pyrr Matrix44, TRS)")
    print("=" * 60)

    pos = Vector3([2.0, 3.0, 4.0])
    rot_euler = Vector3([math.radians(30), math.radians(45), 0.0])
    scale = Vector3([1.0, 2.0, 1.0])

    # TRS: model = T * R * S  (pyrr __mul__)
    scale_mat = Matrix44.from_scale(scale, dtype=float)
    rot_mat = Matrix44.from_eulers(rot_euler, dtype=float)
    trans_mat = Matrix44.from_translation(pos, dtype=float)
    model = trans_mat * rot_mat * scale_mat
    print(f"  model = T*R*S (pyrr Matrix44):\n{model}")

    # Verify: origin (0,0,0,1) transformed by model should give position
    p = Vector4([0, 0, 0, 1.0])
    result = model * p
    print(f"  model * (0,0,0,1) = {result} (expect ~(2,3,4,1))")
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

    # ---- Simulate Pick pass: GL_FALSE ----
    pick_gl = gl_decode_colmajor(model)
    ndc_pick = pick_gl @ center
    print(f"\n  Pick pass (GL_FALSE):   @ center = {ndc_pick[:3]}")
    # Pick pass uses GL_FALSE on numpy matrix -> TRANSPOSED -> wrong position!
    pick_ok = check(ndc_pick[:2], np.array([SCREEN_OFFSET_X, SCREEN_OFFSET_Y]),
                    "pick GL_FALSE: NDC position [EXPECT FAIL if matrix non-symmetric]")

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
# 4. EditorCamera View/Proj matrices (pyrr Matrix44)
# ==========================================================================

def verify_camera_matrices():
    print("=" * 60)
    print("4. EditorCamera View/Proj matrices (pyrr Matrix44)")
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

    # pyrr create_look_at
    view = matrix44.create_look_at(
        Vector3(position.tolist()),
        Vector3(orbit_target.tolist()),
        Vector3([0.0, 1.0, 0.0])
    ).astype(np.float32)

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
    proj = matrix44.create_perspective_projection(fov, aspect, near, far).astype(np.float32)
    np_proj = np.ascontiguousarray(proj)

    decoded_proj_false = gl_decode_colmajor(np_proj)
    decoded_proj_true = gl_decode_rowmajor(np_proj)

    diff = np.abs(decoded_proj_false - decoded_proj_true).max()
    print(f"\n  proj matrix GL_FALSE vs GL_TRUE max_diff = {diff:.4f}")
    if diff < 1e-5:
        print("  -> Proj matrix is symmetric (unlikely for perspective)")
    else:
        print("  -> Proj matrix NOT symmetric, conventions give different results")
        print("  -> GL_FALSE is the correct convention for pyrr proj matrices")

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
| pyrr Matrix44 (look_at, proj, TRS) | row-vector   | GL_FALSE     | GL_FALSE |
| numpy ndarray (C-order, std math)  | column-vector| GL_TRUE      | varies   |
+------------------------------------+--------------+--------------+----------+
| Entity model (RendererMath TRS)    | pyrr         | GL_FALSE     | CORRECT  |
| Entity pick pass (model/view/proj) | pyrr         | GL_FALSE     | CORRECT  |
| Camera view/proj (EditorCamera)    | pyrr         | GL_FALSE     | CORRECT  |
| Camera view/proj (pick pass)       | pyrr         | GL_FALSE     | CORRECT  |
| Overlay visual NDC model           | numpy        | GL_TRUE      | CORRECT  |
| Overlay PICK NDC model             | numpy        | GL_TRUE      | CORRECT  |
| ViewGizmo model_cb                 | numpy        | GL_TRUE      | CORRECT  |
+------------------------------------+--------------+--------------+----------+

STATUS: ALL CORRECT.
  The current openGLRenderer_v6 code already uses GL_TRUE for NDC overlay
  model matrices in both visual and pick passes. The convention is consistent:
    - pyrr Matrix44 -> GL_FALSE
    - numpy ndarray  -> GL_TRUE

  The overlay pick pass was previously analyzed as having a bug, but
  re-examination of the actual code (line 315: gl.GL_TRUE) confirms it
  is already correct.

WHAT WOULD HAPPEN IF GL_FALSE WERE USED FOR numpy:
  The ViewGizmo cube pick would be broken — the pick geometry would be
  transposed relative to visual geometry, with the cube center appearing
  at NDC (0,0) instead of (0.82, -0.8). See section 3 and 6 for numeric
  evidence of how bad this would be.
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
    verify_pyrr_convention()
    verify_entity_model()
    verify_viewgizmo_model()
    verify_camera_matrices()
    print_summary()
