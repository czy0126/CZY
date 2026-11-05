"""Tests for the routed fast-overcurrent module board.

The schematic tests (``test_make_fast_oc_eco.py``) say the circuit is right;
these say the circuit reached copper.  A board is only a deliverable here if
the router connected every pad pair and kicad-cli then found nothing -- the two
statements are independent, because a router that never placed the netlist also
reports "0 unconnected".

Run:
    python -m pytest tools/test_make_fast_oc_pcb.py -q
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import make_fast_oc_pcb as board

OUT = board.OUT


@pytest.fixture(scope="module")
def placed() -> list:
    return board.placement()


@pytest.fixture(scope="module")
def result(placed):
    return board.route(placed)


@pytest.fixture(scope="module")
def drc() -> dict:
    return json.loads((OUT / "drc.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- placement
def test_every_part_with_a_footprint_is_placed_exactly_once(placed):
    refs = [p.ref for p in placed]
    assert len(refs) == len(set(refs))
    expected = {p.ref for p in board.eco.parts() if p.footprint}
    assert set(refs) == expected


def test_every_part_stays_inside_the_board_outline(placed):
    for p in placed:
        x0, y0, x1, y1 = p.rect
        assert x0 >= 0 and y0 >= 0, p.ref
        assert x1 <= board.BOARD_W_MM and y1 <= board.BOARD_D_MM, p.ref


# ---------------------------------------------------------------- routing
def test_the_router_connects_every_net(result):
    assert result.unrouted == []
    assert result.connections_made == result.connections_attempted


def test_the_escape_reserve_is_recorded_rather_than_only_commented(result):
    """The reserve is off here because it is wider than the gap it guards.

    Recording it in the report means the next reader does not have to find the
    comment to learn that this board routes with a different obstacle model
    than the SR validation board.
    """
    report = board.report(result=result)
    assert report["escape_reserve_mm"] == 0.0
    assert "0.40 mm reserve" in report["escape_reserve_note"]


# ---------------------------------------------------------------- DRC
def test_the_drc_report_is_clean(drc):
    assert drc["violations"] == []
    assert drc["unconnected_items"] == []
    assert drc["schematic_parity"] == []


def test_committed_drc_is_a_cached_report_bound_to_the_current_board():
    """Checkout mtime is nondeterministic: use exact board hash and schema.

    A zero cached DRC remains necessary but NOT sufficient: only running
    kicad-cli again in the CAD environment proves the current board passes.
    """
    import hashlib

    actual = json.loads((OUT / "drc.json").read_text(encoding="utf-8"))
    assert actual["source"] == board.BOARD
    assert not actual["violations"] and not actual["unconnected_items"]
    assert not actual["schematic_parity"]
    manifest = json.loads((board.FAB / "manifest.json").read_text())
    sha = hashlib.sha256((OUT / board.BOARD).read_bytes()).hexdigest()
    assert manifest["board_sha256"] == sha
    assert manifest["flags"]["fabrication_approved"] is False


def test_the_board_declares_mask_and_paste_layers():
    """kicad-cli plots only the layers this table lists and drops the rest
    without a word; a five-layer board then looks like a nine-layer one."""
    text = (OUT / board.BOARD).read_text(encoding="utf-8")
    table = text.split("(layers", 1)[1].split("\t(setup", 1)[0]
    for layer in ('"F.Mask"', '"B.Mask"', '"F.Paste"', '"B.Paste"', '"Edge.Cuts"'):
        assert layer in table, layer


def test_the_mounting_hole_label_is_hidden_because_it_had_no_room():
    """The hole courtyard puts the reference 4.9 mm above the hole centre and
    the holes are 5 mm from the edge, so the text lands outside a 38 mm board.
    Official KiCad mounting holes hide it for the same reason."""
    text = (OUT / board.BOARD).read_text(encoding="utf-8")
    for ref in ("H1", "H2", "H3", "H4"):
        start = text.index(f'(property "Reference" "{ref}"')
        assert "hide" in text[start:start + 200], ref


# ---------------------------------------------------------------- artefacts
def test_the_committed_board_is_what_the_table_produces(placed, result):
    assert (OUT / board.BOARD).read_text(encoding="utf-8") == board.board_file(
        placed, result)


def test_the_committed_report_is_current(result):
    on_disk = json.loads((OUT / board.REPORT).read_text(encoding="utf-8"))
    assert on_disk["connections_made"] == result.connections_made
    assert on_disk["unrouted"] == list(result.unrouted)


def test_every_net_name_in_the_board_comes_from_the_schematic():
    text = (OUT / board.BOARD).read_text(encoding="utf-8")
    names = set(re.findall(r'\t\(net \d+ "([^"]*)"\)', text))
    expected = {n for p in board.eco.parts() if p.footprint for n in p.nets.values()}
    assert names == expected | {""}


def test_one_generator_owns_the_project_file():
    """The schematic and the board share ``fast_oc.kicad_pro``.

    If the board generator emitted its own copy, whichever ran last would
    decide whether DRC enforces ``missing_courtyard`` -- a check KiCad ignores
    by default, so losing it makes a board with no courtyards look clean.
    """
    committed = (OUT / "fast_oc.kicad_pro").read_text(encoding="utf-8")
    assert committed == board.eco.project_file()
    assert '"missing_courtyard": "error"' in committed


def test_the_honesty_flags_stay_false(result):
    report = board.report(result=result)
    assert report["hardware_built"] is False
    assert report["fabrication_approved"] is False
    assert "NOT_HARDWARE" in report["evidence_level"]


# ---------------------------------------------------------------- fab package
def output_arg(cmd: list[str]) -> str:
    """The path after ``-o`` -- not the last argument, which is the board."""
    assert "-o" in cmd, cmd
    return cmd[cmd.index("-o") + 1]


def test_the_position_file_is_named_after_this_board():
    """Two packages unpacked side by side must not share a position file."""
    cmds = board.srpcb.fab_commands(Path("kicad-cli"), OUT / board.BOARD, board.FAB,
                                    prefix=board.POS_PREFIX)
    assert output_arg(cmds["position"]).endswith(f"{board.POS_PREFIX}-pos.csv")


def test_the_sr_board_keeps_its_own_position_filename_by_default():
    cmds = board.srpcb.fab_commands(Path("kicad-cli"), Path("b.kicad_pcb"), Path("out"))
    assert output_arg(cmds["position"]).endswith("sr_fault_validation-pos.csv")


@pytest.fixture(scope="module")
def manifest() -> dict:
    path = OUT / "fab/manifest.json"
    if not path.is_file():
        pytest.skip("fab/ has not been exported -- run --fab")
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_manifest_hashes_the_board_it_names(manifest):
    assert manifest["board"] == board.BOARD
    assert manifest["board_sha256"] == board.srpcb._sha256(OUT / board.BOARD)


def test_every_file_in_the_package_is_hashed_and_nothing_missing(manifest):
    """A file nobody hashed is a file nobody can tell was changed."""
    on_disk = {p.name for p in board.FAB.iterdir()
               if p.is_file() and p.name != "manifest.json"}
    assert {f["name"] for f in manifest["files"]} == on_disk
    for entry in manifest["files"]:
        path = board.FAB / entry["name"]
        assert entry["bytes"] == path.stat().st_size, entry["name"]
        assert entry["sha256"] == board.srpcb._sha256(path), entry["name"]


def test_the_package_reports_the_layers_it_actually_plotted(manifest):
    """kicad-cli drops an undeclared layer silently, so ask for both numbers."""
    assert manifest["plotted_layers"] == manifest["layers"]
    assert {"F.Mask", "B.Mask", "F.Paste", "B.Paste"} <= set(manifest["plotted_layers"])


def test_the_package_is_not_an_approval(manifest):
    assert manifest["flags"] == {"hardware_built": False,
                                 "fabrication_approved": False}
    assert any("not an approval" in line for line in manifest["what_this_is_not"])


def test_the_package_does_not_claim_a_conductor_rating(manifest):
    """No power path on this module: say so rather than leave the field blank."""
    assert manifest["current_rating"]["status"] == "NOT_RATED"
    assert manifest["current_rating"]["why"].strip()


def test_the_assembly_drawing_in_the_package_describes_this_board(manifest):
    text = (board.FAB / "assembly.svg").read_text(encoding="utf-8")
    assert "TLV3501 fast-overcurrent ECO module" in text
    assert "SR fault validation board" not in text
    assert f'width="{board.BOARD_W_MM:g}"' in text
