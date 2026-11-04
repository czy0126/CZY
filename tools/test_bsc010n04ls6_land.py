"""Tests for the BSC010N04LS6 land digitisation.

The tool reads Figure 2 of the datasheet with PyMuPDF, which is **not** a
project dependency (``requirements.txt`` has pytest, numpy, matplotlib and
PyLTSpice).  The regeneration test therefore skips where the module is absent,
while the committed JSON is still checked against its own invariants -- those
are the numbers the PCB generator consumes, so they have to hold in CI too.
"""

import hashlib
import json
from pathlib import Path

import pytest

import bsc010n04ls6_land as land

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def reported() -> dict:
    return json.loads(land.DEFAULT_JSON.read_text(encoding="utf-8"))


def _intersection(a: list[float], b: list[float]) -> tuple[float, float]:
    return (max(0.0, min(a[2], b[2]) - max(a[0], b[0])),
            max(0.0, min(a[3], b[3]) - max(a[1], b[1])))


def _union(rects: list[list[float]]) -> list[float]:
    return [min(r[0] for r in rects), min(r[1] for r in rects),
            max(r[2] for r in rects), max(r[3] for r in rects)]


def _grow(rect: list[float], by: float) -> list[float]:
    return [rect[0] - by, rect[1] - by, rect[2] + by, rect[3] + by]


def test_the_committed_json_is_what_the_page_produces():
    """A hand edit of either the geometry or the provenance shows up here."""
    pytest.importorskip("fitz")
    fresh = land.json_text(land.build(land.DEFAULT_PDF))
    assert land.DEFAULT_JSON.read_text(encoding="utf-8") == fresh


def test_every_check_passes_and_no_printed_callout_is_unaccounted(reported):
    assert all(reported["checks"].values())
    assert reported["callouts"]["unassigned"] == []


def test_the_source_hash_is_the_pdf_this_repository_ships(reported):
    """The JSON says which datasheet revision it was measured from; if the file
    beside it is replaced, the geometry no longer describes that document."""
    pdf = ROOT / reported["source"]["pdf"]
    assert hashlib.sha256(pdf.read_bytes()).hexdigest() == reported["source"]["sha256"]
    assert reported["source"]["revision"] == "2.3, 2022-07-21"


def test_the_pinout_is_the_one_the_symbol_models(reported):
    pinout = reported["pinout"]
    assert pinout["drain_pins"] == [5, 6, 7, 8]
    assert pinout["gate_pin"] == 4
    assert pinout["source_pins"] == [1, 2, 3]
    assert pinout["quoted"] == {"drain": "Drain Pin 5-8", "gate": "Gate Pin 4",
                                "source": "Source Pin 1-3"}


def test_every_named_pad_is_a_symbol_pin_and_the_rest_are_stencils(reported):
    named = [p for p in reported["pads"] if p["number"]]
    unnamed = [p for p in reported["pads"] if not p["number"]]
    assert {p["number"] for p in named} == set("12345678")
    assert all(p["layers"] == ["F.Cu"] for p in named)
    assert all(p["layers"] in (["F.Mask"], ["F.Paste"]) for p in unnamed)
    # One pad per pin, plus repeat lands: the drain base repeats 5, the source
    # bar repeats 1, and 2/3 ride on the bar's fingers.
    assert len(named) == 10
    assert len(unnamed) == 3 + 15


def test_each_finger_runs_into_its_base_so_the_copper_is_one_piece(reported):
    """The lands themselves are contiguous; the *pads* overlap on purpose.

    A pad number repeated across two copper rectangles is one land only while
    the rectangles touch.  The digitised lands meet edge to edge, so each
    finger's pad is pushed into the base by ``pad_overlap_mm`` -- otherwise a
    rounding in a CAD importer would leave pins 6-8 on floating copper that DRC
    reports as unconnected.
    """
    pads, overlap = reported["pads"], reported["pad_overlap_mm"]
    for base_kind, finger_kind in (("drain_base", "drain_lead"),
                                   ("source_bar", "source_lead")):
        base = next(p for p in pads if p["kind"] == base_kind)
        fingers = [p for p in pads if p["kind"] == finger_kind]
        assert len(fingers) >= 3
        for finger in fingers:
            dx, dy = _intersection(base["rect"], finger["rect"])
            assert abs(dx - overlap) < 1e-9, finger
            assert dy > 0.0, finger


def test_the_mask_is_each_land_grown_by_the_printed_expansion(reported):
    """The grey region has four straight sides and no notch, so the opening is
    the land's bounding box plus 0.05 -- not each finger grown separately."""
    copper, by = reported["copper"], reported["mask_expansion_mm"]
    lands = {
        "drain": [copper["drain_base"]] + [f["rect"] for f in copper["drain_fingers"]],
        "source": [copper["source_bar"]] + [f["rect"] for f in copper["source_fingers"]],
        "gate": [copper["gate"]],
    }
    drawn = {r["kind"]: r["drawn"] for r in reported["results"]["drawn_mask"]}
    for kind, rects in lands.items():
        expected = _grow(_union(rects), by)
        assert kind in drawn, kind
        assert all(abs(a - b) < land.TOL_MM for a, b in zip(drawn[kind], expected)), kind


def test_every_pad_is_inside_the_courtyard_and_the_courtyard_clears_the_copper(reported):
    x0, y0, x1, y1 = reported["courtyard"]
    for pad in reported["pads"]:
        px0, py0, px1, py1 = pad["rect"]
        assert x0 <= px0 and px1 <= x1 and y0 <= py0 and py1 <= y1, pad
    xs = [v for pad in reported["pads"] if pad["number"] for v in (pad["rect"][0], pad["rect"][2])]
    assert x1 - max(xs) > 0.2 and min(xs) - x0 > 0.2


def test_the_stencil_is_smaller_than_the_lands_it_serves(reported):
    """Paste is a transfer efficiency question, not a geometry identity: the
    measured ratio has to stay well under 1, and the tool reports it."""
    results = reported["results"]
    assert 0.5 < results["paste_fraction"] < 1.0
    assert results["paste_area_mm2"] < results["copper_area_mm2"]
    assert max(results["residuals_mm"].values()) <= land.TOL_MM
