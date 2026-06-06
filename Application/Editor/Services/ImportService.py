"""ImportService — 资源导入服务，纯逻辑，零状态。

FileDialog 打开对话框 → 用户选择文件 → 回调到此服务加载资源。

职责:
  - 封装 ResourceManager 的导入调用
  - 统一日志 / 错误处理
  - 与 UI 和线程模型完全解耦

使用方式:
    from Application.Editor.Services.ImportService import ImportService

    # FileDialog 回调中使用:
    FileDialog.open_mesh(ImportService.load_mesh)
"""

from __future__ import annotations

from Application.Resource.ResourceManager import ResourceManager


class ImportService:
    """资源导入服务 — 纯静态方法，无状态。"""

    @classmethod
    def load_mesh(cls, path: str) -> None:
        """导入网格文件到 ResourceManager。由 FileDialog 回调。"""
        try:
            mesh_id = ResourceManager.ImportMesh(path)
            print(f"[Import] Mesh #{mesh_id}: {path}")
        except Exception as e:
            print(f"[Import] Mesh failed: {e}")

    @classmethod
    def load_texture(cls, path: str) -> None:
        """导入纹理文件到 ResourceManager。由 FileDialog 回调。"""
        try:
            tex_id = ResourceManager.ImportTexture(path)
            print(f"[Import] Texture #{tex_id}: {path}")
        except Exception as e:
            print(f"[Import] Texture failed: {e}")

    @classmethod
    def load_shader(cls, path: str) -> None:
        """导入着色器文件到 ResourceManager。由 FileDialog 回调。"""
        try:
            shader_id = ResourceManager.LoadAssets(path)
            print(f"[Import] Shader #{shader_id}: {path}")
        except Exception as e:
            print(f"[Import] Shader failed: {e}")

