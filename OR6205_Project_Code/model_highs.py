"""
model_highs.py - the MILP of MODEL_FORMULASYONU.md in matrix form, solved with HiGHS
(scipy.optimize.milp). Used to verify the model without a Gurobi licence and as a fallback.

Variable vector: [ x_a (binary, |A|) | B_jt (>=0, |J||T|) | y_jhk (>=0, |J||H||K|) ]
"""
import time
import numpy as np
from scipy import sparse
from scipy.optimize import milp, linprog, LinearConstraint, Bounds

import config as C


def _build(data, epsilon, objective, equity_delta):
    n = len(data.arcs)
    J, T, H, K = data.J, data.T, data.H, data.K
    bidx = {(j, t): n + q for q, (j, t) in enumerate((j, t) for j in J for t in T)}
    off = n + len(bidx)
    yidx = {(j, h, k): off + q for q, (j, h, k) in enumerate((j, h, k) for j in J for h in H for k in K)}
    nv = off + len(yidx)

    # objective pieces
    c_f1 = np.zeros(nv); c_f2 = np.zeros(nv)
    c_f1[:n] = data.c1
    for v in bidx.values():
        c_f1[v] = data.lamD
    for (j, h, k), v in yidx.items():
        c_f2[v] = data.slope[k]
    tb = C.MODEL["tie_break"]
    c = c_f1 + tb * c_f2 if objective == "f1" else c_f2 + tb * c_f1

    eq_r, eq_c, eq_v, b_eq = [], [], [], []
    ub_r, ub_c, ub_v, b_ub = [], [], [], []
    row = 0
    for i, arcs_i in data.arcs_of_patient.items():                     # (1) assignment
        for a in arcs_i:
            eq_r.append(row); eq_c.append(a); eq_v.append(1.0)
        b_eq.append(1.0); row += 1
    for j in J:                                                         # (3) hourly load balance
        for h in H:
            for k in K:
                eq_r.append(row); eq_c.append(yidx[j, h, k]); eq_v.append(1.0)
            for a in data.arcs_jh.get((j, h), []):
                eq_r.append(row); eq_c.append(a); eq_v.append(-1.0)
            b_eq.append(data.walk[j, h]); row += 1

    row = 0
    backlog_rows = {}
    for j in J:                                                         # (2) offload backlog
        for q, t in enumerate(T):
            for a in data.arcs_jt.get((j, t), []):
                ub_r.append(row); ub_c.append(a); ub_v.append(1.0)
            if q > 0:
                ub_r.append(row); ub_c.append(bidx[j, T[q - 1]]); ub_v.append(1.0)
            ub_r.append(row); ub_c.append(bidx[j, t]); ub_v.append(-1.0)
            b_ub.append(data.mu[j, t]); backlog_rows[j, t] = row; row += 1
    if epsilon is not None:                                             # (5) epsilon-constraint
        for v in np.nonzero(c_f2)[0]:
            ub_r.append(row); ub_c.append(v); ub_v.append(c_f2[v])
        b_ub.append(float(epsilon)); row += 1
    if equity_delta is not None and data.equity_coef:                   # (6) equity (two rows)
        for sgn in (1.0, -1.0):
            for a, coef in data.equity_coef.items():
                ub_r.append(row); ub_c.append(a); ub_v.append(sgn * coef)
            b_ub.append(float(equity_delta)); row += 1

    A_eq = sparse.csr_matrix((eq_v, (eq_r, eq_c)), shape=(len(b_eq), nv))
    A_ub = sparse.csr_matrix((ub_v, (ub_r, ub_c)), shape=(len(b_ub), nv))
    lb = np.zeros(nv); ub = np.full(nv, np.inf)
    ub[:n] = 1.0
    for (j, h, k), v in yidx.items():
        ub[v] = data.seg_ub[j, k]
    for a in data.fixed_arcs:                                           # (7) fixed decisions
        lb[a] = 1.0
    integ = np.zeros(nv); integ[:n] = 1
    return dict(n=n, nv=nv, c=c, c_f1=c_f1, c_f2=c_f2, A_eq=A_eq, b_eq=np.array(b_eq),
                A_ub=A_ub, b_ub=np.array(b_ub), lb=lb, ub=ub, integ=integ, backlog_rows=backlog_rows)


def solve_highs(data, epsilon=None, objective="f1", equity_delta=None, time_limit=60,
                mip_gap=None, want_duals=False):
    t0 = time.time()
    m = _build(data, epsilon, objective, equity_delta)
    cons = [LinearConstraint(m["A_eq"], m["b_eq"], m["b_eq"])]
    if m["A_ub"].shape[0]:
        cons.append(LinearConstraint(m["A_ub"], -np.inf, m["b_ub"]))
    res = milp(m["c"], constraints=cons, integrality=m["integ"], bounds=Bounds(m["lb"], m["ub"]),
               options={"time_limit": time_limit, "mip_rel_gap": C.MODEL["mip_gap"] if mip_gap is None else mip_gap, "disp": False})
    if res.x is None:
        raise RuntimeError(f"HiGHS: no solution (status {res.status}: {res.message})")
    z = res.x
    xa = np.where(z[:m["n"]] > 0.5)[0]
    a = data.arcs
    assign = {int(a.pid[i]): int(a.hosp[i]) for i in xa}
    info = {"solver": "highs", "status": int(res.status), "obj": float(res.fun),
            "f1": float(m["c_f1"] @ z), "f2": float(m["c_f2"] @ z),
            "gap": float(getattr(res, "mip_gap", np.nan) or 0.0), "runtime": round(time.time() - t0, 3),
            "n_binary": m["n"], "n_vars": m["nv"]}
    if want_duals:                         # E5: fix x, solve the LP, read backlog duals
        lb, ub = m["lb"].copy(), m["ub"].copy()
        xr = np.round(z[:m["n"]])
        lb[:m["n"]] = xr; ub[:m["n"]] = xr
        lp = linprog(m["c"], A_ub=m["A_ub"], b_ub=m["b_ub"], A_eq=m["A_eq"], b_eq=m["b_eq"],
                     bounds=list(zip(lb, ub)), method="highs")
        marg = lp.ineqlin.marginals
        # value of +1 offload slot in (j,t) = -d(obj)/d(mu_jt)
        info["duals"] = {(j, t): float(-marg[r]) for (j, t), r in m["backlog_rows"].items()}
    return assign, info
