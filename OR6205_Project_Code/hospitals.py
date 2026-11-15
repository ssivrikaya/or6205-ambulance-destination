"""
hospitals.py - the destination set J.

The synthetic network below is FICTIONAL ("Hospital A", ...). It mimics the structure of a
dense metro area (many EDs in the core, a few outer hospitals, one satellite emergency
facility) so the pipeline can run end to end.

For the real study, fill data/hospitals_template.csv with Metro Boston EDs and satellite
emergency facilities, using:
  trauma levels      -> MDPH trauma center designations (ACS verification if out of state)
  stroke_designated  -> DPH stroke designations under 105 CMR 130 (2025 revision)
  evt                -> DPH "endovascular capable" (thrombectomy-capable or comprehensive)
  pci                -> 24/7 primary PCI capability
  ld / ob_night      -> licensed obstetrics; obstetric coverage overnight
  peds / burn / sane -> licensed pediatrics, burn unit, DPH SANE sites
  capacities         -> CMS Care Compare ED volumes, MA CHIA hospital profiles
Coordinates: use lat/lon and an OSRM travel-time matrix (see instance.py) instead of x/y km.
"""
import os
import numpy as np
import pandas as pd

COLUMNS = ["id", "name", "x_km", "y_km", "kind", "trauma_adult", "trauma_peds", "pci",
           "stroke_designated", "evt", "ct_24_7", "ld", "ob_night", "peds", "burn", "sane",
           "safety_net", "offload_per_hour", "ed_capacity_per_hour", "walkin_per_hour"]


def synthetic_hospitals(region_km: float, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = region_km / 2.0
    rows = []
    # (name, radius from center, trauma_adult, trauma_peds, pci, stroke_des, evt, ld, ob_night,
    #  peds, burn, sane, safety_net, offload/h, ED cap/h, walk-in/h, kind)
    spec = [
        ("Hospital A", 1.0, 1, 0, 1, 1, 1, 1, 1, 0, 1, 1, 0, 9, 16, 9, "ED"),
        ("Hospital B", 1.5, 1, 0, 1, 1, 1, 1, 1, 0, 0, 1, 0, 8, 15, 9, "ED"),
        ("Hospital C", 2.0, 1, 1, 0, 1, 0, 0, 0, 1, 0, 1, 0, 6, 10, 6, "ED"),   # pediatric
        ("Hospital D", 2.5, 1, 0, 1, 1, 1, 1, 1, 0, 1, 1, 1, 8, 15, 10, "ED"),  # safety-net
        ("Hospital E", 3.5, 2, 0, 1, 1, 1, 1, 1, 0, 0, 0, 0, 6, 11, 7, "ED"),
        ("Hospital F", 4.0, 0, 0, 1, 1, 0, 1, 0, 0, 0, 0, 1, 5, 9, 6, "ED"),
        ("Hospital G", 5.0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 1, 0, 4, 8, 5, "ED"),
        ("Hospital H", 5.5, 2, 0, 1, 1, 1, 0, 0, 1, 0, 0, 0, 5, 9, 6, "ED"),
        ("Hospital I", 6.0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 1, 4, 7, 5, "ED"),
        ("Hospital J", 6.5, 0, 0, 1, 1, 0, 1, 1, 0, 0, 0, 0, 4, 8, 5, "ED"),
        ("Hospital K", 9.0, 3, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 4, 7, 4, "ED"),
        ("Hospital L", 10.0, 0, 0, 1, 1, 0, 1, 1, 1, 0, 1, 0, 4, 8, 4, "ED"),
        ("Hospital M", 10.5, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 3, 6, 3, "ED"),
        ("Satellite N", 8.0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 2, 4, 2, "SEF"),
    ]
    for k, s in enumerate(spec):
        ang = rng.uniform(0, 2 * np.pi)
        x, y = c + s[1] * np.cos(ang), c + s[1] * np.sin(ang)
        rows.append({
            "id": k, "name": s[0], "x_km": round(x, 3), "y_km": round(y, 3), "kind": s[16],
            "trauma_adult": s[2], "trauma_peds": s[3], "pci": s[4], "stroke_designated": s[5],
            "evt": s[6], "ct_24_7": 1, "ld": s[7], "ob_night": s[8], "peds": s[9], "burn": s[10],
            "sane": s[11], "safety_net": s[12], "offload_per_hour": s[13],
            "ed_capacity_per_hour": s[14], "walkin_per_hour": s[15],
        })
    return pd.DataFrame(rows, columns=COLUMNS)


def load_hospitals(path: str | None, region_km: float) -> pd.DataFrame:
    """Load a filled-in hospital CSV, or fall back to the synthetic network."""
    if path and os.path.exists(path):
        df = pd.read_csv(path)
        missing = set(COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(f"hospital file is missing columns: {sorted(missing)}")
        return df.reset_index(drop=True)
    return synthetic_hospitals(region_km)


def write_template(path: str) -> None:
    pd.DataFrame(columns=COLUMNS).to_csv(path, index=False)
