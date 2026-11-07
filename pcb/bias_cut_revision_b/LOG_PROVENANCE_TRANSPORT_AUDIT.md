# Revision B / T3 LTspice 26.0.2 evidence transport audit

**Status: MODEL_RECORDED_MEASUREMENTS_CHECKABLE; ORIGINAL_RAW_LOG_BYTES_NOT_FULLY_RECOVERED; NOT_FOR_FAB.** This is a source provenance repair, not new simulation or physical protection proof.

## Exact confirmed distinction

- `.cir` input decks were simulated in Windows with CRLF line endings. The Git checkout uses LF. For the entire `startup.cir`, the committed LF SHA-256 is `045b77fa9bd9a81a9b1a77b0aa6225bdc1553ebea4d3409005ea5f6f7b5f026e`; converting only line endings to Windows CRLF yields exactly the original report SHA-256 `188430565d13c275730a4d07fee971fa50ee7b6023a1522c996cd753b6c0bd95`.
- `.log` files are **not** generally byte-identical to the original reporter SHA after either LF or all-CRLF conversion. This repository does **not** hold verifiable identical original bytes for those original Windows reports. Do NOT rewrite the historic `log_sha256` fields or assert an exact raw-log reconstruction.
- The full text of all 10 Revision-B and 8 T3 input decks is checked against its source generator. For log evidence we compare every parsed `.meas` key and numeric value from the **committed log text** to the historic JSON report. If any measurement differs or is missing, testing fails. This is strictly less than original byte-identical log verification, and is labelled accordingly.
- `tools/ltspice_windows_evidence.py` separates `original_windows_deck_sha256` (for exact historical input), `actual_file_sha256` (current Git transport bytes) and `verify_committed_log_measurements` (typed text-value identity plus explicit raw-log availability flag). No test fakes results by writing `report.json` or `timing_report.json`.

## Reproduce

```bash
python -m pytest -q tools/test_ltspice_windows_evidence.py tools/test_bias_cut_revision_b.py tools/test_bias_cut_timing.py
```

To recover **true raw-byte provenance**, retrieve the original LTspice `.log` files directly from the Windows host that ran the Nov 7 simulation (or rerun the unchanged exact `.cir` files in the vendor LTspice and retain both raw log and checksum). Then add those as explicitly versioned *new* evidence; never overwrite historic hashes without a documented new simulation.

## Electrical implications unchanged

- Rev-B Q50 and R59 are still candidate parts, no OEM full SOA / thermal PCB signoff; under a forced 5 V loss the timing model predicts residual SR VDD around 3.81 V at +6ms, above a possible REG UVLO turn-off floor. **Neither a passing numerical status nor a passing evidence transport test certifies 8 physical SR gates are off.**
- D0 10-way fault shutdown, magnetic DOT, 100A PCB ampacity and 15 V eFuse / active reverse-aware discharge need separate independent hardware evidence.

