import math

import numpy as np
import pytest

from eval import stats


def test_bootstrap_ci_of_constant_is_degenerate():
    m, lo, hi = stats.bootstrap_ci([0.5] * 10, n_boot=500, seed=1)
    assert (m, lo, hi) == (0.5, 0.5, 0.5)


def test_bootstrap_ci_brackets_the_mean_and_is_seeded():
    vals = [1, 0, 1, 1, 0, 1, 0, 0, 1, 1, 1, 0]
    a = stats.bootstrap_ci(vals, n_boot=2000, seed=3)
    assert a == stats.bootstrap_ci(vals, n_boot=2000, seed=3)
    assert a[1] <= a[0] <= a[2] and a[0] == pytest.approx(np.mean(vals)) and 0 <= a[1] and a[2] <= 1
    assert a[2] - a[1] > 0.2                       # n=12 -> khoảng rộng


def test_bootstrap_ci_empty_is_nan():
    m, lo, hi = stats.bootstrap_ci([], n_boot=100, seed=0)
    assert math.isnan(m) and math.isnan(lo) and math.isnan(hi)


def test_bootstrap_ratio_micro_average():
    # hai task: 1/2 và 3/4 -> tỷ số gộp 4/6
    r, lo, hi = stats.bootstrap_ratio([1, 3], [2, 4], n_boot=500, seed=0)
    assert r == pytest.approx(4 / 6) and lo <= r <= hi


def test_paired_bootstrap_difference():
    a = [1, 1, 1, 1, 0, 1, 1, 1]
    b = [0, 0, 1, 0, 0, 1, 0, 1]
    d, lo, hi = stats.paired_bootstrap_diff(a, b, n_boot=3000, seed=2)
    assert d == pytest.approx(np.mean(a) - np.mean(b)) and lo > 0 and hi >= d
    same = stats.paired_bootstrap_diff(a, a, n_boot=200, seed=2)
    assert same == (0.0, 0.0, 0.0)


def test_paired_arrays_must_have_equal_length():
    with pytest.raises(ValueError):
        stats.paired_bootstrap_diff([1, 0], [1], n_boot=10, seed=0)


@pytest.mark.parametrize("b,c,p", [(10, 0, 2 * 0.5 ** 10), (5, 1, 2 * (1 + 6) / 64), (3, 3, 1.0), (0, 0, 1.0), (0, 7, 2 * 0.5 ** 7)])
def test_mcnemar_exact_two_sided(b, c, p):
    assert stats.mcnemar_exact(b, c) == pytest.approx(p)


def test_percentile_linear():
    assert stats.percentile([1, 2, 3, 4, 5], 50) == 3
    assert stats.percentile([10], 95) == 10
    assert math.isnan(stats.percentile([], 50))
