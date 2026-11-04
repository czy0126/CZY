"""Tests for the multi-instrument D0 synchronization / resampling gate.

All waveforms here are synthesized. They exercise the *alignment arithmetic and
fail-closed checks*, not real scope behaviour; no test may be cited as hardware
evidence.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

import d0_scope_sync_align as m
import d0_gate_capture_audit as audit

PRE_S = 300e-6
POST_S = 150e-6
DT_S = 1e-6
SHIFT_B_S = 3e-6


def gate_slots() -> dict[str, tuple[float, float]]:
    """Non-overlapping pretrip activation slots, one per gate (seconds)."""
    names = ("P_HO", "P_LO", "SR1A", "SR1B", "SR2A", "SR2B", "SR3A", "SR3B", "SR4A", "SR4B")
    return {name: (-90e-6 + 6e-6 * i, -86e-6 + 6e-6 * i) for i, name in enumerate(names)}


def physical_signal(name: str, p: float) -> float:
    if name == "TRIP_STIMULUS":
        return 5.0 if p >= 0 else 0.0
    start, stop = gate_slots()[name]
    return 5.0 if start <= p < stop else 0.0


def write_instrument(path: Path, shift: float, sources: tuple[str, ...],
                     trigger_column: str, sync_wave=None,
                     physical: dict[str, str] | None = None) -> None:
    """Write one instrument on its own clock ``tau = physical + shift``.

    ``sync_wave`` overrides the trigger column's value as a function of
    physical time; default is the trip stimulus (0 -> 5 V at p = 0).
    ``physical`` maps a recorded column name to the physical signal it carries.
    """
    physical = physical or {name: name for name in sources}
    n_pre = int(round(PRE_S / DT_S))
    n_post = int(round(POST_S / DT_S))
    header = ["time_s", *sources]
    if trigger_column not in sources:
        header.append(trigger_column)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for step in range(-n_pre, n_post + 1):
            tau = step * DT_S
            p = tau - shift
            row = [tau]
            row.extend(physical_signal(physical[name], p) for name in sources)
            if trigger_column not in sources:
                row.append(physical_signal("TRIP_STIMULUS", p) if sync_wave is None
                           else sync_wave(p))
            else:
                # The trigger column is one of the recorded channels; override
                # only if a custom sync waveform was requested.
                if sync_wave is not None:
                    column = header.index(trigger_column) - 1
                    row[column + 1] = sync_wave(p)
            writer.writerow(row)


def instrument(ident: str, csv_path: Path, channels: dict[str, str],
               trigger_column: str, shift: float) -> dict:
    return {
        "id": ident,
        "csv": str(csv_path),
        "time_column": "time_s",
        "trigger": {
            "column": trigger_column,
            "edge": "rising",
            "threshold_v": 2.5,
            "search_start_s": shift - 100e-6,
            "search_end_s": shift + 100e-6,
        },
        "channels": channels,
        "instrument_id": f"SYNTH_{ident}",
        "probe_model": "SYNTHETIC_TEST_ONLY",
        "probe_bandwidth_hz": 100e6,
        "sample_rate_hz": 1.0 / DT_S,
    }


def make_manifest(tmp_path: Path) -> Path:
    a = tmp_path / "scope_a.csv"
    b = tmp_path / "scope_b.csv"
    write_instrument(a, 0.0, ("TRIP_STIMULUS", "P_HO", "P_LO"), "TRIP_STIMULUS")
    write_instrument(b, SHIFT_B_S,
                     ("SR1A", "SR1B", "SR2A", "SR2B", "SR3A", "SR3B", "SR4A", "SR4B"),
                     "SYNC")
    cfg = {
        "schema_version": 1,
        "case_id": "SYNTHETIC_UNIT_TEST_NOT_A_BENCH_MEASUREMENT",
        "sync": {
            "alignment_basis": "SYNTHETIC_TEST_ONLY",
            "basis_review_status": "ENGINEER_REVIEWED",
            "max_remaining_skew_s": 2e-6,
        },
        "grid": {"pre_s": 200e-6, "post_s": 50e-6, "dt_s": DT_S},
        "instruments": [
            instrument("A", a, {"TRIP_STIMULUS": "TRIP_STIMULUS",
                                "P_HO": "P_HO", "P_LO": "P_LO"},
                       "TRIP_STIMULUS", 0.0),
            instrument("B", b, {name: name for name in
                                ("SR1A", "SR1B", "SR2A", "SR2B",
                                 "SR3A", "SR3B", "SR4A", "SR4B")},
                       "SYNC", SHIFT_B_S),
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


def run(tmp_path: Path, manifest: Path) -> tuple[int, dict, Path]:
    out = tmp_path / "aligned.csv"
    report_path = tmp_path / "alignment.json"
    code = m.run(manifest, out, report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return code, report, out


def rewrite_manifest(manifest: Path, mutate) -> Path:
    cfg = json.loads(manifest.read_text(encoding="utf-8"))
    mutate(cfg)
    manifest.write_text(json.dumps(cfg), encoding="utf-8")
    return manifest


def test_two_instruments_align_on_the_trip_edge_and_keep_values():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = make_manifest(tmp_path)
        code, report, out = run(tmp_path, manifest)
        assert code == 0
        assert report["status"] == "ALIGNED_FOR_CAPTURE_AUDIT"
        assert report["physical_simultaneity_proven"] is False
        assert report["hardware_protection_approved"] is False
        assert report["power_stage_fabrication_approved"] is False
        assert len(report["instruments"]) == 2
        assert report["instruments"][1]["trigger_time_s"] == pytest.approx(
            SHIFT_B_S - DT_S / 2)
        assert report["channel_producers"]["SR4B"] == "B"

        with out.open(newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            header = next(reader)
            rows = [list(map(float, row)) for row in reader]
        assert header == list(m.OUTPUT_COLUMNS)
        assert len(rows) == 251  # -200 us .. +50 us at 1 us
        index = {name: header.index(name) for name in header}

        def value_at(when: float, name: str) -> float:
            row = min(rows, key=lambda r: abs(r[0] - when))
            assert abs(row[0] - when) <= DT_S / 2
            return row[index[name]]

        assert value_at(-88e-6, "P_HO") == pytest.approx(5.0)
        assert value_at(10e-6, "P_HO") == pytest.approx(0.0)
        assert value_at(-76e-6, "SR1A") == pytest.approx(5.0)
        assert value_at(10e-6, "SR1A") == pytest.approx(0.0)
        assert value_at(-1e-6, "TRIP_STIMULUS") == pytest.approx(0.0)
        assert value_at(0.0, "TRIP_STIMULUS") == pytest.approx(2.5)
        assert value_at(1e-6, "TRIP_STIMULUS") == pytest.approx(5.0)
        assert report["output"]["row_count"] == len(rows)
        assert len(report["output"]["csv_sha256"]) == 64


def test_resampled_output_is_accepted_by_the_capture_auditor():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = make_manifest(tmp_path)
        code, report, out = run(tmp_path, manifest)
        assert code == 0
        config = {
            "schema_version": 1,
            "case_id": "SYNTHETIC_PIPELINE_TEST",
            "hardware_revision": "SYNTHETIC_TEST_ONLY",
            "instrument_id": "SYNTHETIC_TEST_ONLY",
            "limit_basis": "SYNTHETIC_TEST_ONLY",
            "limits_review_status": "ENGINEER_REVIEWED",
            "time_column": "time_s",
            "trip_column": "TRIP_STIMULUS",
            "gate_columns": list(audit.GATES),
            "gate_off_max_v": 1.0,
            "gate_on_min_v": 4.0,
            "gate_overlap_forbidden_above_v": 2.0,
            "trip_low_max_v": 0.8,
            "trip_high_min_v": 2.5,
            "max_disable_latency_s": 10e-6,
            "max_sample_spacing_s": 2e-6,
            "min_pretrip_s": 100e-6,
            "min_post_trip_hold_s": 20e-6,
        }
        config_path = tmp_path / "limits.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        t, traces = audit.read_csv(out)
        result = audit.evaluate(config, t, traces)
        assert result["status"] == "PASS_CAPTURE_ONLY", result["violations"]
        assert result["all_ten_real_hardware_gates_verified"] is False


def test_duplicate_channel_producers_are_rejected():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = make_manifest(tmp_path)
        a = tmp_path / "scope_a.csv"
        write_instrument(a, 0.0, ("TRIP_STIMULUS", "P_HO", "P_LO", "SR4B"),
                         "TRIP_STIMULUS")
        rewrite_manifest(manifest, lambda c: c["instruments"][0]["channels"].update(
            {"SR4B": "SR4B"}))
        code, report, out = run(tmp_path, manifest)
        assert code == 2
        assert report["status"] == "INVALID_ALIGNMENT"
        assert any("more than one producer" in e for e in report["errors"])
        assert not out.exists()


def test_missing_target_channel_is_rejected():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = make_manifest(tmp_path)
        rewrite_manifest(manifest, lambda c: c["instruments"][1]["channels"].pop("SR4B"))
        code, report, _ = run(tmp_path, manifest)
        assert code == 2
        assert any("no producer" in e for e in report["errors"])


def test_ip_endpoint_map_is_honoured():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        a = tmp_path / "scope_a.csv"
        b = tmp_path / "scope_b.csv"
        cfg = json.loads(make_manifest(tmp_path).read_text(encoding="utf-8"))
        write_instrument(a, 0.0, ("TRIP_STIMULUS", "CH1", "CH2"), "TRIP_STIMULUS",
                         physical={"TRIP_STIMULUS": "TRIP_STIMULUS",
                                   "CH1": "P_HO", "CH2": "P_LO"})
        write_instrument(b, SHIFT_B_S,
                         ("SR1A", "SR1B", "SR2A", "SR2B", "SR3A", "SR3B", "SR4A", "SR4B"),
                         "SYNC")
        cfg["instruments"][0]["channels"] = {
            "TRIP_STIMULUS": "TRIP_STIMULUS", "CH1": "P_HO", "CH2": "P_LO"}
        cfg["instruments"][0]["csv"] = str(a)
        cfg["instruments"][1]["csv"] = str(b)
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        code, report, out = run(tmp_path, path)
        assert code == 0
        assert report["channel_producers"]["P_HO"] == "A"


def test_multiple_trigger_crossings_are_ambiguous_and_rejected():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = make_manifest(tmp_path)
        b = tmp_path / "scope_b.csv"
        write_instrument(b, SHIFT_B_S,
                         ("SR1A", "SR1B", "SR2A", "SR2B", "SR3A", "SR3B", "SR4A", "SR4B"),
                         "SYNC", sync_wave=lambda p: 5.0 if (
                             -50e-6 <= p < -20e-6) or (0 <= p < 20e-6) else 0.0)
        rewrite_manifest(manifest, lambda c: c["instruments"][1].update({"csv": str(b)}))
        code, report, _ = run(tmp_path, manifest)
        assert code == 2
        assert any("exactly one" in e for e in report["errors"])


def test_missing_trigger_edge_is_rejected():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = make_manifest(tmp_path)
        b = tmp_path / "scope_b.csv"
        write_instrument(b, SHIFT_B_S,
                         ("SR1A", "SR1B", "SR2A", "SR2B", "SR3A", "SR3B", "SR4A", "SR4B"),
                         "SYNC", sync_wave=lambda p: 0.0)
        rewrite_manifest(manifest, lambda c: c["instruments"][1].update({"csv": str(b)}))
        code, report, _ = run(tmp_path, manifest)
        assert code == 2
        assert any("no trigger edge" in e for e in report["errors"])


def test_grid_must_fit_inside_every_instrument_record():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = make_manifest(tmp_path)
        rewrite_manifest(manifest, lambda c: c["grid"].update({"pre_s": 400e-6}))
        code, report, _ = run(tmp_path, manifest)
        assert code == 2
        assert any("cover" in e for e in report["errors"])


def test_output_grid_may_not_be_finer_than_the_coarsest_record():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = make_manifest(tmp_path)
        rewrite_manifest(manifest, lambda c: c["grid"].update({"dt_s": 0.5e-6}))
        code, report, _ = run(tmp_path, manifest)
        assert code == 2
        assert any("fabricate" in e for e in report["errors"])


def test_declared_skew_budget_must_be_supported_by_sample_resolution():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = make_manifest(tmp_path)
        rewrite_manifest(manifest, lambda c: c["sync"].update(
            {"max_remaining_skew_s": 0.1e-6}))
        code, report, _ = run(tmp_path, manifest)
        assert code == 2
        assert any("skew budget" in e for e in report["errors"])


def test_declared_sample_rate_must_match_the_record():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = make_manifest(tmp_path)
        rewrite_manifest(manifest, lambda c: c["instruments"][1].update(
            {"sample_rate_hz": 2.0 / DT_S}))
        code, report, _ = run(tmp_path, manifest)
        assert code == 2
        assert any("sample rate" in e for e in report["errors"])


def test_non_monotonic_time_is_rejected():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = make_manifest(tmp_path)
        b = tmp_path / "scope_b.csv"
        write_instrument(b, SHIFT_B_S,
                         ("SR1A", "SR1B", "SR2A", "SR2B", "SR3A", "SR3B", "SR4A", "SR4B"),
                         "SYNC")
        lines = b.read_text(encoding="utf-8").splitlines()
        # Swap the time of rows 20 and 21, keeping the data rows intact.
        first, second = lines[20].split(","), lines[21].split(",")
        first[0], second[0] = second[0], first[0]
        lines[20], lines[21] = ",".join(first), ",".join(second)
        b.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rewrite_manifest(manifest, lambda c: c["instruments"][1].update({"csv": str(b)}))
        code, report, _ = run(tmp_path, manifest)
        assert code == 2
        assert any("strictly increasing" in e for e in report["errors"])


def test_nan_sample_is_rejected():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = make_manifest(tmp_path)
        b = tmp_path / "scope_b.csv"
        write_instrument(b, SHIFT_B_S,
                         ("SR1A", "SR1B", "SR2A", "SR2B", "SR3A", "SR3B", "SR4A", "SR4B"),
                         "SYNC")
        lines = b.read_text(encoding="utf-8").splitlines()
        row = lines[30].split(",")
        row[1] = "nan"
        lines[30] = ",".join(row)
        b.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rewrite_manifest(manifest, lambda c: c["instruments"][1].update({"csv": str(b)}))
        code, report, _ = run(tmp_path, manifest)
        assert code == 2
        assert any("finite" in e for e in report["errors"])


def test_ragged_csv_row_is_rejected():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = make_manifest(tmp_path)
        b = tmp_path / "scope_b.csv"
        write_instrument(b, SHIFT_B_S,
                         ("SR1A", "SR1B", "SR2A", "SR2B", "SR3A", "SR3B", "SR4A", "SR4B"),
                         "SYNC")
        lines = b.read_text(encoding="utf-8").splitlines()
        lines[30] = lines[30] + ",0.0"
        b.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rewrite_manifest(manifest, lambda c: c["instruments"][1].update({"csv": str(b)}))
        code, report, _ = run(tmp_path, manifest)
        assert code == 2
        assert any("ragged" in e for e in report["errors"])


def test_unreviewed_basis_still_aligns_but_returns_one():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = make_manifest(tmp_path)
        rewrite_manifest(manifest, lambda c: c["sync"].update(
            {"basis_review_status": "PENDING"}))
        code, report, out = run(tmp_path, manifest)
        assert code == 1
        assert report["status"] == "ALIGNED_PROVENANCE_INCOMPLETE"
        assert out.exists()
        assert report["checks"]["provenance_complete"] is False


def test_missing_probe_metadata_is_provenance_incomplete():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = make_manifest(tmp_path)
        rewrite_manifest(manifest, lambda c: c["instruments"][1].update(
            {"probe_model": "PENDING"}))
        code, report, _ = run(tmp_path, manifest)
        assert code == 1
        assert report["checks"]["provenance_complete"] is False


def test_reference_trigger_must_be_the_trip_stimulus_record():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = make_manifest(tmp_path)
        a = tmp_path / "scope_a.csv"
        write_instrument(a, 0.0, ("TRIP_STIMULUS", "P_HO", "P_LO"), "SYNC")
        rewrite_manifest(manifest, lambda c: c["instruments"][0].update(
            {"csv": str(a), "trigger": {**c["instruments"][0]["trigger"],
                                        "column": "SYNC"}}))
        code, report, _ = run(tmp_path, manifest)
        assert code == 2
        assert any("trigger column" in e for e in report["errors"])


def test_output_trip_edge_must_remain_unique_after_resampling():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = make_manifest(tmp_path)
        a = tmp_path / "scope_a.csv"
        # A second trip pulse is outside the narrow trigger search window but
        # still visible in the aligned record.
        write_instrument(a, 0.0, ("TRIP_STIMULUS", "P_HO", "P_LO"),
                         "TRIP_STIMULUS",
                         sync_wave=lambda p: 5.0 if (0 <= p < 10e-6) or p >= 30e-6 else 0.0)
        rewrite_manifest(manifest, lambda c: c["instruments"][0].update({
            "csv": str(a),
            "trigger": {**c["instruments"][0]["trigger"],
                        "search_start_s": -1e-6, "search_end_s": 1e-6},
        }))
        code, report, _ = run(tmp_path, manifest)
        assert code == 2
        assert any("trip edge" in e for e in report["errors"])


def test_target_columns_match_the_capture_auditor():
    assert m.TARGET_CHANNELS == ("TRIP_STIMULUS",) + audit.GATES


def test_duplicate_json_keys_are_rejected_instead_of_silently_collapsed():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = make_manifest(tmp_path)
        text = manifest.read_text(encoding="utf-8")
        text = text.replace('"P_HO": "P_HO"', '"P_HO": "P_HO", "P_HO": "P_LO"', 1)
        manifest.write_text(text, encoding="utf-8")
        code, report, out = run(tmp_path, manifest)
        assert code == 2
        assert any("duplicate JSON key" in e for e in report["errors"])
        assert not out.exists()


def test_two_source_columns_for_one_target_are_rejected():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = make_manifest(tmp_path)
        rewrite_manifest(manifest, lambda c: c["instruments"][0]["channels"].update(
            {"P_LO": "P_HO"}))
        code, report, _ = run(tmp_path, manifest)
        assert code == 2
        assert any("same target" in e for e in report["errors"])


def test_the_pending_template_can_never_align():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        template = (Path(__file__).resolve().parent.parent /
                    "docs/D1_EXECUTION_KIT/templates/d0_scope_sync_manifest_TEMPLATE.json")
        out = tmp_path / "aligned.csv"
        code = m.run(template, out, tmp_path / "alignment.json")
        assert code == 2
        assert not out.exists()


def test_invalid_alignment_does_not_write_an_output_csv():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = make_manifest(tmp_path)
        rewrite_manifest(manifest, lambda c: c["grid"].update({"pre_s": 400e-6}))
        out = tmp_path / "must_not_exist.csv"
        report_path = tmp_path / "alignment.json"
        code = m.run(manifest, out, report_path)
        assert code == 2
        assert not out.exists()
        assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "INVALID_ALIGNMENT"


def test_manifest_schema_rejects_unknown_edges_and_pending_rates():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = make_manifest(tmp_path)
        rewrite_manifest(manifest, lambda c: c["instruments"][0]["trigger"].update(
            {"edge": "sideways"}))
        code, report, _ = run(tmp_path, manifest)
        assert code == 2
        assert any("edge" in e for e in report["errors"])

        manifest = make_manifest(tmp_path)
        rewrite_manifest(manifest, lambda c: c["instruments"][0].update(
            {"sample_rate_hz": "PENDING"}))
        code, report, _ = run(tmp_path, manifest)
        assert code == 2
