"""Analytic queueing formulas used to validate the simulator."""
from __future__ import annotations

import math


def erlang_c(lam: float, mu: float, c: int) -> dict:
    """M/M/c queue. lam = arrival rate, mu = service rate per server, c = servers.

    Returns utilization, P(wait), mean queue time Wq, mean queue length Lq.
    """
    a = lam / mu                       # offered load
    rho = a / c
    if rho >= 1:
        raise ValueError(f"Unstable queue: rho = {rho:.3f} >= 1")
    s = sum(a ** k / math.factorial(k) for k in range(c))
    top = a ** c / (math.factorial(c) * (1 - rho))
    p_wait = top / (s + top)
    wq = p_wait / (c * mu - lam)
    return {"rho": rho, "p_wait": p_wait, "Wq": wq, "Lq": lam * wq, "W": wq + 1 / mu}


def kingman_gg1_wq(u: float, ca2: float, ce2: float, te: float) -> float:
    """Kingman's VUT approximation for a G/G/1 queue: Wq = V * U * T."""
    return ((ca2 + ce2) / 2) * (u / (1 - u)) * te
