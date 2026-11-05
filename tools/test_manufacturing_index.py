"""Tests for the bench-board manufacturing directory.

The index says which packages exist and whether they still match the board they
claim to describe.  It must not be able to say a package is present when the
board underneath has moved, and it must not read a missing approval flag as a
granted one -- those two failures are what make a directory page dangerous.

Run:
    python -m pytest tools/test_manufacturing_index.py -q
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import manufacturing_index as index


@pytest.fixture(scope="module")
def data() -> dict:
    return index.build()


def spec_for(board_dir: str, *, fab: str | None = None) -> dict:
    """A spec in the same shape as ``BOARDS``, rooted at ``board_dir``."""
    base = Path(board_dir)
    return {
        "id": base.name,
        "title": "temp",
        "what": "temp",
        "generator": "python -c pass",
        "schematic": str(base / "b.kicad_sch"),
        "board": str(base / "b.kicad_pcb"),
        "fab": fab if fab is not None else str(base / "fab"),
    }


# ---------------------------------------------------------------- coverage
def test_the_index_covers_exactly_the_declared_boards(data):
    assert [row["id"] for row in data["boards"]] == [s["id"] for s in index.BOARDS]
    assert len({row["id"] for row in data["boards"]}) == len(index.BOARDS)


def test_every_board_has_a_status_from_the_closed_set(data):
    allowed = {"FAB_PACKAGE_PRESENT", "FAB_PACKAGE_STALE", "NO_FAB_PACKAGE",
               "SCHEMATIC_ONLY"}
    for row in data["boards"]:
        assert row["status"] in allowed, row["id"]


def test_the_two_packages_are_present_and_match_their_boards(data):
    """Recompute the comparison here rather than trusting the field it wrote."""
    packages = [row for row in data["boards"] if row["status"].startswith("FAB_PACKAGE")]
    assert {row["id"] for row in packages} == {"sr_fault_validation", "fast_oc"}
    for row in packages:
        assert row["status"] == "FAB_PACKAGE_PRESENT", row.get("not_fabricable_because")
        assert row["manifest_board_sha256"] == row["board_sha256"], row["id"]
        listed = {f["name"] for f in json.loads(
            (index.ROOT / row["manifest"]).read_text(encoding="utf-8"))["files"]}
        on_disk = {p.name for p in (index.ROOT / row["fab"]).iterdir()
                   if p.is_file() and p.name != "manifest.json"}
        assert listed == on_disk, row["id"]


def test_the_schematic_only_boards_say_why(data):
    for row in data["boards"]:
        if row["status"] == "SCHEMATIC_ONLY":
            assert row["not_fabricable_because"], row["id"]


# ---------------------------------------------------------------- staleness
def test_a_manifest_hashed_from_another_board_is_stale(tmp_path):
    """The board moves, the manifest does not: the package describes a board
    that no longer exists and must not read as present."""
    (tmp_path / "b.kicad_sch").write_text("sch", encoding="utf-8")
    (tmp_path / "b.kicad_pcb").write_text("board", encoding="utf-8")
    fab = tmp_path / "fab"
    fab.mkdir()
    (fab / "a.gbr").write_text("gerber", encoding="utf-8")
    (fab / "manifest.json").write_text(json.dumps({
        "board_sha256": "0" * 64,
        "files": [{"name": "a.gbr"}],
        "layers": ["F.Cu"], "plotted_layers": ["F.Cu"],
    }), encoding="utf-8")
    row = index.entry(spec_for(str(tmp_path)))
    assert row["status"] == "FAB_PACKAGE_STALE"
    assert any("different board" in why for why in row["not_fabricable_because"])


def test_a_file_nobody_listed_makes_the_package_stale(tmp_path):
    (tmp_path / "b.kicad_sch").write_text("sch", encoding="utf-8")
    (tmp_path / "b.kicad_pcb").write_text("board", encoding="utf-8")
    fab = tmp_path / "fab"
    fab.mkdir()
    (fab / "a.gbr").write_text("gerber", encoding="utf-8")
    (fab / "stowaway.gbr").write_text("not hashed", encoding="utf-8")
    (fab / "manifest.json").write_text(json.dumps({
        "board_sha256": index._sha256(tmp_path / "b.kicad_pcb"),
        "files": [{"name": "a.gbr"}],
        "layers": ["F.Cu"], "plotted_layers": ["F.Cu"],
    }), encoding="utf-8")
    row = index.entry(spec_for(str(tmp_path)))
    assert row["status"] == "FAB_PACKAGE_STALE"
    assert "stowaway.gbr" in " ".join(row["not_fabricable_because"])


def test_a_board_without_a_package_is_not_reported_as_present(tmp_path):
    (tmp_path / "b.kicad_sch").write_text("sch", encoding="utf-8")
    (tmp_path / "b.kicad_pcb").write_text("board", encoding="utf-8")
    row = index.entry(spec_for(str(tmp_path)))
    assert row["status"] == "NO_FAB_PACKAGE"
    assert "does not exist" in row["not_fabricable_because"][0]


# ---------------------------------------------------------------- flags
def test_a_missing_flag_reads_as_false():
    """Absence is exactly how an unapproved package slips through as approved."""
    assert index._flags({}) == {"hardware_built": False, "fabrication_approved": False}
    assert index._flags({"flags": {"hardware_built": True}}) == {
        "hardware_built": True, "fabrication_approved": False}


def test_no_board_in_the_index_is_approved_or_built(data):
    for row in data["boards"]:
        if "flags" in row:
            assert row["flags"] == {"hardware_built": False,
                                    "fabrication_approved": False}, row["id"]


# ---------------------------------------------------------------- artefacts
def test_the_committed_files_are_current(data):
    for path, text in index.write(data):
        assert path.is_file(), f"{path} is missing -- run --write"
        assert path.read_text(encoding="utf-8") == text, f"{path} is stale -- run --write"


def test_the_readme_names_every_board_and_its_rebuild_command(data):
    text = index.render(data)
    for row in data["boards"]:
        assert f"`{row['id']}`" in text, row["id"]
        assert row["generator"] in text, row["id"]


def test_the_directory_points_at_the_main_board_page(data):
    """The one board that cannot be fabricated has to be findable from here."""
    assert "hardware/dcx_main/remaining_dependencies.md" in data["not_here"]
    assert "remaining_dependencies.md" in index.render(data)
