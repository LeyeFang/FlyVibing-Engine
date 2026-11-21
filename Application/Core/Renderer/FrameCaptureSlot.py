"""
FrameCaptureSlot — 渲染线程帧末抓帧的单槽信箱（Editor Live MCP 的引擎侧实现）。

线程模型（free-threading 无 GIL — 只碰锁内小状态, 图像数据是不可变 bytes）:
  - request()      : 编辑器主线程（LiveCommandServer pump 的 op 处理器）;
  - take_pending() : 目标引擎渲染线程每帧末一次（Engine._maybe_capture）;
  - publish()      : 目标引擎渲染线程（glReadPixels 裸字节）;
  - fetch()        : 编辑器主线程（读取结果）。

generation 语义:
  - 每次 request 递增 generation; 只保留"最新未抓取"请求（旧请求被覆盖 → superseded）;
  - fetch(generation) 校验代数: 匹配 → ready; 已有更新代 → superseded; 尚未抓到 → pending。

blank 语义（2026-11-01）:
  - 渲染线程读回后看一眼是否**整帧全 0（RGBA 全透明）**; 是则置 blank=True。
  - 全透明帧没有信息量（上下文刚建/窗口还没画/被遮挡）——上层（probe / capture）
    靠它重试或显式告警，而不是把 0 当成"颜色就是黑"报给调用方。

租约语义（2026-11-16 — 抓帧永不无限 pending）:
  - `request()` 记录时刻; `fetch()` 发现该代**尚未发布**且已等待超过租约（默认 10s）
    → 返回 `state="expired"`。渲染线程不产帧（窗口最小化 / 远程桌面 / 驱动阻塞）时,
    轮询方在租约处拿到确定结论, 而不是永远 pending 把 agent 会话拖死。
  - 租约到期**不清除**原始请求: 渲染线程此后若真的产出帧, 该帧仍然可取回（先到先得）。

数据格式约定: 裸 RGBA8, bottom-up（GL 原生行序）; 翻转与 PNG 编码由 MCP 进程处理。
"""

from __future__ import annotations

import threading
import time


class FrameCaptureSlot:
    """单槽抓帧信箱 — 一进一出, 不做多帧缓存。"""

    #: 默认租约（秒）。`frame.request` 可用 `lease_s` 逐次覆盖。
    DEFAULT_LEASE_S = 10.0
    #: 同时在追踪的请求上限（多 agent 并发抓帧; 超出后最老的请求判 expired）
    MAX_TRACKED_REQUESTS = 64

    def __init__(self, lease_s: float = DEFAULT_LEASE_S) -> None:
        self._lock = threading.Lock()
        self._next_gen = 0
        self._pending_gen: int | None = None
        # generation → (发起时刻 monotonic, 租约秒); publish/覆盖/淘汰 时移除。
        # 用字典而不是单个"当前请求": 两个 agent 并发抓帧时, 老代也必须能过期,
        # 否则先请求的一方会永远 pending。
        self._requests: dict[int, tuple[float, float]] = {}
        self._lease_s: float = float(lease_s)
        self._latest: dict | None = None   # {generation,width,height,payload,error}

    @property
    def lease_s(self) -> float:
        """默认租约（秒）; <=0 表示关闭（仅测试/调试用）。"""
        return self._lease_s

    @lease_s.setter
    def lease_s(self, value: float) -> None:
        self._lease_s = float(value)

    # ── 主线程 ────────────────────────────────────────────────

    def request(self, lease_s: float | None = None) -> dict:
        """请求抓取"下一渲染帧"。返回 {"generation": N}。

        lease_s: 本次请求的租约（秒）; None → 用默认值。
        """
        with self._lock:
            self._next_gen += 1
            self._pending_gen = self._next_gen
            self._requests[self._next_gen] = (
                time.monotonic(),
                self._lease_s if lease_s is None else float(lease_s),
            )
            while len(self._requests) > self.MAX_TRACKED_REQUESTS:
                self._requests.pop(next(iter(self._requests)), None)
            return {"generation": self._next_gen}

    def fetch(self, generation: int | None = None) -> dict:
        """按代数取帧。

        Returns:
            {"ready": True, "state": "ready", "generation", "width", "height", "payload": bytes}
            {"ready": False, "state": "pending"}
            {"ready": False, "state": "expired", "error", "pending_ms"}
            {"ready": False, "state": "superseded", "latest_generation": N}
            {"ready": False, "state": "error", "error": "..."}
        """
        with self._lock:
            latest = self._latest
            tracked = self._requests.get(generation) if generation is not None else None

        latest_gen = latest["generation"] if latest is not None else None

        # ── 该代已发布 ──
        if generation is not None and latest_gen == generation:
            if latest["error"] is not None:
                return {"ready": False, "state": "error",
                        "error": latest["error"], "generation": latest_gen}
            return {
                "ready": True,
                "state": "ready",
                "generation": latest_gen,
                "width": latest["width"],
                "height": latest["height"],
                "blank": bool(latest.get("blank")),
                "payload": latest["payload"],
            }
        # ── 新代已发布, 目标代被覆盖 ──
        if generation is not None and latest_gen is not None and latest_gen > generation:
            return {"ready": False, "state": "superseded", "latest_generation": latest_gen}

        # ── 目标代尚未发布: 先看租约（排队中 / 已交给渲染线程但没回） ──
        if generation is not None:
            if tracked is None:
                return {
                    "ready": False,
                    "state": "expired",
                    "generation": generation,
                    "error": (f"抓帧请求 generation={generation} 已不再被跟踪"
                              "（被更新的请求挤出/覆盖）— 重新发起 frame.request"),
                }
            started_at, lease = tracked
            if lease > 0:
                waited = time.monotonic() - started_at
                if waited > lease:
                    return {
                        "ready": False,
                        "state": "expired",
                        "generation": generation,
                        "pending_ms": round(waited * 1000.0, 1),
                        "error": (f"渲染线程 {lease:g}s 内没有产出新帧（generation={generation}）"
                                  f" — 窗口最小化/被遮挡/远程桌面/驱动阻塞"),
                    }

        if generation is None:
            if latest is None:
                return {"ready": False, "state": "pending"}
            if latest["error"] is not None:
                return {"ready": False, "state": "error",
                        "error": latest["error"], "generation": latest_gen}
            return {
                "ready": True,
                "state": "ready",
                "generation": latest_gen,
                "width": latest["width"],
                "height": latest["height"],
                "blank": bool(latest.get("blank")),
                "payload": latest["payload"],
            }

        return {"ready": False, "state": "pending"}

    # ── 渲染线程 ──────────────────────────────────────────────

    def take_pending(self) -> int | None:
        """取走"待抓取"请求（渲染线程每帧末调用一次; 无请求返回 None）。

        取走只表示"渲染线程开始处理"; 该代仍留在租约表里, 所以渲染线程卡在
        glReadPixels 时 `fetch` 不会永远 pending, 而是在租约处给出 expired。
        """
        with self._lock:
            gen = self._pending_gen
            self._pending_gen = None
            return gen

    def publish(self, generation: int, width: int, height: int, payload: bytes,
                blank: bool = False) -> None:
        """发布抓帧结果（裸 RGBA8, bottom-up; blank=整帧全 0）。"""
        with self._lock:
            self._requests.pop(generation, None)
            self._latest = {
                "generation": generation,
                "width": int(width),
                "height": int(height),
                "payload": payload,
                "blank": bool(blank),
                "error": None,
            }

    def publish_error(self, generation: int, message: str) -> None:
        """发布抓帧失败（渲染线程内任意 GL 异常）。"""
        with self._lock:
            self._requests.pop(generation, None)
            self._latest = {
                "generation": generation,
                "width": 0,
                "height": 0,
                "payload": None,
                "error": str(message),
            }
