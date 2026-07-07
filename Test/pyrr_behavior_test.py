"""
独立测试 pyrr 矩阵库的行为：行/列主序、Euler 参数顺序、numpy 兼容性。
运行: python Test/pyrr_behavior_test.py
"""
from pyrr import Matrix44, Vector3
import numpy as np

# ═══════════════════════════════════════════════════════
# 测试 1: 位移在哪一行/列？
# ═══════════════════════════════════════════════════════
print("=" * 60)
print("测试 1: 位移位置 (row-vector vs col-vector)")
print("=" * 60)

t = Matrix44.from_translation(Vector3([10, 20, 30]))
print("from_translation([10,20,30]):")
print(np.asarray(t))
print()

# v @ M (行向量) vs M @ v (列向量)
v = np.array([0.0, 0.0, 0.0, 1.0])
v_row = v @ np.asarray(t)       # 行向量 × 矩阵
v_col = np.asarray(t) @ v       # 矩阵 × 列向量

print(f"  (0,0,0,1) @ M  = {v_row[:3]}")
print(f"  M @ (0,0,0,1)  = {v_col[:3]}")
print(f"  期望: [10, 20, 30]")

is_row = np.allclose(v_row[:3], [10, 20, 30])
print(f"  结论: pyrr 是 {'行向量 (row-vector)' if is_row else '列向量 (col-vector)'} 约定")
print()

# ═══════════════════════════════════════════════════════
# 测试 2: from_eulers 的参数顺序 (ZYX?)
# ═══════════════════════════════════════════════════════
print("=" * 60)
print("测试 2: from_eulers([a,b,c]) 的参数顺序")
print("=" * 60)
print("  local_forward = (0,0,-1)")
print()


def test_euler(name, rz_deg, ry_deg, rx_deg):
    m = Matrix44.from_eulers(Vector3([
        np.radians(rz_deg), np.radians(ry_deg), np.radians(rx_deg),
    ]))
    fwd = (np.array([0.0, 0.0, -1.0, 0.0]) @ np.asarray(m))[:3]
    print(f"  {name}: a(Z)={rz_deg:3d}  b(Y)={ry_deg:3d}  c(X)={rx_deg:3d}"
          f"  →  fwd=[{fwd[0]:6.2f}, {fwd[1]:6.2f}, {fwd[2]:6.2f}]")


test_euler("仅 Z+90   ", 90, 0, 0)    # 绕 forward 滚转, fwd 应不变
test_euler("仅 Y+90   ", 0, 90, 0)    # 绕 Y → -Z 应转到 +X
test_euler("仅 Y-90   ", 0, -90, 0)   # 绕 Y → -Z 应转到 -X
test_euler("仅 X+90   ", 0, 0, 90)    # 绕 X → -Z 应转到 +Y
test_euler("仅 X-90   ", 0, 0, -90)   # 绕 X → -Z 应转到 -Y
test_euler("Z90+Y90   ", 90, 90, 0)   # 先 Z 转再 Y 转
test_euler("Y90+X90   ", 0, 90, 90)   # 先 Y 转再 X 转

print()
print("  解读:")
print("    仅 Y+90: (0,0,-1) 应绕 Y 轴转到 (+1,0,0)")
print("    仅 X+90: (0,0,-1) 应绕 X 轴转到 (0,+1,0)")
print("    仅 Z+90: (0,0,-1) 应不变 (绕 forward 滚转)")
print("    参数顺序结论: from_eulers([a,b,c]) = Z(a) @ Y(b) @ X(c)")
print()

# ═══════════════════════════════════════════════════════
# 测试 3: scale 是否影响变换
# ═══════════════════════════════════════════════════════
print("=" * 60)
print("测试 3: 缩放")
print("=" * 60)

s = Matrix44.from_scale(Vector3([2, 3, 4]))
v3 = np.array([1.0, 1.0, 1.0, 1.0])
v3_row = v3 @ np.asarray(s)
v3_col = np.asarray(s) @ v3
print(f"  (1,1,1,1) @ scale(2,3,4) = {v3_row[:3]}")
print(f"  scale(2,3,4) @ (1,1,1,1) = {v3_col[:3]}")
print(f"  期望: [2, 3, 4]")
print(f"  结论: 缩放与位移一致，都是 {'行向量' if np.allclose(v3_row[:3], [2,3,4]) else '列向量'}")

# ═══════════════════════════════════════════════════════
# 测试 4: pyrr 对象与 numpy 的兼容性
# ═══════════════════════════════════════════════════════
print()
print("=" * 60)
print("测试 4: pyrr 对象 vs numpy")
print("=" * 60)

for name, obj in [("Vector3", Vector3([1.0, 2.0, 3.0])),
                   ("Matrix44", Matrix44.identity())]:
    print(f"  type({name}) = {type(obj)}")
    # dir(obj)
    try:
        result = np.linalg.norm(obj)
        print(f"    np.linalg.norm  : OK → {result}")
    except Exception as e:
        print(f"    np.linalg.norm  : FAIL → {type(e).__name__}")

    try:
        arr = np.asarray(obj)
        result = np.linalg.norm(arr)
        print(f"    via np.asarray  : OK → norm={result:.3f}")
    except Exception as e:
        print(f"    via np.asarray  : FAIL → {type(e).__name__}")

print()
print("  结论: 用 np.asarray(pyrr_obj) 转换后再用 numpy 函数")

# ═══════════════════════════════════════════════════════
# 测试 5: TRS 组合顺序
# ═══════════════════════════════════════════════════════
print()
print("=" * 60)
print("测试 5: TRS 组合 (T @ R @ S)")
print("=" * 60)

# 模拟 calculate_entity_model 的逻辑
pos = Vector3([5, 0, 0])          # 右移 5
rot = Vector3([0, 0, 0])          # 无旋转
scl = Vector3([2, 1, 1])          # X 放大 2 倍

t_mat = Matrix44.from_translation(pos)
r_mat = Matrix44.from_eulers(rot)
s_mat = Matrix44.from_scale(scl)

trs = t_mat * r_mat * s_mat
print(f"  T(5,0,0) * R(0) * S(2,1,1):")
print(np.asarray(trs))

pt = np.array([1.0, 0.0, 0.0, 1.0])   # 在模型空间 X=1 的点
ptr = pt @ np.asarray(trs)
print(f"  (1,0,0,1) @ TRS = {ptr[:3]}  (期望: [7,0,0] = 5 + 2*1)")
print(f"  组合顺序: trans * rot * scale → 先缩放, 再旋转, 再平移")

print()
print("=" * 60)
print("全部测试完成")
print("=" * 60)
