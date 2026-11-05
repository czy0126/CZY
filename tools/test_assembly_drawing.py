"""Tests for the assembly / DNP drawing that travels with the fab package.

The position file tells a machine where to put a part; the drawing is what a
person reads to check orientation, which pads stay empty on purpose, and which
refs exist at all.  Neither substitutes for the other: a position file cannot
say "R47 is absent by design", and a drawing cannot be loaded by a placer.

Run:
    python -m pytest tools/test_assembly_drawing.py -q
"""

from __future__ import annotations

import re

import pytest

import assembly_drawing as draw
import make_sr_fault_board_pcb as board


@pytest.fixture(scope="module")
def placed() -> list:
    return board.placement()


@pytest.fixture(scope="module")
def table(placed) -> dict:
    return board._table()


@pytest.fixture(scope="module")
def svg(placed, table) -> str:
    return draw.svg(placed, table)


def part_groups(svg: str) -> dict[str, str]:
    """ref -> the opening ``<g>`` tag that carries it."""
    out = {}
    for match in re.finditer(r'<g class="part([^"]*)"[^>]*data-ref="([^"]+)"', svg):
        assert match.group(2) not in out, f"{match.group(2)} drawn twice"
        out[match.group(2)] = match.group(1)
    return out


# ---------------------------------------------------------------- coverage
def test_every_placed_part_appears_exactly_once(svg, placed):
    assert set(part_groups(svg)) == {p.ref for p in placed}


def test_the_parts_that_must_stay_empty_are_marked_dnp(svg, table):
    groups = part_groups(svg)
    dnp = {ref for ref, part in table.items() if part.dnp}
    assert dnp, "the board table has no DNP parts -- this test would prove nothing"
    marked = {ref for ref, cls in groups.items() if " dnp" in cls}
    assert marked == dnp


def test_a_part_that_gets_placed_is_never_marked_dnp(svg, table):
    groups = part_groups(svg)
    for ref, part in table.items():
        if not part.dnp:
            assert "dnp" not in groups[ref], ref


# ---------------------------------------------------------------- geometry
def test_the_drawing_is_one_to_one_in_millimetres(svg):
    """``width``/``height`` in mm is what makes a print measure true.

    kicad-cli's ``--scale 1`` export writes the same thing; a drawing that only
    carries a viewBox prints at whatever the reader's DPI happens to be.
    """
    assert f'width="{draw.PAGE_W_MM:g}mm"' in svg
    assert f'height="{draw.PAGE_H_MM:g}mm"' in svg
    assert f'viewBox="0 0 {draw.PAGE_W_MM:g} {draw.PAGE_H_MM:g}"' in svg


def test_every_part_is_drawn_at_its_placed_position(svg, placed):
    """The parts must land on the outline, not beside it."""
    for p in placed:
        x0, y0, _, _ = p.rect
        assert f'data-ref="{p.ref}"' in svg
        assert f'x="{x0 + draw.OFFSET_X_MM:g}"' in svg, p.ref
        assert f'y="{y0 + draw.OFFSET_Y_MM:g}"' in svg, p.ref


def test_the_board_outline_is_drawn_once_at_the_placed_size(svg):
    assert f'width="{draw.BOARD_W_MM:g}"' in svg.replace(f'width="{draw.PAGE_W_MM:g}mm"', "")
    assert svg.count('class="outline"') == 1


# ---------------------------------------------------------------- content
def test_the_drawing_names_every_dnp_part_in_a_table(svg, table):
    """A reader who cannot read the tiny on-board text must still find R47."""
    rows = re.findall(r'<text class="row dnp"[^>]*>([^<]*)</text>', svg)
    assert sorted(rows) == sorted(ref for ref, p in table.items() if p.dnp)


def test_the_drawing_says_what_it_is_not(svg):
    text = svg.lower()
    assert "not an approval" in text
    assert "hardware_built" in text and "fabrication_approved" in text


def test_the_drawing_is_deterministic(placed, table):
    assert draw.svg(placed, table) == draw.svg(placed, table)


def test_the_committed_drawing_is_current(svg):
    """The package carries a copy; a stale copy is worse than none, because it
    still looks like an instruction."""
    assert draw.OUT.is_file(), f"{draw.OUT} is missing -- run --fab"
    assert draw.OUT.read_text(encoding="utf-8") == svg


# ---------------------------------------------------------------- second board
def test_a_second_board_gets_its_own_title_and_outline_size(placed, table):
    """The sheet is reused, not copied: one code path draws every board."""
    w, d = 52.0, 38.0
    text = draw.svg(placed, table, title="Some other module", board_mm=(w, d))
    assert "Some other module" in text
    assert draw.DEFAULT_TITLE not in text
    assert f'class="outline" x="{(draw.PAGE_W_MM - w) / 2:g}"' in text
    assert f'width="{w:g}" height="{d:g}"' in text


def test_the_outline_stays_centred_when_the_board_size_changes(placed, table):
    """A left-anchored outline would push a narrow board into the page margin."""
    for w in (52.0, 132.0):
        text = draw.svg(placed, table, board_mm=(w, 38.0))
        assert f'x="{(draw.PAGE_W_MM - w) / 2:g}"' in text, w


def test_a_second_board_gets_its_own_document_title(placed, table):
    """The ``<title>`` element is what a screen reader announces and what a
    grep finds; a default left in place would name the SR board in another
    board's file even though the printed heading was changed."""
    text = draw.svg(placed, table, title="Some other module",
                    doc_title="Some other module -- assembly drawing")
    assert "Some other module -- assembly drawing</title>" in text
    assert "SR fault validation board" not in text


def test_the_title_is_escaped(placed, table):
    """A title with an ampersand must not make the SVG unparseable."""
    assert "A &amp; B" in draw.svg(placed, table, title="A & B")


def test_the_default_sheet_is_still_the_sr_board(placed, table):
    """Parameterising the header must not have moved the committed drawing."""
    assert draw.svg(placed, table) == draw.svg(
        placed, table, title=draw.DEFAULT_TITLE,
        board_mm=(board.BOARD_W_MM, board.BOARD_D_MM),
        footprint_note=draw.DEFAULT_FOOTPRINT_NOTE)
