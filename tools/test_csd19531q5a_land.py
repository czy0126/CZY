"""Tests for the CSD19531Q5A land and stencil digitisation.

Same shape as the BSC test: the tool reads the datasheet with PyMuPDF, which is
**not** a project dependency, so the regeneration test skips where the module is
absent while the committed JSON is still held to its own invariants -- those are
the numbers the A5 footprint is built from, so they have to hold in CI too.

Beyond the geometry, one test cross-checks the pinout against
``pin_footprint_review.csv``.  The pinout this tool measured (left column 5-8
top to bottom, right column 4 down to 1) was chosen by where the printed labels
sit, and the review table is the independent statement of the same contract.
"""

import csv
import hashlib
import json
import re
from pathlib import Path

import pytest

import csd19531q5a_land as land

ROOT = Path(__file__).resolve().parent.parent
REVIEW = ROOT / "hardware" / "dcx_main" / "pin_footprint_review.csv"


@pytest.fixture(scope="module")
def reported() -> dict:
    return json.loads(land.DEFAULT_JSON.read_text(encoding="utf-8"))


def _grow(rect: list[float], by: float) -> list[float]:
    return [rect[0] - by, rect[1] - by, rect[2] + by, rect[3] + by]


def _intersection(a: list[float], b: list[float]) -> tuple[float, float]:
    return (max(0.0, min(a[2], b[2]) - max(a[0], b[0])),
            max(0.0, min(a[3], b[3]) - max(a[1], b[1])))


def _review_pins(ref: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    with REVIEW.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["ref"] == ref:
                out.setdefault(row["golden_pin"], []).append(row["pad"])
    return out


def test_the_committed_json_is_what_the_two_pages_produce():
    """A hand edit of the geometry or of the provenance shows up here."""
    pytest.importorskip("fitz")
    fresh = land.json_text(land.build(land.DEFAULT_PDF))
    assert land.DEFAULT_JSON.read_text(encoding="utf-8") == fresh


def test_every_check_passes_and_no_printed_callout_is_unaccounted(reported):
    assert all(reported["checks"].values())
    assert [k for k, ok in reported["checks"].items() if not ok] == []
    assert reported["callouts"]["stencil_unassigned_mm"] == []


def test_the_source_hash_is_the_pdf_this_repository_ships(reported):
    pdf = ROOT / reported["source"]["pdf"]
    assert hashlib.sha256(pdf.read_bytes()).hexdigest() == reported["source"]["sha256"]
    assert reported["source"]["revision"] == "SLPS406B, 2013-09 to 2014-05"


def test_the_pinout_is_the_one_the_review_table_assigns(reported):
    """The drawing is read, not remembered -- so pin 4 has to land where the
    review table says gate 4 is, and 5-8 where it says drain."""
    for ref in ("QH", "QL"):
        pins = _review_pins(ref)
        assert pins["G"] == ["4"], ref
        assert sorted(pins["S"]) == ["1", "2", "3"], ref
        assert sorted(pins["D"]) == ["5", "6", "7", "8", "9"], ref
    pinout = reported["pinout"]
    assert pinout["left_pins"] == [5, 6, 7, 8]
    assert pinout["right_pins"] == [4, 3, 2, 1]
    # pin 9 is the exposed pad.  Neither figure prints a number for it, so this
    # is the symbol's assignment, and the limitation says so.
    assert pinout["body_pin"] == "9"
    assert any("numbered 9" in text for text in reported["limitations"])


def test_every_named_pad_is_a_symbol_pin_and_the_rest_are_stencils(reported):
    named = [p for p in reported["pads"] if p["number"]]
    unnamed = [p for p in reported["pads"] if not p["number"]]
    assert {p["number"] for p in named} == {str(i) for i in range(1, 10)}
    assert all(p["layers"] == ["F.Cu"] for p in named)
    assert all(p["layers"] in (["F.Mask"], ["F.Paste"]) for p in unnamed)
    # Nine copper pads (body + four teeth + four source lands) because the drain
    # and the source each repeat a number across fingers on a common base.
    assert len(named) == 9
    assert len(unnamed) == 9 + 12


def test_each_tooth_runs_into_the_body_so_the_drain_is_one_land(reported):
    """The drawn comb meets edge to edge; the *pads* overlap on purpose.

    Without the push-in, a rounding in a CAD importer leaves pins 5-8 on copper
    that only touches, and DRC reports the drain as unconnected.
    """
    body = next(p for p in reported["pads"] if p["kind"] == "drain_body")
    teeth = [p for p in reported["pads"] if p["kind"] == "drain_tooth"]
    assert len(teeth) == 4
    for tooth in teeth:
        dx, dy = _intersection(body["rect"], tooth["rect"])
        assert abs(dx - reported["pad_overlap_mm"]) < 1e-9, tooth
        assert dy > 0.0, tooth
    # The copper itself is unchanged: the extension lives on the pad only, so
    # the drawn fingers still end on the body's left edge to the last nm.
    body_left = reported["copper"]["body"]["rect"][0]
    assert all(abs(t["rect"][2] - body_left) < 1e-9 for t in reported["copper"]["teeth"])


def test_the_mask_is_each_land_grown_by_the_expansion(reported):
    by = reported["mask_expansion_mm"]
    copper = ([reported["copper"]["body"]]
              + reported["copper"]["teeth"] + reported["copper"]["right"])
    masks = sorted((p["rect"] for p in reported["pads"] if p["layers"] == ["F.Mask"]),
                   key=lambda r: (round(r[0], 6), round(r[1], 6)))
    expected = sorted((_grow(c["rect"], by) for c in copper),
                      key=lambda r: (round(r[0], 6), round(r[1], 6)))
    for got, want in zip(masks, expected):
        assert all(abs(a - b) < 1e-9 for a, b in zip(got, want)), (got, want)


def test_every_stencil_aperture_sits_on_the_pad_it_serves(reported):
    """The lead openings are the copper's own row centres, and the blocks hang
    off their printed gaps -- a redrawn stencil cannot drift from the land."""
    leads = [p for p in reported["paste"] if p["kind"] == "paste_lead"]
    assert len(leads) == 8
    bands = {i: reported["copper"]["right"][i] for i in range(4)}
    for lead in leads:
        band = bands[lead["band"]]
        assert abs((lead["rect"][1] + lead["rect"][3]) / 2
                   - (band["rect"][1] + band["rect"][3]) / 2) < land.STENCIL_TOL_MM
    # The sheet prints 8x one lead size and 4x one block size; the model has to
    # produce exactly that split, or a callout was matched to the wrong aperture.
    widths: dict[float, int] = {}
    for p in reported["paste"]:
        if p["kind"] in ("paste_lead", "paste_block"):
            key = round(p["rect"][2] - p["rect"][0], 3)
            widths[key] = widths.get(key, 0) + 1
    assert widths == {0.5: 8, 1.585: 2, 1.235: 2}


def test_every_pad_is_inside_the_courtyard(reported):
    x0, y0, x1, y1 = reported["courtyard"]
    for pad in reported["pads"]:
        px0, py0, px1, py1 = pad["rect"]
        assert x0 <= px0 and px1 <= x1 and y0 <= py0 and py1 <= y1, pad


def test_the_stencil_is_smaller_than_the_lands_it_serves(reported):
    """The bound is a sanity floor, not a target: TI's four blocks cover 48 % of
    the copper, and that is the figure's own split, not a number to tune."""
    results = reported["results"]
    assert 0.4 < results["paste_fraction"] < 1.0
    assert results["paste_area_mm2"] < results["copper_area_mm2"]
    assert results["residual_max_mm"] <= land.LAND_TOL_MM
    # Drafting rounding, not a measurement limit: every residual, including the
    # 21 um on the overall height, fits inside one 1-mil grid step.
    assert results["residual_max_mm"] <= land.MIL_MM


def test_the_footprint_text_carries_exactly_these_pads(reported):
    text = land.footprint_text(reported)
    pads = re.findall(r'\(pad "([^"]*)" smd rect\s*\(at (-?[\d.]+) (-?[\d.]+)\)\s*'
                      r'\(size ([\d.]+) ([\d.]+)\)\s*\(layers ([^)]*)\)', text)
    assert len(pads) == len(reported["pads"])
    assert sum(1 for p in pads if p[0]) == 9
    assert sum(1 for p in pads if '"F.Paste"' in p[5]) == 12
    assert sum(1 for p in pads if '"F.Mask"' in p[5]) == 9
    # The footprint refuses to build from a JSON whose checks failed.
    broken = json.loads(json.dumps(reported))
    broken["checks"]["every_land_dimension_matches_the_drawing"] = False
    with pytest.raises(SystemExit):
        land.footprint_text(broken)
