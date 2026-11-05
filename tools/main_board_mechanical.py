"""A5: 1:1 mechanical placement of the main power stage, now carrying nets.

What this is
------------
A single table of parts with real outlines, laid out on a KiCad board that
opens in the editor and renders in 3D.  Two questions live here:

* **does it all physically fit, and where does the height problem land** -- the
  outlines, the clearances and the A6 section;
* **where does the current actually have to go** -- every pad now carries the
  net `pin_footprint_review.csv` assigns it, so the editor draws the real
  ratsnest and per-net straight-line lengths can be compared across the four
  identical groups (ELE-04).

The nets are *read*, not invented: ``hardware/dcx_main/pin_footprint_review.csv``
is the table that already arbitrates the logical netlist against a footprint.
Where that table has no row for a placed part, the pad stays netless and the
report says which one and why -- the fifteen bulk capacitors are the clear case,
because the schematic models the whole bank as a single lumped ``Cout``.

What it is not
--------------
Not a routed board, not a DRC-clean design, not a manufacturing output.  Nets
make the connectivity visible; they do not route it, and every ratsnest line is
still a missing track.  `kicad-cli pcb drc` is still run, but only for the
things a placement can be wrong about: courtyards that touch, pads that collide,
and footprints from a library the project cannot see (a footprint KiCad cannot
resolve is a black box, so its courtyard is not checked either -- the same trap
already documented for the schematic side in ``make_control_board.py``).

Where each number comes from
----------------------------
Every outline carries an evidence class, and the report prints it:

``generated-json``  read from a tool's JSON in this repo (ELP32 core, Cout
                    height, busbar section).
``digitised-datasheet``  a land pattern measured off the datasheet's board-pads
                    figure (the SR FET).  Better than a borrowed library part,
                    still not vendor CAD and not checked against IPC-7351.
``kicad-library``   the stock footprint's own dimensions.  No part uses this
                    class any more; the machinery is kept because the vendored
                    library and its PROVENANCE guard are still exercised.
``datasheet``       a package size the BOM marks VERIFIED.  Body only: the
                    part's pads on this board are still placeholders, which is
                    why the report lists it under ``land_pattern_provisional``.
                    No part uses this class any more -- QH/QL were the last, and
                    their land is now digitised -- but the filter stays because
                    it is what makes the class mean something.
``PROVISIONAL``     nobody has selected the part.  CT, Cr, J_IN and the
                    control area are placeholders with a stated size, and the
                    report lists them so a reader cannot mistake the drawing
                    for a BOM.

The height finding
------------------
Five ELP32 cores (T1-T4 and Lr -- Lr is on the *same* core, per
``lr_design.json``) are 9.8 mm worst case.  ``magnetics_design.json`` reports
the flat stack at 9.94 mm: it clears 10 mm by 60 um, which is smaller than the
glue, the label and the core's own flatness.  Add the 0.5 mm clamp and the same
stack is 10.44 mm, over.  So the Z answer is not "it fits" -- it is "it fits
flat only by coincidence, and the moment the cores are retained it does not fit
at all".

Usage:
    python tools/main_board_mechanical.py
    python tools/main_board_mechanical.py --check    # + kicad-cli DRC, fails on errors
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "hardware" / "dcx_mech"
DESIGN = ROOT / "design" / "v3"
# Official footprints this board borrows are vendored; see
# hardware/stock_footprints/PROVENANCE.md.  Nothing here may name a user
# directory: the generator has to reproduce the committed board on any machine
# and on a CI runner that has no KiCad at all (Issue #11).
STOCK = ROOT / "hardware" / "stock_footprints"
NS = uuid.UUID("a5b6c7d8-1e2f-4a3b-9c4d-5e6f7a8b9c0d")

HEIGHT_LIMIT_MM = 10.0
XFMR_FP = "dcx:ELP32_XFMR"
LR_FP = "dcx:ELP32_LR"
CORE_FOOTPRINTS = (XFMR_FP, LR_FP)
EDGE_MARGIN_MM = 5.0
BOARD_T = 1.6
REVIEW = ROOT / "hardware" / "dcx_main" / "pin_footprint_review.csv"
# The 61-row placeholder register.  It, not the review table, owns values: the
# review table's note column still calls every gate resistor a "PLACEHOLDER 0603
# 10k", which would put 10 k on a 2.2 ohm gate and 10 k on a 0 ohm Kelvin link.
ECO = ROOT / "hardware" / "dcx_main" / "placeholder_eco.json"
# Vendored (hardware/stock_footprints/PROVENANCE.md): courtyard 2.96 x 1.46,
# pads at +-0.825 x 0.8 x 0.95, reference text 1.43 mm above centre.
R0603_FP = "Resistor_SMD:R_0603_1608Metric"
R0603_W, R0603_D, R0603_H = 2.96, 1.46, 0.55
# Vendored (PROVENANCE.md): SOIC-8, courtyard 7.4 x 5.4, pads at +-2.475 x
# {+-1.905, +-0.635}, MS-012AA body height max 1.75 mm.  This is the land of the
# four SR controllers U3-U6; it is a library part, not a vendor drawing.
SOIC8_FP = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
SOIC8_W, SOIC8_D, SOIC8_H = 7.4, 5.4, 1.75
# The REG crowbar (doc 34, package C: "紧接着连接选定的实际硬件关断电路").  Not a
# new circuit: it is the shutdown `pcb/sr_fault_validation` selected, with one
# copy per controller.  UCC24624 has no enable pin -- only a REG undervoltage or
# standby pulls VG low -- so pulling REG through 4.7 ohm (12.1 us) is the chosen
# route, against 75.5 ms for cutting VDD.
#
# Courtyards are the vendored lands (hardware/stock_footprints/PROVENANCE.md),
# measured from the files themselves, same as every other library part here.
# The heights are SOT-23/SOD-123/1206/0603 *package envelopes*: the repository's
# AO3400A text has no mechanical section, so unlike the Q5A and the SR land these
# are not datasheet maxima.  They are all under 2 mm in a 10 mm stack, so they
# cannot move the A6 section either way.
SOT23_FP = "Package_TO_SOT_SMD:SOT-23"
SOT23_W, SOT23_D, SOT23_H = 3.86, 3.40, 1.10
SOD123_FP = "Diode_SMD:D_SOD-123"
SOD123_W, SOD123_D, SOD123_H = 4.70, 2.30, 1.35
R1206_FP = "Resistor_SMD:R_1206_3216Metric"
R1206_W, R1206_D, R1206_H = 4.56, 2.26, 0.60
C0603_FP = "Capacitor_SMD:C_0603_1608Metric"
C0603_W, C0603_D, C0603_H = 2.96, 1.46, 0.90
# The two FET lands are digitised into JSON and generated from it.  ``parts()``
# runs while this module is still executing, and the builders import this module
# back, so it reads these files instead of calling them -- see ``_land_pads``.
LAND = {
    "dcx:BSC010N04LS6": DESIGN / "pcb" / "bsc010n04ls6_land.json",
    "dcx:CSD19531Q5A": DESIGN / "pcb" / "csd19531q5a_land.json",
}


def uid(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


def _load(rel: str) -> dict:
    return json.loads((DESIGN / rel).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- netlist
# The arbitration table: one row per (ref, logical pin, footprint pad, net).  It
# already exists for the schematic side, so the board reads it instead of
# re-deriving connectivity from the deck -- two derivations would eventually
# disagree and there would be no way to say which one the board believed.
BANK_PREFIX = "Cout"

# Row 3's two FETs per transformer start here; SR{i}A sits at x0 and SR{i}B at
# x0 + SR_PAIR_MM, so each group's centre is x0 + SR_PAIR_MM / 2.  The busbar
# reads the same tuple: it used to sit at x = 100, which was centre-ish for an
# 80 mm bar but put group 1 41 mm outside it and group 3/4 underneath.  Placing
# it on the centre of the row it serves is what makes the two outer groups pay
# the same, and it costs no copper.
SR_X0 = (14.0, 52.0, 90.0, 128.0)
SR_PAIR_MM = 10.0
SR_ROW_Y = 82.0
# The two resistor rows.  Both sit *below* the FET they serve, because the FET
# gate pad is on the part's lower edge: a tap from above has to squeeze past the
# source strip (0.10 mm of overlap at this x) and the inter-pad channel is
# 0.615 mm wide against the 0.775 mm a 0.25 mm track needs.  From below it is one
# straight vertical run into the gate pad's bottom edge.
SR_GATE_ROW_Y = 88.0
PRIMARY_GATE_ROW_Y = 57.5
# The SR controllers' band: between the primary row (its deepest part, Lr, ends
# at y = 64.7) and the FET row (starts at 79.18).  Above the FETs on purpose --
# the VG/VD taps then come down the 3.35 mm channel between the two FETs of
# their own pair, where below the row they would have to cross the drain slabs
# that span the whole body width.
SR_CTRL_ROW_Y = 72.0
# The crowbar band: whatever is left between the primary row's deepest part (Lr
# ends at 64.70) and the controllers (they start at 69.30).  The tallest part in
# it is the SOT-23 at 3.40 mm deep, so y = 67.0 splits the 4.60 mm band evenly --
# 0.60 mm to Lr, 0.60 mm to the controllers -- and it is the *max-min* choice,
# not a round number picked first and checked later.  The 1206 and the two 0603s
# clear by more.  Nothing already placed lives in this band.
CROWBAR_ROW_Y = 67.0
# One channel group per controller, at fixed offsets from the controller it
# serves: Q at dx -9.4, the 4.7 ohm at dx -4.2.  Derived, never typed -- the four
# groups are electrically identical, so a placement that gave one of them a
# longer REG path would be one nobody measured.  The channel groups span
# x_c - 11.33 .. x_c - 2.92, which leaves x 55.1 .. 83.7 free between groups 2
# and 3 for the shared front end.
CROWBAR_Q_DX = -9.4
CROWBAR_R_DX = -4.2
# The shared front end, left to right: the series limit into the clamp, the 5.1 V
# zener, the pulldown that makes the input fail-open, the 10 us filter, and the
# single 100 ohm gate resistor that drives all four gates.
CROWBAR_SHARED_X = {"R50": 60.00, "D50": 65.33, "R51": 70.66, "C50": 75.12, "R52": 79.58}


def crowbar_nets() -> dict[str, dict[str, str]]:
    """``ref -> pad -> net`` for the board-only REG crowbar.

    Board-only in the same sense as ``PERIPHERALS`` in ``main_board_schematic.py``
    and ``NOT_A_DECK_ELEMENT`` in ``board_netlist.py``: the SPICE deck has no
    crowbar, and the native schematic cannot draw one either -- ``library_pins``
    has no MOSFET and no Zener symbol.  Writing these rows into
    ``pin_footprint_review.csv`` would therefore assert native pins that do not
    exist, so the declaration lives here and ``part_nets`` reads it as a third
    source.  The value and footprint of every part still come from this generator;
    ``test_the_reg_crowbar_is_the_selected_shutdown_circuit_wired_to_all_four_regs``
    reads the same part back out of ``pcb/sr_fault_validation`` and fails if the
    two statements ever disagree.

    Pin roles are the reviewed board's, per pin: on the AO3400A (SOT-23) pin 1 is
    the gate, 2 the source on PGND, 3 the drain on REG.  The zener's cathode is
    pad 1 -- the SOD-123 has two pads and pad 1 is the banded end, which is the
    whole reason the validation board moved off a three-pad SOT-23 land.
    """
    shared = {
        "R50": {"1": "FAULT_IN", "2": "FAULT_G"},
        "D50": {"1": "FAULT_G", "2": "PGND"},
        "R51": {"1": "FAULT_G", "2": "PGND"},
        "C50": {"1": "FAULT_G", "2": "PGND"},
        "R52": {"1": "FAULT_G", "2": "RC_G"},
    }
    for i in range(1, 5):
        shared[f"Q{50 + i}"] = {"1": "RC_G", "2": "PGND", "3": f"REG_CROW{i}"}
        shared[f"R{52 + i}"] = {"1": f"REG{i}", "2": f"REG_CROW{i}"}
    return shared


def review_rows() -> list[dict]:
    with REVIEW.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def pad_nets() -> dict[str, dict[str, str]]:
    """``ref -> pad -> net`` for every pin the review table has mapped.

    An empty net cell means the table mapped the pad but not to a net (U2.2);
    it is dropped rather than turned into a net called ``""``, and the report's
    ``pad_without_a_net`` list keeps it visible.
    """
    out: dict[str, dict[str, str]] = {}
    for row in review_rows():
        if row["net"].strip():
            out.setdefault(row["ref"], {})[row["pad"]] = row["net"].strip()
    return out


def bank_nets() -> dict[str, str]:
    """The bulk bank's pad->net, taken from the *lumped* ``Cout`` symbol.

    ``cout_bank.json`` asks for fifteen physical capacitors while the schematic
    models all of them as one ``Cout``.  Fifteen refs therefore have no row of
    their own; borrowing the lumped symbol's two nets is the only reading that
    does not invent connectivity, and the report says so.
    """
    return pad_nets()["Cout"]


def part_nets(part: "Part") -> dict[str, str]:
    """The nets for one placed part: its own rows, the bank's, the crowbar's, or none.

    Filtered to the pads this footprint actually carries.  Without that filter a
    padless outline would still be counted as a connection -- the control area
    ``U2`` stands for a whole section, and its eleven netlist pins would appear
    on the board as if they had somewhere to land."""
    table = pad_nets()
    if part.ref in table:
        got = table[part.ref]
    elif part.ref.startswith(BANK_PREFIX):
        got = bank_nets()
    else:
        got = crowbar_nets().get(part.ref, {})
    if not got:
        return {}
    local = _pad_positions(part.footprint)
    return {pad: net for pad, net in got.items() if pad in local}


def placed_nets() -> dict[str, list[str]]:
    """``net -> refs`` across the whole board, for the report and the ratsnest."""
    out: dict[str, list[str]] = {}
    for part in PARTS:
        for pad, net in part_nets(part).items():
            out.setdefault(net, []).append(f"{part.ref}.{pad}")
    return {net: sorted(members) for net, members in sorted(out.items())}


# ---------------------------------------------------------------- part table
@dataclass(frozen=True)
class Part:
    ref: str
    value: str
    w_mm: float          # x extent
    d_mm: float          # y extent
    h_mm_worst: float    # z, worst case (not nominal)
    x: float             # centre
    y: float
    evidence: str
    footprint: str = ""   # "lib:name"; empty means generate one
    rot: float = 0.0
    note: str = ""


def _core() -> dict:
    return _load("magnetics/magnetics_design.json")["core"]


def _cout() -> dict:
    return _load("bom/cout_bank.json")["banks"][0]


def _eco_rows() -> dict[str, dict]:
    return {row["ref"]: row for row in
            json.loads(ECO.read_text(encoding="utf-8"))["rows"]}


def placeholder_value(ref: str) -> str:
    """A placed part's value, from the register that owns it.

    ``existing_value_or_rating`` reads "<value> <unit> [<qualifier>]; <why>".  The
    first two words are the value -- the qualifier after them ("external" for
    the primary pair) says where the number comes from, not what to place, and
    the clause after the semicolon is the argument for it.  Reading the register
    rather than restating "2.2 ohm" in this table means the board cannot drift
    from the document a reviewer signs off -- and it is the only source that is
    right: the review table's own note still says "PLACEHOLDER 0603 10k".
    """
    row = _eco_rows().get(ref)
    if row is None:
        raise SystemExit(f"{ref}: no row in {ECO.name}; cannot place a value "
                         f"that nothing in the repository states")
    return " ".join(row["existing_value_or_rating"].split(";")[0].split()[:2])


def _bar() -> dict:
    return _load("bom/connector_budget.json")["output"]["bar"]


def _sr_row_centre() -> float:
    """Mean centre of the four SR groups.

    Derived from ``SR_X0`` rather than written as 76.0 so that moving a group
    moves the busbar with it -- the two are one decision, and a literal here
    would silently reintroduce the offset this function exists to remove.
    """
    return sum(x0 + SR_PAIR_MM / 2.0 for x0 in SR_X0) / len(SR_X0)


def parts() -> tuple[Part, ...]:
    """The placement table.  Order is the reading order of the board, top to
    bottom, and every coordinate is the part *centre* in mm from the top-left."""
    core = _core()
    cout = _cout()
    bar = _bar()
    mag_w = core["outer_length_m"] * 1e3
    mag_d = core["core_depth_m"] * 1e3
    mag_h = core["height_max_m"] * 1e3
    COUT_FP = "dcx:Placeholder_Cout"
    tds = "dcx:BSC010N04LS6"

    out: list[Part] = []
    # Row 1 -- the four transformers, one per 3:1:1 set, evenly spaced so the
    # four secondary loops are identical.  Symmetry is a current-sharing
    # argument, not decoration.
    for i, x in enumerate((20.0, 58.0, 96.0, 134.0), start=1):
        out.append(Part(f"T{i}", "3:1:1 ELP32", mag_w, mag_d, mag_h, x, 20.0,
                        "generated-json", XFMR_FP))
    # Row 2 -- primary side, left to right in power-flow order.
    out.append(Part("Lr", "1.0 uH", mag_w, mag_d, mag_h, 20.0, 52.0,
                    "generated-json", LR_FP,
                    note="same ELP32 core as T1-T4, so it shares the pocket"))
    # Q5A package table (datasheet p9): D1 max 5.00, E max 6.10, A max 1.10.
    # Using the maximums, not the 5x6x1 nominal the BOM calls it -- that is the
    # same nominal/maximum trap the magnetics height stack already avoids.
    # The land is 6.60 x 5.50 with its courtyard, and the pads reach 6.205 x 4.46
    # -- the printed F1/F2.  Clearance and overlap use the courtyard, because
    # that is the box KiCad will actually check.
    for ref, x in (("QH", 48.0), ("QL", 57.0)):
        out.append(Part(ref, "CSD19531Q5A", 6.60, 5.50, 1.10, x, 50.0,
                        "digitised-datasheet", "dcx:CSD19531Q5A",
                        note="Q5A dims D1/E/A max from datasheet p9; land and stencil "
                             "digitised from the sect. 7.2/7.3 figures "
                             "(design/v3/pcb/csd19531q5a_land.json); drain 5-8 on a "
                             "common base.  Not vendor CAD, not IPC-7351 checked"))
    out.append(Part("Cr", "0.62 uF", 18.0, 6.0, 6.0, 72.0, 52.0, "PROVISIONAL",
                    "dcx:Placeholder_18x6", note="no part selected; 18x6x6 film assumed"))
    out.append(Part("CT", "100:1", 20.0, 15.0, 8.0, 92.0, 52.0, "PROVISIONAL",
                    "dcx:Placeholder_20x15",
                    note="no part selected; 20x15x8 assumed, and 8 mm is a ceiling, "
                         "not a guess -- a taller CT does not fit the 10 mm stack"))
    out.append(Part("J_IN", "48 V input", 10.0, 10.0, 10.0, 112.0, 52.0, "PROVISIONAL",
                    "dcx:Placeholder_10x10",
                    note="2-pin 5.08 mm terminal implied by the BOM; body assumed"))
    out.append(Part("U2", "control area", 12.0, 12.0, 3.0, 132.0, 52.0, "PROVISIONAL",
                    "dcx:Placeholder_12x12",
                    note="UCC25600 + UCC27282 + passives grouped; no layout done"))
    # Row 2c -- the REG crowbar, one channel per controller plus one shared front
    # end.  Doc 34, package C: "紧接着连接选定的实际硬件关断电路".  This is the
    # circuit `pcb/sr_fault_validation` selected and measured, not a proposal:
    # FAULT_IN -> 1k -> FAULT_G, clamped at 5.1 V, pulled down by 10k (so a lost
    # fault source leaves it un-fired -- fail-open, carried forward honestly),
    # filtered by 1 nF, then one 100 ohm gate resistor into four AO3400A gates
    # that each pull REG through its own 4.7 ohm.  One gate resistor instead of
    # four: 4 x 630 pF = 2.52 nF gives tau 252 ns and a Miller crossing near
    # 0.94 us, still an order of magnitude inside the 12.1 us REG-UVLO window it
    # has to fit in, and sharing costs one node (5 pads) rather than four parts.
    # It is also the slower of the two options, which is the conservative
    # direction for Q41's turn-on SOA.
    for ref, value, fp, w, d, h in (
            ("R50", "1k", R0603_FP, R0603_W, R0603_D, R0603_H),
            ("D50", "5V1", SOD123_FP, SOD123_W, SOD123_D, SOD123_H),
            ("R51", "10k", R0603_FP, R0603_W, R0603_D, R0603_H),
            ("C50", "1nF/16V", C0603_FP, C0603_W, C0603_D, C0603_H),
            ("R52", "100R", R0603_FP, R0603_W, R0603_D, R0603_H)):
        out.append(Part(ref, value, w, d, h, CROWBAR_SHARED_X[ref], CROWBAR_ROW_Y,
                        "validation-board", fp,
                        note="crowbar front end; value and footprint are the ones "
                             "pcb/sr_fault_validation/BOM.csv carries, and the pin "
                             "roles are its net_map.  Board-only connectivity: the "
                             "deck has no crowbar and the native schematic has no "
                             "MOSFET or Zener symbol (see crowbar_nets)"))
    for i, x0 in enumerate(SR_X0, start=1):
        x_c = x0 + SR_PAIR_MM / 2
        out.append(Part(f"Q{50 + i}", "AO3400A", SOT23_W, SOT23_D, SOT23_H,
                        x_c + CROWBAR_Q_DX, CROWBAR_ROW_Y,
                        "validation-board", SOT23_FP,
                        note=f"REG{i} crowbar FET for group {i}: gate on RC_G, source "
                             f"on PGND, drain on REG_CROW{i}.  AO3400A and its MPN "
                             f"source are the validation board's (references/"
                             f"datasheets/ao3400a.txt); qualified is false there -- "
                             f"turn-on SOA, self-heating and R44 repetitive pulse "
                             f"are still open"))
        out.append(Part(f"R{52 + i}", "4.7R 0.5W", R1206_W, R1206_D, R1206_H,
                        x_c + CROWBAR_R_DX, CROWBAR_ROW_Y,
                        "validation-board", R1206_FP,
                        note=f"REG{i} -> REG_CROW{i} crowbar resistor. 122.7 uJ, "
                             f"25.2 W peak on the validation board; the 1206 pulse "
                             f"curve is not in the repository, so this is a "
                             f"screening ratio and not a qualification"))
    # Row 2b -- one SR controller per pair, centred on the pair it drives (doc
    # 34, package C: "紧接着连接选定的实际硬件关断电路").  Placing U3-U6 needs no
    # ECO: the golden netlist, the BOM row "U3-U6" and theme section 3 already
    # carry them; what was missing was a pad to land on.  With them placed, each
    # VD*/VG* becomes a two-pad net and REG1-REG4 appear as the pin the REG
    # crowbar will pull.
    for i, x0 in enumerate(SR_X0, start=1):
        out.append(Part(f"U{i + 2}", "UCC24624DR", SOIC8_W, SOIC8_D, SOIC8_H,
                        x0 + SR_PAIR_MM / 2, SR_CTRL_ROW_Y,
                        "kicad-library", SOIC8_FP,
                        note=f"dual SR controller for group {i}: pin 1/8 drive VG{i}_A/B "
                             f"through R{20 + 2 * (i - 1)}/R{21 + 2 * (i - 1)}, pin 4/6 "
                             f"sit on the drain Kelvin links, pin 3 (REG{i}) is the "
                             f"node a crowbar pulls, pin 7 is VCC12_S.  MPN from "
                             f"bom_draft.csv U3-U6 (ucc24624.pdf); land is the "
                             f"vendored KiCad SOIC-8, not a vendor drawing"))
    # Row 3 -- the eight SR FETs, two per transformer, directly under their own
    # secondary.  Each pair spans one transformer's width so the secondary loop
    # stays local.
    for i, x0 in enumerate(SR_X0, start=1):
        out.append(Part(f"SR{i}A", "BSC010N04LS6", 7.36, 5.64, 1.0, x0, SR_ROW_Y,
                        "digitised-datasheet", tds,
                        note="land pattern digitised from the BSC010N04LS6 datasheet "
                             "Fig. 2 (design/v3/pcb/bsc010n04ls6_land.json); drain 5-8 "
                             "on a common base.  Not vendor CAD, not IPC-7351 checked"))
        out.append(Part(f"SR{i}B", "BSC010N04LS6", 7.36, 5.64, 1.0, x0 + SR_PAIR_MM,
                        SR_ROW_Y, "digitised-datasheet", tds,
                        note=f"same land pattern as SR{i}A"))
    # Row 3b -- the ten gate resistors and eight drain Kelvin links (doc 34,
    # package C: "按 8 SR Kelvin 栅极逐脚引脚展开").  Without them every GA*,
    # GB*, GH and GL net ends at a FET gate pad and there is nothing on the
    # board to route to, which is why they were single-pad nets.
    #
    # Coordinates are derived from the FET land patterns, not typed: the pad a
    # tap must meet is the pad the board carries, so a change to either land
    # pattern moves the resistor with it.  ``parts()`` runs while this module is
    # still executing, so it reads the *JSON the lands are generated from* and
    # the vendored 0603 file -- it may not call ``_pad_positions``, whose
    # ``_footprint_text`` builds the whole library and imports the two land
    # builders back into this half-initialised module.  The two sources are
    # compared by ``test_every_gate_resistor_lands_directly_under_the_gate_it_serves``.
    sr_pads = _land_pads(tds)
    q5_pads = _land_pads("dcx:CSD19531Q5A")
    r_pad = _text_pad_positions(_stock_footprint(R0603_FP))  # "1" at -0.825, "2" at +0.825

    def under(pads: dict[str, tuple[float, float]], x_fet: float,
              fet_pad: str, res_pad: str) -> float:
        """Resistor centre whose ``res_pad`` sits at the same x as ``fet_pad``.

        ``pads`` is the FET's own pad table -- the two FET types both name a pad
        ``4`` and ``5`` at different offsets, so the table has to be passed in
        rather than looked up by name alone.
        """
        return x_fet + pads[fet_pad][0] - r_pad[res_pad][0]

    for i, x0 in enumerate(SR_X0, start=1):
        for side, x_fet, gate_no, kelvin_no in (
                ("A", x0, 20 + 2 * (i - 1), 28 + 2 * (i - 1)),
                ("B", x0 + SR_PAIR_MM, 21 + 2 * (i - 1), 29 + 2 * (i - 1))):
            gate = f"R{gate_no}"
            out.append(Part(gate, placeholder_value(gate), R0603_W, R0603_D, R0603_H,
                            under(sr_pads, x_fet, "4", "2"), SR_GATE_ROW_Y,
                            "kicad-library", R0603_FP,
                            note=f"SR{i}{side} gate resistor; pad 2 lands directly "
                                 f"under the FET gate pad so the tap is one straight "
                                 f"track. Value from placeholder_eco.json"))
            kelvin = f"R{kelvin_no}"
            out.append(Part(kelvin, placeholder_value(kelvin), R0603_W, R0603_D, R0603_H,
                            under(sr_pads, x_fet, "5", "1"), SR_GATE_ROW_Y,
                            "kicad-library", R0603_FP,
                            note=f"SR{i}{side} drain Kelvin link; pad 1 lands under "
                                 f"the drain base pad 5, so VD{i}_{side} senses at the "
                                 f"drain rather than at the copper. 0 ohm from "
                                 f"placeholder_eco.json"))
    # The primary pair's gate resistors, under their own FET for the same reason.
    for ref, x_fet in (("R4", 48.0), ("R5", 57.0)):
        out.append(Part(ref, placeholder_value(ref), R0603_W, R0603_D, R0603_H,
                        under(q5_pads, x_fet, "4", "2"), PRIMARY_GATE_ROW_Y,
                        "kicad-library", R0603_FP,
                        note="QH/QL gate resistor; pad 2 lands under the Q5A gate pad "
                             "(4). 2.2 ohm external, the deck's 3.2 ohm is the lumped "
                             "value -- different quantity, not a conflict"))
    # Row 4 -- the output bank, one row between the SRs and the busbar.  The
    # refs are Cout1..Cout15, *not* C100..: the schematic already spends
    # C101-C112 on the twelve IC decoupling capacitors, so reusing those names
    # here would attach a 470 uF bulk part to a 0603 position the moment anyone
    # cross-referenced the board against the BOM.
    for i in range(cout["n"]):
        out.append(Part(f"{BANK_PREFIX}{i + 1}", "470 uF 2.5 V", 7.3, 4.3,
                        cout["height_mm"], 14.0 + 8.2 * i, 98.0, "generated-json",
                        COUT_FP,
                        note="height from cout_bank.json; case size assumed; "
                             "the schematic models this whole bank as one lumped Cout"))
    # Row 5 -- the output busbar, last so the 100 A leaves at the board edge.
    # Centred on the SR row it collects from: `output_path_budget.py` measures
    # each group's sideways run to the nearest bar edge, so the bar's x is a
    # design parameter, not a leftover.  At x = 100 group 1 had to travel 41 mm
    # (3.67 squares, 1.19 mohm) while groups 3 and 4 sat underneath it.
    out.append(Part("J_OUT", "20x2 mm bar", bar["length_mm"], bar["width_mm"],
                    bar["thickness_mm"], _sr_row_centre(), 116.0, "generated-json",
                    "dcx:Busbar_20x2",
                    note="contact resistance UNVERIFIED; four-wire at first article"))
    return tuple(out)


# ``PARTS`` is built at the bottom of this module, after the footprint helpers:
# the resistor rows are placed from pad positions read back out of the FET land
# patterns, and that reader is defined further down.


# ---------------------------------------------------------------- geometry
def bbox(part: Part) -> tuple[float, float, float, float]:
    """(x0, y0, x1, y1) of the part's own outline.  Only 0 deg and 90 deg
    rotations occur in this table, so the extent swap is explicit rather than a
    general transform -- if a rotation appears that is not one of those two the
    result would be silently wrong, so it raises."""
    w, d = part.w_mm, part.d_mm
    turns = round(part.rot / 90.0) % 4
    if abs(part.rot - turns * 90.0) > 1e-9:
        raise ValueError(f"{part.ref}: rotation {part.rot} is not a multiple of 90")
    if turns % 2:
        w, d = d, w
    return (part.x - w / 2, part.y - d / 2, part.x + w / 2, part.y + d / 2)


def overlaps(prts: tuple[Part, ...] | list[Part]) -> list[tuple[str, str, float]]:
    """Every pair whose outlines share positive area.  Touching exactly is not
    an overlap -- two parts may legitimately butt together."""
    found = []
    for i, a in enumerate(prts):
        ax0, ay0, ax1, ay1 = bbox(a)
        for b in prts[i + 1:]:
            bx0, by0, bx1, by1 = bbox(b)
            dx = min(ax1, bx1) - max(ax0, bx0)
            dy = min(ay1, by1) - max(ay0, by0)
            if dx > 1e-9 and dy > 1e-9:
                found.append((a.ref, b.ref, dx * dy))
    return found


def min_gap_mm(prts: tuple[Part, ...] | list[Part] | None = None) -> tuple[float, str, str]:
    """Smallest edge-to-edge distance in either axis, and the pair that owns it.
    Reported because 'nothing overlaps' is satisfied by 1 um of clearance too.

    ``prts`` defaults to ``PARTS`` at call time, not at def time: the table is
    built after every helper it derives from exists (it reads pad positions back
    out of the footprint text), so it cannot be a default argument.
    """
    prts = PARTS if prts is None else prts
    best, who = float("inf"), ("", "")
    for i, a in enumerate(prts):
        ax0, ay0, ax1, ay1 = bbox(a)
        for b in prts[i + 1:]:
            bx0, by0, bx1, by1 = bbox(b)
            gx = max(bx0 - ax1, ax0 - bx1)
            gy = max(by0 - ay1, ay0 - by1)
            gap = max(gx, gy)
            if gap < best:
                best, who = gap, (a.ref, b.ref)
    return best, who[0], who[1]


def board_rect(prts: tuple[Part, ...] | list[Part] | None = None) -> tuple[float, float]:
    """Board size in mm, rounded up to 0.5 mm so the Edge.Cuts is a round number."""
    prts = PARTS if prts is None else prts
    x1 = max(bbox(p)[2] for p in prts)
    y1 = max(bbox(p)[3] for p in prts)
    return _ceil_half(x1 + EDGE_MARGIN_MM), _ceil_half(y1 + EDGE_MARGIN_MM)


def _ceil_half(v: float) -> float:
    return round(-(-v // 0.5) * 0.5, 3)


# ---------------------------------------------------------------- report
def _bsc_source() -> str:
    """The SR FET land pattern, built by the module that digitised it.

    Imported lazily because ``make_sr_fault_board_pcb`` imports *this* module
    for ``find_kicad_cli()``; a top-level import would close the cycle.  The
    footprint is generated from ``design/v3/pcb/bsc010n04ls6_land.json``, whose
    own ``checks`` must all pass or that builder exits -- so this board cannot
    silently inherit a land pattern the measurement has already rejected.
    """
    import make_sr_fault_board_pcb as srpcb
    return srpcb.bsc_source()


def _csd_source() -> str:
    """The QH/QL land pattern, from the module that digitised its datasheet.

    Same lazy-import reason as the SR FETs: ``csd19531q5a_land`` is a leaf, but
    keeping every land builder behind a function keeps the import graph a star
    rather than a web.  ``footprint_text`` refuses a JSON whose own ``checks``
    failed, and reads the committed file rather than the PDF -- so a machine
    without PyMuPDF still builds the board from the same numbers.
    """
    import csd19531q5a_land as csd
    with csd.DEFAULT_JSON.open(encoding="utf-8") as fh:
        return csd.footprint_text(json.load(fh))


def _footprint_text(lib_id: str) -> str:
    name = lib_id.split(":", 1)[1]
    libs = footprint_library()
    return libs.get(f"{name}.kicad_mod") or _stock_footprint(lib_id)


def _pad_blocks(lib_id: str) -> list[str]:
    """Every numbered pad block's name, in file order, duplicates kept.

    Distinct from ``_pad_positions``: the vendored TDSON-8 numbers its five
    drain pads all ``"5"``, so the *name* count is 5 while the *copper* count is
    9.  A report that counted names would understate how much copper a net
    actually lands on, and ``_inject_pad_nets`` -- which walks blocks -- would
    agree with the wrong number.
    """
    return [m.group(1) for m in
            re.finditer(r'\(pad "([^"]*)"', _footprint_text(lib_id)) if m.group(1)]


def _text_pad_positions(text: str) -> dict[str, tuple[float, float]]:
    """Pad name -> (x, y) in the footprint's own frame, first occurrence wins.

    Split out from ``_pad_positions`` so a caller that already holds the text --
    or a stock library file -- can parse it without building the whole library.
    """
    out: dict[str, tuple[float, float]] = {}
    for match in re.finditer(r'\(pad "([^"]*)"[^(]*\(at (-?[\d.]+) (-?[\d.]+)', text):
        name, px, py = match.group(1), float(match.group(2)), float(match.group(3))
        if name:
            out.setdefault(name, (px, py))
    return out


def _pad_positions(lib_id: str) -> dict[str, tuple[float, float]]:
    """Pad name -> (x, y) in the footprint's own frame, read back out of the
    footprint text.  Reading it back rather than restating the table means the
    distances below cannot drift from the pads the board actually carries."""
    return _text_pad_positions(_footprint_text(lib_id))


def _land_pads(lib_id: str) -> dict[str, tuple[float, float]]:
    """Copper pad name -> centre, from the digitised land-pattern JSON.

    The only caller is ``parts()``, which runs while this module is still
    executing: the two land builders import this module back for
    ``find_kicad_cli()``, so asking them for the footprint there hands back a
    half-built module (``AttributeError: no attribute 'bsc_source'``).  The JSON
    is what those builders generate the footprint *from*, so it is the same
    number one step upstream -- and ``_pad_positions`` on the generated text is
    compared against it by the placement test.

    Mask and paste openings live in the same list and can share a pad's number,
    so only the ``F.Cu`` entries are copper.  First occurrence wins, as in
    ``_text_pad_positions``: a pad name may cover several blocks (a drain base
    and its first finger are both ``5``).
    """
    out: dict[str, tuple[float, float]] = {}
    for pad in json.loads(LAND[lib_id].read_text(encoding="utf-8"))["pads"]:
        if "F.Cu" not in pad["layers"]:
            continue
        x0, y0, x1, y1 = pad["rect"]
        out.setdefault(pad["number"], ((x0 + x1) / 2, (y0 + y1) / 2))
    return out


def _mst_mm(points: list[tuple[float, float]]) -> float:
    """Straight-line minimum spanning tree length over pad centres.

    A lower bound on the copper, not a route: it ignores obstacle detours, layer
    changes and the fact that a 100 A path is a plane.  Useful for comparing the
    four identical groups against each other, which is why it is here.
    """
    if len(points) < 2:
        return 0.0
    left, total = list(points[1:]), 0.0
    tree = [points[0]]
    while left:
        best = None
        for a in tree:
            for b in left:
                dist = ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
                if best is None or dist < best[0]:
                    best = (dist, b)
        total += best[0]
        tree.append(best[1])
        left.remove(best[1])
    return total


def _padless_reason(part: "Part", pad: str) -> str:
    """Why a netlisted pin has no pad here -- the two causes are not the same.

    A repeated pad name is a gap in the vendored land pattern that a
    part-specific footprint would close; a padless outline is a placeholder
    that was never meant to carry pins.  Folding them into one list would let
    a real land-pattern defect look like a deliberate placeholder.
    """
    blocks = _pad_blocks(part.footprint)
    if not blocks:
        return ("the outline stands for a whole functional block and carries no "
                "pads at all, so no pin of it has a position yet")
    dup = sorted({n for n in blocks if blocks.count(n) > 1})
    if dup:
        return (f"the vendored footprint names pad {', '.join(dup)} more than once, "
                f"so the other pins of that group have no pad of their own")
    return "the footprint has no pad with this name"


def nets_report() -> dict:
    """What the connectivity actually is, and what it does not reach.

    Three lists matter as much as the net count: the parts the review table has
    no row for, the manifest pins with no physical pad, and the pads it mapped
    without naming a net.  Each is a place a reader could otherwise assume the
    ratsnest was complete.
    """
    nets = placed_nets()
    table = pad_nets()
    placed = {p.ref for p in PARTS}
    groups: dict[str, list[tuple[float, float]]] = {}
    landed = 0
    for part in PARTS:
        local = _pad_positions(part.footprint)
        for pad, net in part_nets(part).items():
            if pad not in local:
                continue
            x, y = local[pad]
            groups.setdefault(net, []).append((part.x + x, part.y + y))
            landed += 1
    rows = [
        {"net": net, "pads": len(points),
         "refs": sorted({m.split(".")[0] for m in nets[net]}),
         "straight_line_mst_mm": round(_mst_mm(points), 3)}
        for net, points in groups.items()
    ]
    rows.sort(key=lambda r: (-r["straight_line_mst_mm"], r["net"]))
    # Two different questions, so two different loops.  ``physical`` counts the
    # copper the nets actually land on, which includes the bank parts that have
    # no row of their own.  ``padless`` has to read the *table*, not
    # ``part_nets``: the latter filters unknown pads out, and those are exactly
    # the ones worth reporting.
    physical = sum(1 for part in PARTS
                   for name in _pad_blocks(part.footprint)
                   if name in part_nets(part))
    padless: dict[str, list[str]] = {}
    for part in PARTS:
        local = _pad_positions(part.footprint)
        for pad in table.get(part.ref, {}):
            if pad not in local:
                padless.setdefault(_padless_reason(part, pad), []).append(
                    f"{part.ref}.{pad}")
    return {
        "status": "NETTED_PLACEMENT_NOT_ROUTED",
        "source": "hardware/dcx_main/pin_footprint_review.csv",
        "net_count": len(nets),
        "pads_landed": landed,
        "physical_pads_netted": physical,
        "pads_landed_note": "pad names with a net; physical pads are higher where a "
                            "footprint splits one pin across several lands (the SR FET "
                            "drain: a common base plus four fingers, two of which share "
                            "the name 5).  KiCad merges same-numbered pads, and also "
                            "same-net lands whose copper overlaps, so the ratsnest is "
                            "shorter than pads_landed - net_count",
        "nets": rows,
        "single_pad_nets": [n["net"] for n in rows if n["pads"] == 1],
        "single_pad_nets_note": "a net with one pad here draws no ratsnest line and "
                                "owes no track.  Three kinds remain: the far end of a "
                                "resistor that is now placed (VG*_A/B, GH_DRV, GL_DRV "
                                "-- the driver side, which lives on the control board), "
                                "the CT secondary terminals CS1/CS2, whose rectifier "
                                "sits in the padless U2 outline, and FAULT_IN, the "
                                "crowbar's one off-board end -- on the built board it "
                                "comes from the D0 ten-channel protection board, not "
                                "from anything here.  Listed so none is read as routed",
        "lumped_from_one_netlist_element": {
            f"{BANK_PREFIX}1..{BANK_PREFIX}{_cout()['n']}":
                "the schematic models the whole bank as one lumped Cout; these "
                "fifteen borrow its two nets and the BOM must expand it into "
                "fifteen lines"},
        "not_in_the_netlist_at_all": ["U2"],
        "not_in_the_netlist_reason": "one outline stands for the whole control "
                                     "section; it has no pads and carries no net",
        "netlist_pins_without_a_physical_pad": padless,
        "netlist_pins_without_a_physical_pad_note": "grouped by why, because the two "
                                                   "causes are different defects: a "
                                                   "repeated pad name is a land-pattern "
                                                   "gap, a padless outline is a "
                                                   "placeholder",
        "pad_without_a_net": [{"ref": r["ref"], "pad": r["pad"], "note": r["note"]}
                              for r in review_rows()
                              if r["ref"] in placed and not r["net"].strip()],
        "not_placed_here_netlist_refs": sorted(set(table) - placed),
        "not_placed_here_reason": "power-stage placement only; control, drive and "
                                  "decoupling parts have no position on this board",
        "length_note": "straight-line spanning tree over pad centres, a lower "
                       "bound on copper and not a route",
    }


def report() -> dict:
    height = _load("magnetics/magnetics_design.json")["height"]
    flat = height["flat_no_pocket"]
    clamp = height["with_0.5mm_clamp"]
    magnetics = sorted(p.ref for p in PARTS if p.footprint in CORE_FOOTPRINTS)
    gap, ga, gb = min_gap_mm()
    w, d = board_rect()
    return {
        "status": "netted placement - connectivity drawn, nothing routed",
        "board": {"width_mm": w, "depth_mm": d, "thickness_mm": BOARD_T},
        "parts": [
            {"ref": p.ref, "value": p.value, "evidence": p.evidence,
             "w_mm": round(p.w_mm, 3), "d_mm": round(p.d_mm, 3),
             "h_mm_worst": round(p.h_mm_worst, 3),
             "x_mm": round(p.x, 3), "y_mm": round(p.y, 3), "rot_deg": p.rot,
             "note": p.note}
            for p in PARTS
        ],
        "height": {
            "limit_mm": HEIGHT_LIMIT_MM,
            "parts_max_height_mm": round(max(p.h_mm_worst for p in PARTS), 3),
            "flat_board_worst_case_mm": round(flat["worst_case_m"] * 1e3, 3),
            "flat_board_margin_mm": round(HEIGHT_LIMIT_MM - flat["worst_case_m"] * 1e3, 3),
            "clamp_case_worst_case_mm": round(clamp["worst_case_m"] * 1e3, 3),
            "clamp_case_margin_mm": round(HEIGHT_LIMIT_MM - clamp["worst_case_m"] * 1e3, 3),
            "pocket_required_refs": magnetics,
            "at_limit_refs": sorted(p.ref for p in PARTS
                                    if HEIGHT_LIMIT_MM - p.h_mm_worst < 0.5),
            "note": "flat 9.94 mm clears 10 mm by 60 um, which is smaller than glue, "
                    "label and core flatness; with a 0.5 mm clamp the same stack is "
                    "10.44 mm and over, so the cores need pockets",
        },
        "clearance": {"min_gap_mm": round(gap, 3), "between": [ga, gb]},
        "overlaps": [{"a": a, "b": b, "area_mm2": round(area, 3)}
                     for a, b, area in overlaps(PARTS)],
        "section": mechanical_section(),
        "pocket": pocket_requirements(),
        "provisional": sorted(p.ref for p in PARTS if p.evidence == "PROVISIONAL"),
        "land_pattern_provisional": sorted(
            # Class, not prose: ``datasheet`` means body dimensions only, so the
            # pads are placeholders.  ``digitised-datasheet`` is the class that
            # carries a measured land pattern and must not appear here -- the
            # old substring test caught the SR FETs the moment their note
            # started describing the new pad geometry.
            p.ref for p in PARTS if p.evidence == "datasheet"),
        "nets": nets_report(),
        # Named explicitly so a consumer never has to guess the reference
        # scheme.  ``cout_bank_path.py`` used to select the bank by ``C1xx``;
        # renaming the units to ``Cout1..`` then silently emptied its input and
        # it failed with "a bank row needs at least two units" rather than
        # saying which part it could not find.
        "cout_bank_refs": [p.ref for p in PARTS if p.ref.startswith(BANK_PREFIX)],
        "toolchain": toolchain(),
    }


def toolchain() -> dict:
    """What the board was built from, so a rebuild can be reproduced elsewhere.

    Deliberately **machine-independent**: it names the vendored footprint and
    its hash, and says where the KiCad version is recorded.  Putting the local
    ``kicad-cli --version`` here would make ``placement_report.json`` differ
    between a developer's machine and CI, which is the very failure Issue #11
    is about.  The version that actually ran the DRC lives in ``drc.json``
    (``kicad_version``), next to the run it belongs to.
    """
    generated = {f"dcx:{Path(name).stem}" for name in footprint_library()}
    files = sorted({p.footprint for p in PARTS if p.footprint not in generated})
    return {
        "generator": "tools/main_board_mechanical.py",
        "kicad_needed_for": "DRC and drawings only; the board file needs no KiCad",
        "kicad_version_source": "hardware/dcx_mech/drc.json:kicad_version",
        "stock_footprints": [
            {"lib_id": lib_id,
             "sha256": sha256(stock_footprint_path(lib_id).read_bytes()
                              .replace(b"\r\n", b"\n")).hexdigest()}
            for lib_id in files
        ],
    }


# ---------------------------------------------------------------- footprints
def _pad(number: str, x: float, y: float, dx: float, dy: float, shape: str = "rect") -> str:
    return (
        f'    (pad "{number}" thru_hole {shape}\n'
        f'      (at {x:g} {y:g})\n'
        f'      (size {dx:g} {dy:g})\n'
        f'      (drill {min(dx, dy) / 2:g})\n'
        f'      (layers "*.Cu" "*.Mask")\n'
        f'      (uuid "{uid("pad", number, str(x), str(y))}")\n'
        f'    )\n'
    )


def _outline_footprint(name: str, w: float, d: float, descr: str,
                       pads: list[tuple[str, float, float]],
                       pad_mm: float = 2.0) -> str:
    """A rectangular through-hole footprint: fab outline, courtyard at +0.25 mm,
    and one pad per terminal the caller names.

    The pad *names* matter now that the board carries nets: they are the same
    strings ``pin_footprint_review.csv`` uses, so a net lands on a pad by
    identity rather than by position in a list.  Deliberately minimal -- there
    is no copper land pattern here because the part is not selected."""
    cy, cx = d / 2 + 0.25, w / 2 + 0.25
    s = (f'(footprint "{name}"\n'
         f'\t(version 20260206)\n'
         f'\t(generator "main_board_mechanical")\n'
         f'\t(layer "F.Cu")\n'
         f'\t(descr "{descr}")\n'
         f'\t(attr through_hole)\n'
         f'\t(property "Reference" "REF**" (at 0 {-cy - 1.2:g} 0) (layer "F.SilkS")\n'
         f'\t\t(uuid "{uid("prop", name, "ref")}"))\n'
         f'\t(property "Value" "{name}" (at 0 {cy + 1:g} 0) (layer "F.Fab")\n'
         f'\t\t(uuid "{uid("prop", name, "val")}"))\n')
    for layer, half_w, half_d in (("F.Fab", w / 2, d / 2), ("F.CrtYd", cx, cy)):
        s += (f'\t(fp_rect (start {-half_w:g} {-half_d:g}) (end {half_w:g} {half_d:g})\n'
              f'\t\t(stroke (width {0.05 if layer == "F.CrtYd" else 0.1:g}) (type solid))\n'
              f'\t\t(fill none) (layer "{layer}") (uuid "{uid("rect", name, layer)}"))\n')
    for pad_name, px, py in pads:
        s += _pad(pad_name, px, py, pad_mm, pad_mm)
    return s + ")\n"


def footprint_library() -> dict[str, str]:
    """The project-local footprints, keyed by file name in ``dcx.pretty/``."""
    core = _core()
    bar = _bar()
    w = core["outer_length_m"] * 1e3
    d = core["core_depth_m"] * 1e3
    cout = _cout()
    files = {
        # Terminals at +/- 10 mm are a place to draw the winding exit, not a
        # measured bobbin.  Stated in the descr so the board file says it too.
        # Two footprints on one core outline: the transformer exposes the five
        # logical terminals the netlist names, the inductor only its two.  A
        # single five-pad footprint would leave three pads dangling on Lr.
        "ELP32_XFMR.kicad_mod": _outline_footprint(
            "ELP32_XFMR", w, d,
            "TDK ELP32 (B66287) 3:1:1 planar, 31.75x25.4x9.5 mm. "
            "Terminal positions PROVISIONAL: the winding exit is not drawn yet.",
            [("PRI_A", -10.0, -4.0), ("PRI_B", -10.0, 4.0), ("CTAP", 10.0, 0.0),
             ("SEC_A", 10.0, -5.0), ("SEC_B", 10.0, 5.0)]),
        "ELP32_LR.kicad_mod": _outline_footprint(
            "ELP32_LR", w, d,
            "TDK ELP32 (B66287), same core as T1-T4, two terminals. "
            "Pad names are the review table's pad column (1, 2), not the "
            "schematic's logical N1/N2, so a net lands by identity. "
            "Terminal positions PROVISIONAL.",
            [("1", -10.0, 0.0), ("2", 10.0, 0.0)]),
        "Busbar_20x2.kicad_mod": _outline_footprint(
            "Busbar_20x2", bar["length_mm"], bar["width_mm"],
            "Output copper bar 80x20x2 mm. Contact resistance UNVERIFIED.",
            [("1", -35.0, 0.0), ("2", 35.0, 0.0)]),
        "Placeholder_18x6.kicad_mod": _outline_footprint(
            "Placeholder_18x6", 18, 6, "PROVISIONAL - Cr film capacitor, no part selected",
            [("1", -7.0, 0.0), ("2", 7.0, 0.0)]),
        "Placeholder_20x15.kicad_mod": _outline_footprint(
            "Placeholder_20x15", 20, 15,
            "PROVISIONAL - over-current CT, no part selected. Four logical "
            "terminals per the netlist; the physical part is not chosen and no "
            "pinout is verified.",
            [("PRI_A", -8.0, -3.0), ("PRI_B", -8.0, 3.0),
             ("SEC_A", 8.0, -3.0), ("SEC_B", 8.0, 3.0)]),
        "Placeholder_10x10.kicad_mod": _outline_footprint(
            "Placeholder_10x10", 10, 10, "PROVISIONAL - 48 V input terminal, no part selected",
            [("1", -2.54, 0.0), ("2", 2.54, 0.0)]),
        "Placeholder_12x12.kicad_mod": _outline_footprint(
            "Placeholder_12x12", 12, 12,
            "PROVISIONAL - control area, no layout done. Deliberately padless: "
            "this outline stands for the whole control section, so any pad it "
            "carried would be a pin of a part that has no position yet.",
            []),
        "Placeholder_Cout.kicad_mod": _outline_footprint(
            "Placeholder_Cout", 7.3, 4.3,
            "Bulk output capacitor: max height 2.1 mm from YAGEO OEM; the "
            "7.3x4.3 outline fixed by OEM; PCB land pads are PROVISIONAL",
            [("1", -2.0, 0.0), ("2", 2.0, 0.0)]),
        # The one real land pattern on this board.  The vendored TDSON-8 named
        # all five drain lands "5", so the schematic's drain pins 6-8 had no
        # pad; the datasheet figure has four drain fingers on a common base.
        "BSC010N04LS6.kicad_mod": _bsc_source(),
        "CSD19531Q5A.kicad_mod": _csd_source(),
    }
    return files


FP_TABLE = '(fp_lib_table\n  (version 7)\n  (lib (name "dcx")(type "KiCad")' \
           '(uri "${KIPRJMOD}/dcx.pretty")(options "")(descr "generated placement footprints"))\n)\n'


def project_file() -> str:
    """Same trap as the schematic side: without a ``.kicad_pro`` next to the
    board, ``kicad-cli`` never loads ``fp-lib-table``, so every ``dcx:``
    footprint is reported as an unknown library -- and an unresolved footprint
    has no courtyard, so DRC silently stops checking it.

    ``tracks``/``net_settings`` are empty on purpose: this file has no nets.

    ``missing_courtyard`` is raised from its default *warning* to **error**.
    That is the check this study actually relies on -- a footprint without a
    courtyard is exempt from every clearance question -- and Issue #11 asks for
    the DRC result never to be quoted as "clean" while that check is ignored."""
    return json.dumps({
        "board": {"design_settings": {
            "rule_severities": {"missing_courtyard": "error"},
        }},
        "boards": [], "cvpcb": {}, "erc": {},
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": "power_stage_placement.kicad_pro", "version": 1},
        "net_settings": {}, "pcbnew": {"page_layout_descr_file": ""},
        "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
        "sheets": [], "text_variables": {},
    }, indent=2) + "\n"


# ---------------------------------------------------------------- board file
def _inject_pad_nets(text: str, nets: dict[str, str], ids: dict[str, int]) -> str:
    """Add ``(net N "NAME")`` to every pad whose name the review table knows.

    Found by paren depth rather than by regex: a pad block contains nested
    parentheses (``size``, ``layers``, ``drill``) and a regex that stopped at
    the first ``)`` would cut the block in half.  The net goes where KiCad puts
    it -- after ``layers``, before ``uuid``.
    """
    out: list[str] = []
    i = 0
    marker = '(pad "'
    while True:
        j = text.find(marker, i)
        if j < 0:
            out.append(text[i:])
            return "".join(out)
        out.append(text[i:j])
        k = text.find('"', j + len(marker))
        name = text[j + len(marker):k]
        depth, end = 0, j
        while end < len(text):
            if text[end] == "(":
                depth += 1
            elif text[end] == ")":
                depth -= 1
                if depth == 0:
                    break
            end += 1
        block = text[j:end + 1]
        net = nets.get(name)
        if net:
            pos = block.rfind("(uuid ")
            if pos > 0:
                line = block.rfind("\n", 0, pos) + 1
                indent = block[line:pos]
            else:
                # A vendored KiCad footprint may ship pads with no uuids at all
                # -- the 0603 here does -- and then "after layers, before uuid"
                # has no anchor.  Put the net on its own line just before the
                # pad's closing paren instead; KiCad reads ``(net ...)`` at any
                # position inside the pad.  Without this fallback the resistor
                # pads land on the board with no net, and the pads_landed /
                # physical_pads_netted counts describe copper that is not there.
                line = block.rfind("\n", 0, len(block) - 1) + 1
                inner = re.search(r"\n([ \t]+)\S", block)
                # One level *inside* the pad, not level with it: a net line at
                # the pad's own indent reads as a board-level declaration to
                # anything that counts ``^\t(net `` (it did, and the board
                # appeared to declare 84 nets).
                indent = inner.group(1) if inner else block[line:].split(")")[0] + "\t"
            block = (block[:line] + indent + f'(net {ids[net]} "{net}")\n'
                     + block[line:])
        out.append(block)
        i = end + 1


def _embed(mod_text: str, lib_id: str, ref: str, value: str, x: float, y: float,
           rot: float, nets: dict[str, str] | None = None,
           ids: dict[str, int] | None = None) -> str:
    """Turn a ``.kicad_mod`` body into a placed footprint instance.

    A ``.kicad_pcb`` carries the geometry inline, so the library file is copied
    in rather than referenced.  Five things change: the library id, the
    placement, the reference, every uuid (two instances sharing a uuid make
    KiCad pick one at random when the file is opened), and -- when the netlist
    has a row for this pad -- the net."""
    text = mod_text
    for pat in (r"\(version [^)]*\)\s*", r'\(generator "[^"]*"\)\s*',
                r'\(generator_version "[^"]*"\)\s*'):
        text = re.sub(pat, "", text, count=1)
    text = re.sub(r'\(footprint "[^"]+"', f'(footprint "{lib_id}"', text, count=1)
    text = text.replace(
        '(layer "F.Cu")',
        f'(layer "F.Cu")\n\t(uuid "{uid("fp", ref)}")\n\t(at {x:g} {y:g} {rot:g})',
        1)
    text = text.replace('(property "Reference" "REF**"', f'(property "Reference" "{ref}"', 1)
    text = re.sub(r'\(property "Value" "[^"]*"', f'(property "Value" "{value}"', text, count=1)
    text = re.sub(r'\(uuid "([^"]+)"\)', lambda m: f'(uuid "{uid(ref, m.group(1))}")', text)
    if nets:
        text = _inject_pad_nets(text, nets, ids or {})
    return "\t" + text.strip() + "\n"


def board_file(libs: dict[str, str]) -> str:
    w, d = board_rect()
    mods = {f"dcx:{Path(name).stem}": text for name, text in libs.items()}
    nets = placed_nets()
    ids = {net: i for i, net in enumerate(sorted(nets), start=1)}
    out = [
        "(kicad_pcb\n\t(version 20260206)\n\t(generator \"main_board_mechanical\")\n"
        "\t(generator_version \"10.0\")\n\t(general (thickness 1.6))\n"
        "\t(paper \"A3\")\n\t(title_block\n"
        "\t\t(title \"DCX 48V-2V 100A - A5 1:1 power-stage placement\")\n"
        "\t\t(comment 1 \"NETTED PLACEMENT - no routing; every ratsnest line is a missing track\")\n"
        "\t\t(comment 2 \"PROVISIONAL outlines: CT, Cr, J_IN, U2 area, Cout case size\")\n"
        "\t)\n"
        "\t(layers\n"
        '\t\t(0 "F.Cu" signal)\n\t\t(31 "B.Cu" signal)\n'
        # Paste and mask are declared, not only referenced by pads: kicad-cli
        # plots only the layers this table lists and drops the rest without a
        # message, so a board that omits them yields a package with no mask.
        '\t\t(34 "B.Paste" user)\n\t\t(35 "F.Paste" user)\n'
        '\t\t(36 "B.SilkS" user "B.Silkscreen")\n\t\t(37 "F.SilkS" user "F.Silkscreen")\n'
        '\t\t(38 "B.Mask" user)\n\t\t(39 "F.Mask" user)\n'
        '\t\t(44 "Edge.Cuts" user)\n\t\t(46 "B.CrtYd" user "B.Courtyard")\n'
        '\t\t(47 "F.CrtYd" user "F.Courtyard")\n'
        '\t\t(48 "B.Fab" user)\n\t\t(49 "F.Fab" user)\n\t)\n'
        "\t(setup (pad_to_mask_clearance 0))\n"
    ]
    for net in sorted(nets):
        out.append(f'\t(net {ids[net]} "{net}")\n')
    # Edge.Cuts as four straight segments -- a rectangle drawn with gr_rect is
    # legal but some viewers only close the outline from segments.
    for name, (x0, y0, x1, y1) in {
        "top": (0, 0, w, 0), "right": (w, 0, w, d),
        "bottom": (w, d, 0, d), "left": (0, d, 0, 0),
    }.items():
        out.append(f'\t(gr_line (start {x0:g} {y0:g}) (end {x1:g} {y1:g})'
                   f' (stroke (width 0.1) (type solid)) (layer "Edge.Cuts")'
                   f' (uuid "{uid("edge", name)}"))\n')
    for part in PARTS:
        lib_id = part.footprint
        text = mods.get(lib_id) or _stock_footprint(lib_id)
        out.append("\t" + _embed(text, lib_id, part.ref, part.value,
                                 part.x, part.y, part.rot,
                                 part_nets(part), ids).strip() + "\n")
    out.append(")\n")
    return "".join(out)


def stock_footprint_path(lib_id: str) -> Path:
    """Where the vendored copy of a stock footprint lives."""
    lib, name = lib_id.split(":", 1)
    return STOCK / f"{lib}.pretty" / f"{name}.kicad_mod"


# ---------------------------------------------------------------- A6 section
POCKET_MM = 0.5          # design choice, not yet cleared with a fabricator
CLAMP_MM = 0.5           # 压块, an assumption: the cores cannot float
GLUE_MM, GLUE_MAX_MM = 0.05, 0.08      # assumed: no adhesive data sheet here
LABEL_MM, LABEL_MAX_MM = 0.05, 0.06    # assumed: optional, a label may be skipped


def mechanical_section() -> dict:
    """The Z stack-up with an explicit datum and tolerance chain (Issue #12).

    Issue #12's first blocking question is what "10 mm" even measures.  The
    repo has three answers in it and they are not the same number, so this
    table states the datum first and then lists every contributor above and
    below it, with the class of evidence behind its thickness.

    Below the datum the pocket is *not* free: 0.5 mm out of a 1.6 mm board
    leaves 1.1 mm of FR-4 under the five cores for insulation and support;
    the SR return current requires a separate continuous copper/via/busbar path.

    Above the stack there is nothing in this repository at all -- no TIM, no
    cold plate, no fastener heads.  That is reported as UNKNOWN rather than
    omitted, because omitting it is how a 10 mm claim gets made without anyone
    deciding what the 10 mm covers.
    """
    data = _load("magnetics/magnetics_design.json")
    core, height = data["core"], data["height"]
    up = [
        {"item": "ELP32 磁芯对（B66287 半对 ×2）",
         "nominal_mm": round(core["height_nominal_m"] * 1e3, 3),
         "worst_mm": round(core["height_max_m"] * 1e3, 3), "evidence": "datasheet",
         "note": "9.5 标称 / 9.8 最大，已含研磨气隙"},
        {"item": "胶层", "nominal_mm": GLUE_MM, "worst_mm": GLUE_MAX_MM,
         "evidence": "ASSUMED", "note": "本仓库没有胶的规格书，最大值是假设"},
        {"item": "标签", "nominal_mm": LABEL_MM, "worst_mm": LABEL_MAX_MM,
         "evidence": "ASSUMED", "note": "可选；不做标签直接省掉 0.06 mm 的极端值"},
        {"item": "压块", "nominal_mm": CLAMP_MM, "worst_mm": CLAMP_MM,
         "evidence": "DESIGN", "note": "五只裸磁芯不能悬空；压块形式与厚度都还没定"},
    ]
    down = [
        {"item": "沉槽", "nominal_mm": -POCKET_MM, "worst_mm": -POCKET_MM,
         "evidence": "DESIGN", "note": "尚未与 PCB 厂确认 0.5 mm 沉槽工艺"},
        {"item": "沉槽下剩余介质", "nominal_mm": BOARD_T - POCKET_MM,
         "worst_mm": BOARD_T - POCKET_MM, "evidence": "DESIGN",
         "note": f"{BOARD_T} mm 板厚减沉槽；FR-4 仅提供结构与绝缘；SR 回流必须走连续铜层、过孔或铜排"},
    ]
    glue = next(x for x in up if x["item"] == "胶层")
    label = next(x for x in up if x["item"] == "标签")
    core_row = up[0]
    # Recompute from the rows and *check* against magnetics_design.json rather
    # than trusting one of the two: two independent sums that must agree is a
    # free consistency test, and a silent divergence here is exactly how the
    # document and the JSON drift apart.
    flat_rows = core_row["worst_mm"] + glue["worst_mm"] + label["worst_mm"]
    flat_json = height["flat_no_pocket"]["worst_case_m"] * 1e3
    if abs(flat_rows - flat_json) > 1e-6:
        raise SystemExit(
            f"height stack disagrees with magnetics_design.json: table {flat_rows} mm "
            f"vs JSON {flat_json} mm -- update GLUE_MAX_MM/LABEL_MAX_MM and rerun "
            f"python tools/magnetics_design.py")
    with_clamp = flat_rows + CLAMP_MM
    pocketed = with_clamp - POCKET_MM
    pocketed_plain = flat_rows - POCKET_MM
    return {
        "datum": "PCB 顶面 Z = 0；向上为正。所有尺寸都相对这个面，"
                 "不含 TIM、冷板与紧固件",
        "upward": up,
        "downward": down,
        "undefined_above_the_stack": [
            "TIM / 导热垫厚度与压缩量",
            "冷板或散热器离板面高度",
            "紧固件头部 / 螺纹嵌件凸出",
            "板弯与压块变形（装配态，不是零件公差）",
        ],
        "definitions": {
            "A_flat_no_pocket_no_clamp_mm": round(flat_rows, 3),
            "B_pocket_0p5_no_clamp_mm": round(pocketed_plain, 3),
            "C_pocket_0p5_with_clamp_mm": round(pocketed, 3),
            "D_with_tim_and_cold_plate_mm": None,
        },
        "definitions_note": "A/B/C 都是**模块相对 PCB 顶面**的数，可直接与 10 mm 比；"
                            "D 需要结构专业给出 TIM 与冷板数据后才有意义，现在必须留空",
        "finding": "0.5 mm 沉槽只是把 0.5 mm 压块买回来：C = A = 9.94 mm，余量仍是 +0.06 mm。"
                   "沉槽不是额外余量，是让压块方案回到原点。要真余量，只能减胶/去标签，"
                   "或把压块做进磁芯窗口而不是叠在上面",
        "gate": "未签核：没有 TIM/冷板/紧固件定义，也没有制造商对 0.5 mm 沉槽的确认，"
                "因此不得宣称 ≤10 mm 机电签核通过（Issue #12 关闭条件）",
        "clamp_case_margin_mm": round(HEIGHT_LIMIT_MM - with_clamp, 3),
        "pocket_case_margin_mm": round(HEIGHT_LIMIT_MM - pocketed, 3),
    }


def pocket_requirements() -> dict:
    """What 0.5 mm deep, five times, does to the board (Issue #12 item 2).

    A pocket is not a free vertical offset.  It is a routed cavity that removes
    20 % of the board's copper area, leaves 1.1 mm of dielectric under the
    heaviest parts on the assembly, and -- because it is on one side only --
    makes the stack asymmetric, which is what makes a board bow.

    The one thing that *can* be checked today is whether the cavities take
    copper away from the 100 A output plane.  They do not: the five cores sit
    at y <= 65 mm and the SR-to-busbar channel is y = 82..116 mm.  Recording a
    checked non-issue is worth as much as a finding, because the next person
    moving a transformer has no other way to know it was considered.
    """
    data = _load("magnetics/magnetics_design.json")
    core = data["core"]
    cores = [p for p in PARTS if p.footprint in CORE_FOOTPRINTS]
    w = core["outer_length_m"] * 1e3
    d = core["core_depth_m"] * 1e3
    per_core = w * d
    total = per_core * len(cores)
    bw, bd = board_rect()
    board_area = bw * bd
    channel = (SR_ROW_Y, next(p for p in PARTS if p.ref == "J_OUT").y)
    core_top = max(part.y + part.d_mm / 2 for part in cores)
    core_bottom = min(part.y - part.d_mm / 2 for part in cores)
    # What the output plane has to route *around*.  Until package C this list was
    # the bank and the busbar; the resistor rows now sit in it, and a pour that
    # is measured on this placement will show their keep-outs.  Recording the
    # occupants is the difference between "the channel is clear" (it no longer
    # is) and "the pockets do not reach it" (they still do not).
    occupants = sorted(p.ref for p in PARTS
                       if p.y + p.d_mm / 2 > channel[0] and p.y - p.d_mm / 2 < channel[1])
    return {
        "cores": len(cores),
        "pocket_per_core_mm2": round(per_core, 1),
        "pocket_total_mm2": round(total, 1),
        "board_area_mm2": round(board_area, 1),
        "fraction_of_board_pct": round(100.0 * total / board_area, 1),
        "depth_mm": POCKET_MM,
        "remaining_dielectric_mm": round(BOARD_T - POCKET_MM, 2),
        "depth_tolerance_mm": 0.1,          # typical routed-cavity tolerance
        "remaining_dielectric_range_mm": [round(BOARD_T - POCKET_MM - 0.1, 2),
                                          round(BOARD_T - POCKET_MM + 0.1, 2)],
        "core_footprint_y_mm": [round(core_bottom, 1), round(core_top, 1)],
        "output_channel_y_mm": [round(channel[0], 1), round(channel[1], 1)],
        "output_channel_occupants": occupants,
        "output_channel_occupants_note": "parts whose outline reaches into the "
                                         "SR-to-busbar channel; every one of them is a "
                                         "keep-out in the output pour, so the channel is "
                                         "not empty copper",
        "pocket_overlaps_output_plane": core_top > channel[0],
        "checked_non_issues": [
            "沉槽不占用 100 A 输出平面（磁芯 y ≤ "
            f"{core_top:.0f} mm，通道 y = {channel[0]:.0f}..{channel[1]:.0f} mm）",
        ],
        "undefined": [
            "叠层：沉槽只削顶层还是进到内层？内层铺铜是否也需要让开？",
            "磁芯与 PCB 铜的绝缘等级（N97 是 MnZn 铁氧体，不能直接压在裸铜上）",
            "绕组的引出方式与沉槽边缘的爬电距离",
            "压块的受力点与反作用：压磁芯的力最终落在 1.1 mm 的介质上",
            "板弯：单面开槽使叠层不对称，板弯直接进高度预算",
        ],
        "manufacturability": {
            "ask_the_fabricator": [
                "1.6 mm FR4 上 0.5 mm 深、31.75 × 25.4 mm 的腔体能否做，公差多少",
                "腔体底部的铜（如有）是否保留，最小介质层厚是多少",
                "单面五处腔体对板弯的典型值",
            ],
            "status": "未询问",
        },
        "gate": "沉槽深度与位置在制造商书面确认前不得冻结；"
                "本表只说明它要什么，不说明它做得到",
    }


def _stock_footprint(lib_id: str) -> str:
    path = stock_footprint_path(lib_id)
    if not path.exists():
        raise SystemExit(
            f"{lib_id} is neither generated by this tool nor vendored at {path}.\n"
            f"If the board really needs a new stock footprint, copy it out of a "
            f"KiCad install into {STOCK} and record the version, the sha256 and "
            f"the licence in {STOCK / 'PROVENANCE.md'} -- do not point the "
            f"generator at somebody's home directory.")
    return path.read_text(encoding="utf-8")


def find_kicad_cli() -> Path | None:
    """Locate ``kicad-cli`` without naming a user or a version.

    Order: ``KICAD_CLI`` env var, then PATH, then the per-user and machine-wide
    install roots that KiCad's own installers use on Windows, newest first.
    Returning ``None`` is a normal outcome -- the board file itself needs no
    KiCad, only the DRC and the drawings do.
    """
    env = os.environ.get("KICAD_CLI")
    if env and Path(env).exists():
        return Path(env)
    on_path = shutil.which("kicad-cli")
    if on_path:
        return Path(on_path)
    roots = [os.environ.get("LOCALAPPDATA"), os.environ.get("PROGRAMFILES"),
             os.environ.get("PROGRAMFILES(X86)")]
    candidates: list[Path] = []
    for root in filter(None, roots):
        for pattern in ("Programs/KiCad/*/bin/kicad-cli.exe", "KiCad/*/bin/kicad-cli.exe"):
            candidates += sorted(Path(root).glob(pattern), reverse=True)
    return candidates[0] if candidates else None


def find_kicad_share() -> Path | None:
    """The installed KiCad data directory, if there is one.

    Only used to *cross-check* the vendored footprints; generation never reads
    from it.
    """
    env = os.environ.get("KICAD_SHARE")
    if env and Path(env).exists():
        return Path(env)
    cli = find_kicad_cli()
    if cli is not None:
        share = cli.parent.parent / "share" / "kicad"
        if share.exists():
            return share
    return None


# ---------------------------------------------------------------- write
def write(out_dir: Path | None = None) -> dict:
    out_dir = Path(out_dir or OUT)
    libs = footprint_library()
    pretty = out_dir / "dcx.pretty"
    pretty.mkdir(parents=True, exist_ok=True)
    for name, text in libs.items():
        (pretty / name).write_text(text, encoding="utf-8", newline="\n")
    (out_dir / "fp-lib-table").write_text(FP_TABLE, encoding="utf-8", newline="\n")
    (out_dir / "power_stage_placement.kicad_pro").write_text(
        project_file(), encoding="utf-8", newline="\n")
    (out_dir / "power_stage_placement.kicad_pcb").write_text(
        board_file(libs), encoding="utf-8", newline="\n")
    data = report()
    (out_dir / "placement_report.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return data


def draw(out_dir: Path | None = None) -> list[Path]:
    """The two reviewer-facing pictures.

    The SVG is exported at ``--scale 1`` with the page cropped to the board, so
    its ``width`` attribute is the real board size in mm and it can be printed
    at 1:1 to lay parts on paper.  The 3D view shows what the stack actually
    looks like -- note that the generated footprints carry no 3D model, so the
    magnetics appear as pads only; that is a limit of this drawing, not of the
    parts.
    """
    out_dir = Path(out_dir or OUT)
    out_dir.mkdir(parents=True, exist_ok=True)
    board = out_dir / "power_stage_placement.kicad_pcb"
    cli = find_kicad_cli()
    if cli is None:
        return []
    svg = out_dir / "placement_1to1.svg"
    png = out_dir / "placement_top.png"
    subprocess.run([str(cli), "pcb", "export", "svg", "--mode-single", "--scale", "1",
                    "--page-size-mode", "2", "-l", "F.Fab,Edge.Cuts,F.CrtYd,F.SilkS",
                    "-o", str(svg), str(board)], check=False, capture_output=True)
    subprocess.run([str(cli), "pcb", "render", "--side", "top", "-w", "1400",
                    "-h", "1200", "--background", "opaque", "-o", str(png), str(board)],
                   check=False, capture_output=True)
    return [svg, png]


def _drc(path: Path | None = None) -> dict:
    path = path or OUT / "drc.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def violations(path: Path | None = None) -> list[dict]:
    return _drc(path).get("violations", [])


def unconnected(path: Path | None = None) -> list[dict]:
    """Ratsnest lines still missing a track.

    ``kicad-cli`` puts these in a **second** top-level array, not in
    ``violations``, so reading only the first one reports "nothing
    unconnected" on a board where nothing is routed at all.  This board is
    unrouted on purpose, so the count is reported as debt -- it is the number
    of connections the layout still owes, not a defect of the placement.
    """
    return _drc(path).get("unconnected_items", [])


def check() -> None:
    data = write()
    board = OUT / "power_stage_placement.kicad_pcb"
    print(f"board {data['board']['width_mm']} x {data['board']['depth_mm']} mm, "
          f"{len(data['parts'])} parts, min gap {data['clearance']['min_gap_mm']} mm "
          f"({data['clearance']['between'][0]}/{data['clearance']['between'][1]})")
    print(f"height: flat {data['height']['flat_board_worst_case_mm']} mm "
          f"(margin {data['height']['flat_board_margin_mm']:+} mm), "
          f"clamp {data['height']['clamp_case_worst_case_mm']} mm "
          f"(margin {data['height']['clamp_case_margin_mm']:+} mm)")
    print(f"provisional outlines: {', '.join(data['provisional'])}")
    cli = find_kicad_cli()
    if cli is None:
        print("kicad-cli not found (KICAD_CLI, PATH, or a standard install) -- "
              "DRC and drawings NOT reproduced; the committed board was still regenerated")
        return
    print("kicad-cli:", subprocess.run([str(cli), "--version"], capture_output=True,
                                       text=True, check=False).stdout.strip())
    draw()
    subprocess.run([str(cli), "pcb", "drc", "--format", "json", "--severity-all",
                    "-o", str(OUT / "drc.json"), str(board)], check=False, capture_output=True)
    vs = violations()
    errors = [v for v in vs if v["severity"] == "error"]
    unknown = [v for v in vs if v["type"] == "lib_footprint_issues"]
    # ``missing_courtyard`` is a warning by default, so a board whose footprints
    # carry no courtyard passes a severities-as-shipped run while checking
    # nothing about placement.  ``project_file()`` raises it to error; count it
    # here so a silent regression shows up in the printed line too.
    bare = [v for v in vs if v["type"] == "missing_courtyard"]
    nets = data["nets"]
    ratsnest = unconnected()
    print(f"DRC: {len(vs)} violations, {len(errors)} errors, {len(unknown)} unknown-footprint, "
          f"{len(bare)} footprints without a courtyard")
    print(f"nets: {nets['net_count']} nets on {nets['pads_landed']} netlist pads; "
          f"ratsnest: {len(ratsnest)} unconnected pairs still owing a track")
    # An empty ratsnest on a board that carries nets would mean the injections
    # did not reach the pads -- the exact inversion the SR board hit when it
    # read ``violations`` and found "0 unconnected" on an unrouted layout.
    if nets["net_count"] and not ratsnest:
        raise SystemExit("the board declares nets but kicad-cli reports nothing unconnected "
                         "-- either every net was routed, or the (net ...) children never "
                         "reached the pads")
    for v in (errors + unknown + bare)[:5]:
        print(f"  {v['severity']} {v['type']}: {v['description']}")
    if errors or unknown or bare:
        raise SystemExit("DRC is not clean -- a placement study may leave pads unconnected, "
                         "but a courtyard collision, a footprint without a courtyard, or an "
                         "unresolved library is a real defect")


PARTS = parts()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="regenerate and run kicad-cli DRC")
    args = ap.parse_args()
    if args.check:
        check()
    else:
        data = write()
        print(f"wrote {OUT} ({len(data['parts'])} parts, "
              f"{data['board']['width_mm']} x {data['board']['depth_mm']} mm)")


if __name__ == "__main__":
    main()
