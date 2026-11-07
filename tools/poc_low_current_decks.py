"""Generate 5 A / 10 A diagnostic cold-start SPICE decks from the live D1 source.

The two modes use the SAME resonant power stage and calibrated MOS model:
  SR_ON:  existing behavioural UCC24624 timing
  SR_OFF: *ideal* external 0 V gate clamp, leaving MOS body diodes active.

These are model comparison decks, not a physical gate-off circuit, and are
specifically NOT approval to energize a 48 V assembly. Output 5/10 A is
only a load-resistance target at an assumed 2 V output, NOT a measured value.

Usage: python tools/poc_low_current_decks.py --write
       python tools/poc_low_current_decks.py --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "sim/v3/sr_tank_dual_v33_cold_phys.cir"
OUT = ROOT / "sim/v3"
CASES = {("5a", "on"): 0.4, ("5a", "off"): 0.4,
         ("10a", "on"): 0.2, ("10a", "off"): 0.2}
SOURCE_PARAMETERS = ".param VIN=48 RL=20m LP=10u LR_TOTAL=1u CR_TOTAL=620n"
SAVE_START = ".save V(out) V(sw) V(ss) V(aux) V(reg) V(oc) V(vin0) I(Lr) I(Vbus) I(Vaux) I(Vreg)"


def deck(case: str, mode: str, parent: str | None = None) -> str:
    if (case, mode) not in CASES:
        raise ValueError(f"unsupported target or SR mode {case}/{mode}")
    source = parent if parent is not None else PARENT.read_text(encoding="utf-8")
    if source.count(SOURCE_PARAMETERS) != 1:
        raise ValueError("baseline tank / RL parameters changed; review required")
    # Lock to the *same* 48V, ratio, CT network, cold-start supply and protection.
    lines = source.splitlines()
    marker = f".param VIN=48 RL={CASES[(case, mode)]:.1f} LP=10u LR_TOTAL=1u CR_TOTAL=620n"
    lines = [line.replace(SOURCE_PARAMETERS, marker)
             if SOURCE_PARAMETERS in line else line for line in lines]

    out = []
    skip_save_continuations = False
    cut_groups = 0
    for line in lines:
        if line.startswith(".save "):
            skip_save_continuations = True
            out += [
                ".save V(out) V(sw) V(ss) V(aux) V(reg) V(oc) V(vin0) I(Lr) I(Vbus)",
                "+ V(a1) V(b1) V(ga1) V(gb1) V(ga4) V(gb4)",
                "+ I(VSa1) I(VSb1) I(VSa4) I(VSb4)",
            ]
            continue
        if skip_save_continuations and line.lstrip().startswith("+"):
            continue
        skip_save_continuations = False
        if mode == "off" and re.match(r"^Xsr[1-4]\s", line, re.I):
            m = re.match(r"^Xsr([1-4])\s", line, re.I)
            i = m.group(1)
            out.extend([f"* {line}", f"VCLAMP_A{i} ga{i} sgnd 0",
                        f"VCLAMP_B{i} gb{i} sgnd 0"])
            cut_groups += 1
        elif mode == "off" and line.startswith("Vreg reg sgnd PWL("):
            out.append("Vreg reg sgnd 0 ; SR_OFF test only: REG held off")
        else:
            out.append(line)
    if mode == "off" and cut_groups != 4:
        raise ValueError(f"expected 4 SR_TIMING groups, found {cut_groups}")
    if mode == "on" and any(x.startswith("VCLAMP_A") for x in out):
        raise ValueError("SR_ON must not clamp any real gate")
    if not out or out[-1] != ".end":
        raise ValueError("original deck has no .end")
    out.pop()
    out.extend([
        "* --- D1 split-path diagnostic, 2V/R target only; not a power-on authorization ---",
        ".meas tran POC_VOUT_6_8_AVG AVG V(out) FROM=6m TO=8m",
        ".meas tran POC_VOUT_MAX MAX V(out) FROM=0 TO=8m",
        ".meas tran POC_VOUT_MIN MIN V(out) FROM=6m TO=8m",
        ".meas tran POC_INPUT_MIN MIN -I(Vbus) FROM=6m TO=8m",
        ".meas tran POC_INPUT_MAX MAX -I(Vbus) FROM=0 TO=8m",
        ".meas tran POC_PRIMARY_MAX MAX abs(I(Lr)) FROM=0 TO=8m",
        ".meas tran POC_RECTIFIER_CURRENT_MAX MAX abs(I(VSa1)) FROM=0 TO=8m",
        ".meas tran POC_GATE_A1_MAX MAX V(ga1,sgnd) FROM=0 TO=8m",
        ".meas tran POC_GATE_B1_MAX MAX V(gb1,sgnd) FROM=0 TO=8m",
        ".end",
    ])
    new = ("\n".join(out) + "\n")
    heading = (
        f"* PoC case {case} SR_{mode.upper()} (load R={CASES[(case, mode)]} ohm)\n"
        f"* AUTO-GENERATED from {PARENT.relative_to(ROOT).as_posix()}; NO hardware verification.\n"
        "* SR_OFF uses ideal gate clamps and MOSFET calibrated body diodes; "
        "NOT a qualified clamp circuit.\n"
        "* Rated current and voltage may differ radically in this fixed-ratio light-load model.\n"
        "* No source-level changes are permitted to the primary, CT or transformer network.\n"
    )
    return heading + new


def path(case: str, mode: str) -> Path:
    return OUT / f"poc_{case}_sr_{mode}.cir"


def manifest() -> dict:
    parent = PARENT.read_bytes()
    return {
        "status": "MODEL_ONLY_NOT_FOR_HARDWARE",
        "source_path": PARENT.relative_to(ROOT).as_posix(),
        "source_sha256": hashlib.sha256(parent).hexdigest(),
        "config": {
            "input_bus_nominal_v": 48,
            "output_nominal_for_resistance_only_v": 2,
            "fixed_ratio_unchanged": "24:1",
            "target_load_resistors_ohm": {"5a": 0.4, "10a": 0.2},
            "sr_off_ideal_external_gate_clamp": True,
            "sr_on_existing_behavioural_timing": True,
            "output_actual_current_verified": False,
            "physical_diode_temperature_verified": False,
            "lab_psu_current_limit_measured": False,
            "power_stage_power_on_authorized": False,
        },
        "cases": {
            f"{c}_{m}": {"path": path(c, m).relative_to(ROOT).as_posix(),
                         "sha256": hashlib.sha256(deck(c, m).encode()).hexdigest(),
                         "mode": m,
                         "rload_ohm": CASES[(c, m)],
                         "estimated_2v_output_a": 2/CASES[(c, m)],
                         "LTspice_simulated": False}
            for c, m in CASES
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.write:
        for case, sr in CASES:
            p = path(case, sr)
            p.write_text(deck(case, sr), encoding="utf-8", newline="\n")
            print("written", p.relative_to(ROOT))
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return 0
    bad = [
        str(path(c, m).relative_to(ROOT)) for c, m in CASES
        if not path(c, m).is_file()
        or path(c, m).read_text(encoding="utf-8") != deck(c, m)
    ]
    if bad:
        print("stale generated PoC cases: " + ", ".join(bad))
        return 2
    print("4 PoC cases are current; model-only, no hardware approval")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
