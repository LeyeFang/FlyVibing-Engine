"""
BCIAlgorithm.CCA — 典型相关分析（SSVEP 免训练判别）。

原理（标准 CCA, Lin et al. 2006）:
    参考信号 Y_f = [sin(2πfk t), cos(2πfk t)] (k = 1..h 谐波);
    计算 X（多通道窗口）与 Y_f 的最大典型相关 ρ(f) = argmax corr(wx·X, wy·Y);
    判别: label = argmax_f ρ(f)（频率索引）, 附 Score(ρ) 与 Freq。

设计:
  - 免训练（正弦参考解析构造 → 无校准）;
  - 纯 numpy/scipy, 全程确定性;
  - 返回契约 (label | None, score, freq, detail) — 不抛异常。
"""

from __future__ import annotations

import numpy as np
from scipy import linalg


def _cca_corr(X: np.ndarray, Y: np.ndarray) -> float:
    """X (ch, T) 与 Y (r, T) 的最大典型相关（白化 + SVD, 数值稳定）。"""
    n = X.shape[1]
    Xc = X - X.mean(axis=1, keepdims=True)
    Yc = Y - Y.mean(axis=1, keepdims=True)
    Sxx = Xc @ Xc.T / n + 1e-8 * np.eye(X.shape[0])
    Syy = Yc @ Yc.T / n + 1e-8 * np.eye(Y.shape[0])
    Sxy = Xc @ Yc.T / n

    wx, Vx = linalg.eigh(Sxx)
    Wx = Vx @ np.diag(1.0 / np.sqrt(np.maximum(wx, 1e-12))) @ Vx.T
    wy, Vy = linalg.eigh(Syy)
    Wy = Vy @ np.diag(1.0 / np.sqrt(np.maximum(wy, 1e-12))) @ Vy.T

    M = Wx @ Sxy @ Wy
    sv = np.linalg.svd(M, compute_uv=False)
    return float(np.clip(sv[0], 0.0, 1.0)) if len(sv) else 0.0


def predict_cca(data, fs: float, freqs, harmonics: int = 3
                ) -> tuple[int | None, float, float, str]:
    """CCA 判别。Returns: (label_idx | None, score, freq, detail)。

    data: (channels, samples) 单段窗口（1-D 视为单通道）。
    freqs: 参考频率列表（≥2）。harmonics: 谐波数 1..8。
    """
    x = np.asarray(data, dtype=np.float64)
    if x.ndim == 1:
        x = x.reshape(1, -1)
    if x.ndim != 2 or x.shape[1] < 16:
        return None, 0.0, 0.0, f"window too short (shape {x.shape})"
    try:
        fs = float(fs)
    except (TypeError, ValueError):
        return None, 0.0, 0.0, "fs must be numeric"
    if fs <= 0:
        return None, 0.0, 0.0, "fs must be > 0"

    try:
        freqs = [float(f) for f in (freqs or []) if float(f) > 0]
    except (TypeError, ValueError):
        return None, 0.0, 0.0, "freqs must be numeric"
    if len(freqs) < 2:
        return None, 0.0, 0.0, f"CCA needs at least 2 reference frequencies (got {len(freqs)})"
    nyq = fs / 2.0
    valid = [f for f in freqs if f < nyq]
    if len(valid) < 2:
        return None, 0.0, 0.0, f"reference frequencies must be < Nyquist ({nyq:.1f}Hz)"

    h = max(1, min(8, int(harmonics or 3)))
    t = np.arange(x.shape[1], dtype=np.float64) / fs
    xc = x - x.mean(axis=1, keepdims=True)

    best_rho, best_i = -1.0, 0
    for i, f in enumerate(valid):
        refs = []
        for k in range(1, h + 1):
            refs.append(np.sin(2.0 * np.pi * f * k * t))
            refs.append(np.cos(2.0 * np.pi * f * k * t))
        rho = _cca_corr(xc, np.asarray(refs))
        if rho > best_rho:
            best_rho, best_i = rho, i

    return best_i, float(best_rho), float(valid[best_i]), ""
