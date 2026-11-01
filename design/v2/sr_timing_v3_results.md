# SR_TIMING v3 results: corrected arbitration, blanking, short-pulse and pre-arm behaviour

Date 2026-10-31. Scope: `models/sr_timing_v3.lib` (new corrected copy) and the
`sim/v2/sr_timing_v3_checks_*.cir` decks. **`models/sr_timing_v2.lib` was not modified**
(sha256 starts `412e07a9256576d0`, identical to the audit hash). This is an engineering <!-- hash-owner: models/sr_timing_v2.lib -->
surrogate of the UCC24624 digital sequencing, **not TI silicon and not a guaranteed-silicon
model**. A PASS below means the measured gate/flag behaviour matches the stated expectation
for that case; a numerically completed run alone is not a PASS.

Tool: LTspice 26.0.2, `-b`, Normal solver, 27 C. Every v3 deck below was run with:

```
cd "D:/workshop/design_48v-2v"
rm -f sim/v2/NAME.log sim/v2/NAME.raw
timeout 180 "D:/ADI/LTspice/LTspice.exe" -b "sim/v2/NAME.cir"
```

Independent verification of every v3 deck: the `.log` exists, contains `Total elapsed time`,
contains no line with `Error:`, `Time step too small`, `Singular matrix`, `Analysis failed`,
`Voltage not found` or `Measurement failed`, and every `.meas` declared in the deck appears
in the log with a numeric value (checked by script, see section 8).

## 1. Files delivered

| File | sha256 (first 16) | Purpose |
|---|---|---|
| `models/sr_timing_v3.lib` | `5099df9183b0e060` | corrected SR timing/interlock surrogate |
| `sim/v2/sr_timing_v3_checks_normal.cir` | `846a7e9a51e3b20f` | normal alternating operation |
| `sim/v2/sr_timing_v3_checks_simultaneous.cir` | `77f502cac86a76d7` | exact simultaneous requests (3 events) |
| `sim/v2/sr_timing_v3_checks_skew.cir` | `c417f0bd244a4a68` | 50 ns and 5 ns skew, both directions |
| `sim/v2/sr_timing_v3_checks_shortpulse.cir` | `939f37cbcd2bbc60` | 100 ns filtered, 300 ns control passes |
| `sim/v2/sr_timing_v3_checks_offblank_retrigger.cir` | `6ea188bb55f8f7ea` | re-trigger inside off-blank, incl. near-boundary dip |
| `sim/v2/sr_timing_v3_checks_onblank.cir` | `1974a63d745acc47` | 475 ns on-blank ignores VD, no extension |
| `sim/v2/sr_timing_v3_checks_interlock.cir` | `bad7ec966c0e3e1f` | loser pulse inside winner blank rejected, not queued |
| `sim/v2/sr_timing_v3_checks_reg_first_negative.cir` | `ef4ba0d5e83a8cea` | REG-first unsupported order |
| `sim/v2/sr_timing_v3_checks_fastreg20.cir` | `eb79c370a7b79af7` | 20 ns REG ramp with qualifying VD |
| `sim/v2/sr_timing_v3_checks_fastreg5.cir` | `e92c5d1f333ec740` | 5 ns REG ramp with qualifying VD (stress) |
| `sim/v2/sr_timing_v3_checks_noarb_negative.cir` | `d750bba9859df27f` | negative control: arbitration removed -> double-on detected |
| `sim/v2/sr_timing_v3_checks_v2top_diag.cir` | `2042d2d9ef736f04` | v2 baseline (read-only include) |
| `sim/v2/sr_timing_v3_checks_v2qrace_diag.cir` | `36c94e7193d4590f` | v2 with BLOCK removed (expected failure) |
| `sim/v2/verify_offblank_boundary.cir` | `a9989b0dfa200617` | fast-rise off-blank boundary, re-trigger longer than TON (C14) |
| `sim/v2/verify_offblank_delayed_arm.cir` | `0288ffa8f38462b6` | delayed VD>ARM crossing anchors the off-blank (C15) |

Pins kept: `D1 D2 G1 G2 REG S PRE`. Parameters kept: `TON TOFF BON BOFF ARM ONTH OFFTH PGD TAU`
(same meanings as v2: `TON`=155 ns turn-on delay, `TOFF`=23 ns turn-off delay, `BON`=475 ns
on-blank, `BOFF`=650 ns off-blank).

## 2. Case-by-case PASS/FAIL

| ID | Case | Stated expectation | Measured (from `.log`) | Verdict |
|---|---|---|---|---|
| C1 | Normal alternating, 4 conduction intervals | one gate pulse per channel per interval, order 1-2-1-2, no overlap, PRE set | g1=g2=10.8905 V; rises 4.1767 / 8.1767 us (CH1) and 6.1767 / 10.1767 us (CH2); `overlap_max=0`, `overlap_width_us=0`; `pre_final=0.99999`; `viol=0` | **PASS** |
| C2 | Exact simultaneous request at 4.01, 7.01, 10.01 us (independent but identical PWL) | exactly one channel asserts after TON; CH1 wins exact tie; loser latch never sets; no overlap; repeated 3x | `gate1_max=10.8884 V`, `gate2_max=0`; CH1 rises 4.1765 / 7.1765 / 10.1765 us; `q1_max=1`, `q2_max=0`, `a1_max=1`, `a2_max=0`; `pulses2=0`; `overlap_width_us=0` | **PASS** |
| C3 | Skew: CH2 first 50 ns, CH1 first 50 ns, CH2 first 5 ns, CH1 first 5 ns | first requester wins in every direction; no overlap; no chatter | E1 `g1=0, g2=10.8901`; E2 `g1=10.8884, g2=0`; E3 `g1=0, g2=10.8884`; E4 `g1=10.8884, g2=5.4e-40`; `overlap_max=0`, `overlap_width_us=0` | **PASS** |
| C4 | 100 ns short pulse at 4.01 us, then 300 ns control pulse at 6.01 us | 100 ns pulse produces no gate; 300 ns pulse passes | `early_max=0` V over 4.0-5.9 us; `early_false_pulses=0`; only gate rise at 6.1767 us; `gate1_max=10.8884 V` | **PASS** |
| C5 | Off-blank re-trigger: dips at turn-off+186 ns and +557 ns (both inside 650 ns), then a real edge after blank | dips produce no gate and are not queued; real edge after blank gates | Q1 falls at 4.6635 us; next Q1 rise at 5.7649 us (1.1014 us later, >= 650 ns); `retrig_max=0.0151 V` over 4.8-5.55 us; `retrig_false_pulses=0` | **PASS** |
| C6 | On-blank: VD rises above OFFTH 146 ns after Q, then again after the blank | VD ignored during 475 ns; no turn-off; blank not extended; next pulse gets its own blank | Q1 rise 4.1649 us, fall 4.7252 us; `gate_min_blank1=9.82 V` (stays on through the 4.31 us crossing); turn-off at 4.7252 us (< 4.808 us that a restart would give); second pulse same: rise 6.1649, fall 6.7252, `gate_min_blank2=10.70 V` | **PASS** |
| C7 | Loser pulse 100 ns wide inside winner's on-blank, then winner off; later legitimate loser conduction | loser pulse rejected, not queued; later real edge works | `winner_g1_max=10.8905 V`; `loser_g2_max=0` over 4.2-5.9 us; `loser_false_pulses=0`; later `g2_rise1=6.1767 us`; `overlap_width_us=0` | **PASS** |
| C8 | REG-first: REG reaches 11 V at 0.2 us, first VD>1.5 V at 1.0 us | PRE stays 0, violation latched, no gate | `pre_final=0`, `viol_final=1`, `gate1_max=0`, `gate2_max=0`, `q1_max=q2_max=0` | **PASS** |
| C9 | Fast REG: 20 ns 0->11 V ramp, VD=4 V already present | PRE=1, no violation, normal gate | `pre_final=0.99941`, `viol_final=0`, `gate1_max=10.8885 V` at 4.1768 us | **PASS** |
| C10 | Fast REG stress: 5 ns 0->11 V ramp, VD=4 V present | PRE latches, no violation, normal gate | `pre_final=0.83205`, `viol_final=0`, `gate1_max=10.8884 V` at 4.1768 us | **PASS** |
| C11 | Negative control: arbitration pins tied low, identical simultaneous request | BOTH gates must assert (proves the bench detects a real double-on) | `gate_a_max=gate_b_max=10.8884 V`, `overlap_max=1`, `qa_max=qb_max=1` | **PASS (negative control)** |
| C12 | v2 baseline diagnostic (`v2top_diag`) | v2's "CH2 off" is structural, not arbitration | `gate1_max=10.8885`, `gate2_max=0`, `q1=1`, `q2=0`, **`req2_max=0`** while `req1_max=1` | diagnostic |
| C13 | v2 with BLOCK patch removed (`v2qrace_diag`) | v2 has no arbitration; expected numerical failure | `Convergence Failure: Time step too small; time = 4.16494e-06 ... node "reqa"`; `Simulation Failed` | **EXPECTED FAILURE (v2 deficiency)** |
| C14 | `verify_offblank_boundary`: fast drain rise, ARM crossing (4.6250 us) while Q is still high; retrigger low pulses longer than TON at TD=4.7/4.8/4.9/5.0/5.2/5.4 us | blank starts at the Q falling edge (conservative), expires at 5.3141 us; pulses ending before 5.4685 us produce no gate; later pulses gate after expiry | `arm_t=4.6250 us`, `qfall=4.6635 us`, `off_t01=4.7641 us`, `off_t065=5.3141 us`; `g1r2` failed for TD=4.7/4.8/4.9 (pulses end 5.21/5.31/5.41 us, before 5.4685 us); gate rises 5.4815 us for TD=5.0/5.2 (= expiry+155 ns+edge) and 5.5767 us for TD=5.4 (= 5.41+155 ns+edge) | **PASS** |
| C15 | `verify_offblank_delayed_arm`: slow drain rise, ARM crossing (5.0281 us) **after** the Q falling edge (4.8895 us) | blank starts at the VD>1.5 crossing, not the gate edge; expiry 5.6781 us; gate after expiry+TON | `arm_t=5.0281 us`, `qfall=4.8895 us`, `off_t01=5.1288 us`, `off_t065=5.6788 us` (anchor+0.1007/+0.6507 us, i.e. 138.6 ns after the gate fall); gate rises 5.8463 us for TD=5.35/5.50, 5.8767 us for TD=5.70 (request 5.71>expiry), 5.9767 us for TD=5.80 | **PASS (delayed-ARM anchor confirmed)** |

C13 is deliberately a failing deck: it is the negative evidence for v2, not a v3 PASS. Its log
does contain `Total elapsed time` but also `Time step too small`; that is the point of the record.

## 3. v2 vs v3 comparison (measured in this session)

| Behaviour | v2 measured / structure | v3 measured / structure |
|---|---|---|
| Exact simultaneous request, top level | `g1=10.8885, g2=0, q1=1, q2=0, req1=1, req2=0` (`v2top_diag`). CH2's request is forced to 0 by the undocumented `BLOCK=req1` wire, not by arbitration | `g1=10.8884, g2=0, q1=1, q2=0, a1=1, a2=0`. CH1 wins through the explicit arbitration latch; CH2's raw request exists but its grant is blocked (`a2` never rises) |
| Simultaneous request with the `BLOCK` patch removed | Convergence failure, `Time step too small`, time 4.16494e-06, node `reqa` (`v2qrace_diag`); audit saw the same at 1.1651e-06 | Deterministic, converges, exactly one gate every event (C2) |
| Skew 5/50 ns, both directions | Not tested in v2; worked only by a ~1 ns analog race | First requester wins in all four events (C3) |
| Loser request during winner conduction | v2 `Bton` counts while `req` is high even though `OTHER>0.5` blocks Q, so a loser pulse can be "saved up" | v3 `R` includes `!OQ & !OA`, so the on-delay timer resets while blocked; measured `loser_false_pulses=0` and no gate after the winner (C7) |
| Off-blank anchor | Timer counted after a latched `armstate`; a later VD>1.5 crossing did not restart it and there was no explicit turn-off anchor in the documentation | Timer and arm both reset while Q is high; while Q is low the timer runs once VD>ARM, so the start is the **later** of the Q falling edge and the VD>ARM crossing. Slow drain rise (`verify_offblank_delayed_arm`) starts at the ARM crossing exactly, 138.8 ns after the gate fell; fast rise (`verify_offblank_boundary`) starts at the gate fall, 38.6 ns after the ARM crossing, i.e. later than the datasheet anchor and therefore conservative |
| On-blank 475 ns | `age>BON` (audit confirmed this is the manual's on-blank, not an off-blank bug) | Kept; made explicit and tested: VG stays 9.82-10.70 V through VD crossings inside the blank, turn-off only after the blank (C6) |
| Pre-arm window | `(1 V, 4.5 V)`, 4.5 V = typ VREGON; 1 V floor undocumented; no violation flag | `(0.1 V, 4.1 V)`, 4.1 V = VREGON(min), no 1 V floor; explicit violation latch; 20 ns ramp PRE=0.9994, 5 ns ramp PRE=0.832 (C8-C10) |

## 4. Exact behavioural equations changed

Notation: `Q` = gate state, `A` = arbitration ownership latch, `arm` = re-arm latch,
`off` = off-blank timer (us), `ton` = turn-on delay timer (us), `age` = on-time timer (us),
`toff` = turn-off delay timer (us), `RQ` = raw request, `R` = eligible request.

### 4.1 Arbitration (requirement 1)

v2 (`SR_CH` + top level), no arbitration state:

```
Brequest req = (BLOCK>0.5) ? 0 : (D<ONTH & Q<0.5 & OTHER<0.5 & tarm>BOFF & OK)
Bq: if OTHER>0.5 then reset Q
top: X2 BLOCK = req1          // undocumented fixed priority patch
```

v3 `SR_CH3`, explicit latch (SECOND=0 for CH1, SECOND=1 for CH2):

```
RQ  = (D<ONTH) & (Q<0.5) & (arm>0.5) & (off>BOFF) & (OK>0.5)
R   = RQ & (OQ<0.5) & (OA<0.5)
SET1 = R1
SET2 = R2 & !( RQ1 & (Q1<0.5) & (A1<0.5) )     // CH1 wins an exact solver-time tie
A'   = (Q>0.5) ? hold : ( SET ? set : reset )
ton' = R ? +1 us/us : reset
Q'   = set when (A>0.5) & (ton>TON); reset when toff>TOFF
```

The tie-break is deterministic and documented, not a 1 ns analog race. The arbitration
resolution is one solver timestep; unambiguous ordering was tested at 5 ns and 50 ns.

### 4.2 Off-blank (requirement 2)

v2 anchored the timer on a persistent `armstate` level and never restarted it on a new
VD>1.5 crossing:

```
Ba:  armstate = Q>0.5 ? reset : (D>ARM ? set : hold)
Btarm: tarm = armstate ? +1 us/us : reset
req: ... tarm>BOFF ...
```

v3 anchors at the actual turn-off event, with the first cycle anchored at the first ARM:

```
arm' = (Q>0.5) ? reset : (D>ARM ? set : hold)
off' = (Q>0.5) ? reset : ( arm>0.5 ? +1 us/us : reset )
RQ   = ... & (off>BOFF) ...
```

Both `arm` and `off` are reset by `Q` itself, so the 650 ns starts at
`max(Q falling edge, VD>ARM crossing)`:

- **Slow drain rise** (the realistic case): VD crosses 1.5 V only after the TOFF commit
  has fallen the gate, so the start is the VD>ARM crossing -- exactly the datasheet
  anchor "after its drain voltage rises above 1.5 V".
- **Fast drain rise**: the ARM crossing occurs while the gate is still on and both
  latches are reset, so the start is the Q falling edge, 20-140 ns after the VD anchor.
  Starting later lengthens the block, so this branch is conservative; it never unblocks
  earlier than the datasheet.

An earlier comment here claimed the turn-off anchor was "earlier than, hence
conservative" -- the direction was backwards; an early start ends the block early, which
is anti-conservative. Measured in §2 C14/C15. `age>BON` was **kept**: the audit confirms
it is the 475 ns on-blank (`tONMIN`) required by SLUSD48C 8.3.4.1, not an off-blank defect.

### 4.3 On-blank (requirement 3)

Both versions use `age>BON`, but v3 makes the reference explicit and tests it:

```
age' = (Q>0.5) ? +1 us/us : reset
off_command = (Q>0.5) & (age>BON) & (D>OFFTH)
toff' = (Q>0.5) & (age>BON) & (D>OFFTH | toff already started) ? +1 us/us : reset
Q' = reset when toff>TOFF
```

`age` is reset only by Q, so a VD crossing inside the blank cannot extend it or consume the
next pulse's blank. Reference point is the Q assertion (gate command); the gate 10-90 % edge
adds the driver delay (unchanged from v2, see limits).

### 4.4 Short pulses and blocked pulses (requirement 4)

v2:

```
Bton: ton = req ? +1 us/us : reset          // req ignores OTHER
```

v3:

```
R   = RQ & (OQ<0.5) & (OA<0.5)
ton' = R ? +1 us/us : reset
```

A pulse shorter than `TON` drops `RQ` and resets `ton` (filtered). A pulse that arrives while
the other channel owns the cycle has `R=0`, so its timer resets instead of accumulating
(rejected, not queued).

### 4.5 Pre-arm (requirement 5)

v2:

```
Bpre: REG<1 -> reset; 1<REG<4.5 & max(D)>ARM -> set; else hold
Bok: ok = PRE & uv
```

v3:

```
pl   = (0.1<REG<4.1) & (max(D1,D2)>ARM)         // 4.1 = VREGON(min)
PRE' = REG<0.05 ? reset : (pl ? set : hold)      // 0.05 = power-cycle reset
uv'  = REG>4.5 ? set : (REG<4.0 ? reset : hold)
viol'= REG<0.05 ? reset : (REG>4.1 & PRE<0.5 ? set : hold)
ok   = PRE & uv & !viol
```

The upper window edge uses the guaranteed earliest REG turn-on (4.1 V), not the 4.5 V typ.
The undocumented 1 V floor is removed. A REG-first order latches `viol` and blocks both gates;
a REG power cycle (below 50 mV) clears `PRE` and `viol`. This is a conservative modelling
choice to keep the documented condition testable; it is **not** a claim that physical silicon
latches off forever.

## 5. Model limits (unchanged from v2 unless stated)

- PGD law is still the uncalibrated v2 smooth law (`limit(3+(-D-0.035)*80,2.6,10.9)`);
  do not use `PGD=1` results for device selection or sign-off.
- Gate driver is still the v2 8.7 ohm source / 3.1 ohm sink RC with 6.7 nF; the measured
  10-90 % edges remain about 128 ns / 46 ns, slower than the datasheet 23/35 ns typ. This
  shifts absolute edge times by ~10-12 ns but does not change the state-machine verdicts.
- Not implemented: adaptive 155/275 ns turn-on delay, standby mode, VSS 330 uA offset,
  275 ns tMGPU + 200 uA hold, min/max threshold corners.
- The off-blank starts at `max(Q falling edge, VD>ARM crossing)`. In the fast-rise case
  that is later than the datasheet's "after VD>1.5 V" anchor, so the model blocks at
  least as long; in the slow-rise case it is the anchor itself. It is never earlier.
- Arbitration resolution is one solver timestep; exact ties go to CH1 by construction.

## 6. Numerical notes on the measurement aids

- `pulses1/2` are an edge integral (`ddt` of the gate>2 V indicator, integrated on a 1 uF
  capacitor). Each real gate edge contributes about 0.93-0.95 V, not exactly 1.0 V, because
  `ddt` is numerical. A value of exactly `0` means no edge and is used for the false-pulse
  checks (`early_false_pulses`, `retrig_false_pulses`, `loser_false_pulses`). Positive pulse
  counts are cross-checked with explicit `RISE=n` timing measurements.
- `overlap_width_us` integrates `(g1>2 V) AND (g2>2 V)` with 1 mA into 1 nF, giving
  microseconds of overlap directly; measured 0 in every v3 deck.

## 7. Reproduction

```
cd "D:/workshop/design_48v-2v"
for d in normal simultaneous skew shortpulse offblank_retrigger onblank interlock \
         reg_first_negative fastreg20 fastreg5 noarb_negative; do
  f=sim/v2/sr_timing_v3_checks_$d
  rm -f "$f.log" "$f.raw"
  timeout 180 "D:/ADI/LTspice/LTspice.exe" -b "$f.cir"
done
# Off-blank anchor pair (C14/C15), written directly in sim/v2:
for f in sim/v2/verify_offblank_boundary sim/v2/verify_offblank_delayed_arm; do
  rm -f "$f.log" "$f.raw"
  timeout 180 "D:/ADI/LTspice/LTspice.exe" -b "$f.cir"
done
```

## 8. Log verification performed

For the eleven v3 check decks (C1-C11) and the two off-blank anchor decks (C14/C15):

- `.log` exists and contains `Total elapsed time`.
- No line contains `Error:`, `Time step too small`, `Singular matrix`, `Analysis failed`,
  `Voltage not found`, `Measurement failed`.
- Every `.meas` name declared in the `.cir` appears as `name:` in the `.log` with a numeric
  value (15, 16, 11, 6, 8, 11, 8, 6, 5, 5, 5, 18 and 10 measurements respectively; all
  present).
- C14's `g1r2`/`g1f2` print `failed` for TD=4.7/4.8/4.9 us. That is the measured absence of
  a second gate edge, i.e. the expected rejection of a request inside the blank, and is
  recorded as such -- not a solver or measurement error.

C13 (`v2qrace_diag`) is the one deck that intentionally contains `Time step too small`; it is
recorded as the v2 deficiency evidence, not as a v3 PASS.
