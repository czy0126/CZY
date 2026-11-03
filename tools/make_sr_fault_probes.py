"""Prepare eight-device SR protection probes; no simulation is performed.

Input is the already validated 48/50 V hot-fault netlist. Append only .save
nodes and .meas observations. Do not change drive, fault branch, solver or
nominal electrical parameters. This deck is UNRUN and is NOT a fault approval.
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 50v_120a_cshunt is derived from the CONVERGENCE_DIAGNOSTIC mother deck (the
# base stalls at 296.929 us).  It is the only 50 V deck that can carry the
# 319 us measurements, and it inherits cshunt=1e-15 unchanged.
# 48v_120a_cshunt is the robustness control: the same eight probes on a 1 fF
# variant of the completed 48 V base, to test whether the A-phase latch is a
# property of the circuit or of the solver trajectory.
CASES = ("48v_120a", "50v_120a", "48v_120a_cshunt", "50v_120a_cshunt")
SAVE = (
    "+ V(ga2) V(gb2) V(ga3) V(gb3)\n"
    "+ V(a2) V(b2) V(a3) V(b3)\n"
    "+ I(VSa2) I(VSb2) I(VSa3) I(VSb3)\n"
)
MEAS = "".join(
    (
        f".meas tran SR_{i}{side}_END FIND V(g{side.lower()}{i}) AT=319u\n"
        f".meas tran SR_{i}{side}_POST_PK MAX V(g{side.lower()}{i}) FROM=230u TO=319u\n"
        f".meas tran SR_{i}{side}_POST_I_PK MAX abs(I(VS{side.lower()}{i})) "
        "FROM=230u TO=319u\n"
    )
    for i in range(1, 5) for side in ("A", "B")
)


def source(case: str) -> Path:
    if case not in CASES:
        raise ValueError(case)
    return ROOT / f"sim/v3/sr_tank_dual_v33_ss_hotfault_{case}.cir"


def destination(case: str) -> Path:
    if case not in CASES:
        raise ValueError(case)
    return ROOT / f"sim/v3/sr_tank_dual_v33_ss_hotfault_{case}_srprobe.cir"


def header(case: str) -> str:
    """Short comment header, so the probe deck never claims more than its parent."""
    text = ("* UNRUN eight-SR post-OC gate and device current diagnostic only.\n"
            "* 319us is on the rebased saved axis (nominal fault 175us).\n")
    if case == "50v_120a_cshunt":
        return text + (
            "* Derived from the cshunt=1fF convergence variant: this solve must\n"
            "* reach 319us on its own; prefix deltas are in hotfault_50v_120a_cshunt.json.\n")
    if case == "48v_120a_cshunt":
        return text + (
            "* Derived from the 1fF robustness variant of the completed 48V base:\n"
            "* prefix deltas are in hotfault_48v_120a_cshunt.json.  A gate state that\n"
            "* differs here is solver-sensitive, not a circuit property.\n")
    return text + (
        "* 50V base record stopped at 296.929us: the new 319us measurements\n"
        "* REQUIRE a genuinely complete new solve, not an extrapolation.\n")


def build(text: str, case: str) -> str:
    if case not in CASES or text.count(".end\n") != 1:
        raise ValueError("invalid source or missing final .end")
    anchor = "+ V(ctl_hot) I(Rflt_hot)\n"
    if text.count(anchor) != 1 or ".meas tran HOT_VOUT_EARLY" not in text:
        raise ValueError("source is not the expected fault-probed deck")
    for i in range(1, 5):
        for side in "ab":
            if f"VS{side}{i} " not in text or f"g{side}{i} " not in text:
                raise ValueError(f"SR{i}{side} device/sense node missing")
    # .save continuations must stay directly after the previous .save lines,
    # not after .meas statements or (as the first version did) after
    # ".model HOTFLT ...", which made LTspice fold them into that model.
    body = text.replace(anchor, anchor + SAVE, 1)
    body = body.replace(".end\n", MEAS + ".end\n", 1)
    return header(case) + body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    opts = ap.parse_args()
    for case in CASES:
        out = destination(case)
        expected = build(source(case).read_text(encoding="utf-8"), case)
        if opts.write:
            out.write_text(expected, encoding="utf-8", newline="\n")
        elif out.read_text(encoding="utf-8") != expected:
            raise SystemExit(f"stale SR diagnostic {out}; --write")
        print(case, "UNRUN eight-device protection diagnostic")


if __name__ == "__main__":
    main()
