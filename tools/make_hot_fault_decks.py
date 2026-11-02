"""Generate *unrun* post-settling overload decks from measured 48/50V 120A SS candidates.

Purpose: original 48V cold fault occurs while SS=3.78V (NOT full SS).
These are deliberately precharged operating-point / hot-start fault tests,
NOT replacements for true cold-start tests, and no hardware qualification.
Fault is introduced at absolute 2175us (PWL threshold midpoint).
LTspice .tran saves 2000..2320us, so saved-axis fault is at 175us.
The longer pre-fault window is required: with .ic V(ss)=4 V and 5 uA into
10 nF, SS has only reached ~4.485 V at 1 ms.  At 2 ms it reaches ~5.0 V,
inside PR #20's 4.8..5.1 V settled-state band, without faking the .ic.

"""
from __future__ import annotations
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = {
    "48v_120a": ROOT / "sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i120_cin.cir",
    "50v_120a": ROOT / "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin.cir",
}
OLD_TRAN = ".tran 0 1000u 880u 5n uic"
NEW_TRAN = ".tran 0 2320u 2000u 5n uic"
FAULT = """* ---- independent HOT-START post-settling fault (not the cold deck) ----
* 1m switch + 1m resistor parallel to the existing rated-load candidate.
* Switch changes 0..5V over 2170..2180us, threshold 2.5V at 2175us.
Vfltctl_hot ctl_hot 0 PWL(0 0 2170u 0 2180u 5 2320u 5)
Sflt_hot out flt_hot ctl_hot 0 HOTFLT
Rflt_hot flt_hot 0 1m
.model HOTFLT SW(Ron=1m Roff=1G Vt=2.5)
"""
FAULT_SAVE = "+ V(ctl_hot) I(Rflt_hot)\n"
# These measurements are on the *rebased saved axis* from 2000us; original
# 0..120us measurements remain pre-fault baseline and are not copied into
# the new fault decision.
PROBES = """.meas tran HOT_CTRL_BEFORE AVG V(ctl_hot) FROM=120u TO=170u
.meas tran HOT_CTRL_AFTER AVG V(ctl_hot) FROM=190u TO=300u
.meas tran HOT_IFLT_AFTER MAX I(Rflt_hot) FROM=175u TO=320u
.meas tran HOT_OC_BEFORE MAX V(oc) FROM=120u TO=170u
.meas tran HOT_VOUT_BEFORE AVG V(out) FROM=120u TO=170u
.meas tran HOT_SS_BEFORE AVG V(ss) FROM=120u TO=170u
.meas tran HOT_IPRI_AFTER MAX abs(I(Lr)) FROM=175u TO=320u
.meas tran HOT_OC_AFTER MAX V(oc) FROM=175u TO=320u
.meas tran HOT_VOUT_MIN MIN V(out) FROM=175u TO=320u
.meas tran HOT_OC_TRIP WHEN V(oc)=1 RISE=1
"""


def destination(name: str) -> Path:
    return ROOT / f"sim/v3/sr_tank_dual_v33_ss_hotfault_{name}.cir"


def build(source: str, name: str) -> str:
    if name not in SOURCE or source.count(OLD_TRAN) != 1:
        raise ValueError("source changed / unknown case")
    for expected in ("Sflt_hot", ".ic V(out)=1.89 V(ss)=4", "Rload out sgnd"):
        if expected == "Sflt_hot":
            if expected in source:
                raise ValueError("already contains hot-fault injection")
        elif expected not in source:
            raise ValueError("expected operating-point initialization/load absent")
    if source.count(".end") != 1:
        raise ValueError("unexpected .end count")
    # Keep the exact original power circuit, controls, and original probes;
    # append independent fault circuit immediately before .end.
    body = source.replace(OLD_TRAN, NEW_TRAN)
    save_anchor = ".meas tran VOUT_AVG"
    if body.count(save_anchor) != 1:
        raise ValueError("cannot uniquely find .save termination")
    body = body.replace(save_anchor, FAULT_SAVE + save_anchor, 1)
    body = body.replace(".end", FAULT + PROBES + ".end", 1)
    header = (
        "* UNRUN hot-start overload stress candidate; not a cold start, not hardware rated.\n"
        f"* {name}: same 120A operating-point deck plus 2175us fault and longer transient.\n"
        "* Measured pre-fault V(ss), V(out), V(oc) MUST confirm the intended settled state.\n"
        "* Solver completion and all SR/Lr/CT stress bounds must be checked independently.\n"
    )
    return header + body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    for name, path in SOURCE.items():
        data = build(path.read_text(encoding="utf-8"), name)
        out = destination(name)
        if args.write:
            out.write_text(data, encoding="utf-8", newline="\n")
        elif out.read_text(encoding="utf-8") != data:
            raise SystemExit(f"stale candidate: {out}")
        print(f"{name}: UNRUN HOT-START FAULT; not evidence of steady-state approval")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
