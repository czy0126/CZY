"""The D0 bench board has to compute the reference protection logic.

``tools/two_tier_fault_logic.py`` is the authority; the schematic is a hardware
realisation of it.  Reading the part table and believing it is exactly the
failure this file removes, so the checks *run* the circuit:

* the gate table is compared with the pin roles of the KiCad symbols, so a gate
  output wired to a rail -- or two outputs on one net -- fails here instead of
  becoming an ERC line somebody learns to ignore;
* every combinational net is evaluated from the part table and compared with
  ``hardware_step()`` for *all* input combinations;
* the latch update is compared with the reference ``transition()`` for all
  input/state combinations, and the four safety properties are asserted
  separately so a later edit cannot trade one of them away.

Two pin-assignment bugs were found this way and are pinned below: the 4093's
unit 2 output (pin 4) sat on ``PGND``, and its unit 4 output (pin 11) was on
``ACK_RAW`` while the input pin 13 was on ``ACK_N`` -- so the token clock had no
driver at all while ERC reported the drawing as "self-consistent".

Nothing here is evidence that hardware exists.  ``hardware_built`` and
``fabrication_approved`` stay false in the generated report, and a clean ERC
only says the drawing agrees with itself.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_d0_protection_board as board  # noqa: E402
import two_tier_fault_logic as ref  # noqa: E402

POWER_PINS = {"7", "14"}

# Pin roles read off the KiCad 10.0 library symbols: unit -> (output, inputs).
# 4081/4071/4093 share the DIP layout (1,2->3  5,6->4  8,9->10  12,13->11);
# 4069 is six inverters with the output on the higher pin of each pair.
GATE_PINS: dict[str, dict[int, tuple[str, tuple[str, ...]]]] = {
    "4xxx:4081": {1: ("3", ("1", "2")), 2: ("4", ("5", "6")),
                  3: ("10", ("8", "9")), 4: ("11", ("12", "13"))},
    "4xxx:4071": {1: ("3", ("1", "2")), 2: ("4", ("5", "6")),
                  3: ("10", ("8", "9")), 4: ("11", ("12", "13"))},
    "4xxx:HEF4093B": {1: ("3", ("1", "2")), 2: ("4", ("5", "6")),
                      3: ("10", ("8", "9")), 4: ("11", ("12", "13"))},
    "4xxx:4069": {1: ("2", ("1",)), 2: ("4", ("3",)), 3: ("6", ("5",)),
                  4: ("8", ("9",)), 5: ("10", ("11",)), 6: ("12", ("13",))},
}

GATE_OPERATOR = {"4xxx:4081": "and", "4xxx:4071": "or",
                 "4xxx:HEF4093B": "nand", "4xxx:4069": "not"}

# CD4013: unit 1 is pins 1-6, unit 2 is 8-13, unit 3 is the supply pair.
FF_PINS = {
    1: {"Q": "1", "QN": "2", "CLK": "3", "RST": "4", "D": "5", "SET": "6"},
    2: {"SET": "8", "D": "9", "RST": "10", "CLK": "11", "QN": "12", "Q": "13"},
}

# Nets held by the two flip-flops.  They are state, not logic, so the
# combinational evaluation below takes them from the caller.
FF_NETS = ("LATCHED", "LATCHED_N", "ACK_LOW_OK")


def units() -> dict[tuple[str, int], board.Part]:
    return {(p.ref, p.unit): p for p in board.logic_parts()}


def gate_output_pin(part: board.Part) -> str | None:
    """The output pin of one gate unit, or None for a package's supply unit."""
    if part.lib == "4xxx:4013":
        return None
    spec = GATE_PINS.get(part.lib, {}).get(part.unit)
    return spec[0] if spec else None


def combinational_functions() -> dict[str, tuple[str, tuple[str, ...]]]:
    """net -> (operator, input nets) for every net driven by a 4xxx gate.

    Derived from the part table, not from ``hardware_step``: the two are
    compared against each other, so sharing code between them would make the
    comparison vacuous.
    """
    funcs: dict[str, tuple[str, ...]] = {}
    for part in units().values():
        out = gate_output_pin(part)
        if out is None:
            continue
        net = part.nets[out]
        if net == board.NC:
            # An unused gate's output is the KiCad no-connect token, which many
            # pins share; it is not a net and drives nothing.
            continue
        ins = GATE_PINS[part.lib][part.unit][1]
        funcs[net] = (GATE_OPERATOR[part.lib],
                      tuple(part.nets[pin] for pin in ins))
    return funcs


# The bench feeds these; anything else the circuit reads is a signal input.
CONSTANTS = {"PGND": False, "V5": True}


def free_inputs() -> list[str]:
    """Nets the circuit reads but never drives (comparators, straps, bench)."""
    funcs = combinational_functions()
    used: set[str] = {arg for _, args in funcs.values() for arg in args}
    for part in units().values():
        if part.lib == "4xxx:4013":
            used |= {net for net in part.nets.values() if net != board.NC}
    driven_or_fixed = set(funcs) | set(FF_NETS) | set(CONSTANTS) | {board.NC}
    return sorted(used - driven_or_fixed)


def evaluate(net: str, env: dict[str, bool],
             funcs: dict[str, tuple[str, tuple[str, ...]]],
             cache: dict[str, bool]) -> bool:
    if net in cache:
        return cache[net]
    if net not in funcs:
        return env[net]
    operator, args = funcs[net]
    values = [evaluate(arg, env, funcs, cache) for arg in args]
    if operator == "and":
        result = all(values)
    elif operator == "or":
        result = any(values)
    elif operator == "nand":
        result = not all(values)
    elif operator == "not":
        result = not values[0]
    else:  # pragma: no cover - a typo in GATE_OPERATOR
        raise AssertionError(operator)
    cache[net] = result
    return result


def every_state():
    """Every free-input assignment crossed with both latch states."""
    nets = free_inputs()
    for values in itertools.product((False, True), repeat=len(nets)):
        env = dict(CONSTANTS)
        env.update(zip(nets, values))
        for latched, ack_low_ok in itertools.product((False, True), repeat=2):
            env["LATCHED"] = latched
            env["LATCHED_N"] = not latched
            env["ACK_LOW_OK"] = ack_low_ok
            yield env


def all_off(env: dict[str, bool]) -> bool:
    """ALL_OFF is a gate output (NOT ANY_ON); the comparator sees the gate sum."""
    return not env["ANY_ON"]


def ack_dly_n(env: dict[str, bool]) -> bool:
    """ACK_DLY_N is a gate output (NOT ACK_RC); ACK_RC is the analog RC node."""
    return not env["ACK_RC"]


def por(env: dict[str, bool]) -> bool:
    """POR is a gate output (NOT POR_RC); POR_RC is the analog RC node."""
    return not env["POR_RC"]


def step_from_env(env: dict[str, bool]) -> dict[str, bool]:
    return board.hardware_step(
        hard_trip=env["HARD_TRIP"], fast_trip=env["FAST_TRIP"], fast_ext_n=env["FAST_EXT_N"],
        fast_armed_in=env["FAST_ARMED_IN"],
        v12p_ok=env["V12P_OK"], v12s_ok=env["V12S_OK"],
        v5_ok=env["V5_OK"], ct_ok=env["CT_OK"],
        ss_ready=env["SS_READY"], operator_run=env["OPERATOR_RUN"],
        all_off=all_off(env), ack_raw=env["ACK_RAW"],
        ack_rise=env["ACK_RAW"] and ack_dly_n(env), por=por(env),
        latched=env["LATCHED"], ack_low_ok=env["ACK_LOW_OK"])


def model_from_env(env: dict[str, bool]) -> dict:
    return ref.transition(
        latched_off=env["LATCHED"],
        i=ref.Inputs(
            hard_trip=env["HARD_TRIP"], fast_trip=(env["FAST_TRIP"] or not env["FAST_EXT_N"]),
            armed=env["FAST_ARMED_IN"],
            primary_bias_good=env["V12P_OK"], secondary_bias_good=env["V12S_OK"],
            ct_signal_valid=env["CT_OK"], comparator_bias_good=env["V5_OK"],
            start_sequence_ready=env["SS_READY"],
            operator_run=env["OPERATOR_RUN"],
            reset_ack=env["ACK_RAW"], all_ten_gates_off=all_off(env)),
        memory=ref.ResetMemory(
            # ACK_DLY_N is the inverted delayed ACK, so during the edge window
            # it still holds the level the ACK had *before* the press -- exactly
            # the reference model's reset_ack_was_high.
            reset_ack_was_high=env["ACK_RC"],
            ack_low_seen_while_healthy=env["ACK_LOW_OK"]))


# ------------------------------------------------------------ pin structure
def test_each_gate_unit_uses_the_symbols_output_and_input_pins():
    """A gate whose output pin holds an input net is wired backwards.  The two
    bugs found in review were both this shape."""
    for (ref_, unit), part in units().items():
        if part.lib == "4xxx:4013":
            spec = FF_PINS.get(unit)
        else:
            spec = GATE_PINS.get(part.lib, {}).get(unit)
        if spec is None:
            assert set(part.nets) <= POWER_PINS, (ref_, unit, part.nets)
            assert set(part.nets) == POWER_PINS, (ref_, unit, part.nets)
            continue
        if part.lib == "4xxx:4013":
            pins = set(spec.values())
        else:
            pins = {spec[0]} | set(spec[1])
        assert set(part.nets) == pins, (ref_, unit, part.nets)


def test_no_gate_output_is_tied_to_a_supply_rail():
    supplies = {"PGND", "V5", "V12P", "V12S"}
    for (ref_, unit), part in units().items():
        out = gate_output_pin(part)
        if out is None:
            continue
        assert part.nets[out] not in supplies, (ref_, unit, part.nets[out])


def test_no_two_gate_outputs_share_a_net():
    seen: dict[str, str] = {}
    for (ref_, unit), part in units().items():
        out = gate_output_pin(part)
        if out is None:
            continue
        net = part.nets[out]
        if net == board.NC:
            continue
        assert net not in seen, f"{net} driven by both {seen.get(net)} and {ref_}.{unit}"
        seen[net] = f"{ref_}.{unit}"


def test_the_two_flip_flops_are_wired_as_set_dominant_latches():
    """FF1 must SET on FLT and RESET on the qualified release; FF2 must clear
    on FF2_RESET.  A swapped SET/RESET would still pass ERC."""
    ff1 = units()[("U12", 1)]
    assert ff1.nets[FF_PINS[1]["SET"]] == "FLT"
    assert ff1.nets[FF_PINS[1]["RST"]] == "RST_EFF"
    assert ff1.nets[FF_PINS[1]["Q"]] == "LATCHED"
    assert ff1.nets[FF_PINS[1]["D"]] == "V5"
    assert ff1.nets[FF_PINS[1]["CLK"]] == "PGND"
    ff2 = units()[("U12", 2)]
    assert ff2.nets[FF_PINS[2]["RST"]] == "FF2_RESET"
    assert ff2.nets[FF_PINS[2]["SET"]] == "ACK_ARM"
    assert ff2.nets[FF_PINS[2]["Q"]] == "ACK_LOW_OK"
    # Clock and D tied off: an edge sampler on ACK_N only armed the token on the
    # *release*, so the first press after power-up was swallowed.
    assert ff2.nets[FF_PINS[2]["D"]] == "PGND"
    assert ff2.nets[FF_PINS[2]["CLK"]] == "PGND"
    # ACK_ARM is a gate output, not a strap: the low level must be observed
    # while READY, which is the reference's fresh_release term.
    arm = units()[("U9", 4)]
    assert arm.nets["11"] == "ACK_ARM"
    assert {arm.nets["12"], arm.nets["13"]} == {"READY", "ACK_N"}


# ------------------------------------------- the table vs the python mirror
def test_every_combinational_net_matches_hardware_step():
    funcs = combinational_functions()
    checked = 0
    for env in every_state():
        cache: dict[str, bool] = {}
        step = step_from_env(env)
        for net, key in (("HEALTHY", "healthy"), ("FAST_ARMED", "fast_armed"),
                         ("FAULT_B", "fault"), ("FLT", "flt"),
                         ("READY", "ready"), ("PERMIT", "permit"),
                         ("RST_EFF", "rst_eff")):
            assert evaluate(net, env, funcs, cache) == step[key], (net, env)
            checked += 1
        assert evaluate("LATCHED_N", env, funcs, cache) == (not env["LATCHED"])
    assert checked > 0


def test_external_fast_fault_cannot_suppress_the_legacy_trip():
    """Evaluate actual gate wiring, not a hand-written OR truth function."""
    funcs = combinational_functions()
    for legacy, external in itertools.product((False, True), repeat=2):
        env = dict(CONSTANTS)
        env.update(dict.fromkeys(free_inputs(), False))
        env.update(FAST_TRIP=legacy, FAST_EXT_N=not external,
                   FAST_ARMED_IN=True, LATCHED=False, LATCHED_N=True,
                   ACK_LOW_OK=False)
        assert evaluate("FAST_COMBINED", env, funcs, {}) == (legacy or external)
        assert evaluate("FAST_ARMED", env, funcs, {}) == (legacy or external)


def test_external_connector_and_open_signal_wire_contract():
    import make_fast_oc_eco as module

    ps = {p.ref: p for p in board.parts()}
    tx = {p.ref: p for p in module.parts()}
    assert ps["J10"].nets == tx["J1"].nets
    assert ps["R100"].nets == {"1": "FAST_EXT_N", "2": "PGND"}
    assert ps["R100"].value == "100k"
    assert tx["Q1"].nets["3"] == "FAST_EXT_N"
    assert ps["J10"].nets["4"] != "FAST_TRIP"
    # Check exported native nets as well as the generator table.
    text = (board.OUT / "d0_protection.net").read_text(encoding="utf-8")
    nets = {}
    for match in re.finditer(r"\(net\s+\(code", text):
        chunk = text[match.start():board.block_end(text, match.start())]
        name = re.search(r'\(name "([^"]+)"\)', chunk).group(1)
        nets[name.lstrip("/")] = set(re.findall(r'\(ref "([^"]+)"\)\s+\(pin "([^"]+)"\)', chunk))
    assert {("J10", "4"), ("U11", "13"), ("R100", "1")} <= nets["FAST_EXT_N"]
    assert ("U6", "12") in nets["FAST_COMBINED"]
    assert ("U3", "7") in nets["FAST_TRIP"]
    assert ("J10", "4") not in nets["FAST_TRIP"]
    funcs = combinational_functions()
    assert evaluate("FAST_EXT_H", {"FAST_EXT_N": False}, funcs, {}) is True


def test_the_latch_update_is_the_reference_transition():
    """Exact equality wherever the reference defines a transition.

    The qualified release network has to reduce to the reference's
    ``reset_valid`` term, not merely imply it.  POR is excluded because the
    board folds it into the fault latch so a cold start comes up latched-off
    until an operator presses, while the reference has no POR input -- it
    expresses a power-on as the *initial* ``latched_off=True`` plus cleared
    memory.  There is no per-step equality to check under POR; the board may
    be more conservative there, never less.
    """
    funcs = combinational_functions()
    for env in every_state():
        cache: dict[str, bool] = {}
        combinational_next = (evaluate("FLT", env, funcs, cache)
                              or (env["LATCHED"] and not evaluate("RST_EFF", env, funcs, cache)))
        step = step_from_env(env)
        assert combinational_next == step["latched_next"], env
        if por(env):
            assert step["latched_next"] is True, env
            continue
        assert step["latched_next"] == model_from_env(env)["latched_off_next"], env


def test_a_cold_start_is_latched_until_the_operator_presses():
    """POR is what makes "default off" true at t=0: every other input already
    says go, yet the latch is set and PERMIT stays low."""
    env = dict(CONSTANTS)
    env.update(dict.fromkeys(free_inputs(), False))
    env["FAST_EXT_N"] = True
    env.update({"V12P_OK": True, "V12S_OK": True, "V5_OK": True, "CT_OK": True,
                "SS_READY": True, "OPERATOR_RUN": True,
                "LATCHED": False, "LATCHED_N": True, "ACK_LOW_OK": True,
                "ACK_RAW": False, "ACK_RC": False, "POR_RC": False})
    assert por(env)
    step = step_from_env(env)
    assert step["latched_next"] is True
    assert step["permit"] is False


# --------------------------------------------------------- safety properties
def test_hardware_permit_is_never_wider_than_the_reference():
    """Deliberate difference: the board derives PERMIT from the latch's present
    state, the model from ``next_latched``.  The board can only be *later* to
    enable, so the assertion is an implication, never equality."""
    for env in every_state():
        step = step_from_env(env)
        if not step["permit"]:
            continue
        assert model_from_env(env)["primary_en_permit"], env


def test_any_fault_latches_and_drops_the_permit():
    for env in every_state():
        step = step_from_env(env)
        if not step["fault"]:
            continue
        assert step["latched_next"], env
        assert not step["permit"], env


def test_a_cleared_fault_never_reenables_without_a_press():
    """Once the release token is invalidated (ACK_LOW_OK low), no combination of
    inputs other than a fresh qualified press may clear the latch."""
    for env in every_state():
        if not env["LATCHED"] or env["ACK_LOW_OK"]:
            continue
        if env["ACK_RAW"]:
            # A held-high ACK is not a press: ACK_RISE needs ACK_DLY_N as well,
            # which is the inverted *previous* level.
            continue
        assert step_from_env(env)["latched_next"], env


def test_a_held_high_ack_is_not_a_rising_edge():
    """ACK held high is level, not an edge: the press only counts while the RC
    node still reads the *previous* level, so it cannot be re-armed by waiting."""
    for ack_raw, ack_rc in itertools.product((False, True), repeat=2):
        env = dict(CONSTANTS)
        env.update(dict.fromkeys(free_inputs(), False))
        env["FAST_EXT_N"] = True
        env.update({"LATCHED": True, "LATCHED_N": False, "ACK_LOW_OK": True,
                    "ACK_RAW": ack_raw, "ACK_RC": ack_rc})
        rise = ack_raw and ack_dly_n(env)
        assert rise == (ack_raw and not ack_rc)
        if ack_rc == ack_raw:  # steady state: no edge, so the latch holds
            assert step_from_env(env)["latched_next"] is True


def test_the_token_is_a_set_dominant_level_latch():
    """ACK_ARM = READY and not ACK_RAW sets it, any fault or lost READY clears
    it, and SET wins -- the CD4013's behaviour, not an edge sampler's."""
    for ff2_reset, ready, ack_raw, token in itertools.product((False, True), repeat=4):
        nxt = board.token_next(ff2_reset=ff2_reset, ready=ready,
                               ack_raw=ack_raw, token=token)
        assert nxt == ((ready and not ack_raw) or (token and not ff2_reset))
        if ff2_reset and not (ready and not ack_raw):
            assert nxt is False


def test_the_first_press_after_power_up_clears_the_latch():
    """End to end: healthy with the button idle-low arms the token with no press
    at all, so the *first* press is the one that releases the latch.  An edge
    sampler armed on the release needed press-release-press."""
    env = dict(CONSTANTS)
    env.update(dict.fromkeys(free_inputs(), False))
    env["FAST_EXT_N"] = True
    env.update({"V12P_OK": True, "V12S_OK": True, "V5_OK": True, "CT_OK": True,
                "SS_READY": True, "OPERATOR_RUN": True, "POR_RC": True,
                "LATCHED": True, "LATCHED_N": False, "ACK_LOW_OK": False,
                "ACK_RAW": False, "ACK_RC": False})
    step = step_from_env(env)
    assert step["ready"] is True
    token = board.token_next(ff2_reset=not step["ready"], ready=step["ready"],
                             ack_raw=env["ACK_RAW"], token=False)
    assert token is True, "the ACK-low level while READY must arm the token"
    # The operator presses: ACK_RAW is high while the 1 ms RC still reads low.
    env.update({"ACK_LOW_OK": token, "ACK_RAW": True, "ACK_RC": False})
    step = step_from_env(env)
    assert step["ack_rise"] is True
    assert step["rst_eff"] is True
    assert step["latched_next"] is False


# ------------------------------------------------------ board-level features
def test_every_sr_gate_has_a_pull_down_a_series_resistor_and_a_dummy_load():
    parts = board.parts()
    gates = [f"GA{i}" for i in range(1, 9)] + ["GH1", "GL1"]
    for gate in gates:
        pulldown = [p for p in parts
                    if p.nets.get("1") == gate and p.nets.get("2") == "PGND"
                    and p.value == "10k"]
        assert pulldown, f"{gate} has no 10k gate-source pull-down"
        load = [p for p in parts
                if p.nets.get("1") == gate and p.nets.get("2") == "PGND"
                and p.lib == "Device:C"]
        assert load, f"{gate} has no dummy gate load"
        series = [p for p in parts
                  if gate in p.nets.values() and p.lib == "Device:R"
                  and p.value == "2.2R"]
        assert series, f"{gate} has no 2.2R series resistor"
        sum_res = [p for p in parts
                   if p.nets.get("1") == gate and p.lib == "Device:R"
                   and p.value == "1k" and p.nets.get("2", "").startswith("GK")]
        assert sum_res, f"{gate} has no 1k into its own detector diode"


def test_the_dummy_loads_match_the_deck():
    loads = {p.ref: p for p in board.parts() if p.ref.startswith("C")
             and p.nets.get("2") == "PGND" and p.nets.get("1", "").startswith(("GA", "GH", "GL"))}
    assert len(loads) == 10
    assert sum(1 for p in loads.values() if p.value == "6.7nF/50V") == 8
    assert sum(1 for p in loads.values() if p.value == "4nF") == 2


def test_every_driver_enable_is_pulled_down_to_the_default_off_rail():
    parts = board.parts()
    for index, driver in enumerate(("U14", "U15", "U16", "U17")):
        ena, enb = f"R{36 + 2 * index}", f"R{37 + 2 * index}"
        for ref_ in (ena, enb):
            part = next(p for p in parts if p.ref == ref_)
            assert part.value == "4.7k", ref_
            assert part.nets == {"1": "PERMIT_RAIL", "2": "PGND"}, ref_
        unit = next(p for p in parts if p.ref == driver and p.unit == 1)
        assert unit.nets["1"] == "PERMIT_RAIL" and unit.nets["8"] == "PERMIT_RAIL"


def test_the_permit_transistor_is_oriented_so_the_rail_follows_permit():
    """Q2's source is pin 2 of Q_PMOS_GSD.  Source on V5 and drain on the rail
    keeps the body diode reverse-biased while the gate is high.  With the pins
    swapped the diode conducts V5 -> PERMIT_RAIL, R35 only sets a level, and the
    ten drivers stay enabled at POR: the opposite of default-off."""
    q2 = next(p for p in board.parts() if p.ref == "Q2")
    assert q2.lib == "Transistor_FET:Q_PMOS_GSD"
    assert q2.nets == {"1": "PCOLL", "2": "V5", "3": "PERMIT_RAIL"}
    r35 = next(p for p in board.parts() if p.ref == "R35")
    assert r35.nets == {"1": "PERMIT_RAIL", "2": "PGND"}


def test_the_gate_max_detector_numbers_are_computed_not_guessed():
    """Ten 1k branches, one diode each, into a 22k/6.2k divider.

    The branch resistor loads the divider, so one gate at 10 V gives
    10*6.2/29.2 = 2.123 V -- not the 10*6.2/(22+6.2) = 2.199 V you get by
    forgetting the 1k.  All ten conducting make the ten 1k resistors a 100 ohm
    series element, which is what sets the all-on figure.
    """
    assert board.gate_sense_v(10.0, conducting=1) == pytest.approx(2.1233, abs=1e-4)
    assert board.gate_sense_v(12.0, conducting=10) == pytest.approx(2.6290, abs=1e-4)
    threshold = board.divider_output("R6", "R7")
    assert threshold == pytest.approx(0.200, abs=1e-3)
    assert board.gate_sense_v(board.gate_trip_v()) == pytest.approx(threshold, abs=1e-9)


def test_one_gate_at_three_volts_is_detected_whatever_the_others_do():
    """The P0-1 defect, as an inequality rather than a claim.

    The old ten-resistor sum read 0.150 V for a gate parked at 3 V while the
    other nine were held low -- under the 0.200 V reference, i.e. "all off".
    A diode-OR passes the highest gate, so the other nine cannot pull it down:
    the 3 V gate reads 0.637 V, and the answer is the same whether they are
    driven low or left floating.
    """
    three = board.gate_sense_v(3.0, conducting=1)
    assert three > 3 * board.divider_output("R6", "R7")
    assert three > 0.200
    # The old ten-resistor sum put this gate at 0.150 V -- below the 0.200 V
    # reference.  The detector reads more than four times that.
    assert three > 4 * 0.150


def test_the_detector_trips_below_the_fet_threshold_not_above_it():
    """A gate the FET would conduct on must read "on", so the trip has to sit
    under VGS(th) min = 1.3 V.  The old sum tripped at 3.1-4.0 V, above the
    region where the FET is barely conducting and blind where it is fully on."""
    assert board.gate_trip_v() < 1.3
    assert board.gate_trip_v() == pytest.approx(0.9419, abs=1e-4)
    assert board.gate_sense_v(1.3) > board.divider_output("R6", "R7")


def test_every_gate_has_its_own_diode_and_the_cathodes_share_one_node():
    """Ten diodes, ten distinct series nodes, one cathode net.  A shared series
    node or a missing diode is how a reverse-biased branch silently stops
    reporting its gate."""
    parts = board.parts()
    gates = [f"GA{i}" for i in range(1, 9)] + ["GH1", "GL1"]
    diodes = [p for p in parts if p.lib == "Device:D_Schottky" and p.nets.get("1") == "GSMAX"]
    assert len(diodes) == 10
    anodes = [p.nets["2"] for p in diodes]
    assert len(set(anodes)) == 10
    for gate in gates:
        series = [p for p in parts if p.nets.get("1") == gate and p.value == "1k"
                  and p.lib == "Device:R"]
        assert len(series) == 1, gate
        assert series[0].nets["2"] in anodes, gate


def test_the_gate_max_node_cannot_leave_the_comparator_common_mode_range():
    """All ten gates high put the sense node at 2.629 V at the 12 V rail and
    3.286 V at the board's 15 V TVS standoff -- inside the LM393's
    VCC-1.5 V = 3.5 V, where an out-of-range input could otherwise read low,
    i.e. 'all off' while every gate is driven.

    The limiting element is a divider with a computed bound, not a Zener: a
    knee voltage is specified at 5 mA and this circuit only ever spends tens of
    microamps, so the old BZX84C3V0 could not be trusted to clamp at 3 V.  The
    bound below holds for any diode drop because Vf only lowers the node.
    """
    parts = board.parts()
    d9 = next(p for p in parts if p.ref == "D9")
    assert d9.lib == "Device:D_Schottky"
    assert d9.nets == {"1": "GSMAX", "2": "GK1"}
    assert not [p for p in parts if p.lib == "Device:D_Zener"
                and p.nets.get("1") == "GSMAX"], "the Zener clamp is still here"
    u5 = next(p for p in parts if p.ref == "U5" and p.unit == 2)
    assert u5.nets["5"] == "GATE_SENSE"
    assert board.gate_sense_v(12.0, conducting=10) < 3.5
    assert board.gate_sense_v(15.0, conducting=10) < 3.5
    assert board.gate_rail_for_common_mode() > 15.0, "the bound must cover the TVS standoff"


def test_the_common_mode_constant_is_the_25c_figure_and_the_full_range_one_is_kept():
    """Section 5.8 of the vendored LM393 datasheet gives VICR twice: 0 to
    VCC-1.5 (3.5 V) at 25 C and 0 to VCC-2 (3.0 V) over the full range.  The
    3.5 V this board has always used is the 25 C row; the guaranteed number is
    3.0 V, and the rail it covers is 13.69 V -- below the 15 V TVS standoff.
    Both are kept rather than one replacing the other, because the design is
    not retuned: the datasheet's own note allows it."""
    assert board.LM393_COMMON_MODE_LIMIT_V == pytest.approx(3.5)
    assert board.LM393_COMMON_MODE_LIMIT_FULL_RANGE_V == pytest.approx(3.0)
    assert board.gate_rail_for_full_range_common_mode() == pytest.approx(13.69, abs=0.02)
    assert board.gate_rail_for_common_mode() > board.gate_rail_for_full_range_common_mode()


def test_the_reference_input_stays_inside_the_range_at_every_gate_rail():
    """The datasheet's rule is that only *one* input has to be in the valid
    common-mode range for the output to be proper.  Here that input is the
    0.200 V reference, which is inside 0..VCC-2 no matter what the gates do --
    so the 15 V case is outside the spec limit on one pin, not undefined."""
    assert board.divider_output("R6", "R7") == pytest.approx(0.200, abs=1e-3)
    assert board.divider_output("R6", "R7") < board.LM393_COMMON_MODE_LIMIT_FULL_RANGE_V


def test_the_divider_covers_the_declared_gate_rail_not_just_twelve_volts():
    """V12P comes from the bench input through a reverse-polarity diode and is
    clamped by a 15 V-standoff TVS, so 15 V is the rail the board is allowed to
    see.  A divider sized against 12 V alone would leave the comparator out of
    range in exactly the overvoltage condition it is there for."""
    assert board.gate_rail_for_common_mode() == pytest.approx(15.976, abs=1e-3)
    assert board.gate_rail_for_common_mode() == pytest.approx(
        3.5 * (board.resistance(board.part_value("R66")) / 10
               + board.resistance(board.part_value("R76"))
               + board.resistance(board.part_value("R77")))
        / board.resistance(board.part_value("R77")), rel=1e-12)


def test_each_gate_has_a_first_article_check_that_can_fail():
    """An open diode or an open 1k blinds one channel and leaves the other nine
    working, so a single all-gates-high test cannot see it.  The record carries
    the per-gate expectation for a bring-up sweep, one gate at a time."""
    sweep = board.gate_sense_bring_up()
    assert len(sweep) == 10
    for row in sweep:
        assert row["gate_sense_v"] == pytest.approx(2.1233, abs=1e-4)
        assert row["reads_on"] is True
    assert len({row["gate"] for row in sweep}) == 10
    assert len({row["net"] for row in sweep}) == 10


def test_the_rail_good_dividers_stay_inside_the_comparator_common_mode_range():
    """LM393 inputs are specified 0 to VCC-1.5 = 3.5 V at V5 = 5 V.  A divider
    that reaches the 2.5 V reference at 12 V sits at 3.84 V there -- above the
    limit -- so the trip is based on the 1.000 V reference instead."""
    assert board.rail_good_node(12.0) == pytest.approx(1.54, abs=0.01)
    assert board.rail_good_node(11.5) < 3.5
    assert board.rail_good_node(12.0) < 3.5
    assert board.rail_good_trip() == pytest.approx(7.80, abs=0.02)
    parts = board.parts()
    for ref_ in ("R20", "R21", "R22", "R23"):
        assert next(p for p in parts if p.ref == ref_).value in ("100k", "14.7k")
    u4 = {p.unit: p for p in parts if p.ref == "U4"}
    assert u4[1].nets["2"] == "REF_1V0"
    assert u4[2].nets["6"] == "REF_1V0"


def test_the_always_on_strap_is_dnp():
    r45 = next(p for p in board.parts() if p.ref == "R45")
    assert r45.dnp, "R45 (main board R8) must be unfitted: it defeats the pull-down"
    assert r45.nets == {"1": "V12P", "2": "PERMIT_RAIL"}


def test_the_report_claims_no_hardware():
    report = board.report(board.parts())
    assert report["evidence_level"] == "GENERATED_SCHEMATIC_AND_NETLIST_NOT_HARDWARE"
    assert report["hardware_built"] is False
    assert report["fabrication_approved"] is False
    assert report["observations"], "the report must carry its own limitations"


# The truth is written here, not read back out of the generator: a part that
# cites a deck line has to name the element an auditor would go looking for.
# The first version cited R8's burden as line 117, which is the 0 V test source
# Vctg, so the pointer survived every check and still sent the reader elsewhere.
DECK_ELEMENTS = {
    "D5": "D1", "D6": "D2", "D7": "D3", "D8": "D4",
    "R8": "Rbur", "R9": "Rf", "C11": "Cf", "R10": "Rd1", "R11": "Rd2", "C12": "Coc",
}


def _deck_lines() -> list[str]:
    return (board.ROOT / board.DECK).read_text(encoding="utf-8").splitlines()


def test_every_deck_pointer_names_the_element_it_cites():
    lines = _deck_lines()
    parts = {p.ref: p for p in board.parts()}
    for ref, element in DECK_ELEMENTS.items():
        source = parts[ref].source
        assert source.startswith(f"{board.DECK}:"), (ref, source)
        number = int(source.rsplit(":", 1)[1])
        assert 1 <= number <= len(lines), (ref, number)
        assert lines[number - 1].split()[:1] == [element], (ref, lines[number - 1])


def test_every_source_ranges_over_a_real_deck_element():
    lines = _deck_lines()
    for observation in board.observations():
        if not observation["source"].startswith(f"{board.DECK}:"):
            continue
        span = observation["source"].rsplit(":", 1)[1]
        first, _, last = span.partition("-")
        for number in (int(first), int(last or first)):
            assert 1 <= number <= len(lines), (observation["id"], number)
            assert lines[number - 1].strip(), (observation["id"], number)


def test_no_part_value_contradicts_its_own_voltage_rating():
    """A value string that embeds a voltage is a claim about the same part.

    Every capacitor in the table spells its voltage twice -- "100nF/16V" in the
    value and "16 V X7R" in the rating -- so the two must agree.  The driver
    bulk caps said "1uF/16V" next to "25 V X7R"; one of them was wrong and
    nothing compared them, because a rating of 25 V does not *fail* a 16 V
    value, it just quietly proposes a different part.
    """
    for part in board.parts():
        match = re.search(r"/(\d+(?:\.\d+)?)V", part.value)
        if match is None:
            continue
        assert part.rating, f"{part.ref} embeds {match.group(1)} V but has no rating"
        rating = re.match(r"(\d+(?:\.\d+)?)\s*V", part.rating)
        assert rating, (part.ref, part.rating)
        assert float(match.group(1)) == float(rating.group(1)), (part.ref, part.value, part.rating)


def test_a_missing_erc_report_is_never_read_as_clean(tmp_path: Path):
    with pytest.raises(SystemExit):
        board.erc_violations(tmp_path / "erc.json")


def test_an_erc_report_about_another_schematic_is_rejected(tmp_path: Path):
    path = tmp_path / "erc.json"
    path.write_text(json.dumps({"source": "something_else.kicad_sch",
                                "sheets": [{"violations": []}]}), encoding="utf-8")
    with pytest.raises(SystemExit):
        board.erc_violations(path)


def test_an_erc_report_with_no_sheets_is_rejected(tmp_path: Path):
    path = tmp_path / "erc.json"
    path.write_text(json.dumps({"source": "d0_protection.kicad_sch", "sheets": []}),
                    encoding="utf-8")
    with pytest.raises(SystemExit):
        board.erc_violations(path)


def test_an_erc_report_older_than_the_schematic_is_rejected(tmp_path: Path):
    schematic = tmp_path / "d0_protection.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf-8")
    report = tmp_path / "erc.json"
    report.write_text(json.dumps({"source": "d0_protection.kicad_sch",
                                  "sheets": [{"violations": []}]}), encoding="utf-8")
    stale = schematic.stat().st_mtime - 60
    os.utime(report, (stale, stale))
    with pytest.raises(SystemExit):
        board.erc_violations(report, newer_than=schematic)


def test_a_clean_erc_report_is_read_back():
    report = board.OUT / "erc.json"
    if not report.exists():
        pytest.skip("erc.json has not been exported here")
    assert board.erc_violations(report) == []
