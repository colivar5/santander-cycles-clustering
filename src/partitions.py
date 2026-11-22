"""Compare two partitions of the same items: contingency table, NMI, adjusted Rand index.

Needs only numpy, so it runs both in env_311 and on the Python that runs
graph-tool (``src/sbm.py``). NMI uses the arithmetic mean of the two
entropies, as scikit-learn's ``normalized_mutual_info_score`` does by default;
the ARI is Hubert & Arabie's (1985).
"""
from __future__ import annotations

import numpy as np


def relabel(labels) -> np.ndarray:
    """Labels renumbered 0, 1, 2, ... in order of first appearance."""
    _, first, inverse = np.unique(np.asarray(labels), return_index=True, return_inverse=True)
    order = np.argsort(np.argsort(first))
    return order[inverse.ravel()]


def contingency(a, b) -> np.ndarray:
    a, b = relabel(a), relabel(b)
    if len(a) != len(b):
        raise ValueError("partitions differ in length")
    table = np.zeros((a.max() + 1, b.max() + 1), dtype=np.int64)
    np.add.at(table, (a, b), 1)
    return table


def _entropy(counts: np.ndarray) -> float:
    p = counts[counts > 0] / counts.sum()
    return float(-(p * np.log(p)).sum())


def nmi(a, b) -> float:
    t = contingency(a, b)
    n = t.sum()
    ha, hb = _entropy(t.sum(axis=1)), _entropy(t.sum(axis=0))
    if ha == 0 and hb == 0:
        return 1.0
    nz = t > 0
    outer = np.outer(t.sum(axis=1), t.sum(axis=0))
    mi = float((t[nz] / n * np.log(t[nz] * n / outer[nz])).sum())
    return max(0.0, mi / ((ha + hb) / 2))


def ari(a, b) -> float:
    t = contingency(a, b)
    n = int(t.sum())

    def pairs(x):
        x = np.asarray(x, dtype=np.float64)
        return float((x * (x - 1) / 2).sum())

    index = pairs(t)
    rows, cols = pairs(t.sum(axis=1)), pairs(t.sum(axis=0))
    total = n * (n - 1) / 2
    expected = rows * cols / total if total else 0.0
    top = (rows + cols) / 2
    if top == expected:
        return 1.0
    return (index - expected) / (top - expected)
