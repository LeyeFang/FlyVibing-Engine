"""Extension-contributed Examples — discovery, signature, lifecycle, no pollution.

Covers:
  1. `<extension_dir>/Examples/` is auto-registered when the extension loads.
  2. `ctx.examples.register(root, provider=...)` adds extra roots; unload removes.
  3. Menu provider falls back to the extension manifest, then `.myproj`.
  4. User examples are never overwritten; same names are distinguished by provider.
  5. Legacy `.injected.json` copies are hidden while their source root is registered.

TIER: core
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, "_path_setup.py")):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
    import _path_setup  # noqa: F401

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    _RESULTS["pass" if cond else "fail"] += 1
    tag = "PASS" if cond else "FAIL"
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _write_json(path: str, data: dict) -> None:
    _write(path, json.dumps(data, ensure_ascii=False, indent=2))


_EXT_CODE = """\
import os
from Application.Core.Extension.ExtensionBase import ExtensionBase


class ExamplesExtension(ExtensionBase):
    id = "uext_examples"
    name = "Examples Extension"
    version = "1.0.0"

    def on_load(self, ctx):
        extra = os.path.join(ctx.extension_dir, "ExtraExamples")
        ctx.examples.register(extra, provider="@EXTRA")


def create_extension():
    return ExamplesExtension()
"""

_OTHER_EXT_CODE = """\
from Application.Core.Extension.ExtensionBase import ExtensionBase


class OtherExtension(ExtensionBase):
    id = "uext_other"
    name = "Other Extension"
    version = "1.0.0"


def create_extension():
    return OtherExtension()
"""


def main() -> int:
    print("=" * 60)
    print("Extension examples — discovery / signature / lifecycle")
    print("=" * 60)

    from Application.Editor.Extensions.ExtensionExamples import ExtensionExamplesRegistry
    from Application.Editor.Extensions.ExtensionManager import ExtensionManager
    from Application.Editor.UI.UIManager import UIManager

    tmp = tempfile.mkdtemp(prefix="mge_ext_examples_")
    exts = os.path.join(tmp, "extensions")
    user_examples = os.path.join(tmp, "user_examples")
    state = os.path.join(tmp, "state.json")
    data = os.path.join(tmp, "data")
    saved_env = {k: os.environ.get(k) for k in
                 ("MGE_EXTENSIONS_DIR", "MGE_EXTENSIONS_STATE", "MGE_EXTENSIONS_DATA",
                  "FVE_EXAMPLES_DIR", "MGE_EXAMPLES_DIR")}
    os.environ["MGE_EXTENSIONS_DIR"] = exts
    os.environ["MGE_EXTENSIONS_STATE"] = state
    os.environ["MGE_EXTENSIONS_DATA"] = data
    os.environ["FVE_EXAMPLES_DIR"] = user_examples
    os.environ.pop("MGE_EXAMPLES_DIR", None)

    ext_a = os.path.join(exts, "uext_examples")
    ext_b = os.path.join(exts, "uext_other")
    _write_json(os.path.join(ext_a, "extension.json"), {
        "id": "uext_examples", "name": "Examples Extension", "version": "1.0.0",
        "api_version": "1", "maturity": "skeleton",
        "entry": "extension.py:create_extension",
        "capabilities": ["examples"], "provider": "@ACME",
    })
    _write(os.path.join(ext_a, "extension.py"), _EXT_CODE)
    _write_json(os.path.join(ext_a, "Examples", "Demo", "Demo.myproj"), {
        "name": "Demo", "startup_scene": "scenes/Demo.scene",
    })
    _write_json(os.path.join(ext_a, "Examples", "Injected", "Injected.myproj"), {
        "name": "Injected", "provider": "@ACME", "startup_scene": "scenes/Injected.scene",
    })
    _write_json(os.path.join(ext_a, "ExtraExamples", "Extra", "Extra.myproj"), {
        "name": "Extra", "startup_scene": "scenes/Extra.scene",
    })

    _write_json(os.path.join(ext_b, "extension.json"), {
        "id": "uext_other", "name": "Other Extension", "version": "1.0.0",
        "api_version": "1", "maturity": "skeleton",
        "entry": "extension.py:create_extension", "provider": "@OTHER",
    })
    _write(os.path.join(ext_b, "extension.py"), _OTHER_EXT_CODE)
    _write_json(os.path.join(ext_b, "Examples", "Demo", "Demo.myproj"), {
        "name": "Demo", "startup_scene": "scenes/Demo.scene",
    })

    # 用户自建同名示例 + 旧式注入副本（source 指向扩展 A 的 Injected）
    user_demo = os.path.join(user_examples, "Demo", "Demo.myproj")
    _write_json(user_demo, {
        "name": "Demo", "provider": "@USER", "startup_scene": "scenes/Demo.scene",
    })
    user_injected = os.path.join(user_examples, "Injected", "Injected.myproj")
    _write_json(user_injected, {
        "name": "Injected", "provider": "@ACME", "startup_scene": "scenes/Injected.scene",
    })
    _write_json(os.path.join(user_examples, "Injected", ".injected.json"), {
        "source": os.path.join(ext_a, "Examples", "Injected"),
        "signature": "legacy",
    })
    user_before = open(user_demo, "rb").read()

    try:
        ExtensionExamplesRegistry.clear()
        ExtensionManager.ensure_init(force=True)
        check("extension A enabled", ExtensionManager.enable("uext_examples")["loaded"])
        check("extension B enabled", ExtensionManager.enable("uext_other")["loaded"])

        roots = ExtensionExamplesRegistry.roots()
        providers = {os.path.abspath(r["root"]): r["provider"] for r in roots}
        check("bundled Examples auto-registered (A)",
              os.path.abspath(os.path.join(ext_a, "Examples")) in providers, str(providers))
        check("bundled Examples auto-registered without capability (B)",
              os.path.abspath(os.path.join(ext_b, "Examples")) in providers, str(providers))
        check("ctx.examples extra root registered",
              providers.get(os.path.abspath(os.path.join(ext_a, "ExtraExamples"))) == "@EXTRA",
              str(providers))
        check("manifest provider used for bundled root",
              providers.get(os.path.abspath(os.path.join(ext_a, "Examples"))) == "@ACME",
              str(providers))

        catalog = UIManager._example_projects()
        by_path = {os.path.abspath(path): label for label, path in catalog}
        demo_a = os.path.join(ext_a, "Examples", "Demo", "Demo.myproj")
        demo_b = os.path.join(ext_b, "Examples", "Demo", "Demo.myproj")
        extra = os.path.join(ext_a, "ExtraExamples", "Extra", "Extra.myproj")
        injected_src = os.path.join(ext_a, "Examples", "Injected", "Injected.myproj")
        check("extension bundled example visible", os.path.abspath(demo_a) in by_path)
        check("second extension bundled example visible", os.path.abspath(demo_b) in by_path)
        check("ctx.examples extra root visible", os.path.abspath(extra) in by_path)
        check("extension provider from manifest", UIManager._example_provider(demo_a) == "@ACME")
        check("second extension provider from manifest",
              UIManager._example_provider(demo_b) == "@OTHER")
        check("extra root provider override", UIManager._example_provider(extra) == "@EXTRA")
        check("user same-name example remains visible",
              os.path.abspath(user_demo) in by_path)
        check("user same-name provider preserved",
              UIManager._example_provider(user_demo) == "@USER")
        check("same name with different providers keeps plain labels",
              by_path.get(os.path.abspath(demo_a)) == "Demo"
              and by_path.get(os.path.abspath(demo_b)) == "Demo",
              str(by_path))
        check("legacy injected copy hidden while source root is registered",
              os.path.abspath(user_injected) not in by_path)
        check("legacy source example visible", os.path.abspath(injected_src) in by_path)
        check("user example file untouched", open(user_demo, "rb").read() == user_before)

        ExtensionManager.disable("uext_examples")
        check("extension A roots removed",
              ExtensionExamplesRegistry.owner_for_path(demo_a) == ""
              and ExtensionExamplesRegistry.owner_for_path(extra) == "")
        after = {os.path.abspath(path) for _label, path in UIManager._example_projects()}
        check("extension A bundled example disappears",
              os.path.abspath(demo_a) not in after)
        check("ctx.examples extra root disappears", os.path.abspath(extra) not in after)
        check("extension B example remains", os.path.abspath(demo_b) in after)
        check("user example remains after disable", os.path.abspath(user_demo) in after)
        check("legacy injected copy reappears as a normal user example",
              os.path.abspath(user_injected) in after)

        ExtensionManager.disable("uext_other")
        check("all extension roots removed after disable",
              not ExtensionExamplesRegistry.roots(), str(ExtensionExamplesRegistry.roots()))
        check("no extension root remains in menu",
              not any(os.path.abspath(p).startswith(os.path.abspath(exts) + os.sep)
                      for _label, p in UIManager._example_projects()))
        check("user example file still untouched", open(user_demo, "rb").read() == user_before)
    finally:
        try:
            ExtensionManager.unload_all()
        except Exception:
            pass
        ExtensionExamplesRegistry.clear()
        ExtensionManager._infos = {}
        ExtensionManager._instances = {}
        ExtensionManager._example_facades.clear()
        ExtensionManager._scanned = False
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
