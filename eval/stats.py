"""Thống kê cho report: bootstrap theo task, hiệu cặp, McNemar chính xác (không cần scipy)."""
from __future__ import annotations

import math

import numpy as np


def bootstrap_ci(values, n_boot: int = 10000, seed: int = 0, alpha: float = 0.05):
    """(trung bình, cận dưới, cận trên) bootstrap 95% theo đơn vị task."""
    v = np.asarray(values, dtype=float)
    if v.size == 0:
        return (math.nan, math.nan, math.nan)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, v.size, size=(n_boot, v.size))
    means = v[idx].mean(axis=1)
    return (float(v.mean()), float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2)))


def bootstrap_ratio(num, den, n_boot: int = 10000, seed: int = 0, alpha: float = 0.05):
    """Tỷ số gộp sum(num)/sum(den) với bootstrap theo task (dùng cho Hallucination Rate, Citation Precision)."""
    n, d = np.asarray(num, dtype=float), np.asarray(den, dtype=float)
    if n.size == 0 or d.sum() == 0:
        return (math.nan, math.nan, math.nan)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n.size, size=(n_boot, n.size))
    dens = d[idx].sum(axis=1)
    ratios = np.where(dens > 0, n[idx].sum(axis=1) / np.where(dens > 0, dens, 1), np.nan)
    ratios = ratios[~np.isnan(ratios)]
    return (float(n.sum() / d.sum()), float(np.quantile(ratios, alpha / 2)), float(np.quantile(ratios, 1 - alpha / 2)))


def paired_bootstrap_diff(a, b, n_boot: int = 10000, seed: int = 0, alpha: float = 0.05):
    """Hiệu trung bình a - b trên cùng tập task (cặp), với CI bootstrap."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if a.shape != b.shape:
        raise ValueError("paired arrays must have equal length")
    return bootstrap_ci(a - b, n_boot=n_boot, seed=seed, alpha=alpha)


def mcnemar_exact(b: int, c: int) -> float:
    """McNemar chính xác hai phía: b = a đúng/b sai, c = a sai/b đúng (cặp bất đồng)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def percentile(values, q: float) -> float:
    v = np.asarray(values, dtype=float)
    return float(np.percentile(v, q)) if v.size else math.nan
