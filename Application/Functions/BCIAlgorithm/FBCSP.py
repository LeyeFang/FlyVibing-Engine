"""
BCIAlgorithm.FBCSP — Filter Bank CSP + 分类器（闭式 LDA / 线性 SVM）。

算法（Ang et al. 2008 口径）:
    每个频带: 带通(4 阶 Butterworth, 零相位) → CSP（协方差广义特征分解, 取头尾 m 对）
    → log 方差特征; 各带特征拼接 → 标准化 → 分类器。
    bands == [] → 退化为普通 CSP（不滤波, 全带单一 CSP）。

设计约束:
  - 纯 numpy/scipy（引擎依赖内 — sklearn 无 free-threading wheel, 不引入）;
  - 全程确定性（无随机数; SVM 用 L-BFGS-B 从零初始化）;
  - 二分类（CSP 定义域）; 训练输入 = EpochDataset 快照（epochs × channels × samples）;
  - 返回契约 (model | None, detail) — 不抛异常。

模型 dict（内存形态, 也用于 npz 落盘）:
    {"algo", "fs", "channels", "n_components", "classifier", "bands": [[lo,hi]|None...],
     "filters": [W_band (2m, ch), ...], "mu", "sd", "clf": {"kind","w","b"},
     "classes": [c0, c1], "train_epochs", "train_T", "train_accuracy"}
"""

from __future__ import annotations

import numpy as np
from scipy import linalg, optimize, signal as sps

_MAX_BANDS = 16
_MAX_COMPONENTS = 8


# ═══════════════════════════════════════════════════════════════
# 超参解析（InitFBCSP props → spec）
# ═══════════════════════════════════════════════════════════════

def parse_fbcsp_spec(props: dict) -> tuple[dict, str]:
    """props → spec（钳位 + 说明）。bands 打包 list: [[lo,hi], ...]; 空 = 普通 CSP。"""
    notes: list[str] = []
    try:
        m = int(float(props.get("n_components", 2)))
    except (TypeError, ValueError):
        m = 2
    m = max(1, min(_MAX_COMPONENTS, m))

    clf = str(props.get("classifier", "LDA")).strip().upper()
    if clf not in ("LDA", "SVM"):
        notes.append(f"classifier '{clf}' → LDA")
        clf = "LDA"

    raw_bands = props.get("bands", None)
    bands: list[list[float]] = []
    if isinstance(raw_bands, (list, tuple)):
        for item in raw_bands:
            try:
                lo, hi = float(item[0]), float(item[1])
            except (TypeError, ValueError, IndexError):
                notes.append(f"band {item!r} 非法 → 丢弃")
                continue
            if not (0.1 <= lo < hi <= 500.0):
                notes.append(f"band [{lo:g},{hi:g}] 边界非法 → 丢弃")
                continue
            bands.append([lo, hi])
            if len(bands) >= _MAX_BANDS:
                notes.append(f"band 数封顶 {_MAX_BANDS}")
                break
    elif raw_bands is not None:
        notes.append("bands 非 list → 视为空（普通 CSP）")

    spec = {"n_components": m, "classifier": clf, "bands": bands}
    if not bands:
        notes.append("bands 为空 → 退化普通 CSP（不滤波）")
    return spec, "; ".join(notes)


# ═══════════════════════════════════════════════════════════════
# 内部算子
# ═══════════════════════════════════════════════════════════════

def _bandpass(x: np.ndarray, fs: float, lo: float, hi: float) -> np.ndarray:
    """零相位带通（4 阶 Butterworth SOS）; 边界不合法时原样返回。"""
    nyq = fs / 2.0
    lo = max(0.1, float(lo))
    hi = min(float(hi), nyq * 0.99)
    if not (0.0 < lo < hi < nyq):
        return x
    sos = sps.butter(4, [lo / nyq, hi / nyq], btype="bandpass", output="sos")
    return sps.sosfiltfilt(sos, x, axis=-1)


def _mean_cov(epochs: list[np.ndarray]) -> np.ndarray:
    """类别平均归一化协方差。"""
    acc = None
    for x in epochs:
        c = x @ x.T
        tr = float(np.trace(c)) + 1e-12
        c = c / tr
        acc = c if acc is None else acc + c
    n = max(1, len(epochs))
    return (acc if acc is not None else np.zeros((1, 1))) / n


def _csp_filters(epochs: list[np.ndarray], labels01: np.ndarray,
                 m: int) -> np.ndarray:
    """CSP 空间滤波器 (2m, ch): 广义特征分解取头尾 m 对。"""
    c1 = _mean_cov([x for x, l in zip(epochs, labels01) if l == 1])
    c0 = _mean_cov([x for x, l in zip(epochs, labels01) if l == 0])
    ch = c1.shape[0]
    reg = 1e-6 * (np.trace(c1 + c0) + 1e-12)
    combined = c1 + c0 + reg * np.eye(ch)
    vals, vecs = linalg.eigh(c1, combined)          # 升序
    order = np.argsort(vals)[::-1]
    m = max(1, min(m, ch // 2 if ch >= 2 else 1))
    top = vecs[:, order[:m]]
    bot = vecs[:, order[-m:]]
    w = np.concatenate([top, bot], axis=1).T        # (2m, ch)
    w = w / (np.linalg.norm(w, axis=1, keepdims=True) + 1e-12)
    return w


def _logvar_features(epochs: list[np.ndarray], w: np.ndarray) -> np.ndarray:
    feats = []
    for x in epochs:
        z = w @ x
        feats.append(np.log(np.var(z, axis=1) + 1e-12))
    return np.asarray(feats)


def _fit_lda(f: np.ndarray, labels01: np.ndarray) -> dict:
    """闭式二类 LDA: w = Σ⁻¹(μ1−μ0), b = −w·(μ1+μ0)/2（Σ 加正则）。"""
    mu1 = f[labels01 == 1].mean(axis=0)
    mu0 = f[labels01 == 0].mean(axis=0)
    f1 = f[labels01 == 1] - mu1
    f0 = f[labels01 == 0] - mu0
    n = len(f)
    cov = (f1.T @ f1 + f0.T @ f0) / max(1, n - 2)
    cov = cov + 1e-6 * np.eye(cov.shape[0])
    w = np.linalg.solve(cov, mu1 - mu0)
    b = -0.5 * float(w @ (mu1 + mu0))
    return {"kind": "LDA", "w": w, "b": b}


def _fit_svm(f: np.ndarray, labels01: np.ndarray) -> dict:
    """线性 SVM（平方 hinge + L2, L-BFGS-B 由零初始化 — 确定性）。"""
    t = np.where(labels01 == 1, 1.0, -1.0)

    def obj(p: np.ndarray) -> float:
        w = p[:-1]
        b = p[-1]
        margin = 1.0 - t * (f @ w + b)
        hinge = np.maximum(0.0, margin)
        return 0.5 * float(w @ w) + float(hinge @ hinge)

    res = optimize.minimize(obj, np.zeros(f.shape[1] + 1), method="L-BFGS-B",
                            options={"maxiter": 500, "ftol": 1e-10})
    return {"kind": "SVM", "w": np.asarray(res.x[:-1]), "b": float(res.x[-1])}


# ═══════════════════════════════════════════════════════════════
# 训练 / 预测
# ═══════════════════════════════════════════════════════════════

def train_fbcsp(spec: dict, x_list, y_list, fs, progress_cb=None
                ) -> tuple[dict | None, str]:
    """FBCSP 训练。X: list[(ch, T_i)]; y: 数值标签（恰 2 类）。"""
    if not x_list:
        return None, "empty dataset — capture epochs first"
    try:
        fs = float(fs)
    except (TypeError, ValueError):
        return None, "dataset fs unknown — appends must carry Fs"
    if fs <= 0:
        return None, f"invalid fs ({fs})"

    classes = sorted({float(v) for v in y_list})
    if len(classes) != 2:
        return None, (f"FBCSP needs exactly 2 classes (got {len(classes)}: "
                      f"{classes}) — use EpochClear + balanced capture")
    labels01 = np.asarray([1 if float(v) == classes[1] else 0 for v in y_list])

    t_min = min(int(np.asarray(x).shape[1]) for x in x_list)
    if t_min < 8:
        return None, f"epochs too short (min T={t_min})"
    ch = int(np.asarray(x_list[0]).shape[0])
    xs = [np.asarray(x, dtype=np.float64)[:, :t_min] for x in x_list]

    spec = dict(spec or {})
    spec.setdefault("n_components", 2)
    spec.setdefault("classifier", "LDA")
    spec.setdefault("bands", [])
    band_defs = list(spec["bands"]) if spec["bands"] else [None]
    n_b = len(band_defs)

    filters: list[np.ndarray] = []
    feats: list[np.ndarray] = []
    for i, band in enumerate(band_defs):
        if band:
            xb = [_bandpass(x, fs, band[0], band[1]) for x in xs]
        else:
            xb = xs
        w = _csp_filters(xb, labels01, int(spec["n_components"]))
        filters.append(w)
        feats.append(_logvar_features(xb, w))
        if progress_cb:
            progress_cb(0.15 + 0.55 * (i + 1) / n_b)

    f_mat = np.hstack(feats)
    mu = f_mat.mean(axis=0)
    sd = f_mat.std(axis=0)
    sd[sd < 1e-9] = 1e-9
    fz = (f_mat - mu) / sd

    if str(spec["classifier"]).upper() == "SVM":
        clf = _fit_svm(fz, labels01)
    else:
        clf = _fit_lda(fz, labels01)
    if progress_cb:
        progress_cb(0.95)

    decision = fz @ clf["w"] + clf["b"]
    pred = decision >= 0.0
    acc = float(np.mean(pred == (labels01 == 1)))

    model = {
        "algo": "FBCSP",
        "fs": int(round(fs)),
        "channels": ch,
        "n_components": int(spec["n_components"]),
        "classifier": "SVM" if clf["kind"] == "SVM" else "LDA",
        "bands": [[float(b[0]), float(b[1])] if b else [0.0, 0.0]
                  for b in band_defs],
        "filters": filters,
        "mu": mu, "sd": sd, "clf": clf,
        "classes": [float(classes[0]), float(classes[1])],
        "train_epochs": len(xs), "train_T": int(t_min),
        "train_accuracy": acc,
    }
    detail = (f"FBCSP[{model['classifier']}] trained: {len(xs)} epochs × {ch}ch"
              f"×{t_min} @ {int(fs)}Hz, bands={spec['bands'] or 'CSP(全带)'}, "
              f"n_components={model['n_components']}, feat_dim={f_mat.shape[1]}, "
              f"train_acc={acc:.2f}")
    return model, detail


def predict_fbcsp(model: dict, data) -> tuple[object | None, float, str]:
    """单段推理。Returns: (label | None, confidence, detail)。"""
    if not model:
        return None, 0.0, "no model"
    x = np.asarray(data, dtype=np.float64)
    if x.ndim == 1:
        x = x.reshape(1, -1)
    if x.ndim != 2 or x.shape[1] < 8:
        return None, 0.0, f"window too short (shape {x.shape})"
    if x.shape[0] != model["channels"]:
        return None, 0.0, (f"channel mismatch: model has {model['channels']}ch, "
                           f"got {x.shape[0]}ch")

    parts = []
    for w, band in zip(model["filters"], model["bands"]):
        if band and float(band[1]) > 0:
            xb = _bandpass(x, float(model["fs"]), band[0], band[1])
        else:
            xb = x
        z = w @ xb
        parts.append(np.log(np.var(z, axis=1) + 1e-12))
    f_vec = np.concatenate(parts)
    fz = (f_vec - model["mu"]) / model["sd"]
    d = float(fz @ model["clf"]["w"] + model["clf"]["b"])
    label = model["classes"][1] if d >= 0 else model["classes"][0]
    conf = 1.0 / (1.0 + np.exp(-abs(d)))
    return label, float(conf), ""


# ═══════════════════════════════════════════════════════════════
# 模型落盘 / 回读（npz; 离线训练流水线的对接面）
# ═══════════════════════════════════════════════════════════════

def save_fbcsp_model(model: dict, file_path: str) -> tuple[bool, str]:
    file_path = (file_path or "").strip()
    if not file_path:
        return False, "model_path is empty"
    try:
        bands = np.asarray(model["bands"], dtype=np.float64).reshape(-1, 2)
        w_stack = (np.stack(model["filters"]) if model["filters"]
                   else np.zeros((0, 0, 0), dtype=np.float64))
        np.savez_compressed(
            file_path,
            algo=np.array("FBCSP"),
            fs=np.int64(model["fs"]),
            channels=np.int64(model["channels"]),
            n_components=np.int64(model["n_components"]),
            classifier=np.array(model["classifier"]),
            bands=bands,
            W=w_stack,
            mu=np.asarray(model["mu"]),
            sd=np.asarray(model["sd"]),
            clf_kind=np.array(model["clf"]["kind"]),
            clf_w=np.asarray(model["clf"]["w"]),
            clf_b=np.float64(model["clf"]["b"]),
            classes=np.asarray(model["classes"], dtype=np.float64),
            train_epochs=np.int64(model.get("train_epochs", 0)),
            train_T=np.int64(model.get("train_T", 0)),
            train_accuracy=np.float64(model.get("train_accuracy", 0.0)),
        )
    except OSError as e:
        return False, f"save model failed: {e}"
    return True, f"FBCSP model saved → {file_path}"


def load_fbcsp_model(file_path: str) -> tuple[dict | None, str]:
    file_path = (file_path or "").strip()
    if not file_path:
        return None, "model_path is empty"
    try:
        with np.load(file_path) as z:
            if str(z["algo"]) != "FBCSP":
                return None, f"not an FBCSP model (algo={z['algo']})"
            bands = np.asarray(z["bands"], dtype=np.float64)
            w_stack = np.asarray(z["W"], dtype=np.float64)
            if len(bands) != len(w_stack):
                return None, "corrupt model file (bands/W count mismatch)"
            model = {
                "algo": "FBCSP",
                "fs": int(z["fs"]),
                "channels": int(z["channels"]),
                "n_components": int(z["n_components"]),
                "classifier": str(z["classifier"]),
                "bands": [[float(b[0]), float(b[1])] for b in bands],
                "filters": [w_stack[i] for i in range(len(bands))],
                "mu": np.asarray(z["mu"]),
                "sd": np.asarray(z["sd"]),
                "clf": {"kind": str(z["clf_kind"]), "w": np.asarray(z["clf_w"]),
                        "b": float(z["clf_b"])},
                "classes": [float(c) for c in np.asarray(z["classes"])],
                "train_epochs": int(z["train_epochs"]),
                "train_T": int(z["train_T"]),
                "train_accuracy": float(z["train_accuracy"]),
            }
    except Exception as e:  # noqa: BLE001 — 文件格式错误统一报 detail
        return None, f"load model failed: {type(e).__name__}: {e}"
    return model, f"FBCSP model loaded from {file_path}"
