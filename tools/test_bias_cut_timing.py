"""Independent checks of the T3 timing module, not a device or thermal qualification.

The things worth guarding here are the three that can silently go wrong:

* an anchor drifting away from the vendored datasheet it claims to come from;
* a deck losing the measurement that a ``checks()`` entry reads (which would
  turn a failure into a ``KeyError`` at record time, or worse, a stale number);
* the PMOS polarity regressing to the form that pinned Q50 on.
"""
from __future__ import annotations

import json
import math
import re

import pytest

import bias_cut_timing as t
import ltspice_windows_evidence as transport


def _text(rel: str) -> str:
    return (t.ROOT / rel).read_text(encoding="utf-8", errors="replace")


def _float_lines(text: str, start: int, count: int) -> list[float]:
    """First ``count`` numbers in ``text`` after offset ``start``."""
    found: list[float] = []
    for token in re.findall(r"-?\d+(?:\.\d+)?", text[start:]):
        found.append(float(token))
        if len(found) == count:
            break
    return found


# ---------------------------------------------------------------- datasheet anchors
def test_the_crcw_anchors_are_in_the_vendored_datasheet() -> None:
    text = _text(t.CRCW_DS)
    assert "Rth ≤ 110 K/W" in text          # the rating's own condition
    assert f"{t.P70_W} W" in text                 # rated at 70 C
    assert f"{t.T_FILM_MAX_C:.0f} °C" in text
    assert f"{t.U_MAX_V:.0f} V" in text
    assert "single pulse" in text and "continuous pulse" in text
    assert t.RTH_BOARD_MAX_K_PER_W == 110.0
    assert t.P70_W == 0.75


def test_the_inverter_delay_is_the_5v_max_column() -> None:
    text = _text("references/datasheets/cd4069ub.txt")
    start = text.index("Propagation delay time")
    # MIN/TYP/MAX for VDD = 5 V, 10 V, 15 V; the max column is the last one.
    five = _float_lines(text, start, 3)
    assert five == pytest.approx([5.0, 55.0, 110.0])
    assert t.T_CD4069_MAX_S == pytest.approx(110e-9)


def test_the_or_delay_is_the_5v_max_column() -> None:
    text = _text("references/datasheets/cd4071b.txt")
    line = next(row for row in text.splitlines()
                if row.lstrip().startswith("Propagation Delay Time"))
    assert _float_lines(line, 0, 3) == pytest.approx([5.0, 125.0, 250.0])
    assert t.T_CD4071_MAX_S == pytest.approx(250e-9)


def test_the_latch_delay_is_the_slower_set_reset_direction() -> None:
    text = _text("references/datasheets/cd4013b.txt")
    # tPLH set/reset to Q: 150 typ / 300 max.  tPHL set/reset to Q: 200 / 400.
    set_rise = text.index("tPLH\nSet to Q or reset to Q")
    set_fall = text.index("tPHL\nSet to Q or reset to Q")
    assert _float_lines(text, set_rise, 3)[-1] == 300.0
    assert _float_lines(text, set_fall, 3) == pytest.approx([5.0, 200.0, 400.0])
    # The clear path is the slow one, and that is the number the deck uses.
    assert t.T_CD4013_SET_TO_Q_MAX_S == pytest.approx(400e-9)


def test_the_and_gate_proxy_is_flagged_because_the_source_publishes_no_max() -> None:
    text = _text("references/datasheets/cd4081b.txt")
    assert "THIS DOCUMENT PUBLISHES NO PROPAGATION DELAY MAXIMUM." in text
    assert t.T_CD4081_MAX_S is None
    assert t.T_CD4081_PROXY_S == pytest.approx(t.T_CD4071_MAX_S)
    model = t.record()["model"]["logic_delays"]
    assert model["cd4081b_max_s"] is None
    assert "proxy" in model["cd4081b_proxy_note"]


# ---------------------------------------------------------------- cut delay
def test_the_cut_delay_is_the_rc_closed_form() -> None:
    row = t.cut_delay(15.0)
    tau = t.R50_OHM * t.DMP_CISS_MAX_F
    assert row["tau_s"] == pytest.approx(tau)
    assert row["delay_to_vth_s"] == pytest.approx(tau * math.log(15.0 / t.Q50_VTH_ABS_V))
    assert row["delay_to_13v5_s"] == pytest.approx(
        tau * math.log(15.0 / (15.0 - t.CUT_GATE_TARGET_V)))
    # The threshold crossing always comes before the comparable 13.5 V point.
    assert row["delay_to_vth_s"] < row["delay_to_13v5_s"]


def test_more_gate_capacitance_is_slower_and_the_placeholder_understated_it() -> None:
    small = t.cut_delay(15.0, ciss_f=t.DMP_CISS_TYP_F)
    big = t.cut_delay(15.0, ciss_f=t.DMP_CISS_MAX_F)
    assert big["delay_to_13v5_s"] > small["delay_to_13v5_s"]
    assert big["delay_to_13v5_s"] / small["delay_to_13v5_s"] == pytest.approx(
        t.DMP_CISS_MAX_F / t.DMP_CISS_TYP_F)
    # Rev A's placeholder was 60 pF through 100k.  The part's Ciss is ~17x the
    # placeholder, but R50 dropped 10x, so the *delay* is only ~1.7x Rev A's.
    rng = t.cut_delay_range()
    placeholder = t.cut_delay(15.0, ciss_f=60e-12, r50_ohm=100e3)
    assert rng["placeholder_rev_a_60pf_100k_s"] == pytest.approx(placeholder["delay_to_13v5_s"])
    assert rng["ratio_to_placeholder"] == pytest.approx(
        rng["rows"]["15.00V"]["delay_to_13v5_s"] / placeholder["delay_to_13v5_s"])
    assert rng["ratio_to_placeholder"] == pytest.approx(1.68, abs=0.01)
    assert t.DMP_CISS_MAX_F / 60e-12 == pytest.approx(16.8)
    # Slower than Rev A's *measured* 13.36 us despite the 10x smaller resistor.
    assert rng["rows"]["15.00V"]["delay_to_13v5_s"] > 1.5 * rng["rev_a_measured_s"]


def test_the_worst_cut_delay_is_the_lowest_input_voltage() -> None:
    rows = t.cut_delay_range()["rows"]
    delays = [r["delay_to_13v5_s"] for r in rows.values()]
    assert max(delays) == pytest.approx(rows[f"{t.VDD_IN_MIN_V:.2f}V"]["delay_to_13v5_s"])
    assert len(rows) == 3


def test_an_input_that_cannot_reach_the_target_has_no_cut_time() -> None:
    assert math.isinf(t.cut_delay(13.0, target_v=13.5)["delay_to_13v5_s"])
    assert math.isinf(t.cut_delay(t.Q50_VTH_ABS_V)["delay_to_vth_s"])


# ---------------------------------------------------------------- R59
def test_the_inrush_peak_and_energy_follow_the_divider() -> None:
    row = t.r59_inrush()
    r_max = t.R59_OHM * (1 + t.R59_TOL)
    r_total = r_max + t.Q50_RDS_OHM
    assert row["i_peak_a"] == pytest.approx(t.VDD_IN_MAX_V / r_total)
    assert row["peak_w"] == pytest.approx(row["i_peak_a"] ** 2 * r_max)
    v_charge = t.VDD_IN_MAX_V * r_max / r_total
    assert row["energy_j"] == pytest.approx(0.5 * t.C54_F * v_charge ** 2 * r_max / r_total)
    assert row["equivalent_width_s"] == pytest.approx(row["energy_j"] / row["peak_w"])


def test_the_pulse_limit_interpolates_in_log_log_space() -> None:
    table = t.PULSE_LIMIT_1206_W
    assert t._limit_at(table, 1e-6) == pytest.approx(table[1e-4])       # below the curve
    assert t._limit_at(table, 1.0) == pytest.approx(table[1e-2])       # above the curve
    assert t._limit_at(table, 1e-4) == pytest.approx(table[1e-4])
    # The geometric mean of the widths maps to the geometric mean of the limits.
    mid = t._limit_at(table, math.sqrt(1e-4 * 1e-3))
    assert mid == pytest.approx(math.sqrt(table[1e-4] * table[1e-3]))
    # Reading the curve upward with width is wrong: longer pulses allow less power.
    assert t._limit_at(table, 1e-3) < t._limit_at(table, 1e-4)


def test_the_assessment_compares_the_same_quantity_on_both_sides() -> None:
    row = t.r59_assessment(steady_current_a=0.03885, events_per_s=2.0)
    assert row["pulse_margin_x"] == pytest.approx(row["pulse_limit_w"] / row["inrush"]["peak_w"])
    assert row["average_w_at_event_rate"] == pytest.approx(2.0 * row["inrush"]["energy_j"])
    assert row["events_per_s_for_p70"] == pytest.approx(t.P70_W / row["inrush"]["energy_j"])
    assert row["steady_w"] == pytest.approx(0.03885 ** 2 * t.R59_OHM * (1 + t.R59_TOL))
    assert row["steady_rise_k"] == pytest.approx(row["steady_w"] * t.RTH_BOARD_MAX_K_PER_W)
    # Both margins are claimed against the curve and against the 0402 floor.
    assert row["pulse_margin_floor_x"] < row["pulse_margin_x"]
    assert row["single_pulse_pass"] is True
    assert row["voltage_pass"] is True
    assert row["steady_pass"] is True
    assert row["continuous_pulse_pass_at_1_per_s"] is True


# ---------------------------------------------------------------- logs and decks
def test_parse_meas_reads_both_printed_forms() -> None:
    text = "\n".join((
        "vdd_sr_max: MAX(V(VDD_SR))=13.2619581223 FROM 0 TO 0.025",
        "t_cut_nominal: INTEG((if(V(BC_GATE)<13.5,1,0)) )=2.41833462416e-05 FROM 0.015 TO 0.0155",
        "delayed=1.5e-3 FROM 0.005 TO 0.012",
        "File: nominal.cir",
        "Date: Fri Nov 07 09:12:44 2026",
    ))
    assert t.parse_meas(text) == pytest.approx({
        "vdd_sr_max": 13.2619581223,
        "t_cut_nominal": 2.41833462416e-05,
        "delayed": 1.5e-3,
    })


class _Recorder(dict):
    """Returns 0.0 for any key and remembers which ones were asked for."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: set[tuple[str, str]] = set()
        self._case = ""

    def __getitem__(self, case: str) -> "_RecorderCase":
        return _RecorderCase(self, case)


class _RecorderCase(dict):
    def __init__(self, parent: _Recorder, case: str) -> None:
        super().__init__()
        self._parent = parent
        self._case = case

    def __getitem__(self, key: str) -> float:
        self._parent.seen.add((self._case, key))
        return 0.0


def _deck_measurements(name: str) -> set[str]:
    return set(re.findall(r"^\.meas\s+TRAN\s+(\w+)", t.deck(name), re.MULTILINE))


def test_every_measurement_a_check_reads_is_produced_by_its_deck() -> None:
    recorder = _Recorder()
    t.checks(recorder)  # type: ignore[arg-type]
    assert recorder.seen
    for case, key in recorder.seen:
        assert key in _deck_measurements(case), f"{case}.cir does not measure {key}"


def test_a_missing_measurement_is_an_error_not_a_pass() -> None:
    with pytest.raises(KeyError):
        t.checks({"nominal": {}})  # type: ignore[dict-item]


def test_the_decks_keep_the_pmos_polarity_that_was_the_bug() -> None:
    for name in t.cases():
        text = t.deck(name)
        assert "S50 VDD_IN VMID VDD_IN BC_GATE SWPM" in text
        assert ".model SWPM SW(Ron=0.2 Roff=1Meg Vt=2.0 Vh=0.2)" in text
        assert "Vt=-2" not in text
        # The control is sourced from the supply, so a negative Vt would pin it on.
        assert "Vt=-" not in text


def test_the_decks_start_from_a_cleared_latch() -> None:
    for name in t.cases():
        text = t.deck(name)
        assert "C_L LATCHED 0 100p ic=0" in text
        assert "ic=5" not in text
        assert ".tran" in text and "uic" in text
        assert "V(BC_GATE)" in text


# ---------------------------------------------------------------- drawn control
def _netlist() -> dict[str, set[tuple[str, str]]]:
    """Net -> {(ref, pin)} from the generated Rev B netlist."""
    path = t.ROOT / "pcb" / "bias_cut_revision_b" / "bias_cut_revision_b.net"
    text = path.read_text(encoding="utf-8")
    block = text[text.index("(nets"):]
    nets: dict[str, set[tuple[str, str]]] = {}
    pattern = re.compile(
        r'\(net\s*\(code "\d+"\)\s*\(name "([^"]+)"\)(.*?)'
        r'(?=\n\t\t\(net\s*\(code|\n\t\)\s*\n?\)?\s*$)', re.S)
    for name, body in pattern.findall(block):
        nets[name] = set(re.findall(
            r'\(ref "([^"]+)"\)\s*\(pin "([^"]+)"\)', body))
    return nets


def test_the_drawn_control_is_the_same_chain_the_deck_simulates() -> None:
    """The deck must model the schematic, not an invented ENABLE.

    Pin map, Rev B drawing: U50 = CD4069, U51 = CD4013, U52 = CD4081,
    U53 = CD4071.  SET = FLT_H OR POR, RST_EFF = RESET AND /SET,
    ENABLE_RAW = PERMIT AND /LATCHED, ENABLE = ENABLE_RAW AND /SET.
    """
    nets = _netlist()
    assert ("U53", "3") in nets["/SET_LATCH"]       # OR output
    assert ("U51", "6") in nets["/SET_LATCH"]       # latch SET
    assert ("U53", "2") in nets["/POR"]
    assert ("U53", "1") in nets["/FLT_H"]
    assert ("U50", "6") in nets["/SET_N"] and ("U52", "2") in nets["/SET_N"]
    assert ("U52", "3") in nets["/RST_EFF"] and ("U51", "4") in nets["/RST_EFF"]
    assert ("U52", "4") in nets["/ENABLE_RAW"]      # AND output
    assert ("U52", "5") in nets["/PERMIT"]          # AND input 1
    assert ("U52", "6") in nets["/LATCHED_N"]       # AND input 2
    assert ("U52", "8") in nets["/ENABLE_RAW"]      # second AND input
    assert ("U52", "9") in nets["/SET_N"]           # the /SET interlock on ENABLE
    assert ("U52", "10") in nets["/ENABLE"]
    assert ("Q52", "1") in nets["/ENABLE"] and ("U50", "3") in nets["/ENABLE"]
    assert ("U50", "4") in nets["/ENABLE_N"] and ("Q54", "1") in nets["/ENABLE_N"]
    # Q50: gate on the pulled-up node, source on the input, drain to R59.
    assert nets["/BC_GATE"] == {("Q50", "1"), ("Q52", "3"), ("R50", "2"), ("TP23", "1")}
    assert nets["/VDD_IN"] >= {("Q50", "2"), ("R50", "1")}
    assert nets["/PASS_OUT"] == {("Q50", "3"), ("R59", "1")}


def test_the_drawing_has_no_ideal_enable_bypassing_the_latch() -> None:
    """No gate output reaches Q52 except through the AND chain."""
    nets = _netlist()
    assert nets["/ENABLE"] == {("Q52", "1"), ("R52", "1"), ("TP24", "1"),
                               ("U50", "3"), ("U52", "10")}
    assert "/PERMIT_EXT" in nets and "/RESET_EXT" in nets and "/FAULT_IN" in nets


# ---------------------------------------------------------------- report
def test_the_report_records_the_required_conditions() -> None:
    data = t.record()
    assert data["measured"] is False
    assert data["hardware_qualified"] is False
    assert set(data["results"]["measurements"]) == set(t.cases())
    assert data["open"]
    # The 5 V loss finding: VDD_SR is still above the REG UVLO *turn-off* floor
    # milliseconds after the control domain died, but already below the 4.13 V
    # at which the regulator can hold REG in regulation.  Both readings matter:
    # the gates may still be driven, while the gate clamp is out of spec.
    hold = data["results"]["five_v_loss_hold"]
    assert hold["vdd_sr_3ms"] > t.V_REG_OFF_MAX_V
    assert hold["vdd_sr_6ms"] > t.V_REG_OFF_MAX_V
    assert hold["vdd_sr_3ms"] < t.V_REG_UVLO_VDD_V
    assert hold["gates_may_still_be_driven_at_6ms"] is True
    assert hold["gate_clamp_in_regulation_at_6ms"] is False
    assert hold["vdd_sr_6ms"] < hold["vdd_sr_3ms"]


def test_the_json_on_disk_is_the_module_output_and_passes_every_check() -> None:
    data = json.loads(t.JSON_PATH.read_text(encoding="utf-8"))
    current = t.record()
    # The recorded waveform values and complete circuit inputs MUST agree.
    # The original Windows .log byte hashes are historical and not replaced
    # when the committed logs have changed formatting in Git transport.
    historical_no_hash = json.loads(json.dumps(data))
    current_no_hash = json.loads(json.dumps(current))
    for name in t.cases():
        log = t.OUT / f"{name}.log"
        verified = transport.verify_committed_log_measurements(
            log,
            data["results"]["measurements"][name],
            data["decks"][name]["log_sha256"],
            t.parse_meas,
        )
        assert verified["measurements_exactly_match"]
        assert not verified["hardware_qualified"]
        assert data["decks"][name]["cir_sha256"] == current["decks"][name]["cir_sha256"]
        historical_no_hash["decks"][name].pop("log_sha256")
        current_no_hash["decks"][name].pop("log_sha256")
    assert historical_no_hash == current_no_hash
    assert all(data["checks"].values()), data["checks"]
    assert data["evidence"] == "LTSPICE_BEHAVIOURAL_DECKS_ON_REMOTE_WINSRV"
