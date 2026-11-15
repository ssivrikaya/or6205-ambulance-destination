"""
evaluate.py - scores ANY assignment (P0 baseline, rolling horizon, full information) the same way.

Using one evaluator for every policy keeps comparisons fair: the optimization model may use a
linear approximation of offload delay, but every solution is re-scored here with the same
deterministic FIFO offload queue and the same crowding-cost function.

It also checks feasibility: every assignment must use an admissible arc from protocol.py.
"""
import numpy as np
import pandas as pd

import config as C

_PROF = np.array(C.HOURLY_PROFILE)


def offload_rate(hosp_row, hour: int) -> float:
    """Patients/hour the ED can take off ambulance stretchers. PLACEHOLDER: capacity dips
    when walk-in volume peaks (replace with hospital-specific staffing/boarding data)."""
    f = 1.15 - 0.30 * (_PROF[hour % 24] - _PROF.min()) / (_PROF.max() - _PROF.min())
    return hosp_row.offload_per_hour * f


def crowding_cost(load: float, cap: float) -> float:
    """Convex piecewise-linear cost of hourly ED load (hospital objective f2)."""
    b = [x * cap for x in C.CROWDING_BREAKPOINTS] + [np.inf]
    s = C.CROWDING_SLOPES
    return float(sum(s[k] * max(0.0, min(load, b[k + 1]) - b[k]) for k in range(len(s))))


def check_feasible(assign: dict, arcs: pd.DataFrame) -> None:
    ok = set(zip(arcs.pid, arcs.hosp))
    bad = [(p, j) for p, j in assign.items() if (p, j) not in ok]
    missing = set(arcs.pid) - set(assign)
    if bad or missing:
        raise ValueError(f"infeasible solution: {len(bad)} non-admissible arcs, {len(missing)} unassigned patients")


def evaluate(assign: dict, arcs: pd.DataFrame, inst, hospitals: pd.DataFrame, label: str = ""):
    check_feasible(assign, arcs)
    a = arcs.set_index(["pid", "hosp"]).loc[list(assign.items())].reset_index()
    a = a.merge(inst.patients[["pid", "response_min", "fasted", "onset_elapsed_at_call", "call_min", "child"]], on="pid")

    # --- deterministic FIFO offload queue per hospital ---
    a["wait"] = 0.0
    for j, grp in a.groupby("hosp"):
        h = hospitals.loc[j]
        free_at = -np.inf
        for idx in grp.sort_values("arrival_min").index:
            t = a.at[idx, "arrival_min"]
            start = max(t, free_at)
            a.at[idx, "wait"] = start - t
            free_at = start + 60.0 / offload_rate(h, int(start // 60))
    a["apot"] = a["wait"] + C.SIM["handover_min"]
    a["TDC"] = a["T_no_wait"] + a["wait"]                      # call -> definitive care

    # --- hospital crowding cost (hourly ED load = expected walk-ins + ambulance arrivals) ---
    cost = 0.0
    a["hour"] = (a["arrival_min"] // 60).astype(int)
    amb = a.groupby(["hosp", "hour"]).size()
    for j, h in hospitals.iterrows():
        for hr in range(max(26, int(a["hour"].max()) + 1)):
            load = h.walkin_per_hour * _PROF[hr % 24] / _PROF.mean() + amb.get((j, hr), 0)
            cost += crowding_cost(load, h.ed_capacity_per_hour)

    # --- metrics ---
    w = a["weight"]
    stemi = a[a.cls == "stemi"]
    fmc_to_device = stemi["TDC"] - stemi["response_min"]
    lvo = a[(a.cls == "stroke") & (a.fasted >= C.PROTOCOL["stroke_fasted_cutoff"])]
    tred = a[a.cls == "trauma_red"]
    gen = a[a.cls.isin(["general_low", "general_high", "behavioral"])]
    gA, gB = gen[gen.group == "A"]["TDC"].mean(), gen[gen.group == "B"]["TDC"].mean()
    sn = hospitals.safety_net.values
    m = {
        "policy": label, "day": inst.day, "n": len(a),
        "acuity_weighted_TDC": float((w * a.TDC).sum() / w.sum()),
        "mean_TDC": float(a.TDC.mean()),
        "wall_hours": float(a.wait.sum() / 60.0),
        "pct_APOT_le_30": float((a.apot <= 30).mean() * 100),
        "p90_APOT": float(a.apot.quantile(0.9)),
        "crowding_cost": cost,
        "pct_bypass_closest": float(a.deviation.mean() * 100),
        "pct_STEMI_FMC2D_le_90": float((fmc_to_device <= 90).mean() * 100) if len(stemi) else np.nan,
        "pct_LVO_direct_to_EVT": float(hospitals.loc[lvo.hosp, "evt"].mean() * 100) if len(lvo) else np.nan,
        "pct_trauma_red_L1L2": float(hospitals.loc[tred.hosp, "trauma_adult"].isin([1, 2]).mean() * 100) if len(tred) else np.nan,
        "equity_gap_TDC_B_minus_A": float(gB - gA),
        "pct_groupB_to_safety_net": float(sn[a[a.group == "B"].hosp].mean() * 100),
        "pct_continuity_honored": float(a[a.has_continuity_option == 1].is_continuity.mean() * 100)
                                  if (a.has_continuity_option == 1).any() else np.nan,
    }
    return m, a
