"""Native EasyEDA pilot footprint sourced from KEMET 2026 Density-B X-case land.

Verifies actual serialized native CAD, not metadata or a drawing placeholder.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
G2 = ROOT / "hardware/dcx_main/g2"
sys.path.insert(0, str(G2))
import plan_t530_72_oem_density_b as P

SOURCE = G2 / "T530X477M006ATE004_X1_DENSITY_B_NATIVE_FOOTPRINT_NOT_FOR_FAB.efoo"
RECORD = G2 / "t530_x1_density_b_library_pilot.json"


def primitives():
    rows = []
    for line in SOURCE.read_text(encoding="utf8").splitlines():
        if "||" not in line:
            continue
        head, data = line.split("||", 1)
        rows.append((json.loads(head), json.loads(data.rstrip("|"))))
    return rows


def test_native_library_two_real_pads_and_no_number_duplicates():
    pads = [d for h, d in primitives() if h["type"] == "PAD"]
    assert len(pads) == 2
    assert {p["num"] for p in pads} == {"1", "2"}
    assert all(p["layerId"] == 1 and p["defaultPad"]["padType"] == "RECT"
               for p in pads)
    assert all(p["netName"] == "" for p in pads)  # no net in reusable footprint
    assert all(p["hole"] is None for p in pads)


def test_real_footprint_matches_manufacturer_derived_land_geometry():
    pad = {d["num"]: d for h, d in primitives() if h["type"] == "PAD"}
    for n, polarity in (("1", 1), ("2", -1)):
        d = pad[n]
        assert abs(d["centerX"] * .0254 - polarity * P.DX) < .001
        assert abs(d["centerY"] * .0254) < .001
        assert abs(d["defaultPad"]["width"] * .0254 - P.L) < .001
        assert abs(d["defaultPad"]["height"] * .0254 - P.W) < .001
    assert P.S == 3.87 and P.V1 == 9.12 and P.V2 == 5.10


def test_native_footprint_evidence_is_source_hash_locked_not_release():
    report = json.loads(RECORD.read_text(encoding="utf8"))
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == report["footprint_sha256"]
    assert report["footprint_uuid"] == "c9bdf53e779d4dd6a2eee1e6cecd4462"
    assert report["library_uuid"] == "G1_R34_REC10K_v3_TEST"
    assert report["native_editor_save_acknowledged"] is True
    assert report["native_footprint_saved_and_reopened"] is False
    assert report["native_import_into_main_pcb"] is False
    assert report["72_native_components_instantiated"] is False
    assert report["library_courtyard_and_polarity_review_approved"] is False
    assert report["fabrication_approved"] is False


def test_positive_and_negative_land_numbering_matches_existing_72_site_plan():
    assert P.OUT.exists()
    plan = json.loads(P.OUT.read_text(encoding="utf8"))
    assert plan["placement_count"] == 72
    for part in plan["placement"]:
        by_pin = {p["pin"]: p for p in part["pads"]}
        assert by_pin["P"]["net"] == "VOUT"
        assert by_pin["N"]["net"] == "PGND"
        assert by_pin["P"]["centre_mm"][0] > part["centre_mm"][0]
        assert by_pin["N"]["centre_mm"][0] < part["centre_mm"][0]
