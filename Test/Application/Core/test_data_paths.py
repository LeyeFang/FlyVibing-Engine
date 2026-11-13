"""Regression: 写文件节点的**统一落点** + 导出器的文件/路径卫生（1.2）。

为什么需要（2026-11-11 范式侧 issue `ISSUE_20261111_export_file_io_gaps.md`）
    成品里 `TextFileWrite` 按进程 CWD 解析相对路径 → 凭空在成品根长出
    `Test/TestProject/...` 深目录（装到只读位置直接失败）；扩展把开发机绝对路径
    写进节点 prop → 换机器就写不进去，或**悄悄写到别人的同名目录**；成品自带的
    `output/` 却没有任何写入走它。四个缺口是同一个病：**引擎没有"输出根"概念**。

本守卫锁定四件事:

  A. 解析语义: `relative_to` = output（默认）/ project / cwd；绝对路径原样；
     空路径落到基准目录；`MGE_OUTPUT_DIR` 可整体改道
  B. 节点行为: TextFileWrite / SaveData / PathVar 真的落到 output 根，
     **dry-run 不建目录**（旧实现在 dry-run 里也 mkdir）
  C. 导出器: 跳过 `.git`/`.venv`/`__pycache__`/`*.pyc`，逐文件失败不中断整棵树
  D. 可移植性审计: 场景里写死的绝对路径会被报出来（含跨平台写法）

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

ROOT = os.path.dirname(_d)
_passed = 0
_failed: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    global _passed
    if cond:
        _passed += 1
        print(f"  [PASS] {label}")
    else:
        _failed.append(label)
        print(f"  [FAIL] {label}" + (f"  ({detail})" if detail else ""))


def _norm(p: str) -> str:
    return os.path.normcase(os.path.abspath(p))


def main() -> int:
    print("=" * 60)
    print("Data output root + exporter file hygiene")
    print("=" * 60)

    from Application.Core.FileSystem.DataPaths import (
        DEFAULT_RELATIVE_TO,
        PathMacroError,
        base_for,
        contains_macro,
        data_roots,
        expand_macros,
        looks_absolute_path,
        resolve_write_path,
    )
    from Application.Editor.ProjectManager import (
        EXPORT_SKIP_DIR_NAMES,
        ProjectManager,
    )

    with tempfile.TemporaryDirectory(prefix="mge_paths_") as tmp:
        out = os.path.join(tmp, "product", "output")
        proj = os.path.join(tmp, "product")
        roots = {"output": out, "project": proj, "cwd": os.path.join(tmp, "cwd")}

        # ── A. 解析语义 ──────────────────────────────────────────
        check("default base is output", DEFAULT_RELATIVE_TO == "output",
              DEFAULT_RELATIVE_TO)
        check("relative path lands under output",
              _norm(resolve_write_path("seed/x.txt", roots=roots))
              == _norm(os.path.join(out, "seed/x.txt")),
              resolve_write_path("seed/x.txt", roots=roots))
        check("relative_to=project lands under project root",
              _norm(resolve_write_path("cfg.json", relative_to="project", roots=roots))
              == _norm(os.path.join(proj, "cfg.json")))
        check("relative_to=cwd keeps legacy behaviour",
              _norm(resolve_write_path("a.txt", relative_to="cwd", roots=roots))
              == _norm(os.path.join(roots["cwd"], "a.txt")))
        check("unknown relative_to falls back to output",
              _norm(resolve_write_path("a.txt", relative_to="bogus", roots=roots))
              == _norm(os.path.join(out, "a.txt")))
        check("absolute path is preserved",
              resolve_write_path("C:/data/x.txt" if os.name == "nt" else "/data/x.txt",
                                 roots=roots).endswith("x.txt"))
        check("empty path with default_name lands in base dir",
              _norm(resolve_write_path("", default_name="log.txt", roots=roots))
              == _norm(os.path.join(out, "log.txt")))
        check("empty path without name returns the base dir",
              _norm(resolve_write_path("", roots=roots)) == _norm(out))
        check("base_for is normalized to output for empty name",
              _norm(base_for("", roots)) == _norm(out))

        # 环境变量改道（部署到只读盘时唯一的逃生口）
        saved = os.environ.get("MGE_OUTPUT_DIR")
        try:
            os.environ["MGE_OUTPUT_DIR"] = os.path.join(tmp, "redirected")
            r2 = data_roots()
            check("MGE_OUTPUT_DIR overrides the resolved root",
                  _norm(r2["output"]) == _norm(os.path.join(tmp, "redirected")),
                  str(r2))
        finally:
            if saved is None:
                os.environ.pop("MGE_OUTPUT_DIR", None)
            else:
                os.environ["MGE_OUTPUT_DIR"] = saved

        # 引擎注入优先于环境变量
        from Application.Core.Engine import Engine
        Engine.set_data_roots(output_root=out, project_root=proj)
        r3 = data_roots()
        check("Engine-set root wins over env var",
              _norm(r3["output"]) == _norm(out), str(r3))
        check("Engine-set project root is reported",
              _norm(r3["project"]) == _norm(proj), str(r3))

        # ── A2. 跨平台绝对路径判定（导出审计依赖它）──
        check("windows drive is absolute", looks_absolute_path("C:\\data"))
        check("posix root is absolute", looks_absolute_path("/home/x"))
        check("UNC is absolute", looks_absolute_path("\\\\server\\share"))
        check("relative is not absolute", not looks_absolute_path("seed/x.txt"))
        check("builtin:// is not a path", not looks_absolute_path("builtin://Cube"))
        check("empty is not absolute", not looks_absolute_path(""))
        # ── A3. 宏（macro）—— 跨形态的"命名根" ──────────────────
        roots_m = {
            "engine": os.path.join(tmp, "eng"),
            "project": os.path.join(tmp, "proj"),
            "game": os.path.join(tmp, "game"),
            "output": os.path.join(tmp, "game", "output"),
            "cwd": os.path.join(tmp, "cwd"),
        }
        cases = {
            "<GameRoot>./output/x.txt": os.path.join(tmp, "game", "output", "x.txt"),
            "<GameRoot>output/x.txt": os.path.join(tmp, "game", "output", "x.txt"),
            "<GameRoot>/output/x.txt": os.path.join(tmp, "game", "output", "x.txt"),
            "<ProjectRoot>/assets/a.json": os.path.join(tmp, "proj", "assets", "a.json"),
            "<EngineRoot>/Resource/x": os.path.join(tmp, "eng", "Resource", "x"),
            "<EditorRoot>/y": os.path.join(tmp, "eng", "y"),
            "<OutputRoot>/log.txt": os.path.join(tmp, "game", "output", "log.txt"),
            "<gameroot>/z.txt": os.path.join(tmp, "game", "z.txt"),
        }
        for spec, want in cases.items():
            got = resolve_write_path(spec, roots=roots_m)
            check(f"macro {spec!r} resolves", _norm(got) == _norm(want), got)

        check("contains_macro detects a macro", contains_macro("<GameRoot>/x"))
        check("contains_macro is false for plain paths",
              not contains_macro("seed/x.txt") and not contains_macro("C:/x"))
        check("expand_macros is a pure replace (no normalization)",
              expand_macros("<GameRoot>./output", roots_m)
              == os.path.join(tmp, "game") + os.sep + "./output",
              expand_macros("<GameRoot>./output", roots_m))
        check("macro names are case-insensitive",
              _norm(expand_macros("<PROJECTROOT>/a", roots_m))
              == _norm(os.path.join(tmp, "proj") + "/a"))

        # 未知宏必须报错 —— 不静默降级（写错地方比写失败难查）
        try:
            resolve_write_path("<Nope>/x", roots=roots_m)
            raised = False
        except PathMacroError:
            raised = True
        check("unknown macro raises PathMacroError", raised)
        try:
            expand_macros("<Gameroot/typo>", roots_m)
            ok = True
        except PathMacroError:
            ok = False
        # 语法不匹配（没有闭合 >）→ 不是宏，按普通路径处理
        check("malformed macro is treated as text", ok)
        try:
            resolve_write_path("<OutputRoot>/x", roots={**roots_m, "output": ""})
            empty_root_ok = True
        except PathMacroError:
            empty_root_ok = False
        check("empty root falls back instead of failing", empty_root_ok)
        # 部分键的根表（引擎在编辑器里只注入 project/output）→ 其余键派生
        partial = resolve_write_path("<EngineRoot>/x",
                                     roots={"project": os.path.join(tmp, "p2")})
        check("partial roots fall back to derived engine root",
              os.path.isabs(partial) and partial.endswith("x"), partial)

        # ── A4. 根挂在**子类** state 上（扩展侧 O7，2026-11-13）──────
        #   `set_data_roots` 是 classmethod → 宿主写的是 `EditorHost` / `GameRuntime`
        #   的表；而 `DataPaths` 只能 import `Engine` 基类。不跨子类扫描的话，
        #   编辑器里 `<ProjectRoot>` / `<OutputRoot>` 会退化成引擎根，与 PIE/成品
        #   不一致（扩展侧实测发现并报了 O7）。
        from Application.Core.Engine import Engine as _Eng

        class _RootProbeHost(_Eng):
            pass

        class _RootProbeSecond(_Eng):
            pass

        try:
            _RootProbeHost.set_data_roots(
                project_root=os.path.join(tmp, "o7proj"),
                output_root=os.path.join(tmp, "o7proj", "output"))
            live = data_roots()
            check("O7: subclass roots are visible through DataPaths",
                  _norm(live["project"]) == _norm(os.path.join(tmp, "o7proj")),
                  str(live))
            check("O7: <OutputRoot> uses the subclass output root",
                  _norm(resolve_write_path("<OutputRoot>/a.txt"))
                  == _norm(os.path.join(tmp, "o7proj", "output", "a.txt")),
                  resolve_write_path("<OutputRoot>/a.txt"))
            # 清空也是一次声明 —— 不能继续沿用上一个工程的根
            _RootProbeHost.clear_data_roots()
            check("O7: clearing roots falls back to derived values",
                  _norm(data_roots()["project"]) != _norm(os.path.join(tmp, "o7proj")),
                  str(data_roots()))
            # 后声明者胜出（编辑器 / PIE 同时存在时取最近那次上下文）
            _RootProbeHost.set_data_roots(
                project_root=os.path.join(tmp, "first"),
                output_root=os.path.join(tmp, "first", "output"))
            _RootProbeSecond.set_data_roots(
                project_root=os.path.join(tmp, "second"),
                output_root=os.path.join(tmp, "second", "output"))
            check("O7: the most recent declaration wins",
                  _norm(data_roots()["project"]) == _norm(os.path.join(tmp, "second")),
                  str(data_roots()))
        finally:
            _RootProbeHost.clear_data_roots()
            _RootProbeSecond.clear_data_roots()

        # 语法选择：`<` `>` 在 Windows 上是非法文件名字符 → 磁盘上不可能
        # 存在与宏同名的真实目录（这正是选它而不是 $() 的理由）。
        if os.name == "nt":
            bad = os.path.join(tmp, "<GameRoot>")
            try:
                os.makedirs(bad, exist_ok=True)
                creatable = os.path.isdir(bad)
            except OSError:
                creatable = False
            check("a folder literally named like a macro cannot be created",
                  not creatable)
            if creatable:
                try:
                    os.rmdir(bad)
                except OSError:
                    pass


        from Application.Core.NodeGraph import NodeCanvas, _TYPES
        from Application.Core.NodeGraph.evaluator_engine import (
            ExecutionContext,
            GraphEvaluator,
        )

        canvas = NodeCanvas.from_dict({
            "next_id": 50,
            "nodes": {
                "1": {"node_type": "TextFileWrite", "pos": [0.0, 0.0], "pin_ids": {},
                      "props": {"mode": "manual", "write_mode": "w",
                                "file_name": "log", "value": 7}},
                "2": {"node_type": "PathVar", "pos": [0.0, 0.0], "pin_ids": {},
                      "props": {"path": "seed", "browse_mode": "directory"}},
                "3": {"node_type": "SaveData", "pos": [0.0, 0.0], "pin_ids": {},
                      "props": {"mode": "manual", "format": "json",
                                "file_name": "meta", "unique": False,
                                "value": "{\"a\": 1}"}},
            },
            "links": {},
        })
        evaluator = GraphEvaluator(canvas, _TYPES)
        ctx = ExecutionContext()
        ctx.output_root = out
        ctx.project_root = proj

        # dry-run 必须零副作用：不建目录、不写文件
        ctx.dry_run = True
        ctx.log = lambda *a, **k: None
        from Application.Core.NodeGraph.evaluators import io as io_eval
        io_eval._eval_text_file_write(1, ctx, evaluator)
        io_eval._eval_save_data(3, ctx, evaluator)
        io_eval._eval_path_var(2, ctx, evaluator)
        check("dry-run creates no output dir", not os.path.isdir(out),
              os.path.isdir(out))
        pv = ctx.get_pin(canvas.nodes[2].pin_ids["Path"])
        check("PathVar resolves relative path to an absolute output path",
              os.path.isabs(pv) and _norm(pv) == _norm(os.path.join(out, "seed")), str(pv))

        # 真跑：落在 output 根
        ctx.dry_run = False
        io_eval._eval_text_file_write(1, ctx, evaluator)
        written = os.path.join(out, "log.txt")
        check("TextFileWrite writes under the output root", os.path.isfile(written),
              written)
        if os.path.isfile(written):
            with open(written, "r", encoding="utf-8") as fh:
                check("TextFileWrite content matches", fh.read().strip() == "7")
        check("nothing written outside the output root",
              not os.path.isdir(os.path.join(proj, "Test")), "stray Test/ dir found")

        io_eval._eval_save_data(3, ctx, evaluator)
        check("SaveData writes under the output root",
              os.path.isfile(os.path.join(out, "meta.json")), str(os.listdir(out)))

        # relative_to=cwd 仍可显式选择旧行为
        canvas.nodes[1].props["relative_to"] = "cwd"
        cwd_out = ctx.data_roots()["cwd"]
        io_eval._eval_text_file_write(1, ctx, evaluator)
        check("relative_to=cwd writes to CWD (explicit opt-in)",
              os.path.isfile(os.path.join(cwd_out, "log.txt")),
              os.path.join(cwd_out, "log.txt"))
        try:
            os.remove(os.path.join(cwd_out, "log.txt"))
        except OSError:
            pass

        # ── C. 导出器文件卫生 ──
        src = os.path.join(tmp, "ext")
        os.makedirs(os.path.join(src, ".git", "objects"), exist_ok=True)
        with open(os.path.join(src, ".git", "objects", "abc"), "w") as fh:
            fh.write("x")
        os.makedirs(os.path.join(src, ".venv", "Lib"), exist_ok=True)
        with open(os.path.join(src, ".venv", "Lib", "x.py"), "w") as fh:
            fh.write("x")
        os.makedirs(os.path.join(src, "__pycache__"), exist_ok=True)
        with open(os.path.join(src, "__pycache__", "m.pyc"), "wb") as fh:
            fh.write(b"\x00")
        with open(os.path.join(src, "module.pyc"), "wb") as fh:
            fh.write(b"\x00")
        with open(os.path.join(src, "nodes.py"), "w", encoding="utf-8") as fh:
            fh.write("# real code\n")
        with open(os.path.join(src, "extension.json"), "w", encoding="utf-8") as fh:
            json.dump({"id": "fixture", "name": "Fixture"}, fh)

        dst = os.path.join(tmp, "copied")
        warns: list[str] = []
        errors: list[str] = []
        files, _bytes = ProjectManager._copy_tree_for_export(
            src, dst, warns, errors=errors)
        check("VCS / venv / cache dirs are skipped",
              not os.path.isdir(os.path.join(dst, ".git"))
              and not os.path.isdir(os.path.join(dst, ".venv"))
              and not os.path.isdir(os.path.join(dst, "__pycache__")),
              str(sorted(os.listdir(dst))))
        check("pyc files are skipped", not os.path.exists(os.path.join(dst, "module.pyc")),
              str(sorted(os.listdir(dst))))
        check("real sources survive", os.path.isfile(os.path.join(dst, "nodes.py"))
              and os.path.isfile(os.path.join(dst, "extension.json")))
        check("no copy errors for a clean tree", not errors, str(errors))
        check("copy count reflects skip", files == 2, str(files))
        check("skip list contains the repo-hostile names",
              {".git", ".venv", "__pycache__"} <= set(EXPORT_SKIP_DIR_NAMES),
              str(sorted(EXPORT_SKIP_DIR_NAMES)))

        # ── D. 可移植性审计 ──
        scene_dir = os.path.join(tmp, "bundle", "scenes")
        os.makedirs(scene_dir, exist_ok=True)
        with open(os.path.join(scene_dir, "Main.scene"), "w", encoding="utf-8") as fh:
            json.dump({
                "version": "0.1.0",
                "scene": {"node_graph": {"nodes": {
                    "1": {"node_type": "ext.fixture.Init",
                          "props": {"save_dir": "C:\\WorkSpace\\dev\\recordings"}},
                    "2": {"node_type": "TextFileWrite",
                          "props": {"file_path": "seed", "file_name": "log"}},
                    "3": {"node_type": "ext.fixture.Init",
                          "props": {"save_dir": "/home/dev/rec"}},
                    "4": {"node_type": "PathVar",
                          "props": {"path": "builtin://Cube"}},
                }}},
            }, fh)
        hits = ProjectManager._scan_absolute_props(
            os.path.join(tmp, "bundle"), ["scenes/Main.scene"])
        props = {(h["node"], h["prop"]) for h in hits}
        check("windows absolute prop is reported", ("1", "save_dir") in props, str(props))
        check("posix absolute prop is reported (cross-platform)",
              ("3", "save_dir") in props, str(props))
        check("relative paths are not reported",
              ("2", "file_path") not in props and ("2", "file_name") not in props,
              str(props))
        check("builtin:// is not reported", ("4", "path") not in props, str(props))
        check("audit entries carry scene/type/value",
              all({"scene", "node", "type", "prop", "value"} <= set(h) for h in hits),
              str(hits[:1]))

        # ── E. 扩展上下文有 output_dir（扩展写运行数据的受支持接口）──
        from Application.Core.Extension.ExtensionContext import ExtensionContext
        ctx_ext = ExtensionContext(extension_id="fixture", name="Fixture",
                                   version="0.1.0", manifest={},
                                   extension_dir=tmp, data_dir=tmp,
                                   engine_root=tmp)
        check("ExtensionContext exposes an absolute output_dir",
              os.path.isabs(ctx_ext.output_dir), ctx_ext.output_dir)
        check("ExtensionContext.output_dir is not the process CWD",
              _norm(ctx_ext.output_dir) != _norm(os.getcwd()), ctx_ext.output_dir)

    print()
    print("=" * 60)
    total = _passed + len(_failed)
    print(f"Results: {_passed}/{total} passed, {len(_failed)} failed")
    print("ALL TESTS PASSED" if not _failed else "TESTS FAILED")
    return 0 if not _failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
