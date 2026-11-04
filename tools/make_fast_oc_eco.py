"""Generate the TLV3501 fast-overcurrent ECO module for D0.

Why a module and not a BOM edit
-------------------------------
D0's "fast" channel is U3B (LM393) fed from OC_FILT.  That node sits behind
three cascaded poles:

    OCD --[1k/47nF, 47 us]--> OCF --[10k/24k + 10nF, 70.6 us]--> OC
        --[10k/1nF, 10 us]--> OC_FILT --[LM393]--> FAST_TRIP

so the comparator is not the problem; the ~128 us in front of it is.  Swapping
LM393 for a 4.5 ns part changes nothing measurable.  This module taps the CT
burden node (OCD) through a single 1 us pole, compares against a 2.5 V shunt
reference, and pulls FAST_TRIP low through an open-drain NMOS.

It is a separate 4-pin board so D0's tests are untouched and the module can be
characterised on its own, then wired onto D0 at OCD / FAST_TRIP / V5 / PGND.

Output polarity and wiring
--------------------------
FAST_TRIP on D0 is open-collector (R15 10k to V5) and feeds the CD4013 latch.
The TLV3501 output is push-pull, so it may not be wire-OR'd directly.  Q1 makes
it open drain: overcurrent -> OUT high -> Q1 on -> FAST_TRIP low.  Two
open-drain drivers on one net is a legal wired-OR; the module simply asserts
much earlier than U3B.

Arithmetic the report carries (recomputed by the test)
------------------------------------------------------
* Trip at 75.0 A nominal (76.6 A with the hysteresis offset): 2.5 V reference,
  30k/15k divider, 0.1 V/A burden.  That is 5.4x the 13.88 A rated peak and
  above both UCC25600 levels (1 V / 24 A, 2 V / 48 A), so it does not disturb
  normal protection coordination.  It also sits above the 73.68 A peak of the
  frozen short-circuit deck -- a deliberate boundary, recorded as such.
* 3.2 A hysteresis through a 470k feedback resistor.
* 1.0 us input pole + 12 ns comparator worst case over temperature (5 mV
  overdrive) + ~50 ns gate network: about 1.06 us, versus ~128.9 us today.

SHDN is tied to PGND.  On the TLV3501 a HIGH shutdown pin *disables* the part
(within 0.9 V of V+); it is enabled only when SHDN is more than 1.7 V below V+.
Tying it to V+ is the single easiest way to build a fast comparator that never
switches, so a test pins the net to PGND.

Usage:
    python tools/make_fast_oc_eco.py
    python tools/make_fast_oc_eco.py --check
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import uuid
from dataclasses import replace
from pathlib import Path

from main_board_mechanical import find_kicad_cli

# Shared plumbing.  The SR board is the first generator to need it; importing
# keeps a single definition of pin parsing instead of a third copy.  Only the
# generic helpers are taken -- the part tables and the UUID namespace are local
# so the two boards cannot collide.
from make_sr_fault_board import (
    Part,
    Pin,
    custom_symbol,
    erc_violations,
    extract_symbol,
    pin_tips,
    validate,
    validate_no_coincident_tips,
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "pcb" / "fast_oc"
NS = uuid.UUID("c41b7e08-5f2d-4a63-b9d1-0e8a6c3f2d75")


def uid(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


def snap(part: Part) -> Part:
    return replace(part, x=round(part.x / 1.27) * 1.27, y=round(part.y / 1.27) * 1.27)


def kicad_cli() -> Path | None:
    return find_kicad_cli()


def symbol_libs() -> Path:
    cli = kicad_cli()
    if cli is None:
        raise SystemExit("kicad-cli not found; set KICAD_CLI to regenerate symbols")
    return cli.parent.parent / "share" / "kicad" / "symbols"


# ------------------------------------------------------------------ constants
CMP = "references/datasheets/tlv3501.txt"

VREF = 2.5                 # V, LM4040DBZ-2.5
R_TOP = 30e3               # ohm, OCD -> IN+
R_BOT = 15e3               # ohm, IN+ -> PGND
C_IN = 100e-12             # F, IN+ to PGND
R_HYST = 470e3             # ohm, OUT -> IN+
R_GATE = 100.0             # ohm, comparator OUT -> Q1 gate
C_GATE = 100e-12           # F, 2N7002 gate capacitance (datasheet typical)
R_BIAS = 2.4e3             # ohm, V5 -> REF
V5 = 5.0                   # V, module supply
BURDEN_V_PER_A = 0.1       # V/A, R_burden / CT ratio = 10 ohm / 100

# TLV3501, SBOS321E.  Propagation delay is quoted at two overdrives; the
# worst case over temperature is the 5 mV, 12 ns number, and that is what the
# budget uses (the roadmap forbids quoting the typical 4.5 ns).
TPD_TYP_20MV = 4.5e-9
TPD_MAX_20MV_25C = 6.4e-9
TPD_TYP_5MV_25C = 7.5e-9
TPD_MAX_5MV_25C = 10e-9
TPD_MAX_5MV_OVER_TEMP = 12e-9
CM_LOW = -0.2              # V relative to V- (absolute maximum is -0.3 V)
CM_HIGH_MARGIN = 0.2       # V below V+
ABS_MAX_MARGIN = 0.3       # V beyond either rail
IQ_MAX = 5e-3              # A
SHDN_ENABLE_BELOW = V5 - 1.7   # < 3.3 V enables; > 4.1 V disables

# The status quo on D0 (make_d0_protection_board.ct_parts).
EXISTING_TAUS = (
    ("rf_cf", 1e3 * 47e-9),
    ("rd1_rd2_coc", 10e3 * 24e3 / (10e3 + 24e3) * 10e-9),
    ("r12_c13", 10e3 * 1e-9),
)
LM393_TPD_TYP = 1.3e-6

# Fault peaks already published in this repository, for the threshold table.
KNOWN_PEAKS_A = {
    "steady_state_rated": 13.88,
    "ucc25600_level1": 24.2,
    "frozen_short_circuit_deck": 73.68,
    "cold_start_fault": 84.83,
    "hotfault_48v": 97.44,
    "hotfault_50v_prefix": 101.26,
}


# ------------------------------------------------------------------ symbols
STANDARD = {
    "Device:R": ("Device.kicad_sym", "R"),
    "Device:C": ("Device.kicad_sym", "C"),
    "Device:D_Schottky": ("Device.kicad_sym", "D_Schottky"),
    "Comparator:TLV3501AIDBV": ("Comparator.kicad_sym", "TLV3501AIDBV"),
    "Transistor_FET:Q_NMOS_GSD": ("Transistor_FET.kicad_sym", "Q_NMOS_GSD"),
    "Connector_Generic:Conn_01x04": ("Connector_Generic.kicad_sym", "Conn_01x04"),
    "Connector:TestPoint": ("Connector.kicad_sym", "TestPoint"),
    "power:PWR_FLAG": ("power.kicad_sym", "PWR_FLAG"),
}


def build_symbols() -> dict[str, str]:
    libs = symbol_libs()
    symbols: dict[str, str] = {}
    for lib_id, (lib, name) in STANDARD.items():
        block = extract_symbol(libs / lib, name)
        block = block.replace(f'(symbol "{name}"', f'(symbol "{lib_id}"', 1)
        symbols[lib_id] = block
    # Two-pin shunt reference.  The stock LM4040DBZ symbols use ``extends`` and
    # the SOT-23 third pin is NC, so a two-pin symbol is enough and avoids a
    # derivative-symbol lookup that this generator would have to resolve.
    symbols["FASTOC:LM4040"] = custom_symbol(
        "FASTOC:LM4040",
        [Pin("1", "K", 2.54, 0, 180, "power_out"),
         Pin("2", "A", -2.54, 0, 0, "power_in")],
        5.08, 5.08, footprint="Package_TO_SOT_SMD:SOT-23")
    return symbols


# ------------------------------------------------------------------ parts
SMD = "Package_TO_SOT_SMD:SOT-23"


def parts() -> list[Part]:
    ps = [
        Part("J1", "Connector_Generic:Conn_01x04", "5V/OCD/FAST_TRIP",
             "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", 30, 60,
             {"1": "V5", "2": "PGND", "3": "OCD", "4": "FAST_TRIP"},
             rating="5 V",
             note="wire to D0: V5, PGND, OCD (R8 node), FAST_TRIP (R15/TP8)"),
        Part("C1", "Device:C", "1uF/16V", "Capacitor_SMD:C_0603_1608Metric", 62, 48,
             {"1": "V5", "2": "PGND"}, rating="16 V X7R", note="supply bulk"),
        Part("C2", "Device:C", "100nF/16V", "Capacitor_SMD:C_0603_1608Metric", 74, 48,
             {"1": "V5", "2": "PGND"}, rating="16 V X7R", note="at U1 pin 4"),
        Part("U1", "Comparator:TLV3501AIDBV", "TLV3501AIDBV", SMD, 90, 80,
             {"1": "REF", "2": "PGND", "3": "INP", "4": "V5",
              "5": "OUT", "6": "SHDN"},
             rating="2.7-5.5 V",
             note="pin 1 = IN-, pin 3 = IN+, pin 6 = SHDN tied LOW to enable"),
        Part("U2", "FASTOC:LM4040", "LM4040DBZ-2.5", SMD, 62, 100,
             {"1": "REF", "2": "PGND"}, rating="2.5 V",
             note="shunt reference; pin 3 of the SOT-23 is NC"),
        Part("R1", "Device:R", "2.4k", "Resistor_SMD:R_0603_1608Metric", 50, 92,
             {"1": "V5", "2": "REF"},
             note="reference bias, (5-2.5)/2.4k = 1.04 mA"),
        Part("C3", "Device:C", "100nF/16V", "Capacitor_SMD:C_0603_1608Metric", 62, 112,
             {"1": "REF", "2": "PGND"}, rating="16 V X7R", note="reference bypass"),
        Part("R2", "Device:R", "30k 1%", "Resistor_SMD:R_0603_1608Metric", 70, 74,
             {"1": "OCD", "2": "INP"}, note="divider top; 1/3 of the burden voltage"),
        Part("R3", "Device:R", "15k 1%", "Resistor_SMD:R_0603_1608Metric", 70, 90,
             {"1": "INP", "2": "PGND"}, note="divider bottom"),
        Part("C4", "Device:C", "100pF/50V", "Capacitor_SMD:C_0603_1608Metric", 70, 102,
             {"1": "INP", "2": "PGND"}, rating="50 V C0G",
             note="1 us with the 10k divider Thevenin"),
        Part("R4", "Device:R", "470k 1%", "Resistor_SMD:R_0603_1608Metric", 96, 64,
             {"1": "INP", "2": "OUT"}, note="positive feedback: 3.2 A hysteresis"),
        Part("D1", "Device:D_Schottky", "BAT54", "Diode_SMD:D_SOD-123", 58, 66,
             {"1": "INP", "2": "PGND"}, rating="30 V",
             note="cathode at IN+: holds the pin above -0.3 V"),
        Part("D2", "Device:D_Schottky", "BAT54", "Diode_SMD:D_SOD-123", 58, 56,
             {"1": "V5", "2": "INP"}, rating="30 V",
             note="cathode at V5: starts conducting above 5.3 V"),
        Part("R5", "Device:R", "100R", "Resistor_SMD:R_0603_1608Metric", 108, 80,
             {"1": "OUT", "2": "Q1G"}, note="gate series"),
        Part("R6", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric", 120, 92,
             {"1": "Q1G", "2": "PGND"},
             note="Q1 off while the comparator is unpowered"),
        Part("Q1", "Transistor_FET:Q_NMOS_GSD", "2N7002", SMD, 120, 74,
             {"1": "Q1G", "2": "PGND", "3": "FAST_TRIP"}, rating="60 V",
             note="open-drain output; overcurrent pulls FAST_TRIP low"),
        Part("R7", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric", 134, 62,
             {"1": "V5", "2": "FAST_TRIP"},
             note="standalone pull-up; parallels D0 R15 when wired in"),
        Part("R8", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric", 104, 96,
             {"1": "PGND", "2": "SHDN"},
             note="SHDN low enables the comparator; 2 pA bias -> 20 nV across 10k"),
        Part("#FLG1", "power:PWR_FLAG", "PWR_FLAG", "", 40, 36, {"1": "V5"}, "",
             "ERC: bench supply is the source"),
        Part("#FLG2", "power:PWR_FLAG", "PWR_FLAG", "", 52, 36, {"1": "PGND"}, "",
             "ERC: return is a source"),
    ]
    ps += [
        Part(ref, "Connector:TestPoint", net, "TestPoint:TestPoint_Pad_D1.0mm",
             30 + 14 * i, 130, {"1": net}, "1 mm pad", "scope probe")
        for i, (ref, net) in enumerate([
            ("TP1", "OCD"), ("TP2", "INP"), ("TP3", "REF"), ("TP4", "OUT"),
            ("TP5", "FAST_TRIP"), ("TP6", "SHDN"), ("TP7", "V5"), ("TP8", "PGND"),
        ])
    ]
    return ps


# ------------------------------------------------------------------ physics
def divider() -> dict:
    """Trip and release currents through the real three-resistor network."""
    g = 1.0 / (1.0 / R_TOP + 1.0 / R_BOT + 1.0 / R_HYST)

    def ocd_for(out_v: float) -> float:
        return (VREF / g - out_v / R_HYST) * R_TOP

    up, down = ocd_for(0.0), ocd_for(V5)
    rth = 1.0 / (1.0 / R_TOP + 1.0 / R_BOT)
    return {
        "divider_ratio": R_BOT / (R_TOP + R_BOT),
        "nominal_trip_current_a": VREF * (R_TOP + R_BOT) / R_BOT / BURDEN_V_PER_A,
        "trip_burden_v": up,
        "release_burden_v": down,
        "trip_current_a": up / BURDEN_V_PER_A,
        "release_current_a": down / BURDEN_V_PER_A,
        "hysteresis_v": up - down,
        "hysteresis_a": (up - down) / BURDEN_V_PER_A,
        "thevenin_ohm": rth,
        "input_tau_s": C_IN * rth,
    }


def common_mode() -> dict:
    """Where the input pin sits for every published fault current."""
    rows = []
    for name, current in KNOWN_PEAKS_A.items():
        burden = current * BURDEN_V_PER_A
        inp = burden * R_BOT / (R_TOP + R_BOT)
        rows.append({
            "case": name,
            "primary_peak_a": current,
            "burden_v": burden,
            "in_plus_v": inp,
            "within_common_mode": CM_LOW <= inp <= V5 - CM_HIGH_MARGIN,
            "within_absolute_max": CM_LOW - ABS_MAX_MARGIN <= inp
                                   <= V5 + ABS_MAX_MARGIN,
        })
    return {
        "common_mode_range_v": [CM_LOW, V5 - CM_HIGH_MARGIN],
        "absolute_max_range_v": [CM_LOW - ABS_MAX_MARGIN, V5 + ABS_MAX_MARGIN],
        "current_at_common_mode_limit_a": (V5 - CM_HIGH_MARGIN) * 3 / BURDEN_V_PER_A,
        "current_at_clamp_conduction_a": (V5 + ABS_MAX_MARGIN) * 3 / BURDEN_V_PER_A,
        "rows": rows,
    }


def delay() -> dict:
    """Worst-case module delay, and the status quo it replaces."""
    d = divider()
    gate_tau = R_GATE * C_GATE
    module = d["input_tau_s"] + TPD_MAX_5MV_OVER_TEMP + 5 * gate_tau
    existing = sum(tau for _, tau in EXISTING_TAUS) + LM393_TPD_TYP
    return {
        "input_tau_s": d["input_tau_s"],
        "comparator_worst_s": TPD_MAX_5MV_OVER_TEMP,
        "comparator_typ_s": TPD_TYP_20MV,
        "gate_network_s": 5 * gate_tau,
        "module_total_s": module,
        "existing_path": [{"stage": name, "tau_s": tau} for name, tau in EXISTING_TAUS],
        "existing_path_comparator_s": LM393_TPD_TYP,
        "existing_path_total_s": existing,
        "improvement_factor": existing / module,
        "worst_case_basis": "5 mV overdrive, -40 to +125 C, 12 ns",
        "note": "the existing figure is a sum of cascaded time constants, not a "
                "propagation delay; it is an order-of-magnitude comparison only",
    }


SR_BOARD = ROOT / "pcb" / "sr_fault_validation" / "sr_fault_validation.json"


def system_delay() -> dict:
    """The roadmap's whole-machine t_stop, not just this module.

    ``t_stop = t_CT/rectifier/filter + t_cmp + t_common_logic + max(t_primary, t_SR)``

    The module only owns the first two terms.  The shutdown branches come from
    the single-pair SR board's ``delay_budget``, which is read rather than
    re-derived so the two documents cannot drift.  On this machine the SR
    branch wins by an order of magnitude: the UCC24624 does not let go of VG
    until REG has fallen through UVLO.

    The SR board's own 10 us fault-input RC is excluded -- it belongs to that
    validation board's front end, not to the main board's latch output.
    """
    if not SR_BOARD.is_file():
        raise SystemExit(f"{SR_BOARD} is missing; run tools/make_sr_fault_board.py first")
    sr = json.loads(SR_BOARD.read_text(encoding="utf-8"))["delay_budget"]
    branch = sr["sr_branch"]
    sr_branch = (branch["crowbar_fet_turn_on_s"] + branch["reg_to_uvlo_s"]
                 + branch["vg_active_low_s"])
    primary_branch = sr["primary_branch_reference"]["total_s"]
    slowest = max(sr_branch, primary_branch)
    module = delay()["module_total_s"]
    existing = delay()["existing_path_total_s"]
    return {
        "equation": "t_stop = t_CT/rectifier/filter + t_cmp + t_common_logic "
                    "+ max(t_primary, t_SR)",
        "detection_module_s": module,
        "common_logic_s": None,
        "common_logic_note": "the D0 CD4013 latch and its gating are not modelled here, so "
                             "every total below is a floor, not a worst case",
        "sr_branch_s": sr_branch,
        "sr_branch_terms": {
            "crowbar_fet_turn_on_s": branch["crowbar_fet_turn_on_s"],
            "reg_to_uvlo_s": branch["reg_to_uvlo_s"],
            "vg_active_low_s": branch["vg_active_low_s"],
            "excluded_input_rc_s": branch["input_rc_s"],
            "excluded_input_rc_reason": "the 10 us RC is the validation board's front end, "
                                        "not the main board's fault path",
        },
        "primary_branch_s": primary_branch,
        "slowest_branch": "sr" if sr_branch > primary_branch else "primary",
        "system_floor_s": module + slowest,
        "existing_system_floor_s": existing + slowest,
        "system_improvement_factor": (existing + slowest) / (module + slowest),
        "note": "the 121x module figure is a detection-only comparison; against the whole "
                "machine the comparator change is worth the ratio below, because the REG "
                "crowbar sets the stop time",
    }


def supply() -> dict:
    bias = (V5 - VREF) / R_BIAS
    return {
        "bias_current_a": bias,
        "reference_holds_down_to_v": VREF,
        "shutdown_enable_threshold_v": SHDN_ENABLE_BELOW,
        "shutdown_logic": "SHDN low enables; within 0.9 V of V+ disables",
        "quiescent_current_max_a": IQ_MAX,
        "loss_of_5v": "reference and comparator dead; R6 holds Q1 off, so "
                      "FAST_TRIP is released -- no false trip, but no fast "
                      "protection either",
        "minimum_reference_current": "UNVERIFIED - the LM4040DBZ-2.5 minimum "
                                     "operating current is not in this repository",
    }


def observations() -> list[dict]:
    d, dl, cm = divider(), delay(), common_mode()
    sd = system_delay()
    return [
        {
            "id": "OC-01",
            "finding": "The LM393 is not the bottleneck: the three filters in "
                       "front of it total ~127.6 us of time constants.",
            "evidence": "D0 ct_parts Rf/Cf, Rd1/Rd2/Coc, R12/C13",
            "status": "DESIGN_FACT",
        },
        {
            "id": "OC-02",
            "finding": f"The module trips at {d['trip_current_a']:.1f} A peak "
                       f"({d['trip_burden_v']:.2f} V burden) and releases at "
                       f"{d['release_current_a']:.1f} A; the nominal divider "
                       f"crossing is {d['nominal_trip_current_a']:.1f} A.",
            "evidence": f"divider arithmetic against the {CMP} reference and "
                        "the project CT transfer 0.1 V/A",
            "status": "DESIGN_ESTIMATE",
        },
        {
            "id": "OC-03",
            "finding": f"Total module delay is ~{dl['module_total_s'] * 1e6:.2f} us "
                       f"using the 12 ns over-temperature comparator number, "
                       f"about {dl['improvement_factor']:.0f}x faster than the "
                       "existing filtered path.",
            "evidence": f"{CMP} switching characteristics, overdrive 5 mV, "
                        "-40 to +125 C",
            "status": "DESIGN_ESTIMATE",
        },
        {
            "id": "OC-03b",
            "finding": f"That 121x is detection only. With the SR board's shutdown branch "
                       f"added, the whole-machine stop goes from "
                       f"~{sd['existing_system_floor_s'] * 1e6:.1f} us to "
                       f"~{sd['system_floor_s'] * 1e6:.1f} us -- "
                       f"{sd['system_improvement_factor']:.1f}x -- because the "
                       f"{sd['slowest_branch']} branch sets it. D0's latch is not "
                       "modelled, so both are floors.",
            "evidence": "pcb/sr_fault_validation/sr_fault_validation.json:delay_budget",
            "status": "DESIGN_ESTIMATE",
        },
        {
            "id": "OC-04",
            "finding": "The input pin stays inside the common-mode range up to "
                       f"{cm['current_at_common_mode_limit_a']:.0f} A peak. "
                       "Above that the comparator is out of range but still "
                       "inside its absolute maximum, so it is already tripped "
                       "and the output state no longer matters.",
            "evidence": f"{CMP} common-mode range (V-)-0.2 V to (V+)-0.2 V, "
                        "absolute maximum (V-)-0.3 V to (V+)+0.3 V",
            "status": "BOUNDARY",
        },
        {
            "id": "OC-05",
            "finding": "The threshold sits above the 73.68 A peak of the frozen "
                       "short-circuit deck, so that case is left to the "
                       "controller's own overcurrent. The module is aimed at the "
                       "84-101 A severe faults.",
            "evidence": "design/v3/power_priority: lr_design.json PHYSICAL_PEAKS "
                        "and the hotfault prefixes",
            "status": "DESIGN_DECISION",
        },
        {
            "id": "OC-06",
            "finding": "SHDN tied high would disable the comparator; it is tied "
                       "to PGND through R8.",
            "evidence": f"{CMP} shutdown section: high (within 0.9 V of V+) "
                        "disables, more than 1.7 V below V+ enables",
            "status": "DESIGN_FACT",
        },
        {
            "id": "OC-07",
            "finding": "The module does not latch; the CD4013 on D0 does. Used "
                       "standalone, the output follows the current.",
            "evidence": "D0 FAST_TRIP net and CD4013 unit 4",
            "status": "DESIGN_FACT",
        },
    ]


def report(ps: list[Part]) -> dict:
    nets: dict[str, list[str]] = {}
    for part in ps:
        for num, net in part.nets.items():
            nets.setdefault(net, []).append(f"{part.ref}.{num}")
    return {
        "kind": "TLV3501_FAST_OVERCURRENT_ECO_MODULE",
        "evidence_level": "GENERATED_SCHEMATIC_AND_NETLIST_NOT_HARDWARE",
        "hardware_built": False,
        "fabrication_approved": False,
        "part_instances": len(ps),
        "physical_parts": len([p for p in ps if not p.ref.startswith("#")]),
        "nets": len(nets),
        "net_map": {k: sorted(v) for k, v in sorted(nets.items())},
        "threshold": divider(),
        "common_mode": common_mode(),
        "delay": delay(),
        "system_delay": system_delay(),
        "supply": supply(),
        "d0_connection": [
            "J1.1 V5 -> D0 V5 (bench 5 V rail)",
            "J1.2 PGND -> D0 PGND",
            "J1.3 OCD -> D0 R8/OCD node (the burden, before R9)",
            "J1.4 FAST_TRIP -> D0 FAST_TRIP (R15/TP8); both drivers are open drain",
        ],
        "observations": observations(),
        "limits": [
            "module only; the CT, rectifier and burden stay on D0",
            "the system stop is NOT set by this comparator: the SR branch waits for REG to "
            "fall through UVLO, so the whole-machine floor is quoted in system_delay",
            "D0's CD4013 latch propagation is not modelled, so system_delay totals are floors",
            "no latch, no isolation, no reverse-supply protection beyond D2",
            "the LM4040DBZ-2.5 minimum operating current is unverified, so the "
            "low-supply corner is not characterised",
            "a clean ERC only says the drawing agrees with itself",
        ],
    }


# ------------------------------------------------------------------ driver
def instance(part: Part, symbols: dict[str, str], labels: list[str]) -> str:
    tips = pin_tips(symbols[part.lib])
    on_board = "no" if part.ref.startswith("#") else "yes"
    lines = [
        "\t(symbol",
        f'\t\t(lib_id "{part.lib}")',
        f"\t\t(at {part.x:g} {part.y:g} 0)",
        f"\t\t(unit {part.unit}) (body_style 1)",
        f"\t\t(exclude_from_sim no) (in_bom {on_board}) (on_board {on_board}) "
        f"(in_pos_files {on_board})",
        f'\t\t(dnp {"yes" if part.dnp else "no"})',
        f'\t\t(uuid "{uid(part.ref, "symbol")}")',
        f'\t\t(property "Reference" "{part.ref}" (at {part.x:g} {part.y - 12:g} 0) '
        '(show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
        f'\t\t(property "Value" "{part.value}" (at {part.x:g} {part.y + 12:g} 0) '
        '(show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
        f'\t\t(property "Footprint" "{part.footprint}" (at {part.x:g} {part.y:g} 0) '
        '(hide yes) (show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
        f'\t\t(property "Datasheet" "" (at {part.x:g} {part.y:g} 0) (hide yes) '
        '(show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
        f'\t\t(property "Description" "{part.note}" (at {part.x:g} {part.y:g} 0) '
        '(hide yes) (show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
    ]
    for num in sorted(part.nets, key=int):
        lines.append(f'\t\t(pin "{num}" (uuid "{uid(part.ref, num)}"))')
    lines.append("\t)")
    for num, net in part.nets.items():
        px, py = tips[num]
        labels.append(
            f'\t(label "{net}" (at {part.x + px:g} {part.y - py:g} 0) '
            f'(effects (font (size 1.016 1.016))) '
            f'(uuid "{uid(part.ref, num, "label")}"))')
    return "\n".join(lines)


def schematic(symbols: dict[str, str], parts_: list[Part]) -> str:
    labels: list[str] = []
    instances = [instance(part, symbols, labels) for part in parts_]
    kept: dict[tuple[str, float, float], str] = {}
    for text in labels:
        at = text.split("(at ", 1)[1].split(")", 1)[0]
        net = text.split('"')[1]
        key = (net, *[round(float(v), 3) for v in at.split()[:2]])
        kept.setdefault(key, text)
    body = "\n".join(symbols[k] for k in sorted(symbols))
    return f"""(kicad_sch
\t(version 20260101)
\t(generator "make_fast_oc_eco.py")
\t(generator_version "10.0")
\t(uuid "{uid("root")}")
\t(paper "A4")
\t(title_block
\t\t(title "TLV3501 fast-overcurrent ECO module")
\t\t(date "2026-11-04")
\t\t(rev "A")
\t\t(comment 1 "Taps the CT burden directly; replaces the ~128 us filtered LM393 path.")
\t\t(comment 2 "Open-drain output; wire-OR onto D0 FAST_TRIP.")
\t\t(comment 3 "Generated by tools/make_fast_oc_eco.py.")
\t)
\t(lib_symbols
{body}
\t)
{chr(10).join(instances)}
{chr(10).join(kept.values())}
\t(sheet_instances
\t\t(path "/" (page "1"))
\t)
)
"""


def write_libs(symbols: dict[str, str]) -> None:
    block = symbols["FASTOC:LM4040"].replace(
        '(symbol "FASTOC:LM4040"', '(symbol "LM4040"', 1)
    text = ('(kicad_symbol_lib (version 20241209) (generator "make_fast_oc_eco.py")\n'
            + block[block.index("("):] + "\n)\n")
    (OUT / "FASTOC.kicad_sym").write_text(text, encoding="utf-8")
    (OUT / "sym-lib-table").write_text(
        '(sym_lib_table\n\t(version 7)\n'
        '\t(lib (name "FASTOC")(type "KiCad")(uri "${KIPRJMOD}/FASTOC.kicad_sym")'
        '(options "")(descr ""))\n)\n', encoding="utf-8")


def bom(parts_: list[Part]) -> None:
    path = OUT / "BOM.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Reference", "Value", "Footprint", "Rating", "Note", "DNP",
                    "MPN", "LCSC", "Qty"])
        for part in parts_:
            if part.ref.startswith("#"):
                continue
            w.writerow([part.ref, part.value, part.footprint, part.rating, part.note,
                        "yes" if part.dnp else "", "", "", 1])
    print(f"wrote {path}")


def project_file() -> str:
    return json.dumps({
        "board": {}, "boards": [], "cvpcb": {}, "erc": {},
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": "fast_oc.kicad_pro", "version": 1},
        "net_settings": {}, "pcbnew": {},
        "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
        "sheets": [[uid("root"), "Root"]],
        "text_variables": {},
    }, indent=2) + "\n"


def check() -> None:
    cli = kicad_cli()
    if cli is None:
        raise SystemExit("kicad-cli not found: ERC and netlist export cannot be reproduced")
    sch = OUT / "fast_oc.kicad_sch"
    (OUT / "fast_oc.kicad_pro").write_text(project_file(), encoding="utf-8")
    subprocess.run([str(cli), "sch", "export", "netlist", str(sch),
                    "-o", str(OUT / "fast_oc.net")], check=True)
    subprocess.run([str(cli), "sch", "erc", "--severity-all", str(sch),
                    "-o", str(OUT / "erc.rpt")], check=True)
    subprocess.run([str(cli), "sch", "erc", "--severity-all", "--format", "json",
                    str(sch), "-o", str(OUT / "erc.json")], check=True)
    violations = erc_violations(OUT / "erc.json", newer_than=sch)
    print(f"ERC: {len(violations)} violation(s) at every severity")
    if violations:
        for v in violations:
            print(f"  {v['severity']} {v['type']}: {v['description']}")
        raise SystemExit("ERC is not clean")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    symbols = build_symbols()
    ps = [snap(p) for p in parts()]
    validate(ps, symbols)
    validate_no_coincident_tips(ps, symbols)
    write_libs(symbols)
    path = OUT / "fast_oc.kicad_sch"
    path.write_text(schematic(symbols, ps), encoding="utf-8")
    print(f"wrote {path}")
    bom(ps)
    (OUT / "fast_oc.json").write_text(
        json.dumps(report(ps), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'fast_oc.json'}")
    sd = system_delay()
    print(f"module delay {sd['detection_module_s'] * 1e6:.2f} us; whole-machine floor "
          f"{sd['system_floor_s'] * 1e6:.1f} us (slowest branch: {sd['slowest_branch']}), "
          f"{sd['system_improvement_factor']:.1f}x vs the filtered path")
    if args.check:
        check()


if __name__ == "__main__":
    main()
