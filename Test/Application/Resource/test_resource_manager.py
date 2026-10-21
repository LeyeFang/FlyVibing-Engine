"""ResourceManager P0 contract tests — defaults, materials, textures, deletes.

Run:
    python Utils/Dev/test_runner.py --only test_resource_manager
"""
# TIER: core

from __future__ import annotations

import os
import sys
import tempfile

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def expect_raises(label: str, exc_type: type, fn) -> None:
    try:
        fn()
    except exc_type:
        check(label, True)
    except Exception as exc:  # noqa: BLE001
        check(label, False, f"raised {type(exc).__name__}: {exc}")
    else:
        check(label, False, "did not raise")


class FakeEngine:
    renderer = None
    scene = None


def main() -> int:
    print("=" * 60)
    print("ResourceManager P0 contract (headless)")
    print("=" * 60)

    import numpy as np
    from Application.Resource.ResourceManager import ResourceManager

    ResourceManager.Init(FakeEngine)

    # ── 1. builtin defaults ─────────────────────────────────────
    print("-- builtin defaults --")
    default_mat = ResourceManager.GetDefaultMaterial()
    check("default material id resolves", isinstance(default_mat, int) and default_mat > 0)
    default_mesh = ResourceManager.GetDefaultMesh("Cube")
    check("default mesh Cube resolves", isinstance(default_mesh, int)
          and ResourceManager.GetMesh(default_mesh) is not None)
    default_shader = ResourceManager.GetDefaultShader("Basic")
    check("default shader Basic resolves", isinstance(default_shader, int)
          and ResourceManager.GetShader(default_shader) is not None)
    default_tex = ResourceManager.GetDefaultTexture("Default")
    check("default texture resolves", isinstance(default_tex, int)
          and ResourceManager.GetTexture(default_tex) is not None)
    check("DefaultLit is available", ResourceManager.GetBuiltinMaterial("DefaultLit") > 0)
    check("unknown builtin material falls back to Default",
          ResourceManager.GetBuiltinMaterial("NoSuchMaterial") == default_mat)
    builtin_path = ResourceManager.ResolveBuiltinPath("Cube")
    check("builtin mesh path is resolvable", bool(builtin_path) and os.path.isfile(builtin_path))
    check("unknown builtin path is empty", ResourceManager.ResolveBuiltinPath("NoSuchAsset") == "")

    expect_raises("unknown default mesh raises", Exception,
                  lambda: ResourceManager.GetDefaultMesh("NoSuchMesh"))
    expect_raises("unknown default texture raises", KeyError,
                  lambda: ResourceManager.GetDefaultTexture("NoSuchTexture"))

    # ── 2. materials ────────────────────────────────────────────
    print("-- materials --")
    mid = ResourceManager.NewMaterial()
    mat = ResourceManager.GetMaterial(mid)
    check("NewMaterial returns distinct id", mid > 0 and mid != default_mat)
    check("new material binds default texture",
          default_tex in mat.texture_id_list, str(mat.texture_id_list))
    ResourceManager.SetMaterialColor(mid, 0.1, 0.2, 0.3, 0.4)
    color = ResourceManager.GetMaterialColor(mid)
    check("material color round-trip",
          color is not None and all(abs(a - b) < 1e-6 for a, b in zip(color, (0.1, 0.2, 0.3, 0.4))),
          str(color))

    clone_id = ResourceManager.CloneMaterial(mid, "P0Clone")
    clone = ResourceManager.GetMaterial(clone_id)
    check("clone gets a new id and name", clone_id != mid and clone.name == "P0Clone")
    check("clone is not a builtin template", clone.builtin_name is None)
    check("clone does not inherit source file path", clone._file_path == "")
    ResourceManager.SetMaterialColor(clone_id, 0.9, 0.8, 0.7, 1.0)
    check("clone color is independent",
          ResourceManager.GetMaterialColor(mid) != ResourceManager.GetMaterialColor(clone_id))

    extra_tex = ResourceManager.CreateTextureFromArray(
        "P0Extra", np.zeros((2, 3, 4), dtype=np.uint8))
    ResourceManager.AddMaterialTexture(mid, extra_tex)
    check("material texture append", extra_tex in mat.texture_id_list)
    before = len(mat.texture_id_list)
    ResourceManager.RemoveMaterialTexture(mid, 0)
    check("material texture remove by slot", len(mat.texture_id_list) == before - 1)

    # ── 3. texture lifecycle ───────────────────────────────────
    print("-- texture lifecycle --")
    tex_id = ResourceManager.CreateTextureFromArray(
        "P0Texture", np.zeros((4, 5, 3), dtype=np.uint8))
    tex = ResourceManager.GetTexture(tex_id)
    check("programmatic texture dimensions",
          (tex.width, tex.height, tex.channels) == (5, 4, 3),
          f"{tex.width}x{tex.height}x{tex.channels}")
    expect_raises("invalid texture shape raises", ValueError,
                  lambda: ResourceManager.CreateTextureFromArray(
                      "Bad", np.zeros((2, 2), dtype=np.uint8)))
    check("delete texture", ResourceManager.DeleteTexture(tex_id) is True)
    check("delete texture twice is False", ResourceManager.DeleteTexture(tex_id) is False)
    expect_raises("missing texture get raises", KeyError,
                  lambda: ResourceManager.GetTexture(tex_id))

    # ── 4. file import / errors ────────────────────────────────
    print("-- file import / errors --")
    with tempfile.TemporaryDirectory(prefix="mge_resource_") as tmp:
        missing = os.path.join(tmp, "missing.png")
        expect_raises("missing asset raises FileNotFoundError", FileNotFoundError,
                      lambda: ResourceManager.LoadAssets(missing))
        bad = os.path.join(tmp, "bad.xyz")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("not a resource")
        expect_raises("unsupported suffix raises ValueError", ValueError,
                      lambda: ResourceManager.LoadAssets(bad))

        png = os.path.join(tmp, "p0.png")
        from PIL import Image
        Image.new("RGBA", (3, 2), (255, 0, 0, 255)).save(png)
        png_id = ResourceManager.ImportTexture(png, "P0Png")
        check("import texture from file",
              ResourceManager.GetTexture(png_id).width == 3
              and ResourceManager.loaded_texture[str(png_id)]["name"] == "P0Png")
        check("delete imported texture", ResourceManager.DeleteTexture(png_id) is True)

    # ── 5. material/prefab delete semantics ───────────────────
    print("-- delete semantics --")
    check("delete created material", ResourceManager.DeleteMaterial(mid) is True)
    check("delete clone material", ResourceManager.DeleteMaterial(clone_id) is True)
    check("delete missing material is False", ResourceManager.DeleteMaterial(999999) is False)
    check("delete extra texture", ResourceManager.DeleteTexture(extra_tex) is True)
    check("delete missing mesh is False", ResourceManager.DeleteMesh(999999) is False)
    check("delete missing shader is False", ResourceManager.DeleteShader(999999) is False)
    check("missing prefab returns None",
          ResourceManager.LoadPrefab(os.path.join(tempfile.gettempdir(), "missing.prefab")) is None)

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
