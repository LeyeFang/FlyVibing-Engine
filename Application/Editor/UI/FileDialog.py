"""文件对话框 — 基于 imgui_bundle 内置的 portable_file_dialogs。

原生 OS 对话框 (Windows / macOS / Linux)，非阻塞、渲染线程直接调用。
推荐程度高于 ImFileDialog（后者需要 immapp.run() 且不支持高 DPI）。

使用方式:
    from Application.Editor.UI.FileDialog import FileDialog

    # 1. 菜单点击时打开
    FileDialog.open_mesh(ImportService.load_mesh)

    # 2. 每帧在 UIManager.draw_all 末尾调用 (poll ready)
    FileDialog.render()
"""

from __future__ import annotations

from typing import Callable, Optional

from imgui_bundle import portable_file_dialogs as pfd


# ── 文件类型过滤器 ──────────────────────────────────────────────
# portable_file_dialogs 格式: [描述, 模式, 描述, 模式, ...]

MESH_FILTERS: list[str] = [
    "3D Models",
    "*.obj *.gltf *.glb *.fbx *.stl *.ply *.dae *.3ds",
    "All Files",
    "*",
]

TEXTURE_FILTERS: list[str] = [
    "Images",
    "*.png *.jpg *.jpeg *.bmp *.tga *.tiff *.hdr *.exr",
    "All Files",
    "*",
]

SHADER_FILTERS: list[str] = [
    "Shaders",
    "*.vert *.frag *.shader",
    "All Files",
    "*",
]


class FileDialog:
    """原生 OS 文件对话框 — 非阻塞，轮询 ready() 获取结果。"""

    # 内部状态
    _active_dialog: Optional[pfd.open_file] = None
    _callback: Optional[Callable[[str], None]] = None

    # ============================================================
    # 打开对话框 (渲染线程调用)
    # ============================================================

    @classmethod
    def open_mesh(
        cls,
        callback: Callable[[str], None],
        start_dir: str = ".",
    ) -> None:
        """打开"导入网格"对话框。"""
        cls._active_dialog = pfd.open_file(
            "Import 3D Model",
            start_dir,
            MESH_FILTERS,
            pfd.opt.none,
        )
        cls._callback = callback

    @classmethod
    def open_texture(
        cls,
        callback: Callable[[str], None],
        start_dir: str = ".",
    ) -> None:
        """打开"导入纹理"对话框。"""
        cls._active_dialog = pfd.open_file(
            "Import Texture",
            start_dir,
            TEXTURE_FILTERS,
            pfd.opt.none,
        )
        cls._callback = callback

    @classmethod
    def open_shader(
        cls,
        callback: Callable[[str], None],
        start_dir: str = ".",
    ) -> None:
        """打开"导入着色器"对话框。"""
        cls._active_dialog = pfd.open_file(
            "Import Shader",
            start_dir,
            SHADER_FILTERS,
            pfd.opt.none,
        )
        cls._callback = callback

    # ============================================================
    # 每帧轮询 (在 UIManager.draw_all 末尾调用)
    # ============================================================

    @classmethod
    def render(cls) -> None:
        """每帧调用: 检查原生对话框是否完成。

        当用户关闭对话框时，触发 callback(path) 或丢弃。
        放在 UIManager.draw_all() 末尾即可。
        """
        if cls._active_dialog is None:
            return

        if cls._active_dialog.ready():
            results: list[str] = cls._active_dialog.result()
            if results and len(results) > 0:
                path = results[0]
                if cls._callback:
                    cls._callback(path)
            cls._active_dialog = None
            cls._callback = None
