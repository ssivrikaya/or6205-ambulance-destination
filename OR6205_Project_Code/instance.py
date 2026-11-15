"""
instance.py - one "day" of ambulance transports (the patient set I) plus travel times.

Every distribution here is a PLACEHOLDER chosen to exercise the protocol rules.
Replace with calibrated inputs (NEMSIS public-release data for class mix, timestamps
and acuity; census tracts for spatial demand) before reporting results.

To use real road travel times, build an OSRM / OpenStreetMap matrix offline
(zone x hospital x hour) and pass it via `travel_time_fn` instead of `planar_travel_time`.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd

import config as C


def planar_travel_time(px, py, hx, hy, depart_min):
    """Straight-line distance x circuity / time-of-day speed, plus 1 min to load/unload."""
    dist = C.SIM["circuity"] * np.hypot(np.asarray(px) - hx, np.asarray(py) - hy)
    hour = (np.asarray(depart_min) // 60).astype(int) % 24
    peak = np.isin(hour, C.SIM["peak_hours"])
    speed = np.where(peak, C.SIM["speed_kmh_peak"], C.SIM["speed_kmh_offpeak"])
    return 1.0 + 60.0 * dist / speed


@dataclass
class DayInstance:
    day: int
    patients: pd.DataFrame      # one row per transport
    tau: np.ndarray             # tau[i, j] minutes from scene to hospital j
    busy: np.ndarray            # busy-ness proxy per period (0..1+)


def _sample_classes(rng, n):
    names = list(C.CLASS_MIX)
    p = np.array([C.CLASS_MIX[k] for k in names], dtype=float)
    return rng.choice(names, size=n, p=p / p.sum())


def generate_day(day: int, hospitals: pd.DataFrame, travel_time_fn=planar_travel_time,
                 demand_multiplier: float = 1.0) -> DayInstance:
    rng = np.random.default_rng(C.SIM["seed"] * 1000 + day)
    L = C.SIM["region_km"]
    weekend = day % 7 in (5, 6)
    n = rng.poisson(C.SIM["transports_per_day"] * demand_multiplier * (0.93 if weekend else 1.0))

    # call times from the hourly profile
    prof = np.array(C.HOURLY_PROFILE) / np.sum(C.HOURLY_PROFILE)
    hours = rng.choice(24, size=n, p=prof)
    call = np.sort(hours * 60 + rng.uniform(0, 60, size=n))

    # locations: dense core + uniform background
    core = rng.random(n) < 0.6
    x = np.where(core, rng.normal(L / 2, 3.0, n), rng.uniform(0, L, n)).clip(0, L)
    y = np.where(core, rng.normal(L / 2, 3.0, n), rng.uniform(0, L, n)).clip(0, L)
    r_center = np.hypot(x - L / 2, y - L / 2)
    group = np.where(rng.random(n) < np.where(r_center < 5, C.P_GROUP_B_CORE, C.P_GROUP_B_OUTER), "B", "A")

    cls = _sample_classes(rng, n)
    child = (cls == "peds_medical") | (np.isin(cls, ["trauma_red", "trauma_yellow", "burn"]) & (rng.random(n) < 0.15))
    unstable = rng.random(n) < np.array([C.P_UNSTABLE[c] for c in cls])
    crew = np.where(rng.random(n) < C.P_PARAMEDIC_CREW, "PARAMEDIC",
                    np.where(rng.random(n) < 0.5, "ALS_I", "BLS"))

    response = rng.uniform(*C.SIM["response_min"], size=n)
    scene = rng.uniform(*C.SIM["scene_min"], size=n)
    depart = call + response + scene

    # continuity-of-care hospital (general POE): random hospital, more likely nearby
    H = len(hospitals)
    tau = np.column_stack([travel_time_fn(x, y, hospitals.x_km[j], hospitals.y_km[j], depart) for j in range(H)])
    continuity = np.full(n, -1)
    has_cont = (~unstable) & (rng.random(n) < C.P_CONTINUITY)
    for i in np.where(has_cont)[0]:
        w = np.exp(-tau[i] / 15.0)
        continuity[i] = rng.choice(H, p=w / w.sum())

    # stroke attributes
    onset_elapsed = np.full(n, np.nan)
    fasted = np.full(n, -1)
    s = cls == "stroke"
    u = rng.random(s.sum())
    onset_elapsed[s] = np.where(u < 0.6, rng.exponential(70, s.sum()).clip(5, 230),
                                np.where(u < 0.9, rng.uniform(240, 1380, s.sum()), rng.uniform(1500, 3000, s.sum())))
    fasted[s] = rng.choice(10, size=s.sum(), p=[.10, .12, .12, .11, .10, .10, .10, .09, .08, .08])

    # STEMI attributes
    stemi_high_risk = (cls == "stemi") & (rng.random(n) < 0.25)       # lytic contraindication / severe CHF / hypotension
    arrest_or_airway = (cls == "stemi") & (rng.random(n) < 0.08)

    pts = pd.DataFrame({
        "pid": np.arange(n), "day": day, "call_min": call, "depart_min": depart,
        "x_km": x, "y_km": y, "cls": cls, "child": child, "unstable": unstable, "crew": crew,
        "group": group, "continuity": continuity, "onset_elapsed_at_call": onset_elapsed,
        "fasted": fasted, "stemi_high_risk": stemi_high_risk, "arrest_or_airway": arrest_or_airway,
        "weight": [C.ACUITY_WEIGHT[c] for c in cls],
        "response_min": response, "scene_min": scene,
    })

    # busy-ness proxy: ambulances committed per period / fleet (uses closest-hospital times)
    P = 1440 // C.SIM["period_min"] + 8          # a few spill-over periods after midnight
    busy = np.zeros(P)
    end = depart + tau.min(axis=1) + C.SIM["handover_min"] + 15.0
    for a, b in zip(call, end):
        p0, p1 = int(a // C.SIM["period_min"]), int(min(b, P * C.SIM["period_min"] - 1) // C.SIM["period_min"])
        busy[p0:p1 + 1] += 1
    busy /= C.SIM["ambulance_fleet"]
    return DayInstance(day=day, patients=pts, tau=tau, busy=busy)
