"""统一测试运行器 — 子进程隔离 + 日志落盘 + 紧凑摘要（agent 友好）。

用法:
    python Utils/Dev/test_runner.py                    # core 档（默认; 无 GUI）
    python Utils/Dev/test_runner.py --list             # 列出发现与档位
    python Utils/Dev/test_runner.py --tier gui         # GL 窗口档
    python Utils/Dev/test_runner.py --tier all --only editor
    python Utils/Dev/test_runner.py --json             # 单行机器可读摘要

契约（见 Doc/Dev/test_protocol.md）:
  - 每个测试 = 独立子进程; 全量输出写日志文件, stdout 只回摘要
  - 测试最后一行应输出 `RESULT: OK (n)` / `RESULT: FAIL (k): ...` / `RESULT: n/m passed, k failed`
   （未识别格式或缺省时按退出码判定并告警）
  - 文件头可声明 `# TIER: core|gui|heavy|live`; 未声明按文件名启发式分类
  - 子进程环境: MGE_TEST_TMP=<runs>/tmp/<test>（沙箱）; PYTHONIOENCODING=utf-8

退出码: 0 全部通过 / 1 有失败 / 2 用法错误
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve()
while _ROOT and not (_ROOT / "startup.bat").exists():
    parent = _ROOT.parent
    if parent == _ROOT:
        _ROOT = None
        break
    _ROOT = parent
if _ROOT is None:
    raise SystemExit("cannot locate repo root (startup.bat)")

ROOT = str(_ROOT)
SEARCH_DIRS = ["Test/Application"]
SCENARIO_DIRS = ["Test/Application/Editor/scenarios"]
UI_SCENARIO_RUNNER = "Test/Application/Editor/ui_scenario.py"
TIER_RE = re.compile(r"TIER\s*[:=]\s*['\"]?(core|gui|heavy|live|manual)", re.IGNORECASE)

GUI_HINTS = ("gizmo", "grid", "outliner")
HEAVY_HINTS = ("export_game_bundle",)
LIVE_PREFIX = ("e2e_", "test_e2e_")
MANUAL_HINTS = ("live_ui", "node_runtime")  # 交互式预览/演示 — 不进自动批次
TEST_MAP_PATH = "Doc/Dev/test_nodes.json"
UI_MAP_PATH = "Doc/Dev/ui_map.json"


def _repo_rel(path: str) -> str:
    """规范化为仓库相对路径（统一 / 分隔）。"""
    raw = str(path or "").strip().replace("\\", "/")
    if not raw:
        return ""
    if os.path.isabs(raw):
        try:
            raw = os.path.relpath(raw, ROOT).replace("\\", "/")
        except ValueError:
            pass
    if raw.startswith("./"):
        raw = raw[2:]
    return raw


def _module_name(rel: str) -> str:
    rel = _repo_rel(rel)
    if rel.endswith(".py"):
        rel = rel[:-3]
    return rel.replace("/", ".")


def _affected_names(paths: list[str]) -> tuple[set[str], dict[str, str]]:
    """源码/场景路径 → 相关测试节点名 + GUI scenario 名。

    数据源是两份已有地图:
      - test_nodes.json: covers 模块 → test_*.py
      - ui_map.json:      source 路径 → scenarios
    后者不能省略；节点编辑器 panel 的回归场景只记录在 ui_map 里。
    """
    names: set[str] = set()
    reasons: dict[str, str] = {}
    rels = {r for r in (_repo_rel(p) for p in paths) if r}
    modules = {_module_name(r) for r in rels}

    nodes_path = Path(ROOT) / TEST_MAP_PATH
    if nodes_path.is_file():
        try:
            data = json.loads(nodes_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        for node in data.get("nodes") or []:
            covers = {str(c) for c in (node.get("covers") or [])}
            if not (covers & modules):
                continue
            path = _repo_rel(node.get("path") or "")
            if path:
                names.add(Path(path).stem)
                reasons[Path(path).stem] = f"covers:{','.join(sorted(covers & modules))}"

    ui_path = Path(ROOT) / UI_MAP_PATH
    if ui_path.is_file():
        try:
            ui = json.loads(ui_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            ui = {}
        for ctrl in ui.get("controls") or []:
            src = _repo_rel(ctrl.get("source") or "")
            if src not in rels:
                continue
            for scenario in ctrl.get("scenarios") or []:
                name = str(scenario)
                names.add(name)
                reasons.setdefault(name, f"ui:{ctrl.get('id')}")

    return names, reasons


def _changed_paths() -> list[str]:
    """git 工作区改动文件（不依赖 commit；失败时返回空列表）。"""
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    out: list[str] = []
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        rel = _repo_rel(path)
        if rel:
            out.append(rel)
    return out

def _classify(path: Path, rel: str) -> str:
    try:
        head = "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[:60])
        m = TIER_RE.search(head)
        if m:
            return m.group(1).lower()
    except OSError:
        pass
    name = path.name.lower()
    if any(h.lower() in rel.lower() for h in ("Core/Renderer", "Core/Window")):
        return "gui"  # 渲染/窗口演示 — 需要 GL/Vulkan
    if name.startswith(LIVE_PREFIX):
        return "live"
    if any(h in name for h in MANUAL_HINTS):
        return "manual"
    if any(h in name for h in HEAVY_HINTS):
        return "heavy"
    if any(h in name for h in GUI_HINTS):
        return "gui"
    return "core"


def discover(only: str | None) -> list[tuple[str, Path, str]]:
    found: list[tuple[str, Path, str]] = []
    for base in SEARCH_DIRS:
        root = Path(ROOT) / base
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("test_*.py")):
            rel = str(path.relative_to(ROOT)).replace("\\", "/")
            if only and only.lower() not in rel.lower():
                continue
            found.append((rel, path, _classify(path, rel)))

    # UI scenarios are not test_*.py; run them through ui_scenario.py and
    # expose them as the gui tier so `--tier gui` is no longer empty.
    for base in SCENARIO_DIRS:
        root = Path(ROOT) / base
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.py")):
            if path.name.startswith("_"):
                continue
            rel = str(path.relative_to(ROOT)).replace("\\", "/")
            if only and only.lower() not in rel.lower():
                continue
            found.append((rel, path, _classify(path, rel)))
    # 非 Application 目录（Device/RHI/... 按需 --only + --tier all）— 仅提示, 不默认纳入
    return found


def _extract(lines: list[str]) -> tuple[str, str]:
    """返回 (result_line, first_error_line)。"""
    result_line = ""
    for line in reversed(lines):
        if "RESULT:" in line:
            result_line = line.strip()
            break
    first_error = ""
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith("[FAIL]") or "FAIL:" in s or s.startswith("Traceback") or "AssertionError" in s:
            first_error = s[:180]
            break
    return result_line, first_error


def _verdict(result_line: str, code: int) -> tuple[bool, str]:
    """解析 RESULT 契约行 → (passed, note)。

    支持的格式:
      RESULT: OK (n/m)                     → 通过
      RESULT: FAIL (k): ...                → 失败
      RESULT: n/m passed, k failed         → k == 0 通过
    未识别的 RESULT 格式 → 退回退出码判定。
    """
    m = re.search(r"RESULT:\s*(\d+)\s*/\s*(\d+)\s+passed(?:,\s*(\d+)\s+failed)?", result_line)
    if m:
        failed_n = int(m.group(3)) if m.group(3) is not None else int(m.group(2)) - int(m.group(1))
        if failed_n == 0:
            return True, ""
        return False, f"{failed_n} subtest(s) failed"
    if re.search(r"RESULT:\s*OK\b", result_line):
        return True, ""
    if re.search(r"RESULT:\s*FAIL", result_line):
        tail = result_line.split("RESULT:", 1)[1].strip()
        return False, tail[:80]
    return (code == 0), "unrecognized RESULT format (used exit code)"


def run_one(rel: str, path: Path, runs_dir: Path, timeout: float,
            round_no: int = 0) -> dict:
    test_name = path.stem
    log_dir = runs_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / (f"{test_name}_r{round_no}.log" if round_no else f"{test_name}.log")
    tmp_dir = runs_dir / "tmp" / test_name
    tmp_dir.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["MGE_TEST_TMP"] = str(tmp_dir)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"

    t0 = time.time()
    timed_out = False
    try:
        rel_parent = str(path.parent.relative_to(ROOT)).replace("\\", "/")
        if rel_parent in SCENARIO_DIRS:
            cmd = [sys.executable, str(Path(ROOT) / UI_SCENARIO_RUNNER), str(path)]
        else:
            cmd = [sys.executable, str(path)]
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            env=env,
            capture_output=True,
            timeout=timeout,
        )
        stdout = proc.stdout.decode("utf-8", errors="replace")
        stderr = proc.stderr.decode("utf-8", errors="replace")
        code = proc.returncode
    except subprocess.TimeoutExpired as e:
        timed_out = True
        stdout = (e.stdout or b"").decode("utf-8", errors="replace")
        stderr = (e.stderr or b"").decode("utf-8", errors="replace")
        code = -1
    elapsed = time.time() - t0

    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write(f"# {rel}\n# exit={code} timeout={timed_out} elapsed={elapsed:.1f}s\n")
        fh.write("=" * 60 + " stdout\n")
        fh.write(stdout)
        fh.write("=" * 60 + " stderr\n")
        fh.write(stderr)

    lines = stdout.splitlines() + stderr.splitlines()
    result_line, first_error = _extract(lines)
    if timed_out:
        passed, note = False, f"TIMEOUT ({timeout:.0f}s)"
    elif result_line:
        passed, note = _verdict(result_line, code)
    else:
        passed, note = (code == 0), "no RESULT line"

    return {
        "name": test_name,
        "rel": rel,
        "passed": passed,
        "elapsed": round(elapsed, 1),
        "result_line": result_line,
        "first_error": first_error,
        "note": note,
        "exit": code,
        "log": str(log_path.relative_to(ROOT)).replace("\\", "/"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="test_runner", description="统一测试运行器（子进程隔离 + 紧凑摘要）")
    parser.add_argument("--tier", choices=("core", "gui", "heavy", "live", "all"),
                        default=None,
                        help="默认 core；--affected/--changed 时默认 all（只跑命中的测试）")
    parser.add_argument("--only", default="", help="路径子串过滤（如 editor / functions / graph）")
    parser.add_argument("--exclude", default="", help="路径子串排除")
    parser.add_argument("--affected", nargs="+", default=[],
                        help="按改动源码路径选择相关测试（test_nodes 覆盖 + ui_map 场景）")
    parser.add_argument("--changed", action="store_true",
                        help="用 git status 的改动文件调用 --affected")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--list", action="store_true", help="只列出发现的测试与档位")
    parser.add_argument("--json", action="store_true", help="末尾输出单行 JSON 摘要")
    parser.add_argument("--stress", type=int, default=1,
                        help="每个测试重复轮数 (>=2 时逐轮执行, 日志带 _rN 后缀)")
    ns = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

    affected_paths = list(ns.affected)
    if ns.changed:
        changed = _changed_paths()
        affected_paths.extend(p for p in changed if p not in affected_paths)
    affected_names: set[str] = set()
    affected_reasons: dict[str, str] = {}
    if affected_paths:
        affected_names, affected_reasons = _affected_names(affected_paths)
        if not affected_names:
            print("no related tests for affected paths:")
            for p in affected_paths:
                print(f"  - {p}")
            return 2

    tests = discover(ns.only or None)
    if ns.exclude:
        tests = [t for t in tests if ns.exclude.lower() not in t[0].lower()]
    if affected_names:
        tests = [t for t in tests if Path(t[0]).stem in affected_names]

    if ns.list:
        for rel, _p, tier in tests:
            reason = affected_reasons.get(Path(rel).stem, "")
            print(f"[{tier:6s}] {rel}" + (f"  ({reason})" if reason else ""))
        if affected_names and not tests:
            print("no discovered tests matched affected selection")
        return 0

    tier = ns.tier or ("all" if affected_paths else "core")
    selected = [t for t in tests if tier == "all" or t[2] == tier]
    skipped = len(tests) - len(selected)
    if not selected:
        print(f"no tests for tier={tier} (discovered {len(tests)})")
        return 0

    runs_dir = Path(ROOT) / "Test" / "_runs" / f"run_{time.strftime('%Y%m%d_%H%M%S')}"
    runs_dir.mkdir(parents=True, exist_ok=True)

    rounds = max(1, ns.stress)
    print(f"== test_runner | tier={tier} | {len(selected)} tests"
          f"{f' x{rounds} rounds' if rounds > 1 else ''} | runs: {runs_dir.relative_to(ROOT)} ==")
    results: list[dict] = []
    t0 = time.time()
    for round_no in range(1, rounds + 1):
        for i, (rel, path, _tier) in enumerate(selected, 1):
            r = run_one(rel, path, runs_dir, ns.timeout,
                        round_no=(round_no if rounds > 1 else 0))
            results.append(r)
            tag = "PASS" if r["passed"] else "FAIL"
            extra = f"  first_error: {r['first_error']}" if r["first_error"] and not r["passed"] else ""
            note = f"  [{r['note']}]" if r["note"] else ""
            prefix = f"r{round_no} " if rounds > 1 else ""
            print(f"[{prefix}{i:3d}/{len(selected)}] {tag}  {r['name']} ({r['elapsed']}s){note}{extra}")
            if not r["passed"]:
                print(f"        log: {r['log']}")

    total_time = time.time() - t0
    by_name: dict[str, list[dict]] = {}
    for r in results:
        by_name.setdefault(r["name"], []).append(r)
    failed_names = [n for n, rs in by_name.items() if any(not x["passed"] for x in rs)]
    passed_n = len(by_name) - len(failed_names)
    runs_n = len(results)
    runs_pass = sum(1 for r in results if r["passed"])
    print()
    rounds_info = (f" x{rounds} rounds ({runs_pass}/{runs_n} runs)"
                   if rounds > 1 else f" in {total_time:.0f}s")
    summary = (
        f"SUMMARY: {passed_n}/{len(by_name)} passed{rounds_info}"
        f" | failed: {', '.join(failed_names) if failed_names else '-'}"
        f" | tier={tier} | skipped={skipped} | runs: {runs_dir.relative_to(ROOT)}"
    )
    print(summary)
    if ns.json:
        first_fail_logs = {}
        for n in failed_names:
            for x in by_name[n]:
                if not x["passed"]:
                    first_fail_logs[n] = x["log"]
                    break
        print(json.dumps({
            "tier": tier,
            "total": len(by_name),
            "passed": passed_n,
            "failed": failed_names,
            "stress": rounds,
            "runs_total": runs_n,
            "runs_passed": runs_pass,
            "seconds": round(total_time, 1),
            "runs_dir": str(runs_dir.relative_to(ROOT)).replace("\\", "/"),
            "logs": first_fail_logs,
        }, ensure_ascii=False))
    return 0 if not failed_names else 1


if __name__ == "__main__":
    sys.exit(main())
