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

数据格式约定: 裸 RGBA8, bottom-up（GL 原生行序）; 翻转与 PNG 编码由 MCP 进程处理。
"""

from __future__ import annotations

import threading


class FrameCaptureSlot:
    """单槽抓帧信箱 — 一进一出, 不做多帧缓存。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_gen = 0
        self._pending_gen: int | None = None
        self._latest: dict | None = None   # {generation,width,height,payload,error}

    # ── 主线程 ────────────────────────────────────────────────

    def request(self) -> dict:
        """请求抓取"下一渲染帧"。返回 {"generation": N}。"""
        with self._lock:
            self._next_gen += 1
            self._pending_gen = self._next_gen
            return {"generation": self._next_gen}

    def fetch(self, generation: int | None = None) -> dict:
        """按代数取帧。

        Returns:
            {"ready": True, "state": "ready", "generation", "width", "height", "payload": bytes}
            {"ready": False, "state": "pending"}
            {"ready": False, "state": "superseded", "latest_generation": N}
            {"ready": False, "state": "error", "error": "..."}
        """
        with self._lock:
            latest = self._latest
        if latest is None:
            return {"ready": False, "state": "pending"}
        latest_gen = latest["generation"]
        if generation is not None and latest_gen != generation:
            if latest_gen > generation:
                return {"ready": False, "state": "superseded", "latest_generation": latest_gen}
            return {"ready": False, "state": "pending"}   # 目标代尚未抓到
        if latest["error"] is not None:
            return {"ready": False, "state": "error",
                    "error": latest["error"], "generation": latest_gen}
        return {
            "ready": True,
            "state": "ready",
            "generation": latest_gen,
            "width": latest["width"],
            "height": latest["height"],
            "payload": latest["payload"],
        }

    # ── 渲染线程 ──────────────────────────────────────────────

    def take_pending(self) -> int | None:
        """取走"待抓取"请求（渲染线程每帧末调用一次; 无请求返回 None）。"""
        with self._lock:
            gen = self._pending_gen
            self._pending_gen = None
            return gen

    def publish(self, generation: int, width: int, height: int, payload: bytes) -> None:
        """发布抓帧结果（裸 RGBA8, bottom-up）。"""
        with self._lock:
            self._latest = {
                "generation": generation,
                "width": int(width),
                "height": int(height),
                "payload": payload,
                "error": None,
            }

    def publish_error(self, generation: int, message: str) -> None:
        """发布抓帧失败（渲染线程内任意 GL 异常）。"""
        with self._lock:
            self._latest = {
                "generation": generation,
                "width": 0,
                "height": 0,
                "payload": None,
                "error": str(message),
            }
