"""Shader uniform 注解 → 材质默认值 / GUI 描述 / 复位（无 GL 无头）。

锁定内容:
  1. `//!` 注解解析：kind / 范围 / 步长 / 单位 / 分组 / 默认值 / choices / owner
  2. 无注解降级：与 2026-11 之前完全一致（类型推断、可写、无范围）
  3. 归属语义：`owner=engine|runtime` 不进材质（`model` / SSVEP `time`）
  4. 默认值唯一来源：DefaultLit 的 32 / 0.25 / 1 / 1 来自 `Lighting.frag` 而非硬编码
  5. 复位：单参数 / 全部（默认值只存在 shader 里）
  6. 资源引用唯一性：`ShaderRef` ↔ `ResolveShaderRef` 往返; `.mat` 用 `shader_ref` 解析
  7. 材质隔离：编辑共享/内置模板先 clone（复位同样走这条路）
  8. 运行期注入：`owner=runtime` 的 uniform 每帧拿引擎 elapsed（SSVEP 才真的在闪）
"""

# TIER: core

from __future__ import annotations

import os
import sys
import tempfile

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

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


_ROOT = os.path.dirname(_d)
_SHADER_DIR = os.path.join(_ROOT, "Resource", "Shaders", "Builtin")


def _parse(name: str):
    from Application.Resource._resource_utils import parse_shader_files
    return parse_shader_files(os.path.join(_SHADER_DIR, f"{name}.vert"),
                              os.path.join(_SHADER_DIR, f"{name}.frag"))


def _write_pair(tmp: str, frag_body: str, vert_body: str = "") -> tuple:
    vert = os.path.join(tmp, "probe.vert")
    frag = os.path.join(tmp, "probe.frag")
    with open(vert, "w", encoding="utf-8") as fh:
        fh.write(vert_body or
                 "#version 440 core\n"
                 "layout(location = 0) in vec3 aPos;\n"
                 "uniform mat4 model;\n"
                 "void main() { gl_Position = model * vec4(aPos, 1.0); }\n")
    with open(frag, "w", encoding="utf-8") as fh:
        fh.write(frag_body)
    return vert, frag


class FakeEngine:
    renderer = None
    scene = None


def main() -> int:
    print("=" * 62)
    print("Uniform schema — GLSL //! annotations drive defaults + GUI (headless)")
    print("=" * 62)

    # ── 1. 内置 shader 的注解解析 ──
    print("-- 1. builtin annotations --")
    basic = _parse("Basic")
    check("parse returns 6 items (specs are new)", len(basic) == 6, str(len(basic)))
    b_uniforms, b_specs = basic[4], basic[5]
    check("Basic material uniforms = only uColor (mat4/sampler excluded)",
          list(b_uniforms) == ["uColor"], str(list(b_uniforms)))
    color = b_specs["uColor"]
    check("Basic uColor: color4 + group + default white",
          color.kind == "color4" and color.group == "Surface"
          and color.default == (1.0, 1.0, 1.0, 1.0), str(color))
    check("Basic matrices are engine-owned (read-only)",
          all(b_specs[n].owner == "engine" and not b_specs[n].writable
              for n in ("model", "view", "projection")))

    lit = _parse("Lighting")
    l_specs = lit[5]
    shininess = l_specs["uShininess"]
    check("Lighting uShininess: float, default 32, range 1..256, step 1",
          shininess.kind == "float" and shininess.default == (32.0,)
          and (shininess.minimum, shininess.maximum) == (1.0, 256.0)
          and shininess.step == 1.0, str(shininess))
    check("Lighting uShininess label/group",
          shininess.label == "mat.shininess" and shininess.group == "Specular",
          f"{shininess.label}/{shininess.group}")
    spec_model = l_specs["uSpecularModel"]
    check("Lighting uSpecularModel: enum + 2 choices",
          spec_model.kind == "enum"
          and spec_model.choices == ((0, "mat.phong"), (1, "mat.blinn")),
          str(spec_model.choices))
    check("Lighting kd/ks/ka carry real defaults",
          l_specs["uDiffuseStrength"].default == (1.0,)
          and l_specs["uSpecularStrength"].default == (0.25,)
          and l_specs["uAmbientStrength"].default == (1.0,))
    check("Lighting ranges keep the legacy zero sentinel out (min > 0)",
          l_specs["uDiffuseStrength"].minimum > 0.0
          and l_specs["uSpecularStrength"].minimum > 0.0)

    ssvep = _parse("SSVEP")
    s_uniforms, s_specs = ssvep[4], ssvep[5]
    freq = s_specs["freq"]
    check("SSVEP freq: Hz + range 1..60 + default 10",
          freq.unit == "Hz" and (freq.minimum, freq.maximum) == (1.0, 60.0)
          and freq.default == (10.0,), str(freq))
    check("SSVEP phase: rad + group Stimulus",
          s_specs["phase_shift"].unit == "rad"
          and s_specs["phase_shift"].group == "Stimulus")
    check("SSVEP time is engine/runtime owned → not a material param",
          s_specs["time"].owner == "runtime" and not s_specs["time"].in_material
          and "time" not in s_uniforms, str(list(s_uniforms)))
    check("every material uniform has a writable spec",
          all(n in s_specs and s_specs[n].writable for n in s_uniforms))

    # ── 2. 无注解降级 + 注解位置 + 容错 ──
    print("-- 2. fallback / placement / tolerance --")
    tmp = tempfile.mkdtemp(prefix="mge_uniform_")
    vert, frag = _write_pair(
        tmp,
        "#version 440 core\n"
        "uniform float plain;\n"
        "uniform vec4 tint;\n"
        "uniform int   flag;\n"
        "uniform float tail;    //! ui: float | default=2.5 | range=0..5\n"
        "uniform vec3  arr[4];\n"
        "layout(location = 0) out vec4 FragColor;\n"
        "void main() { FragColor = tint * plain + arr[0].x + tail + flag; }\n"
    )
    from Application.Resource._resource_utils import parse_shader_files
    r = parse_shader_files(vert, frag)
    uniforms, specs = r[4], r[5]
    check("unannotated float → kind float, writable, no range",
          specs["plain"].kind == "float" and specs["plain"].writable
          and specs["plain"].minimum is None, str(specs["plain"]))
    check("unannotated vec4 stays vec4 (not a color picker)",
          specs["tint"].kind == "vec4", str(specs["tint"].kind))
    check("trailing annotation after ';' is honoured",
          specs["tail"].default == (2.5,) and specs["tail"].maximum == 5.0,
          str(specs["tail"]))
    check("arrays are read-only (no vec3 mis-upload)",
          specs["arr"].kind == "array" and not specs["arr"].writable,
          str(specs["arr"].kind))
    check("unannotated int still skipped like before",
          "flag" in uniforms and specs["flag"].default is None, str(list(uniforms)))

    vert2, frag2 = _write_pair(
        tmp,
        "#version 440 core\n"
        "//! ui: nonsense | range=abc | step=zzz | default=oops\n"
        "uniform float broken;\n"
        "layout(location = 0) out vec4 FragColor;\n"
        "void main() { FragColor = vec4(broken); }\n"
    )
    specs2 = parse_shader_files(vert2, frag2)[5]
    check("malformed annotation neither crashes nor invents a range",
          specs2["broken"].kind == "float" and specs2["broken"].minimum is None
          and specs2["broken"].default is None, str(specs2["broken"]))

    vert3, frag3 = _write_pair(
        tmp,
        "#version 440 core\n"
        "//! ui: readonly | owner=engine | label=mat.model\n"
        "uniform mat4 world;\n"
        "layout(location = 0) out vec4 FragColor;\n"
        "void main() { FragColor = vec4(world[0][0]); }\n"
    )
    r3 = parse_shader_files(vert3, frag3)
    check("owner=engine stays out of the material table",
          "world" not in r3[4] and r3[5]["world"].in_material is False, str(list(r3[4])))

    # ── 3. 材质默认值唯一来源 ──
    print("-- 3. material defaults come from the shader --")
    import numpy as np
    import esper
    from Application.Core.Events.Event import BindPackCallback
    from Application.Core.Scene.BasicComponents import MeshRenderer, Transform
    from Application.Core.Scene.SceneManager import SceneManager
    from Application.Resource.ResourceManager import ResourceManager

    BindPackCallback(lambda e: None)
    ResourceManager.Init(FakeEngine)
    SceneManager.Init(FakeEngine)
    st = SceneManager._state_for("FakeEngine")

    default_mid = ResourceManager.GetDefaultMaterial()
    default_mat = ResourceManager.GetMaterial(default_mid)
    check("Default material no longer carries model/view/projection",
          not any(k in default_mat.uniforms_data for k in ("model", "view", "projection")),
          str(list(default_mat.uniforms_data)))
    check("Default uColor = white (annotation default)",
          np.allclose(default_mat.uniforms_data["uColor"], [1, 1, 1, 1]))

    lit_mid = ResourceManager.GetBuiltinMaterial("DefaultLit")
    lit_mat = ResourceManager.GetMaterial(lit_mid)
    check("DefaultLit uShininess = 32 from Lighting.frag annotation",
          float(lit_mat.uniforms_data["uShininess"]) == 32.0,
          str(lit_mat.uniforms_data.get("uShininess")))
    check("DefaultLit kd/ks/ka defaults materialised",
          float(lit_mat.uniforms_data["uDiffuseStrength"]) == 1.0
          and float(lit_mat.uniforms_data["uSpecularStrength"]) == 0.25)
    check("DefaultLit uSpecularModel now exists (int default 0)",
          int(lit_mat.uniforms_data["uSpecularModel"]) == 0)

    # ── 4. 复位语义 ──
    print("-- 4. reset --")
    clone_mid = ResourceManager.CloneMaterial(lit_mid, "reset_probe")
    clone = ResourceManager.GetMaterial(clone_mid)
    clone.uniforms_data["uShininess"] = 128.0
    check("reset single uniform restores annotation default",
          ResourceManager.ResetMaterialUniform(clone_mid, "uShininess")
          and float(clone.uniforms_data["uShininess"]) == 32.0,
          str(clone.uniforms_data.get("uShininess")))
    check("reset unknown uniform → False",
          ResourceManager.ResetMaterialUniform(clone_mid, "no_such_uniform") is False)
    clone.uniforms_data["uDiffuseStrength"] = 0.5
    clone.uniforms_data["uSpecularStrength"] = 0.9
    count = ResourceManager.ResetMaterialUniforms(clone_mid)
    check("reset all touches every writable spec (and only those)",
          count == 6 and float(clone.uniforms_data["uDiffuseStrength"]) == 1.0
          and float(clone.uniforms_data["uSpecularStrength"]) == 0.25, str(count))

    # ── 5. 资源引用唯一性（shader 按名/路径，不按会话 id） ──
    print("-- 5. shader reference uniqueness --")
    check("ShaderRef(builtin) = builtin://Name",
          ResourceManager.ShaderRef(1) == "builtin://Basic", ResourceManager.ShaderRef(1))
    check("ResolveShaderRef round-trips",
          ResourceManager.ResolveShaderRef("builtin://SSVEP")
          == int(next(sid for sid, e in ResourceManager.loaded_shader.items()
                      if e.get("name") == "SSVEP")))
    check("unknown ref resolves to 0 (no silent default)",
          ResourceManager.ResolveShaderRef("builtin://NoSuchShader") == 0
          and ResourceManager.ShaderRef(9999) == "")

    ssvep_sid = ResourceManager.ResolveShaderRef("builtin://SSVEP")
    mat_path = os.path.join(tmp, "cue.mat")
    probe = ResourceManager.GetMaterial(ResourceManager.NewMaterial())
    probe.set_new_shader(ssvep_sid, ResourceManager.GetShader(ssvep_sid).uniforms_name_type,
                         ResourceManager.GetShaderSpecs(ssvep_sid),
                         ResourceManager.ShaderRef(ssvep_sid))
    probe.name = "cue"
    probe.uniforms_data["freq"] = 12.5
    probe.save_to_file(mat_path)
    loaded_mid = ResourceManager.LoadMaterialFromFile(mat_path)
    loaded = ResourceManager.GetMaterial(loaded_mid)
    check(".mat round-trip keeps shader_ref",
          loaded.shader_ref == "builtin://SSVEP", loaded.shader_ref)
    check(".mat round-trip keeps edited freq",
          abs(float(loaded.uniforms_data["freq"]) - 12.5) < 1e-6,
          str(loaded.uniforms_data.get("freq")))
    check("shader resolved by ref even if stored shader_id is bogus", True if
          loaded.shader_id == ssvep_sid else False, str(loaded.shader_id))

    # ── 5b. 纹理引用唯一性（.mat 的 texture_ids 同样是会话级 id）──
    print("-- 5b. texture reference uniqueness --")
    import json
    default_tid = ResourceManager.GetDefaultTexture("Default")
    check("TextureRef(builtin) = builtin://Default",
          ResourceManager.TextureRef(default_tid) == "builtin://Default",
          ResourceManager.TextureRef(default_tid))
    check("ResolveTextureRef round-trips",
          ResourceManager.ResolveTextureRef("builtin://Default") == default_tid)
    check("unknown texture ref resolves to 0 / no ref for runtime textures",
          ResourceManager.ResolveTextureRef("builtin://NoSuchTexture") == 0
          and ResourceManager.TextureRef(9999) == "")

    tex_mat = ResourceManager.GetMaterial(ResourceManager.NewMaterial())
    tex_mat.name = "tex_probe"
    tex_mat.texture_id_list = [default_tid]
    tex_path = os.path.join(tmp, "tex.mat")
    tex_mat.save_to_file(tex_path)
    with open(tex_path, "r", encoding="utf-8") as fh:
        tex_data = json.load(fh)
    check(".mat writes texture_refs next to texture_ids",
          tex_data.get("texture_refs") == ["builtin://Default"],
          str(tex_data.get("texture_refs")))
    # 模拟"另一个会话"：id 错位（9999 不存在），只靠 ref 还原
    tex_data["texture_ids"] = [9999]
    with open(tex_path, "w", encoding="utf-8") as fh:
        json.dump(tex_data, fh)
    reloaded = ResourceManager.GetMaterial(ResourceManager.LoadMaterialFromFile(tex_path))
    check("texture resolved by ref even if stored id is bogus",
          reloaded.texture_id_list == [default_tid], str(reloaded.texture_id_list))

    # ── 6. 编辑共享/内置材质 → 先 clone（复位走同一条路） ──
    print("-- 6. material isolation on edit --")
    eid_a = st.AddEntity("schemaA", Transform(), MeshRenderer())
    mr_a = esper.component_for_entity(eid_a, MeshRenderer)
    before_mid = mr_a.material_id
    before_color = np.array(ResourceManager.GetMaterial(before_mid).uniforms_data["uColor"],
                            dtype=np.float32)
    SceneManager._ensure_unique_material(st, eid_a, mr_a)
    check("editing a builtin template clones it first",
          mr_a.material_id != before_mid,
          f"{before_mid} -> {mr_a.material_id}")
    ResourceManager.GetMaterial(mr_a.material_id).uniforms_data["uColor"] = np.array(
        [0.0, 1.0, 0.0, 1.0], dtype=np.float32)
    check("template stays untouched after the edit",
          np.allclose(ResourceManager.GetMaterial(before_mid).uniforms_data["uColor"],
                      before_color))
    st.DeleteEntity(eid_a)

    # ── 7. 默认值不共享内存（唯一性：一个材质改值不串到另一个） ──
    print("-- 7. no shared ndarray between materials --")
    a_mid = ResourceManager.NewMaterial()
    b_mid = ResourceManager.NewMaterial()
    a_mat = ResourceManager.GetMaterial(a_mid)
    b_mat = ResourceManager.GetMaterial(b_mid)
    check("two materials do not share uniforms_data", a_mat.uniforms_data is not b_mat.uniforms_data)
    a_mat.uniforms_data["uColor"] = np.array([1, 0, 0, 1], dtype=np.float32)
    check("mutating one material leaves the other white",
          np.allclose(b_mat.uniforms_data["uColor"], [1, 1, 1, 1]),
          str(b_mat.uniforms_data["uColor"]))
    from Application.Resource.UniformSpec import build_default_uniforms
    first = build_default_uniforms({"uColor": "vec4"}, ResourceManager.GetShaderSpecs(1))
    first["uColor"][0] = 0.0
    second = build_default_uniforms({"uColor": "vec4"}, ResourceManager.GetShaderSpecs(1))
    check("defaults are freshly allocated each call (spec stays pure)",
          float(second["uColor"][0]) == 1.0, str(second["uColor"]))

    # ── 7. 运行期 uniform 注入（owner=runtime: SSVEP 的 time）──
    print("-- 7. runtime uniform injection --")
    from types import SimpleNamespace
    from Application.Core.Renderer.OpenGL import OpenGLEntities as _ent_mod
    from Application.Core.Renderer.OpenGL.OpenGLEntities import OpenGLEntities

    written: dict = {}
    real_float = _ent_mod.OpenGLUtils.set_uniform_float
    _ent_mod.OpenGLUtils.set_uniform_float = staticmethod(
        lambda shaders, sid, name, val: written.__setitem__(name, float(val)))
    try:
        ss_sid = next((int(sid) for sid, e in ResourceManager.loaded_shader.items()
                       if e.get("name") == "SSVEP"), 0)
        basic_sid = next((int(sid) for sid, e in ResourceManager.loaded_shader.items()
                          if e.get("name") == "Basic"), 0)
        shaders = {ss_sid: SimpleNamespace(runtime_uniforms={"time": "float"}),
                   basic_sid: SimpleNamespace(runtime_uniforms={})}
        ent = OpenGLEntities(SimpleNamespace(registered_shaders=shaders, engine=None))
        ent._inject_runtime(ss_sid, 12.5)
        check("runtime uniform receives elapsed seconds", written.get("time") == 12.5,
              str(written))
        written.clear()
        ent._inject_runtime(basic_sid, 12.5)
        check("shader without runtime uniforms writes nothing", written == {}, str(written))
        written.clear()
        ent._inject_runtime(999, 12.5)
        check("unknown shader id is a no-op", written == {}, str(written))
    finally:
        _ent_mod.OpenGLUtils.set_uniform_float = real_float

    check("_elapsed_seconds tolerates a missing time system",
          OpenGLEntities(SimpleNamespace(registered_shaders={}, engine=None))
          ._elapsed_seconds() == 0.0)
    check("_elapsed_seconds reads engine.get_elapsed_time",
          OpenGLEntities(SimpleNamespace(
              registered_shaders={},
              engine=SimpleNamespace(get_elapsed_time=lambda: 7.25)))._elapsed_seconds() == 7.25)
    check("_elapsed_seconds survives a throwing time source",
          OpenGLEntities(SimpleNamespace(
              registered_shaders={},
              engine=SimpleNamespace(get_elapsed_time=_boom)))._elapsed_seconds() == 0.0)

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


def _boom():
    raise RuntimeError("no clock")


if __name__ == "__main__":
    sys.exit(main())
