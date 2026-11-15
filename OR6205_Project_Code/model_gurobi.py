"""
model_gurobi.py - the MILP of MODEL_FORMULASYONU.md written algebraically in gurobipy.
Each block below corresponds to one numbered constraint in the formulation document.

Requires: pip install gurobipy  (academic licence for full-size instances)
Cross-check against the HiGHS implementation with:  python verify_model.py
"""
import time
import gurobipy as gp
from gurobipy import GRB

import config as C


def solve_gurobi(data, epsilon=None, objective="f1", equity_delta=None, time_limit=60,
                 mip_gap=None, want_duals=False):
    t0 = time.time()
    a = data.arcs
    A = range(len(a))
    m = gp.Model("ems_destination")
    m.Params.OutputFlag = 0
    m.Params.TimeLimit = time_limit
    m.Params.MIPGap = C.MODEL["mip_gap"] if mip_gap is None else mip_gap

    # ---------------- decision variables ----------------
    x = m.addVars(A, vtype=GRB.BINARY, name="x")                       # x_a: patient i(a) -> hospital j(a)
    B = m.addVars(data.J, data.T, lb=0.0, name="B")                     # B_jt: ambulances waiting at end of t
    y = {}
    for j in data.J:                                                    # y_jhk: hourly ED load in cost segment k
        for h in data.H:
            for k in data.K:
                ub = data.seg_ub[j, k]
                y[j, h, k] = m.addVar(lb=0.0, ub=ub if ub != float("inf") else GRB.INFINITY,
                                      name=f"y[{j},{h},{k}]")

    # ---------------- (1) assignment: one destination per patient ----------------
    for i, arcs_i in data.arcs_of_patient.items():
        m.addConstr(gp.quicksum(x[q] for q in arcs_i) == 1, name=f"assign[{i}]")

    # ---------------- (2) offload backlog (Lindley recursion, linearised) ----------------
    #   arrivals_jt + B_j,t-1 - B_jt <= mu_jt      (with B >= 0 and B in the objective,
    #   B_jt = max(0, B_j,t-1 + arrivals_jt - mu_jt) at the optimum)
    for j in data.J:
        for q, t in enumerate(data.T):
            arrivals = gp.quicksum(x[r] for r in data.arcs_jt.get((j, t), []))
            prev = B[j, data.T[q - 1]] if q > 0 else 0.0
            m.addConstr(arrivals + prev - B[j, t] <= data.mu[j, t], name=f"backlog[{j},{t}]")

    # ---------------- (3) hourly ED load split into convex cost segments ----------------
    for j in data.J:
        for h in data.H:
            amb = gp.quicksum(x[r] for r in data.arcs_jh.get((j, h), []))
            m.addConstr(gp.quicksum(y[j, h, k] for k in data.K) == data.walk[j, h] + amb,
                        name=f"load[{j},{h}]")

    # ---------------- objectives ----------------
    f1 = gp.quicksum(float(data.c1[r]) * x[r] for r in A) + data.lamD * B.sum()
    f2 = gp.quicksum(data.slope[k] * y[j, h, k] for j in data.J for h in data.H for k in data.K)

    # ---------------- (5) epsilon-constraint (Pareto frontier) ----------------
    if epsilon is not None:
        m.addConstr(f2 <= float(epsilon), name="epsilon")

    # ---------------- (6) optional equity constraint ----------------
    if equity_delta is not None and data.equity_coef:
        gap = gp.quicksum(coef * x[r] for r, coef in data.equity_coef.items())
        m.addConstr(gap <= equity_delta, name="equity_up")
        m.addConstr(gap >= -equity_delta, name="equity_lo")

    # ---------------- (7) decisions already committed (rolling horizon) ----------------
    for r in data.fixed_arcs:
        x[r].LB = 1.0

    tb = C.MODEL["tie_break"]
    m.setObjective(f1 + tb * f2 if objective == "f1" else f2 + tb * f1, GRB.MINIMIZE)
    m.optimize()
    if m.SolCount == 0:
        raise RuntimeError(f"Gurobi: no solution (status {m.Status})")

    assign = {int(a.pid[r]): int(a.hosp[r]) for r in A if x[r].X > 0.5}
    info = {"solver": "gurobi", "status": int(m.Status), "obj": m.ObjVal,
            "f1": f1.getValue(), "f2": f2.getValue(), "gap": m.MIPGap,
            "runtime": round(time.time() - t0, 3), "n_binary": len(a), "n_vars": m.NumVars}

    if want_duals:                          # E5: LP with x fixed -> duals of the backlog constraints
        fm = m.fixed()
        fm.Params.OutputFlag = 0
        fm.optimize()
        # constraint is "... <= mu_jt"; Pi = d(obj)/d(mu_jt) <= 0, so value of +1 slot = -Pi
        info["duals"] = {(j, t): -fm.getConstrByName(f"backlog[{j},{t}]").Pi
                         for j in data.J for t in data.T}
    return assign, info
