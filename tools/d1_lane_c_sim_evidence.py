"""Read back remote LTspice *model-only* gate-loss evidence; never approve G0."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "design/v3/stage_f/d1_lane_c_g0"
STEM = "d1_lane_c_sr_gate_loss_illustrative_NOT_FOR_FAB"
DECK, LOG, ARCHIVE = (D / f"{STEM}.{suffix}" for suffix in ("cir", "log", "raw.gz"))
REPORT = D / "d1_lane_c_sr_gate_loss_model_receipt_NOT_FOR_FAB.json"

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def parse_value(v: str) -> float:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([npukm]?)", v, re.IGNORECASE)
    if not m:
        raise ValueError("SPICE value not accepted: " + v)
    factor = {"":1, "n":1e-9,"p":1e-12,"u":1e-6,"k":1e3,"m":1e-3}
    return float(m.group(1)) * factor[m.group(2).lower()]

def get_part(text: str, ref: str) -> list[str]:
    lines = [x.split() for x in text.splitlines()
             if x.split() and x.split()[0].lower() == ref.lower()]
    if len(lines) != 1:
        raise ValueError(ref + " missing/duplicated in model deck")
    return lines[0]

def parse_measure(log: str, ref: str) -> float:
    m = re.search(r"^" + re.escape(ref) + r":.*?\bAT\s+([\deE.+-]+)\s*$",
                  log, re.MULTILINE | re.IGNORECASE)
    if not m:
        raise ValueError(f"missing measure {ref}")
    return float(m.group(1))

def load(deckt: str, logt: str, raw: bytes, archived: bytes) -> dict:
    if "LTspice 26.0.2 for Windows" not in logt or "Total elapsed time:" not in logt:
        raise ValueError("LTspice 26.0.2 complete log required")
    if not raw.startswith(b"Title:") or b"No. Variables:" not in raw[:1000]:
        raise ValueError("raw waveform missing header")
    if "NOT_FOR_FAB" not in deckt or "HIGH-Z" not in deckt:
        raise ValueError("model caveat removed")
    cp = get_part(deckt, "Cpassive")
    cd = get_part(deckt, "Cdriven")
    rb = get_part(deckt, "Rpassive")
    ra = get_part(deckt, "Rdriver_sink_typ")
    rdb = get_part(deckt, "Rdriven_bleed")
    if cp[1:3] != ["GA_PASS", "0"] or cd[1:3] != ["GA_DRIVEN", "0"]:
        raise ValueError("gate model nodes changed")
    if rb[1:3] != ["GA_PASS", "0"] or ra[1:3] != ["GA_DRIVEN", "0"]:
        raise ValueError("gate model resistor nodes changed")
    c = parse_value(cp[3])
    if c != parse_value(cd[3]):
        raise ValueError("gate load mismatch")
    r_bleed = parse_value(rb[3])
    ractive = parse_value(ra[3])
    if parse_value(rdb[3]) != r_bleed:
        raise ValueError("gate bleed mismatch")
    source = float(cp[4].split("=",1)[1])
    if cd[4] != cp[4]:
        raise ValueError("different model initial voltages")
    thresh = 1.3  # only the SR VGS(th) minimum, NOT a measured safe-off limit
    predicted_passive = r_bleed*c*math.log(source/thresh)
    predicted_active = (r_bleed*ractive/(r_bleed+ractive))*c*math.log(source/thresh)
    measured_passive = parse_measure(logt,"passive_to_1p3")
    measured_active = parse_measure(logt,"driven_typ_to_1p3")
    for name, actual, pred in (("passive", measured_passive, predicted_passive),
                               ("driven_typ", measured_active, predicted_active)):
        if not math.isclose(actual, pred, rel_tol=0.015, abs_tol=1e-9):
            raise ValueError(f"{name} simulation measurement disagrees with RC formula")
    if gzip.decompress(archived) != raw:
        raise ValueError("raw gzip archive mismatch")
    return {
        "kind":"D1_LANE_C_GATE_LOSS_SIMULATION_ONLY",
        "status":"VALID_MODEL_RECEIPT_NOT_HARDWARE_PROOF",
        "remote_engine":"winsrv / LTspice 26.0.2 (log-readback, not hardware)",
        "deck_sha256":sha(deckt.encode("utf-8")),
        "log_sha256":sha(logt.encode("utf-8")),
        "raw_sha256":sha(raw),
        "raw_gzip_sha256":sha(archived),
        "raw_bytes":len(raw),
        "archive_bytes":len(archived),
        "source_voltage_v":source,
        "sr_dummy_gate_capacitance_f":c,
        "sr_bleed_ohm":r_bleed,
        "illustrative_driven_sink_ohm":ractive,
        "gate_threshold_for_screen_v":thresh,
        "passive_gate_fall_to_threshold_s":measured_passive,
        "illustrative_powered_sink_fall_to_threshold_s":measured_active,
        "rc_analytical_passive_s":predicted_passive,
        "rc_analytical_driven_s":predicted_active,
        "is_vendor_worst_case":False,
        "physical_sr_gate_safe_off_proven":False,
        "actual_loss_of_12vs_hardware_proven":False,
        "g0_approved":False,
        "g1_approved":False,
        "must_measure_independently":"All 8 SR VGS (actual source-referenced), 2 primary VGS, 12V bias collapse, permit release, dynamic third-quadrant current, temperature",
    }

def build() -> dict:
    if not all(f.is_file() for f in (DECK,LOG,ARCHIVE)):
        raise ValueError("model evidence file missing")
    deck_bytes = DECK.read_bytes()
    log_bytes = LOG.read_bytes()
    archived = ARCHIVE.read_bytes()
    raw = gzip.decompress(archived)
    result = load(deck_bytes.decode("utf-8"), log_bytes.decode("utf-8"), raw,
                  archived)
    # Bind exact on-disk bytes, not newline-normalized read_text() strings.
    result["deck_sha256"] = sha(deck_bytes)
    result["log_sha256"] = sha(log_bytes)
    return result

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write",action="store_true")
    group.add_argument("--check",action="store_true")
    args = parser.parse_args()
    report = build()
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.write:
        REPORT.write_text(text,"utf-8")
    elif not REPORT.exists() or REPORT.read_text("utf-8") != text:
        print("model receipt missing/stale",file=sys.stderr)
        return 1
    print(report["status"],report["passive_gate_fall_to_threshold_s"])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
