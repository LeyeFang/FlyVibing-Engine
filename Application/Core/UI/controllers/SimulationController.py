"""模拟状态机 — 统一管理 Run / Pause / Stop 状态"""
from enum import Enum, auto


class SimulationState(Enum):
    STOPPED = auto()
    RUNNING = auto()
    PAUSED = auto()


class SimulationController:
    """单例风格的模拟状态控制器 — 纯数据层，不 import imgui"""

    _state: SimulationState = SimulationState.STOPPED

    # ── 状态查询 ────────────────────────────────────────────

    @classmethod
    def is_running(cls) -> bool:
        return cls._state == SimulationState.RUNNING

    @classmethod
    def is_paused(cls) -> bool:
        return cls._state == SimulationState.PAUSED

    @classmethod
    def is_stopped(cls) -> bool:
        return cls._state == SimulationState.STOPPED

    @classmethod
    def get_state(cls) -> SimulationState:
        return cls._state

    @classmethod
    def get_state_label(cls) -> str:
        return {
            SimulationState.STOPPED: "Not running",
            SimulationState.RUNNING: "Running",
            SimulationState.PAUSED: "Paused",
        }[cls._state]

    # ── 状态变更 ────────────────────────────────────────────

    @classmethod
    def play(cls) -> None:
        """▶ 启动模拟"""
        cls._state = SimulationState.RUNNING

    @classmethod
    def pause(cls) -> None:
        """⏸ 暂停模拟（仅在运行时有效）"""
        if cls._state == SimulationState.RUNNING:
            cls._state = SimulationState.PAUSED

    @classmethod
    def resume(cls) -> None:
        """▶ 恢复运行（仅在暂停时有效）"""
        if cls._state == SimulationState.PAUSED:
            cls._state = SimulationState.RUNNING

    @classmethod
    def stop(cls) -> None:
        """■ 停止模拟"""
        cls._state = SimulationState.STOPPED
