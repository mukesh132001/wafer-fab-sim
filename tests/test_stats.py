import numpy as np
import pytest

from fabsim import stats

scipy_stats = pytest.importorskip("scipy.stats")

rng = np.random.default_rng(0)
A = rng.normal(10, 2, 30)
B = A + rng.normal(0.5, 1, 30)
C = rng.normal(11, 2, 30)


def test_t_distribution():
    for t, df in [(2.0, 5), (-1.3, 29), (0.4, 3), (4.2, 58)]:
        assert stats.t_sf(t, df) == pytest.approx(scipy_stats.t.sf(t, df), rel=1e-7)
    assert stats.t_ppf(0.975, 29) == pytest.approx(scipy_stats.t.ppf(0.975, 29), rel=1e-6)


def test_paired_and_welch():
    p = stats.paired_t(A, B)
    ref = scipy_stats.ttest_rel(A, B)
    assert p["t"] == pytest.approx(ref.statistic, rel=1e-9)
    assert p["p"] == pytest.approx(ref.pvalue, rel=1e-6)
    w = stats.welch_t(A, C)
    ref = scipy_stats.ttest_ind(A, C, equal_var=False)
    assert w["p"] == pytest.approx(ref.pvalue, rel=1e-6)


def test_anova():
    r = stats.anova_oneway([A, B, C])
    ref = scipy_stats.f_oneway(A, B, C)
    assert r["F"] == pytest.approx(ref.statistic, rel=1e-9)
    assert r["p"] == pytest.approx(ref.pvalue, rel=1e-6)


def test_holm():
    assert stats.holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
