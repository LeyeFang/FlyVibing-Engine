"""Regression: Scene 并发安全（2026-11-10 P0 竞态修复）。

事故
    渲染线程的 `NodeEditorPanel._ensure_default_scene()`（每帧）与主线程的
    `SimulationController._sync_ecs_to_scene()`（点 Play）都在重建
    `Scene.entities`，而主线程 `copy.deepcopy(editor_scene)` 同时在迭代它：

        RuntimeError: dictionary changed size during iteration
        → 抛在 Engine._render_loop → 编辑器 exit code 1

修复三层（本测试逐层验）
    1. Mutator 加锁（add_entity / remove_entity / set_component / remove_component）
    2. 批量重建走 `replace_entities()` —— 整表原子替换，读方永不见半空表
    3. `__deepcopy__` 锁内快照 + 离线构造（RLock 不可深拷贝，必须手工重建）

额外验: 深拷贝独立性（改副本不影响原图，包括 node_graph）与"新锁不共享"。
"""
# TIER: core

from __future__ import annotations

import copy
import os
import sys
import threading
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Application.Core.Scene.Scene import Scene, EntityData, GameType  # noqa: E402
from Application.Core.Scene.BasicComponents import Transform  # noqa: E402

_RESULTS = {"pass": 0, "fail": 0}


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    _RESULTS["pass" if cond else "fail"] += 1
    suffix = f"  ({detail})" if detail and not cond else ""
    print(f"  [{tag}] {label}{suffix}")


def _make_scene(n: int = 16) -> Scene:
    scene = Scene(name="RaceProbe")
    for i in range(n):
        scene.add_entity(f"E{i}", Transform=Transform(position_x=float(i)))
    return scene


def _build_batch(n: int, tag: int) -> dict[int, EntityData]:
    """模拟 _sync_ecs_to_scene / _ensure_default_scene 的整表重建。"""
    return {
        i + 1: EntityData(name=f"E{i}_v{tag}",
                          components={"Transform": Transform(position_x=float(i + tag))})
        for i in range(n)
    }


def main() -> int:
    # ── A. 基本语义没变 ──
    s = Scene(name="Basic")
    eid = s.add_entity("Cube", Transform=Transform(position_x=1.0))
    check("add_entity 返回 id", isinstance(eid, int) and eid > 0, str(eid))
    check("get_entity 拿到", s.get_entity(eid) is not None)
    check("get_entity_names", s.get_entity_names() == ["Cube"], str(s.get_entity_names()))
    check("get_entity_by_name", (s.get_entity_by_name("Cube") or (None,))[0] == eid)
    check("entities_snapshot 是副本",
          s.entities_snapshot() is not s.entities)
    s.remove_entity(eid)
    check("remove_entity 生效", s.get_entity(eid) is None)

    # ── B. replace_entities 是原子替换（旧引用不变）──
    s2 = _make_scene(4)
    old_ref = s2.entities
    old_len = len(old_ref)
    s2.replace_entities(_build_batch(9, 1))
    check("replace_entities 换掉引用", s2.entities is not old_ref)
    check("旧引用内容未被修改（读方安全）", len(old_ref) == old_len, str(len(old_ref)))
    check("新表长度正确", len(s2.entities) == 9, str(len(s2.entities)))

    # ── C. deepcopy 正确性 + 独立性 ──
    s3 = _make_scene(3)
    s3.node_graph = {"nodes": {"1": {"x": 1}}, "links": {}}
    s3.ambient_color = (0.1, 0.2, 0.3)
    s3.game_type = GameType.GAME_2D
    dup = copy.deepcopy(s3)
    check("deepcopy 实体数一致", len(dup.entities) == len(s3.entities))
    check("deepcopy 独立（改副本不影响原图）",
          dup.entities[1] is not s3.entities[1])
    dup.entities[1].name = "MUTATED"
    check("改副本名字不影响原件", s3.entities[1].name != "MUTATED",
          s3.entities[1].name)
    dup.node_graph["nodes"]["1"]["x"] = 999
    check("node_graph 也独立", s3.node_graph["nodes"]["1"]["x"] == 1)
    check("game_type / ambient 正确复制",
          dup.game_type == GameType.GAME_2D and dup.ambient_color == (0.1, 0.2, 0.3),
          f"{dup.game_type} {dup.ambient_color}")
    check("副本有自己的锁", dup._entities_lock is not s3._entities_lock)
    check("_next_sid 正常复制", dup._next_sid == s3._next_sid,
          f"{dup._next_sid} vs {s3._next_sid}")

    # 深拷贝后还能正常用（锁没坏）
    try:
        dup.add_entity("AfterCopy", Transform=Transform())
        ok_lock = len(dup.entities) == len(s3.entities) + 1
    except BaseException as exc:                      # noqa: BLE001
        ok_lock = False
        print(f"    (add_entity on copy raised: {type(exc).__name__}: {exc})")
    check("副本的锁可用", ok_lock)

    # ── D. 并发：writer 整表重建 + 原地增删，reader 深拷贝/序列化/摘要 ──
    scene = _make_scene(16)
    stop = threading.Event()
    errors: list[str] = []

    def _writer_batch() -> None:
        tag = 0
        try:
            while not stop.is_set():
                tag += 1
                scene.replace_entities(_build_batch(16 + (tag % 5), tag))
        except BaseException as exc:                  # noqa: BLE001
            errors.append(f"batch writer: {type(exc).__name__}: {exc}")

    def _writer_inplace() -> None:
        try:
            while not stop.is_set():
                eid = scene.add_entity("Tmp", Transform=Transform())
                scene.remove_entity(eid)
        except BaseException as exc:                  # noqa: BLE001
            errors.append(f"inplace writer: {type(exc).__name__}: {exc}")

    stats = {"deepcopy": 0, "to_dict": 0, "summary": 0, "names": 0}

    def _reader() -> None:
        t0 = time.perf_counter()
        try:
            while time.perf_counter() - t0 < 2.5:
                copy.deepcopy(scene)
                stats["deepcopy"] += 1
                scene.to_dict()
                stats["to_dict"] += 1
                scene.summary()
                stats["summary"] += 1
                scene.get_entity_names()
                stats["names"] += 1
        except BaseException as exc:                  # noqa: BLE001
            errors.append(f"reader: {type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=_writer_batch, daemon=True),
               threading.Thread(target=_writer_inplace, daemon=True),
               threading.Thread(target=_reader, daemon=True)]
    for t in threads:
        t.start()
    t_reader = threads[-1]
    t_reader.join(timeout=10.0)
    stop.set()
    for t in threads[:2]:
        t.join(timeout=2.0)

    check("并发期零异常", not errors, "; ".join(errors[:3]))
    check("并发期 reader 完成足够多轮",
          stats["deepcopy"] > 100 and stats["to_dict"] > 100, str(stats))

    # ── E. 并发的"旧写法"仍会崩（说明我们真的在保护，而不是恰好没撞上）──
    naive = _make_scene(16)
    stop2 = threading.Event()
    naive_err = []

    def _naive_writer() -> None:
        try:
            while not stop2.is_set():
                # 这正是修复前的写法: clear + 逐条 add（半空表窗口）
                naive.entities.clear()
                for i in range(16):
                    naive.entities[i + 1] = EntityData(
                        name=f"n{i}", components={"Transform": Transform()})
        except BaseException as exc:                  # noqa: BLE001
            naive_err.append(str(exc))

    th = threading.Thread(target=_naive_writer, daemon=True)
    th.start()
    naive_failures = 0
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 1.2:
        try:
            # 注意: 这里**故意**用默认深拷贝路径的等价物（直接迭代 live dict）
            for _k, _v in naive.entities.items():
                pass
        except RuntimeError:
            naive_failures += 1
        except BaseException:                          # noqa: BLE001
            naive_failures += 1
    stop2.set()
    th.join(timeout=2.0)
    check("对照: 旧写法确实会崩（证明修复有意义）", naive_failures > 0,
          f"failures={naive_failures}")

    print(f"RESULT: {_RESULTS['pass']}/{_RESULTS['pass'] + _RESULTS['fail']} passed, "
          f"{_RESULTS['fail']} failed")
    return 0 if _RESULTS["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
