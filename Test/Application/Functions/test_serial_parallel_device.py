"""
Test: SerialParallelDevice — 串口/并口 I/O 模块单元测试
═══════════════════════════════════════════════════════════════

测试范围:
  - protocol.encode/decode  所有格式 (string / bytes / byte)
  - I/O 线程生命周期         start / stop / is_running
  - 租约所有权              editor / runtime 交权（单线程, 多租约）
  - 严格写入                strict=True → DeviceNotReady（面板/op 路径）
  - 串口 send()             无真实串口时不崩溃
  - 并口 write_parallel()   无驱动时优雅降级
  - Mock 并口驱动            验证写入 + 自动复位
  - 复位延迟可配置          set_reset_delay(ms) → 调度截止时间
  - 面板载荷校验            extension.parallel_payload（byte/bytes/string）
  - uint8 钳位              0→1, 256→255, 负数→1

运行: python Test/Application/Functions/test_serial_parallel_device.py
"""

from __future__ import annotations

import sys, os, time, struct, threading
from unittest.mock import MagicMock, call, patch

# ── path setup ──
_d = os.path.dirname(os.path.abspath(__file__))
while _d and not os.path.exists(os.path.join(_d, '_path_setup.py')):
    _d = os.path.dirname(_d)
if _d:
    sys.path.insert(0, _d)
import _path_setup  # noqa: E402

from Application.Functions.SerialParallelDevice import (
    start, stop, send, write_parallel,
    is_running, parallel_ready,
    _test_get_reset_schedule, _test_clear_reset_schedule,
    _test_inject_parallel, _test_get_parallel_driver,
)
from Application.Functions.SerialParallelDevice.protocol import encode, decode

_TAG = "[TEST-SPD]"
_PASS = 0
_FAIL = 0


def check(cond: bool, name: str) -> bool:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  [PASS] {name}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {name}")
    return cond


def _wait_until(pred, timeout: float = 1.0, step: float = 0.005) -> bool:
    """有界轮询: 等待 pred() 为真。消除固定 sleep 的线程调度 flaky。"""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if pred():
            return True
        time.sleep(step)
    return pred()


# ═══════════════════════════════════════════════════════════════
# Protocol 编码/解码
# ═══════════════════════════════════════════════════════════════

def test_protocol():
    print("── Protocol ──")

    # string — 协议约定: 自动追加 "\n" 终止符 (设备端命令需要换行)
    data = encode("hello", "string")
    check(data == b"hello\n", "encode string (+\\n)")
    check(encode("hi\n", "string") == b"hi\n", "encode string no double newline")
    check(decode(b"hello", "string") == "hello", "decode string")
    check(encode(123, "string") == b"123\n", "encode int as string")

    # bytes (float32 LE)
    data = encode(1.0, "bytes")
    check(len(data) == 4, "bytes length = 4")
    val = decode(data, "bytes")
    check(abs(val - 1.0) < 0.001, f"decode bytes 1.0 → {val}")

    data = encode(3.14, "bytes")
    val = decode(data, "bytes")
    check(abs(val - 3.14) < 0.01, f"decode bytes 3.14 → {val}")

    # byte (uint8, clamped 1-255)
    check(encode(1, "byte") == b"\x01", "byte 1")
    check(encode(255, "byte") == b"\xff", "byte 255")

    # 钳位
    check(encode(0, "byte") == b"\x01", "byte 0 → 1 (clamped)")
    check(encode(256, "byte") == b"\xff", "byte 256 → 255 (clamped)")
    check(encode(-5, "byte") == b"\x01", "byte -5 → 1 (clamped)")

    # decode (byte format not in decode, so skip decode test for byte)


# ═══════════════════════════════════════════════════════════════
# I/O 线程生命周期
# ═══════════════════════════════════════════════════════════════

def test_thread_lifecycle():
    print("── Thread Lifecycle ──")

    # 先确保是停止状态
    if is_running():
        stop()
        time.sleep(0.1)

    check(not is_running(), "initially stopped")

    start()
    time.sleep(0.05)
    check(is_running(), "started")

    # 幂等
    start()
    time.sleep(0.05)
    check(is_running(), "start idempotent")

    stop()
    time.sleep(0.1)
    check(not is_running(), "stopped")

    # 幂等
    stop()
    check(not is_running(), "stop idempotent")


# ═══════════════════════════════════════════════════════════════
# 串口 — 无硬件不崩溃
# ═══════════════════════════════════════════════════════════════

def test_serial_send():
    print("── Serial Send ──")

    start()
    time.sleep(0.05)

    # 无真实串口时不应崩溃，只是打印 drop 日志
    send("COM99", 9600, b"\x00\x00\x80\x3f")
    time.sleep(0.1)  # 给 I/O 线程时间处理

    send("COM99", 115200, b"hello")
    time.sleep(0.1)

    stop()
    time.sleep(0.1)
    check(True, "serial send no crash")


# ═══════════════════════════════════════════════════════════════
# 并口 — 无驱动优雅降级
# ═══════════════════════════════════════════════════════════════

def test_parallel_no_driver():
    print("── Parallel (no driver) ──")

    # 保存真实驱动
    real_pp = _test_get_parallel_driver()
    _test_inject_parallel(None)

    check(not parallel_ready(), "parallel_ready=False without driver")

    start()
    time.sleep(0.05)

    # 不应崩溃
    write_parallel(0x378, 1.0, "bytes")
    write_parallel(0x378, 42, "byte")
    time.sleep(0.1)

    # 无驱动时不应有复位调度
    sched = _test_get_reset_schedule()
    check(len(sched) == 0, f"no resets when driver absent (got {len(sched)})")

    stop()
    time.sleep(0.1)

    # 恢复
    _test_inject_parallel(real_pp)


# ═══════════════════════════════════════════════════════════════
# 并口 — Mock 驱动验证写入 + 自动复位
# ═══════════════════════════════════════════════════════════════

def test_parallel_mock():
    print("── Parallel (mock driver) ──")

    # 创建 mock 驱动
    mock_pp = MagicMock()
    mock_pp.out8 = MagicMock()
    mock_pp.driver_open = MagicMock(return_value=True)
    _test_inject_parallel(mock_pp)

    check(parallel_ready(), "parallel_ready=True with mock")

    _test_clear_reset_schedule()
    start()
    time.sleep(0.05)

    # ── 写入后立即检查调度 (2ms < 5ms 复位窗口; 重试容忍线程调度抖动) ──
    sched = []
    for _ in range(3):
        _test_clear_reset_schedule()
        write_parallel(0x378, 0x55, "byte")
        time.sleep(0.002)  # 只等 I/O 线程取走任务，不等复位
        sched = _test_get_reset_schedule()
        if len(sched) == 1:
            break

    # 验证写入
    mock_pp.out8.assert_any_call(0x378, 0x55)
    print(f"  [INFO] out8 call count after write: {mock_pp.out8.call_count}")

    # 调度中应有 1 个待复位 (5ms 还没过)
    check(len(sched) == 1, f"reset scheduled (got {len(sched)})")
    if sched:
        deadline, addr, count = sched[0]
        check(addr == 0x378, f"reset addr=0x378 (got 0x{addr:04X})")
        check(count == 1, f"reset byte_count=1 (got {count})")

    # ── 等待复位触发 (有界轮询: 复位窗口 5ms) ──
    mock_pp.out8.reset_mock()
    _wait_until(lambda: len(_test_get_reset_schedule()) == 0, timeout=1.0)

    # 调度应已清空
    sched_after = _test_get_reset_schedule()
    check(len(sched_after) == 0, f"reset consumed (remaining: {len(sched_after)})")

    # 验证复位调用了 out8(0x378, 0)
    reset_calls = [c for c in mock_pp.out8.call_args_list
                   if c == call(0x378, 0)]
    check(len(reset_calls) >= 1,
          f"reset out8(0x378, 0) called ({len(reset_calls)} times)")

    # ── 写入 float32 值 ──
    mock_pp.out8.reset_mock()
    sched_f32 = []
    for _ in range(3):
        _test_clear_reset_schedule()
        write_parallel(0x278, 3.14, "bytes")
        time.sleep(0.002)
        sched_f32 = _test_get_reset_schedule()
        if len(sched_f32) == 1:
            break

    check(len(sched_f32) == 1, f"float32 write scheduled reset (got {len(sched_f32)})")
    if sched_f32:
        check(sched_f32[0][1] == 0x278, "float32 reset addr=0x278")
        check(sched_f32[0][2] == 4, "float32 reset byte_count=4")

    # 等复位触发 (有界轮询)
    _wait_until(lambda: len(_test_get_reset_schedule()) == 0, timeout=1.0)
    sched_f32_after = _test_get_reset_schedule()
    check(len(sched_f32_after) == 0, "float32 reset consumed")

    stop()
    time.sleep(0.1)

    # 恢复
    _test_inject_parallel(None)


# ═══════════════════════════════════════════════════════════════
# 停止时自动处理待复位
# ═══════════════════════════════════════════════════════════════

def test_stop_flushes_resets():
    print("── Stop Flushes Resets ──")

    mock_pp = MagicMock()
    mock_pp.out8 = MagicMock()
    _test_inject_parallel(mock_pp)
    _test_clear_reset_schedule()

    start()
    time.sleep(0.05)

    # 写入非零值，只等取走，不等复位 (重试容忍线程调度抖动)
    sched_before = []
    for _ in range(3):
        _test_clear_reset_schedule()
        write_parallel(0x378, 0xAA, "byte")
        time.sleep(0.002)
        sched_before = _test_get_reset_schedule()
        if len(sched_before) == 1:
            break

    # 调度中应有待复位
    check(len(sched_before) == 1,
          f"reset pending before stop (got {len(sched_before)})")

    mock_pp.out8.reset_mock()
    stop()

    # stop 退出前应已处理待复位
    sched_after = _test_get_reset_schedule()
    check(len(sched_after) == 0,
          f"reset consumed after stop (remaining: {len(sched_after)})")

    reset_calls = [c for c in mock_pp.out8.call_args_list
                   if c == call(0x378, 0)]
    check(len(reset_calls) >= 1,
          f"stop flushed reset: out8(0x378, 0) called ({len(reset_calls)} times)")

    _test_inject_parallel(None)


# ═══════════════════════════════════════════════════════════════
# I/O 线程所有权租约（editor / runtime 交权）
# ═══════════════════════════════════════════════════════════════

def test_lease_ownership():
    print("── Lease Ownership (editor / runtime) ──")
    from Application.Functions.SerialParallelDevice import io_owner

    if is_running():
        stop()
    check(io_owner() == "none", f"no lease → owner none (got {io_owner()})")

    start("editor")
    time.sleep(0.05)
    check(is_running() and io_owner() == "editor",
          f"editor lease → running, owner editor (got {io_owner()})")

    start("runtime")
    check(is_running() and io_owner() == "runtime",
          f"runtime lease → owner runtime (got {io_owner()})")

    # ★ 交权: PIE 运行期间编辑器释放租约不得停线程
    stop("editor")
    check(is_running(), "editor release keeps thread alive while runtime holds")
    check(io_owner() == "runtime", f"owner still runtime (got {io_owner()})")

    # ★ 反向: PIE 停止但编辑器仍在调试 → 线程继续
    start("editor")
    stop("runtime")
    check(is_running(), "runtime release keeps thread alive while editor holds")
    check(io_owner() == "editor", f"owner falls back to editor (got {io_owner()})")

    stop("editor")
    time.sleep(0.1)
    check(not is_running(), "last lease released → thread stopped")
    check(io_owner() == "none", "owner none after all leases released")


# ═══════════════════════════════════════════════════════════════
# 严格写入（面板/op 路径 — 禁止静默丢弃）
# ═══════════════════════════════════════════════════════════════

def test_strict_writes():
    print("── Strict Writes ──")
    from Application.Functions.SerialParallelDevice import DeviceNotReady

    mock_pp = MagicMock()
    mock_pp.out8 = MagicMock()
    _test_inject_parallel(mock_pp)

    if is_running():
        stop()
    time.sleep(0.05)

    # 未运行 → 默认模式返回 False（节点评估器路径不打断图执行）
    check(write_parallel(0x378, 1, "byte") is False,
          "write_parallel → False when not running (default)")

    raised = False
    try:
        write_parallel(0x378, 1, "byte", strict=True)
    except DeviceNotReady:
        raised = True
    check(raised, "strict parallel write raises DeviceNotReady")

    raised = False
    try:
        send("COM_TEST", 9600, b"x", strict=True)
    except DeviceNotReady:
        raised = True
    check(raised, "strict serial send raises DeviceNotReady")

    # 运行中 → 入队成功返回 True
    _test_clear_reset_schedule()
    start()
    time.sleep(0.05)
    check(write_parallel(0x378, 1, "byte", strict=True) is True,
          "strict write returns True when running")
    _wait_until(lambda: len(_test_get_reset_schedule()) >= 1, timeout=1.0)
    check(len(_test_get_reset_schedule()) >= 1, "mock driver got the strict write")
    stop()
    time.sleep(0.1)
    _test_inject_parallel(None)


# ═══════════════════════════════════════════════════════════════
# 复位延迟可配置（脉冲宽度）
# ═══════════════════════════════════════════════════════════════

def test_reset_delay_setting():
    print("── Configurable Reset Delay ──")
    from Application.Functions.SerialParallelDevice import (
        reset_delay_ms, set_reset_delay)

    mock_pp = MagicMock()
    mock_pp.out8 = MagicMock()
    _test_inject_parallel(mock_pp)
    _test_clear_reset_schedule()

    check(abs(reset_delay_ms() - 5.0) < 0.001, f"default 5 ms (got {reset_delay_ms()})")
    check(abs(set_reset_delay(25) - 0.025) < 1e-9, "set_reset_delay(25) → 0.025 s")
    check(abs(reset_delay_ms() - 25.0) < 0.001, f"reads back 25 ms (got {reset_delay_ms()})")
    check(abs(set_reset_delay(0) - 0.001) < 1e-9, "lower bound clamp → 1 ms")
    set_reset_delay(25)

    start()
    time.sleep(0.05)
    t0 = time.perf_counter()
    _test_clear_reset_schedule()
    write_parallel(0x378, 1, "byte", strict=True)
    sched = []
    for _ in range(50):
        sched = _test_get_reset_schedule()
        if sched:
            break
        time.sleep(0.002)
    check(len(sched) == 1, f"reset scheduled with configured delay (got {len(sched)})")
    if sched:
        delay_ms = (sched[0][0] - t0) * 1000.0
        check(delay_ms >= 20.0, f"reset deadline ≈ 25 ms (got {delay_ms:.1f} ms)")

    _wait_until(lambda: len(_test_get_reset_schedule()) == 0, timeout=1.0)
    check(len(_test_get_reset_schedule()) == 0, "configured reset consumed")

    set_reset_delay(5)                      # 恢复默认（后续用例依赖）
    stop()
    time.sleep(0.1)
    _test_inject_parallel(None)


# ═══════════════════════════════════════════════════════════════
# 面板载荷校验（extension.parallel_payload — 纯函数）
# ═══════════════════════════════════════════════════════════════

def test_parallel_payload():
    print("── Panel Payload Validation ──")
    from Application.Functions.SerialParallelDevice import extension as spd_ext
    payload = spd_ext.parallel_payload

    check(payload("1", "byte") == b"\x01", "byte '1' → 01")
    check(payload("1.0", "byte") == b"\x01", "byte '1.0' → 01 (numeric text)")
    check(payload("255", "byte") == b"\xff", "byte '255' → ff")
    for bad in ("0", "256", "-3", "abc", ""):
        raised = False
        try:
            payload(bad, "byte")
        except ValueError:
            raised = True
        check(raised, f"byte '{bad}' rejected")

    check(payload("1.0", "bytes") == struct.pack("<f", 1.0),
          "bytes '1.0' → float32 LE (00 00 80 3F)")
    check(payload("hi", "string") == b"hi\n", "string 'hi' → hi + LF")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("SerialParallelDevice — Unit Tests")
    print("=" * 60)

    test_protocol()
    test_thread_lifecycle()
    test_lease_ownership()
    test_strict_writes()
    test_serial_send()
    test_parallel_no_driver()
    test_parallel_mock()
    test_reset_delay_setting()
    test_stop_flushes_resets()
    test_parallel_payload()

    print()
    print("=" * 60)
    total = _PASS + _FAIL
    print(f"Results: {_PASS}/{total} passed, {_FAIL} failed")
    if _FAIL > 0:
        print("SOME TESTS FAILED")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")
