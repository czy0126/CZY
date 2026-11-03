"""Consolidate the per-SR-device fault evidence into one protection/SOA table.

The D4 deliverable asks for one 48 V/50 V table of ``Vgs``/``Vds``/``Id``,
reverse current and I2t.  Today that evidence is split across three probe
records and seven candidate-comparison records, and no single file answers
"which device saw the worst stress".

This tool adds **no new raw data**.  Every number is copied from a committed
record, and the copy is what the committed JSON contains.  Two different
windows are involved and are labelled rather than merged:

* ``sr_fault_probe_*.json`` reports post-trip statistics only.
* ``protection_candidate_*.json`` reports the whole saved window.

There is no vendor SOA curve in this repository, so the output is a screening
list, not a pass/fail.  The reverse-current column is a port measurement; it
must not be split into body-diode and channel components from ``Vgs`` (that
claim was withdrawn in the second review).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "design/v3/power_priority/protection_soa_table.json"

PROBE_FIELDS = {
    "gate_end_v": "gate_end_v",
    "gate_peak_v": "gate_post_peak_v",
    "gate_last_rise_us": "gate_last_rise_us",
    "gate_high_at_end": "gate_high_at_end",
    "drain_end_v": "vds_end_v",
    "drain_min_v": "vds_min_post_v",
    "drain_max_v": "vds_max_post_v",
    "forward_peak_a": "i_forward_peak_post_a",
    "reverse_peak_a": "i_reverse_peak_post_a",
    "forward_i2t_a2s": "i2t_forward_post_a2s",
    "abs_i2t_a2s": "i2t_abs_post_a2s",
    "i2t_while_gate_high_a2s": "i2t_while_gate_high_a2s",
    "conduction_while_gate_high_a": "conduction_while_gate_high_a",
}

COMPARE_FIELDS = {
    "gate_end_v": "end_v",
    "gate_peak_v": None,
    "gate_last_rise_us": "last_high_us",
    "gate_high_at_end": "high_at_end",
    "drain_end_v": None,
    "drain_min_v": "drain_min_v",
    "drain_max_v": None,
    "forward_peak_a": "forward_peak_a",
    "reverse_peak_a": None,
    "forward_i2t_a2s": "forward_i2t_a2s",
    "abs_i2t_a2s": None,
    "i2t_while_gate_high_a2s": "i2t_while_gate_high_a2s",
    "conduction_while_gate_high_a": None,
}

# Recorded fields that are legitimately null for an individual device.
NULL_BY_DESIGN = {"gate_last_rise_us"}

PROBE_RUNS = {
    "48v_probe_base": {
        "json": "sr_fault_probe_48v_120a.json", "vin": 48.0, "role": "base",
        "window": "post_trip", "solver": "base",
    },
    "48v_probe_cshunt": {
        "json": "sr_fault_probe_48v_120a_cshunt.json", "vin": 48.0, "role": "base",
        "window": "post_trip", "solver": "cshunt=1e-15",
    },
    "50v_probe_cshunt": {
        "json": "sr_fault_probe_50v_120a_cshunt.json", "vin": 50.0, "role": "base",
        "window": "post_trip", "solver": "cshunt=1e-15",
    },
}

# (json, vin, case, solver, comparison_basis).  The basis says which deck the
# candidate was differenced against: the declared parent, or a topology-matched
# control that shares the candidate's pre-fault numerical path.  It matters
# because two records can carry identical device rows and mean different
# things; without it the table cannot say why one 50 V row is causal and the
# other is exploratory.
COMPARE_RUNS = {
    "48v_prot_a": ("protection_candidate_48v_120a_prot_a.json", 48.0, "prot_a_oc1v",
                   "base", "declared_parent"),
    "48v_prot_b": ("protection_candidate_48v_120a_prot_b.json", 48.0, "prot_b_fast10u_1p8v",
                   "base", "declared_parent"),
    "50v_prot_a": ("protection_candidate_50v_120a_prot_a.json", 50.0, "prot_a_oc1v",
                   "cshunt=1e-15", "declared_parent"),
    "50v_prot_b": ("protection_candidate_50v_120a_prot_b.json", 50.0, "prot_b_fast10u_1p8v",
                   "cshunt=1e-15", "declared_parent"),
    # PROT-03: the same two candidates differenced against a threshold-muted
    # control instead of the parent.  Only these rows can attribute a change to
    # the protection, because the control keeps the candidate's pre-fault
    # numerical path; the parent rows above stay as the exploratory record.
    "50v_prot_a_ctrl": ("protection_candidate_50v_120a_prot_a_paired.json", 50.0, "prot_a_oc1v",
                        "cshunt=1e-15", "topology_matched_control"),
    "50v_prot_b_ctrl": ("protection_candidate_50v_120a_prot_b_paired.json", 50.0,
                        "prot_b_fast10u_1p8v", "cshunt=1e-15", "topology_matched_control"),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    # Normalize checkout line endings so a Windows-generated report stays
    # identical on Linux CI; hashes refer to canonical LF JSON text.
    h.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def _row(device: str, src: dict, fields: dict[str, str | None]) -> dict:
    row = {"device": device.lower()}
    for name, key in fields.items():
        row[name] = None if key is None else src.get(key)
    return row


def _sorted_devices(devices: dict) -> list[str]:
    return sorted(devices, key=lambda d: (int(d[:-1]), d[-1]))


def probe_run(name: str, spec: dict) -> dict:
    path = ROOT / "design/v3/power_priority" / spec["json"]
    data = json.loads(path.read_text(encoding="utf-8"))
    res = data["results"]
    devices = res["devices"]
    return {
        "run": name,
        "source_json": spec["json"],
        "source_sha256": sha256(path),
        "vin_v": spec["vin"],
        "role": spec["role"],
        "solver": spec["solver"],
        "window": spec["window"],
        "trip_us": res["trip_s"] * 1e6,
        "reached_declared_window": bool(res["reached_tstop"]),
        "solver_prefix_only": bool(res["solver_prefix_only"]),
        "unrecorded_fields": [],
        "null_by_design_fields": [],
        "devices": [_row(d, devices[d], PROBE_FIELDS) for d in _sorted_devices(devices)],
    }


def compare_runs(name: str, spec: tuple) -> list[dict]:
    filename, vin, case, solver, *rest = spec
    basis = rest[0] if rest else "declared_parent"
    path = ROOT / "design/v3/power_priority" / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    res = data["results"]
    unrecorded = [k for k, v in COMPARE_FIELDS.items() if v is None]
    paired = bool(data["checks"]["the_pre_fault_operating_points_match_within_1_mv"])
    delta_mv = float(res["pre_fault"]["vout_mean_delta_mv"])
    coverage = data["coverage"]
    out = []
    for role, key in (("compare_base", "base"), ("candidate", "candidate")):
        gates = res[key]["gates"]
        out.append({
            "run": f"{name}_{role}",
            "source_json": filename,
            "source_sha256": sha256(path),
            "vin_v": vin,
            "case": case,
            "role": role,
            "solver": solver,
            "comparison_basis": basis,
            "window": "saved_window",
            "trip_us": res["trigger"]["base_trip_us"],
            "reached_declared_window": bool(
                coverage[f"{key}_reached_saved_stop"]),
            "solver_prefix_only": not bool(
                coverage[f"{key}_reached_saved_stop"]),
            "paired_pre_fault": paired,
            "pre_fault_vout_delta_mv": delta_mv,
            "paired_change_can_be_attributed_to_protection": (
                paired and bool(coverage["declared_window_fully_covered"])),
            "unrecorded_fields": unrecorded,
            "null_by_design_fields": sorted(NULL_BY_DESIGN),
            "devices": [_row(d, gates[d], COMPARE_FIELDS) for d in _sorted_devices(gates)],
        })
    return out


def summarize(run: dict) -> dict:
    rows = run["devices"]
    fwd = max(rows, key=lambda r: r["forward_peak_a"])
    rev = [r for r in rows if r["reverse_peak_a"] is not None]
    vds = [r for r in rows if r["drain_min_v"] is not None]
    gate = [r for r in rows if r["gate_end_v"] is not None]
    return {
        "run": run["run"],
        "worst_forward_peak_a": fwd["forward_peak_a"],
        "worst_forward_device": fwd["device"],
        "worst_reverse_peak_a": max((r["reverse_peak_a"] for r in rev), default=None),
        "worst_reverse_device": max(rev, key=lambda r: r["reverse_peak_a"])["device"] if rev else None,
        "min_drain_v": min((r["drain_min_v"] for r in vds), default=None),
        "devices_high_at_end": [r["device"] for r in rows if r["gate_high_at_end"]],
        "max_gate_v": max((r["gate_end_v"] for r in gate), default=None),
    }


def build() -> dict:
    runs = [probe_run(name, spec) for name, spec in PROBE_RUNS.items()]
    for name, spec in COMPARE_RUNS.items():
        runs.extend(compare_runs(name, spec))
    summaries = [summarize(run) for run in runs]
    worst = max(summaries, key=lambda s: s["worst_forward_peak_a"])
    every_eight = all(len(run["devices"]) == 8 for run in runs)
    return {
        "kind": "protection_soa_screening_table",
        "evidence_level": "SIMULATED_ONLY / NOT_RATED / NO_VENDOR_SOA",
        "results": {
            "vendor_soa_available": False,
            "reverse_current_components_resolved": False,
            "window_definitions": {
                "post_trip": "statistics over the saved samples at or after the OC trip",
                "saved_window": "statistics over the whole saved window",
            },
            "runs": runs,
            "summary": summaries,
            "global_worst_forward_peak_a": worst["worst_forward_peak_a"],
            "global_worst_run": worst["run"],
            "global_worst_device": worst["worst_forward_device"],
            "excluded_control": (
                "protection_candidate_48v_120a_prot_b_unarmed.json is excluded: it latches on "
                "the startup inrush and records a stopped converter, not fault stress"
            ),
            "limits": [
                "no vendor SOA curve or datasheet was read; the table is a screening list",
                "reverse current is a port measurement and is not split into body-diode and "
                "channel components; that decomposition from Vgs was withdrawn",
                "50 V rows come from the cshunt=1e-15 child; the 50 V base still stalls at 296.929 us",
                "the compare_base rows and the standalone probe rows use different windows and "
                "must not be differenced against each other",
                "50 V comparisons against the declared parent do not meet the 1 mV pre-fault "
                "pairing criterion (13-18 mV offset); their performance gains are exploratory, "
                "not paired effects.  Each row's comparison_basis names the deck it was "
                "differenced against",
                "the 50 V *_ctrl rows come from *_paired.json, which differences the candidate "
                "against a threshold-muted control deck; they are the only 50 V rows whose change "
                "can be attributed to the protection, and only when paired_pre_fault is true AND "
                "every device row reaches the declared window",
                "the threshold-muted 50 V control pairs exactly (0.000 mV pre-fault) but stalls at "
                "250.151 us (A) / 254.980 us (B) against a 320 us candidate, so its compare_base "
                "rows are truncated at that tail; the 50 V paired change is measured over the "
                "common slice, not the declared window",
                "two candidate fields (gate peak, drain max) and reverse current are not recorded "
                "in the comparison JSONs; they are null, not zero",
            ],
        },
        "checks": {
            "every_run_has_eight_devices": bool(every_eight),
            "every_source_is_hashed": all(len(run["source_sha256"]) == 64 for run in runs),
            "no_vendor_soa_is_claimed": True,
            "the_window_definition_is_recorded_for_every_run": all(
                run["window"] in ("post_trip", "saved_window") for run in runs),
            "unpaired_50v_parent_comparisons_not_claimed_as_paired": all(
                not run.get("paired_change_can_be_attributed_to_protection", False)
                for run in runs if run.get("case") and run["vin_v"] == 50.0
                and run["comparison_basis"] == "declared_parent"),
            # Structural: a control-based row must come from a paired record and
            # must say so.  Whether the pairing succeeded is a measured result and
            # stays in the row, never in this gate.
            "control_based_rows_come_from_paired_records": all(
                run["source_json"].endswith("_paired.json")
                for run in runs if run.get("comparison_basis") == "topology_matched_control"),
            "unrecorded_fields_are_null_not_zero": all(
                name in run["unrecorded_fields"] or name in run["null_by_design_fields"]
                for run in runs for row in run["devices"] for name, value in row.items()
                if value is None and name != "device"),
        },
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=Path, default=OUT)
    args = ap.parse_args(argv)
    table = build()
    args.json.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {args.json}  ({len(table['results']['runs'])} runs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
