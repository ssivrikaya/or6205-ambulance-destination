"""
protocol.py - the "protocol compiler".

Turns the Massachusetts DPH point-of-entry (POE) plans into, for every patient i:
  * A_i      : the set of hospitals the protocols allow (admissible arcs)
  * P0(i)    : the destination today's practice would choose (nearest eligible) -> baseline
  * per-arc data the optimization model needs (time to definitive care, arrival period, flags)

Plans encoded (files in the project folder):
  General POE  (eff. 12/2/2022)  - unstable -> closest; stable bypass only for a clinical reason
                                   within +20 min; <10-min hospitals count as equal distance;
                                   bypass only if EMS resources can absorb the extra time.
  Stroke S-PEP (rev. 1/7/2026)   - <4 h onset-to-arrival -> nearest designated stroke hospital/SEF;
                                   FAST-ED >= 6 and 4-24 h -> nearest EVT hospital if <= +30 min.
  STEMI POE                      - arrest/airway/BLS/ALS-I -> closest; high-risk -> PCI hospital;
                                   otherwise PCI hospital if transport-time difference < 30 min.
  Trauma POE  (rev. 9/9/2024)    - red -> highest-level trauma center within regional limits;
                                   yellow -> a trauma center (peds trauma center for children).

Interpretation choices are parameters in config.PROTOCOL, so they are explicit and testable.
Every place where the plan text is ambiguous is marked "INTERPRETATION" - state each one in your paper.
"""
import numpy as np
import pandas as pd

import config as C
from instance import planar_travel_time


def _hh_matrix(h: pd.DataFrame) -> np.ndarray:
    """Hospital-to-hospital travel times (off-peak) for secondary transfers."""
    H = len(h)
    m = np.zeros((H, H))
    for j in range(H):
        m[j] = planar_travel_time(h.x_km.values, h.y_km.values, h.x_km[j], h.y_km[j], np.full(H, 3 * 60))
        m[j, j] = 0.0
    return m


def _night(minute: float) -> bool:
    hr = int(minute // 60) % 24
    return hr >= 19 or hr < 7


class ProtocolCompiler:
    def __init__(self, hospitals: pd.DataFrame, protocol: dict | None = None, scenario: dict | None = None):
        self.h = hospitals
        self.P = dict(C.PROTOCOL, **(protocol or {}))
        self.S = dict(C.SCENARIO, **(scenario or {}))
        self.hh = _hh_matrix(hospitals)
        self.open = np.array([j not in set(self.S["code_black"]) for j in range(len(hospitals))])

    # ---------- capability helpers ----------
    def _set(self, mask) -> np.ndarray:
        return np.where(np.asarray(mask) & self.open)[0]

    def _nearest(self, tau_i, cand):
        cand = np.asarray(cand)
        return int(cand[np.argmin(tau_i[cand])]) if len(cand) else None

    def _ties(self, tau_i, cand, tol):
        cand = np.asarray(cand)
        if not len(cand):
            return []
        best = tau_i[cand].min()
        return [int(j) for j in cand if tau_i[j] <= best + tol]

    def _nearest_with(self, j, mask):
        """Nearest hospital (from hospital j) that satisfies mask - for secondary transfers."""
        cand = self._set(mask)
        if not len(cand):
            return None, np.inf
        k = int(cand[np.argmin(self.hh[j, cand])])
        return k, self.hh[j, k]

    # ---------- door-to-definitive-care, including secondary transfer when j is not definitive ----------
    def door_to_definitive(self, row, j, arrival_min) -> float:
        h, D = self.h, C.DOOR_TO_TREAT
        c = row.cls
        if c == "stemi":
            if h.pci[j]:
                return D["stemi_pci"]
            k, t = self._nearest_with(j, h.pci == 1)
            return D["interfacility_setup"] + t + 30.0          # PLACEHOLDER: door-to-device after transfer
        if c == "stroke":
            onset_at_arrival = row.onset_elapsed_at_call + (arrival_min - row.call_min)
            lvo = row.fasted >= self.P["stroke_fasted_cutoff"]
            if lvo and onset_at_arrival <= self.P["stroke_window_long"]:
                if h.evt[j]:
                    return D["stroke_groin"]
                k, t = self._nearest_with(j, h.evt == 1)
                return D["stroke_needle"] + D["interfacility_setup"] + t + 45.0   # drip-and-ship (PLACEHOLDER)
            if onset_at_arrival <= 270:                          # tPA window (4.5 h) - clinical assumption
                return D["stroke_needle"] if h.stroke_designated[j] else D["stroke_needle"] + 30.0
            return D["default"]
        if c in ("trauma_red", "trauma_yellow"):
            lvl = h.trauma_adult[j]
            base = D["trauma_or"] if (lvl in (1, 2) or (row.child and h.trauma_peds[j])) else \
                   D["trauma_or"] + 20.0 if lvl == 3 else D["trauma_nontc"]
            if row.child and not h.trauma_peds[j] and lvl in (1, 2, 3):
                base += 20.0                                     # PLACEHOLDER: child at adult center
            return base
        if c == "ob_labor":
            ok = h.ld[j] and (h.ob_night[j] or not _night(arrival_min))
            if ok:
                return D["default"]
            k, t = self._nearest_with(j, (h.ld == 1) & ((h.ob_night == 1) | (not _night(arrival_min))))
            return D["default"] + D["interfacility_setup"] + t
        if c == "burn":
            if h.burn[j]:
                return D["default"]
            k, t = self._nearest_with(j, h.burn == 1)
            return D["default"] + D["interfacility_setup"] + t
        if c == "peds_medical":
            return D["default"] if h.peds[j] else D["default"] + 15.0   # PLACEHOLDER
        if c == "sane":
            if h.sane[j]:
                return D["default"]
            k, t = self._nearest_with(j, h.sane == 1)
            return D["default"] + D["interfacility_setup"] + t
        return D["default"]

    # ---------- the four plans ----------
    def _stroke(self, row, tau_i, closest):
        h, P = self.h, self.P
        elapsed = row.onset_elapsed_at_call + (row.depart_min - row.call_min)
        arr = elapsed + tau_i                                    # onset-to-arrival, per hospital (arc-specific!)
        if np.nanmin(arr) > P["stroke_window_long"]:
            return None                                          # beyond 24 h -> general POE applies
        designated = self._set((h.stroke_designated == 1) & (h.ct_24_7 == 1))   # CT unavailable -> next nearest
        nd = self._nearest(tau_i, designated)
        if row.unstable:
            # S-PEP: unstable/airway/hypoglycemia -> nearest receiving hospital "may be more appropriate"
            A = sorted({closest, nd} - {None})
            return "stroke_unstable", A, closest
        if nd is not None and arr[nd] < P["stroke_window_short"]:
            A = [j for j in self._ties(tau_i, designated, P["stroke_tie_tolerance"]) if arr[j] < P["stroke_window_short"]] or [nd]
            return "stroke_<4h", A, nd
        if row.fasted >= P["stroke_fasted_cutoff"] and arr.min() <= P["stroke_window_long"]:
            evt = self._set(h.evt == 1)
            ne = self._nearest(tau_i, evt)
            if ne is not None and nd is not None and tau_i[ne] - tau_i[nd] <= P["stroke_evt_extra_band"]:
                return "stroke_4-24h_EVT", self._ties(tau_i, evt, P["stroke_tie_tolerance"]), ne
            return "stroke_4-24h_noEVT", self._ties(tau_i, designated, P["stroke_tie_tolerance"]), nd
        # INTERPRETATION: FAST-ED < 6 in the 4-24 h window is not addressed by the S-PEP text;
        # we send these patients to the nearest designated stroke hospital.
        return "stroke_4-24h_lowFASTED", self._ties(tau_i, designated, P["stroke_tie_tolerance"]), nd

    def _stemi(self, row, tau_i, closest):
        h, P = self.h, self.P
        if row.arrest_or_airway or row.crew != "PARAMEDIC":
            return "stemi_closest_rule", [closest], closest
        pci = self._set(h.pci == 1)
        npci = self._nearest(tau_i, pci)
        if npci is None:
            return "stemi_noPCI", [closest], closest
        # INTERPRETATION: with several PCI hospitals the plan says use history/relationships;
        # we admit every PCI hospital within the 30-min difference band.
        within = [int(j) for j in pci if tau_i[j] - tau_i[closest] < P["stemi_pci_extra_band"]]
        if row.stemi_high_risk:
            A = sorted(set(within) | {npci})
            return "stemi_high_risk", A, npci
        if tau_i[npci] - tau_i[closest] < P["stemi_pci_extra_band"]:
            return "stemi_PCI", sorted(set(within) | {npci}), npci
        return "stemi_closest", [closest], closest

    def _trauma(self, row, tau_i, closest):
        h, P = self.h, self.P
        red = row.cls == "trauma_red"
        tmax = P["trauma_red_max_time"] if red else P["trauma_yellow_max_time"]
        reach = tau_i <= tmax
        if row.child:
            peds = self._set((h.trauma_peds == 1) & reach)
            if len(peds):
                return ("trauma_red_peds" if red else "trauma_yellow_peds"), [int(j) for j in peds], self._nearest(tau_i, peds)
        if red:
            for lvl in (1, 2, 3):                                # highest level available within limits
                cand = self._set((h.trauma_adult == lvl) & reach)
                if len(cand):
                    return f"trauma_red_L{lvl}", [int(j) for j in cand], self._nearest(tau_i, cand)
        else:
            cand = self._set((h.trauma_adult > 0) & reach)
            if len(cand):
                return "trauma_yellow_TC", [int(j) for j in cand], self._nearest(tau_i, cand)
        return "trauma_no_TC_in_reach", [closest], closest

    def _general(self, row, tau_i, closest, busy_now):
        h, P = self.h, self.P
        if row.unstable:
            return "general_unstable", [closest], closest, set()
        night = _night(row.depart_min + tau_i[closest])
        # clinical reasons that justify a bypass (general POE factor 1)
        reasons = set()
        if row.continuity >= 0 and self.open[row.continuity]:
            reasons.add(int(row.continuity))
        spec = {"ob_labor": (h.ld == 1) & ((h.ob_night == 1) | (not night)),
                "burn": h.burn == 1, "sane": h.sane == 1,
                "peds_medical": h.peds == 1}.get(row.cls)
        if spec is not None:
            reasons |= set(int(j) for j in self._set(spec))
        eq = P["general_equal_distance"]

        def extra(j):  # INTERPRETATION of the 10-minute clause (reading A and B share this)
            if tau_i[j] < eq and tau_i[closest] < eq:
                return 0.0
            return tau_i[j] - tau_i[closest]

        A, olmc = {closest}, set()
        if busy_now <= self.S["ems_busy_threshold"]:            # factor: EMS resources can absorb extra time
            for j in reasons:
                if extra(j) <= P["general_extra_time_band"]:
                    A.add(j)
                elif P["allow_olmc_beyond_band"]:
                    A.add(j); olmc.add(j)
            if P["ten_minute_reading"] == "B":
                A |= set(int(j) for j in self._set(tau_i < eq))
        # baseline P0: what EMTs typically do
        p0 = closest
        if self.S["p0_honor_continuity"] and row.continuity in A and row.continuity not in olmc:
            p0 = int(row.continuity)
        elif spec is not None:
            sp = [j for j in A if j in reasons and j != row.continuity]
            if sp:
                p0 = min(sp, key=lambda j: tau_i[j])
        return ("general_stable" if len(A) > 1 else "general_stable_closest"), sorted(A), p0, olmc

    # ---------- main entry ----------
    def compile_day(self, inst):
        pts, tau, busy = inst.patients, inst.tau, inst.busy
        Pm = C.SIM["period_min"]
        arcs, plans = [], []
        open_idx = np.where(self.open)[0]
        for r in pts.itertuples(index=False):
            tau_i = tau[r.pid].copy()
            tau_i[~self.open] = np.inf
            closest = int(open_idx[np.argmin(tau_i[open_idx])])
            busy_now = busy[min(int(r.depart_min // Pm), len(busy) - 1)]
            olmc = set()
            res = None
            if r.cls == "stroke":
                res = self._stroke(r, tau_i, closest)
            elif r.cls == "stemi":
                res = self._stemi(r, tau_i, closest)
            elif r.cls in ("trauma_red", "trauma_yellow"):
                res = self._trauma(r, tau_i, closest)
            if res is None:
                plan, A, p0, olmc = self._general(r, tau_i, closest, busy_now)
            else:
                plan, A, p0 = res
            A = [j for j in A if j is not None and self.open[j]] or [closest]
            if p0 not in A:
                p0 = min(A, key=lambda j: tau_i[j])
            plans.append((r.pid, plan, closest, p0, len(A)))
            for j in A:
                arr = r.depart_min + tau_i[j]
                d2t = self.door_to_definitive(r, j, arr)
                arcs.append({
                    "pid": r.pid, "hosp": int(j), "plan": plan,
                    "tau": tau_i[j], "arrival_min": arr, "period": int(arr // Pm),
                    # time from 911 call to definitive care, EXCLUDING any offload queue wait
                    "T_no_wait": (r.depart_min - r.call_min) + tau_i[j] + C.SIM["handover_min"] + d2t,
                    "weight": r.weight, "cls": r.cls, "group": r.group,
                    "is_closest": int(j == closest), "is_p0": int(j == p0),
                    "deviation": int(j != closest), "olmc": int(j in olmc),
                    "is_continuity": int(j == r.continuity),
                    "has_continuity_option": int(r.continuity in A),
                })
        arcs = pd.DataFrame(arcs)
        plans = pd.DataFrame(plans, columns=["pid", "plan", "closest", "p0", "n_admissible"])
        return arcs, plans
