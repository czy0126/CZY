"""Screen a real 100 A source-to-load interface on the live G1 native board.

D-06 already proved that the drawn 4 x VOUT + 8 x PGND 1 mm necks cannot reach
the 150 uohm both-rail placeholder budget at any copper thickness.  This tool
does not repeat that: it imports ``g1_current_neck_screen`` for the board-only
floor and asks the next question with geometry taken from the saved/reopened
readback -- can a bottom-side two-pole bar pair carry the same lands to a load
interface inside the budget?

Three things make the answer less optimistic than a naive square count:

* **Transverse path.**  The CTAP and SR lands sit on each bar's centreline
  (source row y = bar centre), but the terminal draws from the bar's inner
  edge.  Every amp must also cross half the bar in y; that path is at least
  0.5 square per rail (a full square of the bar's sheet resistance for the
  pair) and it is *not* part of the along-x collector term.  The reported
  ``bar_uohm`` includes it as a screening allowance; a 2-D/FE solve is still
  required to bound it.
* **Leg width is the binding choice.**  The collector loss is exactly flat for
  a whole interval of feeds (between the two central taps, and out to the
  adjacent taps), so the feed position is free.  The centre feed makes a
  18.599 mm pole pitch and 16.599 mm lugs; feeding the far ends of the flat
  interval gives a 51.600 mm pitch and the full 39 mm bar width, at the *same*
  collector loss.  Narrower pitches are reachable too -- down to the 2 mm
  inter-pole gap -- and are worse.  So the lug width, not the feed loss, is
  the design variable; the centre feed is one low-loss choice, not a bound.
* **Thickness.**  At the declared 50 uohm joint scenario, 4 mm fails even with
  full-width lugs once the transverse path is charged; 5 mm passes only with
  lugs >= 21.3 mm; 6 mm passes even at the centre feed.  At the 20 uohm joint
  scenario 4 mm passes, so every "4 mm fails" statement carries that qualifier.

The J_OUT termination is modelled only as a lower bound: its straight VOUT leg
is the shortest possible and still crosses the PGND bar, so it is not
realizable as drawn.  Not a finite-element solve, not a thermal rating, not a
fab approval.

python tools/g1_100a_output_interface.py --write
python tools/g1_100a_output_interface.py --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from text_identity import sha256_file
from g1_current_neck_screen import analyze as neck_analyze

ROOT = Path(__file__).resolve().parents[1]
G1 = ROOT / "hardware/dcx_main/g1"
BOARD = G1 / "dcx_main_board_g1_signal_stubs.eprj2"
PARENT = G1 / "dcx_main_board_g1_lr_repack.eprj2"
REVIEW = G1 / "lr_signal_review_report.json"
READBACK = G1 / "lr_signal_review_readback.json"
NATIVE_REPORT = G1 / "g1_native_pcb_report.json"
JOINT_CASES = ROOT / "hardware/dcx_main/output_joint_reduction_cases.json"
REPORT = G1 / "g1_100a_output_interface.json"

MIL_MM = 0.0254
RHO20_OHM_M = 1.724e-8
ALPHA_PER_C = 0.00393
TEMP_C = 100.0
CURRENT_A = 100.0
BUDGET_UOHM = 150.0
EDGE_MARGIN_MM = 0.3
INTER_POLE_GAP_MM = 2.0
REFERENCE_BAR_WIDTH_MM = 39.0
REFERENCE_BAR_THICKNESS_MM = 5.0
CONFIG_THICKNESS_MM = (4.0, 5.0, 6.0)
BAR_SCENARIOS = ((30.0, 2.0), (30.0, 3.0), (30.0, 4.0), (30.0, 5.0), (30.0, 6.0),
                 (39.0, 2.0), (39.0, 3.0), (39.0, 4.0), (39.0, 5.0), (39.0, 6.0))
LEG_WIDTH_SENSITIVITY_MM = (39.0, 35.0, 30.0, 25.0, 22.0, 20.0, 12.0, 10.0, 8.0)
TRANSVERSE_SQUARES_PER_RAIL = 0.5
NEEDED_LANDS = {"vout": 4, "pgnd": 8, "jout": 2}


def _rho(temp_c: float = TEMP_C) -> float:
    if not -30.0 <= temp_c <= 200.0:
        raise ValueError("invalid copper temperature")
    return RHO20_OHM_M * (1.0 + ALPHA_PER_C * (temp_c - 20.0))


def sheet_uohm_per_square(thickness_mm: float, temp_c: float = TEMP_C) -> float:
    """One square of a solid copper bar of ``thickness_mm`` at ``temp_c``."""
    if thickness_mm <= 0.0:
        raise ValueError("bar thickness must be positive")
    return _rho(temp_c) / (thickness_mm * 1e-3) * 1e6


def bar_uohm(length_mm: float, width_mm: float, thickness_mm: float,
             temp_c: float = TEMP_C) -> float:
    """Resistance of a rectangular bar; ``width`` is the cross-section width."""
    if length_mm < 0.0 or width_mm <= 0.0:
        raise ValueError("bar length must be non-negative and width positive")
    return sheet_uohm_per_square(thickness_mm, temp_c) * length_mm / width_mm


def post_uohm(diameter_mm: float, length_mm: float,
              temp_c: float = TEMP_C) -> float:
    """Solid round post; a lower bound for a pad-to-bar transition."""
    if diameter_mm <= 0.0 or length_mm <= 0.0:
        raise ValueError("post diameter and length must be positive")
    area_m2 = math.pi * (diameter_mm * 1e-3 / 2.0) ** 2
    return _rho(temp_c) * length_mm * 1e-3 / area_m2 * 1e6


def weighted_length_mm(taps_mm: list[float], feed_mm: float) -> float:
    """Equivalent 1 A path length for equal-current taps feeding one point.

    For a collector with equal tap currents, the loss of segment ``i`` scales
    with the square of the fraction of total current it carries.  Summing
    ``(I_i / I_total)**2 * length_i`` gives the series length that produces the
    same loss at the full current.  A feed outside the tap span is rejected:
    this model only describes a collector, not a stub.
    """
    if len(taps_mm) < 2:
        raise ValueError("need at least two taps")
    taps = sorted(float(x) for x in taps_mm)
    if not taps[0] <= feed_mm <= taps[-1]:
        raise ValueError("feed must lie inside the tap span")
    nodes = sorted(set(taps + [float(feed_mm)]))
    n = len(taps)
    total = 0.0
    for a, b in zip(nodes, nodes[1:]):
        if b <= feed_mm:
            fraction = sum(1 for t in taps if t <= a) / n
        elif a >= feed_mm:
            fraction = sum(1 for t in taps if t >= b) / n
        else:
            raise ValueError("feed must be one of the collector nodes")
        total += fraction ** 2 * (b - a)
    return total


def _feed_grid(taps_mm: list[float], step: float = 0.1) -> list[float]:
    """Tap-clamped feed grid; ``round(lo + n*step)`` can overshoot ``hi``."""
    lo, hi = min(taps_mm), max(taps_mm)
    count = int(math.floor((hi - lo) / step + 1e-9))
    return sorted({min(hi, round(lo + i * step, 9)) for i in range(count + 1)} | {lo, hi})


def best_feed(taps_mm: list[float], step: float = 0.1) -> tuple[float, float]:
    """Lowest-loss feed; among tied feeds choose the one nearest the row centre."""
    lo, hi = min(taps_mm), max(taps_mm)
    centre = (lo + hi) / 2.0
    grid = _feed_grid(taps_mm, step)
    losses = {x: weighted_length_mm(taps_mm, x) for x in grid}
    best = min(losses.values())
    tied = [x for x in grid if losses[x] <= best + 1e-9]
    x = min(tied, key=lambda value: abs(value - centre))
    return x, losses[x]


def feed_plateau(taps_mm: list[float], step: float = 0.1) -> tuple[float, float, float]:
    """The interval of feeds with the minimum collector loss.

    The collector loss is piecewise linear in the feed and flat between the two
    central taps, so every point of this interval is an equally valid "lowest
    loss" feed.  The pole pitch -- hence the lug width -- is a choice inside it.
    The taps themselves are candidates: a 0.1 mm grid alone stops 0.1 mm short
    of the true endpoints and understates the widest pitch.
    """
    points = sorted(set(_feed_grid(taps_mm, step)) | {float(t) for t in taps_mm})
    losses = {x: weighted_length_mm(taps_mm, x) for x in points}
    best = min(losses.values())
    tied = sorted(x for x in points if losses[x] <= best + 1e-9)
    return tied[0], tied[-1], best


def _value_sha256(value: dict) -> str:
    blob = json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def load() -> tuple[dict, dict]:
    """Read the live readback and bind it to the accepted candidate receipt.

    The receipt's own verdict fields are part of the binding: a failed review,
    or a review that did not confirm the CAD stayed unchanged, must not feed a
    "pass" screen.  The value hash below binds the value passed to ``build`` to
    the readback file read in this call; it is not a capture-time attestation,
    and a receipt re-sign would refresh the file hash (see ``not_qualified``).
    """
    report = json.loads(REVIEW.read_text(encoding="utf-8"))
    if report.get("status") != "NATIVE_SIGNAL_INCREMENT_ACCEPTED_NOT_FOR_FAB":
        raise ValueError("review receipt is not an accepted signal increment")
    if report.get("cad_unchanged") is not True:
        raise ValueError("review receipt did not confirm an unchanged CAD")
    if (report.get("geometry") or {}).get("status") != (
            "REOPENED_NATIVE_SIGNAL_STUBS_PENDING_ACTUAL_DRC"):
        raise ValueError("review receipt lacks the reopened geometry status")
    if sha256_file(BOARD) != report["cad_sha256_after"]:
        raise ValueError("candidate_sha256 differs from the actual native CAD")
    if sha256_file(READBACK) != report["readback_sha256"]:
        raise ValueError("readback_sha256 differs from the native reopen receipt")
    raw = json.loads(READBACK.read_text(encoding="utf-8"))
    if raw.get("ok") is not True or not isinstance(raw.get("value"), dict):
        raise ValueError("no successful native reopen readback")
    # D-02 names exactly one parent; hash that file, do not trust the receipt copy.
    if Path(report["geometry"]["source_cad"]).as_posix() != PARENT.relative_to(ROOT).as_posix():
        raise ValueError("the review receipt names a different parent board than D-02")
    parent_actual = sha256_file(PARENT)
    if parent_actual != report["parent_cad_sha256"]:
        raise ValueError("parent_cad_sha256 does not match the D-02 parent board file")
    native = json.loads(NATIVE_REPORT.read_text(encoding="utf-8"))
    outline_path = ROOT / native["cad"]["path"]
    if not outline_path.is_file():
        raise ValueError("the board-outline report names a missing base board")
    outline_bytes = outline_path.read_bytes()
    outline_md5 = hashlib.md5(outline_bytes).hexdigest()
    if outline_md5 != native["cad"]["md5"]:
        raise ValueError("the base board no longer matches the outline report")
    board_mm = native["board"]["outline_mm"]
    identity = {
        "candidate_sha256": sha256_file(BOARD),
        "report_candidate_sha256": report["cad_sha256_after"],
        "readback_sha256": sha256_file(READBACK),
        "report_readback_sha256": report["readback_sha256"],
        "readback_value_sha256": _value_sha256(raw["value"]),
        "parent_cad_sha256": parent_actual,
        "report_parent_sha256": report["parent_cad_sha256"],
        "native_drc_passed": report["native_drc_passed"],
        "fabrication_approved": report["fabrication_approved"],
        "board_mm": [float(board_mm[0]), float(board_mm[1])],
        "outline": {
            "report": NATIVE_REPORT.relative_to(ROOT).as_posix(),
            "board_path": native["cad"]["path"],
            "md5": outline_md5,
            "md5_verified": True,
            "sha256": hashlib.sha256(outline_bytes).hexdigest(),
            "report_sha256": sha256_file(NATIVE_REPORT),
        },
    }
    return raw["value"], identity


def _pad_mm(pad: dict) -> tuple[float, float]:
    return pad["X"] * MIL_MM, -pad["Y"] * MIL_MM


def _pad_half_extents(pad: dict) -> tuple[float, float]:
    """Axis-aligned half extents of a rotated pad, in mm.

    The readback carries ``Rotation`` and the SR source tab is a 23.6 x 129.9
    mil RECT at 90 degrees; ignoring the rotation swaps the extents and makes
    the bar rectangle 2.7 mm too short.  A circle is rotation-invariant.
    """
    shape = pad.get("Pad") or []
    if len(shape) < 3 or shape[0] not in ("ELLIPSE", "OVAL", "RECT"):
        return 0.0, 0.0
    width = abs(shape[1]) * MIL_MM
    height = abs(shape[2]) * MIL_MM
    extra = float(shape[3]) if len(shape) > 3 else 0.0
    angle = math.radians(float(pad.get("Rotation") or 0.0) + extra)
    cos, sin = abs(math.cos(angle)), abs(math.sin(angle))
    return (width * cos + height * sin) / 2.0, (width * sin + height * cos) / 2.0


def find_lands(value: dict) -> dict:
    """The four CTAP, eight SR source and two J_OUT lands, from the readback.

    The SR source row is not "the row with the most pads": each SR footprint
    also has 24 small drain/gate pads 0.35 mm below the 8 tall source tabs.
    The tab is identified by its own geometry -- the tallest RECT in the SR
    PGND group -- so a footprint change cannot silently re-pick the wrong row.
    """
    pads = value.get("pads") or []
    vout = [p for p in pads if p.get("Net") == "VOUT" and p.get("PadNumber") == "CTAP"]
    sr_pgnd = [p for p in pads if p.get("Net") == "PGND"
               and str(p.get("ref") or "").startswith("SR")]
    if not sr_pgnd:
        raise ValueError("no SR PGND source lands in the readback")
    groups: dict[tuple, list] = {}
    for pad in sr_pgnd:
        shape = pad.get("Pad") or []
        key = (shape[0] if shape else "",
               round(shape[1], 3) if len(shape) > 1 else 0.0,
               round(shape[2], 3) if len(shape) > 2 else 0.0)
        groups.setdefault(key, []).append(pad)
    tallest = max(groups.items(), key=lambda item: item[0][2])
    pgnd = tallest[1]
    jout = [p for p in pads if p.get("ref") == "J_OUT"]
    out = {
        "vout": [{"x_mm": round(_pad_mm(p)[0], 4), "y_mm": round(_pad_mm(p)[1], 4),
                  "half_x_mm": round(_pad_half_extents(p)[0], 4),
                  "half_y_mm": round(_pad_half_extents(p)[1], 4),
                  "rotation_deg": p.get("Rotation"),
                  "provisional": p.get("ref") is None} for p in sorted(vout, key=lambda p: p["X"])],
        "pgnd": [{"x_mm": round(_pad_mm(p)[0], 4), "y_mm": round(_pad_mm(p)[1], 4),
                  "half_x_mm": round(_pad_half_extents(p)[0], 4),
                  "half_y_mm": round(_pad_half_extents(p)[1], 4),
                  "rotation_deg": p.get("Rotation"),
                  "ref": p.get("ref"), "pad": p.get("PadNumber")}
                 for p in sorted(pgnd, key=lambda p: p["X"])],
        "jout": [{"x_mm": round(_pad_mm(p)[0], 4), "y_mm": round(_pad_mm(p)[1], 4),
                  "net": p.get("Net"), "pad": p.get("PadNumber")} for p in jout],
    }
    for key, count in NEEDED_LANDS.items():
        if len(out[key]) != count:
            raise ValueError(f"expected {count} {key} lands, found {len(out[key])}")
    return out


def joint_basis() -> dict:
    """The 150 uohm / 30 uohm / 20-50 uohm basis, read from its one home.

    Every case in that file is ``UNVERIFIED_INTERFACE_TOPOLOGY_REDESIGN_NOT_FOR_FAB``;
    the 6.798 uohm external pair is the most optimistic of the same-joint cases,
    so it must be reported as unverified, never as "existing".
    """
    data = json.loads(JOINT_CASES.read_text(encoding="utf-8"))
    if data["design_basis_uohm_both_rails"] != BUDGET_UOHM:
        raise ValueError("joint case budget differs from 150 uohm")
    if data["reserved_pcb_uohm_unverified"] != 30:
        raise ValueError("joint case PCB reserve differs from 30 uohm")
    if list(data["per_joint_uohm_scenarios_unverified"]) != [20, 50]:
        raise ValueError("joint case scenarios differ from 20/50 uohm")
    cases = {c["id"]: c for c in data["candidates"]}
    case = cases["reduced_2_contacts_50x2x15"]
    alternatives = [{"id": c["id"], "bar_pair_uohm": float(c["bar_pair_uohm_at_100c"])}
                    for c in data["candidates"] if c["id"].startswith("reduced_2_contacts")]
    deduction = data["feasibility_deduction"]
    return {
        "both_rails_budget_uohm": BUDGET_UOHM,
        "transition_allowance_uohm": float(data["reserved_pcb_uohm_unverified"]),
        "transition_allowance_is_unverified": True,
        "joint_scenarios_uohm": [float(x) for x in data["per_joint_uohm_scenarios_unverified"]],
        "joint_scenarios_are_unverified": True,
        "joints_per_pole": 1,
        "requires_one_verified_separable_joint_per_pole": bool(
            deduction["two_contacts_require_one_verified_separable_joint_per_pole"]),
        "four_joint_total_uohm": float(deduction["four_contacts_only_joints_uohm_at_50"]),
        "external_link_uohm": float(case["bar_pair_uohm_at_100c"]),
        "external_link_case": case["id"],
        "external_link_is_unverified": True,
        "external_link_cases_are_math_only": True,
        "external_link_alternatives": alternatives,
        "external_link_source": "hardware/dcx_main/output_joint_reduction_cases.json",
        "source_status": data["status"],
        "source_hardware_qualified": bool(data["hardware_qualified"]),
        "design_basis_is_internal_not_regulatory_or_measured": bool(
            data["design_basis_is_internal_not_regulatory_or_measured"]),
        "temperature_c_assumed": float(data["temperature_c_assumed"]),
        "current_a_assumed": float(data["current_a_assumed"]),
    }


def _row(collector_v_mm: float, collector_p_mm: float, leg_v_mm: float,
         leg_p_mm: float, leg_width_mm: float, width_mm: float,
         thickness_mm: float, basis: dict) -> dict:
    """One bar configuration: along-x collectors + legs + transverse allowance."""
    fixed = basis["transition_allowance_uohm"] + basis["external_link_uohm"]
    sheet = sheet_uohm_per_square(thickness_mm)
    collector = sheet * (collector_v_mm + collector_p_mm) / width_mm
    leg = sheet * (leg_v_mm + leg_p_mm) / leg_width_mm
    transverse = sheet * 2.0 * TRANSVERSE_SQUARES_PER_RAIL
    one_dimensional = collector + leg
    r_bar = one_dimensional + transverse
    cases = []
    for joint in basis["joint_scenarios_uohm"]:
        total = r_bar + fixed + 2.0 * joint
        cases.append({
            "separable_joint_uohm_each": joint,
            "total_uohm": round(total, 3),
            "margin_uohm": round(BUDGET_UOHM - total, 3),
            "meets_150_uohm": total <= BUDGET_UOHM,
        })
    return {
        "bar_width_mm": width_mm,
        "bar_thickness_mm": thickness_mm,
        "leg_length_mm": {"vout": round(leg_v_mm, 4), "pgnd": round(leg_p_mm, 4)},
        "one_dimensional_uohm": round(one_dimensional, 3),
        "transverse_allowance_uohm": round(transverse, 3),
        "bar_uohm": round(r_bar, 3),
        "max_separable_joint_uohm_each": round(
            (BUDGET_UOHM - r_bar - fixed) / 2.0, 3),
        "cases": cases,
    }


def _central_rows(collector_v_mm: float, collector_p_mm: float, y_v: float,
                  y_p: float, pole_pitch_mm: float, basis: dict) -> list[dict]:
    """Central termination; the leg length follows each scenario's bar width."""
    rows = []
    for width, thickness in BAR_SCENARIOS:
        leg = (y_p - y_v - width) / 2.0
        lug = min(pole_pitch_mm - INTER_POLE_GAP_MM, width)
        rows.append(_row(collector_v_mm, collector_p_mm, leg, leg, lug,
                         width, thickness, basis))
    return rows


def _config_case(row: dict, joint: float) -> dict:
    case = next(c for c in row["cases"] if c["separable_joint_uohm_each"] == joint)
    return {
        "bar_width_mm": row["bar_width_mm"],
        "bar_thickness_mm": row["bar_thickness_mm"],
        "one_dimensional_uohm": row["one_dimensional_uohm"],
        "transverse_allowance_uohm": row["transverse_allowance_uohm"],
        "bar_uohm": row["bar_uohm"],
        "separable_joint_uohm_each": joint,
        "total_uohm": case["total_uohm"],
        "margin_uohm": case["margin_uohm"],
        "meets_150_uohm": case["meets_150_uohm"],
        "max_separable_joint_uohm_each": row["max_separable_joint_uohm_each"],
    }


def _verdict_at_joint(rows: list[dict], joint: float, width: float) -> dict:
    """4 mm and thinnest-modelled verdicts at one separable-joint scenario.

    The report carries two declared scenarios (20 and 50 uohm) which disagree
    about thin bars, so every verdict has to name the scenario it belongs to.
    ``thinnest_modelled`` scans BAR_SCENARIOS only; it is not a continuum bound.
    """
    def case_of(row: dict) -> dict:
        return next(c for c in row["cases"]
                    if c["separable_joint_uohm_each"] == joint)

    passing = sorted(r["bar_thickness_mm"] for r in rows if case_of(r)["meets_150_uohm"])
    best4 = next(r for r in rows
                 if r["bar_width_mm"] == width and r["bar_thickness_mm"] == 4.0)
    case4 = case_of(best4)
    return {
        "separable_joint_uohm_each": joint,
        "four_mm_best_uohm": case4["total_uohm"],
        "four_mm_meets_150_uohm": case4["meets_150_uohm"],
        "thinnest_modelled_passing_bar_mm": passing[0] if passing else None,
        "scan_floor_is_a_model_choice": True,
    }


def _leg_width_sensitivity(collector_v_mm: float, collector_p_mm: float,
                           leg_mm: float, basis: dict,
                           extra_widths: tuple[float, ...]) -> list[dict]:
    """Lug width at the reference thickness, including the two real choices."""
    sheet = sheet_uohm_per_square(REFERENCE_BAR_THICKNESS_MM)
    collector = sheet * (collector_v_mm + collector_p_mm) / REFERENCE_BAR_WIDTH_MM
    transverse = sheet * 2.0 * TRANSVERSE_SQUARES_PER_RAIL
    widths = sorted({float(w) for w in LEG_WIDTH_SENSITIVITY_MM + extra_widths},
                    reverse=True)
    rows = []
    for leg_width in widths:
        r_bar = collector + sheet * (2.0 * leg_mm) / leg_width + transverse
        total = r_bar + basis["transition_allowance_uohm"] + basis["external_link_uohm"] + 100.0
        rows.append({
            "leg_width_mm": round(leg_width, 4),
            "bar_uohm": round(r_bar, 3),
            "total_uohm": round(total, 3),
            "meets_150_uohm": total <= BUDGET_UOHM,
        })
    return rows


def _in_rect(x: float, y: float, rect_x: tuple[float, float],
             rect_y: tuple[float, float]) -> bool:
    return rect_x[0] <= x <= rect_x[1] and rect_y[0] <= y <= rect_y[1]


def _segments_in_rect(value: dict, rect_x: tuple[float, float],
                      rect_y: tuple[float, float]) -> list[dict]:
    """Layer-2 tracks whose copper envelope overlaps the bar rectangle."""
    hits = []
    for line in value.get("lines") or []:
        if line.get("layer") != 2:
            continue
        x1, x2 = line["x1"] * MIL_MM, line["x2"] * MIL_MM
        y1, y2 = -line["y1"] * MIL_MM, -line["y2"] * MIL_MM
        half = line["width"] * MIL_MM / 2.0
        if (min(x1, x2) - half < rect_x[1] and max(x1, x2) + half > rect_x[0]
                and min(y1, y2) - half < rect_y[1] and max(y1, y2) + half > rect_y[0]):
            hits.append({"id": line["id"], "net": line["net"],
                         "x_mm": [round(min(x1, x2), 3), round(max(x1, x2), 3)],
                         "y_mm": [round(min(y1, y2), 3), round(max(y1, y2), 3)],
                         "width_mm": round(line["width"] * MIL_MM, 3)})
    return hits


def _vias_in_rect(value: dict, rect_x: tuple[float, float],
                  rect_y: tuple[float, float]) -> list[dict]:
    """Through-vias whose annulus overlaps the bar rectangle."""
    hits = []
    for via in value.get("vias") or []:
        x, y = via["x"] * MIL_MM, -via["y"] * MIL_MM
        radius = via["diameter"] * MIL_MM / 2.0
        if (rect_x[0] - radius <= x <= rect_x[1] + radius
                and rect_y[0] - radius <= y <= rect_y[1] + radius):
            hits.append({"id": via["id"], "net": via["net"],
                         "x_mm": round(x, 3), "y_mm": round(y, 3),
                         "diameter_mm": round(via["diameter"] * MIL_MM, 3)})
    return hits


def _geometry(value: dict, lands: dict, width: float, identity: dict) -> dict:
    board_mm = identity["board_mm"]
    y_v = sum(p["y_mm"] for p in lands["vout"]) / len(lands["vout"])
    y_p = sum(p["y_mm"] for p in lands["pgnd"]) / len(lands["pgnd"])
    max_width = min(2.0 * (y_v - EDGE_MARGIN_MM), y_p - y_v - INTER_POLE_GAP_MM)
    rects = {
        "vout": ((min(p["x_mm"] - p["half_x_mm"] for p in lands["vout"]),
                  max(p["x_mm"] + p["half_x_mm"] for p in lands["vout"])),
                 (y_v - width / 2.0, y_v + width / 2.0)),
        "pgnd": ((min(p["x_mm"] - p["half_x_mm"] for p in lands["pgnd"]),
                  max(p["x_mm"] + p["half_x_mm"] for p in lands["pgnd"])),
                 (y_p - width / 2.0, y_p + width / 2.0)),
    }
    bars_inside = all(
        0.0 <= rects[name][0][0] and rects[name][0][1] <= board_mm[0]
        and 0.0 <= rects[name][1][0] and rects[name][1][1] <= board_mm[1]
        for name in rects)
    if not bars_inside:
        raise ValueError("a bar rectangle overhangs the board outline")
    jout_inside = any(
        _in_rect(p["x_mm"], p["y_mm"], rects[name][0], rects[name][1])
        for p in lands["jout"] for name in ("vout", "pgnd"))
    pads_inside = all(
        0.0 <= p["x_mm"] <= board_mm[0] and 0.0 <= p["y_mm"] <= board_mm[1]
        for p in lands["vout"] + lands["pgnd"] + lands["jout"])
    outline = identity["outline"]
    return {
        "board_mm": [round(v, 6) for v in board_mm],
        "board_outline_source": (
            f"{outline['report']} (base board {outline['board_path']}, file md5 "
            f"{outline['md5']} verified; this is neither the candidate nor its D-02 "
            "parent dcx_main_board_g1_lr_repack.eprj2)"),
        "board_outline_is_base_board_provenance": True,
        "board_outline_is_parent_provenance": False,
        "base_board_file_md5_verified": outline["md5_verified"],
        "board_outline_dimensions_verified": False,
        "board_outline_dimensions_note": (
            "the md5 binds the base-board file bytes; the outline_mm field itself is "
            "read from the same report and is not independently re-measured, so the "
            "bars-inside-board gate is only as good as that field"),
        "board_outline_sha256": outline["sha256"],
        "board_outline_report_sha256": outline["report_sha256"],
        "board_outline_consistent_with_lands": pads_inside,
        "bars_inside_board": bars_inside,
        "source_row_y_mm": {"vout": round(y_v, 5), "pgnd": round(y_p, 5)},
        "terminal_y_mm": round((y_v + y_p) / 2.0, 6),
        "max_centred_bar_width_mm": round(max_width, 6),
        "width_limits_mm": {
            "centred_vout_bar_to_y0_edge": round(2.0 * (y_v - EDGE_MARGIN_MM), 6),
            "between_source_rows": round(y_p - y_v - INTER_POLE_GAP_MM, 6),
        },
        "bar_width_mm": width,
        "vout_bar_rect_mm": {"x": [round(rects["vout"][0][0], 3), round(rects["vout"][0][1], 3)],
                             "y": [round(rects["vout"][1][0], 3), round(rects["vout"][1][1], 3)]},
        "pgnd_bar_rect_mm": {"x": [round(rects["pgnd"][0][0], 3), round(rects["pgnd"][0][1], 3)],
                             "y": [round(rects["pgnd"][1][0], 3), round(rects["pgnd"][1][1], 3)]},
        "bar_edge_clearance_mm": {
            "vout_bar_to_y0_edge": round(rects["vout"][1][0] - 0.0, 3),
            "pgnd_bar_to_y131_edge": round(board_mm[1] - rects["pgnd"][1][1], 3),
            "between_bars": round(rects["pgnd"][1][0] - rects["vout"][1][1], 3),
        },
        "jout_inside_bar_pair": jout_inside,
        "bottom_tracks_under_vout_bar": _segments_in_rect(value, *rects["vout"]),
        "bottom_tracks_under_pgnd_bar": _segments_in_rect(value, *rects["pgnd"]),
        "bottom_vias_under_vout_bar": _vias_in_rect(value, *rects["vout"]),
        "bottom_vias_under_pgnd_bar": _vias_in_rect(value, *rects["pgnd"]),
        "bottom_copper_under_pgnd_bar": _segments_in_rect(value, *rects["pgnd"]),
        "bottom_copper_note": (
            "A bottom bar is a mechanical part with a standoff, not PCB copper; an "
            "overlap in plan is an insulation/standoff item, not a PCB DRC result. "
            "The readback exports polylines only as a count and has no zone or "
            "component-side primitives, so the bottom side is not shown clear."),
    }


def _validate(identity: dict, value: dict) -> None:
    if identity["candidate_sha256"] != identity["report_candidate_sha256"]:
        raise ValueError("candidate_sha256 != report_candidate_sha256: the accepted "
                         "candidate receipt does not bind this file")
    if identity["readback_sha256"] != identity["report_readback_sha256"]:
        raise ValueError("readback_sha256 != report_readback_sha256: the native reopen "
                         "receipt does not bind this file")
    if identity.get("readback_value_sha256") != _value_sha256(value):
        raise ValueError("readback_value_sha256 does not match the supplied readback "
                         "value; geometry must come from the bound readback")
    if identity["parent_cad_sha256"] != identity["report_parent_sha256"]:
        raise ValueError("parent_cad_sha256 != report_parent_sha256: the D-02 parent "
                         "board file does not match the receipt")
    if not identity["outline"]["md5_verified"]:
        raise ValueError("the board-outline report is not verified against its base board")
    if identity["native_drc_passed"] or identity["fabrication_approved"]:
        raise ValueError("DRC/fab state changed: this source-only screen must not "
                         "run on an approved board")


def build(value: dict, identity: dict) -> dict:
    """Report builder; the readback value is bound to the receipt hash."""
    _validate(identity, value)
    basis = joint_basis()
    lands = find_lands(value)
    width = REFERENCE_BAR_WIDTH_MM
    geometry = _geometry(value, lands, width, identity)
    if width > geometry["max_centred_bar_width_mm"] + 1e-9:
        raise ValueError("reference bar is wider than the board geometry allows")
    y_v = geometry["source_row_y_mm"]["vout"]
    y_p = geometry["source_row_y_mm"]["pgnd"]
    xs_v = [p["x_mm"] for p in lands["vout"]]
    xs_p = [p["x_mm"] for p in lands["pgnd"]]
    centre_v, collector_v = best_feed(xs_v)
    centre_p, collector_p = best_feed(xs_p)
    lo_v, hi_v, _ = feed_plateau(xs_v)
    lo_p, hi_p, _ = feed_plateau(xs_p)
    # Widest equal-loss pitch: one feed at each end of its flat interval.
    wide_v, wide_p = max(
        ((a, b) for a in (lo_v, hi_v) for b in (lo_p, hi_p)),
        key=lambda pair: abs(pair[0] - pair[1]))
    pitch_centre = abs(centre_v - centre_p)
    pitch_wide = abs(wide_v - wide_p)
    leg = (y_p - y_v - width) / 2.0
    lug_centre = min(pitch_centre - INTER_POLE_GAP_MM, width)
    lug_wide = min(pitch_wide - INTER_POLE_GAP_MM, width)
    if lug_centre <= 0.0:
        raise ValueError("the centre-feed pitch is too small for a two-pole gap")

    centre_rows = _central_rows(collector_v, collector_p, y_v, y_p,
                                pitch_centre, basis)
    wide_rows = _central_rows(collector_v, collector_p, y_v, y_p,
                              pitch_wide, basis)
    reference_wide = _config_case(
        next(r for r in wide_rows
             if r["bar_width_mm"] == width
             and r["bar_thickness_mm"] == REFERENCE_BAR_THICKNESS_MM), 50.0)
    reference_centre_4 = _config_case(
        next(r for r in centre_rows
             if r["bar_width_mm"] == width and r["bar_thickness_mm"] == 4.0), 50.0)
    reference_centre_ref = _config_case(
        next(r for r in centre_rows
             if r["bar_width_mm"] == width
             and r["bar_thickness_mm"] == REFERENCE_BAR_THICKNESS_MM), 50.0)

    variants = {
        "centre": (collector_v, collector_p, pitch_centre, lug_centre),
        "widest_equal_loss": (collector_v, collector_p, pitch_wide, lug_wide),
    }
    configurations = []
    for name, (cv_, cp_, pitch, lug) in variants.items():
        for thickness in CONFIG_THICKNESS_MM:
            row = _row(cv_, cp_, leg, leg, lug, width, thickness, basis)
            case = _config_case(row, 50.0)
            configurations.append({
                "feed": name,
                "pole_pitch_mm": round(pitch, 3),
                "leg_width_mm": round(lug, 4),
                **case,
            })
    four_mm = [c for c in configurations if c["bar_thickness_mm"] == 4.0]
    # Configurations are evaluated at the 50 uohm joint scenario, the working
    # assumption; the 20 uohm scenario is reported separately per joint below.
    passing_thicknesses = sorted({
        c["bar_thickness_mm"] for c in configurations
        if c["feed"] == "widest_equal_loss" and c["meets_150_uohm"]})
    if not passing_thicknesses:
        raise ValueError("no thickness passes at 50 uohm joints with the widest feed")
    minimum_passing_thickness = passing_thicknesses[0]
    if minimum_passing_thickness != REFERENCE_BAR_THICKNESS_MM:
        raise ValueError("the reference thickness is not the thinnest passing bar "
                         "at 50 uohm joints")
    max_lug_4mm = _row(collector_v, collector_p, leg, leg, width, width, 4.0, basis)
    four_mm_best = _config_case(max_lug_4mm, 50.0)
    five_mm = [c for c in configurations
               if c["bar_thickness_mm"] == REFERENCE_BAR_THICKNESS_MM
               and c["feed"] == "widest_equal_loss"][0]
    leg_sheet = sheet_uohm_per_square(REFERENCE_BAR_THICKNESS_MM)
    leg_sensitivity = _leg_width_sensitivity(
        collector_v, collector_p, leg, basis, (lug_centre, lug_wide))
    # Break-even lug width: the leg term must consume the whole remaining
    # headroom, where the headroom excludes the collector and transverse terms
    # but includes the reference leg's own contribution.
    leg_term_reference = leg_sheet * 2.0 * leg / lug_wide
    headroom = (BUDGET_UOHM - basis["transition_allowance_uohm"]
                - basis["external_link_uohm"] - 100.0
                - reference_wide["bar_uohm"] + leg_term_reference)
    leg_break_even = (leg_sheet * 2.0 * leg / headroom) if headroom > 0.0 else None

    jout_v = next(p for p in lands["jout"] if p["net"] == "VOUT")
    jout_p = next(p for p in lands["jout"] if p["net"] == "PGND")
    jout_y = sum(p["y_mm"] for p in lands["jout"]) / len(lands["jout"])
    jout_collector_v = weighted_length_mm(xs_v, jout_v["x_mm"])
    jout_collector_p = weighted_length_mm(xs_p, jout_p["x_mm"])
    jout_rows = []
    for row_width, thickness in BAR_SCENARIOS:
        leg_v = jout_y - (y_v + row_width / 2.0)
        leg_p = jout_y - (y_p + row_width / 2.0)
        if leg_v <= 0.0 or leg_p <= 0.0:
            raise ValueError("J_OUT is not beyond both source rows; topology changed")
        jout_rows.append(_row(jout_collector_v, jout_collector_p, leg_v, leg_p,
                              row_width, row_width, thickness, basis))
    reference_jout = _config_case(
        next(r for r in jout_rows
             if r["bar_width_mm"] == width
             and r["bar_thickness_mm"] == REFERENCE_BAR_THICKNESS_MM), 50.0)
    pgnd_rect_x = geometry["pgnd_bar_rect_mm"]["x"]
    pgnd_rect_y = geometry["pgnd_bar_rect_mm"]["y"]
    crosses = (pgnd_rect_x[0] <= jout_v["x_mm"] <= pgnd_rect_x[1]
               and pgnd_rect_y[0] < jout_y and pgnd_rect_y[1] > y_v + width / 2.0)

    neck = neck_analyze(value["lines"])
    neck_70 = next(s for s in neck["scenarios"] if s["nominal_thickness_um"] == 70)
    # The neck tool's own source sentence names the Lr board; this report runs on
    # the signal-stubs candidate, so restate the binding and the ratio's scope.
    neck_limits = [m for m in neck["model_limitations"]
                   if not m.startswith("Source-locked")]
    neck_limits.append(
        "Source-locked to the saved/reopened signal-stubs candidate readback "
        f"{identity['candidate_sha256'][:8]}; the times-budget ratio is the 1 mm "
        "necks only, not the whole loop.")

    fixed = basis["transition_allowance_uohm"] + basis["external_link_uohm"]
    post = post_uohm(1.5, 1.6)
    worst_length = (max(abs(t - wide_v) for t in xs_v)
                    + max(abs(t - wide_p) for t in xs_p) + 2.0 * leg)
    worst_total = (leg_sheet * worst_length / lug_wide
                   + leg_sheet * 2.0 * TRANSVERSE_SQUARES_PER_RAIL
                   + fixed + 100.0)
    transition_break_even = BUDGET_UOHM - reference_wide["bar_uohm"] - basis["external_link_uohm"] - 100.0
    alternatives = [{"id": alt["id"], "bar_pair_uohm": alt["bar_pair_uohm"],
                     "total_uohm": round(reference_wide["total_uohm"]
                                         - basis["external_link_uohm"]
                                         + alt["bar_pair_uohm"], 3)}
                    for alt in basis["external_link_alternatives"]
                    if abs(alt["bar_pair_uohm"] - basis["external_link_uohm"]) > 1e-9]
    return {
        "schema": "g1_100a_output_interface/3",
        "status": "CONCEPT_ONLY_NOT_FOR_FAB",
        "candidate": {
            "path": BOARD.relative_to(ROOT).as_posix(),
            "sha256": identity["candidate_sha256"],
            "parent_path": PARENT.relative_to(ROOT).as_posix(),
            "parent_sha256": identity["parent_cad_sha256"],
            "readback": READBACK.relative_to(ROOT).as_posix(),
            "readback_sha256": identity["readback_sha256"],
            "readback_value_sha256": identity["readback_value_sha256"],
        },
        "design_basis": basis,
        "source_lands": lands,
        "geometry": geometry,
        "topologies": {
            "board_only_existing": {
                "computed_from": "g1_current_neck_screen.analyze(value['lines'])",
                "reference_report": "hardware/dcx_main/g1/g1_100a_copper_neck_screen.json",
                "scope": ("1 mm necks only; excludes trunks, pads, vias, joints and "
                          "current spreading"),
                "scenarios": neck["scenarios"],
                "times_budget_at_70um": round(
                    neck_70["combined_necks_uohm"] / BUDGET_UOHM, 3),
                "meets_150_uohm": any(s["within_complete_rail_budget"]
                                      for s in neck["scenarios"]),
                "model_limitations": neck_limits,
            },
            "central_two_pole_bar": {
                "description": (
                    "Two bottom-side flat bars centred on their source rows with a "
                    "two-lug terminal between the rows.  The collector loss is flat "
                    "over a whole feed interval, so the pole pitch (hence the lug "
                    "width) is a design choice: a narrower pitch at the same "
                    "collector loss is worse, and the centre feed is one mid-pitch "
                    "choice, not a bound."),
                "transverse_allowance": {
                    "squares_per_rail": TRANSVERSE_SQUARES_PER_RAIL,
                    "total_squares": 2.0 * TRANSVERSE_SQUARES_PER_RAIL,
                    "rule": ("pads sit on the bar centreline and the terminal draws "
                             "from the inner edge: half a bar width at the bar-width "
                             "cross-section per rail"),
                    "is_a_screening_estimate_not_a_2d_solve": True,
                },
                "feeds": {
                    "centre": {
                        "vout_x_mm": round(centre_v, 4),
                        "pgnd_x_mm": round(centre_p, 4),
                        "pole_pitch_mm": round(pitch_centre, 4),
                        "leg_width_mm": round(lug_centre, 4),
                        "collector_length_mm": {"vout": round(collector_v, 4),
                                                "pgnd": round(collector_p, 4)},
                    },
                    "widest_equal_loss": {
                        "vout_x_mm": round(wide_v, 4),
                        "pgnd_x_mm": round(wide_p, 4),
                        "pole_pitch_mm": round(pitch_wide, 4),
                        "leg_width_mm": round(lug_wide, 4),
                        "collector_length_mm": {"vout": round(collector_v, 4),
                                                "pgnd": round(collector_p, 4)},
                        "vout_flat_interval_mm": [round(lo_v, 4), round(hi_v, 4)],
                        "pgnd_flat_interval_mm": [round(lo_p, 4), round(hi_p, 4)],
                    },
                },
                "leg_length_mm_each": round(leg, 4),
                "configurations": configurations,
                "reference": reference_wide,
                "leg_width_sensitivity": leg_sensitivity,
                "scenarios_at_widest_feed": wide_rows,
            },
            "jout_terminated_bar": {
                "description": (
                    "The bars routed to the existing J_OUT at y = 116 mm; the VOUT leg "
                    "alone is 76.5 mm, and its straight path crosses the PGND bar."),
                "feeds": {"vout_x_mm": round(jout_v["x_mm"], 4),
                          "pgnd_x_mm": round(jout_p["x_mm"], 4)},
                "collector_equivalent_length_mm": {
                    "vout": round(jout_collector_v, 4),
                    "pgnd": round(jout_collector_p, 4)},
                "leg_width_is_a_lower_bound": True,
                "vout_leg_crosses_pgnd_bar": crosses,
                "realizable_as_drawn": not crosses,
                "scenarios": jout_rows,
                "reference": reference_jout,
            },
        },
        "conclusion": {
            "board_only_impossible": True,
            "board_only_times_budget_at_2oz": round(
                neck_70["combined_necks_uohm"] / BUDGET_UOHM, 3),
            "jout_terminated_bar_is_the_100a_path": False,
            "jout_lower_bound_uohm": reference_jout["total_uohm"],
            "jout_realizable_as_drawn": not crosses,
            "four_mm_fails_at_every_lug_width_at_50_uohm_joints":
                four_mm_best["meets_150_uohm"] is False,
            "verdict_joint_scenario_uohm": 50.0,
            "four_mm_best_case_uohm": four_mm_best["total_uohm"],
            "four_mm_configurations": four_mm,
            "per_joint_verdicts": [
                _verdict_at_joint(wide_rows, joint, width)
                for joint in basis["joint_scenarios_uohm"]],
            "minimum_modelled_passing_thickness_at_50_uohm_mm": minimum_passing_thickness,
            "reference_configuration": {
                "feed": "widest_equal_loss",
                "pole_pitch_mm": round(pitch_wide, 4),
                "leg_width_mm": round(lug_wide, 4),
                **reference_wide,
            },
            "centre_fed_four_mm": reference_centre_4,
            "centre_fed_reference_thickness": reference_centre_ref,
            "leg_width_break_even_mm": round(leg_break_even, 4) if leg_break_even else None,
            "transition_break_even_uohm": round(transition_break_even, 3),
            "transition_modelled_bounds_uohm": {
                "one_post_per_rail_in_series": round(2.0 * post, 3),
                "all_12_lands_paralleled": round(post / 4.0 + post / 8.0, 3),
            },
            "joint_break_even_uohm": reference_wide["max_separable_joint_uohm_each"],
            "joint_break_even_depends_on_thickness": True,
            "external_link_uohm": basis["external_link_uohm"],
            "external_link_is_unverified": True,
            "external_link_same_joint_alternatives": alternatives,
            "current_sharing": "equal (25 A per CTAP, 12.5 A per SR land)",
            "single_land_total_uohm": round(worst_total, 3),
            "reference_statement": (
                f"At 39 x {REFERENCE_BAR_THICKNESS_MM:.0f} mm with {lug_wide:.3f} mm lugs and a "
                f"{pitch_wide:.3f} mm pole pitch, a 30 uohm unverified transition, the "
                f"unverified {basis['external_link_case']} pair "
                f"({basis['external_link_uohm']} uohm) and 50 uohm joints, the central "
                f"termination is {reference_wide['total_uohm']} uohm: a pass with "
                f"{reference_wide['margin_uohm']} uohm margin. At the same 50 uohm "
                f"joints the same thickness centre-fed (16.599 mm lugs) is "
                f"{reference_centre_ref['total_uohm']} uohm and fails, and 4 mm fails "
                "at every lug width; at the 20 uohm joint scenario 4 mm passes. J_OUT "
                f"is {reference_jout['total_uohm']} uohm as a lower bound and not "
                "realizable as drawn."),
            "next_physical_deliverables": [
                "Real CTAP winding terminals and SR source attachment (D-07), not the "
                "24 provisional pads.",
                "A 2-D/FE current-distribution solve for the transverse path; the "
                "0.5-square-per-rail allowance is a screen, not a bound.",
                "Measured pad-to-bar transition resistance; the 30 uohm allowance breaks "
                f"even at {round(transition_break_even, 3)} uohm.",
                "Measured separable joint resistance; the acceptance number is "
                f"{reference_wide['max_separable_joint_uohm_each']} uohm per pole at "
                "39 x 5 mm, not the 50 uohm placeholder.",
                f"Lugs at least {round(leg_break_even, 2) if leg_break_even else '?'} mm "
                "wide, i.e. a terminal pitch of at least "
                f"{round(leg_break_even + INTER_POLE_GAP_MM, 2) if leg_break_even else '?'} mm.",
                "Measured current sharing across the four CTAP and eight SR lands; a "
                f"single-land worst case is {round(worst_total, 1)} uohm.",
                "Bottom-side standoff, insulation, the thermal/cold-plate interface, 3D "
                "height and PCB fab DFM; the bars occupy the bottom of the board.",
            ],
        },
        "not_qualified": [
            "No finite-element current distribution, local hot spot or 2D spreading solve; "
            "the transverse term is a screening allowance that a real solve must replace.",
            "Equal DC current sharing is assumed; the single-land worst case is reported.",
            "The 30 uohm transition, the 20/50 uohm joints and the 6.798 uohm external "
            "pair are unverified math cases, not measurements.",
            "The external pair assumes one separable joint per pole; the budget's "
            "four-joint alternative is reported and cannot pass at 50 uohm per joint.",
            "The 39 mm lug and the 51.6 mm pole pitch are a design choice inside the "
            "flat-loss feed interval, not a physical bound; a narrower terminal "
            "requires more copper or a thicker bar.",
            "The 20/50 uohm joint scenarios disagree about thin bars (4 mm fails at 50, "
            "passes at 20), so every thickness verdict names its joint scenario.",
            "The four CTAP pads are design-owned placeholders, not physical terminals.",
            "The bottom bars are not in CAD; no native DRC or fab DFM has run on them.",
            "The readback exports polylines only as a count and carries no zone or "
            "component-side primitives; the bottom side is not shown clear.",
            "The board outline comes from the base-board report "
            "(dcx_main_board_g1.eprj2), not from the candidate or its D-02 parent; the "
            "report's md5 binds the base-board file, but the outline_mm field itself is "
            "not independently re-measured, so the bars-inside-board gate and every "
            "clearance share that unverified field.",
            "The canonical readback value hash binds the value passed to build() to the "
            "file read in the same call; it is not a capture-time attestation, and "
            "review_signal_stubs.py --resign would refresh the file hash without "
            "re-verifying geometry.",
            "The 16 mm assembly height and the cold-plate/thermal interface are unverified.",
        ],
        "fabrication_approved": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    args = parser.parse_args()
    value, identity = load()
    result = build(value=value, identity=identity)
    if args.write:
        REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    elif not REPORT.is_file() or json.loads(REPORT.read_text(encoding="utf-8")) != result:
        raise SystemExit("G1 100 A output-interface screen stale; rerun --write")
    ref = result["conclusion"]["reference_configuration"]
    print(f"board-only at 2 oz: {result['conclusion']['board_only_times_budget_at_2oz']}x budget")
    print(f"central 39x5 widest feed: {ref['total_uohm']} uohm "
          f"({'PASS' if ref['meets_150_uohm'] else 'FAIL'}), {ref['margin_uohm']} uohm margin")
    print(f"4 mm at any lug width, 50 uohm joints: "
          f"{result['conclusion']['four_mm_best_case_uohm']} uohm "
          f"({'PASS' if not result['conclusion']['four_mm_fails_at_every_lug_width_at_50_uohm_joints'] else 'FAIL'})")
    print(f"J_OUT 39x5: {result['conclusion']['jout_lower_bound_uohm']} uohm (lower bound)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
