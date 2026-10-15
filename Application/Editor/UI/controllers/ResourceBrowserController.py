"""资源浏览器 — 已加载资源列表查询 + CRUD"""
from typing import Any

from Application.Resource.ResourceManager import ResourceManager


class ResourceBrowserController:
    """查询已加载的 Mesh / Shader / Texture / Material — 纯数据层"""

    # ── 资源类型常量 ────────────────────────────────────────
    TYPE_MESH     = "mesh"
    TYPE_SHADER   = "shader"
    TYPE_TEXTURE  = "texture"
    TYPE_MATERIAL = "material"
    TYPE_PREFAB   = "prefab"

    @classmethod
    def get_resource_types(cls) -> list[str]:
        return [cls.TYPE_MESH, cls.TYPE_SHADER, cls.TYPE_TEXTURE,
                cls.TYPE_MATERIAL, cls.TYPE_PREFAB]

    # ── 分类查询 ────────────────────────────────────────────

    @classmethod
    def get_meshes(cls) -> dict[str, dict[str, Any]]:
        return dict(ResourceManager.loaded_mesh)

    @classmethod
    def get_shaders(cls) -> dict[str, dict[str, Any]]:
        return dict(ResourceManager.loaded_shader)

    @classmethod
    def get_textures(cls) -> dict[str, dict[str, Any]]:
        return dict(ResourceManager.loaded_texture)

    @classmethod
    def get_materials(cls) -> dict[str, dict[str, Any]]:
        return dict(ResourceManager.loaded_material)

    # ── 便捷方法 ────────────────────────────────────────────

    @classmethod
    def get_resource_name(cls, resource: dict[str, Any]) -> str:
        return resource.get("name", "unnamed")

    # ── 统一资源查询 (供 Asset Browser 使用) ─────────────────

    @classmethod
    def get_all_resources(cls, filter_type: str | None = None) -> list[dict]:
        """返回所有已注册资源的统一列表。

        每项包含: id, name, type, path, extra
        """
        result = []

        if filter_type is None or filter_type == cls.TYPE_MESH:
            for id_str, data in list(ResourceManager.loaded_mesh.items()):
                result.append({
                    'id': int(id_str),
                    'name': data.get('name', 'unnamed'),
                    'type': cls.TYPE_MESH,
                    'path': data.get('path', ''),
                })

        if filter_type is None or filter_type == cls.TYPE_SHADER:
            for id_str, data in list(ResourceManager.loaded_shader.items()):
                result.append({
                    'id': int(id_str),
                    'name': data.get('name', 'unnamed'),
                    'type': cls.TYPE_SHADER,
                    'path': data.get('path', ''),
                })

        if filter_type is None or filter_type == cls.TYPE_TEXTURE:
            for id_str, data in list(ResourceManager.loaded_texture.items()):
                result.append({
                    'id': int(id_str),
                    'name': data.get('name', 'unnamed'),
                    'type': cls.TYPE_TEXTURE,
                    'path': data.get('path', ''),
                })

        if filter_type is None or filter_type == cls.TYPE_MATERIAL:
            for id_str, mat in list(ResourceManager.loaded_material.items()):
                mid = int(id_str)
                mat_name = getattr(mat, 'name', '') or f"Material #{mid}"
                # ★ 过滤内部 clone（xxx_copy），只显示用户创建的材质
                if mat_name.endswith("_copy"):
                    continue
                shader_id = getattr(mat, 'shader_id', '?')
                result.append({
                    'id': mid,
                    'name': mat_name,
                    'type': cls.TYPE_MATERIAL,
                    'path': f"Shader: {shader_id}",
                })

        if filter_type is None or filter_type == cls.TYPE_PREFAB:
            for id_str, pdata in list(ResourceManager.loaded_prefab.items()):
                pid = int(id_str)
                p_name = pdata.get('name', '') or f"Prefab #{pid}"
                result.append({
                    'id': pid,
                    'name': p_name,
                    'type': cls.TYPE_PREFAB,
                    'path': pdata.get('path', ''),
                })

        return result

    @classmethod
    def get_resource_count_by_type(cls) -> dict[str, int]:
        """返回各类型资源数量统计。"""
        return {
            cls.TYPE_MESH:     len(ResourceManager.loaded_mesh),
            cls.TYPE_SHADER:   len(ResourceManager.loaded_shader),
            cls.TYPE_TEXTURE:  len(ResourceManager.loaded_texture),
            cls.TYPE_MATERIAL: len(ResourceManager.loaded_material),
            cls.TYPE_PREFAB:   len(ResourceManager.loaded_prefab),
        }

    # ── 资源 CRUD ───────────────────────────────────────────

    @classmethod
    def delete_resource(cls, resource_type: str, resource_id: int) -> bool:
        """根据类型和 ID 删除资源。返回是否成功。"""
        try:
            if resource_type == cls.TYPE_MESH:
                return ResourceManager.DeleteMesh(resource_id)
            elif resource_type == cls.TYPE_SHADER:
                return ResourceManager.DeleteShader(resource_id)
            elif resource_type == cls.TYPE_TEXTURE:
                return ResourceManager.DeleteTexture(resource_id)
            elif resource_type == cls.TYPE_MATERIAL:
                return ResourceManager.DeleteMaterial(resource_id)
            elif resource_type == cls.TYPE_PREFAB:
                return ResourceManager.DeletePrefab(resource_id)
        except RuntimeError as e:
            print(f"[Resource] Delete blocked: {e}")
            return False
        return False

    @classmethod
    def new_material(cls) -> int:
        """创建新材质。返回 material_id。"""
        return ResourceManager.NewMaterial()

    @classmethod
    def load_prefab(cls, filepath: str) -> int | None:
        """导入 .prefab 文件到 ResourceManager。返回 prefab_id 或 None。"""
        return ResourceManager.LoadPrefab(filepath)

    @classmethod
    def instantiate_prefab(cls, prefab_id: int) -> list[int]:
        """将指定 prefab 实例化到当前场景。返回新创建的 entity ID 列表。"""
        from Application.Core.Scene.PrefabManager import PrefabManager
        from Application.Editor.EditorHost import EditorHost
        pdata = ResourceManager.loaded_prefab.get(str(prefab_id))
        if pdata is None or pdata.get('prefab_data') is None:
            print(f"[Resource] Prefab #{prefab_id} not found or not loaded")
            return []
        prefab_data = pdata['prefab_data']
        eids = PrefabManager.instantiate_to_scene(prefab_data, EditorHost.scene)

        # ★ 注册新实体的 MeshRenderer 到 GPU
        cls._register_mesh_entities(eids)
        return eids

    @classmethod
    def _register_mesh_entities(cls, eids: list[int]) -> None:
        """将指定 entity 列表中的 MeshRenderer 注册到 GPU。"""
        try:
            import esper
            from Application.Core.Scene.BasicComponents import MeshRenderer
            from Application.Core.Renderer.RenderCommand import EntityRegistrationCommand
            from Application.Editor.EditorHost import EditorHost
            renderer = EditorHost.get_editor_renderer()
            if renderer is None:
                return
            for eid in eids:
                try:
                    if esper.has_component(eid, MeshRenderer):
                        renderer.enqueue(EntityRegistrationCommand(eid, register=True))
                except KeyError:
                    pass
        except Exception:
            pass

    # ── 选项列表 (供 Combo/下拉使用) ──────────────────────────

    @classmethod
    def get_mesh_options(cls) -> list[tuple[int, str]]:
        """返回 [(mesh_id, name), ...] 列表，供下拉选择用。"""
        result = []
        for id_str, data in list(ResourceManager.loaded_mesh.items()):
            result.append((int(id_str), data.get("name", "unnamed")))
        return result

    @classmethod
    def get_material_options(cls) -> list[tuple[int, str]]:
        """返回 [(material_id, label), ...] 列表，供下拉选择用。过滤内部 clone。"""
        result = []
        for id_str, data in list(ResourceManager.loaded_material.items()):
            mid = int(id_str)
            mat_name = getattr(data, 'name', '') or f"Material #{mid}"
            if mat_name.endswith("_copy"):
                continue  # ★ 过滤内部 clone
            result.append((mid, mat_name))
        return result

    @classmethod
    def get_shader_options(cls) -> list[tuple[int, str]]:
        """返回 [(shader_id, name), ...] 列表。"""
        result = []
        for id_str, data in list(ResourceManager.loaded_shader.items()):
            result.append((int(id_str), data.get("name", "unnamed")))
        return result

    @classmethod
    def get_texture_options(cls) -> list[tuple[int, str]]:
        """返回 [(texture_id, name), ...] 列表。"""
        result = []
        for id_str, data in list(ResourceManager.loaded_texture.items()):
            result.append((int(id_str), data.get("name", "unnamed")))
        return result

# ── 注册到 ControllerRegistry（供 Panel 通过名称查找） ──
from Application.Editor.Services.ControllerRegistry import register, NAME_RESOURCE_BROWSER
register(NAME_RESOURCE_BROWSER, ResourceBrowserController)
