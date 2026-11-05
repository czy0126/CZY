"""Generate the D0 ten-gate protection board as a native KiCad project.

Scope (issue #36, second checkbox): CT conditioning -> comparators -> SET-dominant
latch -> UVLO / rail-good -> ACK-low release token -> ten default-off gates with
gate-source pulldowns and ten capacitive dummy loads.  The board is a *bench*
artifact: it proves the logic and the default-off behaviour, not the power stage,
not thermal, not the ACK ceremony's timing margins.

The schematic is NET-LABEL FIRST for the same reason as the control board: every
pin gets a local label with its net name instead of a drawn wire.  That is real
KiCad connectivity (checked with ``kicad-cli sch export netlist``) and honest
about what the file is -- a machine-checked netlist with a human-readable layout.

Why the boolean network is duplicated here in Python (``hardware_step``): the
safety claim is "no hardware state can ever enable the converter when the
reference model forbids it".  Writing that network as an executable function lets
the test enumerate all 32768 input/state combinations against
``tools/two_tier_fault_logic.transition()`` instead of asserting it in prose.
The schematic table below and ``hardware_step`` must stay in step; the test
cross-checks the gate list against the part table.

Usage:
    python tools/make_d0_protection_board.py
    python tools/make_d0_protection_board.py --check   # netlist + ERC + report
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

from main_board_mechanical import find_kicad_cli

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "pcb" / "d0_protection"
NS = uuid.UUID("2b0d7f4e-93a1-4c68-8f52-7d0e1c9a4b31")


def kicad_cli() -> Path | None:
    """Locate ``kicad-cli`` without hardcoding a username (issue #11).

    Only the ``--check`` path needs it; generating the schematic does not, so a
    machine without KiCad can still rebuild every committed file.
    """
    return find_kicad_cli()


def symbol_libs() -> Path:
    """The bundled KiCad symbol directory next to the CLI it was installed with."""
    cli = kicad_cli()
    if cli is None:
        raise SystemExit("kicad-cli not found; set KICAD_CLI to regenerate symbols")
    return cli.parent.parent / "share" / "kicad" / "symbols"

# A pin tied to one of these is emitted as a ``no_connect`` marker, not a label.
NC = "#NC"

# Evidence anchors for the values that are *not* this author's choice.
DECK = "sim/v3/sr_tank_dual_v33_ss_1ms_100a.cir"
LIB = "models/sr_timing_v3.lib"
CTRL = "hardware/dcx_main/protection_interface_candidate.json"
PINS = "design/v1/pin_connections.csv"
BOM = "design/v3/bom/bom_draft.csv"
CT_DESIGN = "design/v3/bom/ct_design.json"
LOGIC = "tools/two_tier_fault_logic.py"


def deck_line(element: str) -> int:
    """1-based line of the deck element whose first token is ``element``.

    Provenance used to be integer literals, and they drifted: R8 (the 10 ohm
    burden) cited line 117, which is a 0 V test source, so an auditor was sent
    to the wrong element.  Resolving by name moves every pointer with an
    inserted line, and a renamed or deleted element fails loudly instead of
    silently naming its neighbour.
    """
    lines = (ROOT / DECK).read_text(encoding="utf-8").splitlines()
    hits = [number for number, line in enumerate(lines, 1) if line.split()[:1] == [element]]
    if len(hits) != 1:
        raise SystemExit(f"{DECK}: expected exactly one '{element}', found {hits}")
    return hits[0]


@dataclass(frozen=True)
class Pin:
    number: str
    name: str
    x: float
    y: float
    angle: int
    etype: str = "passive"


@dataclass(frozen=True)
class Part:
    ref: str
    lib: str
    value: str
    footprint: str
    x: float
    y: float
    nets: dict[str, str]  # pin number -> net name
    unit: int = 1
    rating: str = ""
    note: str = ""
    dnp: bool = False
    source: str = "DESIGN_PROPOSAL"


def uid(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


# ---------------------------------------------------------------- symbols
def block_end(text: str, start: int) -> int:
    """Index just past the balanced s-expression that starts at ``start``."""
    depth = 0
    in_string = False
    i = start
    while i < len(text):
        ch = text[i]
        if ch == '"' and (i == 0 or text[i - 1] != "\\"):
            in_string = not in_string
        elif not in_string:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    raise SystemExit("unbalanced s-expression")


def extract_symbol(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.find(f'(symbol "{name}"')
    if start < 0:
        raise SystemExit(f"{name} not found in {path}")
    return text[start:block_end(text, start)]


def pin_numbers(block: str) -> list[str]:
    out: list[str] = []
    marker = '(number "'
    i = 0
    while True:
        i = block.find(marker, i)
        if i < 0:
            return out
        j = block.find('"', i + len(marker))
        out.append(block[i + len(marker):j])
        i = j + 1


def symbol_base(block: str) -> str:
    """The stem KiCad uses for a symbol's sub-units.

    Not the outer name: several stock symbols here are ``extends`` aliases
    (``LM393`` extends ``LM2903``, ``MMBT3904`` extends ``Q_NPN_BEC``), and a
    renamed alias keeps the *parent's* sub-symbol names.  Reading the first
    inner ``(symbol "stem_0_1"`` gets the stem that actually exists.
    """
    first = block.find('(symbol "')
    inner = block.find('(symbol "', first + 1)
    if inner < 0:
        return block[first + len('(symbol "'):].split('"', 1)[0].split(":")[-1]
    name = block[inner + len('(symbol "'):].split('"', 1)[0]
    stem = name.rsplit("_", 2)[0]
    return stem or block[first + len('(symbol "'):].split('"', 1)[0].split(":")[-1]


def unit_pin_numbers(block: str, unit: int) -> list[str]:
    """Pin numbers of one unit, across all of its sub-symbols.

    Two traps: a unit can be split over several ``stem_<unit>_<style>`` blocks
    (HEF4093B uses ``_1_0``/``_1_1``/``_1_2`` for De Morgan styles), and pins
    that are common to every unit live in ``stem_0_<style>`` (``PWR_FLAG`` has
    its only pin in ``PWR_FLAG_0_1``).  Both are part of the unit.
    """
    out: list[str] = []
    for owner in (unit, 0):
        marker = f'(symbol "{symbol_base(block)}_{owner}_'
        start = block.find(marker)
        while start >= 0:
            end = block_end(block, start)
            out.extend(pin_numbers(block[start:end]))
            start = block.find(marker, end)
    return out


def pin_tips(block: str) -> dict[str, tuple[float, float]]:
    """Pin number -> symbol-space pin tip (x, y), y up."""
    out: dict[str, tuple[float, float]] = {}
    i = 0
    while True:
        i = block.find("(pin ", i)
        if i < 0:
            return out
        j = block.find('(number "', i)
        at = block.find("(at ", i)
        if j < 0 or at < 0:
            return out
        num = block[j + len('(number "'):block.find('"', j + len('(number "'))]
        nums = block[at + 4:block.find(")", at)].split()
        out[num] = (float(nums[0]), float(nums[1]))
        i = j + 1


def custom_symbol(name: str, pins: list[Pin], width: float, height: float,
                  reference: str = "U", footprint: str = "") -> str:
    """A rectangular symbol with explicit pin tips (KiCad modern format)."""
    base = name.split(":")[-1]
    lines = [
        f'\t\t(symbol "{name}"',
        '\t\t\t(pin_names (offset 0.508))',
        '\t\t\t(exclude_from_sim no) (in_bom yes) (on_board yes)',
        f'\t\t\t(property "Reference" "{reference}" (at 0 {height / 2 + 2.54:.3f} 0) '
        '(show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
        f'\t\t\t(property "Value" "{base}" (at 0 {-height / 2 - 2.54:.3f} 0) '
        '(show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
        f'\t\t\t(property "Footprint" "{footprint}" (at 0 0 0) (hide yes) '
        '(show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
        '\t\t\t(property "Datasheet" "" (at 0 0 0) (hide yes) (show_name no) '
        '(do_not_autoplace no) (effects (font (size 1.27 1.27))))',
        '\t\t\t(property "Description" "" (at 0 0 0) (hide yes) (show_name no) '
        '(do_not_autoplace no) (effects (font (size 1.27 1.27))))',
        f'\t\t\t(symbol "{base}_0_1"',
        f'\t\t\t\t(rectangle (start {-width / 2:.3f} {height / 2:.3f}) '
        f'(end {width / 2:.3f} {-height / 2:.3f}) '
        '(stroke (width 0.254) (type default)) (fill (type background)))',
        '\t\t\t)',
        f'\t\t\t(symbol "{base}_1_1"',
    ]
    for p in pins:
        lines.append(
            f'\t\t\t\t(pin {p.etype} line (at {p.x:.3f} {p.y:.3f} {p.angle}) (length 2.54) '
            f'(name "{p.name}" (effects (font (size 1.27 1.27)))) '
            f'(number "{p.number}" (effects (font (size 1.27 1.27)))))'
        )
    lines += ["\t\t\t)", "\t\t)", ""]
    return "\n".join(lines)


STANDARD = {
    "Device:R": ("Device.kicad_sym", "R"),
    "Device:C": ("Device.kicad_sym", "C"),
    "Device:D_Schottky": ("Device.kicad_sym", "D_Schottky"),
    "Device:D_Zener": ("Device.kicad_sym", "D_Zener"),
    "Device:D_TVS": ("Device.kicad_sym", "D_TVS"),
    "Device:Fuse": ("Device.kicad_sym", "Fuse"),
    "Regulator_Linear:L7805": ("Regulator_Linear.kicad_sym", "L7805"),
    "Reference_Voltage:TL431LP": ("Reference_Voltage.kicad_sym", "TL431LP"),
    # Aliases (LM393 = LM2903, MMBT3904 = Q_NPN_BEC, BSS84 = Q_PMOS_GSD) are
    # referenced under the *parent* name on purpose: the drawing and pin map are
    # the parent's, and building a block under an alias name that does not match
    # the installed library makes KiCad report lib_symbol_mismatch.  The real
    # part number stays in Part.value, which is what the BOM and netlist show.
    "Comparator:LM2903": ("Comparator.kicad_sym", "LM2903"),
    "4xxx:4013": ("4xxx.kicad_sym", "4013"),
    "4xxx:4069": ("4xxx.kicad_sym", "4069"),
    "4xxx:4071": ("4xxx.kicad_sym", "4071"),
    "4xxx:4081": ("4xxx.kicad_sym", "4081"),
    "4xxx:HEF4093B": ("4xxx.kicad_sym", "HEF4093B"),
    "Transistor_BJT:Q_NPN_BEC": ("Transistor_BJT.kicad_sym", "Q_NPN_BEC"),
    "Transistor_FET:Q_PMOS_GSD": ("Transistor_FET.kicad_sym", "Q_PMOS_GSD"),
    "Connector_Generic:Conn_01x02": ("Connector_Generic.kicad_sym", "Conn_01x02"),
    "Connector_Generic:Conn_01x04": ("Connector_Generic.kicad_sym", "Conn_01x04"),
    "Connector:TestPoint": ("Connector.kicad_sym", "TestPoint"),
    "power:PWR_FLAG": ("power.kicad_sym", "PWR_FLAG"),
}


def rename_symbol(block: str, lib_id: str) -> str:
    """Rename a symbol *and its sub-units* to ``lib_id``.

    KiCad matches a unit's sub-symbol by name: an outer ``Comparator:LM393``
    whose units are still called ``LM2903_1_1`` has no units at all and the
    whole sheet fails to load.  Renaming only the outer symbol is not enough
    for aliases (``extends``) whose stem differs from the alias name.
    """
    stem = symbol_base(block)
    bare = lib_id.split(":")[-1]
    out = block.replace(f'(symbol "{stem}"', f'(symbol "{lib_id}"', 1)
    if bare != stem:
        out = out.replace(f'(symbol "{stem}_', f'(symbol "{bare}_')
    return out


def build_symbols() -> dict[str, str]:
    symbols: dict[str, str] = {}
    libs = symbol_libs()
    for lib_id, (lib, name) in STANDARD.items():
        symbols[lib_id] = rename_symbol(extract_symbol(libs / lib, name), lib_id)
    symbols["UCC27524:UCC27524ADR"] = custom_symbol(
        "UCC27524:UCC27524ADR",
        [Pin("1", "ENA", -8.89, 5.08, 0, "input"),
         Pin("2", "INA", -8.89, 2.54, 0, "input"),
         Pin("4", "INB", -8.89, -2.54, 0, "input"),
         Pin("8", "ENB", -8.89, -5.08, 0, "input"),
         Pin("7", "OUTA", 8.89, 5.08, 180, "output"),
         Pin("5", "OUTB", 8.89, -5.08, 180, "output"),
         Pin("6", "VDD", 0, 10.16, 270, "power_in"),
         Pin("3", "GND", 0, -10.16, 90, "power_in")],
        17.78, 20.32, "U", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm")
    symbols["UCC27282:UCC27282DRCR"] = custom_symbol(
        "UCC27282:UCC27282DRCR",
        [Pin("1", "VDD", 0, 12.7, 270, "power_in"),
         Pin("3", "HB", 6.35, 12.7, 270, "passive"),
         Pin("4", "HO", 11.43, 5.08, 180, "output"),
         Pin("5", "HS", 11.43, 0, 180, "passive"),
         Pin("10", "LO", 11.43, -5.08, 180, "output"),
         Pin("6", "EN", -11.43, 5.08, 0, "input"),
         Pin("7", "HI", -11.43, 2.54, 0, "input"),
         Pin("8", "LI", -11.43, -2.54, 0, "input"),
         Pin("9", "VSS", 0, -12.7, 90, "power_in"),
         Pin("11", "EP", -6.35, -12.7, 90, "power_in"),
         Pin("2", "NC", -11.43, -5.08, 0, "unspecified")],
        22.86, 25.4, "U", "Package_SON:Texas_S-PVSON-N10")
    return symbols


# ---------------------------------------------------------------- parts
def bias_parts() -> list[Part]:
    """Two 12 V bench feeds, reverse-polarity blocks, clamps, and the 5 V rail."""
    tb2 = "TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm"
    return [
        Part("J1", "Connector_Generic:Conn_01x02", "VBIAS 12V", tb2, 30, 40,
             {"1": "V12P_IN", "2": "PGND"}, note="primary-side bias, polarity marked"),
        Part("J2", "Connector_Generic:Conn_01x02", "VCC12_S", tb2, 30, 70,
             {"1": "V12S_IN", "2": "PGND"}, note="secondary-side bias, polarity marked"),
        Part("F1", "Device:Fuse", "0.5A", "Fuse:Fuse_1206_3216Metric", 50, 40,
             {"1": "V12P_IN", "2": "V12P_F"}, rating="0.5 A", note="bias fuse"),
        Part("F2", "Device:Fuse", "0.5A", "Fuse:Fuse_1206_3216Metric", 50, 70,
             {"1": "V12S_IN", "2": "V12S_F"}, rating="0.5 A", note="bias fuse"),
        Part("D1", "Device:D_Schottky", "SS34", "Diode_SMD:D_SMA", 70, 40,
             {"1": "V12P", "2": "V12P_F"}, rating="40 V 3 A",
             note="reverse-polarity block; V12P = 12 V - 0.5 V"),
        Part("D2", "Device:D_Schottky", "SS34", "Diode_SMD:D_SMA", 70, 70,
             {"1": "V12S", "2": "V12S_F"}, rating="40 V 3 A",
             note="reverse-polarity block; V12S = 12 V - 0.5 V"),
        Part("D3", "Device:D_TVS", "SMBJ15A", "Diode_SMD:D_SMB", 88, 40,
             {"1": "V12P", "2": "PGND"}, rating="15 V standoff", note="clamp"),
        Part("D4", "Device:D_TVS", "SMBJ15A", "Diode_SMD:D_SMB", 88, 70,
             {"1": "V12S", "2": "PGND"}, rating="15 V standoff", note="clamp"),
        Part("U1", "Regulator_Linear:L7805", "L7805", "Package_TO_SOT_SMD:TO-252-2", 110, 40,
             {"1": "V12P", "2": "PGND", "3": "V5"}, rating="1 A, 2 V dropout",
             note="5 V logic rail; V12P - 0.5 V reverse block still >= 10 V"),
        Part("C1", "Device:C", "1uF/25V", "Capacitor_SMD:C_1206_3216Metric", 110, 60,
             {"1": "V12P", "2": "PGND"}, rating="25 V X7R", note="L7805 input"),
        Part("C2", "Device:C", "100nF/50V", "Capacitor_SMD:C_0603_1608Metric", 122, 60,
             {"1": "V12P", "2": "PGND"}, rating="50 V X7R", note="L7805 input"),
        Part("C3", "Device:C", "1uF/16V", "Capacitor_SMD:C_1206_3216Metric", 134, 60,
             {"1": "V5", "2": "PGND"}, rating="16 V X7R", note="L7805 output"),
        Part("C4", "Device:C", "100nF/16V", "Capacitor_SMD:C_0603_1608Metric", 146, 60,
             {"1": "V5", "2": "PGND"}, rating="16 V X7R", note="L7805 output"),
        Part("C5", "Device:C", "1uF/25V", "Capacitor_SMD:C_1206_3216Metric", 110, 78,
             {"1": "V12S", "2": "PGND"}, rating="25 V X7R", note="secondary bias"),
        Part("C6", "Device:C", "100nF/50V", "Capacitor_SMD:C_0603_1608Metric", 122, 78,
             {"1": "V12S", "2": "PGND"}, rating="50 V X7R", note="secondary bias"),
    ]


def reference_parts() -> list[Part]:
    """One TL431 plus three dividers: 1.000 V trip, 1.769 V fast, 0.200 V gate-sum."""
    return [
        Part("U2", "Reference_Voltage:TL431LP", "TL431LP",
             "Package_TO_SOT_THT:TO-92_Inline", 170, 50,
             {"1": "REF_2V5", "2": "PGND", "3": "REF_2V5"},
             rating="2.5 V shunt", note="TI LP is TO-92: K=1, A=2, REF=3; K/REF are shorted only in this 2.500 V design"),
        Part("R1", "Device:R", "1k", "Resistor_SMD:R_0603_1608Metric", 156, 38,
             {"1": "V5", "2": "REF_2V5"}, note="TL431 cathode bias, 2.5 mA"),
        Part("C7", "Device:C", "100nF/16V", "Capacitor_SMD:C_0603_1608Metric", 170, 32,
             {"1": "REF_2V5", "2": "PGND"}, rating="16 V X7R", note="reference bypass"),
        Part("R2", "Device:R", "15k", "Resistor_SMD:R_0603_1608Metric", 190, 38,
             {"1": "REF_2V5", "2": "REF_1V0"}, note="divider top: 2.5 V * 10/25 = 1.000 V"),
        Part("R3", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric", 190, 50,
             {"1": "REF_1V0", "2": "PGND"}, note="divider bottom"),
        Part("C8", "Device:C", "100nF/16V", "Capacitor_SMD:C_0603_1608Metric", 190, 62,
             {"1": "REF_1V0", "2": "PGND"}, rating="16 V X7R", note="trip threshold bypass"),
        Part("R4", "Device:R", "6.2k", "Resistor_SMD:R_0603_1608Metric", 210, 38,
             {"1": "REF_2V5", "2": "REF_1V8"},
             note="2.5 V * 15/21.2 = 1.769 V; fast threshold on the filtered node"),
        Part("R5", "Device:R", "15k", "Resistor_SMD:R_0603_1608Metric", 210, 50,
             {"1": "REF_1V8", "2": "PGND"}, note="divider bottom"),
        Part("C9", "Device:C", "100nF/16V", "Capacitor_SMD:C_0603_1608Metric", 210, 62,
             {"1": "REF_1V8", "2": "PGND"}, rating="16 V X7R", note="threshold bypass"),
        Part("R6", "Device:R", "23k", "Resistor_SMD:R_0603_1608Metric", 230, 38,
             {"1": "REF_2V5", "2": "REF_0V2"},
             note="2.5 V * 2/25 = 0.200 V; gate-sum threshold"),
        Part("R7", "Device:R", "2k", "Resistor_SMD:R_0603_1608Metric", 230, 50,
             {"1": "REF_0V2", "2": "PGND"}, note="divider bottom"),
        Part("C10", "Device:C", "100nF/16V", "Capacitor_SMD:C_0603_1608Metric", 230, 62,
             {"1": "REF_0V2", "2": "PGND"}, rating="16 V X7R", note="threshold bypass"),
    ]


def ct_parts() -> list[Part]:
    """The deck's OC network, verbatim (R3/R15/R16/R17/C11/C12 on the main board)."""
    sch = "Diode_SMD:D_SOD-123"
    return [
        Part("J3", "Connector_Generic:Conn_01x02", "CT secondary",
             "TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm", 40, 130,
             {"1": "CT_S1", "2": "CT_S2"}, rating="<=20 V peak",
             note="CT 24/35-turn secondary; this board IS the burden path"),
        Part("D5", "Device:D_Schottky", "BAT54", sch, 62, 118,
             {"1": "OCD", "2": "CT_S1"}, rating="30 V 200 mA",
             note="bridge: anode CT_S1 -> cathode OCD (deck D1)", source=f"{DECK}:{deck_line('D1')}"),
        Part("D6", "Device:D_Schottky", "BAT54", sch, 62, 142,
             {"1": "OCD", "2": "CT_S2"}, rating="30 V 200 mA",
             note="bridge: anode CT_S2 -> cathode OCD (deck D2)", source=f"{DECK}:{deck_line('D2')}"),
        Part("D7", "Device:D_Schottky", "BAT54", sch, 78, 118,
             {"1": "CT_S1", "2": "OCM"}, rating="30 V 200 mA",
             note="bridge: anode OCM -> cathode CT_S1 (deck D3)", source=f"{DECK}:{deck_line('D3')}"),
        Part("D8", "Device:D_Schottky", "BAT54", sch, 78, 142,
             {"1": "CT_S2", "2": "OCM"}, rating="30 V 200 mA",
             note="bridge: anode OCM -> cathode CT_S2 (deck D4)", source=f"{DECK}:{deck_line('D4')}"),
        Part("R8", "Device:R", "10R 1%", "Resistor_SMD:R_0805_2012Metric", 100, 130,
             {"1": "OCD", "2": "OCM"}, rating="0.25 W", note="burden Rbur (main R3)",
             source=f"{DECK}:{deck_line('Rbur')}"),
        Part("R9", "Device:R", "1k", "Resistor_SMD:R_0603_1608Metric", 118, 118,
             {"1": "OCD", "2": "OCF"}, note="Rf (main R15)", source=f"{DECK}:{deck_line('Rf')}"),
        Part("C11", "Device:C", "47nF/16V", "Capacitor_SMD:C_0603_1608Metric", 118, 130,
             {"1": "OCF", "2": "OCM"}, rating="16 V X7R", note="Cf (main C11)",
             source=f"{DECK}:{deck_line('Cf')}"),
        Part("R10", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric", 136, 118,
             {"1": "OCF", "2": "OC"}, note="Rd1 (main R16)", source=f"{DECK}:{deck_line('Rd1')}"),
        Part("R11", "Device:R", "24k", "Resistor_SMD:R_0603_1608Metric", 136, 130,
             {"1": "OC", "2": "OCM"}, note="Rd2: divider gain 24/35 = 0.6857 (main R17)",
             source=f"{DECK}:{deck_line('Rd2')}"),
        Part("C12", "Device:C", "10nF/16V", "Capacitor_SMD:C_0603_1608Metric", 136, 142,
             {"1": "OC", "2": "OCM"}, rating="16 V X7R", note="Coc (main C12)",
             source=f"{DECK}:{deck_line('Coc')}"),
        Part("R12", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric", 154, 118,
             {"1": "OC", "2": "OC_FILT"}, note="fast-channel filter, 10 us with C13"),
        Part("C13", "Device:C", "1nF/16V", "Capacitor_SMD:C_0603_1608Metric", 154, 130,
             {"1": "OC_FILT", "2": "PGND"}, rating="16 V X7R", note="fast-channel filter"),
        Part("R13", "Device:R", "0R", "Resistor_SMD:R_0603_1608Metric", 172, 130,
             {"1": "OCM", "2": "PGND"}, note="single-point return tie; no isolation"),
    ]


def comparator_parts() -> list[Part]:
    """Three LM393: trip, fast trip, three rail-good channels, gate-sum channel."""
    soic = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
    return [
        Part("U3", "Comparator:LM2903", "LM393", soic, 210, 120,
             {"1": "HARD_TRIP", "2": "REF_1V0", "3": "OC"},
             unit=1, rating="36 V",
             note="U3A trip, U3B fast trip; open collector, low = below threshold"),
        Part("U3", "Comparator:LM2903", "LM393", soic, 210, 120,
             {"5": "OC_FILT", "6": "REF_1V8", "7": "FAST_TRIP"}, unit=2),
        Part("U3", "Comparator:LM2903", "LM393", soic, 210, 120,
             {"4": "PGND", "8": "V5"}, unit=3),
        Part("R14", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric", 226, 108,
             {"1": "V5", "2": "HARD_TRIP"}, note="open-collector pull-up"),
        Part("R15", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric", 226, 120,
             {"1": "V5", "2": "FAST_TRIP"}, note="open-collector pull-up"),
        Part("U4", "Comparator:LM2903", "LM393", soic, 250, 120,
             {"1": "V12P_OK", "2": "REF_1V0", "3": "V12P_SNS"},
             unit=1, rating="36 V",
             note="rail-good: output high only while the divider exceeds 1.000 V"),
        Part("U4", "Comparator:LM2903", "LM393", soic, 250, 120,
             {"5": "V12S_SNS", "6": "REF_1V0", "7": "V12S_OK"}, unit=2),
        Part("U4", "Comparator:LM2903", "LM393", soic, 250, 120,
             {"4": "PGND", "8": "V5"}, unit=3),
        Part("R16", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric", 266, 108,
             {"1": "V5", "2": "V12P_OK"}, note="open-collector pull-up"),
        Part("R17", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric", 266, 120,
             {"1": "V5", "2": "V12S_OK"}, note="open-collector pull-up"),
        Part("R20", "Device:R", "100k", "Resistor_SMD:R_0603_1608Metric", 238, 96,
             {"1": "V12P", "2": "V12P_SNS"},
             note="UVLO divider: trip at 7.80 V, 1.54 V at 12 V (inside the 3.5 V CM limit)"),
        Part("R21", "Device:R", "14.7k", "Resistor_SMD:R_0603_1608Metric", 238, 104,
             {"1": "V12P_SNS", "2": "PGND"}, note="1.000 V * 114.7/14.7 = 7.80 V"),
        Part("C14", "Device:C", "100nF/16V", "Capacitor_SMD:C_0603_1608Metric", 238, 116,
             {"1": "V12P_SNS", "2": "PGND"}, rating="16 V X7R", note="divider bypass"),
        Part("R22", "Device:R", "100k", "Resistor_SMD:R_0603_1608Metric", 278, 96,
             {"1": "V12S", "2": "V12S_SNS"},
             note="UVLO divider: trip at 7.80 V, 1.54 V at 12 V (inside the 3.5 V CM limit)"),
        Part("R23", "Device:R", "14.7k", "Resistor_SMD:R_0603_1608Metric", 278, 104,
             {"1": "V12S_SNS", "2": "PGND"}, note="divider bottom, 1.000 V * 114.7/14.7"),
        Part("C15", "Device:C", "100nF/16V", "Capacitor_SMD:C_0603_1608Metric", 278, 116,
             {"1": "V12S_SNS", "2": "PGND"}, rating="16 V X7R", note="divider bypass"),
        Part("U5", "Comparator:LM2903", "LM393", soic, 300, 120,
             {"1": "V5_OK", "2": "REF_1V0", "3": "V5_SNS"},
             unit=1, rating="36 V",
             note="V5_OK is also comparator_bias_good; U5B watches the gate maximum"),
        Part("U5", "Comparator:LM2903", "LM393", soic, 300, 120,
             {"5": "GATE_SENSE", "6": "REF_0V2", "7": "ANY_ON"}, unit=2),
        Part("U5", "Comparator:LM2903", "LM393", soic, 300, 120,
             {"4": "PGND", "8": "V5"}, unit=3),
        Part("R18", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric", 316, 108,
             {"1": "V5", "2": "V5_OK"}, note="open-collector pull-up"),
        Part("R19", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric", 316, 120,
             {"1": "V5", "2": "ANY_ON"}, note="open-collector pull-up"),
        Part("R24", "Device:R", "100k", "Resistor_SMD:R_0603_1608Metric", 288, 96,
             {"1": "V5", "2": "V5_SNS"}, note="5 V supervisor: trip at 3.13 V"),
        Part("R25", "Device:R", "47k", "Resistor_SMD:R_0603_1608Metric", 288, 104,
             {"1": "V5_SNS", "2": "PGND"}, note="1.0 V * 147/47 = 3.13 V"),
        Part("C16", "Device:C", "100nF/16V", "Capacitor_SMD:C_0603_1608Metric", 288, 116,
             {"1": "V5_SNS", "2": "PGND"}, rating="16 V X7R", note="divider bypass"),
    ]


def bench_input_parts() -> list[Part]:
    """Straps and the ACK button.  Every one floats to 'invalid' by default."""
    strap = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
    return [
        Part("J5", "Connector_Generic:Conn_01x02", "CT_OK strap", strap, 40, 200,
             {"1": "V5", "2": "CT_OK"}, note="shunt = CT considered valid; open wire = invalid"),
        Part("R26", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric", 56, 212,
             {"1": "CT_OK", "2": "PGND"}, note="default invalid"),
        Part("J6", "Connector_Generic:Conn_01x02", "SS_READY strap", strap, 70, 200,
             {"1": "V5", "2": "SS_READY"}, note="start_sequence_ready from the main board"),
        Part("R27", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric", 86, 212,
             {"1": "SS_READY", "2": "PGND"}, note="default not ready"),
        Part("J7", "Connector_Generic:Conn_01x02", "FAST_ARMED strap", strap, 100, 200,
             {"1": "V5", "2": "FAST_ARMED_IN"}, note="armed; separate from SS_READY"),
        Part("R28", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric", 116, 212,
             {"1": "FAST_ARMED_IN", "2": "PGND"}, note="default unarmed"),
        Part("J8", "Connector_Generic:Conn_01x02", "OPERATOR_RUN strap", strap, 130, 200,
             {"1": "V5", "2": "OPERATOR_RUN"}, note="operator run"),
        Part("R29", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric", 146, 212,
             {"1": "OPERATOR_RUN", "2": "PGND"}, note="default run low"),
        Part("J9", "Connector_Generic:Conn_01x02", "ACK button", strap, 160, 200,
             {"1": "ACK_RAW", "2": "V5"}, note="press = ACK high; release = low"),
        Part("R30", "Device:R", "100k", "Resistor_SMD:R_0603_1608Metric", 160, 212,
             {"1": "ACK_RAW", "2": "PGND"}, note="ACK pull-down; release decay in ACK_TIMING_UNQUALIFIED"),
        Part("C17", "Device:C", "100nF/16V", "Capacitor_SMD:C_0603_1608Metric", 172, 212,
             {"1": "ACK_RAW", "2": "PGND"}, rating="16 V X7R", note="contact debounce"),
        Part("R31", "Device:R", "100k", "Resistor_SMD:R_0603_1608Metric", 186, 200,
             {"1": "ACK_RAW", "2": "ACK_RC"}, note="edge-detect lag; window in ACK_TIMING_UNQUALIFIED"),
        Part("C18", "Device:C", "10nF/16V", "Capacitor_SMD:C_0603_1608Metric", 186, 212,
             {"1": "ACK_RC", "2": "PGND"}, rating="16 V X7R", note="edge-detect lag"),
        Part("R32", "Device:R", "100k", "Resistor_SMD:R_0603_1608Metric", 200, 200,
             {"1": "V5", "2": "POR_RC"}, note="power-on reset, 8 ms to VT+ with C19"),
        Part("C19", "Device:C", "100nF/16V", "Capacitor_SMD:C_0603_1608Metric", 200, 212,
             {"1": "POR_RC", "2": "PGND"}, rating="16 V X7R", note="power-on reset"),
    ]


def logic_parts() -> list[Part]:
    """The gate network, one Part per instantiated unit; ``hardware_step`` mirrors it."""
    dip = "Package_DIP:DIP-14_W7.62mm"
    so14 = "Package_SO:SOIC-14_3.9x8.7mm_P1.27mm"  # HEF4093BT, Nexperia SO14 SOT108-1
    return [
        # U6 -- 4081 #1
        Part("U6", "4xxx:4081", "CD4081BE", dip, 40, 250,
             {"1": "V12P_OK", "2": "V12S_OK", "3": "H_OK_A"}, unit=1,
             note="HEALTHY = four rail/CT supervisors ANDed"),
        Part("U6", "4xxx:4081", "CD4081BE", dip, 40, 250,
             {"4": "H_OK_B", "5": "V5_OK", "6": "CT_OK"}, unit=2),
        Part("U6", "4xxx:4081", "CD4081BE", dip, 40, 250,
             {"8": "H_OK_A", "9": "H_OK_B", "10": "HEALTHY"}, unit=3),
        Part("U6", "4xxx:4081", "CD4081BE", dip, 40, 250,
             {"11": "FAST_ARMED", "12": "FAST_COMBINED", "13": "FAST_ARMED_IN"}, unit=4),
        Part("U6", "4xxx:4081", "CD4081BE", dip, 40, 250, {"7": "PGND", "14": "V5"}, unit=5),
        # U7 -- 4081 #2
        Part("U7", "4xxx:4081", "CD4081BE", dip, 90, 250,
             {"1": "HEALTHY", "2": "NOT_FLT", "3": "READY_A"}, unit=1,
             note="READY also needs every gate measured off"),
        Part("U7", "4xxx:4081", "CD4081BE", dip, 90, 250,
             {"4": "READY_B", "5": "SS_READY", "6": "ALL_OFF"}, unit=2),
        Part("U7", "4xxx:4081", "CD4081BE", dip, 90, 250,
             {"8": "READY_A", "9": "READY_B", "10": "READY"}, unit=3),
        Part("U7", "4xxx:4081", "CD4081BE", dip, 90, 250,
             {"11": "P_A", "12": "READY_A", "13": "SS_READY"}, unit=4),
        Part("U7", "4xxx:4081", "CD4081BE", dip, 90, 250, {"7": "PGND", "14": "V5"}, unit=5),
        # U8 -- 4081 #3
        Part("U8", "4xxx:4081", "CD4081BE", dip, 140, 250,
             {"1": "OPERATOR_RUN", "2": "LATCHED_N", "3": "P_B"}, unit=1,
             note="PERMIT: same terms as the contract's permits product"),
        Part("U8", "4xxx:4081", "CD4081BE", dip, 140, 250,
             {"4": "P_C", "5": "P_A", "6": "P_B"}, unit=2),
        Part("U8", "4xxx:4081", "CD4081BE", dip, 140, 250,
             {"8": "P_C", "9": "NOT_HARD_TRIP", "10": "PERMIT"}, unit=3),
        Part("U8", "4xxx:4081", "CD4081BE", dip, 140, 250,
             {"11": "RESET_OK", "12": "ACK_LOW_OK", "13": "ACK_RISE"}, unit=4),
        Part("U8", "4xxx:4081", "CD4081BE", dip, 140, 250, {"7": "PGND", "14": "V5"}, unit=5),
        # U9 -- 4081 #4
        Part("U9", "4xxx:4081", "CD4081BE", dip, 190, 250,
             {"1": "RESET_OK", "2": "READY", "3": "RST_A"}, unit=1,
             note="RST_EFF also ANDs LATCHED: the model's reset_valid term"),
        Part("U9", "4xxx:4081", "CD4081BE", dip, 190, 250,
             {"4": "RST_EFF", "5": "RST_A", "6": "LATCHED"}, unit=2),
        Part("U9", "4xxx:4081", "CD4081BE", dip, 190, 250,
             {"8": "ACK_RAW", "9": "ACK_DLY_N", "10": "ACK_RISE"}, unit=3,
             note="edge detect: ACK_RISE high only while the RC lags the press"),
        Part("U9", "4xxx:4081", "CD4081BE", dip, 190, 250,
             {"11": "ACK_ARM", "12": "READY", "13": "ACK_N"}, unit=4,
             note="ACK_ARM: the low level is observed while READY, exactly the model's "
                  "fresh_release term (a release edge alone is not enough)"),
        Part("U9", "4xxx:4081", "CD4081BE", dip, 190, 250, {"7": "PGND", "14": "V5"}, unit=5),
        # U10 -- 4071 OR
        Part("U10", "4xxx:4071", "CD4071BE", dip, 240, 250,
             {"1": "HARD_TRIP", "2": "FAST_ARMED", "3": "FAULT_A"}, unit=1,
             note="fault = hard trip OR armed fast trip OR any supervisor down"),
        Part("U10", "4xxx:4071", "CD4071BE", dip, 240, 250,
             {"4": "FAULT_B", "5": "FAULT_A", "6": "NOT_HEALTHY"}, unit=2),
        Part("U10", "4xxx:4071", "CD4071BE", dip, 240, 250,
             {"8": "FAULT_B", "9": "POR", "10": "FLT"}, unit=3,
             note="FLT also holds during power-on reset"),
        Part("U10", "4xxx:4071", "CD4071BE", dip, 240, 250,
             {"11": "FF2_RESET", "12": "FLT", "13": "NOT_READY"}, unit=4,
             note="the release token is invalidated by any fault"),
        Part("U10", "4xxx:4071", "CD4071BE", dip, 240, 250, {"7": "PGND", "14": "V5"}, unit=5),
        # U11 -- 4069 inverters
        Part("U11", "4xxx:4069", "CD4069UBE", dip, 290, 250,
             {"1": "HEALTHY", "2": "NOT_HEALTHY"}, unit=1),
        Part("U11", "4xxx:4069", "CD4069UBE", dip, 290, 250,
             {"3": "FLT", "4": "NOT_FLT"}, unit=2),
        Part("U11", "4xxx:4069", "CD4069UBE", dip, 290, 250,
             {"5": "HARD_TRIP", "6": "NOT_HARD_TRIP"}, unit=3),
        Part("U11", "4xxx:4069", "CD4069UBE", dip, 290, 250,
             {"9": "ANY_ON", "8": "ALL_OFF"}, unit=4),
        Part("U11", "4xxx:4069", "CD4069UBE", dip, 290, 250,
             {"11": "READY", "10": "NOT_READY"}, unit=5),
        Part("U11", "4xxx:4069", "CD4069UBE", dip, 290, 250,
             {"13": "FAST_EXT_N", "12": "FAST_EXT_H"}, unit=6),
        Part("U11", "4xxx:4069", "CD4069UBE", dip, 290, 250, {"7": "PGND", "14": "V5"}, unit=7),
        # External active-low receiver. Same V5 domain; no wired-OR at FAST_TRIP.
        Part("U19", "4xxx:4071", "CD4071BE", dip, 410, 210,
             {"1": "FAST_TRIP", "2": "FAST_EXT_H", "3": "FAST_COMBINED"}, unit=1),
        Part("U19", "4xxx:4071", "CD4071BE", dip, 410, 210,
             {"5": "PGND", "6": "PGND", "4": NC}, unit=2),
        Part("U19", "4xxx:4071", "CD4071BE", dip, 410, 210,
             {"8": "PGND", "9": "PGND", "10": NC}, unit=3),
        Part("U19", "4xxx:4071", "CD4071BE", dip, 410, 210,
             {"12": "PGND", "13": "PGND", "11": NC}, unit=4),
        Part("U19", "4xxx:4071", "CD4071BE", dip, 410, 210,
             {"7": "PGND", "14": "V5"}, unit=5),
        # U12 -- 4013 latches
        Part("U12", "4xxx:4013", "CD4013BE", dip, 340, 250,
             {"1": "LATCHED", "2": "LATCHED_N", "3": "PGND", "4": "RST_EFF",
              "5": "V5", "6": "FLT"}, unit=1,
             note="FF1: SET=FLT, RESET=RST_EFF, clock static; ~Q is the permit term"),
        Part("U12", "4xxx:4013", "CD4013BE", dip, 340, 250,
             {"8": "ACK_ARM", "9": "PGND", "10": "FF2_RESET", "11": "PGND",
              "12": NC, "13": "ACK_LOW_OK"}, unit=2,
             note="FF2: set-dominant level latch, not an edge sampler; SET=ACK_ARM, "
                  "RESET=any fault or lost READY, clock and D tied off"),
        Part("U12", "4xxx:4013", "CD4013BE", dip, 340, 250, {"7": "PGND", "14": "V5"}, unit=3),
        # U13 -- 4093 Schmitt
        Part("U13", "4xxx:HEF4093B", "HEF4093BT", so14, 390, 250,
             {"1": "ACK_RC", "2": "ACK_RC", "3": "ACK_DLY_N"}, unit=1,
             note="Schmitt on the RC node: the delayed copy for edge detection"),
        Part("U13", "4xxx:HEF4093B", "HEF4093BT", so14, 390, 250,
             {"4": NC, "5": "PGND", "6": "PGND"}, unit=2),
        Part("U13", "4xxx:HEF4093B", "HEF4093BT", so14, 390, 250,
             {"8": "POR_RC", "9": "POR_RC", "10": "POR"}, unit=3,
             note="power-on reset: holds FLT until V5 has been up ~8 ms"),
        Part("U13", "4xxx:HEF4093B", "HEF4093BT", so14, 390, 250,
             {"11": "ACK_N", "12": "ACK_RAW", "13": "ACK_RAW"}, unit=4,
             note="Schmitt inverter: ACK_N = NOT(ACK_RAW), the token clock"),
        Part("U13", "4xxx:HEF4093B", "HEF4093BT", so14, 390, 250, {"7": "PGND", "14": "V5"}, unit=5),
    ]


def permit_parts() -> list[Part]:
    """PERMIT (5 V CMOS) -> NPN -> PMOS high side -> PERMIT_RAIL.  Open = rail low."""
    return [
        Part("R33", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric", 430, 200,
             {"1": "PERMIT", "2": "PDRV"}, note="Q1 base resistor"),
        Part("Q1", "Transistor_BJT:Q_NPN_BEC", "MMBT3904", "Package_TO_SOT_SMD:SOT-23",
             444, 200, {"1": "PDRV", "2": "PGND", "3": "PCOLL"}, rating="40 V",
             note="opens PDRV only while PERMIT is high"),
        Part("R34", "Device:R", "100k", "Resistor_SMD:R_0603_1608Metric", 458, 188,
             {"1": "V5", "2": "PCOLL"}, note="PDRV pull-up: default high = PMOS off"),
        Part("Q2", "Transistor_FET:Q_PMOS_GSD", "BSS84", "Package_TO_SOT_SMD:SOT-23",
             472, 200, {"1": "PCOLL", "2": "V5", "3": "PERMIT_RAIL"}, rating="50 V",
             note="high-side PMOS: pin 2 is the source, so source=V5 and drain=rail "
                  "keep the body diode reverse-biased while off"),
        Part("R35", "Device:R", "100k", "Resistor_SMD:R_0603_1608Metric", 472, 216,
             {"1": "PERMIT_RAIL", "2": "PGND"},
             note="defines the rail low whenever the PMOS is off"),
    ]


def driver_parts() -> list[Part]:
    """Four UCC27524A for the eight SR gates, one UCC27282 for the primary pair."""
    soic = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
    out: list[Part] = []
    for index, ref in enumerate(("U14", "U15", "U16", "U17")):
        out += [
            Part(ref, "UCC27524:UCC27524ADR", "UCC27524ADR", soic,
                 40 + 55 * index, 300,
                 {"1": "PERMIT_RAIL", "2": "TG_SR", "3": "PGND", "4": "TG_SR",
                  "5": f"SOB{index}", "6": "V12S", "7": f"SOA{index}", "8": "PERMIT_RAIL"},
                 rating="dual 5 A", source=f"{CTRL}:proposed_sr_channels",
                 note="ENA/ENB must be pulled low externally: internal 200 k pulls HIGH"),
            Part(f"R{36 + 2 * index}", "Device:R", "4.7k", "Resistor_SMD:R_0603_1608Metric",
                 40 + 55 * index, 270, {"1": "PERMIT_RAIL", "2": "PGND"},
                 note=f"{ref} ENA default-off pull-down"),
            Part(f"R{37 + 2 * index}", "Device:R", "4.7k", "Resistor_SMD:R_0603_1608Metric",
                 48 + 55 * index, 270, {"1": "PERMIT_RAIL", "2": "PGND"},
                 note=f"{ref} ENB default-off pull-down"),
            Part(f"C{20 + 2 * index}", "Device:C", "1uF/25V", "Capacitor_SMD:C_1206_3216Metric",
                 40 + 55 * index, 316, {"1": "V12S", "2": "PGND"},
                 rating="25 V X7R", note=f"{ref} VDD bulk"),
            Part(f"C{21 + 2 * index}", "Device:C", "100nF/50V", "Capacitor_SMD:C_0603_1608Metric",
                 48 + 55 * index, 316, {"1": "V12S", "2": "PGND"},
                 rating="50 V X7R", note=f"{ref} VDD decoupling"),
        ]
    out += [
        Part("U18", "UCC27282:UCC27282DRCR", "UCC27282DRCR",
             "Package_SON:Texas_S-PVSON-N10", 300, 305,
             {"1": "V12P", "2": NC, "3": "HB", "4": "HO", "5": "PGND",
              "6": "PERMIT_RAIL", "7": "TG_HI", "8": "TG_LO",
              "9": "PGND", "10": "LO", "11": "PGND"}, rating="120 V",
             source=f"{PINS}:10-20",
             note="EN is pin 6 on the DRC 10-pin; the D 8-pin has no EN"),
        Part("R44", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric", 288, 292,
             {"1": "PERMIT_RAIL", "2": "PGND"}, source=f"{CTRL}:native_primary",
             note="main board R7: EN default-off"),
        Part("C28", "Device:C", "1nF/50V", "Capacitor_SMD:C_0603_1608Metric", 276, 306,
             {"1": "PERMIT_RAIL", "2": "PGND"}, rating="50 V X7R",
             source=f"{CTRL}:native_primary", note="main board C13: EN noise filter"),
        Part("R45", "Device:R", "1k", "Resistor_SMD:R_0603_1608Metric", 288, 308,
             {"1": "V12P", "2": "PERMIT_RAIL"}, dnp=True,
             source=f"{CTRL}:native_primary",
             note="main board R8: fitted only to demonstrate the floating-EN hazard"),
        Part("C29", "Device:C", "100nF/25V", "Capacitor_SMD:C_0603_1608Metric", 312, 320,
             {"1": "HB", "2": "PGND"}, rating="25 V X7R", note="Cbt; HS is grounded on the bench"),
        Part("C30", "Device:C", "1uF/25V", "Capacitor_SMD:C_1206_3216Metric", 300, 320,
             {"1": "V12P", "2": "PGND"}, rating="25 V X7R", note="U18 VDD bulk"),
        Part("C31", "Device:C", "100nF/50V", "Capacitor_SMD:C_0603_1608Metric", 308, 320,
             {"1": "V12P", "2": "PGND"}, rating="50 V X7R", note="U18 VDD decoupling"),
        # gate resistors and loads
        Part("R46", "Device:R", "2.2R", "Resistor_SMD:R_0603_1608Metric", 330, 300,
             {"1": "HO", "2": "GH1"}, note="primary high-side gate resistor"),
        Part("R47", "Device:R", "2.2R", "Resistor_SMD:R_0603_1608Metric", 330, 310,
             {"1": "LO", "2": "GL1"}, note="primary low-side gate resistor"),
    ]
    return out


def gate_load_parts() -> list[Part]:
    """Ten gate pulldowns, ten dummy loads, and the ten-way gate *maximum* detector.

    The detector is a diode-OR, not a resistor sum.  A sum is linear in every
    gate at once, so one gate parked at 3 V contributes only its share of a
    shared node (0.150 V through the old ten-resistor star) and disappears under
    the 0.200 V reference -- the board then reports "all off" while a FET sits
    in its linear region.  A diode-OR passes the *highest* gate: the other nine
    branches are reverse-biased and carry nothing, so no combination of the
    gates that are off can pull the answer down.
    """
    out: list[Part] = []
    sr = ["SOA0", "SOB0", "SOA1", "SOB1", "SOA2", "SOB2", "SOA3", "SOB3"]
    for index, net in enumerate(sr):
        gate = f"GA{index + 1}"
        branch = f"GK{index + 1}"
        out += [
            Part(f"R{48 + index}", "Device:R", "2.2R", "Resistor_SMD:R_0603_1608Metric",
                 360, 292 + 9 * index, {"1": net, "2": gate},
                 source=f"{CTRL}:proposed_sr_channels", note="SR gate resistor"),
            Part(f"R{56 + index}", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric",
                 374, 292 + 9 * index, {"1": gate, "2": "PGND"},
                 note="gate-source pull-down: default off if the driver is unpowered"),
            Part(f"C{32 + index}", "Device:C", "6.7nF/50V", "Capacitor_SMD:C_0603_1608Metric",
                 388, 292 + 9 * index, {"1": gate, "2": "PGND"}, rating="50 V",
                 source=f"{LIB}:106", note="dummy gate load = Cgate 6.7 nF"),
            Part(f"R{66 + index}", "Device:R", "1k", "Resistor_SMD:R_0603_1608Metric",
                 402, 292 + 9 * index, {"1": gate, "2": branch},
                 note="gate-max branch: in series with D so the diode drop is set by a "
                      "current this 1k fixes, and so ten gate nodes never share copper"),
            Part(f"D{9 + index}", "Device:D_Schottky", "BAT54", "Diode_SMD:D_SOD-123",
                 426, 292 + 9 * index, {"1": "GSMAX", "2": branch}, rating="30 V 200 mA",
                 note="anode on the gate branch, cathode on GSMAX: only the highest gate "
                      "forward-biases its diode"),
        ]
    for index, (gate, load) in enumerate((("GH1", "4nF"), ("GL1", "4nF"))):
        branch = f"GK{9 + index}"
        out += [
            Part(f"R{64 + index}", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric",
                 416, 292 + 9 * index, {"1": gate, "2": "PGND"},
                 note="gate-source pull-down"),
            Part(f"C{40 + index}", "Device:C", load, "Capacitor_SMD:C_0603_1608Metric",
                 430, 292 + 9 * index, {"1": gate, "2": "PGND"}, rating="50 V",
                 source=f"{DECK}:Cgh", note="dummy gate load = 4 nF"),
            Part(f"R{74 + index}", "Device:R", "1k", "Resistor_SMD:R_0603_1608Metric",
                 444, 292 + 9 * index, {"1": gate, "2": branch},
                 note="gate-max branch, primary pair"),
            Part(f"D{17 + index}", "Device:D_Schottky", "BAT54", "Diode_SMD:D_SOD-123",
                 456, 292 + 9 * index, {"1": "GSMAX", "2": branch}, rating="30 V 200 mA",
                 note="gate max detector, primary pair"),
        ]
    out += [
        Part("R76", "Device:R", "22k", "Resistor_SMD:R_0603_1608Metric", 468, 270,
             {"1": "GSMAX", "2": "GATE_SENSE"},
             note="divider top.  With the ten 1k branches this bounds the comparator "
                  "input by a ratio, not by a knee voltage: at most 2.629 V at 12 V and "
                  "3.286 V at the 15 V TVS standoff"),
        Part("R77", "Device:R", "6.2k", "Resistor_SMD:R_0603_1608Metric", 480, 270,
             {"1": "GATE_SENSE", "2": "PGND"},
             note="divider bottom: 3.5 V * 28.3k / 6.2k = 15.98 V of gate rail before the "
                  "LM393 input reaches its common-mode limit"),
    ]
    return out


def connector_and_flag_parts() -> list[Part]:
    tp = "TestPoint:TestPoint_Pad_D1.0mm"
    out: list[Part] = [
        Part("J4", "Connector_Generic:Conn_01x04", "TG_HI/TG_LO/TG_SR",
             "TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-04P_1x04_P5.00mm", 30, 330,
             {"1": "TG_HI", "2": "TG_LO", "3": "TG_SR", "4": "PGND"},
             note="bench gate drive; all eight SR channels share TG_SR as in the deck"),
    ]
    for index, (ref, net) in enumerate([
            ("TP1", "V12P"), ("TP2", "V12S"), ("TP3", "V5"), ("TP4", "REF_2V5"),
            ("TP5", "OC"), ("TP6", "OC_FILT"), ("TP7", "HARD_TRIP"), ("TP8", "FAST_TRIP"),
            ("TP9", "HEALTHY"), ("TP10", "READY"), ("TP11", "LATCHED"), ("TP12", "ACK_LOW_OK"),
            ("TP13", "ACK_RISE"), ("TP14", "FLT"), ("TP15", "PERMIT"),
            ("TP16", "PERMIT_RAIL"), ("TP17", "GSMAX"), ("TP18", "ANY_ON"),
            ("TP19", "GATE_SENSE")]):
        out.append(Part(ref, "Connector:TestPoint", net, tp, 40 + 14 * index, 360,
                        {"1": net}, rating="1 mm pad", note="scope probe point"))
    # ERC needs a source declaration only where every existing pin is passive:
    # V5 is driven by the L7805 output and needs none (two power outputs on one
    # net is itself an error).
    for index, net in enumerate(("V12P", "V12S", "PGND")):
        out.append(Part(f"#FLG{index + 1}", "power:PWR_FLAG", "PWR_FLAG", "",
                        260 + 12 * index, 360, {"1": net}, note="ERC source declaration"))
    return out


def external_fast_parts() -> list[Part]:
    return [
        Part("J10", "Connector_Generic:Conn_01x04", "FAST_OC_MODULE",
             "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", 420, 340,
             {"1": "V5", "2": "PGND", "3": "OCD", "4": "FAST_EXT_N"},
             note="Only connect fast_oc J1 here. Never bridge FAST_EXT_N to FAST_TRIP."),
        Part("R100", "Device:R", "100k", "Resistor_SMD:R_0603_1608Metric", 440, 340,
             {"1": "FAST_EXT_N", "2": "PGND"},
             note="Open signal wire requests fault while armed; not a backfeed guarantee."),
        Part("C100", "Device:C", "100nF/50V", "Capacitor_SMD:C_0603_1608Metric", 460, 340,
             {"1": "V5", "2": "PGND"}, rating="50 V X7R", note="U19 local bypass"),
    ]


def parts() -> list[Part]:
    return (bias_parts() + reference_parts() + ct_parts() + comparator_parts()
            + bench_input_parts() + logic_parts() + permit_parts() + driver_parts()
            + gate_load_parts() + connector_and_flag_parts() + external_fast_parts())


# ------------------------------------------------- the executable network
def hardware_step(*, hard_trip: bool, fast_trip: bool, fast_armed_in: bool,
                  v12p_ok: bool, v12s_ok: bool, v5_ok: bool, ct_ok: bool,
                  ss_ready: bool, operator_run: bool, all_off: bool,
                  ack_raw: bool, ack_rise: bool, por: bool,
                  latched: bool, ack_low_ok: bool, fast_ext_n: bool = True) -> dict[str, bool]:
    """One combinational pass of the gate list, then the two latch next-states.

    ``latched`` is the model's ``latched_off``: true means protection is holding
    the converter off.  Every term below appears as a named net in ``logic_parts``.
    """
    h_ok_a = v12p_ok and v12s_ok
    h_ok_b = v5_ok and ct_ok
    healthy = h_ok_a and h_ok_b
    not_healthy = not healthy
    fast_armed = (fast_trip or not fast_ext_n) and fast_armed_in
    fault_a = hard_trip or fast_armed
    fault_b = fault_a or not_healthy
    flt = fault_b or por
    not_flt = not flt
    not_hard_trip = not hard_trip
    all_off_ = all_off
    ready_a = healthy and not_flt
    ready_b = ss_ready and all_off_
    ready = ready_a and ready_b
    not_ready = not ready
    ff2_reset = flt or not_ready
    p_a = ready_a and ss_ready
    p_b = operator_run and not latched
    p_c = p_a and p_b
    permit = p_c and not_hard_trip
    reset_ok = ack_low_ok and ack_rise
    rst_a = reset_ok and ready
    rst_eff = rst_a and latched
    latched_next = flt or (latched and not rst_eff)
    # FF2: asynchronous reset plus a level-sensitive set (SET dominates).  This
    # pass carries the hold/reset half of Q; ``token_next`` adds the set term
    # ``ACK_ARM = READY and not ACK_RAW``.
    token_held = (not ff2_reset) and ack_low_ok
    return {
        "healthy": healthy, "fast_armed": fast_armed, "fault": fault_a or not_healthy,
        "flt": flt, "ready": ready, "permit": permit, "latched_next": latched_next,
        "token_held": token_held, "rst_eff": rst_eff, "ack_rise": ack_rise,
    }


def token_next(*, ff2_reset: bool, ready: bool, ack_raw: bool, token: bool) -> bool:
    """FF2 next state: ACK_ARM sets the token, any fault or lost READY clears it.

    ``ACK_ARM`` is a *level* (READY and the button not pressed), so the token is
    armed before the operator presses: the first press after power-up clears the
    latch.  An edge-triggered FF2 armed only on release, which swallowed that
    first press.  SET dominates RESET, as on the CD4013.
    """
    ack_arm = ready and not ack_raw
    return ack_arm or (token and not ff2_reset)


# ---------------------------------------------------------------- structural
def origin(part: Part) -> tuple[float, float]:
    """Absolute placement of one unit.

    Units of the same package must not share an origin: each unit's symbol
    space puts the same pins in the same places, so two units at one point have
    their pin tips coincident and KiCad merges the nets.  The offset keeps every
    tip on the 1.27 mm grid (11.43 = 9 x 1.27).
    """
    return part.x + 11.43 * (part.unit - 1), part.y - 11.43 * (part.unit - 1)


def pin_tip_positions(part: Part, symbols: dict[str, str]) -> dict[str, tuple[float, float]]:
    """Pin number -> absolute tip position for one unit instance."""
    tips = pin_tips(symbols[part.lib])
    x, y = origin(part)
    return {num: (round(x + tips[num][0], 3), round(y - tips[num][1], 3)) for num in part.nets}


def validate(ps: list[Part], symbols: dict[str, str]) -> None:
    """Every pin of a unit must be assigned, and no two nets may share a tip."""
    seen: set[str] = set()
    for part in ps:
        key = f"{part.ref}#{part.unit}"
        if key in seen:
            raise SystemExit(f"duplicate reference/unit {key}")
        seen.add(key)
        if part.lib not in symbols:
            raise SystemExit(f"{part.ref}: unknown symbol {part.lib}")
        nums = unit_pin_numbers(symbols[part.lib], part.unit)
        if not nums:
            raise SystemExit(f"{part.ref}: unit {part.unit} not in {part.lib}")
        if set(nums) != set(part.nets):
            raise SystemExit(f"{part.ref} unit {part.unit}: pins {nums} != nets {sorted(part.nets)}")
        for net in part.nets.values():
            if net != NC and (not net or " " in net):
                raise SystemExit(f"{part.ref}: bad net name {net!r}")
    validate_no_coincident_tips(ps, symbols)


def validate_no_coincident_tips(ps: list[Part], symbols: dict[str, str]) -> None:
    """Two labels at one point join their nets, so tips must not coincide."""
    occupied: dict[tuple[float, float], str] = {}
    for part in ps:
        positions = pin_tip_positions(part, symbols)
        for num, net in part.nets.items():
            if net == NC:
                continue
            pos = positions[num]
            other = occupied.setdefault(pos, net)
            if other != net:
                raise SystemExit(
                    f"{part.ref}.{num} ({net}) lands on {other} at {pos}: "
                    "two nets would be joined by a coincident label"
                )


def nets_of(ps: list[Part]) -> dict[str, list[str]]:
    """Net name -> list of ``REF.pin`` endpoints, for the report and the tests."""
    out: dict[str, list[str]] = {}
    for part in ps:
        for pin, net in part.nets.items():
            if net != NC:
                out.setdefault(net, []).append(f"{part.ref}.{pin}")
    return {k: sorted(v) for k, v in sorted(out.items())}


# ---------------------------------------------------------------- schematic
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
	(generator "make_d0_protection_board.py")
	(generator_version "10.0")
	(uuid "{uid("root")}")
	(paper "A2")
	(title_block
		(title "D0 ten-gate protection logic bench board")
		(date "2026-11-04")
		(rev "A")
		(comment 1 "Bench logic board. NOT for fabrication. Not a power stage, not thermal, not timing.")
		(comment 2 "Generated by tools/make_d0_protection_board.py; the part table is the source of truth.")
		(comment 3 "Corresponds to issue #36 checkbox 2. Physical assembly and scope acceptance PENDING.")
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
    """Keep every pin tip on KiCad's 1.27 mm connection grid."""
    return replace(part, x=round(part.x / 1.27) * 1.27, y=round(part.y / 1.27) * 1.27)


def write_libs(symbols: dict[str, str]) -> None:
    """Project-local symbol libraries for the two custom drivers."""
    libs = {"UCC27524": "UCC27524ADR", "UCC27282": "UCC27282DRCR"}
    for lib, name in libs.items():
        key = f"{lib}:{name}"
        block = symbols[key].replace(f'(symbol "{key}"', f'(symbol "{name}"', 1)
        text = ('(kicad_symbol_lib (version 20241209) (generator "make_d0_protection_board.py")\n'
                + block[block.index("("):] + "\n)\n")
        (OUT / f"{lib}.kicad_sym").write_text(text, encoding="utf-8")
    rows = "".join(
        f'\t(lib (name "{lib}")(type "KiCad")(uri "${{KIPRJMOD}}/{lib}.kicad_sym")'
        '(options "")(descr ""))\n' for lib in libs)
    (OUT / "sym-lib-table").write_text(
        f'(sym_lib_table\n\t(version 7)\n{rows})\n', encoding="utf-8")


def physical_components(parts_: list[Part]) -> list[Part]:
    """One orderable physical package per reference, not one per KiCad unit.

    Multi-unit CMOS symbols (e.g., U11 seven units including VDD/GND)
    describe ONE chip. The old BOM issued seven quantities of U11 with
    identical reference labels. Fail rather than silently picking one when
    a repeated reference disagrees about its actual MPN or footprint.
    """
    by_ref: dict[str, Part] = {}
    units: dict[str, set[int]] = {}
    for part in parts_:
        if part.ref.startswith("#"):
            continue
        previous = by_ref.get(part.ref)
        if previous is None:
            by_ref[part.ref] = part
            units[part.ref] = {part.unit}
            continue
        if part.unit in units[part.ref]:
            raise ValueError(f"{part.ref}: duplicate schematic unit {part.unit}")
        units[part.ref].add(part.unit)
        for field in ("lib", "value", "footprint", "dnp", "source"):
            if getattr(previous, field) != getattr(part, field):
                raise ValueError(f"{part.ref}: conflicting BOM {field} across units")
        if previous.rating and part.rating and previous.rating != part.rating:
            raise ValueError(f"{part.ref}: conflicting package rating")
        if previous.note and part.note and previous.note != part.note:
            # Each unit can legitimately describe a different logic function,
            # so preserve one physical row while retaining full notes in
            # the schematic/report, rather than treating each as a part.
            pass
        if not previous.rating and part.rating:
            previous = replace(previous, rating=part.rating)
        if not previous.note and part.note:
            previous = replace(previous, note=part.note)
        by_ref[part.ref] = previous
    return list(by_ref.values())


def bom(parts_: list[Part]) -> None:
    path = OUT / "BOM.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Reference", "Value", "Footprint", "Rating", "Note", "DNP",
                    "Provenance", "Source", "Qty"])
        for part in physical_components(parts_):
            w.writerow([part.ref, part.value, part.footprint, part.rating, part.note,
                        "yes" if part.dnp else "", "SOURCED" if part.source != "DESIGN_PROPOSAL"
                        else "DESIGN_PROPOSAL", part.source, 1])
    print(f"wrote {path}")


def project_file() -> str:
    """The ``.kicad_pro`` without which ERC cannot see the project libraries.

    ``missing_courtyard`` is raised from its default to **error** for the same
    reason ``main_board_mechanical`` does it: KiCad can leave that check off, and
    a board whose every footprint lacked a courtyard would then report zero
    violations while nothing had been checked.  ERC does not read this section.
    """
    return json.dumps({
        "board": {"design_settings": {"rule_severities": {"missing_courtyard": "error"}}},
        "boards": [], "cvpcb": {}, "erc": {},
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": "d0_protection.kicad_pro", "version": 1},
        "net_settings": {}, "pcbnew": {},
        "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
        "sheets": [[uid("root"), "Root"]],
        "text_variables": {},
    }, indent=2) + "\n"


def erc_violations(path: Path | None = None, *, source: str = "d0_protection.kicad_sch",
                   newer_than: Path | None = None) -> list[dict]:
    """Violations from a fresh ERC report -- never from a stale or absent one.

    This used to return ``[]`` when the report was missing, so a crashed or
    unsupported ``kicad-cli sch erc`` read as "0 violations".  A check that
    cannot distinguish "clean" from "nothing ran" is not a check.
    """
    path = path or OUT / "erc.json"
    if not path.exists():
        raise SystemExit(f"ERC report missing: {path} -- refusing to report it as clean")
    if newer_than is not None and path.stat().st_mtime < newer_than.stat().st_mtime:
        raise SystemExit(f"ERC report {path.name} is older than {newer_than.name}: "
                         "it does not describe this schematic")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("source") != source:
        raise SystemExit(f"ERC report {path.name} is about {data.get('source')!r}, not {source!r}")
    sheets = data.get("sheets") or []
    if not sheets:
        raise SystemExit(f"ERC report {path.name} has no sheets: this is not a completed run")
    return [v for sheet in sheets for v in sheet.get("violations", [])]


def resistance(text: str) -> float:
    """Parse the part-table resistor spelling: '10k', '14.7k', '2.2R'."""
    suffix = text[-1]
    if suffix == "k":
        return float(text[:-1]) * 1e3
    if suffix == "R":
        return float(text[:-1])
    return float(text)


def capacitance(text: str) -> float:
    """Parse the part-table capacitor spelling: '100nF/16V', '1uF/25V', '10nF'."""
    body = text.split("/")[0]
    for suffix, scale in (("pF", 1e-12), ("nF", 1e-9), ("uF", 1e-6)):
        if body.endswith(suffix):
            return float(body[: -len(suffix)]) * scale
    raise ValueError(f"cannot read a capacitance from {text!r}")


def rc_ms(ref_resistor: str, ref_capacitor: str) -> float:
    """RC time constant in milliseconds, read from the part table.

    The ACK notes used to state "10 ms (R30*C17)" in prose while R30 and C17
    were separate table entries, so changing either value left the text lying.
    """
    return resistance(part_value(ref_resistor)) * capacitance(part_value(ref_capacitor)) * 1e3


def part_value(ref: str) -> str:
    for part in parts():
        if part.ref == ref:
            return part.value
    raise KeyError(f"no part {ref} in the part table")


def divider_output(ref_top: str, ref_bottom: str) -> float:
    """Voltage at the tap of a two-resistor divider across the 2.500 V reference."""
    top, bottom = resistance(part_value(ref_top)), resistance(part_value(ref_bottom))
    return 2.5 * bottom / (top + bottom)


def rail_good_node(vin: float = 12.0) -> float:
    """Voltage the 12 V supervisor sees at ``vin`` (must stay under VCC-1.5 V)."""
    top, bottom = resistance(part_value("R20")), resistance(part_value("R21"))
    return vin * bottom / (top + bottom)


def rail_good_trip() -> float:
    """Input voltage at which the supervisor divider reaches the reference."""
    top, bottom = resistance(part_value("R20")), resistance(part_value("R21"))
    return divider_output("R2", "R3") * (top + bottom) / bottom


def burden_numbers() -> tuple[float, float]:
    """The published CT slope (V per amp at the OC node) and its hard-trip current."""
    data = json.loads((ROOT / CT_DESIGN).read_text(encoding="utf-8"))["as_built"]
    return float(data["slope_v_per_a_peak"]), float(data["trip_peak_a"])


def burden_gain() -> float:
    """Rf/Rd1/Rd2 divider gain, from the published CT record.

    The slope above is quoted at the *OC pin*, behind this divider; ``V(ocdf)``
    sits on the burden ahead of it.  Anything comparing the two thresholds has
    to convert through this gain, or it reads 1/gain = 1.46x high.
    """
    data = json.loads((ROOT / CT_DESIGN).read_text(encoding="utf-8"))["as_built"]
    return float(data["divider_gain"])


def trip_timing_record() -> dict | None:
    """The measured two-channel timing, if the tool that writes it has run.

    Optional on purpose: generating the board needs no raw files, and a machine
    without them must still rebuild the schematic.  When the record is present
    its numbers are used instead of a remembered sentence.
    """
    path = ROOT / "design" / "v3" / "stage_f" / "d0_trip_timing.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))["results"]


# LM393 inputs, references/datasheets/lm393.txt (SLCS005AH) section 5.8, which
# tabulates VICR twice: 0 to VCC-1.5 at 25 C and 0 to VCC-2 over the full
# range.  At V5 = 5 V those are 3.5 V and 3.0 V.  The board's divider has
# always been sized against the 25 C row; the full-range row is the guaranteed
# number, so both are kept and both are reported.  Neither is a design margin
# the board can retune away: the divider's ratio is what sets the gate trip,
# and the datasheet's own note allows one input to exceed the range, which is
# the input that is *not* the 0.200 V reference.
LM393_VICR_25C_V = 3.5
LM393_VICR_FULL_RANGE_V = 3.0
LM393_COMMON_MODE_LIMIT_V = LM393_VICR_25C_V
LM393_COMMON_MODE_LIMIT_FULL_RANGE_V = LM393_VICR_FULL_RANGE_V
LM393_COMMON_MODE_SOURCE = ("references/datasheets/lm393.txt (SLCS005AH, revised "
                            "April 2025; section 5.8, VICR row)")

# One gate driven at a time, at a level a healthy 12 V driver reaches with
# margin.  The per-channel sweep in gate_sense_bring_up() uses it.
BRING_UP_GATE_V = 10.0


def gate_branch_resistance() -> float:
    """The 1k between a gate and its detector diode, read from the part table."""
    return resistance(part_value("R66"))


def gate_sense_v(gate_v: float, *, conducting: int = 1, vf: float = 0.0) -> float:
    """V(GATE_SENSE) when ``conducting`` gates sit at ``gate_v``.

    Only the highest gate forward-biases its diode, so the ordinary case is one
    gate: the other nine branches are reverse-biased and contribute nothing,
    which is exactly why a diode-OR answers "is *any* gate on" while a resistor
    sum answers "how much gate voltage is there in total".  ``conducting`` > 1
    describes the special case where several gates share the *same* voltage; it
    is what sizes the divider, because n parallel 1k branches are the lowest
    series resistance the node can ever see.  ``vf`` lowers the node, so 0 V is
    the worst case for the common-mode bound.
    """
    if conducting < 1:
        raise ValueError("at least one gate has to conduct")
    series = gate_branch_resistance() / conducting
    top, bottom = resistance(part_value("R76")), resistance(part_value("R77"))
    return (gate_v - vf) * bottom / (series + top + bottom)


def gate_trip_v(vf: float = 0.0) -> float:
    """Gate volts at which a single gate's branch reaches the 0.200 V reference.

    ``vf`` is the detector diode's forward drop at that current; it adds to the
    gate voltage needed, so the default 0 V is the optimistic end.
    """
    series = gate_branch_resistance()
    top, bottom = resistance(part_value("R76")), resistance(part_value("R77"))
    return divider_output("R6", "R7") * (series + top + bottom) / bottom + vf


def gate_rail_for_common_mode(limit_v: float | None = None) -> float:
    """Gate rail at which all ten gates high land exactly on the VICR bound.

    Ten conducting is the worst case for the comparator input, not the best:
    parallel branches lower the series resistance, so the sense node reaches
    higher for a given gate voltage than it does with one gate on.

    ``limit_v`` defaults to the 25 C row (3.5 V -> 15.98 V of gate); passing
    the full-range row gives 13.69 V, which the 15 V TVS standoff exceeds.
    """
    limit = LM393_COMMON_MODE_LIMIT_V if limit_v is None else limit_v
    series = gate_branch_resistance() / 10
    top, bottom = resistance(part_value("R76")), resistance(part_value("R77"))
    return limit * (series + top + bottom) / bottom


def gate_rail_for_full_range_common_mode() -> float:
    """Same bound on the guaranteed-over-temperature VICR row (3.0 V)."""
    return gate_rail_for_common_mode(LM393_COMMON_MODE_LIMIT_FULL_RANGE_V)


def gate_sense_bring_up() -> list[dict]:
    """The per-channel first-article sweep: one gate driven at a time.

    An open diode or an open branch resistor blinds exactly one channel and
    leaves the other nine working, so a single "all ten gates high" test cannot
    see it -- the node still reads the all-ten value.  Ten gates driven one at a
    time must each produce the same 2.123 V; the channel that reads low is the
    open one.
    """
    gates = [f"GA{i}" for i in range(1, 9)] + ["GH1", "GL1"]
    reference = divider_output("R6", "R7")
    rows = []
    for index, gate in enumerate(gates):
        sense = gate_sense_v(BRING_UP_GATE_V, conducting=1)
        rows.append({"gate": gate, "net": f"GK{index + 1}",
                     "gate_v": BRING_UP_GATE_V, "gate_sense_v": sense,
                     "reference_v": reference, "reads_on": sense > reference})
    return rows


def observations() -> list[dict]:
    """Facts a reader must know before treating this board as evidence.

    Every threshold is derived from the part table (or from ``ct_design.json``)
    rather than restated: the previous hand-written numbers survived a change in
    the reference base and were wrong by 1.4-1.8x on the gate sum.
    """
    slope, hard_a = burden_numbers()
    gain = burden_gain()
    fast_v = divider_output("R4", "R5")
    # slope is burden-peak-current -> OC pin; V(ocdf) sits on the burden itself,
    # so the burden node moves slope/gain per amp and the fast threshold is at
    # fast_v * gain / slope.  Dividing by the slope alone inflates it 1/gain =
    # 1.46x, which is how the board used to claim a 42.9 A fast threshold.
    burden_v_per_a = slope / gain
    fast_a = fast_v / burden_v_per_a
    hard_v = divider_output("R2", "R3")
    ref_0v2 = divider_output("R6", "R7")
    measured = trip_timing_record()
    return [
        {"id": "FAST_IS_EARLIER_BUT_NOT_MORE_SENSITIVE",
         "statement": f"The {fast_v:.3f} V fast threshold sits on the filtered burden "
                      f"node (gain 1.0, one 1k/10n pole), the {hard_v:.3f} V hard trip "
                      f"behind the Rf/Rd1/Rd2 divider (gain {gain:.4f}, two poles of "
                      f"47 us and 75.4 us). Converted on their own nodes they are "
                      f"{fast_a:.1f} A versus {hard_a:.1f} A peak: the fast channel is "
                      f"the earlier one and the less sensitive one at the same time."
                      + (f" Measured on the 48 V hot-fault pair it fires "
                         f"{measured['fast_is_earlier_us']:.1f} us earlier "
                         f"({measured['fast_delay_us']:.1f} us versus "
                         f"{measured['hard_delay_us']:.1f} us after the fault)."
                         if measured else ""),
         "consequence": "'Faster' and 'more sensitive' are two claims and only the first "
                        "one holds. A statement that the fast channel is both is a unit "
                        "error: the two thresholds are on different nodes and one "
                        "divider gain separates them.",
         "source": ("design/v3/stage_f/d0_trip_timing.json" if measured
                    else f"{DECK}:{deck_line('Rbur')}-{deck_line('Coc')}")},
        {"id": "GATE_MAX_DETECTOR_REPORTS_THE_HIGHEST_GATE",
         "statement": f"Each gate drives a 1k into its own Schottky; the ten cathodes "
                      f"share GSMAX, divided by 22k/6.2k against the {ref_0v2:.3f} V "
                      f"reference. Because only the highest gate forward-biases its "
                      f"diode, one gate at 3 V reads "
                      f"{gate_sense_v(3.0, conducting=1):.3f} V -- "
                      f"{gate_sense_v(3.0, conducting=1) / ref_0v2:.1f}x the reference -- "
                      f"whatever the other nine are doing, where the ten-resistor sum it "
                      f"replaces read 0.150 V, below the reference, i.e. 'off'. The trip "
                      f"is {gate_trip_v():.3f} V of gate voltage plus the diode drop, "
                      f"under VGS(th) min = 1.3 V, so a FET that is barely conducting "
                      f"already reads on. All ten high give "
                      f"{gate_sense_v(12.0, conducting=10):.3f} V at the 12 V rail and "
                      f"{gate_sense_v(15.0, conducting=10):.3f} V at the 15 V TVS "
                      f"standoff. At 12 V that is inside both LM393 VICR rows "
                      f"(VCC-1.5 = 3.5 V at 25 C, VCC-2 = 3.0 V over the full range); "
                      f"at 15 V it is inside the 25 C row and 0.29 V above the "
                      f"full-range one, which the datasheet permits because only one "
                      f"input has to be in range and the other input here is the "
                      f"0.200 V reference; that "
                      f"bound is a resistor ratio, so it holds for any diode drop, which "
                      f"the BZX84C3V0 it replaces could not -- a Zener knee is specified "
                      f"at 5 mA and this node spends tens of microamps.",
         "consequence": "It answers 'is any gate on' without being diluted by gates that "
                        "are off, but it cannot say which gate, and an open diode or "
                        "branch resistor blinds one channel invisibly to an all-high "
                        "test -- hence the ten-step bring-up sweep in "
                        "gate_sense_bring_up(). The diode drop over temperature has no "
                        "vendored datasheet, so the trip band between the ideal "
                        f"{gate_trip_v():.3f} V and VGS(th) min 1.3 V is UNVERIFIED "
                        "until measured at first article.",
         "source": "DESIGN_PROPOSAL"},
        {"id": "RAIL_GOOD_TRIP_IS_A_DIVIDER_RATIO",
         "statement": f"Both 12 V supervisors compare a 100k/14.7k divider against the "
                      f"{divider_output('R2', 'R3'):.3f} V reference: trip "
                      f"{rail_good_trip():.2f} V, {rail_good_node():.2f} V at 12 V. The "
                      f"base has to stay low -- with the 2.5 V reference the first draft "
                      f"read 3.84 V at 12 V, above both LM393 VICR rows (3.5 V at 25 C, "
                      f"3.0 V over the full range), where the output is not specified.",
         "consequence": f"Rail-good is a {rail_good_trip():.1f} V threshold on a 12 V rail, "
                        f"so the drivers are declared healthy down to "
                        f"{rail_good_trip():.1f} V and run with reduced gate drive in that "
                        f"band. The trip is set by resistor choice and is not adjusted "
                        f"at first article.",
         "source": f"{CTRL}:proposed_sr_channels"},
        {"id": "EN_THRESHOLD_IS_A_TABLE_FIGURE_BUT_NOT_PRODUCTION_TESTED",
         "statement": "UCC27524ADR ENA/ENB thresholds come from the vendored datasheet "
                      "(references/datasheets/ucc27524a.txt, SLUSBP4C, D package): "
                      "VEN_H 1.9 V min, VEN_L 1.35 V max, 0.7/0.95/1.1 V of hysteresis. "
                      "The 5 V PERMIT_RAIL clears VEN_H min by 3.1 V, and the released "
                      "rail settles at 0.26 V, below VEN_L max by 1.09 V, so both ends "
                      "of the logic are specified rather than assumed.",
         "consequence": "What is still missing is not a threshold but an acceptance: the "
                        "datasheet states that switching parameters are not tested in "
                        "production, and the internal EN pull-up is a 200 k typical with "
                        "no min or max, so the released-rail ceiling is nominal. The "
                        "permit stage stays unqualified until first article.",
         "source": f"{CTRL}:proposed_sr_channels"},
        {"id": "ACK_TIMING_UNQUALIFIED",
         "statement": "The release token is a level latch, not an edge sampler: "
                      "ACK_ARM = READY and the button not pressed sets it, and any fault "
                      "or lost READY clears it, so the first press after power-up is the "
                      "one that clears the fault latch (an edge sampler armed on release "
                      "would swallow that press). The press charges C17 straight from V5 "
                      f"through the button; the {rc_ms('R30', 'C17'):.2g} ms (R30*C17) is "
                      f"the release decay and the {rc_ms('R31', 'C18'):.2g} ms edge window "
                      "is R31*C18.",
         "consequence": "The press path is undebounced, so one contact bounce while READY "
                        "is indistinguishable from an operator press and clears the latch; "
                        "only the release is filtered. Neither the "
                        f"{rc_ms('R31', 'C18'):.2g} ms window nor the "
                        "bounce sensitivity is qualified on hardware.",
         "source": f"{LOGIC}:50-61"},
        {"id": "PERMITS_USE_CURRENT_STATE_NOT_NEXT_STATE",
         "statement": "The reference model computes permits from next_latched; the "
                      "hardware computes PERMIT from the latch's present Q.",
         "consequence": "On the single cycle that clears the latch, the model already "
                        "permits while the hardware still does not (one gate delay). "
                        "The hardware can only be later, never earlier -- the safety "
                        "direction. This is why the test asserts an implication, not "
                        "equality, for permits.",
         "source": f"{LOGIC}:62-63"},
        {"id": "NO_COMPARATOR_OR_DRIVER_DELAY",
         "statement": "No propagation delay is modelled or budgeted for the LM393, the "
                      "CD4xxx network, or the UCC27524A/UCC27282.",
         "consequence": "Nothing here says how long the ten gates take to go low. The "
                        "only published number is UCC27282 EN-to-output ~1.5 us typical, "
                        "which is not a worst-case bound.",
         "source": f"{CTRL}:native_primary"},
        {"id": "BENCH_DRIVE_IS_SHARED",
         "statement": "All eight SR channels are driven from one TG_SR input, matching "
                      "the deck's in-phase drive.",
         "consequence": "This board cannot demonstrate per-channel timing differences, "
                        "and it does not reproduce the UCC24624 gate outputs it would "
                        "eventually sit behind.",
         "source": f"{DECK}:{deck_line('Bgh')}-{deck_line('Bgl')}"},
        {"id": "NO_HARDWARE_HAS_BEEN_BUILT",
         "statement": "No board exists. The netlist and ERC pass are machine checks of "
                      "a generated schematic, not evidence that the circuit works.",
         "consequence": "fabrication_approved stays false; assembly and scope "
                        "acceptance are PENDING in issue #36.",
         "source": "tools/make_d0_protection_board.py"},
    ]


def report(ps: list[Part]) -> dict:
    nets = nets_of(ps)
    sourced = [p for p in ps if p.source != "DESIGN_PROPOSAL"]
    return {
        "kind": "D0_TEN_GATE_PROTECTION_BOARD",
        "evidence_level": "GENERATED_SCHEMATIC_AND_NETLIST_NOT_HARDWARE",
        "hardware_built": False,
        "fabrication_approved": False,
        "logic_verified_against": LOGIC,
        "part_instances": len(ps),
        "physical_parts": len(physical_components(ps)),
        "nets": len(nets),
        "sourced_values": len(sourced),
        "design_proposals": len(ps) - len(sourced),
        "parts": [{"ref": p.ref, "unit": p.unit, "value": p.value, "dnp": p.dnp,
                   "provenance": "SOURCED" if p.source != "DESIGN_PROPOSAL"
                   else "DESIGN_PROPOSAL", "source": p.source}
                  for p in ps],
        "net_map": nets,
        "observations": observations(),
    }


def check() -> None:
    cli = kicad_cli()
    if cli is None:
        raise SystemExit("kicad-cli not found: ERC and netlist export cannot be reproduced here")
    sch = OUT / "d0_protection.kicad_sch"
    net = OUT / "d0_protection.net"
    erc = OUT / "erc.rpt"
    (OUT / "d0_protection.kicad_pro").write_text(project_file(), encoding="utf-8")
    subprocess.run([str(cli), "sch", "export", "netlist", str(sch), "-o", str(net)],
                   check=True)
    # --severity-all: the default report skips exclusions, and "0 violations"
    # has to mean every severity or it is not a sign-off.
    # check=True catches only hard failures -- kicad-cli exits 0 when it *reports*
    # violations -- so the report's own content is checked separately below.
    subprocess.run([str(cli), "sch", "erc", "--severity-all", str(sch), "-o", str(erc)],
                   check=True)
    subprocess.run([str(cli), "sch", "erc", "--severity-all", "--format", "json",
                    str(sch), "-o", str(OUT / "erc.json")], check=True)
    text = net.read_text(encoding="utf-8")
    print(f"netlist: {text.count('(net' + chr(10))} nets -> {net.name}")
    violations = erc_violations(newer_than=sch)
    print(f"ERC: {len(violations)} violation(s) at every severity")
    if violations:
        for v in violations:
            print(f"  {v['severity']} {v['type']}: {v['description']}")
        raise SystemExit("ERC is not clean -- fix the circuit or record why each one is accepted")
    required = ["V12P", "V12S", "V5", "PGND", "OC", "HARD_TRIP", "FAST_TRIP",
                "HEALTHY", "READY", "LATCHED", "ACK_LOW_OK", "ACK_ARM", "FLT",
                "PERMIT", "PERMIT_RAIL", "GSMAX", "GATE_SENSE"]
    # Nets are named "/<label>" on a single sheet, so a substring match on the bare
    # label never finds them -- parse the name field instead.
    net_names = set(re.findall(r'\(name "/([^"]+)"\)', text))
    missing = [n for n in required if n not in net_names]
    if missing:
        raise SystemExit(f"nets missing from netlist: {missing}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    symbols = build_symbols()
    ps = [snap(p) for p in parts()]
    validate(ps, symbols)
    write_libs(symbols)
    path = OUT / "d0_protection.kicad_sch"
    path.write_text(schematic(symbols, ps), encoding="utf-8")
    print(f"wrote {path}  ({len(ps)} part instances, {len(symbols)} symbols)")
    bom(ps)
    (OUT / "report.json").write_text(
        json.dumps(report(ps), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'report.json'}")
    if args.check:
        check()


if __name__ == "__main__":
    main()
