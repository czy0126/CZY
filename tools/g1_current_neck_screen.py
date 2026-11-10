"""Screen actual saved/reopened G1 100 A output copper *necks*, not concept bars.

The four CTAP/VOUT and eight SR/PGND 1 mm-wide track branches are
independently taken from the native EasyEDA readback and combined as ideal
parallel paths. 2 mm trunks, vias, terminations, AC and thermal effects are
omitted: the result is an optimistic DC series-resistance floor, not 100 A
qualification or a replacement for IPC-2152 thermal evaluation.

python tools/g1_current_neck_screen.py --write
python tools/g1_current_neck_screen.py --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
G1 = ROOT / "hardware/dcx_main/g1"
READBACK = G1 / "lr_repack_readback.json"
NATIVE = G1 / "dcx_main_board_g1_lr_repack.eprj2"
RECEIPT = G1 / "lr_repack_native_report.json"
GATE = G1 / "g1_magnetic_envelope_gate.json"
REPORT = G1 / "g1_100a_copper_neck_screen.json"
MIL_MM = .0254
RHO20_OHM_M = 1.724e-8
ALPHA_PER_C = .00393
TEMP_C = 100.0
TOTAL_CURRENT_A = 100.0
BUDGET_UOHM = 150.0
THICKNESSES_UM = (35, 70, 105, 210)


def git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def validate_source() -> dict:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    gate = json.loads(GATE.read_text(encoding="utf-8"))
    if hashlib.sha256(NATIVE.read_bytes()).hexdigest() != receipt["candidate_sha256"]:
        raise ValueError("native CAD hash differs from the actual reopen receipt")
    if git_blob_sha(READBACK) != gate["evidence"]["native_readback_git_blob_sha"]:
        raise ValueError("native readback differs from the active G1 physical audit")
    if receipt["candidate"] != NATIVE.relative_to(ROOT).as_posix():
        raise ValueError("native CAD identity differs from receipt")
    if receipt["fab_release"] or gate["evidence"]["fab_approved"]:
        raise ValueError("source-only neck estimate must never approve fabrication")
    raw = json.loads(READBACK.read_text(encoding="utf-8"))
    if raw.get("ok") is not True or not isinstance(raw.get("value"), dict):
        raise ValueError("no successful native reopen readback")
    value = raw["value"]
    if len(value["lines"]) != receipt["lines"] or len(value["pads"]) != receipt["pads"]:
        raise ValueError("PCB primitive counts differ from original native receipt")
    return value


def near(a: float, b: float, tol: float = .035) -> bool:
    return abs(a - b) <= tol


def unpack(t: dict) -> dict:
    return {
        "id": t["id"], "net": t["net"], "layer": t["layer"],
        "x1": t["x1"] * MIL_MM, "y1": -t["y1"] * MIL_MM,
        "x2": t["x2"] * MIL_MM, "y2": -t["y2"] * MIL_MM,
        "width_mm": t["width"] * MIL_MM,
        "length_mm": math.hypot(t["x2"] - t["x1"], t["y2"] - t["y1"]) * MIL_MM,
    }


def extract_branches(lines: list[dict]) -> tuple[list[list[dict]], list[list[dict]]]:
    tracks = [unpack(x) for x in lines]
    vout, pgnd = [], []
    for x in (39., 77., 115., 153.):
        h = [s for s in tracks if s["net"] == "VOUT" and s["layer"] == 1
             and near(s["width_mm"], 1.) and near(s["x1"], x-2)
             and near(s["x2"], x) and near(s["y1"], 20.) and near(s["y2"], 20.)]
        v = [s for s in tracks if s["net"] == "VOUT" and s["layer"] == 1
             and near(s["width_mm"], 1.) and near(s["x1"], x)
             and near(s["x2"], x) and near(s["y1"], 20.) and near(s["y2"], 35.5)]
        if len(h) != 1 or len(v) != 1:
            raise ValueError(f"changed VOUT CTAP neck at x={x}: H={len(h)} V={len(v)}")
        vout.append([h[0], v[0]])
    for x in (13.401, 23.401, 51.399, 61.399, 89.400, 99.400, 127.401, 137.401):
        segments = [s for s in tracks if s["net"] == "PGND" and s["layer"] == 1
                    and near(s["width_mm"], 1.) and near(s["x1"], x)
                    and near(s["x2"], x) and near(s["y1"], 84.470)
                    and near(s["y2"], 96.)]
        if len(segments) != 1:
            raise ValueError(f"changed SR PGND source neck at x={x}: {len(segments)}")
        pgnd.append([segments[0]])
    ids = [s["id"] for group in vout + pgnd for s in group]
    if len(set(ids)) != 16:
        raise ValueError("duplicated or missing native copper primitive IDs")
    return vout, pgnd


def resistance(branch: list[dict], thickness_um: float,
               temp_c: float = TEMP_C) -> float:
    if not 0 < thickness_um <= 1000 or not -30 <= temp_c <= 200:
        raise ValueError("invalid copper thickness or temperature")
    rho = RHO20_OHM_M * (1 + ALPHA_PER_C * (temp_c - 20))
    return sum(rho * s["length_mm"] * 1e-3 /
               (s["width_mm"] * 1e-3 * thickness_um * 1e-6)
               for s in branch)


def parallel_resistance(resistances: list[float]) -> float:
    if not resistances or any(not math.isfinite(x) or x <= 0 for x in resistances):
        raise ValueError("invalid branch resistance")
    return 1 / sum(1 / x for x in resistances)


def analyze(lines: list[dict]) -> dict:
    vout, pgnd = extract_branches(lines)
    result = {
        "status": "P0_G1_ACTUAL_NARROW_NECKS_NOT_100A_QUALIFIED",
        "source": "hardware/dcx_main/g1/lr_repack_readback.json",
        "source_is_reopened_native_pcb": True,
        "current_a_assumed": TOTAL_CURRENT_A,
        "conductor_temp_c_assumed": TEMP_C,
        "copper_rho20_ohm_m_assumed": RHO20_OHM_M,
        "alpha_per_c_assumed": ALPHA_PER_C,
        "both_rails_budget_uohm": BUDGET_UOHM,
        "vout_four_ctap_branches": [
            {"track_ids": [s["id"] for s in group],
             "length_mm": round(sum(s["length_mm"] for s in group), 5),
             "width_mm": 1.} for group in vout],
        "pgnd_eight_sr_source_branches": [
            {"track_ids": [s["id"] for s in group],
             "length_mm": round(sum(s["length_mm"] for s in group), 5),
             "width_mm": 1.} for group in pgnd],
        "scenarios": [],
        "model_limitations": [
            "Optimistic uniform copper cross section and ideal parallel load sharing, not actual transient SR RMS currents.",
            "Excludes even the existing 2mm VOUT/PGND trunks, joints, pads, connectors, vias, current spreading and AC loss.",
            "Four CTAPs are provisional design-owned pads, not qualified physical winding terminals.",
            "Thick foil scenario is hypothetical: actual EDA PCB stackup and manufactured copper thickness are not verified.",
            "No IPC-2152 thermal/current carrying qualification, Maxwell 3D current distribution or PCB fab approval.",
            "Source-locked to the saved/reopened Lr board; any subsequent actual copper redraw requires new readback.",
        ],
        "fabrication_approved": False,
    }
    for um in THICKNESSES_UM:
        rv = parallel_resistance([resistance(group, um) for group in vout])
        rp = parallel_resistance([resistance(group, um) for group in pgnd])
        rt = rv + rp
        result["scenarios"].append({
            "nominal_thickness_um": um,
            "vout_necks_uohm": round(rv*1e6, 3),
            "pgnd_necks_uohm": round(rp*1e6, 3),
            "combined_necks_uohm": round(rt*1e6, 3),
            "ideal_100a_neck_loss_w": round(TOTAL_CURRENT_A**2 * rt, 3),
            "times_complete_rail_budget": round(rt*1e6/BUDGET_UOHM, 3),
            "within_complete_rail_budget": rt*1e6 <= BUDGET_UOHM,
        })
    return result


def report() -> dict:
    native = validate_source()
    result = analyze(native["lines"])
    result["native_cad_sha256"] = hashlib.sha256(NATIVE.read_bytes()).hexdigest()
    result["readback_git_blob_sha"] = git_blob_sha(READBACK)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    args = ap.parse_args()
    result = report()
    if args.write:
        REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n",
                          encoding="utf-8")
    elif not REPORT.is_file() or json.loads(REPORT.read_text(encoding="utf-8")) != result:
        raise SystemExit("G1 native copper-neck screen stale; rerun --write")
    print(json.dumps({"scenarios": result["scenarios"], "fab_approved": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
