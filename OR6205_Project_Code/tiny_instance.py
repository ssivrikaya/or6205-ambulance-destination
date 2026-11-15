"""
tiny_instance.py - a hand-checkable instance (6 patients, 3 hospitals) for the
"Verification of the math model" section, like your professor's sample project.

  python tiny_instance.py

Prints the admissible arcs and hospital data. Solve your formulation BY HAND (or by
enumeration) on this table, then confirm your Gurobi code returns the same optimum.
"""
import numpy as np
import pandas as pd

import config as C
from instance import DayInstance, planar_travel_time
from protocol import ProtocolCompiler

hosp = pd.DataFrame([
    # id name       x    y   kind trA trP pci strD evt ct ld obN peds burn sane sn off cap walk
    [0, "H0", 10.0, 10.0, "ED", 1, 0, 1, 1, 1, 1, 1, 1, 0, 0, 1, 0, 2, 4, 2],
    [1, "H1", 13.0, 10.0, "ED", 0, 0, 0, 1, 0, 1, 1, 0, 0, 0, 0, 1, 2, 3, 2],
    [2, "H2", 10.0, 14.0, "ED", 0, 0, 1, 1, 0, 1, 0, 0, 1, 0, 0, 0, 1, 3, 1],
], columns=["id", "name", "x_km", "y_km", "kind", "trauma_adult", "trauma_peds", "pci",
            "stroke_designated", "evt", "ct_24_7", "ld", "ob_night", "peds", "burn", "sane",
            "safety_net", "offload_per_hour", "ed_capacity_per_hour", "walkin_per_hour"])

pts = pd.DataFrame({
    "pid": range(6), "day": 0,
    "call_min": [600, 602, 605, 610, 612, 615],
    "x_km": [11.5, 12.0, 10.5, 11.0, 12.5, 10.2], "y_km": [11.0, 10.5, 12.5, 11.5, 11.0, 13.0],
    "cls": ["general_low", "stemi", "general_high", "ob_labor", "general_low", "stroke"],
    "child": False, "unstable": [False, False, True, False, False, False],
    "crew": ["BLS", "PARAMEDIC", "PARAMEDIC", "BLS", "BLS", "PARAMEDIC"],
    "group": ["A", "B", "A", "B", "A", "B"], "continuity": [2, -1, -1, -1, 0, -1],
    "onset_elapsed_at_call": [np.nan] * 5 + [60.0], "fasted": [-1] * 5 + [7],
    "stemi_high_risk": False, "arrest_or_airway": False,
    "response_min": 8.0, "scene_min": 15.0,
})
pts["weight"] = [C.ACUITY_WEIGHT[c] for c in pts.cls]
pts["depart_min"] = pts.call_min + pts.response_min + pts.scene_min
tau = np.column_stack([planar_travel_time(pts.x_km, pts.y_km, hosp.x_km[j], hosp.y_km[j], pts.depart_min) for j in range(3)])
inst = DayInstance(day=0, patients=pts, tau=tau, busy=np.zeros(200))

arcs, plans = ProtocolCompiler(hosp).compile_day(inst)
pd.set_option("display.width", 160)
print("HOSPITALS\n", hosp[["id", "pci", "evt", "ld", "offload_per_hour", "ed_capacity_per_hour", "walkin_per_hour"]], "\n")
print("PLANS\n", plans, "\n")
print("ADMISSIBLE ARCS\n", arcs[["pid", "hosp", "plan", "tau", "period", "T_no_wait", "weight", "is_p0"]].round(1))
