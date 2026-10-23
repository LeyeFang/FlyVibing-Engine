"""
压力/竞态测试 — 线程协议验收 (Doc/Dev/threading_protocol.md §5)。

覆盖:
  A. ThreadRegistry 并行 churn: 6 线程各自 register/heartbeat/unregister + 并发 snapshot 读者;
     断言: 零异常 / 全部 join / beats 精确 == iters / 注销后无残留。
  B. LiveCommandServer 并发客户端: 8 客户端线程 x 10 ops(混合 op), 主线程 pump —
     处理器线程 + pump 队列的真实竞态; 断言: 全部应答且 ok。

确定性: 固定种子; 内部 4 轮; 外层放大用 `test_runner --stress N`。

运行:
  python Utils/Dev/test_runner.py --only stress
  .venv-py314t\\Scripts\\python.exe Test/Application/stress/test_stress_thread_races.py
"""
# TIER: core

from __future__ import annotations

import json
import os
import random
import socket
import sys
import threading
import time

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


def _setup_engine_env() -> None:
    """最小事件环境（op 处理器内部会 Pack 事件）。"""
    from Application.Core.Engine import Engine
    from Application.Core.Events.Event import BindPackCallback, _register_engine
    from Application.Core.Input.InputState import _set_default_input_state

    _register_engine(Engine)
    BindPackCallback(Engine._on_event)
    _set_default_input_state(Engine._get_input_state())


# ═══════════════════════════════════════════════════════════════
# A. ThreadRegistry 并行 churn
# ═══════════════════════════════════════════════════════════════

def case_registry_churn(rng: random.Random, n_threads: int = 6, iters: int = 120) -> None:
    from Application.Core.ThreadRegistry import ThreadRegistry

    errors: list[str] = []
    final_beats: dict[str, int] = {}
    snap_observed = [0]

    def churn(k: int) -> None:
        name = f"churn-{k}"
        try:
            ThreadRegistry.register(name, owner="stress", expect_hz=0.0)
            for i in range(iters):
                ThreadRegistry.heartbeat(name)
                if i % 13 == 0:
                    time.sleep(rng.random() * 0.0005)
            for t in ThreadRegistry.snapshot()["registered"]:
                if t["name"] == name:
                    final_beats[name] = t["beats"]
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
        finally:
            ThreadRegistry.unregister(name)

    def reader() -> None:
        try:
            for _ in range(iters):
                snap = ThreadRegistry.snapshot()
                snap_observed[0] += 1
                assert isinstance(snap["registered"], list)
                time.sleep(rng.random() * 0.0005)
        except Exception as e:  # noqa: BLE001
            errors.append(f"reader: {e}")

    threads = [threading.Thread(target=churn, args=(k,), daemon=True)
               for k in range(n_threads)]
    threads.append(threading.Thread(target=reader, daemon=True))
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)
    elapsed = time.perf_counter() - t0

    check("churn: no exceptions", not errors, str(errors[:3]))
    alive = [t for t in threads if t.is_alive()]
    check("churn: all threads joined", not alive, f"{len(alive)} alive")
    check("churn: beats exact per thread",
          all(final_beats.get(f"churn-{k}") == iters for k in range(n_threads)),
          str(final_beats))
    after = ThreadRegistry.snapshot()
    leftovers = [t["name"] for t in after["registered"] if t["name"].startswith("churn-")]
    check("churn: all unregistered after join", not leftovers, str(leftovers))
    check("churn: reader snapshots observed", snap_observed[0] > 0, str(snap_observed[0]))
    print(f"  [INFO] churn {n_threads}x{iters} in {elapsed * 1000:.0f} ms")


# ═══════════════════════════════════════════════════════════════
# B. SceneManager 实体注册表 churn（project.open / TextSystem.tick 同类）
# ═══════════════════════════════════════════════════════════════

def case_scene_registry_churn(rng: random.Random, n_writers: int = 4,
                              iters: int = 400) -> None:
    from Application.Core.Scene.SceneManager import SceneManager

    class _StressEngine:
        renderer = None
        scene = None

    st = SceneManager("StressScene", _StressEngine)
    errors: list[str] = []
    observed = [0]

    def writer(k: int) -> None:
        base = 10_000_000 + k * 1_000_000
        try:
            for i in range(iters):
                key = str(base + i)
                with st._entities_lock:
                    st.entities[key] = 1
                with st._entities_lock:
                    st.entities.pop(key, None)
                if i % 17 == 0:
                    time.sleep(rng.random() * 0.0005)
        except Exception as e:  # noqa: BLE001
            errors.append(f"writer-{k}: {e}")

    def reader() -> None:
        try:
            for _ in range(iters):
                ids = st.entity_ids_snapshot()
                assert all(isinstance(eid, int) for eid in ids)
                observed[0] += 1
                time.sleep(rng.random() * 0.0005)
        except Exception as e:  # noqa: BLE001
            errors.append(f"reader: {e}")

    threads = [threading.Thread(target=writer, args=(k,), daemon=True)
               for k in range(n_writers)]
    threads += [threading.Thread(target=reader, daemon=True) for _ in range(2)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)
    elapsed = time.perf_counter() - t0
    check("scene registry churn: no exceptions", not errors, str(errors[:3]))
    check("scene registry churn: readers observed snapshots",
          observed[0] > 0, str(observed[0]))
    check("scene registry churn: no temp keys left",
          not any(str(k) in st.entities for k in range(10_000_000, 14_000_000)),
          f"registry={len(st.entities)}")
    print(f"  [INFO] scene registry {n_writers} writers x {iters} in {elapsed * 1000:.0f} ms")


# ═══════════════════════════════════════════════════════════════
# C. LiveCommandServer 并发客户端
# ═══════════════════════════════════════════════════════════════

def case_server_concurrency(rng: random.Random, n_clients: int = 8,
                            ops_per_client: int = 10) -> None:
    from Application.Editor.Services.LiveCommandServer import LiveCommandServer

    ok = LiveCommandServer.start(port=0)
    check("server starts", ok)
    if not ok:
        return
    port = LiveCommandServer.port
    results: dict[int, list] = {i: [] for i in range(n_clients)}

    def client(tid: int) -> None:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=30.0) as conn:
                reader = conn.makefile("r", encoding="utf-8", newline="\n")
                for i in range(ops_per_client):
                    op = "threads.snapshot" if (i % 4 == 0) else "sim.state"
                    conn.sendall((json.dumps({"id": i, "op": op, "args": {}}) + "\n")
                                 .encode("utf-8"))
                    line = reader.readline()
                    resp = json.loads(line) if line else {}
                    results[tid].append(bool(resp.get("ok")))
                    time.sleep(rng.random() * 0.001)
        except OSError as e:
            results[tid].append(f"OSError: {e}")

    threads = [threading.Thread(target=client, args=(i,), daemon=True)
               for i in range(n_clients)]
    print(f"  [INFO] {n_clients} clients x {ops_per_client} ops on port {port}")
    for t in threads:
        t.start()
    deadline = time.monotonic() + 60.0
    while any(t.is_alive() for t in threads) and time.monotonic() < deadline:
        LiveCommandServer.pump()
        time.sleep(0.005)
    for t in threads:
        t.join(timeout=2.0)
    LiveCommandServer.stop()

    flat = [x for v in results.values() for x in v]
    check("concurrency: all ops answered",
          len(flat) == n_clients * ops_per_client, f"{len(flat)} answered")
    bad = [x for x in flat if x is not True]
    check("concurrency: all responses ok", not bad, str(bad[:3]))


# ═══════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════

def main() -> int:
    print("=" * 60)
    print("Stress — Thread Races (protocol: Doc/Dev/threading_protocol.md)")
    print("=" * 60)
    _setup_engine_env()
    rng = random.Random(20261005)
    rounds = 4
    for r in range(1, rounds + 1):
        print(f"-- round {r}/{rounds} --")
        case_registry_churn(rng)
        case_scene_registry_churn(rng)
        case_server_concurrency(rng)
    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
