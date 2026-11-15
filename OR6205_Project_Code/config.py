"""
config.py - every tunable number in one place.

Three kinds of parameters live here:
  (1) PROTOCOL thresholds, taken from the Massachusetts DPH point-of-entry (POE) plans.
      These are the policy levers for the sensitivity experiments.
  (2) SCENARIO switches (code black, surge, interpretation choices).
  (3) PLACEHOLDER calibration values. Every one is marked "PLACEHOLDER".
      They are NOT data. Replace them with calibrated values (NEMSIS, CMS Care Compare,
      MA CHIA, Boston EMS reports) and cite the source in your paper.
"""

# ---------------------------------------------------------------------------
# (1) PROTOCOL THRESHOLDS  (source: MA DPH POE plans in your project folder)
# ---------------------------------------------------------------------------
PROTOCOL = {
    # General POE (eff. Dec 2, 2022)
    "general_extra_time_band": 20.0,   # min: max extra transport time for a clinically justified bypass
    "general_equal_distance": 10.0,    # min: hospitals closer than this count as "equal transport distance"
    # Interpretation of the 10-minute clause (state your choice in the paper; test both):
    #   "A" = it only changes how extra time is measured (closest-equivalent set used as the reference)
    #   "B" = every hospital under 10 min is interchangeable with the closest for stable patients
    "ten_minute_reading": "A",
    "allow_olmc_beyond_band": False,   # allow >20-min bypass arcs (needs on-line medical control approval)

    # Stroke POE (S-PEP, rev. Jan 7, 2026)
    "stroke_window_short": 240.0,      # min: onset-to-arrival < 4 h -> nearest designated stroke hospital/SEF
    "stroke_window_long": 1440.0,      # min: 4-24 h window
    "stroke_fasted_cutoff": 6,         # FAST-ED >= 6 -> endovascular-capable (EVT) hospital in 4-24 h window
    "stroke_evt_extra_band": 30.0,     # min: max additional travel time to reach the EVT hospital
    "stroke_tie_tolerance": 0.0,       # min: treat hospitals within this of "nearest" as ties (OLMC discretion)

    # STEMI POE (paramedic-level algorithm)
    # NOTE: the text copy of the flowchart lost its arrows; verify branch order against the original PDF.
    "stemi_pci_extra_band": 30.0,      # min: PCI hospital if transport-time difference vs closest < 30

    # Trauma POE (rev. Sep 9, 2024) -- regional geographic constraint is set by the Region IV
    # Regional POE plan, which is NOT in the project folder. PLACEHOLDER until you obtain it.
    "trauma_red_max_time": 30.0,       # PLACEHOLDER min
    "trauma_yellow_max_time": 30.0,    # PLACEHOLDER min
}

# ---------------------------------------------------------------------------
# (2) SCENARIO SWITCHES
# ---------------------------------------------------------------------------
SCENARIO = {
    "name": "base",
    "code_black": [],            # list of hospital ids closed by "code black" (internal disaster)
    "demand_multiplier": 1.0,    # e.g. 1.2 for a winter surge stress test
    "ems_busy_threshold": 0.85,  # if system busy-ness proxy > this in a period, bypass arcs are disabled
                                 # (general POE: EMS resources must be able to absorb extra transport time)
    "p0_honor_continuity": True, # baseline: EMTs honor continuity-of-care bypasses when allowed
}

# ---------------------------------------------------------------------------
# (3) PLACEHOLDER CALIBRATION VALUES
# ---------------------------------------------------------------------------
SIM = {
    "seed": 2027,
    "n_days": 30,
    "region_km": 24.0,              # synthetic square service region (replace with real geography)
    "period_min": 15,               # length of a model time period (minutes)
    "transports_per_day": 420,      # PLACEHOLDER: calibrate from Boston EMS / MATRIS / NEMSIS
    "response_min": (6, 12),        # PLACEHOLDER: dispatch-to-scene (uniform range)
    "scene_min": (12, 22),          # PLACEHOLDER: on-scene time
    "handover_min": 10.0,           # PLACEHOLDER: offload time with no queue
    "circuity": 1.3,                # road distance / straight-line distance
    "speed_kmh_offpeak": 40.0,      # PLACEHOLDER
    "speed_kmh_peak": 26.0,         # PLACEHOLDER
    "peak_hours": [7, 8, 9, 16, 17, 18],
    "ambulance_fleet": 55,          # PLACEHOLDER: used only for the busy-ness proxy
}

# Hourly call-volume profile (relative weights, 24 values) - PLACEHOLDER shape
HOURLY_PROFILE = [0.55, 0.45, 0.40, 0.38, 0.40, 0.50, 0.70, 0.95, 1.10, 1.20, 1.25, 1.25,
                  1.25, 1.22, 1.20, 1.20, 1.20, 1.18, 1.15, 1.10, 1.00, 0.90, 0.78, 0.65]

# Clinical class mix - PLACEHOLDER proportions (calibrate from NEMSIS public-release data)
CLASS_MIX = {
    "general_low": 0.42, "general_high": 0.24, "peds_medical": 0.07,
    "stroke": 0.045, "stemi": 0.02, "trauma_red": 0.02, "trauma_yellow": 0.07,
    "ob_labor": 0.02, "burn": 0.005, "sane": 0.005, "behavioral": 0.075,
}

# Acuity weights used in the objective/metrics - PLACEHOLDER (justify in paper, test sensitivity)
ACUITY_WEIGHT = {
    "general_low": 1, "general_high": 3, "peds_medical": 3, "behavioral": 2,
    "stroke": 8, "stemi": 8, "trauma_red": 10, "trauma_yellow": 5,
    "ob_labor": 5, "burn": 6, "sane": 3,
}

# Probability a patient is unstable, by class - PLACEHOLDER
P_UNSTABLE = {
    "general_low": 0.02, "general_high": 0.20, "peds_medical": 0.08, "behavioral": 0.05,
    "stroke": 0.12, "stemi": 0.15, "trauma_red": 0.60, "trauma_yellow": 0.10,
    "ob_labor": 0.08, "burn": 0.30, "sane": 0.02,
}

P_CONTINUITY = 0.35        # PLACEHOLDER: share of stable general patients with a continuity-of-care hospital
P_PARAMEDIC_CREW = 0.65    # PLACEHOLDER: share of transports at ALS-Paramedic level (rest BLS / ALS-I)
P_GROUP_B_CORE = 0.55      # PLACEHOLDER: share of demographic group B in the dense core (equity metric)
P_GROUP_B_OUTER = 0.20

# Door-to-definitive-treatment times (minutes) - PLACEHOLDER
DOOR_TO_TREAT = {
    "stemi_pci": 45.0,          # door-to-device at a PCI hospital (with prehospital cath-lab activation)
    "stemi_lytics": 30.0,       # door-to-needle at a non-PCI hospital (lytic pathway)
    "stroke_needle": 45.0,      # door-to-needle (tPA) at a stroke-designated hospital
    "stroke_groin": 90.0,       # door-to-groin (thrombectomy) at an EVT hospital
    "interfacility_setup": 45.0,# time to arrange a secondary transfer
    "trauma_or": 40.0,          # door-to-definitive trauma care at a trauma center
    "trauma_nontc": 120.0,      # stabilize + transfer penalty at a non-trauma center
    "default": 30.0,            # door-to-provider for everyone else
}

# Piecewise-linear convex ED crowding cost (hospital objective).
# Breakpoints are utilization levels of hourly ED load / ED hourly capacity; slopes are cost per patient.
# PLACEHOLDER shape - justify from boarding-cost literature.
CROWDING_BREAKPOINTS = [0.0, 0.85, 1.00, 1.20]
CROWDING_SLOPES      = [0.0, 1.0, 3.0, 10.0]

# ---------------------------------------------------------------------------
# (4) OPTIMIZATION MODEL SETTINGS (see MODEL_FORMULASYONU.md)
# ---------------------------------------------------------------------------
MODEL = {
    "solver": "auto",          # "gurobi", "highs", or "auto" (Gurobi if gurobipy is installed)
    "wall_weight": None,       # lambda: weight of one minute of ambulance wall time in f1;
                               # None -> mean acuity weight of the patients in the instance
    "continuity_value": 20.0,  # PLACEHOLDER pi: value of honoring continuity of care, in equivalent
                               # minutes (multiplied by the patient's acuity weight)
    "tie_break": 1e-4,         # weight of the secondary objective (lexicographic tie-breaking)
    "drain_periods": 16,       # extra periods after the last arrival so every queue can empty
    "mip_gap": 1e-4,
    "equity_delta": None,      # minutes; if set, |mean T(group B) - mean T(group A)| <= delta
}
