# Optimizing Within the Protocol — computational package

Working title: *Optimizing Within the Protocol: Multi-Objective Ambulance Destination Assignment under Massachusetts' Point-of-Entry Rules and Diversion Ban*. Target venue: 12th North American IEOM Conference, Boston, June 1–3, 2027 (submission deadline March 1, 2027).

## What is in this package

- a synthetic patient-day generator and a fictional hospital network;
- the **protocol compiler**, which encodes the four Massachusetts DPH point-of-entry (POE) plans;
- the **multi-objective MILP** (`MODEL_FORMULASYONU.md`), implemented twice on the same data:
  `model_gurobi.py` (algebraic gurobipy) and `model_highs.py` (matrix form, open-source HiGHS);
- `verify_model.py`: brute-force enumeration vs. solver, objective recomputation, and a
  Gurobi-vs-HiGHS cross-check when gurobipy is installed;
- the protocol baseline P0, a rolling-horizon driver, one common evaluator, scenario presets,
  Pareto (epsilon-constraint) and shadow-price experiments, 95% CIs, and figures.

The model formulation was produced with AI assistance with the instructor's permission. Disclose this in the paper per IEOM's Publication Ethics statement.

**All results are from synthetic, uncalibrated data.** Replace every `PLACEHOLDER` in `config.py` and the synthetic hospitals before reporting findings.

## Setup

Use the `OR6205` Anaconda environment from your professor's guide.

```
pip install gurobipy numpy pandas matplotlib scipy
python verify_model.py                    # correctness tests (+ Gurobi vs HiGHS if gurobipy is installed)
python tiny_instance.py                   # 6-patient instance for the paper's verification section
```

`config.MODEL["solver"] = "auto"` uses Gurobi when gurobipy is installed, otherwise HiGHS.

```
python run_experiments.py --days 30 --policies P0,RH,FI                       # E1
python run_experiments.py --days 30 --policies P0,FI --eps-grid 1,0.75,0.5,0.25,0   # E2 Pareto
python run_experiments.py --days 30 --scenarios base,reading_B,band10,band30,stemi_band20,stemi_band40,stroke_band15,stroke_band45   # E3
python run_experiments.py --days 30 --scenarios surge,code_black_A,busy_strict  # E4
python run_experiments.py --compare --scenarios base,reading_B,band10,band30,stemi_band20,stemi_band40,stroke_band15,stroke_band45,code_black_A,surge,busy_strict
```

```
python run_experiments.py --days 30 --policies P0,FI --duals              # E5 shadow prices
```

Outputs are written to `results/<scenario>/`:

| File | Contents |
|---|---|
| `metrics_by_day.csv` | Metrics for each policy and day |
| `summary_95ci.csv` | Summary with 95% confidence intervals |
| `protocol_flexibility.csv` | Share of patients the POE plans give more than one legal destination |
| `key_metrics.png` | Key metrics by policy |
| `pareto.csv`, `pareto_mean.csv`, `pareto.png` | Pareto frontier (E2) |
| `shadow_prices_hosp_hour.csv`, `shadow_prices.png` | Value of +1 offload slot by hospital and hour (E5) |
| `settings.json` | Exact parameters used, for reproducibility |

## Files

| File | Role |
|---|---|
| `config.py` | Every threshold, scenario switch, and placeholder |
| `hospitals.py` | Destination set J (fictional network); `data/hospitals_template.csv` for real data |
| `instance.py` | One day of transports (set I) and travel times |
| `protocol.py` | POE plans → admissible arcs A_i, baseline P0, arc data |
| `evaluate.py` | Feasibility check, FIFO offload queue, crowding cost, metrics |
| `MODEL_FORMULASYONU.md` | Full mathematical formulation (Turkish), numbered like the code |
| `formulation.py` | Index sets and parameters shared by both solver backends; independent objective recomputation |
| `model_gurobi.py` | The MILP in gurobipy |
| `model_highs.py` | The same MILP for HiGHS (scipy), used for verification and as a fallback |
| `model.py` | Entry point; picks the solver backend |
| `verify_model.py` | Correctness tests |
| `run_experiments.py` | Experiments E1–E5 |
| `tiny_instance.py` | Verification instance |

## How the POE plans are encoded

| Plan (file in project folder) | Rule | Code |
|---|---|---|
| General POE, eff. 12/2/2022 | Unstable patient → closest ED | `_general` |
| General POE | Stable patient may bypass only for a clinical reason (continuity of care; licensed OB, burn, or pediatrics; SANE site) if extra time ≤ 20 min | `_general` |
| General POE | Hospitals under 10 min count as equal distance | `_general.extra` |
| General POE | Bypass only if EMS resources can absorb the extra transport time | busy-ness proxy, `ems_busy_threshold` |
| Stroke S-PEP, rev. 1/7/2026 | Onset-to-arrival < 4 h → nearest designated stroke hospital or SEF | `_stroke` (checked arc by arc) |
| Stroke S-PEP | FAST-ED ≥ 6 and 4–24 h → nearest EVT hospital if ≤ +30 min; CT unavailable → next nearest; unstable → nearest | `_stroke` |
| STEMI POE | Arrest, compromised airway, or BLS/ALS-I crew → closest | `_stemi` |
| STEMI POE | High-risk features → PCI hospital; otherwise PCI hospital if transport-time difference < 30 min | `_stemi` |
| Trauma POE, rev. 9/9/2024 | Red criteria → highest-level trauma center within regional limits | `_trauma` |
| Trauma POE | Yellow criteria → any trauma center; children → pediatric trauma center | `_trauma` |
| Code black (diversion ban) | Closed hospital removed from every set | `ProtocolCompiler.open` |

### Interpretations to state explicitly in your paper

Each is a parameter or a marked `INTERPRETATION` comment in the code.

1. **The 10-minute clause.** Reading A: it only changes how extra time is measured. Reading B: every hospital under 10 min is interchangeable with the closest. Set with `ten_minute_reading`; test both.
2. **STEMI branch order.** The text copy lost its flowchart arrows. Verify the branch order against the original PDF and obtain footnotes 2–5.
3. **Several PCI hospitals.** The plan says to use history and established relationships. The code admits every PCI hospital within the 30-min band.
4. **Stroke, FAST-ED < 6 in the 4–24 h window.** The plan text doesn't address this case. The code sends these patients to the nearest designated stroke hospital.
5. **"DPH-designated stroke care hospital."** Confirm which 105 CMR 130 tiers count as designated (`stroke_designated` column).
6. **Trauma regional limits.** These come from the **Region IV Regional POE Plan**, which you still need to obtain (`trauma_red_max_time`, `trauma_yellow_max_time`).
7. **The EMS-resources condition.** The plan states it qualitatively; the code operationalizes it with a busy-ness proxy and a threshold. In the base synthetic run the proxy never exceeds 0.85; `busy_strict` tests a binding case.
8. **Out of scope:** air ambulance routing and ambulance dispatch. The model decides destinations only.

## Placeholders to calibrate before reporting results

| Parameter | Suggested source | Sanity target |
|---|---|---|
| Hospitals and capabilities | DPH designation lists, MDPH trauma list, hospital sites | Real Metro Boston EDs and satellite emergency facilities |
| Travel times | OSRM / OpenStreetMap matrix by hour (run locally) | Replaces the planar model |
| Transports per day, hourly profile, class mix, stability share | NEMSIS public-release research data; Boston EMS reports | Cite each figure |
| Door-to-treatment times | Published registries (Get With The Guidelines, Mission: Lifeline) | STEMI: about half of EMS-direct patients meet the 90-min goal (Mission: Lifeline Accelerator, PMC4975540) |
| Offload rates | Hospital throughput (CMS Care Compare, MA CHIA) | Compare with California's 30-min / 90% offload standard |
| Crowding-cost breakpoints and slopes | ED boarding-cost literature | Justify the convex shape |
| Acuity weights | Sensitivity analysis (for example ±50%) | Report robustness |

## Experiments and paper skeleton (IEOM template)

| Paper section | What goes in it | Comes from |
|---|---|---|
| 1. Introduction | Diversion bans spreading (MA 2009; Indiana third state, Sept 2026); research questions RQ1–RQ3 | Your writing |
| 2. Literature review | Comparison table: Acuna 2020, Drabecki 2023, Baek 2020, Fu 2025, Hanchate 2022, Li review | Your writing; run a Scopus search first |
| 3. Regulatory context | EMTALA, diversion ban, the four POE plans | Earlier notes plus the plan files |
| 4. Model | Formulation, exactness of the linearizations, verification | `MODEL_FORMULASYONU.md`, `verify_model.py`, `tiny_instance.py` |
| 5. Case study and data | Calibration table, protocol encoding table, interpretations | This README, `settings.json` |
| 6.1 Protocol flexibility | How much legal choice exists | `protocol_flexibility.csv` |
| 6.2 E1: value of coordination | P0 vs. RH vs. FI | `summary_95ci.csv`, `key_metrics.png` |
| 6.3 E2: EMS–hospital trade-off | Pareto frontier | `pareto.png` |
| 6.4 E3/E4: policy thresholds and stress tests | Scenario comparisons | Scenario folders |
| 6.5 E5: where capacity helps | Shadow prices of offload capacity | `shadow_prices.png` |
| 7. Discussion and policy implications | | Your writing |
| 8. Limitations and future work | Synthetic calibration; deterministic queue; no dispatch; regional trauma plan; Turkey vs. US regime comparison | Your writing |

Disclose AI assistance per the IEOM Publication Ethics statement and Northeastern's academic integrity policy.
