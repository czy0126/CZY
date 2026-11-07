"""Generate the native bias-cut ECO for the UCC24624 SR bias.

This is the design-path deliverable from
``docs/2026-11-07_保持审核修复与H1证据路线.md``: an always-on 15 V input, a
controlled SR-bias output, an independent 5 V fault latch, a PERMIT interface,
default-off behaviour, reverse blocking, and a local capacitor discharge.

The module is deliberately **additive**: it sits in series with the SR bias and
does not contain or replace the existing Q41/R44 REG crowbar.  The crowbar is
the only path that crosses REG UVLO in ~12 us; the bias cut is the long-hold
path.  Removing the crowbar because "the bias is cut" is a known-bad change
(see ``docs/2026-11-06_REG保持热边界与偏置关断审核.md`` section 4).

Topology (pin-level source of truth is ``parts()`` below):

    VDD_IN --Q50-- VMID --Q51-- VDD_SR
                 (back-to-back P-MOS, common drain)

    R50 pulls both gates to VDD_IN, so the switch is OFF when nobody drives it.
    Q52 pulls the gates low only when the 5 V logic says ENABLE.
    Q55 is a source follower (gate at VDD_IN, source at VDD_SR) with D50 in
    series with its drain: together they pull the gate up only when VDD_SR
    exceeds VDD_IN, so a back-fed VDD_SR cannot turn Q51 on.  Two simpler
    versions failed in the deck and are recorded so nobody re-derives them:

    * a plain Schottky from VDD_SR to the gate is forward-biased in normal
      operation too; it fought the enable pulldown and left the pair in its
      linear region (14.44 V out of 15 V at 13 ms);
    * the follower without D50 leaks backwards through its own body diode
      (anode = drain, cathode = source) for as long as R50 holds the gate
      high, which is the entire off state (13.3 V measured on a cut output).

    With D50 in series, the channel is off in normal operation (Vgs = 0) and
    Q55's body diode faces the wrong way, so neither state has a leak path.

    5 V domain (separate connector J7):
      FAULT_G -> Q53 -> FLT_N -> U50A -> FLT_H
      SET  = FLT_H OR POR              (U53A)
      RST  = RESET_CMD AND FLT_N       (U52A)
      U51A CD4013B, set-dominant, CLK=D=0
      ENABLE = PERMIT AND /LATCHED     (U52B)
      ENABLE_N -> Q54 + R57 discharges VDD_SR; R58 is the passive bleed.

``TO_SELECT`` is a real outcome, not a placeholder to be filled silently: the
repository holds no P-channel MOSFET datasheet and external datasheet
acquisition is blocked in this environment.  The PMOS row therefore carries the
selection requirements in ``pmos_selection()`` and no invented orderable code.

Usage:
    python tools/make_bias_cut_eco.py
    python tools/make_bias_cut_eco.py --check   # netlist + ERC + report
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

import make_d0_protection_board as d0
from main_board_mechanical import find_kicad_cli

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "pcb" / "bias_cut_eco"
NS = uuid.UUID("8f6c2a1d-4b7e-4a90-9c15-2d3e5f607182")

NC = "#NC"
DIP14 = "Package_DIP:DIP-14_W7.62mm"
SOT23 = "Package_TO_SOT_SMD:SOT-23"
SOD123 = "Diode_SMD:D_SOD-123"
R0805 = "Resistor_SMD:R_0805_2012Metric"
R1206 = "Resistor_SMD:R_1206_3216Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
C1210 = "Capacitor_SMD:C_1210_3225Metric"
HDR2 = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
HDR4 = "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"
TP = "TestPoint:TestPoint_Pad_D1.0mm"

# Vendored datasheets.  A part number is written only when one of these files
# carries the orderable code; everything else stays TO_SELECT.
DS_2N7002 = "references/datasheets/2n7002lt1g_onsemi_oem_parameters.txt"
DS_BAT54W = "references/datasheets/bat54w.txt"
DS_4013 = "references/datasheets/cd4013b.txt"
DS_4069 = "references/datasheets/cd4069ub.txt"
DS_4071 = "references/datasheets/cd4071b.txt"
DS_4081 = "references/datasheets/cd4081b.txt"
DS_AO3400 = "references/datasheets/ao3400a.txt"


@dataclass(frozen=True)
class Part:
    ref: str
    lib: str
    value: str
    footprint: str
    x: float
    y: float
    nets: dict[str, str]
    rating: str = ""
    note: str = ""
    dnp: bool = False
    unit: int = 1
    source: str = "DESIGN_PROPOSAL"
    mpn: str = ""
    mpn_source: str = "TO_SELECT"


def uid(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


def kicad_cli() -> Path | None:
    return find_kicad_cli()


def symbol_libs() -> Path:
    cli = kicad_cli()
    if cli is None:
        raise SystemExit("kicad-cli not found; set KICAD_CLI to regenerate symbols")
    return cli.parent.parent / "share" / "kicad" / "symbols"


STANDARD = {
    "Device:R": ("Device.kicad_sym", "R"),
    "Device:C": ("Device.kicad_sym", "C"),
    "Device:D_Schottky": ("Device.kicad_sym", "D_Schottky"),
    "4xxx:4013": ("4xxx.kicad_sym", "4013"),
    "4xxx:4069": ("4xxx.kicad_sym", "4069"),
    "4xxx:4071": ("4xxx.kicad_sym", "4071"),
    "4xxx:4081": ("4xxx.kicad_sym", "4081"),
    "Transistor_FET:Q_PMOS_GSD": ("Transistor_FET.kicad_sym", "Q_PMOS_GSD"),
    "Transistor_FET:Q_NMOS_GSD": ("Transistor_FET.kicad_sym", "Q_NMOS_GSD"),
    "Connector_Generic:Conn_01x02": ("Connector_Generic.kicad_sym", "Conn_01x02"),
    "Connector_Generic:Conn_01x04": ("Connector_Generic.kicad_sym", "Conn_01x04"),
    "Connector:TestPoint": ("Connector.kicad_sym", "TestPoint"),
    "power:PWR_FLAG": ("power.kicad_sym", "PWR_FLAG"),
}


def build_symbols() -> dict[str, str]:
    """Native cached symbol blocks; the committed schematic is the CI fallback.

    CI has no KiCad.  Rebuilding from the committed schematic keeps the test
    suite runnable there and still checks that every block in the file is the
    one the part table asks for.
    """
    symbols: dict[str, str] = {}
    cli = kicad_cli()
    libs = symbol_libs() if cli is not None else None
    source = OUT / "bias_cut_eco.kicad_sch"
    if libs is None and not source.is_file():
        raise SystemExit("KiCad symbols unavailable: install KiCad or provide the committed schematic")
    for lib_id, (lib, name) in STANDARD.items():
        if libs is None:
            symbols[lib_id] = d0.extract_symbol(source, lib_id)
        else:
            symbols[lib_id] = d0.rename_symbol(d0.extract_symbol(libs / lib, name), lib_id)
    return symbols


# ---------------------------------------------------------------- parts
def power_switch_parts() -> list[Part]:
    """The always-on input, the two P-MOS, and the default-off gate network."""
    return [
        Part("J6", "Connector_Generic:Conn_01x04", "15V IN / SR BIAS OUT", HDR4, 40, 60,
             {"1": "VDD_IN", "2": "VDD_SR", "3": "PGND", "4": "PGND"}, "15 V, 1 A",
             "pin 1 always-on 15 V; pin 2 switched SR bias; pins 3-4 return"),
        Part("Q50", "Transistor_FET:Q_PMOS_GSD", "P-MOS TO_SELECT", SOT23, 90, 60,
             {"1": "BC_GATE", "2": "VDD_IN", "3": "VMID"}, "30 V",
             "input-side pass device; source at VDD_IN, drain at VMID",
             mpn="", mpn_source="TO_SELECT"),
        Part("Q51", "Transistor_FET:Q_PMOS_GSD", "P-MOS TO_SELECT", SOT23, 120, 60,
             {"1": "BC_GATE", "2": "VDD_SR", "3": "VMID"}, "30 V",
             "output-side pass device; source at VDD_SR, drain at VMID; body diodes oppose Q50",
             mpn="", mpn_source="TO_SELECT"),
        Part("R50", "Device:R", "100k", R0805, 70, 50,
             {"1": "VDD_IN", "2": "BC_GATE"}, "1/10 W",
             "default-off pull-up; 100k keeps the VDD_SR->VDD_IN bleed at ~27 uA "
             "and turns off in ~14 us with 60 pF of gate capacitance"),
        Part("Q55", "Transistor_FET:Q_PMOS_GSD", "P-MOS TO_SELECT", SOT23, 105, 75,
             {"1": "VDD_IN", "2": "VDD_SR", "3": "BC_FB"}, "30 V",
             "gate-follow source follower: gate at VDD_IN, source at VDD_SR, "
             "drain at BC_FB. Vgs is zero in normal operation, so it neither "
             "injects into the gate nor loads the enable pulldown; it conducts "
             "only when VDD_SR is back-fed above VDD_IN",
             mpn="", mpn_source="TO_SELECT"),
        Part("D50", "Device:D_Schottky", "BAT54W", SOD123, 105, 90,
             {"1": "BC_GATE", "2": "BC_FB"}, "30 V 200 mA",
             "pin 1 is the cathode; in series with Q55's drain. Without it "
             "Q55's body diode (anode = drain, cathode = source) conducts "
             "BC_GATE -> VDD_SR whenever R50 has the gate high, which is the "
             "whole off state: the deck read 13.3 V on a cut output",
             mpn="BAT54W-E3-08", mpn_source=DS_BAT54W),
        Part("Q52", "Transistor_FET:Q_NMOS_GSD", "2N7002", SOT23, 70, 80,
             {"1": "ENABLE", "2": "PGND", "3": "BC_GATE"}, "60 V",
             "pulls the P-MOS gates low only when the 5 V logic says ENABLE",
             mpn="2N7002LT1G", mpn_source=DS_2N7002),
        Part("R52", "Device:R", "100k", R0805, 50, 80,
             {"1": "ENABLE", "2": "PGND"}, "1/10 W",
             "second default-off: ENABLE is low if the logic is unpowered or floating"),
        Part("R57", "Device:R", "47R", R1206, 150, 60,
             {"1": "VDD_SR", "2": "VDD_DIS"}, "1/4 W, pulse",
             "active-discharge resistor; 47R * 3.3 uF = 155 us, 0.37 mJ per event"),
        Part("Q54", "Transistor_FET:Q_NMOS_GSD", "AO3400A", SOT23, 150, 80,
             {"1": "ENABLE_N", "2": "PGND", "3": "VDD_DIS"}, "30 V 5.7 A",
             "local capacitor discharge; on whenever the bias is disabled",
             mpn="AO3400A", mpn_source=DS_AO3400),
        Part("R58", "Device:R", "100k", R0805, 170, 60,
             {"1": "VDD_SR", "2": "PGND"}, "1/10 W",
             "passive bleed, fail-safe when the 5 V domain is lost; tau ~330 ms"),
        Part("C54", "Device:C", "3.3uF/25V", C1210, 185, 60,
             {"1": "VDD_SR", "2": "PGND"}, "25 V X7R",
             "bench load equal to C1+C2+C3; remove when integrated, the real "
             "UCC24624 VDD capacitance is the load"),
        Part("R62", "Device:R", "1k", R0805, 200, 60,
             {"1": "VDD_SR", "2": "PGND"}, "1/10 W",
             "bench load, ~15 mA at 15 V; remove when integrated"),
    ]


def level_shift_parts() -> list[Part]:
    """The 5 V domain input conditioning and the fault level shifter."""
    return [
        Part("J7", "Connector_Generic:Conn_01x04", "5V / PERMIT / RESET", HDR4, 40, 140,
             {"1": "V5_IND", "2": "PGND", "3": "PERMIT_EXT", "4": "RESET_EXT"},
             "5 V, 10 mA", "independent 5 V control domain; must survive the SR bias cut"),
        Part("R63", "Device:R", "1k", R0805, 55, 150,
             {"1": "PERMIT_EXT", "2": "PERMIT"}, "1/10 W", "series protection for the CMOS input"),
        Part("R60", "Device:R", "100k", R0805, 55, 168,
             {"1": "PERMIT", "2": "PGND"}, "1/10 W", "default PERMIT low = bias off"),
        Part("R64", "Device:R", "1k", R0805, 70, 150,
             {"1": "RESET_EXT", "2": "RESET_CMD"}, "1/10 W", "series protection for the CMOS input"),
        Part("R55", "Device:R", "100k", R0805, 70, 168,
             {"1": "RESET_CMD", "2": "PGND"}, "1/10 W", "default reset low"),
        Part("C51", "Device:C", "1uF/16V", C0805, 85, 150,
             {"1": "V5_IND", "2": "PGND"}, "16 V X7R", "5 V bulk"),
        Part("C52", "Device:C", "100nF/16V", C0805, 95, 150,
             {"1": "V5_IND", "2": "PGND"}, "16 V X7R", "5 V decoupling"),
        Part("J8", "Connector_Generic:Conn_01x02", "FAULT_G", HDR2, 130, 140,
             {"1": "FAULT_IN", "2": "PGND"}, "5.1 V clamp",
             "fault input; the existing R41/R40/C40 network stays on the SR board"),
        Part("R65", "Device:R", "1k", R0805, 140, 140,
             {"1": "FAULT_IN", "2": "FAULT_G"}, "1/10 W", "series protection"),
        Part("R61", "Device:R", "100k", R0805, 140, 156,
             {"1": "FAULT_G", "2": "PGND"}, "1/10 W",
             "default no fault; opposite direction to the fail-safe bias cut, see report"),
        Part("R54", "Device:R", "100k", R0805, 160, 140,
             {"1": "V5_IND", "2": "FLT_N"}, "1/10 W", "open-drain fault pull-up"),
        Part("Q53", "Transistor_FET:Q_NMOS_GSD", "2N7002", SOT23, 175, 150,
             {"1": "FAULT_G", "2": "PGND", "3": "FLT_N"}, "60 V",
             "level shifts the 5.1 V fault node into the 5 V CMOS domain",
             mpn="2N7002LT1G", mpn_source=DS_2N7002),
    ]


def logic_parts() -> list[Part]:
    """CD4069 inverter, CD4013 set-dominant latch, CD4081 AND, CD4071 OR."""
    return [
        Part("U50", "4xxx:4069", "CD4069UBE", DIP14, 200, 150,
             {"1": "FLT_N", "2": "FLT_H"}, "5 V",
             "unit A: inverts the active-low fault node",
             mpn="CD4069UBE", mpn_source=DS_4069),
        Part("U50", "4xxx:4069", "CD4069UBE", DIP14, 200, 150,
             {"3": "ENABLE", "4": "ENABLE_N"}, "5 V",
             "unit B: drives the discharge FET", unit=2,
             mpn="CD4069UBE", mpn_source=DS_4069),
        Part("U50", "4xxx:4069", "CD4069UBE", DIP14, 200, 150,
             {"7": "PGND", "14": "V5_IND"}, "5 V", "power unit", unit=7,
             mpn="CD4069UBE", mpn_source=DS_4069),
        Part("U51", "4xxx:4013", "CD4013BE", DIP14, 300, 190,
             {"1": "LATCHED", "2": "LATCHED_N", "3": "PGND", "4": "RST_EFF",
              "5": "PGND", "6": "SET_LATCH"}, "5 V",
             "unit A: set-dominant latch; CLK=D=0 so only SET/RESET change it",
             mpn="CD4013BE", mpn_source=DS_4013),
        Part("U51", "4xxx:4013", "CD4013BE", DIP14, 300, 190,
             {"7": "PGND", "14": "V5_IND"}, "5 V", "power unit", unit=3,
             mpn="CD4013BE", mpn_source=DS_4013),
        Part("U52", "4xxx:4081", "CD4081BE", DIP14, 260, 200,
             {"1": "RESET_CMD", "2": "FLT_N", "3": "RST_EFF"}, "5 V",
             "unit A: reset is blocked while the fault is present",
             mpn="CD4081BE", mpn_source=DS_4081),
        Part("U52", "4xxx:4081", "CD4081BE", DIP14, 260, 200,
             {"4": "ENABLE", "5": "PERMIT", "6": "LATCHED_N"}, "5 V",
             "unit B: bias on only when permitted and not latched", unit=2,
             mpn="CD4081BE", mpn_source=DS_4081),
        Part("U52", "4xxx:4081", "CD4081BE", DIP14, 260, 200,
             {"7": "PGND", "14": "V5_IND"}, "5 V", "power unit", unit=5,
             mpn="CD4081BE", mpn_source=DS_4081),
        Part("U53", "4xxx:4071", "CD4071BE", DIP14, 230, 180,
             {"1": "FLT_H", "2": "POR", "3": "SET_LATCH"}, "5 V",
             "unit A: fault or power-on sets the latch",
             mpn="CD4071BE", mpn_source=DS_4071),
        Part("U53", "4xxx:4071", "CD4071BE", DIP14, 230, 180,
             {"7": "PGND", "14": "V5_IND"}, "5 V", "power unit", unit=5,
             mpn="CD4071BE", mpn_source=DS_4071),
        Part("R56", "Device:R", "100k", R0805, 105, 168,
             {"1": "POR", "2": "PGND"}, "1/10 W",
             "POR pull-down; C53 to V5 makes POR high at power-up"),
        Part("C53", "Device:C", "100nF/16V", C0805, 105, 182,
             {"1": "POR", "2": "V5_IND"}, "16 V X7R",
             "power-on set pulse: 100k * 100nF = 10 ms"),
    ]


def spare_parts() -> list[Part]:
    """Unused CMOS units: inputs tied to PGND, outputs no-connect.

    CMOS inputs must never float.  Placing every unit also clears KiCad's
    ``missing_unit`` / ``missing_input_pin`` warnings, which are real (an
    unplaced unit is an ungrounded input in the physical package), not noise.
    """
    return [
        # CD4069UB: used A (1/2) and B (3/4); C-F are spares.
        Part("U50", "4xxx:4069", "CD4069UBE", DIP14, 200, 150,
             {"5": "PGND", "6": NC}, "5 V", "spare inverter C", unit=3,
             mpn="CD4069UBE", mpn_source=DS_4069),
        Part("U50", "4xxx:4069", "CD4069UBE", DIP14, 200, 150,
             {"9": "PGND", "8": NC}, "5 V", "spare inverter D", unit=4,
             mpn="CD4069UBE", mpn_source=DS_4069),
        Part("U50", "4xxx:4069", "CD4069UBE", DIP14, 200, 150,
             {"11": "PGND", "10": NC}, "5 V", "spare inverter E", unit=5,
             mpn="CD4069UBE", mpn_source=DS_4069),
        Part("U50", "4xxx:4069", "CD4069UBE", DIP14, 200, 150,
             {"13": "PGND", "12": NC}, "5 V", "spare inverter F", unit=6,
             mpn="CD4069UBE", mpn_source=DS_4069),
        # CD4013B: used A; B is a spare with CLK/D/SET/RESET grounded.
        Part("U51", "4xxx:4013", "CD4013BE", DIP14, 300, 190,
             {"8": "PGND", "9": "PGND", "10": "PGND", "11": "PGND",
              "12": NC, "13": NC}, "5 V",
             "spare flip-flop B; inputs grounded, outputs open", unit=2,
             mpn="CD4013BE", mpn_source=DS_4013),
        # CD4081B: used A and B; C and D are spares.
        Part("U52", "4xxx:4081", "CD4081BE", DIP14, 260, 200,
             {"8": "PGND", "9": "PGND", "10": NC}, "5 V",
             "spare AND C; inputs grounded, output open", unit=3,
             mpn="CD4081BE", mpn_source=DS_4081),
        Part("U52", "4xxx:4081", "CD4081BE", DIP14, 260, 200,
             {"12": "PGND", "13": "PGND", "11": NC}, "5 V",
             "spare AND D; inputs grounded, output open", unit=4,
             mpn="CD4081BE", mpn_source=DS_4081),
        # CD4071B: used A; B-D are spares.
        Part("U53", "4xxx:4071", "CD4071BE", DIP14, 230, 180,
             {"5": "PGND", "6": "PGND", "4": NC}, "5 V",
             "spare OR B; inputs grounded, output open", unit=2,
             mpn="CD4071BE", mpn_source=DS_4071),
        Part("U53", "4xxx:4071", "CD4071BE", DIP14, 230, 180,
             {"8": "PGND", "9": "PGND", "10": NC}, "5 V",
             "spare OR C; inputs grounded, output open", unit=3,
             mpn="CD4071BE", mpn_source=DS_4071),
        Part("U53", "4xxx:4071", "CD4071BE", DIP14, 230, 180,
             {"12": "PGND", "13": "PGND", "11": NC}, "5 V",
             "spare OR D; inputs grounded, output open", unit=4,
             mpn="CD4071BE", mpn_source=DS_4071),
    ]


def test_point_parts() -> list[Part]:
    points = [
        ("TP21", "VDD_IN"), ("TP22", "VDD_SR"), ("TP23", "BC_GATE"),
        ("TP24", "ENABLE"), ("TP25", "ENABLE_N"), ("TP26", "LATCHED"),
        ("TP27", "LATCHED_N"), ("TP28", "FLT_N"), ("TP29", "POR"),
        ("TP30", "V5_IND"), ("TP31", "FAULT_G"), ("TP32", "PGND"),
    ]
    return [Part(ref, "Connector:TestPoint", net, TP, 40 + 15 * i, 250,
                 {"1": net}, "1 mm pad", "scope probe / Kelvin point")
            for i, (ref, net) in enumerate(points)]


def flag_parts() -> list[Part]:
    return [
        Part("#FLG1", "power:PWR_FLAG", "PWR_FLAG", "", 230, 250, {"1": "VDD_IN"}),
        Part("#FLG2", "power:PWR_FLAG", "PWR_FLAG", "", 245, 250, {"1": "VDD_SR"}),
        Part("#FLG3", "power:PWR_FLAG", "PWR_FLAG", "", 260, 250, {"1": "V5_IND"}),
        Part("#FLG4", "power:PWR_FLAG", "PWR_FLAG", "", 275, 250, {"1": "PGND"}),
    ]


def parts() -> list[Part]:
    return (power_switch_parts() + level_shift_parts() + logic_parts()
            + spare_parts() + test_point_parts() + flag_parts())


# ---------------------------------------------------------------- logic
def step(fault: bool, permit: bool, reset: bool, por: bool, latched: bool) -> tuple[bool, bool]:
    """One transition of the set-dominant latch and its enable gate.

    ``SET`` wins over ``RESET``; ``RESET`` is additionally gated by the fault
    (``RST_EFF = RESET_CMD AND /FAULT``), so a fault that is still present can
    never clear the latch.  ``ENABLE = PERMIT AND /LATCHED``.
    """
    set_ = bool(fault or por)
    rst_eff = bool(reset and not fault)
    new = True if set_ else (False if rst_eff else bool(latched))
    return new, bool(permit and not new)


def truth_table() -> list[dict]:
    rows = []
    for fault in (False, True):
        for permit in (False, True):
            for reset in (False, True):
                for por in (False, True):
                    for latched in (False, True):
                        new, enable = step(fault, permit, reset, por, latched)
                        rows.append({"fault": fault, "permit": permit, "reset": reset,
                                     "por": por, "latched_prev": latched,
                                     "latched": new, "enable": enable})
    return rows


def pmos_selection() -> dict:
    """What the P-MOS has to be, because no datasheet in the repo names one."""
    return {
        "mpn": "TO_SELECT",
        "reason": "no P-channel MOSFET datasheet in references/datasheets; "
                  "external acquisition is blocked in this environment, and a "
                  "fabricated orderable code is worse than an empty one",
        "requirements": {
            "vds_min_v": 30,
            "vgs_abs_max_v": 20,
            "id_continuous_min_a": 1.0,
            "id_pulsed_min_a": 3.0,
            "rds_on_max_ohm_at_vgs_minus_10v": 0.1,
            "ciss_max_pf": 100,
            "vgs_th_abs_max_v": 2.5,
            "package": "SOT-23 or SOT-323",
            "body_diode": "standard P-MOS body diode, drain-to-source; the "
                          "common-drain pair must present opposing diodes",
        },
        "why": {
            "vds": "15 V rail plus back-fed VDD_SR; 30 V gives 2x margin",
            "id_pulsed": "C54 (3.3 uF) charges through the switch at turn-on; "
                         "the supply and wiring set the peak, so the part must "
                         "have pulsed headroom. No soft-start is fitted.",
            "ciss": "R50 turn-off is 100k * Ciss; at 100 pF the gate crosses "
                    "Vth in ~14 us, after the ~12 us crowbar has already crossed REG UVLO",
            "rds_on": "the SR bias is ~15 mA; 0.1 ohm is 1.5 mV, not a "
                      "thermal constraint, but keeps the pass drop negligible",
            "vgs_th": "Q55 is a source follower driven by VDD_IN; it can only "
                      "lift the gate when the back-fed VDD_SR exceeds VDD_IN by "
                      "more than |Vth|. With a 3 V backfeed the part has to be a "
                      "logic-level P-MOS, |Vth| <= 2.5 V at the quoted test "
                      "current, or Q51 stays partly on",
        },
        "not_acceptable": "BSS84-class parts are not automatically acceptable: "
                          "no datasheet is held, and the 3.3 uF turn-on pulse is "
                          "outside a small-signal default assumption.",
    }


def integration() -> dict:
    return {
        "cut_points": {
            "VDD_IN": "existing SR board VDD_IN, after D2 (SS34)",
            "VDD_SR": "existing SR board VDD node; JP1 stays between VDD_SR and "
                      "VDD as a service disconnect, not as the protection",
            "FAULT_G": "existing R40/R41/C40 node, shared with the Q41/R44 crowbar",
            "PGND": "existing SR board PGND",
        },
        "preserved_fast_path": "Q41 + R44 remain directly driven by FAULT_G. This "
                               "module does not include, bypass, or delay them.",
        "removed_from_module_when_integrated": ["C54", "R62"],
        "five_volt_source": "J7 must be fed from a 5 V rail that survives the SR "
                            "bias cut. If that rail is lost, the P-MOS gate is "
                            "pulled to VDD_IN by R50, so the bias is removed "
                            "(fail-safe), but the latch is also unpowered.",
    }


def observations() -> list[dict]:
    return [
        {"item": "default state",
         "finding": "R50 pulls BC_GATE to VDD_IN, R52 pulls ENABLE low, and R60 "
                    "pulls PERMIT low. A floating or unpowered control domain "
                    "leaves the switch off.",
         "evidence": "topology + truth_table"},
        {"item": "set dominates reset",
         "finding": "SET = FLT_H OR POR is evaluated before RST_EFF; a fault that "
                    "is still present cannot be cleared by RESET_CMD.",
         "evidence": "step() exhaustive enumeration"},
        {"item": "no auto-reset",
         "finding": "when SET and RST_EFF are both false the latch holds. A fault "
                    "that disappears does not restore the bias.",
         "evidence": "truth_table rows with fault=False, por=False, reset=False"},
        {"item": "reverse blocking",
         "finding": "Q50/Q51 share a drain (VMID) so their body diodes oppose. "
                    "With the switch off, neither body diode conducts from "
                    "VDD_IN or VDD_SR into VMID. Q55 + D50 pull the gate up "
                    "with VDD_SR when VDD_SR is back-fed above VDD_IN, and D50 "
                    "also blocks Q55's body diode in the off state. Residual: "
                    "VDD_SR -> Q55 -> D50 -> R50 -> VDD_IN is ~30 uA at "
                    "VDD_SR=18 V; it is a bleed in the safe direction, not "
                    "switch conduction.",
         "evidence": "topology + reverse deck"},
        {"item": "local capacitor discharge",
         "finding": "when ENABLE is low, ENABLE_N is high and Q54+R57 discharge "
                    "VDD_SR; R58 is the passive bleed if the 5 V domain is lost. "
                    "47 ohm * 3.3 uF is 155 us, ~220 us to 3.63 V.",
         "evidence": "topology + sequence deck"},
        {"item": "fault input default",
         "finding": "R61 pulls FAULT_G low, so a disconnected fault source reads "
                    "as no-fault. This is the existing fail-open input policy and "
                    "is deliberately opposite to the fail-safe bias cut; they are "
                    "different circuits, see "
                    "docs/2026-11-06_REG保持热边界与偏置关断审核.md section 4.",
         "evidence": "topology + report"},
        {"item": "timing split",
         "finding": "the crowbar crosses REG UVLO in ~12.11 us (existing estimate); "
                    "the 5 V logic adds <1 us; the gate network adds ~14 us; the "
                    "local discharge adds ~220 us. The crowbar is the fast path, "
                    "the bias cut is the long-hold path.",
         "evidence": "arithmetic; the gate time uses an assumed 60 pF Ciss"},
        {"item": "what is not proven",
         "finding": "no hardware, no thermal sign-off, no measured reverse "
                    "backfeed into VDD/REG, no SOA for the P-MOS turn-on pulse.",
         "evidence": "report flags"},
    ]


# ---------------------------------------------------------------- schematic
def origin(part: Part) -> tuple[float, float]:
    return part.x + 11.43 * (part.unit - 1), part.y - 11.43 * (part.unit - 1)


def pin_tip_positions(part: Part, symbols: dict[str, str]) -> dict[str, tuple[float, float]]:
    tips = d0.pin_tips(symbols[part.lib])
    x, y = origin(part)
    return {num: (round(x + tips[num][0], 3), round(y - tips[num][1], 3)) for num in part.nets}


def validate(ps: list[Part], symbols: dict[str, str]) -> None:
    seen: set[str] = set()
    for part in ps:
        key = f"{part.ref}#{part.unit}"
        if key in seen:
            raise SystemExit(f"duplicate reference/unit {key}")
        seen.add(key)
        if part.lib not in symbols:
            raise SystemExit(f"{part.ref}: unknown symbol {part.lib}")
        nums = d0.unit_pin_numbers(symbols[part.lib], part.unit)
        if not nums:
            raise SystemExit(f"{part.ref}: unit {part.unit} not in {part.lib}")
        if set(nums) != set(part.nets):
            raise SystemExit(f"{part.ref} unit {part.unit}: pins {numbers(nums)} != nets {sorted(part.nets)}")
        for net in part.nets.values():
            if net != NC and (not net or " " in net):
                raise SystemExit(f"{part.ref}: bad net name {net!r}")
    d0.validate_no_coincident_tips(ps, symbols)


def numbers(values: list[str]) -> list[str]:
    return sorted(set(values), key=lambda s: int(s))


def nets_of(ps: list[Part]) -> dict[str, list[str]]:
    return d0.nets_of(ps)


def instance(part: Part, symbols: dict[str, str], labels: list[str],
             no_connects: list[str]) -> str:
    positions = pin_tip_positions(part, symbols)
    x, y = origin(part)
    on_board = "no" if part.ref.startswith("#") else "yes"
    in_bom = "no" if part.ref.startswith("#") else "yes"
    lines = [
        "\t(symbol",
        f'\t\t(lib_id "{part.lib}")',
        f"\t\t(at {x:g} {y:g} 0)",
        f"\t\t(unit {part.unit}) (body_style 1)",
        f"\t\t(exclude_from_sim no) (in_bom {in_bom}) (on_board {on_board}) (in_pos_files {on_board})",
        f'\t\t(dnp {"yes" if part.dnp else "no"})',
        f'\t\t(uuid "{uid(part.ref, str(part.unit), "symbol")}")',
        f'\t\t(property "Reference" "{part.ref}" (at {x:g} {y - 12:g} 0) '
        '(show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
        f'\t\t(property "Value" "{part.value}" (at {x:g} {y + 12:g} 0) '
        '(show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
        f'\t\t(property "Footprint" "{part.footprint}" (at {x:g} {y:g} 0) '
        '(hide yes) (show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
        f'\t\t(property "Datasheet" "" (at {x:g} {y:g} 0) (hide yes) '
        '(show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
        f'\t\t(property "Description" "{part.note}" (at {x:g} {y:g} 0) (hide yes) '
        '(show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
    ]
    for num in sorted(part.nets, key=lambda s: int(s)):
        lines.append(f'\t\t(pin "{num}" (uuid "{uid(part.ref, str(part.unit), num)}"))')
    lines.append("\t)")
    for num, net in part.nets.items():
        ax, ay = positions[num]
        suffix = uid(part.ref, str(part.unit), num, "label")
        if net == NC:
            no_connects.append(f'\t(no_connect (at {ax:g} {ay:g}) (uuid "{suffix}"))')
        else:
            labels.append(
                f'\t(label "{net}" (at {ax:g} {ay:g} 0) '
                f'(effects (font (size 1.016 1.016))) (uuid "{suffix}"))'
            )
    return "\n".join(lines)


def schematic(symbols: dict[str, str], parts_: list[Part]) -> str:
    labels: list[str] = []
    no_connects: list[str] = []
    instances = [instance(p, symbols, labels, no_connects) for p in parts_]
    kept: dict[tuple[str, float, float], str] = {}
    for text in labels:
        at = text.split("(at ", 1)[1].split(")", 1)[0]
        net = text.split('"')[1]
        key = (net, *[round(float(v), 3) for v in at.split()[:2]])
        kept.setdefault(key, text)
    body = "\n".join(symbols[k] for k in sorted(symbols))
    return f"""(kicad_sch
	(version 20260101)
	(generator "make_bias_cut_eco.py")
	(generator_version "10.0")
	(uuid "{uid("root")}")
	(paper "A2")
	(title_block
		(title "Bias-cut ECO for the UCC24624 SR bias")
		(date "2026-11-07")
		(rev "A")
		(comment 1 "Native ECO proposal. NOT built, NOT thermal-qualified, NOT a replacement for the Q41/R44 crowbar.")
		(comment 2 "Generated by tools/make_bias_cut_eco.py; the part table is the source of truth.")
		(comment 3 "P-MOS is TO_SELECT: no P-channel datasheet in the repository.")
	)
	(lib_symbols
{body}
	)
{chr(10).join(instances)}
{chr(10).join(kept.values())}
{chr(10).join(no_connects)}
	(sheet_instances
		(path "/" (page "1"))
	)
)
"""


def snap(part: Part) -> Part:
    return replace(part, x=round(part.x / 1.27) * 1.27, y=round(part.y / 1.27) * 1.27)


def physical_components(parts_: list[Part]) -> list[Part]:
    return d0.physical_components(parts_)


def bom(parts_: list[Part]) -> None:
    path = OUT / "BOM.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Reference", "Value", "Footprint", "Rating", "Note", "DNP",
                    "MPN", "MPN_Source", "LCSC", "Qty"])
        for part in physical_components(parts_):
            w.writerow([part.ref, part.value, part.footprint, part.rating, part.note,
                        "yes" if part.dnp else "", part.mpn, part.mpn_source, "", 1])
    print(f"wrote {path}")


def project_file() -> str:
    return json.dumps({
        "board": {"design_settings": {"rule_severities": {"missing_courtyard": "error"}}},
        "boards": [], "cvpcb": {}, "erc": {},
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": "bias_cut_eco.kicad_pro", "version": 1},
        "net_settings": {}, "pcbnew": {},
        "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
        "sheets": [[uid("root"), "Root"]],
        "text_variables": {},
    }, indent=2) + "\n"


# ---------------------------------------------------------------- decks
def sequence_deck() -> str:
    """Behavioural logic + switch deck.  Not a device-accurate model.

    The 5 V gates are behavioural so the deck tests the *logic*, not a CMOS
    input model.  The P-MOS is two voltage-controlled switches with body
    diodes; the body-diode orientation is the part of the deck that matters
    for reverse blocking.
    """
    return """* Bias-cut ECO sequence: default off -> explicit reset -> fault -> hold -> reset
* Behavioural logic and switch model; NOT device-accurate, NOT thermal.
.param VDD=15 V5=5
V1 VDD_IN 0 {VDD}
V5S V5_IND 0 {V5}
VPERMIT PERMIT_EXT 0 5
* The POR time constant is R56 * C53 = 100k * 100nF = 10 ms, so POR crosses the
* 2.5 V CMOS threshold at 10 ms * ln(5/2.5) = 6.9 ms.  The first reset is placed
* at 10 ms, after POR has decayed; a reset during POR would be correctly ignored.
VRESET RESET_EXT 0 PWL(0 0 10m 0 10.001m 5 10.01m 5 10.011m 0
+ 25m 0 25.001m 5 25.01m 5 25.011m 0)
VFAULT FAULT_IN 0 PWL(0 0 15m 0 15.001m 5 15.1m 5 15.101m 0)
R63 PERMIT_EXT PERMIT 1k
R60 PERMIT 0 100k
R64 RESET_EXT RESET_CMD 1k
R55 RESET_CMD 0 100k
R65 FAULT_IN FAULT_G 1k
R61 FAULT_G 0 100k
R56 POR 0 100k
C53 POR V5_IND 100n ic=0
R54 V5_IND FLT_N 100k
S53 FLT_N 0 FAULT_G 0 SWLOG
.model SWLOG SW(Ron=10 Roff=1Meg Vt=2.5 Vh=0.2)
B_FLTH FLT_H 0 V=if(V(FLT_N)<2.5,5,0)
B_SET SET_LATCH 0 V=if(V(FLT_H)>2.5 | V(POR)>2.5,5,0)
B_RST RST_EFF 0 V=if(V(RESET_CMD)>2.5 & V(FLT_N)>2.5,5,0)
* ic=5: a real CD4013 comes up in an arbitrary state, but POR forces SET
* within nanoseconds of V5 rising, so "set" is the state the circuit is
* actually in.  Without it the node starts at 0, ENABLE is briefly high and
* the switch conducts a 3.3 uF charge pulse that exists only in the model.
C_L LATCHED 0 1n ic=5
R_L LATCHED 0 1G
B_L 0 LATCHED I=if(V(SET_LATCH)>2.5,(5-V(LATCHED))/1k,
+ if(V(RST_EFF)>2.5,(0-V(LATCHED))/1k,0))
B_LN LATCHED_N 0 V=5-V(LATCHED)
B_EN ENABLE 0 V=if(V(PERMIT)>2.5 & V(LATCHED_N)>2.5,5,0)
B_ENN ENABLE_N 0 V=if(V(ENABLE)>2.5,0,5)
R50 VDD_IN BC_GATE 100k
S52 BC_GATE 0 ENABLE 0 SWEN
* Roff=1G: a 2N7002 leaks nA off, so a 1 Meg off-resistance would load the
* 100k pull-up and read as a permanent fault in the mock.
.model SWEN SW(Ron=2 Roff=1G Vt=2.5 Vh=0.2)
* 60 pF lumped Ciss on the gate.  This is a MODEL element, not a BOM part: the
* switch model has no gate capacitance of its own, and without this the gate
* node is instantaneous, so the turn-off delay could only be done on paper.
* ic=15 (= VDD_IN): under uic every node starts at 0 V, so without it the gate
* ramps up from 0 through R50 over ~14 us and both switches conduct during that
* ramp - a charge pulse that exists only in the model and hides the real
* startup state (it read as 14.97 V on VDD_SR and made the first TARG crossing
* land at 12.6 us instead of at the fault).  Same reasoning as C_L below.
CG BC_GATE 0 60p ic=15
* Q55 source follower plus D50 in series with its drain.  The channel is off
* while VDD_SR <= VDD_IN (Vgs = 0); D50 blocks the follower's body diode, and
* the channel+D50 lift the gate only when VDD_SR is back-fed above VDD_IN.
S55 VDD_SR BC_FB VDD_SR VDD_IN SVP
.model SVP SW(Ron=0.05 Roff=1Meg Vt=1.5 Vh=0.3)
D55B BC_FB VDD_SR DBODY
D50 BC_FB BC_GATE DBAT
.model DBAT D(Is=1e-8 N=1.05 Rs=0.5)
S50 VDD_IN VMID VDD_IN BC_GATE SWPM
S51 VDD_SR VMID VDD_SR BC_GATE SWPM
.model SWPM SW(Ron=0.05 Roff=1Meg Vt=1.5 Vh=0.3)
D50B VMID VDD_IN DBODY
D51B VMID VDD_SR DBODY
.model DBODY D(Is=1e-12 N=1.2 Rs=0.05)
R57 VDD_SR VDD_DIS 47
S54 VDD_DIS 0 ENABLE_N 0 SWEN
R58 VDD_SR 0 100k
C54 VDD_SR 0 3.3u
R62 VDD_SR 0 1k
.tran 0 30m 0 0.1u uic
.save V(VDD_IN) V(VDD_SR) V(VMID) V(BC_GATE) V(ENABLE) V(ENABLE_N)
+ V(LATCHED) V(SET_LATCH) V(RST_EFF) V(FLT_N) V(POR) V(FAULT_IN) I(V1)
* 8 ms   POR has decayed (tau = 100k * 100nF = 10 ms, threshold ~6.9 ms):
*        the latch is still set from power-up and the bias is off.
* 13 ms  the 10 ms reset pulse has cleared the latch; the bias is on.
* 16 ms  1 ms after the 15 ms fault; the active discharge has emptied C54.
* 20 ms  the fault is gone but the latch persists: no auto-reset.
* 28 ms  the 25 ms explicit reset has re-enabled the bias.
* Windowed statistics, not point samples: a relaxation around a switch
* threshold shows up as a slow oscillation that a single sample can miss.
.meas TRAN vdd_sr_default_off MAX V(VDD_SR) FROM 7.5m TO 9.5m
.meas TRAN vdd_sr_enabled MIN V(VDD_SR) FROM 12m TO 14m
.meas TRAN vdd_sr_after_fault MAX V(VDD_SR) FROM 16m TO 17m
.meas TRAN vdd_sr_held_off MAX V(VDD_SR) FROM 19m TO 24m
.meas TRAN vdd_sr_recovered MIN V(VDD_SR) FROM 27m TO 29.5m
.meas TRAN latched_after_fault FIND V(LATCHED) AT=20m
.meas TRAN enable_after_fault FIND V(ENABLE) AT=20m
* The input current must fall to the R58 bleed after the cut, and come back
* after the explicit reset.  MIN over a window is the right statistic here:
* it shows the current actually reached the off state, not just a sample.
.meas TRAN i_vdd_in_off_min MIN I(V1) FROM 17.5m TO 24m
.meas TRAN i_vdd_in_on_min MIN I(V1) FROM 27m TO 29.5m
* Off-state node voltages.  These are the two nodes that told the story when
* the gate network was wrong: BC_GATE must sit at VDD_IN and VMID must not.
.meas TRAN gate_off FIND V(BC_GATE) AT=8m
.meas TRAN vmid_off FIND V(VMID) AT=8m
* Power-up invariant: the switch must never conduct before the first reset.
* This is the check that caught the gate node starting at 0 V under uic; it is
* what `vdd_sr_startup_max` guards now that both model state elements are
* initialised (C_L to "set", CG to VDD_IN).
.meas TRAN vdd_sr_startup_max MAX V(VDD_SR) FROM 0 TO 1m
* Two delays measured from the fault edge instead of computed on paper.
* The trigger is FAULT_IN, which rises exactly once.  Do NOT trigger on ENABLE:
* with the latch starting at 0 (no ic= on C_L) ENABLE is briefly high at t=0
* and its first fall is at 0.7 us, not at the fault - both delays then time the
* power-up transient and still land inside any sane threshold.  That is how the
* first version of these two measurements passed; the TO columns in the log are
* what exposed it.  Check them, not just the number.
* TARG is searched over the WHOLE run, not from the trigger onwards.  With the
* gate initialised at VDD_IN it is already above 13.5 V at t=0, and LTspice
* counts that initial point as the first crossing (TO came back as 1.8e-18, so
* the delay read -15 ms).  RISE=2 is therefore the fault edge; the FROM/TO
* columns are what prove which crossing was taken - always read them.
.meas TRAN t_bias_cut TRIG V(FAULT_IN) VAL=2.5 RISE=1
+ TARG V(BC_GATE) VAL=13.5 RISE=2
.meas TRAN t_discharge TRIG V(FAULT_IN) VAL=2.5 RISE=1
+ TARG V(VDD_SR) VAL=3.63 FALL=1
.end
"""


def reverse_deck() -> str:
    """Switch off, VDD_SR forced to 18 V; measure current into VDD_IN."""
    return """* Bias-cut ECO reverse-blocking check: switch off, VDD_SR back-fed to 18 V
* Behavioural switch model; the body-diode orientation is the point.
.param VDD=15
V1 VDD_IN 0 {VDD}
V5S V5_IND 0 5
VREV VREV_SRC 0 18
VREV_CTL VREV_CTL 0 PWL(0 0 0.4m 0 0.401m 5 1.0m 5 1.001m 0)
SREV VREV_SRC VDD_SR VREV_CTL 0 SWREV
.model SWREV SW(Ron=0.1 Roff=1Meg Vt=2.5 Vh=0.2)
* Latch deliberately held set: ENABLE=0, switch off.
B_ENABLE ENABLE 0 V=0
R50 VDD_IN BC_GATE 100k
S52 BC_GATE 0 ENABLE 0 SWEN
* Roff=1G: a 2N7002 leaks nA off, so a 1 Meg off-resistance would load the
* 100k pull-up and read as a permanent fault in the mock.
.model SWEN SW(Ron=2 Roff=1G Vt=2.5 Vh=0.2)
* 60 pF lumped Ciss on the gate.  This is a MODEL element, not a BOM part.
* ic=15 = VDD_IN, the state R50 holds it in: under uic the node would
* otherwise ramp up from 0 V through R50 over ~14 us (see the sequence deck).
CG BC_GATE 0 60p ic=15
* Q55 source follower plus D50 in series with its drain.  The channel is off
* while VDD_SR <= VDD_IN (Vgs = 0); D50 blocks the follower's body diode, and
* the channel+D50 lift the gate only when VDD_SR is back-fed above VDD_IN.
S55 VDD_SR BC_FB VDD_SR VDD_IN SVP
.model SVP SW(Ron=0.05 Roff=1Meg Vt=1.5 Vh=0.3)
D55B BC_FB VDD_SR DBODY
D50 BC_FB BC_GATE DBAT
.model DBAT D(Is=1e-8 N=1.05 Rs=0.5)
S50 VDD_IN VMID VDD_IN BC_GATE SWPM
S51 VDD_SR VMID VDD_SR BC_GATE SWPM
.model SWPM SW(Ron=0.05 Roff=1Meg Vt=1.5 Vh=0.3)
D50B VMID VDD_IN DBODY
D51B VMID VDD_SR DBODY
.model DBODY D(Is=1e-12 N=1.2 Rs=0.05)
R57 VDD_SR VDD_DIS 47
B_ENN ENABLE_N 0 V=5
S54 VDD_DIS 0 ENABLE_N 0 SWEN
R58 VDD_SR 0 100k
C54 VDD_SR 0 3.3u
R62 VDD_SR 0 1k
.tran 0 2m 0 0.1u uic
.save V(VDD_IN) V(VDD_SR) V(VMID) V(BC_GATE) I(V1) I(VREV)
.meas TRAN i_vdd_in_min MIN I(V1) FROM 0.45m TO 0.95m
.meas TRAN vdd_sr_reverse FIND V(VDD_SR) AT=0.7m
.meas TRAN vmid_reverse FIND V(VMID) AT=0.7m
.end
"""


def write_decks() -> None:
    (OUT / "bias_cut_eco.cir").write_text(sequence_deck(), encoding="utf-8")
    (OUT / "bias_cut_eco_reverse.cir").write_text(reverse_deck(), encoding="utf-8")
    print(f"wrote {OUT / 'bias_cut_eco.cir'} and reverse deck")


# ---------------------------------------------------------------- sim record
SEQ_LOG = OUT / "bias_cut_eco.log"
REV_LOG = OUT / "bias_cut_eco_reverse.log"
SIM_RUN = OUT / "sim_run.json"

DECK_FILES = {"bias_cut_eco.cir": sequence_deck, "bias_cut_eco_reverse.cir": reverse_deck}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Two printed forms: `.meas ... STAT(...)` gives ``name: STAT(...)=value``, while
# `.meas TRIG/TARG` gives ``name=value FROM a TO b`` with no colon and no unit.
# The second form is what a two-edge delay looks like, and dropping it silently
# loses exactly the measurements that have the least paper trail.
_MEAS_STAT = re.compile(r"^([a-z_][a-z0-9_]*):.*?=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)")
_MEAS_DELAY = re.compile(
    r"^([a-z_][a-z0-9_]*)=(-?[\d.]+(?:[eE][-+]?\d+)?)\s+FROM\s+\S+\s+TO\s+\S+")


def parse_meas(text: str) -> dict[str, float]:
    """Pull measurement values out of an LTspice .log tail."""
    out: dict[str, float] = {}
    for line in text.splitlines():
        m = _MEAS_STAT.match(line) or _MEAS_DELAY.match(line)
        if m:
            out[m.group(1)] = float(m.group(2))
    return out


def sim_checks(seq: dict[str, float], rev: dict[str, float]) -> list[dict]:
    """The pass/fail reading of a run.  Thresholds are the design intent."""

    def check(name: str, value: float, ok: bool, why: str) -> dict:
        return {"name": name, "value": value, "ok": ok, "why": why}

    def need(mapping: dict[str, float], key: str) -> float:
        if key not in mapping:
            raise KeyError(f"measurement {key!r} missing from the log; the deck was not run")
        return mapping[key]

    return [
        check("default_off_v", need(seq, "vdd_sr_default_off"),
              need(seq, "vdd_sr_default_off") <= 0.05,
              "power-up with POR set must leave the SR bias off"),
        check("startup_max_v", need(seq, "vdd_sr_startup_max"),
              need(seq, "vdd_sr_startup_max") <= 0.5,
              "the switch must never conduct before the first explicit reset; "
              "a non-zero value here means a model state element starts in the "
              "wrong state, not that the circuit misbehaves"),
        check("enabled_v", need(seq, "vdd_sr_enabled"),
              need(seq, "vdd_sr_enabled") >= 14.9,
              "an explicit reset with PERMIT must pass the full 15 V rail"),
        check("after_fault_v", need(seq, "vdd_sr_after_fault"),
              need(seq, "vdd_sr_after_fault") <= 0.05,
              "the fault must cut the bias, not merely lower it"),
        check("held_off_v", need(seq, "vdd_sr_held_off"),
              need(seq, "vdd_sr_held_off") <= 0.05,
              "with the fault gone and no reset the bias must stay off"),
        check("recovered_v", need(seq, "vdd_sr_recovered"),
              need(seq, "vdd_sr_recovered") >= 14.9,
              "an explicit reset must restore the bias"),
        check("latched_after_fault_v", need(seq, "latched_after_fault"),
              need(seq, "latched_after_fault") >= 4.5,
              "the latch, not the fault input, is what holds the bias off"),
        check("enable_after_fault_v", need(seq, "enable_after_fault"),
              need(seq, "enable_after_fault") <= 0.5,
              "ENABLE must be low while latched"),
        check("off_input_current_a", -need(seq, "i_vdd_in_off_min"),
              -need(seq, "i_vdd_in_off_min") <= 1e-3,
              "the cut must remove the load current; only leakage remains"),
        check("on_input_current_a", -need(seq, "i_vdd_in_on_min"),
              -need(seq, "i_vdd_in_on_min") >= 10e-3,
              "the enabled state must carry the bench load (~15 mA)"),
        check("gate_off_v", need(seq, "gate_off"),
              need(seq, "gate_off") >= 14.5,
              "R50 must hold the gate at VDD_IN with the switch off"),
        check("bias_cut_time_s", need(seq, "t_bias_cut"),
              5e-6 <= need(seq, "t_bias_cut") <= 40e-6,
              "the gate must reach 15 V - |Vth| within tens of microseconds; "
              "R50 * 60 pF says ~14 us, and anything past 40 us means the gate "
              "node is being held by something else"),
        check("discharge_time_s", need(seq, "t_discharge"),
              100e-6 <= need(seq, "t_discharge") <= 500e-6,
              "VDD_SR must reach the 3.63 V UCC24624 UVLO in a few hundred "
              "microseconds; 47 ohm * 3.3 uF says ~220 us"),
        check("reverse_current_a", abs(need(rev, "i_vdd_in_min")),
              abs(need(rev, "i_vdd_in_min")) <= 100e-6,
              "back-fed VDD_SR=18 V must not conduct through the switch; "
              "the only path is the R50 bleed"),
        check("reverse_vdd_sr_v", need(rev, "vdd_sr_reverse"),
              need(rev, "vdd_sr_reverse") >= 17.5,
              "the back-fed node holds 18 V: a conducting pass pair would drag it "
              "toward VDD_IN"),
    ]


def sim_run() -> dict:
    """Load the recorded run, and say whether it still belongs to these decks."""
    if not SIM_RUN.is_file():
        return {"status": "NOT_RECORDED", "note": "run the decks and use --record-run"}
    payload = json.loads(SIM_RUN.read_text(encoding="utf-8"))
    current = {name: sha256(build()) for name, build in DECK_FILES.items()}
    stale = [name for name, digest in current.items()
             if payload.get("deck_sha256", {}).get(name) != digest]
    payload["status"] = "STALE" if stale else payload.pop("status", "RUN")
    if stale:
        payload["stale_decks"] = stale
        payload["note"] = ("the deck changed after this run; re-run and --record-run "
                           "before quoting any number")
    return payload


def record_run(seq_path: Path = SEQ_LOG, rev_path: Path = REV_LOG) -> None:
    """Turn two captured .log files into sim_run.json.

    The deck hashes are taken here, next to the logs, so a later edit to the
    deck invalidates the record instead of silently re-labelling old numbers.
    """
    seq_text = seq_path.read_text(encoding="utf-8", errors="replace")
    rev_text = rev_path.read_text(encoding="utf-8", errors="replace")
    seq = parse_meas(seq_text)
    rev = parse_meas(rev_text)
    version = re.search(r"LTspice (\d+\.\d+\.\d+) for Windows", seq_text)
    circuit = re.search(r"^Circuit: (.+)$", seq_text, re.M)
    checks = sim_checks(seq, rev)
    payload = {
        "status": "RUN",
        "host": "winsrv" if circuit and "C:\\work\\" in circuit.group(1) else "unknown",
        "ltspice": version.group(1) if version else "unknown",
        "deck_sha256": {name: sha256(build()) for name, build in DECK_FILES.items()},
        "measured": {"sequence": seq, "reverse": rev},
        "checks": checks,
        "all_checks_pass": all(c["ok"] for c in checks),
        "evidence_level": "BEHAVIOURAL_SIMULATION_NOT_HARDWARE",
        "note": "behavioural switch and logic model; this is not a device model, "
                "not a thermal model, and not a hardware measurement",
    }
    SIM_RUN.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {SIM_RUN}  ({sum(c['ok'] for c in checks)}/{len(checks)} checks)")
    for c in checks:
        if not c["ok"]:
            print(f"  FAIL {c['name']} = {c['value']:.6g} -- {c['why']}")


# ---------------------------------------------------------------- report
def report(ps: list[Part]) -> dict:
    nets = nets_of(ps)
    return {
        "kind": "BIAS_CUT_ECO",
        "evidence_level": "GENERATED_SCHEMATIC_AND_NETLIST_NOT_HARDWARE",
        "hardware_built": False,
        "hardware_qualified": False,
        "thermal_qualified": False,
        "simulation_status": sim_run()["status"],
        "simulation": sim_run(),
        "part_instances": len(ps),
        "physical_parts": len(physical_components(ps)),
        "nets": len(nets),
        "pmos_selection": pmos_selection(),
        "integration": integration(),
        "truth_table": truth_table(),
        "net_map": nets,
        "observations": observations(),
        "requirements": [
            {"requirement": "always-on 15 V input",
             "implementation": "J6.1 VDD_IN; Q50 source; R50 pull-up",
             "status": "TOPOLOGY_ONLY"},
            {"requirement": "controlled SR bias output",
             "implementation": "VDD_SR at J6.2; Q51 source; C54/R62 bench load",
             "status": "TOPOLOGY_ONLY"},
            {"requirement": "independent 5 V fault latch",
             "implementation": "J7.1 V5_IND; U51 CD4013B; R56/C53 POR",
             "status": "TOPOLOGY_ONLY"},
            {"requirement": "PERMIT interface",
             "implementation": "J7.3; R63/R60; U52B",
             "status": "TOPOLOGY_ONLY"},
            {"requirement": "default off",
             "implementation": "R50 pulls BC_GATE high; R52 pulls ENABLE low; "
                               "R60 pulls PERMIT low; POR sets the latch",
             "status": "TOPOLOGY_AND_TRUTH_TABLE"},
            {"requirement": "reverse blocking",
             "implementation": "Q50/Q51 common drain VMID; Q55 source follower "
                               "+ D50 lift the gate only when VDD_SR > VDD_IN",
             "status": "TOPOLOGY_AND_REVERSE_DECK; residual ~30 uA bleed documented"},
            {"requirement": "local capacitor discharge",
             "implementation": "Q54 + R57; R58 passive bleed",
             "status": "TOPOLOGY_ONLY"},
            {"requirement": "preserve the fast REG crowbar",
             "implementation": "Q41/R44 stay on the SR board, directly driven by FAULT_G",
             "status": "NOT_MODIFIED"},
            {"requirement": "latch and gate discharge survive SR bias loss",
             "implementation": "the latch and Q54 are supplied from V5_IND, not VDD_SR",
             "status": "TOPOLOGY_ONLY"},
            {"requirement": "explicit reset",
             "implementation": "RESET_CMD AND FLT_N; set-dominant; no auto-reset",
             "status": "TOPOLOGY_AND_TRUTH_TABLE"},
            {"requirement": "backfeed measured at VDD/REG",
             "implementation": "H5 hardware capture; this ECO only provides the "
                               "reverse deck for the switch",
             "status": "OPEN"},
        ],
        "open_items": [
            "P-MOS is TO_SELECT; no P-channel datasheet in the repository",
            "no hardware build, no thermal measurement",
            "no measured VDD/REG backfeed; H5 remains NOT_READY",
            "P-MOS turn-on inrush and SOA are not checked against a vendor curve",
            "the 14 us gate turn-off uses an assumed 60 pF Ciss; recompute for the selected part",
            "the 5 V domain must be independent of the SR bias; its source is not part of this schematic",
            "over-voltage backfeed while the switch is ON is not handled by this ECO",
        ],
    }


def check() -> None:
    cli = kicad_cli()
    if cli is None:
        raise SystemExit("kicad-cli not found: ERC and netlist export cannot be reproduced here")
    sch = OUT / "bias_cut_eco.kicad_sch"
    net = OUT / "bias_cut_eco.net"
    erc = OUT / "erc.rpt"
    (OUT / "bias_cut_eco.kicad_pro").write_text(project_file(), encoding="utf-8")
    subprocess.run([str(cli), "sch", "export", "netlist", str(sch), "-o", str(net)], check=True)
    subprocess.run([str(cli), "sch", "erc", "--severity-all", str(sch), "-o", str(erc)], check=True)
    subprocess.run([str(cli), "sch", "erc", "--severity-all", "--format", "json",
                    str(sch), "-o", str(OUT / "erc.json")], check=True)
    text = net.read_text(encoding="utf-8")
    print(f"netlist: {text.count('(net' + chr(10))} nets -> {net.name}")
    violations = d0.erc_violations(OUT / "erc.json", source="bias_cut_eco.kicad_sch",
                                   newer_than=sch)
    print(f"ERC: {len(violations)} violation(s) at every severity")
    if violations:
        for v in violations:
            print(f"  {v['severity']} {v['type']}: {v['description']}")
        raise SystemExit("ERC is not clean -- fix the circuit or record why each one is accepted")
    nodes = netlist_nodes(text)
    required_nets = {"VDD_IN", "VDD_SR", "VMID", "PGND", "BC_GATE", "BC_FB", "VDD_DIS",
                     "V5_IND", "FLT_N", "FLT_H", "SET_LATCH", "RST_EFF",
                     "LATCHED", "LATCHED_N", "ENABLE", "ENABLE_N", "POR",
                     "PERMIT", "PERMIT_EXT", "RESET_CMD", "RESET_EXT",
                     "FAULT_IN", "FAULT_G"}
    missing = sorted(required_nets - set(nodes))
    if missing:
        raise SystemExit(f"nets missing from netlist: {missing}")
    expected = {
        "VMID": {("Q50", "3"), ("Q51", "3")},
        "BC_GATE": {("R50", "2"), ("Q50", "1"), ("Q51", "1"), ("D50", "1"), ("Q52", "3")},
        "BC_FB": {("Q55", "3"), ("D50", "2")},
        "VDD_SR": {("Q51", "2"), ("Q55", "2"), ("R57", "1"), ("R58", "1"),
                   ("C54", "1"), ("R62", "1"), ("J6", "2")},
        "VDD_IN": {("Q50", "2"), ("Q55", "1"), ("R50", "1"), ("J6", "1")},
        "VDD_DIS": {("R57", "2"), ("Q54", "3")},
        "ENABLE": {("Q52", "1"), ("U50", "3"), ("U52", "4"), ("R52", "1")},
        "ENABLE_N": {("Q54", "1"), ("U50", "4")},
        "FLT_N": {("Q53", "3"), ("R54", "2"), ("U50", "1"), ("U52", "2")},
        "FLT_H": {("U50", "2"), ("U53", "1")},
        "SET_LATCH": {("U53", "3"), ("U51", "6")},
        "RST_EFF": {("U52", "3"), ("U51", "4")},
        "LATCHED": {("U51", "1")},
        "LATCHED_N": {("U51", "2"), ("U52", "6")},
        "POR": {("R56", "1"), ("C53", "1"), ("U53", "2")},
        "PERMIT": {("R63", "2"), ("R60", "1"), ("U52", "5")},
        "FAULT_G": {("R65", "2"), ("R61", "1"), ("Q53", "1")},
    }
    for name, wanted in expected.items():
        if not wanted <= nodes[name]:
            raise SystemExit(f"net {name}: missing {sorted(wanted - nodes[name])}")
        # Test points are deliberately extra scope hooks; everything else on
        # the net has to be one of the declared endpoints.
        extra = {e for e in nodes[name] - wanted if not e[0].startswith(("TP", "#"))}
        if extra:
            raise SystemExit(f"net {name}: unexpected endpoints {sorted(extra)}")


def netlist_nodes(text: str) -> dict[str, set[tuple[str, str]]]:
    """Parse a KiCad netlist into net -> {(ref, pin)}.

    A regex over the whole file would either over-match across nets or miss the
    nested ``(node ...)`` blocks; walking balanced s-expressions is cheap and
    exact.
    """
    out: dict[str, set[tuple[str, str]]] = {}
    marker = "\t\t(net\n"
    start = text.find(marker)
    while start >= 0:
        end = d0.block_end(text, start + 2)
        block = text[start:end]
        name = re.search(r'\(name "([^"]*)"\)', block)
        if name and name.group(1).startswith("/"):
            net = name.group(1)[1:]
            out[net] = set(re.findall(
                r'\(node\s*\n\s*\(ref "([^"]+)"\)\s*\n\s*\(pin "([^"]+)"\)', block))
        start = text.find(marker, end)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--record-run", action="store_true",
                    help="fold the captured .log files in pcb/bias_cut_eco into sim_run.json")
    ap.add_argument("--seq-log", type=Path, default=SEQ_LOG)
    ap.add_argument("--rev-log", type=Path, default=REV_LOG)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.record_run:
        record_run(args.seq_log, args.rev_log)
        return
    symbols = build_symbols()
    ps = [snap(p) for p in parts()]
    validate(ps, symbols)
    (OUT / "bias_cut_eco.kicad_sch").write_text(schematic(symbols, ps), encoding="utf-8")
    print(f"wrote {OUT / 'bias_cut_eco.kicad_sch'}  ({len(ps)} part instances)")
    bom(ps)
    write_decks()
    (OUT / "report.json").write_text(
        json.dumps(report(ps), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'report.json'}")
    if args.check:
        check()


if __name__ == "__main__":
    main()
