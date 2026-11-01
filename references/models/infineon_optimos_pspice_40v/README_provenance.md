# Provenance: Infineon OptiMOS6 40V SPICE archive (official)

Downloaded 2026-10-31 by the official-model scout task.

## Source

- URL (works without a fileId parameter):
  https://www.infineon.com/dgdl/Infineon-SimulationModel_OptiMOS_PowerMOSFET_PSpice_40V_N-Channel-SM-v01_00-EN.zip
- Publisher: Infineon Technologies, linked from the "Power MOSFET simulation models"
  promopage (https://www.infineon.com/cms/en/product/promopages/power-mosfet-simulation-models/,
  client-rendered; the archive itself is served by the dgdl document gateway).
- Local copy: `Infineon-SimulationModel_OptiMOS_PowerMOSFET_PSpice_40V_N-Channel-SM-v01_00-EN.zip`
- sha256: 345f0cc2198a8f9890be5eba736483c2a7a82951ae2dad8f664a0888191344ba
- Archive members: 34; family folders OptiMOS3/5/6/7 and StrongIRFET, each with
  Cadence_PSpice, LTSpice and plain Spice .lib variants plus ReadMe PDFs, and the
  application note "Introduction to Infineons Simulation Models for Power MOSFETs".

## Extracted files (verbatim members, unmodified)

| file | member | bytes | sha256 |
|---|---|---|---|
| OptiMOS6_40V_LTSpice.lib | OptiMOS6/OptiMOS6_40V_LTSpice.lib | 159473 | 1703d0fc995cd102a9cbf1f50bc67d8c17f75eec89f4886b0941ea2fcc0b1f9b |
| OptiMOS6_40V_Spice.lib | OptiMOS6/OptiMOS6_40V_Spice.lib | 159446 | 197dc54cecda1b047665d3f1f30fdc90ad4889681734b3bc5a56df030b0a1b85 |

Zip member timestamp of OptiMOS6_40V_LTSpice.lib: 2026-07-31 17:25:32.
Library header: "Level1/3 LTSPICE Library for OptiMOS6 40V", "Version 310726"
(the header code matches the 31.07.2026 member date; no separate date is printed).

## Content check for BSC010N04LS6

The library lists BSC010N04LS6 in its header product table and defines:

- `.SUBCKT BSC010N04LS6_L1 drain gate source PARAMS: ...` (Level 1, constant temperature)
- `.SUBCKT BSC010N04LS6 drain gate source Tj Tcase PARAMS: ...` (Level 3, self-heating)
- `.SUBCKT BSC010N04LS6_L0 drain gate source` (Level 0 simplified, LEVEL=3 NMOS)

All three are plain ASCII text. No encryption or obfuscation.

## Notes

- Files here are vendor data, not project code. Do not edit them; re-download and
  re-hash if a newer archive is needed.
- `L1_default_solver_failure.txt` is the LTspice log of `sim/v2/model_probe.cir`
  run without the alternate solver (convergence failure at the first time step).
- `OptiMOS6_40V_Spice.lib` was kept only to test whether the plain-Spice variant
  behaves differently; it fails with the same internal node.
- `diagnostics/` holds the auxiliary runs quoted in
  `design/v2/official_model_report.md`: L3 with `-alt`, L0 turn-off with the
  default solver, and the L0 saturation point. They are logs of runs, not models.
