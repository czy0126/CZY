"""Offline tests for source-backed magnetic screening and Maxwell fail-closed inputs."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import maxwell_magnetics_prescreen as screen  # noqa: E402
import maxwell_lr_from_step as runner  # noqa: E402


def test_prescreen_uses_repository_core_data_not_arbitrary_simulated_values():
    report = screen.report()
    assert report["maxwell_executed"] is False
    assert report["fab_release"] is False
    assert len(report["cases"]) == 4
    c = {(row["turns"], row["target_l_uh"]): row
         for row in report["cases"]}
    assert c[(2, 0.92)]["gap_analytic_mm"] == pytest.approx(1.031, abs=0.002)
    assert c[(2, 0.92)]["b_at_rfq_current_t"] == pytest.approx(0.291, abs=0.001)
    assert c[(2, 1.0)]["b_at_rfq_current_t"] > 0.31
    assert c[(3, 0.92)]["b_at_rfq_current_t"] < 0.20
    assert c[(3, 0.92)]["gap_inside_published_empirical_range"] is False
    assert c[(2, 0.92)]["gap_inside_published_empirical_range"] is True
    assert all(x["passes_flux_screen_at_fixed_l"] is False
               for x in c.values() if x["turns"] == 2)


def test_rfq_current_is_separate_from_physically_measured_fault_peak():
    report = screen.report()
    source = json.loads(screen.SOURCE.read_text("utf-8"))
    actual_deck = source["physical_peaks"]["cases"]["fault_lrmin_ride_through"]
    assert actual_deck["current_a"] == pytest.approx(104.17)
    assert report["rfq_current_a"] > actual_deck["current_a"]
    assert report["decisions"]["stop_rule"].startswith("Do not claim")


def test_maxwell_project_cannot_be_released_with_missing_cad_and_bh():
    cfg = json.loads(runner.CONFIG.read_text("utf-8"))
    item = runner.load_case(cfg, "ELP38_Lr_2turn_0920uH")
    problems = runner.blockers(cfg, item)
    assert any("STEP" in x for x in problems)
    assert any("BH" in x for x in problems)
    assert any("approval." in x for x in problems)
    assert cfg["hardware_fabrication_approved"] is False


def test_runner_rejects_fabrication_approved_true_even_when_checking_only():
    cfg = json.loads(runner.CONFIG.read_text("utf-8"))
    cfg = copy.deepcopy(cfg)
    cfg["hardware_fabrication_approved"] = True
    p = runner.blockers(cfg, runner.load_case(cfg, cfg["cases"][0]["id"]))
    assert "fabrication flag cannot be set by Maxwell recipe" in p


def test_material_bh_csv_must_be_monotonic_and_reach_screen_range(tmp_path):
    f = tmp_path / "n97.csv"
    f.write_text(
        "H_A_per_m,B_T\n0,0\n100,0.10\n200,0.15\n400,0.21\n"
        "600,0.27\n800,0.34\n", encoding="utf-8")
    assert runner.check_bh_csv(f) == []
    f.write_text("H_A_per_m,B_T\n0,0\n200,0.1\n100,0.2\n",
                 encoding="utf-8")
    assert runner.check_bh_csv(f)


def test_config_has_separate_cad_cases_and_all_currents():
    cfg = json.loads(runner.CONFIG.read_text("utf-8"))
    assert len(cfg["cases"]) == 4
    assert {x["turns"] for x in cfg["cases"]} == {2, 3}
    assert 121.515 in cfg["solved_currents_a"]
    assert 104.17 in cfg["solved_currents_a"]
    assert cfg["aedt_material_name"] == "N97_100C_BH_CONCEPT_REVIEWED"
    assert all(c["step_file"] is None for c in cfg["cases"])

def test_bh_input_is_accepted_in_pyaedt_h_then_b_units():
    rows = [
        {"H_A_per_m": "0", "B_T": "0"},
        {"H_A_per_m": "500", "B_T": "0.2"},
    ]
    assert runner.bh_pairs_for_pyaedt(rows) == [[0.0, 0.0], [500.0, 0.2]]


def test_bh_csv_requires_origin_valid_slope_and_2turn_field_range(tmp_path):
    f = tmp_path / "bh.csv"
    prefix = "H_A_per_m,B_T\n"
    # Data below a 2-turn RFQ flux estimate is not enough for a conclusion.
    f.write_text(prefix+"0,0\n100,0.01\n200,0.03\n300,0.11\n400,0.20\n500,0.29\n", encoding="utf-8")
    assert any("0.32T" in msg for msg in runner.check_bh_csv(f))
    # Nonphysical origin and negative differential permeability must fail.
    f.write_text(prefix+"0,0.005\n100,0.10\n200,0.2\n300,0.3\n400,0.33\n500,0.35\n", encoding="utf-8")
    assert any("begin" in msg for msg in runner.check_bh_csv(f))
    f.write_text(prefix+"0,0\n100,0.10\n200,0.20\n300,0.30\n400,0.30000001\n500,0.33\n", encoding="utf-8")
    assert any("mu0" in msg for msg in runner.check_bh_csv(f))

def test_maxwell_matrix_export_has_documented_txt_extension(tmp_path):
    """Maxwell3d.export_matrix does not support a CSV filename."""
    p = runner.matrix_export_path(tmp_path, 121.515)
    assert p.name == "matrix_121p515A.txt"
    assert p.suffix == ".txt"
    assert p.parent == tmp_path


def test_maxwell_inputs_pin_config_geometry_and_bh_bytes(tmp_path):
    cfg, step, bh = (tmp_path / name for name in ("contract.json", "geom.step", "curve.csv"))
    cfg.write_text('{"case": 1}', encoding="utf-8")
    step.write_text("ISO-10303-21; CONCEPT", encoding="utf-8")
    bh.write_text("H_A_per_m,B_T\\n0,0\\n", encoding="utf-8")
    original = runner.source_sha256_evidence(cfg, step, bh)
    assert set(original) == {"config_sha256", "step_sha256", "bh_sha256"}
    cfg.write_text('{"case": 2}', encoding="utf-8")
    assert original["config_sha256"] != runner.source_sha256_evidence(cfg, step, bh)["config_sha256"]
    assert original["step_sha256"] == runner.sha256(step)
