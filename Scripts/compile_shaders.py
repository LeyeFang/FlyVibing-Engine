"""
编译 GLSL 着色器 → SPIR-V 二进制。

用法:
    python Scripts/compile_shaders.py

扫描 Resource/Shaders/Builtin/ 下所有 .vert 和 .frag 文件，
调用 glslc 编译为 .vert.spv / .frag.spv。
"""

import subprocess
import os
import shutil
import sys

SHADER_DIR = os.path.join(os.path.dirname(__file__), "..", "Resource", "Shaders", "Builtin")


def find_glslc():
    """查找 glslc 编译器。"""
    # ① PATH
    glslc = shutil.which("glslc")
    if glslc:
        return glslc
    # ② 常见 Vulkan SDK 路径
    for base in [r"C:\VulkanSDK", r"C:\Program Files\VulkanSDK"]:
        if os.path.isdir(base):
            for ver in sorted(os.listdir(base), reverse=True):
                path = os.path.join(base, ver, "Bin", "glslc.exe")
                if os.path.isfile(path):
                    return path
    # ③ 环境变量
    sdk = os.environ.get("VULKAN_SDK", "")
    if sdk:
        path = os.path.join(sdk, "Bin", "glslc.exe")
        if os.path.isfile(path):
            return path
    raise RuntimeError("未找到 glslc，请安装 Vulkan SDK 或将其加入 PATH")


def main():
    os.chdir(SHADER_DIR)
    glslc = find_glslc()
    print(f"[glslc] {glslc}")

    compiled, failed = 0, 0
    for f in sorted(os.listdir(".")):
        if f.endswith(".vert") or f.endswith(".frag"):
            out = f + ".spv"
            print(f"  Compiling {f} ...", end=" ")
            r = subprocess.run([glslc, f, "-o", out], capture_output=True, text=True)
            if r.returncode == 0:
                print("OK")
                compiled += 1
            else:
                print(f"FAILED\n{r.stderr}")
                failed += 1

    print(f"\nDone: {compiled} compiled, {failed} failed")
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
