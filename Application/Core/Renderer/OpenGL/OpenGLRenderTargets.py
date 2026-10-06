"""OpenGLRenderTargets — 渲染目标 (FBO) 管理 (组合到 OpenGLRenderer)。

职责:
  - 创建/销毁离屏渲染目标: 颜色纹理 (RGBA8) + 可选深度缓冲 (DEPTH24)
  - 将颜色纹理按 rt_id 注册进纹理注册表 — 材质 `texture_id_list` 直接引用采样
  - 场景目标切换: 实体/后处理/overlay 输出重定向 (0 = 屏幕)

设计约束 (协议: Doc/Dev/rendering_protocol.md §7):
  - rt_id 同时是纹理 ID — 注册进 registered_textures + loaded_texture('rt:<id>'),
    材质 texture_id_list 传该 id 即可采样; 纹理名形如 "rt:<id>"。
  - 销毁时级联清理 GL 对象与两个注册表条目。
  - 不负责 Y 翻转 — GL 纹理原点在左下; 用全屏 quad 展示时按需翻转 (协议 §7.3)。
"""

from __future__ import annotations

import numpy as np
from OpenGL import GL as gl


class OpenGLRenderTargets:
    """渲染目标池 — 创建/销毁/查询 + 场景目标切换状态。"""

    def __init__(self, renderer) -> None:
        self._renderer = renderer
        self.targets: dict[int, dict] = {}   # rt_id → {fbo, tex, depth_rb, width, height, with_depth}

    # ════════════════════════════════════════════════════════════
    # 查询
    # ════════════════════════════════════════════════════════════

    def get(self, rt_id: int) -> dict | None:
        """返回渲染目标记录 (不存在返回 None; rt_id=0 → None)。"""
        try:
            rid = int(rt_id)
        except (TypeError, ValueError):
            return None
        if rid == 0:
            return None
        return self.targets.get(rid)

    # ════════════════════════════════════════════════════════════
    # 创建 / 销毁
    # ════════════════════════════════════════════════════════════

    def create(
        self,
        rt_id: int,
        width: int,
        height: int,
        with_depth: bool = True,
    ) -> dict:
        """创建渲染目标 — 同 id 已存在时先销毁旧目标 (重建语义)。"""
        r = self._renderer
        rt_id = int(rt_id)
        width = int(width)
        height = int(height)
        if rt_id <= 0 or width <= 0 or height <= 0:
            raise ValueError(
                f"invalid render target params: id={rt_id} size={width}x{height}")

        if rt_id in self.targets:
            self.destroy(rt_id)

        # ── 颜色纹理 (RGBA8) ──
        tex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
        gl.glTexImage2D(
            gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, width, height, 0,
            gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)

        # ── FBO + 深度缓冲 ──
        fbo = gl.glGenFramebuffers(1)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, fbo)
        gl.glFramebufferTexture2D(
            gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0, gl.GL_TEXTURE_2D, tex, 0)
        depth_rb = 0
        if with_depth:
            depth_rb = gl.glGenRenderbuffers(1)
            gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, depth_rb)
            gl.glRenderbufferStorage(
                gl.GL_RENDERBUFFER, gl.GL_DEPTH_COMPONENT24, width, height)
            gl.glFramebufferRenderbuffer(
                gl.GL_FRAMEBUFFER, gl.GL_DEPTH_ATTACHMENT, gl.GL_RENDERBUFFER, depth_rb)
        status = gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, 0)

        if status != gl.GL_FRAMEBUFFER_COMPLETE:
            # ── 失败清理, 不留半成品 ──
            if depth_rb:
                gl.glDeleteRenderbuffers(1, [depth_rb])
            gl.glDeleteFramebuffers(1, [fbo])
            gl.glDeleteTextures(1, [tex])
            raise RuntimeError(
                f"render target FBO incomplete: id={rt_id} status=0x{status:X}")

        record = {
            "fbo": fbo,
            "tex": tex,
            "depth_rb": depth_rb,
            "width": width,
            "height": height,
            "with_depth": bool(with_depth),
        }
        self.targets[rt_id] = record

        # ── 注册为可直接采样的纹理 (rt_id 即纹理 ID) ──
        r.registered_textures[rt_id] = r._resources.texture_data_struct(
            ref_count=1, gl_handle=tex, texture_unit=-1)
        try:
            from Application.Resource.ResourceManager import ResourceManager
            from Application.Resource.Material import Texture
            ResourceManager.loaded_texture[str(rt_id)] = {
                "name": f"rt:{rt_id}",
                "data": Texture(width=width, height=height, channels=4),
                "builtin_name": None,
            }
        except Exception:  # noqa: BLE001 — 注册表条目失败不影响渲染
            pass
        return record

    def destroy(self, rt_id: int) -> bool:
        """销毁渲染目标 — 级联清理 GL 对象 + 纹理注册表条目。"""
        rt_id = int(rt_id)
        record = self.targets.pop(rt_id, None)
        if record is None:
            return False
        r = self._renderer

        gl.glDeleteFramebuffers(1, [record["fbo"]])
        gl.glDeleteTextures(1, [record["tex"]])
        if record["depth_rb"]:
            gl.glDeleteRenderbuffers(1, [record["depth_rb"]])

        # ── 纹理注册表条目 (仅清理本目标持有的 gl_handle, 防误删重名条目) ──
        tex_entry = r.registered_textures.get(rt_id)
        if tex_entry is not None and tex_entry.gl_handle == record["tex"]:
            del r.registered_textures[rt_id]
        try:
            from Application.Resource.ResourceManager import ResourceManager
            entry = ResourceManager.loaded_texture.get(str(rt_id))
            if entry is not None and str(entry.get("name", "")).startswith("rt:"):
                del ResourceManager.loaded_texture[str(rt_id)]
        except Exception:  # noqa: BLE001
            pass

        # ── 场景目标指向被销毁对象 → 回退屏幕 ──
        if getattr(r, "_scene_target_id", 0) == rt_id:
            r._scene_target_id = 0
        return True
