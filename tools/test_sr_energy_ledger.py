"""Tests for the branch-energy ledger arithmetic and trace lookup.

The real bench run is the primary evidence; these tests pin the sign
conventions and the closure identity so a later refactor cannot silently flip a
branch and turn a dissipated watt into a stored one.
"""

from __future__ import annotations

import numpy as np

from sr_energy_ledger import find, ledger_period


def _synthetic(extra: dict[str, np.ndarray] | None = None) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    t = np.arange(0.0, 1e-6 + 0.5e-9, 1e-9)
    n = t.size
    zero = np.zeros(n)
    data = {
        "V(a1)": np.full(n, -0.05),
        "I(VSa1)": np.full(n, -8.0),
        "V(ga1)": np.full(n, 11.0),
        "I(xsa1:Lg)": zero.copy(),
        "I(xsr1:x1:Bdrive)": zero.copy(),
        "V(xsa1:di)": np.full(n, 0.0),
        "V(xsa1:si)": np.full(n, 0.05),  # V(di,si) = -0.05
        "V(xsa1:gi)": np.full(n, 11.0),
        "V(xsa1:gn)": np.full(n, 11.0),
        "I(xsa1:Bch)": np.full(n, -8.0),
        "I(xsa1:Dbd)": zero.copy(),
        "I(xsa1:Cds)": zero.copy(),
        "I(xsa1:Cgd)": zero.copy(),
        "I(xsa1:Cgs)": zero.copy(),
        "I(xsa1:Ld)": zero.copy(),
        "I(xsa1:Ls)": zero.copy(),
        "I(xsa1:Lg)": zero.copy(),
        "I(xsa1:Rg)": zero.copy(),
    }
    if extra:
        data.update(extra)
    return t, data


def test_channel_energy_equals_port_when_nothing_is_reactive() -> None:
    t, data = _synthetic()
    e = ledger_period(t, data, 1, 0.0, 1e-6)
    assert np.isclose(e["e_port_ds_uj"], 0.4, rtol=0.01)  # 0.05 V * 8 A * 1 us
    assert np.isclose(e["e_channel_uj"], 0.4, rtol=0.01)
    assert np.isclose(e["e_dissipated_uj"], 0.4, rtol=0.01)
    assert np.isclose(e["e_residual_uj"], 0.0, atol=1e-3)


def test_stored_term_shows_up_in_the_residual() -> None:
    """A charging Cds is not heat: it must land in the stored column, not dissipated."""
    t, data = _synthetic()
    n = t.size
    data["I(xsa1:Cds)"] = np.full(n, 1e-3)  # 1 mA into Cds, V(di,si) = -0.05 V
    e = ledger_period(t, data, 1, 0.0, 1e-6)
    assert np.isclose(e["e_cds_delta_uj"], -5e-5, rtol=0.02)
    assert np.isclose(e["e_dissipated_uj"], 0.4, rtol=0.01)
    assert np.isclose(e["e_stored_delta_uj"], e["e_cds_delta_uj"], rtol=1e-9)
    assert np.isclose(e["e_residual_uj"], -e["e_cds_delta_uj"], rtol=0.02)


def test_body_diode_energy_is_anode_voltage_times_current() -> None:
    t, data = _synthetic()
    n = t.size
    # forward diode: V(si,di) = +0.8 V, I(Dbd) = +5 A
    data["V(xsa1:si)"] = np.full(n, 0.8)
    data["V(xsa1:di)"] = np.zeros(n)
    data["I(xsa1:Dbd)"] = np.full(n, 5.0)
    e = ledger_period(t, data, 1, 0.0, 1e-6)
    assert np.isclose(e["e_bodydiode_uj"], 4.0, rtol=0.01)  # 0.8 V * 5 A * 1 us


def test_find_is_case_insensitive_for_ltspice_names() -> None:
    data = {"I(xsa1:Bch)": np.zeros(3)}
    assert find(data, "I(xsa1:bch)") == "I(xsa1:Bch)"


def test_non_instrumented_pair_is_rejected_instead_of_silently_reused() -> None:
    """The trace names are hardcoded to xsa1/xsr1; pair 2 would be a wrong label."""
    t, data = _synthetic()
    try:
        ledger_period(t, data, 2, 0.0, 1e-6)
    except ValueError as exc:
        assert "pair 1" in str(exc)
    else:
        raise AssertionError("pair 2 must not silently return pair-1 numbers")
