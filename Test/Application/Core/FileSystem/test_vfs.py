"""VFS / PathUtils P0 contract tests — sandbox filesystem I/O.

Run:
    python Utils/Dev/test_runner.py --only test_vfs
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


def main() -> int:
    print("=" * 60)
    print("VFS / PathUtils P0 contract (sandbox)")
    print("=" * 60)

    from Application.Core.FileSystem.PathUtils import PathUtils
    from Application.Core.FileSystem.VFS import VFS

    # ── 1. PathUtils pure functions ──────────────────────────
    print("-- PathUtils --")
    check("normalize separators/trailing slash",
          PathUtils.normalize("a\\b///") == "a/b")
    check("join and normalize",
          PathUtils.normalize(PathUtils.join("a", "b", "c")) == "a/b/c")
    check("relative_to child", PathUtils.relative_to("a/b/c.txt", "a/b") == "c.txt")
    expect_raises("relative_to outside raises", ValueError,
                  lambda: PathUtils.relative_to("a/other.txt", "a/b"))
    check("is_child_of true", PathUtils.is_child_of("a/b/c.txt", "a/b"))
    check("is_child_of blocks traversal", not PathUtils.is_child_of("a/../secret", "a/b"))
    check("stem/basename/dirname/extension",
          PathUtils.stem("a/b/c.scene") == "c"
          and PathUtils.basename("a/b/c.scene") == "c.scene"
          and PathUtils.dirname("a/b/c.scene") == "a/b"
          and PathUtils.extension("a/b/c.scene") == ".scene")

    with tempfile.TemporaryDirectory(prefix="mge_vfs_") as root:
        # ── 2. init / write / read ────────────────────────────
        print("-- VFS init / I/O --")
        VFS.init(root)
        check("project root normalized", PathUtils.normalize(VFS.get_project_root()) == PathUtils.normalize(root))
        VFS.write_text("nested/config.txt", "hello")
        check("write_text creates parent and reads back",
              VFS.read_text("nested/config.txt") == "hello")
        check("resolve returns absolute existing path",
              os.path.isabs(VFS.resolve("nested/config.txt") or ""))
        check("exists sees relative file", VFS.exists("nested/config.txt"))
        check("exists false for missing", not VFS.exists("nested/missing.txt"))

        VFS.write_json("nested/data.json", {"a": 1, "b": ["x"]})
        check("write_json/read_json", VFS.read_json("nested/data.json") == {"a": 1, "b": ["x"]})
        VFS.write_bytes("nested/raw.bin", b"\x00\x01\xff")
        check("write_bytes/read_bytes", VFS.read_bytes("nested/raw.bin") == b"\x00\x01\xff")

        check("resolve absolute path",
              VFS.resolve(os.path.join(root, "nested", "config.txt")) is not None)
        check("resolve_or_raise missing",
              _missing_raises(VFS.resolve_or_raise, "nested/missing.txt"))

        # ── 3. mount priority ────────────────────────────────
        print("-- mounts --")
        VFS.write_text("priority.txt", "root")
        extra = os.path.join(root, "extra_mount")
        os.makedirs(extra, exist_ok=True)
        with open(os.path.join(extra, "priority.txt"), "w", encoding="utf-8") as fh:
            fh.write("mounted")
        VFS.mount(extra)
        check("later mount wins", VFS.read_text("priority.txt") == "mounted")
        VFS.unmount(extra)
        check("unmount restores root", VFS.read_text("priority.txt") == "root")

        check("list_dir", "config.txt" in VFS.list_dir("nested"))
        check("glob", any(p.endswith("config.txt") for p in VFS.glob("nested", "*.txt")))
        check("glob recursive", any(p.endswith("data.json")
                                    for p in VFS.glob(".", "**/*.json", recursive=True)))

        # ── 4. lifecycle ─────────────────────────────────────
        print("-- lifecycle --")
        VFS.shutdown()
        check("shutdown clears project root", VFS.get_project_root() == "")
        expect_raises("relative read after shutdown raises FileNotFoundError", FileNotFoundError,
                      lambda: VFS.read_text("nested/config.txt"))
        expect_raises("relative write after shutdown raises RuntimeError", RuntimeError,
                      lambda: VFS.write_text("nested/new.txt", "x"))

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


def _missing_raises(fn, path: str) -> bool:
    try:
        fn(path)
    except FileNotFoundError:
        return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
