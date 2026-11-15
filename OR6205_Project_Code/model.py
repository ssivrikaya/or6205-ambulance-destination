"""
model.py - entry point used by run_experiments.py.

solve(arcs, hospitals, inst, epsilon=None, fixed=None, time_limit=60,
      objective="f1", want_duals=False, solver=None) -> (assign, info)

  objective  "f1" (EMS/patient objective, default) or "f2" (hospital crowding objective);
             the other one is added with a tiny weight to break ties (lexicographic).
  epsilon    adds f2 <= epsilon (epsilon-constraint method, Pareto frontier).
  fixed      {pid: hosp} decisions already committed (rolling horizon).
  solver     "gurobi", "highs" or None -> config.MODEL["solver"] ("auto" = Gurobi if installed).

The formulation is documented in MODEL_FORMULASYONU.md. Both backends solve the same model.
"""
import config as C
from formulation import prepare


def _backend(name):
    name = name or C.MODEL["solver"]
    if name in ("gurobi", "auto"):
        try:
            from model_gurobi import solve_gurobi
            return solve_gurobi
        except ImportError:
            if name == "gurobi":
                raise
    from model_highs import solve_highs
    return solve_highs


def solve(arcs, hospitals, inst=None, epsilon=None, fixed=None, time_limit=60,
          objective="f1", want_duals=False, solver=None):
    data = prepare(arcs, hospitals, fixed)
    return _backend(solver)(data, epsilon=epsilon, objective=objective,
                            equity_delta=C.MODEL["equity_delta"], time_limit=time_limit,
                            want_duals=want_duals)


def plumbing_stand_in(arcs, hospitals, inst, epsilon=None, fixed=None, time_limit=60, **kw):
    """NOT a model: returns the baseline choice for every patient (pipeline test only)."""
    assign = dict(fixed or {})
    for r in arcs[arcs.is_p0 == 1].itertuples(index=False):
        assign.setdefault(r.pid, r.hosp)
    return assign, {"note": "plumbing stand-in, not an optimization model"}
