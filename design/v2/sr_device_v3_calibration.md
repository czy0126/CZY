# BSC010N04LS6 Datasheet Calibration Extraction (for sr_device_v3.lib)

Date: 2026-10-31
Device: Infineon BSC010N04LS6, OptiMOS 6, 40 V N-channel, PG-TDSON-8 FL
Datasheet: Rev. 2.3, 2022-07-21, `references/datasheets/bsc010n04ls6.pdf`
Text extract: `references/datasheets/bsc010n04ls6.txt`

Purpose: traceable calibration input for the SR MOSFET stand-in model. No model is built or
modified in this task. Every number below is either read from a datasheet table or digitized
from a datasheet diagram; nothing is from memory of generic MOSFETs.

## Digitization method and validation

- Pages rendered at 600 dpi with `pdftoppm`; plot frames and grid lines located by pixel scan.
- Diagram 8: x = 180.0 px/V, y = 716.8 px/mOhm (grid 0.4 V / 0.1 mOhm).
- Diagram 11/12: y = 669.0 px/decade (log), 45.0 px/V (Diagram 11) and 1200 px/V (Diagram 12).
- Diagram 9/10: y = 1003 px/unit (D9), 835 px/unit (D10); x = 6.4286 px/degC.
- Diagram 14: x = 25.714 px/nC, y = 200.75 px/V.
- Curve pixels are separated from the 50% grey grid by intensity (curve < 80, grid = 128).

Calibration cross-checks (digitized vs datasheet table):

| Check | Digitized | Table | Page |
|---|---|---|---|
| RDS(on) at VGS=10 V, ID=50 A, 25 C | 0.893 mOhm | typ 0.89 mOhm | D8 p7 / T4 p4 |
| Ciss at VDS=20 V | 4640 pF | typ 4600 pF | D11 p8 / T5 p4 |
| Coss at VDS=20 V | 1504 pF | typ 1500 pF | D11 p8 / T5 p4 |
| Crss at VDS=20 V | 38.5 pF | typ 38 pF | D11 p8 / T5 p4 |
| RDS(on) normalized at Tj=25 C | 1.00 | 1.00 by definition | D9 p8 |

The agreement is within ~1 %, which validates the axis calibration. Curve line width gives
about +/-3 % on log-diagram capacitance values and +/-0.02 mOhm on flat RDS(on) regions;
steep regions are worse and are flagged.

## 1. Static characteristics (Table 4, p4; Table 7, p5)

| Parameter | Min | Typ | Max | Unit | Test condition | Source |
|---|---|---|---|---|---|---|
| V(BR)DSS | 40 | - | - | V | VGS=0 V, ID=1 mA, Tj=25 C | T4 p4 |
| VGS(th) | 1.3 | - | 2.3 | V | VDS=VGS, ID=250 uA, Tj=25 C | T4 p4 |
| VGS(th) typ (derived) | - | 1.65 | - | V | D10 p8, 250 uA curve, Tj=25 C | digitized |
| RDS(on) @ VGS=10 V | - | 0.89 | 1.0 | mOhm | ID=50 A, Tj=25 C | T4 p4 |
| RDS(on) @ VGS=4.5 V | - | 1.1 | 1.4 | mOhm | ID=50 A, Tj=25 C | T4 p4 |
| RDS(on) @ 125 C, 10 V (derived) | - | 1.32 | - | mOhm | ID=50 A | D8 + D9 p7/p8 |
| RDS(on) @ 125 C, 4.5 V (derived) | - | 1.70 | - | mOhm | ID=50 A | D8 + D9 p7/p8 |
| gfs | - | 250 | - | S | \|VDS\| >= 2\*\|ID\|\*RDS(on)max, ID=50 A | T4 p4 |
| RG (internal gate R) | - | 1 | - | Ohm | not specified | T4 p4 |
| IDSS @ Tj=25 C | - | 0.1 | 1 | uA | VDS=40 V, VGS=0 V | T4 p4 |
| IDSS @ Tj=125 C | - | 10 | 100 | uA | VDS=40 V, VGS=0 V | T4 p4 |
| IGSS | - | 10 | 100 | nA | VGS=20 V, VDS=0 V | T4 p4 |

Notes:
- The datasheet does not tabulate VGS(th) typ; 1.65 V is digitized from Diagram 10 (p8), which
  plots typical VGS(th) with ID as parameter. Uncertainty +/-0.05 V.
- The table specifies RDS(on) only at Tj=25 C. The 125 C values are derived by multiplying the
  Diagram 8 25 C values (0.893 / 1.147 mOhm) by the Diagram 9 normalized factor at 125 C
  (1.48). Using the table typ (0.89 / 1.1) instead gives 1.32 / 1.63 mOhm; the 4.5 V case is
  therefore a 1.63-1.70 mOhm range. The temperature factor is specified at VGS=10 V only, so
  applying it at 4.5 V is an approximation (see JSON `kind: digitized`, note).
- No RDS(on) max at 125 C is published. Estimates applying the 25 C max/typ ratio to the
  125 C factor: 1.48 mOhm (10 V) and 2.07 mOhm (4.5 V), marked `estimate` in the JSON.

## 2. RDS(on) vs VGS at ID=50 A (Diagram 8, p7)

Digitized from Diagram 8 (parameter Tj = 25 C and 175 C; the datasheet diagram does not show
125 C). Values in mOhm.

| VGS [V] | 25 C | 175 C | Note |
|---|---|---|---|
| 2.5 | off-chart (>2.8) | off-chart (>2.8) | Both traces leave the top of the chart below ~3.1 V |
| 3.0 | 2.65 +/-0.20 | off-chart (>2.8) | 25 C trace is near-vertical here (2.5-2.8 mOhm over 2.96-3.04 V) |
| 3.5 | 1.52 +/-0.04 | 2.40 +/-0.04 | |
| 4.0 | 1.27 +/-0.03 | 2.14 +/-0.03 | |
| 4.5 | 1.15 +/-0.03 | 1.99 +/-0.03 | Table typ at 4.5 V, 25 C is 1.1 (1.15 from diagram) |
| 6.0 | 0.973 +/-0.02 | 1.78 +/-0.02 | |
| 8.0 | 0.925 +/-0.02 | 1.67 +/-0.02 | |
| 10.0 | 0.893 +/-0.02 | 1.62 +/-0.02 | |

Cross-check: 175 C / 25 C ratio at 10 V = 1.82, equal to Diagram 9 at 175 C (1.815).

Because RDS(on) is undefined when ID=50 A cannot be supported (VGS below ~3.1 V), the SR model
must use transfer-characteristic behaviour there, not extrapolated RDS(on). At the intended
SR gate drive (>=4.5 V) the curve is well behaved.

## 3. RDS(on) vs Tj, normalized to 25 C (Diagram 9, p8)

Condition: ID=50 A, VGS=10 V.

| Tj [C] | -40 | 0 | 25 | 50 | 75 | 100 | 125 | 150 | 175 |
|---|---|---|---|---|---|---|---|---|---|
| RDS(on)/RDS(on,25C) | 0.79 | 0.91 | 1.00 | 1.10 | 1.21 | 1.34 | 1.48 | 1.64 | 1.82 |

Uncertainty +/-0.02. This is the only temperature scaling published; no separate curve at
VGS=4.5 V is given.

## 4. Capacitances (Table 5, p4; Diagram 11, p8)

Specified values at VDS=20 V, VGS=0 V, f=1 MHz:

| Parameter | Min | Typ | Max | Unit | Source |
|---|---|---|---|---|---|
| Ciss | - | 4600 | 6000 | pF | T5 p4 |
| Coss | - | 1500 | 2000 | pF | T5 p4 |
| Crss | - | 38 | 66 | pF | T5 p4 |
| Qoss | - | 73 | 97 | nC | T6 p4 (VDD=20 V, VGS=0 V) |

Digitized from Diagram 11 (typical, VGS=0 V, f=1 MHz). Ciss values are included because the
diagram supports them; the table above is the authoritative 20 V point.

| VDS [V] | Ciss [pF] | Coss [pF] | Crss [pF] | Note |
|---|---|---|---|---|
| 0.5 | 5380 | 6900 | 783 | |
| 1 | 5300 | 6600 | 700 | |
| 2 | 5200 | 6125 | 604 | |
| 5 | ~4950 (merged) | ~4950 (merged) | 406 | Ciss and Coss cross near 4.5-5 V; the two traces merge within one line width |
| 10 | 4790 | 3400 | 192 | |
| 20 | 4640 | 1504 | 38.5 | matches table typ within 1 % |
| 40 | not plotted | not plotted | 27 | Ciss/Coss traces stop at ~37-38 V where the labels sit; extrapolated Ciss ~4600, Coss ~860 (see JSON, +/-10 %) |

Uncertainty: +/-3 % for separated traces; +/-10 % at 5 V (merged) and at 40 V (extrapolated).
The Coss maximum (2000 pF at 20 V) is a production limit, not plotted as a curve.

## 5. Gate charge (Table 6, p4; Diagram 14, p9)

Table 6 conditions: VDD=20 V, ID=50 A, VGS=0 to 10 V, Tj=25 C (unless stated).

| Parameter | Min | Typ | Max | Unit | Test condition | Source |
|---|---|---|---|---|---|---|
| Qgs | - | 12 | - | nC | VDD=20 V, ID=50 A, 0-10 V | T6 p4 |
| Qg(th) | - | 7.3 | - | nC | VDD=20 V, ID=50 A, 0-10 V | T6 p4 |
| Qgd | - | 8.1 | 12 | nC | VDD=20 V, ID=50 A, 0-10 V | T6 p4 |
| Qsw | - | 13 | - | nC | VDD=20 V, ID=50 A, 0-10 V | T6 p4 |
| Qg (0-10 V) | - | 67 | 83 | nC | VDD=20 V, ID=50 A | T6 p4 |
| Vplateau | - | 2.7 | - | V | VDD=20 V, ID=50 A | T6 p4 |
| Qg (0-4.5 V) | - | 32 | - | nC | VDD=20 V, ID=50 A | T6 p4 |
| Qg(sync) | - | 28 | - | nC | VDS=0.1 V, VGS=0-4.5 V | T6 p4 |

Diagram 14: VGS=f(Qgate), ID=50 A pulsed, Tj=25 C, parameter VDD = 8 V / 20 V / 32 V.
The three VDD traces lie within about one line width at low charge and separate by at most
~0.35 V at Qg>=30 nC (about 2 nC horizontally); the individual VDD traces are NOT separately
legible. The table below is the envelope read from the diagram, midpoint of the resolved
traces. Treat each VGS as +/-0.10 V (envelope half-width; the envelope itself spans the three
VDD values).

| Qgate [nC] | VGS low [V] | VGS high [V] | VGS midpoint [V] |
|---|---|---|---|
| 0 | 0.03 | 0.05 | 0.04 |
| 5 | 0.99 | 1.14 | 1.06 |
| 8 | 1.60 | 1.77 | 1.68 |
| 10 | 2.02 | 2.22 | 2.12 |
| 12 | 2.43 | 2.65 | 2.55 |
| 15 | 2.62 | 2.70 | 2.66 |
| 18 | 2.62 | 2.70 | 2.66 |
| 20 | 2.64 | 2.79 | 2.72 |
| 22 | 2.88 | 3.11 | 3.00 |
| 25 | 3.33 | 3.53 | 3.43 |
| 30 | 4.08 | 4.42 | 4.27 |
| 35 | 4.87 | 5.21 | 5.05 |
| 40 | 5.69 | 6.00 | 5.86 |
| 45 | 6.47 | 6.80 | 6.63 |
| 50 | 7.25 | 7.59 | 7.40 |
| 55 | 8.05 | 8.38 | 8.23 |
| 60 | 8.84 | 9.18 | 9.02 |
| 65 | 9.68 | 9.97 | 9.82 |

Derived from the digitized curve (consistency checks against the table):
- Plateau = 2.66 V (table Vplateau 2.7 V); plateau spans Qg ~12 to ~21 nC (Qgs=12, Qgs+Qgd=20.1).
- VGS=4.5 V reached at Qg ~31-33 nC (table Qg 0-4.5 V = 32 nC).
- VGS=10 V reached at Qg ~66-67 nC (table Qg 0-10 V = 67 nC).
- Post-plateau slope dVGS/dQg ~0.163 V/nC (equivalent to ~6.1 nF gate-charging capacitance);
  pre-plateau slope ~0.22 V/nC (~4.5 nF).

## 6. Body diode (Table 7, p5; Diagram 12, p8)

| Parameter | Min | Typ | Max | Unit | Test condition | Source |
|---|---|---|---|---|---|---|
| IS (continuous) | - | - | 150 | A | TC=25 C | T7 p5 |
| IS,pulse | - | - | 1140 | A | TC=25 C | T7 p5 |
| VSD | - | 0.80 | 1.0 | V | VGS=0 V, IF=50 A, Tj=25 C | T7 p5 |
| trr | - | 30 | 60 | ns | VR=20 V, IF=10 A, diF/dt=400 A/us | T7 p5 |
| Qrr | - | 97 | 194 | nC | VR=20 V, IF=10 A, diF/dt=400 A/us | T7 p5 |

Diagram 12 digitization (IF=f(VSD), parameter Tj; solid 25 C, long-dash 25 C max, short-dash
175 C, dotted 175 C max):
- At IF=50 A, 25 C: 0.79 V, consistent with the table typ 0.80 V.
- At IF=50 A, 175 C: ~0.61 V from the short-dash trace (+/-0.03 V); the dashed curves have
  gaps and the max traces are not reliably separable at this row.
- 25 C max at IF=50 A: ~1.0 V (table limit; diagram trace at ~1.00 V).
- trr/Qrr are only in the table; the datasheet does not plot reverse recovery.

## 7. Thermal and package (Tables 2 and 3, p3)

| Parameter | Min | Typ | Max | Unit | Condition | Source |
|---|---|---|---|---|---|---|
| RthJC (junction-case, bottom) | - | - | 1.0 | C/W | - | T3 p3 |
| RthJC (junction-case, top) | - | - | 20 | C/W | - | T3 p3 |
| RthJA | - | - | 50 | C/W | 6 cm2 Cu, 40x40x1.5 mm FR4, still air | T3 p3 |
| Tj, Tstg | -55 | - | 175 | C | - | T2 p3 |
| Ptot | - | - | 150 (TC=25 C) / 3.0 (TA=25 C) | W | - | T2 p3 |
| Package | PG-TDSON-8 FL (enlarged source interconnection); drain 5-8, gate 4, source 1-3 | | | | | p1 |

## 8. Package parasitic inductances - ESTIMATE, NOT DATASHEET

The BSC010N04LS6 datasheet contains no package inductance values. The following ranges are an
engineering estimate for the PG-TDSON-8 FL (5x6 mm class) with an enlarged (ribbon/clip) source
interconnect, derived from geometry (bond/clip length ~1-2 mm, ~0.8-1.2 nH per mm for a single
conductor, divided by the number of parallel source connections) and typical PQFN 5x6 values.
They are NOT measured and NOT from the datasheet; treat as +/-factor 2.

| Element | Estimate range | Basis |
|---|---|---|
| L_source, package (pins 1-3 to die) | 0.4 - 1.2 nH | multiple parallel source bonds / enlarged source clip |
| L_drain, package (tab) | 0.15 - 0.5 nH | large-area clip/tab connection |
| L_gate, package (pin 4) | 1.5 - 3.5 nH | single small bond wire |
| Effective L_source including PCB Kelvin return | 0.7 - 2.5 nH | package plus 1-3 mm of layout return, ~0.3-0.5 nH/mm |

Use these only as a sensitivity range in the SR commutation model (the current v2 result's
largest unquantified term). They must be replaced by measurement or vendor data before sign-off.

## 9. Uncertainty register (what the datasheet does not settle)

1. RDS(on) at VGS=2.5 V and 3.0 V is off the Diagram 8 chart at 25 C and 175 C; no value exists
   to digitize. The 25 C 3.0 V point (2.65 mOhm) sits on a near-vertical trace and is only
   +/-0.2 mOhm meaningful. Do not extrapolate RDS(on) below ~3.1 V; use transfer behaviour.
2. Ciss and Coss merge near VDS=5 V; only the sum is legible (~4950 pF). Individual split is
   unknown.
3. Ciss/Coss curves stop at ~37-38 V where the labels are placed; the 40 V values are
   extrapolations, not plotted points. Crss is plotted to 40 V (27 pF).
4. The three Diagram 14 VDD traces (8/20/32 V) are not individually legible; only the envelope
   is digitized. The 20 V trace cannot be assigned with confidence.
5. 125 C RDS(on) is derived, not tabulated; the temperature factor is published only for
   VGS=10 V. No 125 C max exists.
6. All RDS(on), capacitance and gate-charge values except the stated maxima are typical values;
   no distribution/spread data is published.
7. Package inductances are estimates only (Section 8).
8. Diagram 12 dashed/dotted max traces are partially illegible at IF=50 A; only the 25 C typ
   (table-confirmed) and the 175 C typ are usable.

## 10. Files

- Machine-readable: `design/v2/sr_device_v3_calibration.json`
- This document: `design/v2/sr_device_v3_calibration.md`
