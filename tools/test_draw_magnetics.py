"""Tests for the magnetic manufacturing drawings.

The drawings are part of the deliverable, so the test checks that the labels the
inspection sheet refers to actually make it into the SVG files.
"""

from __future__ import annotations

from pathlib import Path

from draw_magnetics import draw_height_stack, draw_winding_stack


def test_winding_stack_svg_has_every_foil(tmp_path: Path) -> None:
    path = draw_winding_stack(tmp_path / "winding.svg")
    text = path.read_text(encoding="utf-8")
    for label in ("P1", "P2", "P3", "S_A", "S_B", "0.05", "1.10"):
        assert label in text
    assert path.stat().st_size > 1000


def test_height_stack_svg_shows_the_10mm_limit(tmp_path: Path) -> None:
    path = draw_height_stack(tmp_path / "height.svg")
    text = path.read_text(encoding="utf-8")
    for label in ("9.50", "9.94", "10.00", "ELP half", "I plate"):
        assert label in text
    assert path.stat().st_size > 1000
