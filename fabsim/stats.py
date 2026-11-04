"""Small, dependency-free statistics for comparing simulation scenarios.

Implemented with numpy + math only (no SciPy), so it installs anywhere.
Validated against SciPy in tests/test_stats.py when SciPy is available.

  mean_ci            mean and t-based confidence interval
  paired_t           paired t-test (use with common random numbers)
  welch_t            two-sample t-test, unequal variances
  anova_oneway       one-way ANOVA across scenarios
  anova_rcbd         randomized complete block ANOVA (scenario x seed blocks)
  holm               Holm-Bonferroni adjustment for multiple comparisons
"""
from __future__ import annotations

import math

import numpy as np


# ---- special functions ----------------------------------------------------
def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Numerical Recipes)."""
    tiny, qab, qap, qam = 1e-300, a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 400):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_sf(t: float, df: float) -> float:
    """P(T > t) for Student's t."""
    x = df / (df + t * t)
    p = 0.5 * betainc(df / 2, 0.5, x)
    return p if t >= 0 else 1.0 - p


def t_two_sided_p(t: float, df: float) -> float:
    return min(1.0, 2.0 * t_sf(abs(t), df))


def t_ppf(q: float, df: float) -> float:
    """Inverse CDF of Student's t (bisection; plenty fast for CIs)."""
    lo, hi = -1e3, 1e3
    for _ in range(200):
        mid = (lo + hi) / 2
        if 1.0 - t_sf(mid, df) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def f_sf(f: float, d1: float, d2: float) -> float:
    """P(F > f) for the F distribution."""
    if f <= 0:
        return 1.0
    return betainc(d2 / 2, d1 / 2, d2 / (d2 + d1 * f))


# ---- tests ------------------------------------------------------------------
def mean_ci(x, conf: float = 0.95) -> tuple[float, float, float]:
    """Return (mean, half_width, std)."""
    x = np.asarray(x, float)
    n = len(x)
    m, s = float(x.mean()), float(x.std(ddof=1)) if n > 1 else 0.0
    hw = t_ppf(1 - (1 - conf) / 2, n - 1) * s / math.sqrt(n) if n > 1 else float("nan")
    return m, hw, s


def paired_t(a, b) -> dict:
    """Paired t-test of a vs b (same seeds). Returns mean diff (a - b), CI, t, p."""
    d = np.asarray(a, float) - np.asarray(b, float)
    n = len(d)
    m, hw, s = mean_ci(d)
    t = m / (s / math.sqrt(n)) if s > 0 else math.copysign(math.inf, m) if m else 0.0
    return {"mean_diff": m, "ci_half_width": hw, "t": t, "df": n - 1,
            "p": t_two_sided_p(t, n - 1) if math.isfinite(t) else 0.0}


def welch_t(a, b) -> dict:
    a, b = np.asarray(a, float), np.asarray(b, float)
    va, vb, na, nb = a.var(ddof=1), b.var(ddof=1), len(a), len(b)
    se = math.sqrt(va / na + vb / nb)
    t = (a.mean() - b.mean()) / se
    df = (va / na + vb / nb) ** 2 / ((va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1))
    return {"mean_diff": float(a.mean() - b.mean()), "t": float(t), "df": float(df),
            "p": t_two_sided_p(float(t), float(df))}


def anova_oneway(groups: list) -> dict:
    groups = [np.asarray(g, float) for g in groups]
    k, n = len(groups), sum(len(g) for g in groups)
    grand = np.concatenate(groups).mean()
    ssb = sum(len(g) * (g.mean() - grand) ** 2 for g in groups)
    ssw = sum(((g - g.mean()) ** 2).sum() for g in groups)
    d1, d2 = k - 1, n - k
    f = (ssb / d1) / (ssw / d2)
    return {"F": float(f), "df_between": d1, "df_within": d2, "p": f_sf(f, d1, d2),
            "eta_squared": float(ssb / (ssb + ssw))}


def anova_rcbd(matrix) -> dict:
    """Randomized complete block design: rows = seeds (blocks), cols = scenarios.

    With common random numbers each seed is a block, so seed-to-seed noise is
    removed from the error term -> a more powerful test than one-way ANOVA.
    """
    y = np.asarray(matrix, float)
    b, k = y.shape
    grand = y.mean()
    ss_treat = b * ((y.mean(axis=0) - grand) ** 2).sum()
    ss_block = k * ((y.mean(axis=1) - grand) ** 2).sum()
    ss_total = ((y - grand) ** 2).sum()
    ss_err = ss_total - ss_treat - ss_block
    d1, d2 = k - 1, (k - 1) * (b - 1)
    f = (ss_treat / d1) / (ss_err / d2)
    return {"F": float(f), "df_treatment": d1, "df_error": d2, "p": f_sf(f, d1, d2)}


def holm(pvalues: list[float]) -> list[float]:
    """Holm-Bonferroni adjusted p-values (same order as input)."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    adj, running = [0.0] * m, 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvalues[i]))
        adj[i] = running
    return adj
