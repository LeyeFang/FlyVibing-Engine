"""进程内控制台日志环形缓冲（stdout/stderr tee）。

用途:
  agent / CLI 侧没有终端时也能读引擎控制台输出 —— 通过 op `console.tail` 取最近若干行，
  用于诊断"节点图里的设备打开失败"这类只打印到控制台、不写返回值的问题。

设计:
  - `install()` 把 `sys.stdout` / `sys.stderr` 包成 tee（保留原输出 + 复制进环形缓冲）；
  - 行号单调递增（`seq`），`tail(since=...)` 只返回新行，适合轮询；
  - 缓冲有上限（默认 4000 行），超出后旧行被丢弃并在结果里标记 `dropped=true`；
  - 纯标准库、线程安全；在 `EntryPoint` 最早处安装，覆盖后续所有 print。
"""

from __future__ import annotations

import io
import sys
import threading
from collections import deque

_MAX_LINES = 4000
_MAX_LINE_CHARS = 2000


def _classify(text: str) -> str:
    """按文本粗分级别（print 没有级别，只能启发式）。"""
    low = text.strip().lower()
    if ("traceback (most recent call last)" in low
            or "[error]" in low or low.startswith("error")
            or " error:" in low or "[err]" in low):
        return "error"
    if "[warn" in low or "warning" in low or low.startswith("warn"):
        return "warn"
    return "info"


class LogBus:
    """全局环形缓冲（类级单例）。"""

    _lines: deque = deque(maxlen=_MAX_LINES)
    _seq: int = 0
    _dropped: int = 0
    _lock = threading.Lock()
    _installed = False
    _originals: tuple = ()

    # ── 写入 ────────────────────────────────────────────────

    @classmethod
    def push(cls, text: str) -> None:
        """写入一段文本（可含多行）。"""
        if not text:
            return
        parts = str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if parts and parts[-1] == "":
            parts.pop()
        if not parts:
            return
        with cls._lock:
            for line in parts:
                if len(line) > _MAX_LINE_CHARS:
                    line = line[:_MAX_LINE_CHARS] + "..."
                cls._seq += 1
                if len(cls._lines) == cls._lines.maxlen:
                    cls._dropped += 1
                cls._lines.append((cls._seq, _classify(line), line))

    # ── 读取 ────────────────────────────────────────────────

    @classmethod
    def tail(cls, since: int = 0, lines: int = 200,
             level: str | None = None) -> dict:
        """返回序号 > since 的最近 lines 行（可按 level 过滤）。

        Returns:
            {"lines": [{"seq", "level", "text"}], "next_since": int,
             "dropped": bool, "buffered": int}
        """
        limit = max(1, min(int(lines or 200), _MAX_LINES))
        want_level = (str(level).strip().lower() or None) if level else None
        with cls._lock:
            entries = [e for e in cls._lines if e[0] > int(since or 0)]
            if want_level:
                entries = [e for e in entries if e[1] == want_level]
            entries = entries[-limit:]
            next_since = entries[-1][0] if entries else int(since or 0)
            buffered = len(cls._lines)
            dropped = cls._dropped > 0
        return {
            "lines": [{"seq": s, "level": lv, "text": t} for s, lv, t in entries],
            "next_since": int(next_since),
            "dropped": bool(dropped),
            "buffered": int(buffered),
        }

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._lines.clear()
            cls._seq = 0
            cls._dropped = 0

    # ── tee 安装 ────────────────────────────────────────────

    @classmethod
    def install(cls) -> bool:
        """幂等安装 stdout/stderr tee；返回是否本次安装。"""
        if cls._installed:
            return False
        cls._originals = (sys.stdout, sys.stderr)
        sys.stdout = _Tee(sys.stdout)
        sys.stderr = _Tee(sys.stderr)
        cls._installed = True
        return True

    @classmethod
    def uninstall(cls) -> None:
        if not cls._installed:
            return
        out, err = cls._originals
        if out is not None:
            sys.stdout = out
        if err is not None:
            sys.stderr = err
        cls._installed = False


class _Tee(io.TextIOBase):
    """把写入同时转发给原流并记录到 LogBus。"""

    def __init__(self, target) -> None:
        self._target = target

    def write(self, text):  # noqa: D401 — file-like protocol
        if text:
            try:
                LogBus.push(text)
            except Exception:  # noqa: BLE001 — 日志失败不得影响主流程
                pass
        return self._target.write(text) if self._target is not None else len(text or "")

    def flush(self) -> None:
        if self._target is not None:
            try:
                self._target.flush()
            except Exception:  # noqa: BLE001
                pass

    def isatty(self) -> bool:
        return False

    @property
    def encoding(self):  # noqa: D401
        return getattr(self._target, "encoding", "utf-8")

    def fileno(self):
        return self._target.fileno()
