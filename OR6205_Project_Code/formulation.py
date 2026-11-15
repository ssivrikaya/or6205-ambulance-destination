"""
formulation.py - builds the index sets and parameters of the MILP (MODEL_FORMULASYONU.md).

Both solver backends (model_gurobi.py, model_highs.py) read the same ModelData object,
so the two implementations solve exactly the same mathematical model.

Notation (matches the formulation document):
  a in A        admissible arc (patient i(a), hospital j(a)) from protocol.py
  t in T        15-min periods          h in H   hours          k in K   cost segments
  c1[a]         w_i * T_ij  (+ w_i * pi if a breaks an available continuity-of-care option)
  mu[j,t]       offload capacity of hospital j in period t (patients per period)
  walk[j,h]     expected walk-in arrivals of hospital j in hour h
  seg_ub[j,k]   width of crowding-cost segment k at hospital j (patients/hour); last is +inf
  slope[k]      crowding cost per patient in segment k (increasing -> convex)
  lamD          lambda * Delta: cost of one patient waiting one period on the wall
"""
from dataclasses import dataclass, field
import numpy as np
import pandas as pd

import config as C
from evaluate import offload_rate

_PROF = np.array(C.HOURLY_PROFILE)
GENERAL = ("general_low", "general_high", "behavioral")


@dataclass
class ModelData:
    arcs: pd.DataFrame
    J: list
    T: list
    H: list
    K: list
    mu: dict
    walk: dict
    seg_ub: dict
    slope: list
    c1: np.ndarray
    lamD: float
    arcs_of_patient: dict
    arcs_jt: dict
    arcs_jh: dict
    fixed_arcs: list
    equity_coef: dict = field(default_factory=dict)   # arc -> coefficient in (mean_B - mean_A)


def prepare(arcs: pd.DataFrame, hospitals: pd.DataFrame, fixed: dict | None = None) -> ModelData:
    M = C.MODEL
    Pm = C.SIM["period_min"]
    a = arcs.reset_index(drop=True).copy()
    a["hour"] = (a["arrival_min"] // 60).astype(int)

    J = list(range(len(hospitals)))
    T = list(range(int(a.period.min()), int(a.period.max()) + M["drain_periods"] + 1))
    H = list(range(0, max(26, int(a.hour.max()) + 1)))
    K = list(range(len(C.CROWDING_SLOPES)))

    rate = {(j, hr): offload_rate(hospitals.loc[j], hr) for j in J for hr in range(24)}
    mu = {(j, t): rate[j, ((t * Pm) // 60) % 24] * Pm / 60.0 for j in J for t in T}
    walk = {(j, h): hospitals.walkin_per_hour[j] * _PROF[h % 24] / _PROF.mean() for j in J for h in H}
    bp = C.CROWDING_BREAKPOINTS
    seg_ub = {}
    for j in J:
        cap = float(hospitals.ed_capacity_per_hour[j])
        for k in K:
            seg_ub[j, k] = (bp[k + 1] - bp[k]) * cap if k + 1 < len(bp) else np.inf

    # f1 coefficients: weighted time to definitive care + continuity-of-care penalty
    w = a["weight"].to_numpy(float)
    c1 = w * a["T_no_wait"].to_numpy(float)
    breaks_cont = (a["has_continuity_option"] == 1) & (a["is_continuity"] == 0)
    c1 = c1 + np.where(breaks_cont, w * M["continuity_value"], 0.0)

    lam = M["wall_weight"] if M["wall_weight"] is not None else float(a.drop_duplicates("pid").weight.mean())
    lamD = lam * Pm

    arcs_of_patient = a.groupby("pid").indices
    arcs_jt = {k: list(v) for k, v in a.groupby(["hosp", "period"]).indices.items()}
    arcs_jh = {k: list(v) for k, v in a.groupby(["hosp", "hour"]).indices.items()}
    fixed_arcs = []
    if fixed:
        key = dict(zip(zip(a.pid, a.hosp), a.index))
        fixed_arcs = [key[(p, j)] for p, j in fixed.items() if (p, j) in key]

    equity_coef = {}
    g = a[a.cls.isin(GENERAL)]
    nA, nB = g[g.group == "A"].pid.nunique(), g[g.group == "B"].pid.nunique()
    if nA and nB:
        coef = np.where(g.group == "B", g.T_no_wait / nB, -g.T_no_wait / nA)
        equity_coef = dict(zip(g.index.tolist(), coef.tolist()))

    return ModelData(a, J, T, H, K, mu, walk, seg_ub, list(C.CROWDING_SLOPES), c1, lamD,
                     {int(k): list(v) for k, v in arcs_of_patient.items()}, arcs_jt, arcs_jh,
                     fixed_arcs, equity_coef)


# ---------- independent re-computation of the objectives (used for verification) ----------
def true_objectives(data: ModelData, chosen_arcs) -> tuple[float, float]:
    """Compute f1 and f2 for a given set of chosen arcs WITHOUT any solver:
    Lindley recursion for the fluid backlog, closed-form convex cost for crowding."""
    chosen = list(chosen_arcs)
    f1 = float(data.c1[chosen].sum())
    hosp = data.arcs.hosp.to_numpy(); per = data.arcs.period.to_numpy(); hr = data.arcs.hour.to_numpy()
    arr, load = {}, {}
    for q in chosen:
        arr[hosp[q], per[q]] = arr.get((hosp[q], per[q]), 0) + 1
        load[hosp[q], hr[q]] = load.get((hosp[q], hr[q]), 0) + 1
    for j in data.J:
        b = 0.0
        for t in data.T:
            b = max(0.0, b + arr.get((j, t), 0) - data.mu[j, t])
            f1 += data.lamD * b
    f2 = 0.0
    for j in data.J:
        for h in data.H:
            L = data.walk[j, h] + load.get((j, h), 0)
            lo = 0.0
            for k in data.K:
                width = data.seg_ub[j, k]
                f2 += data.slope[k] * max(0.0, min(L - lo, width))
                lo += width
                if lo >= L:
                    break
    return f1, f2
