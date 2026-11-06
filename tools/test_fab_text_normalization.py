"""KiCad on Windows emits CRLF while Git checks out fabrication text as LF.

The original two committed fab manifests hashed Windows originals, so all
Gerber/drill sizes and SHA256s mismatched the actual Git stored files.
This check makes identical bytes reproducible across Windows and Linux.
"""
from __future__ import annotations

import hashlib
import json

import pytest

import make_sr_fault_board_pcb as sr


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("name", ["x.gbl", "x.gbrjob", "x.drl", "x.csv"])
def test_canonicalizer_converts_windows_manufacturing_text_to_lf(tmp_path, name):
    p = tmp_path / name
    p.write_bytes(b"alpha\r\nbeta\r\n")
    assert sr.normalise_fab_text_line_endings(tmp_path) == [name]
    assert p.read_bytes() == b"alpha\nbeta\n"
    assert sr.normalise_fab_text_line_endings(tmp_path) == []


def test_binary_content_is_not_silently_mangled_as_gerber(tmp_path):
    item = tmp_path / "x.gbl"
    item.write_bytes(b"G04 note\r\n\x00invalid\r\n")
    with pytest.raises(ValueError, match="binary content"):
        sr.normalise_fab_text_line_endings(tmp_path)
    assert item.read_bytes() == b"G04 note\r\n\x00invalid\r\n"


@pytest.mark.parametrize("board", ["sr_fault_validation", "fast_oc"])
def test_actual_committed_manufacturing_bytes_match_every_single_manifest_hash(board):
    fab = sr.ROOT / "pcb" / board / "fab"
    report = json.loads((fab / "manifest.json").read_text(encoding="utf-8"))
    assert report["flags"] == {
        "hardware_built": False, "fabrication_approved": False,
    }
    physical = {p.name for p in fab.iterdir() if p.is_file() and p.name != "manifest.json"}
    listed = [entry["name"] for entry in report["files"]]
    assert set(listed) == physical
    assert len(listed) == len(set(listed)) == 13
    for entry in report["files"]:
        file = fab / entry["name"]
        assert file.stat().st_size == entry["bytes"], entry["name"]
        assert _sha(file) == entry["sha256"], entry["name"]
        if file.suffix in sr.FAB_TEXT_SUFFIXES:
            assert b"\r\n" not in file.read_bytes(), entry["name"]
    pcb = sr.ROOT / "pcb" / board / f"{board}.kicad_pcb"
    assert _sha(pcb) == report["board_sha256"]


def test_documentation_index_matches_both_real_packages():
    index = json.loads((sr.ROOT / "pcb/manufacturing/index.json").read_text())
    for row in index["boards"]:
        if not row.get("manifest"):
            continue
        assert row["status"] == "FAB_PACKAGE_PRESENT"
        assert row["manifest_sha256"] == _sha(sr.ROOT / row["manifest"])
        assert row["board_sha256"] == _sha(sr.ROOT / row["board"])
        assert row["schematic_sha256"] == _sha(sr.ROOT / row["schematic"])
        assert row["flags"]["fabrication_approved"] is False
