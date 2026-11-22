import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import partitions  # noqa: E402

metrics = pytest.importorskip("sklearn.metrics")


def test_relabel_is_order_of_first_appearance():
    assert partitions.relabel([7, 3, 7, 9, 3]).tolist() == [0, 1, 0, 2, 1]


def test_contingency_counts_pairs():
    t = partitions.contingency(["a", "a", "b", "b"], [1, 2, 2, 2])
    assert t.tolist() == [[1, 1], [0, 2]]


def test_nmi_and_ari_match_scikit_learn():
    rng = np.random.default_rng(42)
    for _ in range(20):
        a = rng.integers(0, 6, 300)
        b = np.where(rng.random(300) < 0.6, a, rng.integers(0, 9, 300))
        assert partitions.nmi(a, b) == pytest.approx(metrics.normalized_mutual_info_score(a, b), abs=1e-12)
        assert partitions.ari(a, b) == pytest.approx(metrics.adjusted_rand_score(a, b), abs=1e-12)


def test_identical_and_single_block_partitions():
    a = [0, 0, 1, 1, 2]
    assert partitions.nmi(a, [5, 5, 3, 3, 9]) == pytest.approx(1.0)
    assert partitions.ari(a, [5, 5, 3, 3, 9]) == pytest.approx(1.0)
    assert partitions.nmi([0] * 5, [1] * 5) == 1.0
