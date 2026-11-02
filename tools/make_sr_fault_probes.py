"""Prepare eight-device SR protection probes; no simulation is performed.

Input is the already validated 48/50 V hot-fault netlist. Append only .save
nodes and .meas observations. Do not change drive, fault branch, solver or
nominal electrical parameters. This deck is UNRUN and is NOT a fault approval.
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES = ("48v_120a", "50v_120a")
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
    return ("* UNRUN eight-SR post-OC gate and device current diagnostic only.\n"
            "* 319us is on the rebased saved axis (nominal fault 175us).\n"
            "* 50V base record stopped at 296.929us: the new 319us measurements\n"
            "* REQUIRE a genuinely complete new solve, not an extrapolation.\n"
            + body)


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
