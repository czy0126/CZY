"""A5 gates: the 1:1 power-stage placement has to be a checkable claim.

`hardware/dcx_mech/power_stage_placement.kicad_pcb` is a placement study, not a
routed board -- there are no nets, no tracks, and every pad is unconnected by
design.  That means the usual DRC gates (unconnected items, clearance) say
nothing here, and a board file that merely *parses* proves nothing either.

So the gates are the two questions a placement study exists to answer:

* does every outline fit inside the board without touching its neighbour, and
* does the stack of parts fit under the 10 mm height limit?

The second one is the reason this deliverable exists at all: five ELP32 cores
at 9.8 mm worst case.  The height JSON's flat-board case is 9.94 mm, i.e. it
clears 10 mm by 60 um -- a number that is a coincidence, not a margin -- and
the 0.5 mm clamp case is 10.44 mm, over.  A placement document that quietly
drops that finding would look like progress and be the opposite, so
`test_the_flat_board_clears_the_limit_by_less_than_a_manufacturing_tolerance`
asserts the *margin is unreal*, and the clamp failure with it: if someone later
edits the numbers until the flat board "comfortably passes", this goes red.

The mechanical board is regenerated from one table, so the last test keeps the
committed `.kicad_pcb` byte-identical to what the table produces -- the same
stale-generated-file contract `tools/ci_check.py` enforces elsewhere.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import main_board_mechanical as mbm  # noqa: E402

EVIDENCE = {"datasheet", "generated-json", "kicad-library", "PROVISIONAL"}


def test_no_two_parts_overlap():
    """Bounding boxes must not touch.  `overlaps()` returns a pair whenever the
    intersection area is positive, so an exact edge contact (area 0) is allowed
    and a 0.01 mm intrusion is not."""
    bad = mbm.overlaps(mbm.PARTS)
    assert bad == [], [f"{a} x {b} by {area:.2f} mm^2" for a, b, area in bad]


def test_every_part_is_inside_the_board_outline():
    w, d = mbm.board_rect(mbm.PARTS)
    for part in mbm.PARTS:
        x0, y0, x1, y1 = mbm.bbox(part)
        assert 0.0 <= x0 and x1 <= w, f"{part.ref} sticks out in x: {x0:.2f}..{x1:.2f} of {w:.2f}"
        assert 0.0 <= y0 and y1 <= d, f"{part.ref} sticks out in y: {y0:.2f}..{y1:.2f} of {d:.2f}"


def test_every_dimension_states_its_evidence_class():
    """The whole document is worthless if a provisional case size travels
    without its label.  Three classes are allowed and PROVISIONAL is the only
    one that may appear in the "assumed" list of the report."""
    for part in mbm.PARTS:
        assert part.evidence in EVIDENCE, f"{part.ref}: {part.evidence!r}"
        if part.evidence == "PROVISIONAL":
            assert part.note, f"{part.ref} is assumed but carries no note saying what is assumed"
    report = mbm.report()
    assumed = {p["ref"] for p in report["parts"] if p["evidence"] == "PROVISIONAL"}
    assert assumed == {p.ref for p in mbm.PARTS if p.evidence == "PROVISIONAL"}
    assert assumed, "every dimension provisional means the table is a guess; state it"


def test_the_flat_board_clears_the_limit_by_less_than_a_manufacturing_tolerance():
    """The mechanical finding, asserted as a *thin* margin on purpose.

    9.94 mm against a 10 mm limit is 60 um.  Nothing on a first article is
    specified to 60 um: glue dispense, label thickness and core flatness are
    each larger than that.  Adding the 0.5 mm clamp -- the obvious way to hold
    five loose cores down -- puts the same stack at 10.44 mm, over the limit.

    So the placement has to say two things at once: every outline fits in X/Y,
    and the Z stack does not fit at all unless the cores sit in pockets.
    """
    magnetics = [p for p in mbm.PARTS if p.footprint == mbm.ELP32_FP]
    assert len(magnetics) == 5, "T1-T4 and Lr are all on ELP32"
    report = mbm.report()
    height = report["height"]
    assert height["parts_max_height_mm"] <= mbm.HEIGHT_LIMIT_MM, (
        "a bare part taller than the limit makes the board impossible; the "
        "pocket rescues the stack, a larger limit would not")
    assert height["flat_board_margin_mm"] < 0.1, (
        "the flat board only 'passes' by 60 um -- if this number grew, someone "
        "changed the height stack and has to re-read this section, not relax it")
    assert height["clamp_case_margin_mm"] < 0.0, "the clamp case is the one that fails"
    assert height["pocket_required_refs"] == sorted(p.ref for p in magnetics)
    # the input terminal is a second, independent 10.0 mm user of the same budget
    assert "J_IN" in height["at_limit_refs"]


def test_the_lr_shares_the_transformer_core_so_it_shares_the_pocket():
    """Lr is on the same ELP32 as T1-T4 (lr_design.json), so a mechanical
    drawing that pockets only the transformers would fail on the bench."""
    lr = next(p for p in mbm.PARTS if p.ref == "Lr")
    t1 = next(p for p in mbm.PARTS if p.ref == "T1")
    assert (lr.w_mm, lr.d_mm) == (t1.w_mm, t1.d_mm)


def test_the_committed_board_is_what_the_table_produces(tmp_path):
    """Regenerate into a temp directory and compare bytes.

    Timestamps are excluded from the board file for exactly this reason; a
    generated artifact that changes on every run cannot be checked by a diff
    and hides real edits behind noise."""
    mbm.write(tmp_path)
    for name in ("power_stage_placement.kicad_pcb", "fp-lib-table",
                 "power_stage_placement.kicad_pro", "placement_report.json"):
        committed = mbm.OUT / name
        assert committed.exists(), f"{name} is not committed"
        # Autocrlf rewrites this working copy on checkout; the generator always
        # writes LF, so compare with line endings normalised.  `current_manifest.sha256()`
        # does the same thing for the same reason.
        assert _normalised(committed) == _normalised(tmp_path / name), (
            f"{name} is stale -- run python tools/main_board_mechanical.py")


def _normalised(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def test_the_report_lists_every_part_once():
    report = mbm.report()
    refs = [p["ref"] for p in report["parts"]]
    assert len(refs) == len(set(refs))
    assert set(refs) == {p.ref for p in mbm.PARTS}
    json.dumps(report)                       # must be serialisable as-is


def test_the_committed_svg_is_drawn_at_one_to_one():
    """``--scale 1 --page-size-mode 2`` crops the page to the board, so the SVG's
    ``width`` is the board's real size in millimetres.  That is the whole point
    of a 1:1 drawing: someone can print it and lay a core on it.  A "fit to
    page" export would tile the same geometry at some arbitrary scale and read
    identically to the eye, so the number is what has to be checked."""
    svg = (mbm.OUT / "placement_1to1.svg").read_text(encoding="utf-8")
    match = re.search(r'width="([0-9.]+)mm"', svg)
    assert match, "the SVG is not in millimetres"
    w, _ = mbm.board_rect()
    # KiCad crops to the drawn extents, so a few hundredths of a millimetre of
    # line width is expected; a fit-to-page scaling would be off by any amount.
    assert abs(float(match.group(1)) - w) < 0.5, f"{match.group(1)} mm wide for a {w} mm board"


def test_the_document_quotes_the_report_it_describes():
    """`design/v3/A5_机械布置_2026-11-01.md` is the only thing a person reads
    before laying a core on the drawing.  Its numbers must come from
    `placement_report.json`, and its provisional list must come from the parts
    table -- a hand-written "all sizes verified" would otherwise outlive the
    data it describes."""
    doc = (mbm.OUT.parent.parent / "design/v3/A5_机械布置_2026-11-01.md").read_text(encoding="utf-8")
    doc = doc.replace("−", "-")          # the tables use a real minus sign
    data = mbm.report()
    assert f"{data['board']['width_mm']:.1f} × {data['board']['depth_mm']:.1f} mm" in doc
    assert f"{data['clearance']['min_gap_mm']:.1f} mm" in doc
    height = data["height"]
    assert f"{height['flat_board_worst_case_mm']:.2f} mm" in doc
    assert f"{height['flat_board_margin_mm']:+.2f} mm" in doc
    assert f"{height['clamp_case_worst_case_mm']:.2f} mm" in doc
    assert f"{height['clamp_case_margin_mm']:+.2f} mm" in doc
    for ref in data["provisional"]:
        assert ref in doc, f"{ref} is provisional but the document does not say so"
    assert "沉槽" in doc, "the pocket requirement is the whole point of this document"


@pytest.mark.skipif(not mbm.KICAD_CLI.exists(), reason="kicad-cli is not installed here")
def test_kicad_reports_no_drc_errors_and_no_unknown_footprints(tmp_path):
    """Two separate assertions, because they fail for different reasons.

    * Errors: a placement study gets none only if the courtyards really do not
      touch -- this is DRC re-checking the python `overlaps()` test with a
      different engine, which is worth having.
    * `lib_footprint_issues`: the trap already documented for the schematic
      side.  A footprint from a library the project cannot see is silently
      treated as a black box, so its courtyard is not checked either.
    """
    out = tmp_path / "drc.json"
    subprocess.run([str(mbm.KICAD_CLI), "pcb", "drc", "--format", "json",
                    "--severity-all", "-o", str(out), str(mbm.OUT / "power_stage_placement.kicad_pcb")],
                   check=False, capture_output=True)
    data = json.loads(out.read_text(encoding="utf-8"))
    violations = data.get("violations", [])
    errors = [v for v in violations if v["severity"] == "error"]
    assert errors == [], [f"{v['type']}: {v['description']}" for v in errors[:5]]
    unknown = [v for v in violations if v["type"] == "lib_footprint_issues"]
    assert unknown == [], [v["description"] for v in unknown[:5]]
