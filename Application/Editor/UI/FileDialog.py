"""文件对话框 — 基于 imgui_bundle 内置的 portable_file_dialogs。

原生 OS 对话框 (Windows / macOS / Linux)，非阻塞、渲染线程直接调用。
推荐程度高于 ImFileDialog（后者需要 immapp.run() 且不支持高 DPI）。

使用方式:
    from Application.Editor.UI.FileDialog import FileDialog

    # 1. 菜单点击时打开
    FileDialog.open_mesh(ImportService.load_mesh)

    # 2. 每帧在 UIManager.draw_all 末尾调用 (poll ready)
    FileDialog.render()

目录记忆:
    通过 .editor_cache.json 记录每种对话框上次打开的目录，
    下次打开时自动定位到该目录，避免反复在复杂文件结构中导航。
"""

from __future__ import annotations

import json
import os
from typing import Callable, Optional, Union

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

JSON_FILTERS: list[str] = [
    "JSON Files",
    "*.json",
    "All Files",
    "*",
]

PREFAB_FILTERS: list[str] = [
    "Prefab Files",
    "*.prefab",
    "All Files",
    "*",
]

MAT_FILTERS: list[str] = [
    "Material Files",
    "*.mat",
    "All Files",
    "*",
]

SCENE_FILTERS: list[str] = [
    "Scene Files",
    "*.scene",
    "All Files",
    "*",
]

PROJ_FILTERS: list[str] = [
    "Project Files",
    "*.myproj",
    "All Files",
    "*",
]


# ════════════════════════════════════════════════════════════════
# 目录记忆 — 轻量 JSON 持久化
# ════════════════════════════════════════════════════════════════

def _cache_path() -> str:
    """返回缓存文件路径 (Application/Editor/Config/.editor_cache.json)。"""
    # FileDialog.py 位于 Application/Editor/UI/
    # Config 目录 = 向上 1 级 + Config/
    this_dir = os.path.dirname(os.path.abspath(__file__))
    config_dir = os.path.normpath(os.path.join(this_dir, "..", "Config"))
    return os.path.join(config_dir, ".editor_cache.json")


class _DialogMemory:
    """读取/写入文件对话框目录记忆（线程安全由 GIL 保证）。"""

    _cache: dict[str, str] = {}
    _loaded: bool = False

    @classmethod
    def _ensure_loaded(cls) -> None:
        if cls._loaded:
            return
        cls._loaded = True
        path = _cache_path()
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                cls._cache = {
                    k: v for k, v in data.items()
                    if isinstance(v, str) and os.path.isdir(v)
                }
        except (OSError, json.JSONDecodeError):
            pass  # 缓存损坏，丢弃即可

    @classmethod
    def get_dir(cls, dialog_type: str, fallback: str = ".") -> str:
        """获取指定类型对话框的上次目录。"""
        cls._ensure_loaded()
        d = cls._cache.get(dialog_type)
        if d and os.path.isdir(d):
            return d
        return fallback

    @classmethod
    def set_dir(cls, dialog_type: str, directory: str) -> None:
        """记录指定类型对话框的目录并持久化。"""
        cls._ensure_loaded()
        if not directory or not os.path.isdir(directory):
            return
        if cls._cache.get(dialog_type) == directory:
            return  # 没变化，跳过写入
        cls._cache[dialog_type] = directory
        cls._save()

    @classmethod
    def update_from_file_path(cls, dialog_type: str, file_path: str) -> None:
        """从用户选择的文件路径中提取父目录并记录。"""
        if not file_path:
            return
        parent = os.path.dirname(os.path.abspath(file_path))
        cls.set_dir(dialog_type, parent)

    @classmethod
    def _save(cls) -> None:
        path = _cache_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(cls._cache, fh, indent=2, ensure_ascii=False)
        except OSError:
            pass  # 写入失败不影响 UI


class FileDialog:
    """原生 OS 文件对话框 — 非阻塞，轮询 ready() 获取结果。

    自动记忆每种对话框的上次目录，通过 .editor_cache.json 持久化。
    """

    # 内部状态（open_file 或 save_file，接口兼容）
    _active_dialog: Optional[Union[pfd.open_file, pfd.save_file]] = None
    _callback: Optional[Callable[[str], None]] = None
    _active_type: str = ""   # 记录当前对话框类型，用于记忆目录

    # ============================================================
    # 打开对话框 (渲染线程调用)
    # ============================================================

    @classmethod
    def open_mesh(
        cls,
        callback: Callable[[str], None],
        start_dir: str | None = None,
    ) -> None:
        """打开"导入网格"对话框。"""
        d = start_dir if start_dir is not None else _DialogMemory.get_dir("mesh")
        cls._active_dialog = pfd.open_file(
            "Import 3D Model", d, MESH_FILTERS, pfd.opt.none,
        )
        cls._callback = callback
        cls._active_type = "mesh"

    @classmethod
    def open_texture(
        cls,
        callback: Callable[[str], None],
        start_dir: str | None = None,
    ) -> None:
        """打开"导入纹理"对话框。"""
        d = start_dir if start_dir is not None else _DialogMemory.get_dir("texture")
        cls._active_dialog = pfd.open_file(
            "Import Texture", d, TEXTURE_FILTERS, pfd.opt.none,
        )
        cls._callback = callback
        cls._active_type = "texture"

    @classmethod
    def open_shader(
        cls,
        callback: Callable[[str], None],
        start_dir: str | None = None,
    ) -> None:
        """打开"导入着色器"对话框。"""
        d = start_dir if start_dir is not None else _DialogMemory.get_dir("shader")
        cls._active_dialog = pfd.open_file(
            "Import Shader", d, SHADER_FILTERS, pfd.opt.none,
        )
        cls._callback = callback
        cls._active_type = "shader"

    @classmethod
    def open_json(
        cls,
        callback: Callable[[str], None],
        start_dir: str | None = None,
    ) -> None:
        """打开"导入 JSON"对话框。"""
        d = start_dir if start_dir is not None else _DialogMemory.get_dir("json_open")
        cls._active_dialog = pfd.open_file(
            "Import JSON", d, JSON_FILTERS, pfd.opt.none,
        )
        cls._callback = callback
        cls._active_type = "json_open"

    @classmethod
    def save_json(
        cls,
        callback: Callable[[str], None],
        start_dir: str | None = None,
        default_name: str = "graph.json",
    ) -> None:
        """打开"导出 JSON"保存对话框。"""
        d = start_dir if start_dir is not None else _DialogMemory.get_dir("json_save")
        cls._active_dialog = pfd.save_file(
            "Export JSON",
            os.path.join(d, default_name),
            JSON_FILTERS,
            pfd.opt.none,
        )
        cls._callback = callback
        cls._active_type = "json_save"

    @classmethod
    def open_prefab(
        cls,
        callback: Callable[[str], None],
        start_dir: str | None = None,
    ) -> None:
        """打开"导入 Prefab"对话框。"""
        d = start_dir if start_dir is not None else _DialogMemory.get_dir("prefab_open")
        cls._active_dialog = pfd.open_file(
            "Import Prefab", d, PREFAB_FILTERS, pfd.opt.none,
        )
        cls._callback = callback
        cls._active_type = "prefab_open"

    @classmethod
    def save_prefab(
        cls,
        callback: Callable[[str], None],
        start_dir: str | None = None,
        default_name: str = "NewPrefab.prefab",
    ) -> None:
        """打开"保存 Prefab"对话框。"""
        d = start_dir if start_dir is not None else _DialogMemory.get_dir("prefab_save")
        cls._active_dialog = pfd.save_file(
            "Save Prefab",
            os.path.join(d, default_name),
            PREFAB_FILTERS,
            pfd.opt.none,
        )
        cls._callback = callback
        cls._active_type = "prefab_save"

    @classmethod
    def open_mat(
        cls,
        callback: Callable[[str], None],
        start_dir: str | None = None,
    ) -> None:
        """打开"导入材质"对话框。"""
        d = start_dir if start_dir is not None else _DialogMemory.get_dir("mat")
        cls._active_dialog = pfd.open_file(
            "Load Material", d, MAT_FILTERS, pfd.opt.none,
        )
        cls._callback = callback
        cls._active_type = "mat"

    @classmethod
    def save_mat(
        cls,
        callback: Callable[[str], None],
        start_dir: str | None = None,
        default_name: str = "material.mat",
    ) -> None:
        """打开"保存材质"对话框。"""
        d = start_dir if start_dir is not None else _DialogMemory.get_dir("mat_save")
        cls._active_dialog = pfd.save_file(
            "Save Material",
            os.path.join(d, default_name),
            MAT_FILTERS,
            pfd.opt.none,
        )
        cls._callback = callback
        cls._active_type = "mat_save"

    @classmethod
    def open_scene(
        cls,
        callback: Callable[[str], None],
        start_dir: str | None = None,
    ) -> None:
        """打开"加载场景"对话框。"""
        d = start_dir if start_dir is not None else _DialogMemory.get_dir("scene_open")
        cls._active_dialog = pfd.open_file(
            "Open Scene", d, SCENE_FILTERS, pfd.opt.none,
        )
        cls._callback = callback
        cls._active_type = "scene_open"

    @classmethod
    def save_scene(
        cls,
        callback: Callable[[str], None],
        start_dir: str | None = None,
        default_name: str = "Untitled.scene",
    ) -> None:
        """打开"保存场景"对话框。"""
        d = start_dir if start_dir is not None else _DialogMemory.get_dir("scene_save")
        cls._active_dialog = pfd.save_file(
            "Save Scene",
            os.path.join(d, default_name),
            SCENE_FILTERS,
            pfd.opt.none,
        )
        cls._callback = callback
        cls._active_type = "scene_save"

    @classmethod
    def open_project(
        cls,
        callback: Callable[[str], None],
        start_dir: str | None = None,
    ) -> None:
        """打开"打开项目"对话框。"""
        d = start_dir if start_dir is not None else _DialogMemory.get_dir("project_open")
        cls._active_dialog = pfd.open_file(
            "Open Project", d, PROJ_FILTERS, pfd.opt.none,
        )
        cls._callback = callback
        cls._active_type = "project_open"

    @classmethod
    def save_project(
        cls,
        callback: Callable[[str], None],
        start_dir: str | None = None,
        default_name: str = "MyProject.myproj",
    ) -> None:
        """打开"保存项目"对话框。"""
        d = start_dir if start_dir is not None else _DialogMemory.get_dir("project_save")
        cls._active_dialog = pfd.save_file(
            "Save Project",
            os.path.join(d, default_name),
            PROJ_FILTERS,
            pfd.opt.none,
        )
        cls._callback = callback
        cls._active_type = "project_save"

    @classmethod
    def open_directory(
        cls,
        callback: Callable[[str], None],
        start_dir: str | None = None,
    ) -> None:
        """打开"选择目录"对话框（文件夹选择器）。"""
        d = start_dir if (start_dir and os.path.isdir(start_dir)) else _DialogMemory.get_dir("directory")
        cls._active_dialog = pfd.select_folder(
            "Select Directory", d, pfd.opt.none,
        )
        cls._callback = callback
        cls._active_type = "directory"

    @classmethod
    def open_export_dir(
        cls,
        callback: Callable[[str], None],
        start_dir: str | None = None,
    ) -> None:
        """打开"导出目标文件夹"选择对话框。

        选中目录作为导出父目录 — 导出时会在其下创建 <项目名>/ 子目录。
        """
        d = start_dir if (start_dir and os.path.isdir(start_dir)) else _DialogMemory.get_dir("export")
        cls._active_dialog = pfd.select_folder(
            "Export To Folder (a project subfolder will be created)", d, pfd.opt.none,
        )
        cls._callback = callback
        cls._active_type = "export"

    @classmethod
    def open_text(
        cls,
        callback: Callable[[str], None],
        start_dir: str | None = None,
    ) -> None:
        """打开"选择文本文件"对话框。"""
        d = start_dir if start_dir is not None else _DialogMemory.get_dir("text")
        cls._active_dialog = pfd.open_file(
            "Select Text File", d,
            ["Text Files", "*.txt *.csv *.log *.json", "All Files", "*"],
            pfd.opt.none,
        )
        cls._callback = callback
        cls._active_type = "text"

    # ============================================================
    # 每帧轮询 (在 UIManager.draw_all 末尾调用)
    # ============================================================

    @classmethod
    def render(cls) -> None:
        """每帧调用: 检查原生对话框是否完成。

        当用户关闭对话框时:
          1. 触发 callback(path)
          2. 记录所选文件的父目录到缓存
          3. 清理内部状态
        """
        if cls._active_dialog is None:
            return

        if cls._active_dialog.ready():
            raw = cls._active_dialog.result()
            # save_file 返回 str，open_file 返回 list[str]，统一处理
            if isinstance(raw, str):
                path = raw
            elif isinstance(raw, list) and len(raw) > 0:
                path = raw[0]
            else:
                path = ""

            if path and cls._callback:
                cls._callback(path)
                # ── 记住父目录 ──
                _DialogMemory.update_from_file_path(cls._active_type, path)

            cls._active_dialog = None
            cls._callback = None
            cls._active_type = ""
