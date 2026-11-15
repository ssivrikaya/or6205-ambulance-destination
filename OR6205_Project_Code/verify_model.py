"""
verify_model.py - proves the implementation solves the model it claims to solve.

  python verify_model.py

Test 1  Brute force: on small congested sub-instances, enumerate EVERY feasible assignment,
        score each one with an independent calculation (Lindley recursion + closed-form
        convex cost, no solver), and check the solver finds the same optimum.
        Repeated for objective f1, objective f2, and the epsilon-constraint mode.
Test 2  Objective recomputation: on full days, the objective the solver reports must equal the
        independent recalculation for its chosen assignment (checks B = max(0, ...) and the
        convex segment filling at the optimum).
Test 3  Feasibility: every solution passes the protocol feasibility check in evaluate.py.
Test 4  (only if gurobipy is installed) Gurobi and HiGHS return the same optimal value.
"""
import itertools
import numpy as np

import config as C
from hospitals import load_hospitals
from instance import generate_day
from protocol import ProtocolCompiler
from formulation import prepare, true_objectives
from model_highs import solve_highs
from evaluate import check_feasible

TB = C.MODEL["tie_break"]


def enumerate_all(data):
    choices = [data.arcs_of_patient[i] for i in sorted(data.arcs_of_patient)]
    return [true_objectives(data, combo) for combo in itertools.product(*choices)]


def brute_force(table, objective="f1", epsilon=None):
    best = (np.inf, None, None)
    for f1, f2 in table:
        if epsilon is not None and f2 > epsilon + 1e-6:
            continue
        val = f1 + TB * f2 if objective == "f1" else f2 + TB * f1
        if val < best[0]:
            best = (val, f1, f2)
    return best


def test_bruteforce(n_cases=6, max_multi=9, seed=0):
    h = load_hospitals(None, C.SIM["region_km"]).copy()
    h["offload_per_hour"] = 1.0                       # congested on purpose: forces trade-offs
    # heterogeneous ED headroom so hospitals sit on different crowding-cost segments
    h["ed_capacity_per_hour"] = h["walkin_per_hour"] * (0.9 + 0.12 * (h.index % 5))
    comp = ProtocolCompiler(h)
    rng = np.random.default_rng(seed)
    ok = 0
    for case in range(n_cases):
        inst = generate_day(case, h)
        arcs, plans = comp.compile_day(inst)
        start = rng.uniform(8 * 60, 18 * 60)
        win = inst.patients[(inst.patients.call_min >= start) & (inst.patients.call_min < start + 150)].pid
        multi, n_comb = [], 1
        for p in win:                                   # keep enumeration size <= 4096
            k = plans.n_admissible[p]
            if k > 1 and n_comb * k <= 4096 and len(multi) < max_multi:
                multi.append(p); n_comb *= k
        single = [p for p in win if plans.n_admissible[p] == 1][:6]
        sub = arcs[arcs.pid.isin(multi + single)]
        data = prepare(sub, h)
        table = enumerate_all(data)
        for objective, eps in (("f1", None), ("f2", None), ("f1", "mid")):
            if eps == "mid":
                f2_hi = brute_force(table, "f1")[2]
                f2_lo = brute_force(table, "f2")[2]
                eps = f2_lo + 0.3 * (f2_hi - f2_lo)    # binding whenever f2_hi > f2_lo
            bf = brute_force(table, objective, eps)
            _, info = solve_highs(data, epsilon=eps, objective=objective, mip_gap=0.0)
            match = abs(bf[0] - info["obj"]) <= 1e-6 * max(1.0, abs(bf[0]))
            ok += match
            n_comb = len(table)
            print(f"  case {case} {objective:>2} eps={'-' if eps is None else round(eps, 2):>7}  "
                  f"{n_comb:5d} assignments  brute-force={bf[0]:.4f}  solver={info['obj']:.4f}  "
                  f"{'OK' if match else 'MISMATCH'}")
    return ok, 3 * n_cases


def test_full_days(days=(0, 1, 2)):
    h = load_hospitals(None, C.SIM["region_km"])
    comp = ProtocolCompiler(h)
    ok = 0
    for d in days:
        inst = generate_day(d, h)
        arcs, _ = comp.compile_day(inst)
        data = prepare(arcs, h)
        assign, info = solve_highs(data)
        check_feasible(assign, arcs)                    # Test 3
        key = dict(zip(zip(data.arcs.pid, data.arcs.hosp), data.arcs.index))
        f1, f2 = true_objectives(data, [key[p, j] for p, j in assign.items()])
        match = abs(f1 - info["f1"]) < 1e-4 * f1 and abs(f2 - info["f2"]) < 1e-4 * max(f2, 1)
        ok += match
        print(f"  day {d}: solver f1={info['f1']:.2f} f2={info['f2']:.2f} | recomputed f1={f1:.2f} f2={f2:.2f} "
              f"| {info['n_binary']} binaries, {info['runtime']} s  {'OK' if match else 'MISMATCH'}")
        try:
            from model_gurobi import solve_gurobi            # Test 4
            _, gi = solve_gurobi(data, mip_gap=1e-6)
            _, hi = solve_highs(data, mip_gap=1e-6)
            same = abs(gi["obj"] - hi["obj"]) <= 1e-5 * abs(hi["obj"])
            print(f"         Gurobi obj={gi['obj']:.3f}  HiGHS obj={hi['obj']:.3f}  {'OK' if same else 'MISMATCH'}")
        except ImportError:
            pass
    return ok, len(days)


if __name__ == "__main__":
    print("Test 1: brute-force enumeration vs solver")
    a, b = test_bruteforce()
    print(f"  -> {a}/{b} passed\n")
    print("Test 2-4: full days (objective recomputation, feasibility, Gurobi vs HiGHS if available)")
    c, d = test_full_days()
    print(f"  -> {c}/{d} passed")
    try:
        import gurobipy  # noqa: F401
    except ImportError:
        print("\n(gurobipy not installed: Test 4 skipped. Run this script on your machine to compare Gurobi with HiGHS.)")
