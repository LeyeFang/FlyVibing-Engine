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
TIER_RE = re.compile(r"TIER\s*[:=]\s*['\"]?(core|gui|heavy|live|manual)", re.IGNORECASE)

GUI_HINTS = ("gizmo", "grid", "outliner")
HEAVY_HINTS = ("export_game_bundle",)
LIVE_PREFIX = "e2e_"
MANUAL_HINTS = ("live_ui", "node_runtime")  # 交互式预览/演示 — 不进自动批次


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
        proc = subprocess.run(
            [sys.executable, str(path)],
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
    parser.add_argument("--tier", choices=("core", "gui", "heavy", "live", "all"), default="core")
    parser.add_argument("--only", default="", help="路径子串过滤（如 editor / functions / graph）")
    parser.add_argument("--exclude", default="", help="路径子串排除")
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

    tests = discover(ns.only or None)
    if ns.exclude:
        tests = [t for t in tests if ns.exclude.lower() not in t[0].lower()]

    if ns.list:
        for rel, _p, tier in tests:
            print(f"[{tier:6s}] {rel}")
        return 0

    selected = [t for t in tests if ns.tier == "all" or t[2] == ns.tier]
    skipped = len(tests) - len(selected)
    if not selected:
        print(f"no tests for tier={ns.tier} (discovered {len(tests)})")
        return 0

    runs_dir = Path(ROOT) / "Test" / "_runs" / f"run_{time.strftime('%Y%m%d_%H%M%S')}"
    runs_dir.mkdir(parents=True, exist_ok=True)

    rounds = max(1, ns.stress)
    print(f"== test_runner | tier={ns.tier} | {len(selected)} tests"
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
        f" | tier={ns.tier} | skipped={skipped} | runs: {runs_dir.relative_to(ROOT)}"
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
            "tier": ns.tier,
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
