"""
渲染命令契约测试 — 16 个 RenderCommand 的 execute() 分派 + CommandQueue 语义（无 GL）。

覆盖:
  1. 命令注册表完整性（新增命令必须同步这里 — 分层契约守卫）
  2. 每条命令 execute(renderer) → 调用渲染器的哪个方法/参数（接口契约钉死）
  3. CommandQueue: FIFO 顺序 / execute_all 排空 / 并发入队无丢失 / 生产者-消费者
  4. 受控输入: ResizeCommand(0,0) 忽略; 属性写命令（SetViewProjection）的 attr 落点
  5. 原子批 (begin_batch/end_batch): staging 不可见 / 嵌套 / 线程隔离 / 并发不拆批

运行: python Utils/Dev/test_runner.py --only render_commands
"""
# TIER: core

from __future__ import annotations

import os
import sys
import threading
import time
import types

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


class RecordingRenderer:
    """方法调用与属性写全部入账的渲染器替身。"""

    def __init__(self) -> None:
        object.__setattr__(self, "calls", [])
        object.__setattr__(self, "attrs", {})

    def __getattr__(self, name):
        def _rec(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return _rec

    def __setattr__(self, name, value):
        self.attrs[name] = value
        object.__setattr__(self, name, value)


class _CountCmd:
    """并发压力用的最小命令（不是 RenderCommand 子类 — 只测队列容器语义）。"""
    __slots__ = ("i",)

    def __init__(self, i: int) -> None:
        self.i = i

    def execute(self, recorder) -> None:
        recorder.calls.append(self.i)


def main() -> int:
    print("=" * 60)
    print("RenderCommand 契约 + CommandQueue 语义 (headless)")
    print("=" * 60)

    import numpy as np
    from Application.Core.Renderer import RenderCommand as rc
    from Application.Core.Renderer.CommandQueue import CommandQueue

    # ── 1. 命令注册表完整性 ──
    print("── command registry ──")
    concrete = [c for c in vars(rc).values()
                if isinstance(c, type) and issubclass(c, rc.RenderCommand)
                and c is not rc.RenderCommand]
    check("16 concrete commands", len(concrete) == 16, str(sorted(c.__name__ for c in concrete)))

    # ── 2. 逐命令分派契约 ──
    print("── dispatch contract ──")
    rec = RecordingRenderer()
    view = np.eye(4, dtype=np.float32)
    proj = np.eye(4, dtype=np.float32)
    arr = np.zeros((4, 4, 4), dtype=np.uint8)
    cfg = types.SimpleNamespace(name="highlight")

    rc.ResizeCommand(800, 600).execute(rec)
    check("Resize → _on_window_resize", rec.calls[-1][0] == "_on_window_resize"
          and rec.calls[-1][1] == (800, 600))

    _n_before = len(rec.calls)
    rc.ResizeCommand(0, 0).execute(rec)
    check("Resize(0,0) ignored (no call)", len(rec.calls) == _n_before)

    before = len(rec.calls)
    rc.SetViewProjectionCommand(view=view, proj=proj, orbit_target=np.array([1, 2, 3]),
                                orbit_distance=7.5, is_orthographic=True,
                                ortho_size=5.0).execute(rec)
    ok_sp = (rec.attrs.get("_cached_view") is view
             and rec.attrs.get("_cached_proj") is proj
             and rec.attrs.get("_cam_ortho_size") == 5.0
             and rec.attrs.get("_cam_is_orthographic") is True
             and rec.attrs.get("_cam_orbit_distance") == 7.5
             and len(rec.calls) == before)   # 纯属性写, 无方法调用
    check("SetViewProjection → attr writes", ok_sp, str(rec.attrs.keys()))

    rc.EntityRegistrationCommand(7, True).execute(rec)
    check("EntityRegistration(+) → register_entity",
          rec.calls[-1][0] == "register_entity" and rec.calls[-1][1] == (7,))
    rc.EntityRegistrationCommand(7, False).execute(rec)
    check("EntityRegistration(-) → unregister_entity",
          rec.calls[-1][0] == "unregister_entity" and rec.calls[-1][1] == (7,))

    rc.TextureUpdateCommand(3, arr, 4, 4, 4).execute(rec)
    check("TextureUpdate → update_texture_data(同参)",
          rec.calls[-1][0] == "update_texture_data"
          and rec.calls[-1][1] == (3, arr, 4, 4, 4))

    rc.EntityVisibilityCommand(9, False).execute(rec)
    check("Visibility(False) → hide_entity",
          rec.calls[-1][0] == "hide_entity" and rec.calls[-1][1] == (9,))
    rc.EntityVisibilityCommand(9, True).execute(rec)
    check("Visibility(True) → show_entity", rec.calls[-1][0] == "show_entity")

    rc.EntityRenderVisibleCommand(9, False).execute(rec)
    check("RenderVisible → set_entity_render_visible",
          rec.calls[-1][0] == "set_entity_render_visible" and rec.calls[-1][1] == (9, False))

    rc.OverlayRegistrationCommand(cfg).execute(rec)
    check("OverlayRegistration → register_overlay_drawable",
          rec.calls[-1][0] == "register_overlay_drawable" and rec.calls[-1][1] == (cfg,))
    rc.OverlayUnregistrationCommand("grid").execute(rec)
    check("OverlayUnregistration → unregister_overlay_drawable",
          rec.calls[-1][0] == "unregister_overlay_drawable" and rec.calls[-1][1] == ("grid",))

    rc.RegisterHighlightEffectCommand(cfg).execute(rec)
    check("Highlight register", rec.calls[-1][0] == "register_highlight_effect")
    rc.UnregisterHighlightEffectCommand().execute(rec)
    check("Highlight unregister (无参)",
          rec.calls[-1][0] == "unregister_highlight_effect" and rec.calls[-1][1] == ())

    rc.UpdateHighlightSelectionCommand({1, 2}).execute(rec)
    check("Highlight selection", rec.calls[-1][0] == "update_highlight_selection"
          and rec.calls[-1][1] == ({1, 2},))
    rc.UpdateHighlightConfigCommand(color=(1.0, 0.0, 0.0), width=5).execute(rec)
    check("Highlight config kwargs", rec.calls[-1][0] == "update_highlight_config"
          and rec.calls[-1][2] == {"color": (1.0, 0.0, 0.0), "width": 5, "xray": None})

    rc.SetClearColorCommand(0.1, 0.2, 0.3, 0.4).execute(rec)
    check("SetClearColor", rec.calls[-1][0] == "set_clear_color"
          and rec.calls[-1][1] == (0.1, 0.2, 0.3, 0.4))

    rc.CreateRenderTargetCommand(500, 128, 64, with_depth=False).execute(rec)
    check("CreateRenderTarget → create_render_target",
          rec.calls[-1][0] == "create_render_target"
          and rec.calls[-1][1] == (500, 128, 64)
          and rec.calls[-1][2] == {"with_depth": False})

    rc.DestroyRenderTargetCommand(500).execute(rec)
    check("DestroyRenderTarget → destroy_render_target",
          rec.calls[-1][0] == "destroy_render_target" and rec.calls[-1][1] == (500,))

    rc.SetSceneTargetCommand(500).execute(rec)
    check("SetSceneTarget → set_scene_target",
          rec.calls[-1][0] == "set_scene_target" and rec.calls[-1][1] == (500,))

    # ── 3. CommandQueue 语义 ──
    print("── CommandQueue ──")
    q = CommandQueue()
    q.enqueue(rc.ResizeCommand(1, 1))
    q.enqueue(rc.SetClearColorCommand(0.5, 0.5, 0.5, 1.0))
    q.enqueue(rc.EntityRegistrationCommand(5, True))
    check("len counts pending", len(q) == 3, str(len(q)))

    rec2 = RecordingRenderer()
    q.execute_all(rec2)
    order = [c[0] for c in rec2.calls]
    check("FIFO order preserved",
          order == ["_on_window_resize", "set_clear_color", "register_entity"], str(order))
    check("execute_all drains", len(q) == 0)

    # ── 3b. 原子批: 一批命令要么整批被消费, 要么全部不可见 ──
    print("── command batch (atomic beat) ──")
    qb = CommandQueue()
    qb.begin_batch()
    check("batch active", qb.batch_active)
    qb.enqueue(rc.SetClearColorCommand(0.1, 0.1, 0.1, 1.0))
    qb.enqueue_many([rc.ResizeCommand(64, 64)])
    check("len includes staged", len(qb) == 2, str(len(qb)))
    drained = qb.dequeue_all()
    check("drain during open batch sees nothing", drained == [], str(len(drained)))
    qb.enqueue(rc.EntityRegistrationCommand(3, True))
    qb.end_batch()
    check("batch closed", not qb.batch_active)
    drained = qb.dequeue_all()
    check("batch flushes as one unit (3 cmds)", len(drained) == 3, str(len(drained)))

    # 嵌套: 仅深度归零时入队
    qb.begin_batch()
    qb.begin_batch()
    qb.enqueue(rc.ResizeCommand(8, 8))
    qb.end_batch()
    check("nested: still staged after inner end", len(qb) == 1)
    qb.end_batch()
    check("nested: flushed at depth 0", len(qb) == 1 and not qb.batch_active)
    qb.dequeue_all()

    # 线程隔离: 其他线程入队不被本线程批暂存
    qb.begin_batch()
    qb.enqueue(rc.SetClearColorCommand(0.3, 0.3, 0.3, 1.0))
    t_other = threading.Thread(target=lambda: qb.enqueue(rc.ResizeCommand(5, 5)))
    t_other.start()
    t_other.join()
    drained = qb.dequeue_all()
    check("other thread bypasses staging", len(drained) == 1
          and drained[0].__class__ is rc.ResizeCommand,
          str([type(d).__name__ for d in drained]))
    qb.end_batch()
    drained = qb.dequeue_all()
    check("main-thread staged cmd flushed after", len(drained) == 1
          and drained[0].__class__ is rc.SetClearColorCommand,
          str([type(d).__name__ for d in drained]))

    # 并发: 批生产者 vs 消费者 — 任何一次 drain 不得出现"半批"
    qb2 = CommandQueue()
    K, N = 5, 120
    def _batched_producer() -> None:
        for b in range(N):
            qb2.begin_batch()
            for j in range(K):
                qb2.enqueue(_CountCmd(b * K + j))
            qb2.end_batch()
    tb = threading.Thread(target=_batched_producer)
    tb.start()
    got: list[int] = []
    partial = 0
    deadline = time.monotonic() + 10.0
    while len(got) < N * K and time.monotonic() < deadline:
        chunk = qb2.dequeue_all()
        if not chunk:
            time.sleep(0.0002)
            continue
        per_batch: dict[int, int] = {}
        for c in chunk:
            per_batch[c.i // K] = per_batch.get(c.i // K, 0) + 1
        if any(cnt != K for cnt in per_batch.values()):
            partial += 1
        got.extend(c.i for c in chunk)
    tb.join(timeout=5.0)
    check("no partial batch across concurrent drains",
          partial == 0 and len(got) == N * K and len(set(got)) == N * K,
          f"partial={partial} got={len(got)}")

    # 并发入队（4 线程 × 250）
    q2 = CommandQueue()
    N_THREADS, N_EACH = 4, 250
    def _producer(tid: int) -> None:
        for i in range(N_EACH):
            q2.enqueue(_CountCmd(tid * N_EACH + i))
    ts = [threading.Thread(target=_producer, args=(t,)) for t in range(N_THREADS)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    check("concurrent enqueue count", len(q2) == N_THREADS * N_EACH, str(len(q2)))
    sink = types.SimpleNamespace(calls=[])
    q2.execute_all(sink)
    check("concurrent enqueue no loss/dup",
          len(sink.calls) == N_THREADS * N_EACH and len(set(sink.calls)) == N_THREADS * N_EACH,
          f"{len(sink.calls)}/{len(set(sink.calls))}")

    # 生产者-消费者交错（1 生产 + 主线程反复排空）
    q3 = CommandQueue()
    TOTAL = 500
    def _producer3() -> None:
        for i in range(TOTAL):
            q3.enqueue(_CountCmd(i))
            time.sleep(0.0002)
    tp = threading.Thread(target=_producer3)
    tp.start()
    got: list[int] = []
    deadline = time.monotonic() + 10.0
    while len(got) < TOTAL and time.monotonic() < deadline:
        got.extend(cmd.i for cmd in q3.dequeue_all())
        time.sleep(0.0005)
    tp.join(timeout=2.0)
    check("interleaved producer/consumer", len(got) == TOTAL and len(set(got)) == TOTAL,
          f"{len(got)}/{len(set(got))}")

    total = _RESULTS["pass"] + _RESULTS["fail"]
    status = "OK" if _RESULTS["fail"] == 0 else "FAIL"
    print()
    print(f"RESULT: {status} ({_RESULTS['pass']}/{total})")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
