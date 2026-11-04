"""Tests for the per-device magnetics supplier RFQ package.

The claims worth locking are not "the generator ran".  They are:

* the six sheets exist and stay separate -- T1-T4, Lr and the CT -- because the
  roadmap asks for them separately and a merged sheet hides which part has no
  mechanical definition yet;
* the logical terminals are the same 24 the rest of the vendor workflow uses,
  so an RFQ cannot quietly invent a seventh transformer terminal;
* the numbers are recomputed here from the source JSONs, not read back out of
  the sheets;
* the fields this repository cannot answer say UNKNOWN and are repeated in the
  open-items list -- an omitted field is the failure mode this file exists to
  prevent.

Run:
    python -m pytest tools/test_magnetics_rfq_package.py -q
"""

from __future__ import annotations

import json

import pytest

import magnetics_rfq_package as pkg

MAG = pkg.MAG
BOM = pkg.BOM


def devices() -> dict[str, dict]:
    return {d["ref"]: d for d in pkg.devices()}


@pytest.fixture(scope="module")
def devs() -> dict[str, dict]:
    return devices()


def find(dev: dict, section: str, label: str) -> dict:
    for item in dev[section]:
        if item["label"] == label:
            return item
    raise AssertionError(f"{dev['ref']}: no row {label!r} in {section}")


# ---------------------------------------------------------------- structure
def test_one_sheet_per_device_and_nothing_merged(devs):
    assert list(devs) == ["T1", "T2", "T3", "T4", "Lr", "CT"]
    kinds = {ref: d["kind"] for ref, d in devs.items()}
    assert kinds["Lr"] == "RESONANT_INDUCTOR"
    assert kinds["CT"] == "CURRENT_TRANSFORMER_4_TERMINAL"
    assert len({kinds[f"T{i}"] for i in range(1, 5)}) == 1


def test_every_section_is_present_and_non_empty(devs):
    for dev in devs.values():
        for key, _ in pkg.SECTIONS:
            assert dev[key], (dev["ref"], key)


def test_every_row_carries_a_source(devs):
    for dev in devs.values():
        for key, _ in pkg.SECTIONS:
            for item in dev[key]:
                assert item["source"].strip(), (dev["ref"], key, item["label"])


def test_the_roadmap_ten_fields_are_all_covered(devs):
    """Roadmap deliverable 3 lists ten things each sheet must carry."""
    labels = " ".join(
        item["label"] for dev in devs.values() for key, _ in pkg.SECTIONS for item in dev[key]
    )
    for needle in ("气隙", "匝比", "磁密", "故障峰值", "温度",
                   "损耗", "绝缘", "高度", "公差", "端子图"):
        assert needle in labels, needle


# ---------------------------------------------------------------- terminals
def test_transformer_and_ct_terminals_are_the_same_24_the_vendor_workflow_uses(devs):
    request = json.loads((pkg.HW / "vendor_terminal_request.json").read_text(encoding="utf-8"))
    expected = {
        d["ref"]: {(p["logical_terminal"], p["required_circuit_net"], p["dot_convention_expected"])
                   for p in d["pins"]}
        for d in request["devices"]
    }
    for ref in ("T1", "T2", "T3", "T4", "CT"):
        got = {(r["label"], r["value"], r["dot"]) for r in devs[ref]["terminals"]}
        assert got == expected[ref], ref
    assert sum(len(devs[r]["terminals"]) for r in ("T1", "T2", "T3", "T4", "CT")) == 24


def test_the_centre_tap_is_not_a_dot_to_dot_joint(devs):
    ctap = find(devs["T1"], "terminals", "CTAP")
    assert ctap["dot"] == "S_A_DOT_AND_S_B_NON_DOT"
    assert ctap["value"] == "VOUT"


def test_the_free_standing_inductor_has_two_terminals_from_the_board_netlist(devs):
    nets = {r["label"]: r["value"] for r in devs["Lr"]["terminals"]}
    assert nets == {"N1": "CT_LR", "N2": "PRI_T1"}


def test_the_ct_sheet_says_the_two_pad_footprint_is_invalid(devs):
    text = pkg.render(devs["CT"])
    assert "2 pad" in text and "无效" in text


# ---------------------------------------------------------------- arithmetic
def test_the_transformer_al_is_derived_from_lm_and_turns_not_quoted(devs):
    for i in range(1, 5):
        al = find(devs[f"T{i}"], "inductance", "目标 AL")
        assert al["value"] == pytest.approx(10e-6 / 3**2 * 1e9)


def test_the_transformer_gap_is_a_process_target_from_al_not_a_fixed_number(devs):
    dev = devs["T1"]
    assert "按 AL 磨" in find(dev, "inductance", "气隙加工口径")["value"]
    window = find(dev, "inductance", "气隙窗口")["value"]
    assert "0.112" in window and "0.126" in window


def test_the_transformer_copper_loss_is_the_four_set_total_divided_by_four(devs):
    mag = json.loads((MAG / "magnetics_design.json").read_text(encoding="utf-8"))
    per_set = mag["copper_100a"]["total_w"] / 4.0
    assert find(devs["T1"], "loss", "铜损 @100 A")["value"] == pytest.approx(per_set)
    assert find(devs["T1"], "loss", "合计 @100 A")["value"] == pytest.approx(
        per_set + mag["core_loss_w_per_set_50v"])


def test_the_transformer_flux_is_not_the_inductor_rule(devs):
    """Roadmap: L*I/(N*A) screens Lr; it must not decide transformer saturation."""
    rule = find(devs["T1"], "waveform", "磁通判据")["value"]
    assert "电压积分" in rule
    assert "L*I/(N*Ae)" in rule


def test_the_inductor_al_and_gap_come_from_the_three_turn_candidate():
    lr = json.loads((BOM / "lr_design.json").read_text(encoding="utf-8"))
    three = next(c for c in lr["candidates"] if c["turns"] == 3)
    dev = devices()["Lr"]
    assert find(dev, "inductance", "目标 AL")["value"] == pytest.approx(
        lr["tank"]["total_target_h"] / 9 * 1e9)
    assert find(dev, "inductance", "气隙（由目标 AL 算）")["value"] == pytest.approx(three["gap_mm"])
    assert find(dev, "inductance", "饱和电流 Isat")["value"] == pytest.approx(three["isat_a"])


def test_the_inductor_fault_current_is_above_the_rated_peak(devs):
    dev = devs["Lr"]
    rated = find(dev, "currents", "稳态峰值 @100 A")["value"]
    worst = find(dev, "currents", "故障峰值（外置件取下限）")["value"]
    rfq = find(dev, "currents", "询价设计电流")["value"]
    assert rated < worst < rfq
    assert rfq == pytest.approx(101.26 * 1.20, rel=1e-4)


def _policy() -> dict:
    path = pkg.POWER / "d1_staged_target_policy.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _stage(stage_id: str) -> dict:
    return next(s for s in _policy()["stages"] if s["id"] == stage_id)


def test_the_height_limits_come_from_the_policy_and_not_from_a_literal(devs):
    """The sheet used to print 10 mm for every device while noting that D1 was
    16 mm.  A quoted limit that disagrees with the policy asks the supplier for
    a part the project no longer wants."""
    d1 = _stage("D1_100A")["height_limit_mm"]
    d3 = _stage("D3_THIN")["height_limit_mm"]
    assert d1 != d3            # the two stages really do differ
    for ref in ("T1", "Lr"):
        assert find(devs[ref], "mechanical", "整机限值（D1_100A）")["value"] == pytest.approx(d1)
        assert find(devs[ref], "mechanical", "整机限值（D3_THIN）")["value"] == pytest.approx(d3)
    assert find(devs["CT"], "mechanical", "整机限值（D1_100A）")["value"] == pytest.approx(d1)


def test_the_preferred_core_is_the_one_the_policy_names(devs):
    assert pkg.preferred_core(pkg.D1) == _stage("D1_100A")["preferred_magnetic_core"]
    assert find(devs["Lr"], "mechanical", "现行首选套件")["value"] == pkg.preferred_core(pkg.D1)


def test_only_the_preferred_core_passes_both_screens():
    """Height alone picks two sets and flux alone picks four; the intersection
    is what the policy is buying, and it must be exactly one set."""
    candidates = pkg.lr_core_candidates()
    assert candidates["passing_both_screens"] == [pkg.preferred_core(pkg.D1)]
    elp32 = next(r for r in candidates["rows"] if r["id"] == "ELP32_I32")
    assert elp32["area_ok"] is False and elp32["height_ok"] is True
    elp43 = next(r for r in candidates["rows"] if r["id"] == "ELP43_I43")
    assert elp43["area_ok"] is True and elp43["height_ok"] is False


def test_the_candidate_rows_are_recomputed_from_the_design_package():
    stack = json.loads((MAG / "magnetics_design.json").read_text(encoding="utf-8"))["catalogue_core_stack"]
    by_id = {r["id"]: r for r in pkg.lr_core_candidates()["rows"]}
    assert set(by_id) == {r["id"] for r in stack["cores"]}
    for core in stack["cores"]:
        row = by_id[core["id"]]
        assert row["b3_t"] == pytest.approx(core["three_turn_fault_flux_t"])
        assert row["stack_worst_mm"] == pytest.approx(core["stack_flat_no_clamp_worst_mm"])
        assert row["left_mm"] == pytest.approx(core["d1_budget_left_for_tim_cold_plate_fasteners_mm"])


def test_the_sheet_keeps_the_superseded_verdict_and_says_why_it_expired(devs):
    """The 2026-11-03 screen rejected ELP38 for height against a 10 mm box.
    Deleting that line would erase the evidence that the basis moved."""
    row = find(devs["Lr"], "mechanical", "旧筛选表的口径")["value"]
    assert "10 mm" in row and "16 mm" in row
    assert "REJECT" in row and "高度" in row
    assert "0.23206" in row


def test_the_elp32_gap_does_not_travel_with_the_core_change(devs):
    """1.4443 mm of grinding is computed on ELP32's AL_ungapped.  Carrying it
    into an ELP38 quote would ask for a part nobody designed."""
    assert "作废" in find(devs["Lr"], "inductance", "气隙口径")["value"]
    assert find(devs["Lr"], "inductance", "首选套件气隙")["value"].startswith(pkg.UNKNOWN)


def test_the_open_items_ask_for_the_elp38_data_the_catalogue_lacks(devs):
    text = " ".join(devs["Lr"]["open_items"])
    for needle in ("AL_ungapped", "le", "Ve", "窗口净高", "L(I)", "100 °C"):
        assert needle in text, needle


def test_the_ct_secondary_current_is_the_primary_divided_by_the_turns_ratio(devs):
    ct = json.loads((BOM / "ct_design.json").read_text(encoding="utf-8"))
    expected = ct["measured"]["i_rms_a"] / ct["as_built"]["turns_ratio"]
    assert find(devs["CT"], "currents", "二次 RMS = 一次 / 匝比")["value"] == pytest.approx(expected)


def test_the_ct_burden_power_is_not_presented_as_ct_loss(devs):
    note = find(devs["CT"], "loss", "口径提醒")["value"]
    assert "不在 CT 本体" in note


# ---------------------------------------------------------------- honesty
def test_every_unknown_is_listed_and_counted(devs):
    index = pkg.index(list(devs.values()))
    for entry in index["devices"]:
        dev = devs[entry["ref"]]
        recount = sum(1 for key, _ in pkg.SECTIONS for item in dev[key]
                      if pkg.UNKNOWN in str(item["value"]))
        assert entry["unknown_count"] == recount
        assert entry["unknown_count"] > 0, entry["ref"]
        assert entry["open_item_count"] == len(dev["open_items"]) > 0


def test_the_ct_has_no_mechanical_definition_yet(devs):
    assert find(devs["CT"], "mechanical", "高度")["value"] == pkg.UNKNOWN


def test_no_sheet_claims_a_physical_pad_number(devs):
    for dev in devs.values():
        drawing = find(dev, "drawing", "物理端子图 / 焊盘号")["value"]
        assert drawing.startswith("NOT AVAILABLE"), dev["ref"]


def test_every_sheet_states_that_it_is_not_a_verified_article(devs):
    for dev in devs.values():
        assert pkg.STATUS in pkg.render(dev)


def test_the_index_says_which_sheets_are_which(devs):
    index = pkg.index(list(devs.values()))
    assert index["status"] == pkg.STATUS
    assert [d["sheet"] for d in index["devices"]] == [
        "rfq/T1.md", "rfq/T2.md", "rfq/T3.md", "rfq/T4.md", "rfq/Lr.md", "rfq/CT.md"]


# ---------------------------------------------------------------- artefacts
def test_the_committed_sheets_are_current(devs):
    for path, text in pkg.write(list(devs.values())):
        assert path.is_file(), path.name
        assert path.read_text(encoding="utf-8") == text, path.name
