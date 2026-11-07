"""Tests for the native bias-cut ECO (design path, not hardware evidence)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import make_bias_cut_eco as eco

ROOT = Path(__file__).resolve().parent.parent


def by_ref(ref: str) -> list[eco.Part]:
    return [p for p in eco.parts() if p.ref == ref]


def one(ref: str, unit: int = 1) -> eco.Part:
    hits = [p for p in eco.parts() if p.ref == ref and p.unit == unit]
    assert len(hits) == 1, (ref, unit, len(hits))
    return hits[0]


# ---------------------------------------------------------------- logic
def test_truth_table_is_set_dominant_and_complete():
    rows = eco.truth_table()
    assert len(rows) == 32
    for row in rows:
        if row["fault"] or row["por"]:
            assert row["latched"] is True
            assert row["enable"] is False
        if row["latched"] is True:
            assert row["enable"] is False


def test_no_auto_reset_after_the_fault_clears():
    # fault gone, no POR, no RESET -> the previous latched state survives.
    for latched in (False, True):
        new, enable = eco.step(fault=False, permit=True, reset=False, por=False, latched=latched)
        assert new is latched
        assert enable is (not latched)


def test_reset_is_blocked_while_the_fault_is_present():
    new, enable = eco.step(fault=True, permit=True, reset=True, por=False, latched=True)
    assert new is True
    assert enable is False


def test_explicit_reset_with_permit_reenables():
    new, enable = eco.step(fault=False, permit=True, reset=True, por=False, latched=True)
    assert new is False
    assert enable is True


def test_permit_low_keeps_the_bias_off_even_after_reset():
    new, enable = eco.step(fault=False, permit=False, reset=True, por=False, latched=True)
    assert new is False
    assert enable is False


def test_power_on_sets_the_latch_even_with_reset_asserted():
    new, enable = eco.step(fault=False, permit=True, reset=True, por=True, latched=False)
    assert new is True
    assert enable is False


# ---------------------------------------------------------------- topology
def test_default_off_network_is_present():
    r50 = one("R50")
    assert r50.nets == {"1": "VDD_IN", "2": "BC_GATE"}
    assert one("R52").nets == {"1": "ENABLE", "2": "PGND"}
    assert one("R60").nets == {"1": "PERMIT", "2": "PGND"}
    # POR is high at power-up because C53 couples V5 into the POR node while
    # R56 discharges it to PGND.
    assert one("R56").nets == {"1": "POR", "2": "PGND"}
    assert one("C53").nets == {"1": "POR", "2": "V5_IND"}


def test_back_to_back_pmos_shares_the_drain():
    q50, q51 = one("Q50"), one("Q51")
    assert q50.nets["3"] == q51.nets["3"] == "VMID"
    assert q50.nets["2"] == "VDD_IN"
    assert q51.nets["2"] == "VDD_SR"
    assert q50.nets["1"] == q51.nets["1"] == "BC_GATE"


def test_gate_follower_only_conducts_when_vdd_sr_exceeds_vdd_in():
    # Q55 is a P-MOS source follower: gate at VDD_IN, source at VDD_SR, drain
    # at BC_FB.  Its channel is off while VDD_SR <= VDD_IN (Vgs = 0), so it
    # cannot inject into the gate and fight the enable pulldown; it only pulls
    # the gate up when VDD_SR is back-fed above VDD_IN.
    q55 = one("Q55")
    assert q55.nets == {"1": "VDD_IN", "2": "VDD_SR", "3": "BC_FB"}


def test_the_follower_drain_has_the_series_diode():
    # D50 sits between Q55's drain and the gate: cathode on BC_GATE.  It is what
    # stops Q55's body diode (anode = drain) from leaking gate -> VDD_SR in the
    # off state; the deck measured 13.3 V on a cut output without it.
    d50 = one("D50")
    assert d50.nets == {"1": "BC_GATE", "2": "BC_FB"}


def test_no_part_connects_vdd_sr_directly_to_the_gate():
    # A plain Schottky from VDD_SR to the gate is forward-biased in normal
    # operation: it fought the pulldown and held the pair at 14.44 V of 15 V.
    for part in eco.parts():
        nets = set(part.nets.values())
        assert nets != {"VDD_SR", "BC_GATE"}, part.ref


def test_no_two_pin_part_shorts_vdd_in_to_vdd_sr():
    for part in eco.parts():
        if len(part.nets) == 2:
            assert set(part.nets.values()) != {"VDD_IN", "VDD_SR"}, part.ref


def test_discharge_path_and_passive_bleed():
    assert one("R57").nets == {"1": "VDD_SR", "2": "VDD_DIS"}
    q54 = one("Q54")
    assert q54.nets == {"1": "ENABLE_N", "2": "PGND", "3": "VDD_DIS"}
    assert one("R58").nets == {"1": "VDD_SR", "2": "PGND"}
    assert one("C54").nets == {"1": "VDD_SR", "2": "PGND"}


def test_latch_clock_and_d_are_grounded():
    u51 = one("U51")
    assert u51.nets["3"] == "PGND"  # CLK
    assert u51.nets["5"] == "PGND"  # D
    assert u51.nets["6"] == "SET_LATCH"
    assert u51.nets["4"] == "RST_EFF"


def test_the_module_does_not_replace_the_crowbar():
    refs = {p.ref for p in eco.parts()}
    assert "Q41" not in refs
    assert "R44" not in refs
    assert "Q41 + R44" in eco.integration()["preserved_fast_path"]


def test_spare_cmos_units_have_grounded_inputs_and_open_outputs():
    by_unit = {(p.ref, p.unit): p for p in eco.parts()}
    for ref, units in (("U50", (3, 4, 5, 6)), ("U51", (2,)),
                       ("U52", (3, 4)), ("U53", (2, 3, 4))):
        for unit in units:
            part = by_unit[(ref, unit)]
            for pin, net in part.nets.items():
                if net == eco.NC:
                    assert pin in {"4", "6", "8", "10", "11", "12", "13"}, (ref, unit, pin)
                else:
                    assert net == "PGND", (ref, unit, pin, net)


# ---------------------------------------------------------------- parts
def test_every_mpn_is_traceable_or_explicitly_to_select():
    for part in eco.parts():
        if part.ref.startswith("#"):
            continue
        if part.mpn:
            source = ROOT / part.mpn_source
            assert source.is_file(), (part.ref, part.mpn_source)
            text = source.read_text(encoding="utf-8", errors="ignore")
            assert part.mpn in text, (part.ref, part.mpn, part.mpn_source)
        else:
            assert part.mpn_source == "TO_SELECT", part.ref


def test_pmos_is_to_select_with_written_requirements():
    for ref in ("Q50", "Q51", "Q55"):
        part = one(ref)
        assert part.mpn == ""
        assert part.mpn_source == "TO_SELECT"
    selection = eco.pmos_selection()
    assert selection["mpn"] == "TO_SELECT"
    assert selection["requirements"]["vds_min_v"] >= 30
    assert selection["requirements"]["id_pulsed_min_a"] >= 3
    # Q55 only works as a follower if the part is logic level.
    assert selection["requirements"]["vgs_th_abs_max_v"] <= 2.5


def test_footprints_are_not_empty_for_physical_parts():
    for part in eco.parts():
        if part.ref.startswith("#"):
            continue
        assert part.footprint, part.ref


def test_units_merge_to_one_physical_row_per_reference():
    physical = eco.physical_components(eco.parts())
    refs = [p.ref for p in physical]
    assert len(refs) == len(set(refs))
    assert {p.ref for p in physical} >= {"U50", "U51", "U52", "U53", "Q50", "Q51"}


def test_part_table_matches_the_native_symbols():
    symbols = eco.build_symbols()
    ps = [eco.snap(p) for p in eco.parts()]
    eco.validate(ps, symbols)  # raises on any pin/net mismatch or coincident tip


# ---------------------------------------------------------------- report
def test_report_does_not_claim_qualification():
    report = eco.report(eco.parts())
    assert report["hardware_qualified"] is False
    assert report["thermal_qualified"] is False
    assert report["hardware_built"] is False
    # A behavioural run may (and now does) be recorded; hardware may not.
    assert report["simulation_status"] in {"NOT_RECORDED", "RUN", "STALE"}
    assert report["simulation"]["evidence_level"] == "BEHAVIOURAL_SIMULATION_NOT_HARDWARE"
    assert len(report["requirements"]) == 11
    assert {r["requirement"] for r in report["requirements"]} >= {
        "always-on 15 V input", "controlled SR bias output",
        "independent 5 V fault latch", "PERMIT interface", "default off",
        "reverse blocking", "local capacitor discharge",
        "preserve the fast REG crowbar", "explicit reset",
    }


def test_report_open_items_include_the_hardware_gaps():
    items = " ".join(eco.report(eco.parts())["open_items"])
    assert "TO_SELECT" in items
    assert "no hardware" in items
    assert "H5" in items


def test_recorded_run_passes_every_check():
    path = eco.SIM_RUN
    if not path.is_file():
        pytest.skip("sim_run.json has not been recorded here")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] == "RUN"
    assert payload["all_checks_pass"] is True, [
        c for c in payload["checks"] if not c["ok"]]
    assert payload["evidence_level"] == "BEHAVIOURAL_SIMULATION_NOT_HARDWARE"
    names = {c["name"] for c in payload["checks"]}
    assert {"default_off_v", "startup_max_v", "after_fault_v", "held_off_v",
            "reverse_current_a", "bias_cut_time_s", "discharge_time_s"} <= names


def test_recorded_run_belongs_to_the_current_decks():
    # If the deck is edited after a run, the numbers in report.json would
    # describe a different circuit; the deck hash makes that visible.
    path = eco.SIM_RUN
    if not path.is_file():
        pytest.skip("sim_run.json has not been recorded here")
    payload = json.loads(path.read_text(encoding="utf-8"))
    for name, build in eco.DECK_FILES.items():
        assert payload["deck_sha256"][name] == eco.sha256(build()), name
    assert eco.sim_run()["status"] == "RUN"


def test_committed_report_flags_match_the_generator():
    path = eco.OUT / "report.json"
    if not path.is_file():
        pytest.skip("report.json has not been generated here")
    committed = json.loads(path.read_text(encoding="utf-8"))
    fresh = eco.report(eco.parts())
    for key in ("hardware_qualified", "thermal_qualified", "hardware_built",
                "simulation_status", "requirements", "pmos_selection"):
        assert committed[key] == fresh[key], key


# ---------------------------------------------------------------- decks
def test_sequence_deck_measures_the_required_points():
    text = eco.sequence_deck()
    for name in ("vdd_sr_default_off", "vdd_sr_enabled", "vdd_sr_after_fault",
                 "vdd_sr_held_off", "vdd_sr_recovered", "latched_after_fault",
                 "enable_after_fault", "vdd_sr_startup_max", "t_bias_cut",
                 "t_discharge"):
        assert name in text
    assert ".tran" in text
    assert "B_L 0 LATCHED" in text  # the latch is behavioural, not a device model
    # The model has no gate capacitance of its own; the timing is only real
    # because this lumped element is there.  Both uic state elements must carry
    # their steady-state initial value, or the deck invents a power-up pulse:
    # CG at VDD_IN (gate held by R50) and C_L at 5 V (POR has set the latch).
    assert "CG BC_GATE 0 60p ic=15" in text
    assert "C_L LATCHED 0 1n ic=5" in text


def test_reverse_deck_forces_vdd_sr_and_measures_vdd_in_current():
    text = eco.reverse_deck()
    assert "MIN I(V1)" in text
    assert "VREV_SRC 0 18" in text
    assert "SREV" in text


def test_log_parser_reads_both_printed_measurement_forms():
    # `.meas STAT(...)` prints "name: STAT(x)=value"; `.meas TRIG/TARG` prints
    # "name=value FROM a TO b" with no colon.  The second form was silently
    # dropped once, and the two delays looked like they had never been measured.
    text = (
        "vdd_sr_enabled: MIN(V(VDD_SR) )=14.9984836717 FROM 0.012 TO 0.014\n"
        "t_bias_cut=1.33573975912e-05 FROM 0.0150005 TO 0.0150138573976\n"
        "t_discharge=-0.000232712698501 FROM 0.0150005 TO 0.0147672873\n"
        "Total elapsed time: 7.682 seconds.\n"
        "tnom = 27\n"
    )
    got = eco.parse_meas(text)
    assert got["vdd_sr_enabled"] == pytest.approx(14.9984836717)
    assert got["t_bias_cut"] == pytest.approx(1.33573975912e-05)
    assert got["t_discharge"] == pytest.approx(-0.000232712698501)
    # Header lines are not measurements, even when they look like assignments.
    assert "tnom" not in got


# ---------------------------------------------------------------- netlist
def test_netlist_has_the_required_connections():
    path = eco.OUT / "bias_cut_eco.net"
    if not path.is_file():
        pytest.skip("netlist has not been exported here")
    nodes = eco.netlist_nodes(path.read_text(encoding="utf-8"))
    assert nodes["VMID"] == {("Q50", "3"), ("Q51", "3")}
    assert {("Q50", "2"), ("Q51", "2")} <= nodes["VDD_IN"] | nodes["VDD_SR"]
    assert nodes["BC_FB"] == {("Q55", "3"), ("D50", "2")}
    assert ("D50", "1") in nodes["BC_GATE"]
    assert ("Q55", "2") in nodes["VDD_SR"]
    assert ("Q55", "1") in nodes["VDD_IN"]
    assert ("R57", "2") in nodes["VDD_DIS"] and ("Q54", "3") in nodes["VDD_DIS"]
    assert ("U51", "6") in nodes["SET_LATCH"] and ("U53", "3") in nodes["SET_LATCH"]
    assert ("U51", "4") in nodes["RST_EFF"] and ("U52", "3") in nodes["RST_EFF"]
