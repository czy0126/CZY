"""The G1 plan view is review evidence, so it has to name what it is evidence *of*.

Two board files now exist: the baseline ``dcx_main_board_g1.eprj2`` (no copper,
no routing, no DRC) and the routed candidate ``..._driver_eco.eprj2`` /
``..._driver_route.eprj2`` (50 readback lines and 13 vias, plus a native DRC
raw).  A drawing
captioned only "NO COPPER, NO ROUTING, NO DRC" therefore reads as a statement
about *the* board rather than about the baseline file, and a stale copy of the
drawing looks exactly like a current one.  These tests pin the caption to the
file it was dumped from and make the committed SVG a render of the committed
dump.
"""
import importlib.util
from pathlib import Path


G1 = Path(__file__).resolve().parents[1] / "hardware/dcx_main/g1"
spec = importlib.util.spec_from_file_location("g1layout", G1 / "make_g1_layout_svg.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def dump() -> dict:
    import json
    return json.loads((G1 / "g1_pads.json").read_text(encoding="utf-8"))


def test_the_caption_names_the_board_file_and_its_no_copper_claim():
    svg = g.render(dump())
    assert g.BOARD == "dcx_main_board_g1.eprj2"
    assert g.BOARD in svg
    # The claim is about this baseline file, not about the routed candidates.
    assert "NO COPPER, NO ROUTING, NO DRC" in svg
    assert "NOT FOR FAB" in svg


def test_every_tbd_zone_gets_exactly_one_label():
    data = dump()
    svg = g.render(data)
    labels = [z["ref"] for z in data["tbd_zones"]]
    assert labels == ["CT", "T1", "T2", "T3", "T4"]
    for ref in labels:
        assert svg.count(f">TBD {ref}<") == 1
    assert svg.count(">TBD ") == len(labels)


def test_lr_is_a_placed_part_and_not_a_core_body_zone():
    """Lr sits on its own native footprint; only the six transformer/CT bodies are TBD."""
    data = dump()
    assert "Lr" in {c["ref"] for c in data["components"]}
    svg = g.render(data)
    assert "TBD Lr" not in svg


def test_the_committed_svg_is_what_the_committed_dump_renders(tmp_path):
    out = tmp_path / "g1_layout.svg"
    g.main(out)
    assert out.read_text(encoding="utf-8") == (G1 / "g1_layout.svg").read_text(encoding="utf-8")
