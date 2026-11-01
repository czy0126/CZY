"""Generate the round-4 decks from the accepted 1 ms operating-point deck.

Round 4 (see docs/第三次独立审核与后续阶段任务书_2026-10-31.md, task package 1)
needs four controlled comparisons that differ from the accepted deck in ONE
dimension each:

    conv_5n / conv_2n / conv_1n   same init, same 200 us duration, same saved
                                  150..200 us window, only the max timestep moves
    cpin_50p / cpin_200p           same 2 ns run, only CPIN moves (the 100 pF
                                  reference is conv_2n itself)
    ss_1ms_full                   1 ms operating point plus full-machine I/O
                                  saves (Vbus, Vaux) and all four SR groups
    cold                          true cold start: no .ic at all, output cap at
                                  0 V, bias then main input then REG sequenced

The decks are generated instead of copied so the power stage stays bit-identical
to sr_tank_dual_v33_ss_1ms.cir (the accepted operating-point deck) and a later
edit to one deck cannot silently drift from the others.

Usage:
    python tools/make_round4_decks.py
"""

from __future__ import annotations

from pathlib import Path

SIM = Path(__file__).resolve().parent.parent / "sim" / "v2"
BASE = SIM / "sr_tank_dual_v33_ss_1ms.cir"
SPLIT = ".options plotwinsize=0 method=gear\n"


def sub_once(text: str, old: str, new: str) -> str:
    """Replace exactly one occurrence, or fail loudly."""
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one {old!r}, found {count}")
    return text.replace(old, new)


def load_base() -> str:
    return BASE.read_text(encoding="utf-8")


def head_of(text: str) -> str:
    if SPLIT not in text:
        raise SystemExit(f"{BASE.name} has no {SPLIT!r} separator")
    return text.split(SPLIT)[0]


def write(name: str, body: str) -> None:
    path = SIM / name
    path.write_text(body, encoding="utf-8")
    print(f"wrote {path.relative_to(SIM.parent.parent)}")


# ---------------------------------------------------------------- convergence
CONV_SAVE = """\
.save V(out) V(sw) V(reg) V(ss) I(Lr) V(a1) V(b1) V(ga1) V(gb1) I(VSa1) I(VSb1)
+ V(pre1) V(xsr1:q1) V(xsr1:q2) V(ovl1) V(ovg1) V(oc)
+ V(a4) V(b4) V(ga4) V(gb4) I(VSa4) I(VSb4) V(ovl4)
+ V(xsa1:di) V(xsa1:si) V(xsa1:gi) V(xsa1:gn) V(xsb1:di) V(xsb1:si) V(xsb1:gi) V(xsb1:gn)
+ I(xsa1:bch) I(xsa1:dbd) I(xsa1:cds) I(xsa1:cgd) I(xsa1:cgs) I(xsa1:rg) I(xsa1:lg) I(xsa1:ld) I(xsa1:ls)
+ I(xsr1:x1:bdrive) I(xsr1:x2:bdrive)
.meas tran VOUT_AVG AVG V(out) FROM=0 TO=50u
.meas tran VOUT_RIP PP V(out) FROM=40u TO=50u
.meas tran VDS_A1_MIN MIN V(a1) FROM=0 TO=50u
.meas tran VDS_A1_MAX MAX V(a1) FROM=0 TO=50u
.meas tran IREV_A1 MAX I(VSa1) FROM=0 TO=50u
.meas tran IFWD_A1 MAX -I(VSa1) FROM=0 TO=50u
.meas tran OVL_CUR MAX V(ovl1) FROM=0 TO=50u
.meas tran IPRI_PK MAX abs(I(Lr)) FROM=0 TO=50u
.end
"""


def convergence(step: str, cpin: str) -> str:
    head = head_of(load_base())
    if cpin != "100p":
        # Six occurrences: four SR_TIMING instances plus two header comments.
        # Replacing all keeps the comments consistent with the deck.
        head = head.replace("CPIN=100p", f"CPIN={cpin}")
    return (
        f"* ROUND-4 generated convergence deck: 200 us run, save 150..200 us,\n"
        f"* max timestep {step}, CPIN={cpin}.  Same .ic and same power stage as\n"
        f"* sr_tank_dual_v33_ss_1ms.cir.  LTspice REBASES the saved axis to 0,\n"
        f"* so every .meas window is 0..50 us (add 150 us to compare with the 1 ms run).\n"
        + SPLIT
        + head
        + f"\n.tran 0 200u 150u {step} uic\n"
        + ".ic V(out)=1.89 V(ss)=4\n"
        + CONV_SAVE
    )


def convergence_long(step: str, cpin: str = "100p") -> str:
    """Same 1 ms duration and 880..1000 us window as the accepted deck.

    The 200 us family compares timesteps at its own (not yet settled) point --
    measured later, its saved window was still in a 1.82..2.10 V transient, so
    it is NOT convergence evidence.  This family answers the strict question at
    the DESIGN point.  `cpin` isolates the SR device's input capacitance at the
    same 5 ns step and window.
    """
    head = head_of(load_base())
    if cpin != "100p":
        head = head.replace("CPIN=100p", f"CPIN={cpin}")
    return (
        f"* ROUND-4 generated 1 ms convergence deck: same duration (1 ms), same\n"
        f"* saved window (880..1000 us, rebased to 0..120 us), same .ic as\n"
        f"* sr_tank_dual_v33_ss_1ms.cir; only the max timestep is {step} and\n"
        f"* CPIN is {cpin} (100 pF is the reference).\n"
        + SPLIT
        + head
        + f"\n.tran 0 1000u 880u {step} uic\n"
        + ".ic V(out)=1.89 V(ss)=4\n"
        + CONV_SAVE
    )


# ---------------------------------------------------------------- full-machine
FULL_SAVE = """\
.save V(out) V(sw) V(reg) V(ss) V(aux) V(oc) V(vin0) I(Lr) I(Vbus) I(Vaux) I(Vreg)
+ V(a1) V(b1) V(a2) V(b2) V(a3) V(b3) V(a4) V(b4)
+ V(ga1) V(gb1) V(ga2) V(gb2) V(ga3) V(gb3) V(ga4) V(gb4)
+ I(VSa1) I(VSb1) I(VSa2) I(VSb2) I(VSa3) I(VSb3) I(VSa4) I(VSb4)
+ V(xsa1:di) V(xsa1:si) V(xsa1:gi) V(xsa1:gn)
+ I(xsa1:bch) I(xsa1:dbd) I(xsa1:cds) I(xsa1:cgd) I(xsa1:cgs) I(xsa1:rg) I(xsa1:lg) I(xsa1:ld) I(xsa1:ls)
+ I(xsr1:x1:bdrive)
.meas tran VOUT_AVG AVG V(out) FROM=0 TO=120u
.meas tran VOUT_RIP PP V(out) FROM=110u TO=120u
.meas tran VDS_A1_MIN MIN V(a1) FROM=0 TO=120u
.meas tran VDS_A1_MAX MAX V(a1) FROM=0 TO=120u
.meas tran IREV_A1 MAX I(VSa1) FROM=0 TO=120u
.meas tran IFWD_A1 MAX -I(VSa1) FROM=0 TO=120u
.meas tran IPRI_PK MAX abs(I(Lr)) FROM=0 TO=120u
.meas tran VIN_AVG AVG V(vin0) FROM=0 TO=120u
.meas tran IAUX_AVG AVG I(Vaux) FROM=0 TO=120u
.end
"""


def full_machine() -> str:
    head = head_of(load_base())
    return (
        "* ROUND-4 generated full-machine deck: same 1 ms operating point as\n"
        "* sr_tank_dual_v33_ss_1ms.cir, but saves all four SR groups and the two\n"
        "* input sources so output / input / bias power are measured on the same run.\n"
        + SPLIT + head
        + "\n.tran 0 1000u 880u 5n uic\n"
        + ".ic V(out)=1.89 V(ss)=4\n"
        + FULL_SAVE
    )


# ---------------------------------------------------------------- cold start
COLD_SAVE = """\
.save V(out) V(sw) V(ss) V(aux) V(reg) V(oc) V(vin0) I(Lr) I(Vbus) I(Vaux) I(Vreg)
+ V(pre1) V(pre2) V(pre3) V(pre4)
+ V(ga1) V(gb1) V(ga2) V(gb2) V(ga3) V(gb3) V(ga4) V(gb4)
+ V(a1) V(a2) V(a3) V(a4) V(b1) V(b2) V(b3) V(b4)
+ I(VSa1) I(VSb1) I(VSa4) I(VSb4)
.meas tran VOUT_MAX MAX V(out) FROM=0 TO=8m
.meas tran VOUT_2M FIND V(out) AT=2m
.meas tran VOUT_4M FIND V(out) AT=4m
.meas tran VOUT_6M FIND V(out) AT=6m
.meas tran VOUT_AVG AVG V(out) FROM=7m TO=8m
.meas tran IPRI_PK MAX abs(I(Lr)) FROM=0 TO=8m
.meas tran VSRA1_PK MAX -I(VSa1) FROM=0 TO=8m
.meas tran OC_MAX MAX V(oc) FROM=0 TO=8m
.meas tran IAUX_PK MAX I(Vaux) FROM=0 TO=8m
.meas tran IBUS_PK MAX -I(Vbus) FROM=0 TO=8m
.end
"""


def cold() -> str:
    head = head_of(load_base())
    head = sub_once(head, "Vbus vin0 0 {VIN}", "Vbus vin0 0 PWL(0 0 400u 0 800u {VIN} 8m {VIN})")
    head = sub_once(head, "Vaux aux 0 12", "Vaux aux 0 PWL(0 0 50u 0 350u 12 8m 12)")
    head = sub_once(head, "Vreg reg sgnd PWL(0 0 130u 0 150u 11 1m 11)",
                    "Vreg reg sgnd PWL(0 0 1.2m 0 1.4m 11 8m 11)")
    return (
        "* ROUND-4 generated TRUE COLD-START deck (review 2026-10-31 round 3,\n"
        "* P1 'cold start still precharges 2 V').\n"
        "*\n"
        "* Deliberately has NO .ic: with uic every node and every capacitor starts\n"
        "* at zero, so Cout is at 0 V -- unlike sr_tank_dual_v33.cir, whose\n"
        "* '.ic V(out)=2' only makes SS start from zero.\n"
        "*\n"
        "* Sequence (modelling choice, documented, not a datasheet claim):\n"
        "*   0..350 us    VCC/aux 0 -> 12 V (crosses the 10.5 V UVLO at ~262 us)\n"
        "*   400..800 us  main 48 V input 0 -> 48 V\n"
        "*   1.2..1.4 ms  SR controller REG rail 0 -> 11 V, AFTER the main input\n"
        "*                is present so the model's pre-arm (VD>1.5 V before\n"
        "*                REG>4.1 V) can qualify.  REG before main would latch the\n"
        "*                violation flag and hold every SR gate off forever.\n"
        "*   ~6 ms        SS reaches 3.982 V -> 200.6 kHz design point.\n"
        "*\n"
        "* 10 ns max step: this deck answers 'does the converter traverse start-up',\n"
        "* not a ledger-grade 1 ns question.  The fine-step comparison is the\n"
        "* conv_* family on the operating point.\n"
        + SPLIT + head
        + "\n.tran 0 8m 0 10n uic\n"
        + COLD_SAVE
    )


FAULT_NET = """\
* ---- OC fault injection: severe overload at ~5.55 ms -----------------------
* Same mechanism as sim/v2/startup_ct_fault.cir: a 1 mOhm switch plus a 1 mOhm
* resistor in parallel with the 20 mOhm load = 1.818 mOhm, about 11x nominal.
* It is injected AFTER start-up has settled at the 200.6 kHz design point, so
* the over-current trip and restart are measured on the true cold deck instead
* of only on the older startup_seq family.
Vfltctl ctl 0 PWL(0 0 5.5m 0 5.6m 5 8m 5)
Sflt out flt ctl 0 SFLT
Rflt flt 0 1m
.model SFLT SW(Ron=1m Roff=1G Vt=2.5)
"""

COLD_OC_SAVE = COLD_SAVE.replace(
    ".meas tran OC_MAX MAX V(oc) FROM=0 TO=8m",
    ".meas tran OC_MAX MAX V(oc) FROM=0 TO=8m\n"
    ".meas tran OC_TRIP WHEN V(oc)=1 CROSS=1\n"
    ".meas tran OC_AFTER_MAX MAX V(oc) FROM=5.6m TO=8m\n"
    ".meas tran IPRI_AFTER MAX abs(I(Lr)) FROM=5.6m TO=5.8m\n"
    ".meas tran VOUT_AFTER_MIN MIN V(out) FROM=5.6m TO=8m\n"
    ".meas tran OUT_AT_END FIND V(out) AT=8m",
)


def cold_oc() -> str:
    """True cold start plus a severe overload at ~5.55 ms (review P1 'OC restart').

    Identical to sr_tank_dual_v33_cold.cir apart from the injected fault path
    and the extra trip/restart measurements, so trip time and restart behaviour
    are attributable to the cold deck itself rather than to the older
    startup_seq deck.
    """
    text = cold()
    text = sub_once(text, "\nRload out sgnd {RL}\n", "\nRload out sgnd {RL}\n" + FAULT_NET)
    text = sub_once(text, COLD_SAVE, COLD_OC_SAVE)
    note = (
        "* VARIANT cold_oc: sr_tank_dual_v33_cold.cir plus a severe overload at\n"
        "* ~5.55 ms, so the over-current trip and restart are exercised on the\n"
        "* TRUE cold deck (no .ic, Cout at 0 V).\n"
    )
    return note + text


def main() -> None:
    write("sr_tank_dual_v33_conv_5n.cir", convergence("5n", "100p"))
    write("sr_tank_dual_v33_conv_2n.cir", convergence("2n", "100p"))
    write("sr_tank_dual_v33_conv_1n.cir", convergence("1n", "100p"))
    write("sr_tank_dual_v33_cpin_50p.cir", convergence("2n", "50p"))
    write("sr_tank_dual_v33_cpin_200p.cir", convergence("2n", "200p"))
    write("sr_tank_dual_v33_conv1ms_2n.cir", convergence_long("2n"))
    write("sr_tank_dual_v33_conv1ms_1n.cir", convergence_long("1n"))
    write("sr_tank_dual_v33_cpin1ms_50p.cir", convergence_long("5n", "50p"))
    write("sr_tank_dual_v33_cpin1ms_200p.cir", convergence_long("5n", "200p"))
    write("sr_tank_dual_v33_ss_1ms_full.cir", full_machine())
    write("sr_tank_dual_v33_cold.cir", cold())
    write("sr_tank_dual_v33_cold_oc.cir", cold_oc())


if __name__ == "__main__":
    main()
