"""
run_experiments.py - runs experiments E1-E5 from the project blueprint.

  python run_experiments.py --selftest                 # whole pipeline, no model needed
  python run_experiments.py --days 30 --policies P0,RH,FI
  python run_experiments.py --scenarios base,reading_B,band10,band30,code_black_A,surge
  python run_experiments.py --policies FI --eps-grid 1,0.75,0.5,0.25,0   # Pareto (E2)
  python run_experiments.py --policies P0,FI --duals                     # shadow prices (E5)

Outputs go to results/<scenario>/ : per-day metrics, summary with 95% CIs, the protocol
flexibility table (how much decision freedom the POE plans leave), and figures.
"""
import argparse
import json
import os
import time

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import config as C
from hospitals import load_hospitals
from instance import generate_day
from protocol import ProtocolCompiler
from evaluate import evaluate
import model as M

SCENARIOS = {
    "base": ({}, {}),
    "reading_B": ({"ten_minute_reading": "B"}, {}),
    "band10": ({"general_extra_time_band": 10.0}, {}),
    "band30": ({"general_extra_time_band": 30.0}, {}),
    "olmc": ({"allow_olmc_beyond_band": True}, {}),
    "stemi_band20": ({"stemi_pci_extra_band": 20.0}, {}),
    "stemi_band40": ({"stemi_pci_extra_band": 40.0}, {}),
    "stroke_band15": ({"stroke_evt_extra_band": 15.0}, {}),
    "stroke_band45": ({"stroke_evt_extra_band": 45.0}, {}),
    "code_black_A": ({}, {"code_black": [0]}),
    "surge": ({}, {"demand_multiplier": 1.2}),
    "busy_strict": ({}, {"ems_busy_threshold": 0.6}),
}

KEY_METRICS = ["acuity_weighted_TDC", "wall_hours", "pct_APOT_le_30", "crowding_cost",
               "pct_STEMI_FMC2D_le_90", "pct_LVO_direct_to_EVT", "pct_bypass_closest",
               "equity_gap_TDC_B_minus_A"]


def p0_assignment(arcs):
    return dict(zip(arcs[arcs.is_p0 == 1].pid, arcs[arcs.is_p0 == 1].hosp))


def rolling_horizon(arcs, inst, hospitals, solver, step=15, memory=180):
    """Re-solve every `step` minutes with only the patients whose 911 call has arrived.
    Decisions are committed when the ambulance leaves the scene."""
    pts = inst.patients.set_index("pid")
    committed, now, n_solves = {}, 0.0, 0
    end = pts.depart_min.max() + step
    while now <= end and len(committed) < len(pts):
        known = pts.index[pts.call_min <= now]
        pending = [p for p in known if p not in committed]
        if pending:
            recent = {p: j for p, j in committed.items() if pts.at[p, "depart_min"] >= now - memory}
            window = arcs[arcs.pid.isin(pending) | arcs.pid.isin(list(recent))]
            assign, _ = solver(window, hospitals, inst, fixed=recent)
            n_solves += 1
            for p in pending:
                if pts.at[p, "depart_min"] < now + step:
                    committed[p] = assign[p]
        now += step
    return committed, n_solves


def flexibility_table(plans):
    t = plans.groupby("plan").agg(patients=("pid", "size"),
                                  mean_admissible=("n_admissible", "mean"),
                                  pct_with_choice=("n_admissible", lambda s: 100 * (s > 1).mean()))
    t.loc["ALL"] = [len(plans), plans.n_admissible.mean(), 100 * (plans.n_admissible > 1).mean()]
    return t.round(2)


def summarize(df):
    g = df.groupby("policy")
    out = {}
    for m in KEY_METRICS + ["mean_TDC", "p90_APOT", "pct_trauma_red_L1L2", "pct_groupB_to_safety_net",
                            "pct_continuity_honored"]:
        mu, sd, n = g[m].mean(), g[m].std(ddof=1), g[m].count()
        out[m] = mu.round(2).astype(str) + " ± " + (1.96 * sd / np.sqrt(n)).round(2).astype(str)
    return pd.DataFrame(out).T


def plot_bars(df, path):
    fig, axes = plt.subplots(2, 4, figsize=(15, 6.5))
    for ax, m in zip(axes.flat, KEY_METRICS):
        g = df.groupby("policy")[m]
        mu, ci = g.mean(), 1.96 * g.std(ddof=1).fillna(0) / np.sqrt(g.count())
        ax.bar(mu.index, mu.values, yerr=ci.values, capsize=4, color="#4C72B0")
        ax.set_title(m, fontsize=9)
        ax.tick_params(labelsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def run(args):
    hospitals = load_hospitals(args.hospitals, C.SIM["region_km"])
    solver = M.plumbing_stand_in if args.selftest else M.solve
    for scen in args.scenarios.split(","):
        prot, scenario = SCENARIOS[scen]
        out = os.path.join(args.out, scen)
        os.makedirs(out, exist_ok=True)
        comp = ProtocolCompiler(hospitals, prot, scenario)
        rows, plans_all, pareto, duals = [], [], [], []
        for d in range(args.day_from, args.day_from + args.days):
            inst = generate_day(d, hospitals, demand_multiplier=comp.S["demand_multiplier"])
            arcs, plans = comp.compile_day(inst)
            plans_all.append(plans.assign(day=d))
            for pol in args.policies.split(","):
                t0 = time.time()
                try:
                    if pol == "P0":
                        assign, info = p0_assignment(arcs), {}
                    elif pol == "FI":
                        assign, info = solver(arcs, hospitals, inst, time_limit=args.time_limit)
                    elif pol == "RH":
                        assign, n = rolling_horizon(arcs, inst, hospitals, solver)
                        info = {"solves": n}
                    else:
                        raise ValueError(pol)
                except NotImplementedError as e:
                    print(f"[{scen}] skipping {pol}: {e}")
                    continue
                m, _ = evaluate(assign, arcs, inst, hospitals, pol)
                m["runtime_s"] = round(time.time() - t0, 2)
                m.update({f"model_{k}": v for k, v in info.items() if np.isscalar(v)})
                rows.append(m)
            if args.eps_grid and not args.selftest:          # E2: epsilon-constraint Pareto frontier
                _, hi = M.solve(arcs, hospitals, inst, time_limit=args.time_limit)                    # min f1
                _, lo = M.solve(arcs, hospitals, inst, objective="f2", time_limit=args.time_limit)    # min f2
                for frac in map(float, args.eps_grid.split(",")):
                    eps = lo["f2"] + frac * (hi["f2"] - lo["f2"]) + 1e-6
                    assign, inf2 = M.solve(arcs, hospitals, inst, epsilon=eps, time_limit=args.time_limit)
                    m, _ = evaluate(assign, arcs, inst, hospitals, f"eps={frac:g}")
                    m.update({"eps_frac": frac, "model_f1": inf2["f1"], "model_f2": inf2["f2"]})
                    pareto.append(m)
            if args.duals and not args.selftest:              # E5: shadow prices of offload capacity
                _, inf3 = M.solve(arcs, hospitals, inst, want_duals=True, time_limit=args.time_limit)
                for (j, t), v in inf3["duals"].items():
                    duals.append({"day": d, "hosp": j, "hour": (t * C.SIM["period_min"] // 60) % 24, "value": v})
            print(f"[{scen}] day {d} done ({len(inst.patients)} transports)", flush=True)

        tag = f"_d{args.day_from:03d}"
        pd.DataFrame(rows).to_csv(os.path.join(out, f"raw_metrics{tag}.csv"), index=False)
        pd.concat(plans_all).to_csv(os.path.join(out, f"raw_plans{tag}.csv"), index=False)
        if pareto:
            pd.DataFrame(pareto).to_csv(os.path.join(out, f"raw_pareto{tag}.csv"), index=False)
        if duals:
            pd.DataFrame(duals).to_csv(os.path.join(out, f"raw_duals{tag}.csv"), index=False)
        with open(os.path.join(out, "settings.json"), "w") as f:
            json.dump({"protocol": comp.P, "scenario": comp.S, "sim": C.SIM, "model": C.MODEL,
                       "selftest": args.selftest}, f, indent=2, default=str)
        if not args.no_summary:
            summarize_folder(out, hospitals)


def _load(out, prefix):
    import glob
    files = sorted(glob.glob(os.path.join(out, f"raw_{prefix}_d*.csv")))
    return pd.concat([pd.read_csv(f) for f in files]) if files else pd.DataFrame()


def summarize_folder(out, hospitals):
    """Combine all day-chunks in a scenario folder into summaries and figures."""
    df, plans, pareto, duals = (_load(out, p) for p in ("metrics", "plans", "pareto", "duals"))
    df.to_csv(os.path.join(out, "metrics_by_day.csv"), index=False)
    summarize(df).to_csv(os.path.join(out, "summary_95ci.csv"))
    flex = flexibility_table(plans)
    flex.to_csv(os.path.join(out, "protocol_flexibility.csv"))
    plot_bars(df, os.path.join(out, "key_metrics.png"))
    if len(pareto):
        pareto.to_csv(os.path.join(out, "pareto.csv"), index=False)
        g = pareto.groupby("eps_frac")[["crowding_cost", "acuity_weighted_TDC", "wall_hours"]].mean().sort_index()
        g.to_csv(os.path.join(out, "pareto_mean.csv"))
        p0 = df[df.policy == "P0"][["crowding_cost", "acuity_weighted_TDC"]].mean() if (df.policy == "P0").any() else None
        fig, ax = plt.subplots(figsize=(5.5, 4.2))
        ax.plot(g.crowding_cost, g.acuity_weighted_TDC, "o-", label="optimized (epsilon-constraint)")
        for fr, r in g.iterrows():
            ax.annotate(f"{fr:g}", (r.crowding_cost, r.acuity_weighted_TDC), fontsize=8,
                        xytext=(4, 4), textcoords="offset points")
        if p0 is not None:
            ax.plot(p0.crowding_cost, p0.acuity_weighted_TDC, "s", color="crimson", label="P0 protocol baseline")
        ax.set_xlabel("hospital crowding cost (f2)"); ax.set_ylabel("acuity-weighted time to care (min)")
        ax.legend(fontsize=8); fig.tight_layout(); fig.savefig(os.path.join(out, "pareto.png"), dpi=150); plt.close(fig)
    if len(duals):
        piv = duals.groupby(["hosp", "hour"]).value.mean().unstack(fill_value=0.0)
        piv.index = [hospitals.name[j] for j in piv.index]
        piv.to_csv(os.path.join(out, "shadow_prices_hosp_hour.csv"))
        fig, ax = plt.subplots(figsize=(10, 4.8))
        im = ax.imshow(piv.values, aspect="auto", cmap="viridis")
        ax.set_yticks(range(len(piv.index))); ax.set_yticklabels(piv.index, fontsize=8)
        ax.set_xticks(range(len(piv.columns))); ax.set_xticklabels(piv.columns, fontsize=8)
        ax.set_xlabel("hour of day"); fig.colorbar(im, ax=ax, label="value of +1 offload slot (objective units)")
        fig.tight_layout(); fig.savefig(os.path.join(out, "shadow_prices.png"), dpi=150); plt.close(fig)
    print(f"\n=== {out}: protocol flexibility ===\n{flex}\n\n=== {out}: summary ===\n{summarize(df)}\n")


def compare_scenarios(out_root, scenarios):
    """Cross-scenario table (P0 vs FI): results/scenario_comparison.csv"""
    rows = []
    for scen in scenarios:
        d = pd.read_csv(os.path.join(out_root, scen, "metrics_by_day.csv"))
        f = pd.read_csv(os.path.join(out_root, scen, "protocol_flexibility.csv"), index_col=0)
        g = d.groupby("policy").mean(numeric_only=True)
        if not {"P0", "FI"} <= set(g.index):
            print(f"{scen}: needs P0 and FI results; skipped")
            continue
        r = {"scenario": scen, "pct_with_choice": f.loc["ALL", "pct_with_choice"]}
        for m in ["acuity_weighted_TDC", "wall_hours", "crowding_cost", "pct_STEMI_FMC2D_le_90",
                  "pct_LVO_direct_to_EVT", "pct_continuity_honored"]:
            r[m + "_P0"], r[m + "_FI"] = g.loc["P0", m], g.loc["FI", m]
        r["wall_reduction_%"] = 100 * (1 - g.loc["FI", "wall_hours"] / g.loc["P0", "wall_hours"])
        r["crowd_reduction_%"] = 100 * (1 - g.loc["FI", "crowding_cost"] / g.loc["P0", "crowding_cost"])
        r["TDC_reduction_min"] = g.loc["P0", "acuity_weighted_TDC"] - g.loc["FI", "acuity_weighted_TDC"]
        rows.append(r)
    t = pd.DataFrame(rows).round(2)
    t.to_csv(os.path.join(out_root, "scenario_comparison.csv"), index=False)
    print(t.to_string(index=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=C.SIM["n_days"])
    ap.add_argument("--policies", default="P0,RH,FI")
    ap.add_argument("--scenarios", default="base")
    ap.add_argument("--hospitals", default=None, help="CSV following data/hospitals_template.csv")
    ap.add_argument("--eps-grid", default=None)
    ap.add_argument("--time-limit", type=int, default=60)
    ap.add_argument("--duals", action="store_true", help="E5: shadow prices of offload capacity")
    ap.add_argument("--day-from", type=int, default=0, help="first day index (run long studies in chunks)")
    ap.add_argument("--no-summary", action="store_true", help="only write raw chunk files")
    ap.add_argument("--summarize", action="store_true", help="only combine existing chunks into summaries")
    ap.add_argument("--compare", action="store_true", help="build results/scenario_comparison.csv from finished scenarios")
    ap.add_argument("--out", default="results")
    ap.add_argument("--selftest", action="store_true", help="use the plumbing stand-in instead of your model")
    a = ap.parse_args()
    if a.selftest and a.days == C.SIM["n_days"]:
        a.days = 3
    if a.compare:
        compare_scenarios(a.out, a.scenarios.split(","))
    elif a.summarize:
        h = load_hospitals(a.hospitals, C.SIM["region_km"])
        for scen in a.scenarios.split(","):
            summarize_folder(os.path.join(a.out, scen), h)
    else:
        run(a)
