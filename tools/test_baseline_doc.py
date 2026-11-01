"""Lock the current-candidate baseline document to the JSONs it quotes.

design/v3/当前候选基线_2026-11-01.md is the single place that says "these are
the numbers we design to".  Every number in it is produced by a tool, so this
test recomputes the number from the JSON and requires the formatted value to
appear in the markdown.  Editing a tool and regenerating the JSON without
updating the baseline turns the suite red -- which is the point.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "design/v3/当前候选基线_2026-11-01.md"
COUT = ROOT / "design/v3/bom/cout_bank.json"
LR = ROOT / "design/v3/bom/lr_design.json"
CONNECTOR = ROOT / "design/v3/bom/connector_budget.json"
LEDGER = ROOT / "design/v3/stage_f/energy_ledger_100a.json"
LEDGER_ALIGNED = ROOT / "design/v3/stage_f/energy_ledger_100a_phase_aligned.json"
MAGNETICS = ROOT / "design/v3/magnetics/magnetics_design.json"
OP = ROOT / "design/v3/magnetics/operating_point_100a.json"
CT = ROOT / "design/v3/bom/ct_design.json"
LEDGER_LOG = ROOT / "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ledger.log"

CLASSES = ("SIM_MEASURED", "ENG_ESTIMATE", "HW_MEASURED", "UNVERIFIED")
DESIGN_MARKERS = ("设计定义", "设计规则", "设计决定", "设计约束")


def text() -> str:
    return DOC.read_text(encoding="utf-8")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def freeze_rows() -> list[list[str]]:
    """The rows of the '## 1 冻结量' table, split into cells."""
    body = text().split("## 1 冻结量", 1)[1].split("## 2", 1)[0]
    rows: list[list[str]] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if all(set(cell) <= set("-: ") for cell in cells):
            continue
        rows.append(cells)
    return rows[1:]                       # drop the header row


def test_every_frozen_row_states_an_evidence_class():
    rows = freeze_rows()
    assert len(rows) >= 20, "the freeze table lost rows"
    for cells in rows:
        assert len(cells) == 4, f"row is not item/value/class/evidence: {cells}"
        declared = cells[2]
        known = any(f"`{label}`" in declared for label in CLASSES) or any(
            mark in declared for mark in DESIGN_MARKERS
        )
        assert known, f"no evidence class in {cells[0]!r}: {declared!r}"


def test_no_hardware_measurement_is_claimed_before_first_article():
    assert "目前 0 条" in text()
    assert "HW_MEASURED" not in " ".join(" ".join(r) for r in freeze_rows())


def test_cout_counts_and_bank_match_cout_bank_json():
    bank = load(COUT)["banks"][0]
    doc = text()
    assert bank["part"] in doc
    assert f"{bank['n']} ×" in doc
    assert f"{bank['bank_capacitance_f'] * 1e3:.2f} mF" in doc
    assert f"容量 {bank['counts']['capacitance']} 只" in doc
    assert f"RMS {bank['counts']['rms']} 只" in doc
    assert f"ESR {bank['counts']['esr']} 只" in doc


def test_lr_selection_and_fault_peaks_match_lr_design_json():
    data = load(LR)
    chosen = next(c for c in data["candidates"] if c["passes_slow_oc"])
    doc = text()
    assert f"{chosen['turns']} 匝" in doc
    assert f"{chosen['gap_mm']:.3f} mm" in doc
    assert f"{chosen['isat_a']:.1f} A" in doc
    for value, digits in (("steady", 2), ("startup", 2),
                          ("fault_fast_oc_13us", 0), ("fault_slow_oc_51us", 2)):
        assert f"{data['peaks_a'][value]:.{digits}f}" in doc, value


def test_the_physical_peaks_and_the_turn_conclusion_are_both_quoted():
    """The measured fault peaks are what eliminated 2 turns; a baseline that
    only keeps the frozen-deck 65/73.7 A table would still read as a choice."""
    data = load(LR)["physical_peaks"]
    doc = text()
    assert data["min_turns_all"] == 3
    for name, case in data["cases"].items():
        assert f"{case['current_a']:.2f} A" in doc, name
    worst = max(data["cases"].values(), key=lambda c: c["flux_t_at_3"])
    assert f"{worst['flux_t_at_3']:.3f} T" in doc
    assert f"{data['cases']['fault_phys_ride_through']['flux_t_at_2']:.3f} T" in doc


def test_height_worst_cases_use_the_maximum_not_the_nominal():
    height = load(MAGNETICS)["height"]
    doc = text()
    pocket = height["pocket_0.5mm_no_clamp"]
    flat = height["flat_no_pocket"]
    clamp = height["with_0.5mm_clamp"]
    assert f"{pocket['worst_case_m'] * 1e3:.2f} mm" in doc
    assert f"{pocket['margin_m'] * 1e3:.2f} mm" in doc
    assert f"{flat['worst_case_m'] * 1e3:.2f} mm" in doc
    assert f"{clamp['worst_case_m'] * 1e3:.2f} mm" in doc
    assert clamp["worst_case_m"] > 0.010, "the clamp case must still fail the 10 mm limit"


def test_output_path_joint_limit_matches_connector_budget_json():
    limit = load(CONNECTOR)["joint_limit"]
    doc = text()
    assert f"{limit['bar_ohm'] * 1e6:.1f} µΩ" in doc
    assert f"{limit['per_joint_ohm'] * 1e6:.1f} µΩ" in doc


def test_energy_balance_matches_the_measured_ledger():
    data = load(LEDGER)
    doc = text()
    losses = data["losses"]
    pair1 = losses["sr_channel_body_pair1"]["w"]
    x4 = losses["sr_channel_body_x4"]["w"]
    ct = losses["ct_bridge_diodes"]["w"] + losses["ct_burden_resistor"]["w"]
    assert f"{pair1:.3f} W/对" in doc
    assert f"{x4:.3f} W" in doc
    assert f"{ct:.3f} W" in doc
    assert f"{data['port']['pin_minus_pout_w']:.3f} W" in doc
    assert f"{data['loss_total_w']:.3f} W" in doc
    assert f"{abs(data['balance']['loss_residual_w']):.3f} W" in doc
    assert f"{data['window']['start_s'] * 1e6:.2f}" in doc
    assert f"{data['window']['end_s'] * 1e6:.2f}" in doc
    assert f"{data['window']['periods']} 个门极周期" in doc
    assert f"{data['outside_port']['driver_output_w']:.3f} W" in doc


def test_the_phase_aligned_window_is_quoted_from_its_own_json():
    """§2.3 quotes the 133-period window; every number there must be read off the
    aligned JSON.  Hand-copying the 16-period figures would leave the two
    readings indistinguishable in the document, which is the one thing this
    section exists to prevent."""
    if not LEDGER_ALIGNED.exists():
        pytest.skip("the aligned-window ledger has not been generated")
    data = load(LEDGER_ALIGNED)
    doc = text()
    window = data["window"]
    balance = data["balance"]
    avg = balance["period_averaged"]
    align = balance["resolution"]["phase_alignment"]
    assert f"{window['periods']} 个门极周期" in doc
    assert f"{window['span_s'] * 1e6:.1f} µs" in doc
    assert f"{align['aligned_periods']} 个门极周期" in doc
    assert f"{balance['closure_residual_w']:+.3f} W" in doc
    assert f"{avg['closure_residual_w']:+.3f} W" in doc
    assert f"{avg['sem_w']:.3f} W" in doc
    assert f"`{balance['closure_status']}`" in doc


def test_ripple_quotes_the_22_period_value_not_the_2_period_one():
    """38.27 mVpp is 10 us; the 22-period figure is 49.73 mVpp and is the one
    the same deck reports for the steady state.  The short window misses the
    beat envelope and must not be quoted alone."""
    pp_mv = load(OP)["vout_pp_mv"]
    doc = text()
    assert f"{pp_mv:.1f} mVpp" in doc
    short = short_window_ripple_mv()
    assert f"{short:.1f} mVpp" in doc
    # the short number appears only with its limitation written next to it
    assert "漏掉慢包络" in doc
    assert abs(pp_mv - 50.0) < 1.0, "the 50 mVpp target has no real margin; say so"


def test_the_physical_bank_ripple_is_quoted_with_its_configuration():
    """The frozen 100 A deck runs `Cout=4 mF`, but the frozen *design* is the
    15 x 470 uF = 7.05 mF bank.  The design-conforming ripple is therefore the
    `cout7m` run, and it must appear next to the 4 mF number rather than
    replacing it silently."""
    bank = load(ROOT / "design/v3/magnetics/operating_point_100a_cout7m.json")
    untrimmed = load(ROOT / "design/v3/magnetics/operating_point_100a_phys.json")
    doc = text()
    assert f"{bank['vout_pp_mv']:.1f} mVpp" in doc
    assert f"{untrimmed['vout_pp_mv']:.1f} mVpp" in doc
    assert f"{bank['iout_from_v_a']:.1f} A" in doc
    assert bank["periods"] == 22 and untrimmed["periods"] == 22
    assert bank["vout_pp_mv"] < load(OP)["vout_pp_mv"], (
        "the physical bank is larger than the 4 mF deck, so its ripple must be smaller")


def short_window_ripple_mv() -> float:
    line = next(
        ln for ln in LEDGER_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        if ln.startswith("vout_rip:")
    )
    match = re.search(r"PP\(V\(out\)\s*\)=([0-9.eE+-]+)", line)
    assert match, line
    return float(match.group(1)) * 1e3


def test_output_envelope_matches_magnetics_design_json():
    out = load(MAGNETICS)["output_100a"]
    doc = text()
    for vin in ("46v", "48v", "50v"):
        assert f"{out[vin]['vout_v']:.3f}" in doc, vin
    assert f"{load(MAGNETICS)['output_100a']['vin_for_200w']:.2f} V" in doc


def test_efficiency_rows_say_which_losses_are_included():
    data = load(MAGNETICS)["loss_at_100a"]
    port = load(LEDGER)["port"]
    doc = text()
    port_eff = port["pout_w"] / port["pin_source_w"] * 100
    assert f"{port_eff:.2f}" in doc
    assert "deck 不含磁芯损耗" in doc
    assert f"{data['p_core_w']:.3f} W" in doc
    assert f"{data['efficiency_at_converter_pct']:.2f}" in doc
    assert f"{data['efficiency_pct']:.2f}" in doc


def test_ct_trip_threshold_matches_ct_design_json():
    assert f"{load(CT)['as_built']['trip_peak_a']:.1f} A" in text()


def test_ci_commands_in_the_document_are_the_ones_that_exist():
    doc = text()
    assert "python -m pytest tools -q" in doc
    assert "python tools/ci_check.py" in doc
    assert (ROOT / "tools/ci_check.py").exists()
    assert (ROOT / ".github/workflows/ci.yml").exists()


@pytest.mark.parametrize("label", CLASSES)
def test_each_evidence_class_is_defined(label):
    assert f"`{label}`" in text()
