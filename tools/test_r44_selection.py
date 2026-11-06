"""Independent checks of curve provenance and full-hold crowbar energy."""
import hashlib
import math
import pytest
import r44_selection as r44
import make_sr_fault_board as board


def test_changed_resistance_cannot_silently_keep_the_old_order_code():
    with pytest.raises(ValueError, match="new procurement"):
        r44.screen(r=10)
    with pytest.raises(ValueError, match="equilibrium"):
        r44.screen(injection=3)


def test_selected_part_is_in_the_actual_bom_and_has_archived_evidence():
    part = next(p for p in board.parts() if p.ref == "R44")
    assert part.mpn == "CRCW12064R70FKEAHP"
    assert part.mpn_source == r44.SOURCE
    result = r44.screen()
    source = result["source_evidence"]
    assert hashlib.sha256((r44.ROOT/source["source_pdf"]).read_bytes()).hexdigest() == source["sha256"]
    for key in ("single", "continuous"):
        curve = source[key]
        readout = 10**(4-6*(curve["curve_y_pt"]-curve["top_y_pt"])
                      /(curve["bottom_y_pt"]-curve["top_y_pt"]))
        assert curve["readout_w"] == pytest.approx(readout)
        assert source["conservative_screen_w"] < readout*(1-source["reading_uncertainty_fraction"])
    assert result["qualified"] is False


def test_peak_envelope_covers_tolerance_corners_and_the_tail():
    result = r44.screen()
    env = result["pulse_envelope"]
    for r in (4.7*.99, 4.7*1.01):
        for rds in (0, .1):
            for c in (2.3e-6, 2.3e-6*1.2):
                for inj in (0, .095):
                    rt = r+rds
                    for t in (0, 1e-6, 20e-6, 100e-6, 1e-3):
                        current = inj+(11.9/rt-inj)*math.exp(-t/(rt*c))
                        limit = env["peak_w"] if t < env["duration_s"] else env["tail_power_w"]
                        assert current*current*r <= limit*(1+1e-12)
    assert env["margin"] > 1.9
    assert env["passes_assumed_envelope"] is True


def test_hold_energy_agrees_with_time_integration_and_includes_uvlo_tail():
    result = r44.screen()
    dt, duration = 1e-8, .001
    r, rt, c = 4.7, 4.8, 2.76e-6
    total = 0.0
    for n in range(round(duration/dt)):
        t = (n+.5)*dt
        i = .095+(11.9/rt-.095)*math.exp(-t/(rt*c))
        total += r*i*i*dt
    # After 1 ms the exponential is negligible; integrate the DC remainder.
    total += .095**2*r*(.010-duration)
    assert total == pytest.approx(result["energy"]["r44_with_injection_j_by_hold_ms"]["10"], rel=1e-6)
    no_injection = r44.screen(injection=0)
    expected = .5*c*11.9**2*r/rt
    assert no_injection["energy"]["r44_with_injection_j_by_hold_ms"]["10"] == pytest.approx(expected)
    assert result["energy"]["capacitor_full_discharge_j"] > board.crowbar()["energy_released_to_uvlo_j"]
    assert result["hold_sensitivity"]["controller_regulator_w"] > 1.3
