"""Guard the single D1 documentation entry against old status/route reintroduction.

Documentation-only regression: does NOT claim native CAD, Maxwell, bench or
fabrication success. Changes to old technical analyses remain possible, but
must not silently replace the one current operational handoff.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "docs/D1_CURRENT.md"
DECISIONS = ROOT / "docs/D1_DECISIONS.md"
INDEX = ROOT / "docs/D1_REFERENCE_INDEX.md"
TOP = ROOT / "README.md"
PR_TEMPLATE = ROOT / ".github/PULL_REQUEST_TEMPLATE.md"
G1_README = ROOT / "hardware/dcx_main/g1/README.md"
ARCHIVED = ROOT / "docs/archive/README_D1_branch_before_single_entry_2026-11-10.md"
DOCS = (TOP, CURRENT, DECISIONS, INDEX, PR_TEMPLATE)


def test_navigation_links_resolve_locally_without_hidden_parallel_roadmaps():
    for file in DOCS:
        assert file.is_file(), file
        doc = file.read_text(encoding="utf-8")
        for match in re.finditer(r"\]\(([^)]+)\)", doc):
            url = match.group(1).strip().split("#", 1)[0]
            if not url or re.match(r"^(?:https?://|mailto:|data:)", url):
                continue
            target = (file.parent / url).resolve()
            assert target.is_relative_to(ROOT), (file, url)
            assert target.exists(), (file, url)


def test_one_small_entry_and_full_historical_preservation():
    top = TOP.read_text(encoding="utf-8")
    archive = ARCHIVED.read_text(encoding="utf-8")
    assert top.count("docs/D1_CURRENT.md") == 1
    assert top.count("docs/D1_DECISIONS.md") == 1
    assert len(top) < 4500  # no more append-only timestamped audit reports
    assert len(archive) > 14000
    assert "历史存档" in archive
    assert "D1_CURRENT" in INDEX.read_text(encoding="utf-8")


def test_current_docs_follow_actual_g1_not_the_old_main_snapshot():
    now = CURRENT.read_text(encoding="utf-8")
    d = DECISIONS.read_text(encoding="utf-8")
    p = PR_TEMPLATE.read_text(encoding="utf-8")
    gate = json.loads((ROOT / "hardware/dcx_main/d1_fabrication_gate.json").read_text(encoding="utf-8"))
    active = json.loads((ROOT / "hardware/dcx_main/g1/g1_native_inventory_bom_gate.json").read_text(encoding="utf-8"))
    actual = json.loads((ROOT / "hardware/dcx_main/g1/g1_schematic_pcb_alignment.json").read_text(encoding="utf-8"))
    neck = json.loads((ROOT / "hardware/dcx_main/g1/g1_100a_copper_neck_screen.json").read_text(encoding="utf-8"))
    assert gate["status"] == "NOT_FOR_FAB" and gate["release_approved"] is False
    assert active["manufacturer_target_conflicts"] == 38
    assert active["r8_capture_designator"] == "R6"
    assert active["original_r8_in_bom"] is False
    assert active["original_r8_in_pcb"] is False
    assert actual["native_schematic_component_count"] == 83
    assert actual["native_pcb_component_count"] == 77
    assert actual["native_pcb_anonymous_magnetic_pad_count"] == 24
    assert actual["native_drc"]["netlist_errors"] == 1
    assert neck["fabrication_approved"] is False
    assert "38" in now and "R6" in now and "206" in now
    assert "9 条" in now and "24 个" in now
    assert "NOT_FOR_FAB" in now and "NOT_FOR_FAB" in d
    assert "真实" in p and "改前" in p


def test_g1_readme_starts_with_real_nine_route_handoff_not_six_route_preview():
    first = G1_README.read_text(encoding="utf-8").split(
        "## 形成过程记录（历史", 1)[0]
    assert "9 条" in first
    assert "尚未真正写入" in first
    assert "apply_lr_signal_stubs.py --apply" in first
    assert "206 Connection" in first
    assert "NOT_FOR_FAB" in first
