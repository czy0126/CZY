```spice
* 48V->2V fixed-ratio DCX power stage, LTspice netlist
* Power-stage validation only. Vin ramp is an excitation, not chip soft-start.
.options plotwinsize=0
.tran 0 3m 0 30n
.model DSR D(Ron=1.5m Roff=1G Vfwd=0.02)
.model DSW D(Ron=8m Roff=1G Vfwd=0.7)

* Control reference: PH/PL are independent logic inputs referred to PGND.
VPH PH 0 PULSE(0 5 5u 10n 10n 1.15u 2.5u)
VPL PL 0 PULSE(0 5 1.399u 10n 10n 1.15u 2.5u)

* Input ramp, 0 to 48 V in 0.5 ms
Vin vin_src 0 PWL(0 0 0.5m 48 3m 48)
Rvin vin_src vin 1m

* Half-bridge: voltage-controlled switches with body diodes
* QH: vin to sw
Bqh sw PH vin_src 0 VSW
.model VSW SW(Ron=8m Roff=1G Vt=2.5 Vh=0.5)
Dqh_bd 0 sw DSW
* QL: sw to PGND
Bql sw PL 0 0 VSW
Dql_bd 0 sw DSW

* Resonant tank: Lr + Cr + total Lm (four series primaries)
Lr sw n_lr 1u Rser=1m
Cr n_lr n_cr 620n Rser=0.5m
* Magnetizing inductance, total 40u, split as four 10u units
Lm1 n_cr n_p2 10u
Lm2 n_p2 n_p3 10u
Lm3 n_p3 n_p4 10u
Lm4 n_p4 pgnd_ref 10u
Rpgnd_ref pgnd_ref 0 1m

* Four coupled magnetic elements, 3:1:1, primaries series
* Ideal K=1 model. Each secondary half is 10u/9.
* Unit 1
Lp1 n_cr n_p1a 10u Rser=3m
Lsa1 n_a1 out1 1.111111u Rser=0.15m
Lsb1 out1 n_b1 1.111111u Rser=0.15m
K1 Lp1 Lsa1 1
K2 Lp1 Lsb1 1
K3 Lsa1 Lsb1 1
* Unit 2
Lp2 n_p2 n_p2a 10u Rser=3m
Lsa2 n_a2 out2 1.111111u Rser=0.15m
Lsb2 out2 n_b2 1.111111u Rser=0.15m
K4 Lp2 Lsa2 1
K5 Lp2 Lsb2 1
K6 Lsa2 Lsb2 1
* Unit 3
Lp3 n_p3 n_p3a 10u Rser=3m
Lsa3 n_a3 out3 1.111111u Rser=0.15m
Lsb3 out3 n_b3 1.111111u Rser=0.15m
K7 Lp3 Lsa3 1
K8 Lp3 Lsb3 1
K9 Lsa3 Lsb3 1
* Unit 4
Lp4 n_p4 n_p4a 10u Rser=3m
Lsa4 n_a4 out4 1.111111u Rser=0.15m
Lsb4 out4 n_b4 1.111111u Rser=0.15m
K10 Lp4 Lsa4 1
K11 Lp4 Lsb4 1
K12 Lsa4 Lsb4 1

* Primaries return to PGND; intermediate nodes connect the four series units.
Rpa1 n_p1a n_cr 1u
Rpa2 n_p2a n_p3 1u
Rpa3 n_p3a n_p4 1u
Rpa4 n_p4a 0 1u

* Secondary rectifiers: low-side ideal-diode SR equivalents.
* a-end: SGND to a (conducts when a is below SGND)
* b-end: SGND to b (conducts when b is below SGND)
* These are NOT UCC24624 models.
Da1 sgnd n_a1 DSR
Db1 sgnd n_b1 DSR
Da2 sgnd n_a2 DSR
Db2 sgnd n_b2 DSR
Da3 sgnd n_a3 DSR
Db3 sgnd n_b3 DSR
Da4 sgnd n_a4 DSR
Db4 sgnd n_b4 DSR

* Secondary series inductances, out-a and b-out with defined polarity
Lsa_out out n_a1 1n Rser=0
Lsa2_out n_a1 n_a2 1n Rser=0
Lsa3_out n_a2 n_a3 1n Rser=0
Lsa4_out n_a3 n_a4 1n Rser=0
Lsb_out n_b1 out 1n Rser=0
Lsb2_out n_b2 n_b1 1n Rser=0
Lsb3_out n_b3 n_b2 1n Rser=0
Lsb4_out n_b4 n_b3 1n Rser=0

* Output capacitor and load
Cout out sgnd 4m Rser=0.2m
Rload out sgnd 20m

* SGND to PGND: 1G numerical reference only
Rref sgnd 0 1G

* Measurements
.meas TRAN Vout_avg AVG V(out,sgnd) FROM 2.5m TO 3m
.meas TRAN Vout_ripple PP V(out,sgnd) FROM 2.5m TO 3m
.meas TRAN IpRMS RMS I(Lr) FROM 2.5m TO 3m
.meas TRAN Ip_peak MAX I(Lr) FROM 2.5m TO 3m
.meas TRAN Irms_Lsa1 RMS I(Lsa1) FROM 2.5m TO 3m
.meas TRAN Irms_Lsb1 RMS I(Lsb1) FROM 2.5m TO 3m
.meas TRAN Irms_Lsa2 RMS I(Lsa2) FROM 2.5m TO 3m
.meas TRAN Irms_Lsb2 RMS I(Lsb2) FROM 2.5m TO 3m
.meas TRAN Irms_Lsa3 RMS I(Lsa3) FROM 2.5m TO 3m
.meas TRAN Irms_Lsb3 RMS I(Lsb3) FROM 2.5m TO 3m
.meas TRAN Irms_Lsa4 RMS I(Lsa4) FROM 2.5m TO 3m
.meas TRAN Irms_Lsb4 RMS I(Lsb4) FROM 2.5m TO 3m

.save V(out,sgnd) I(Lr) I(Lsa1) I(Lsb1) I(Lsa2) I(Lsb2) I(Lsa3) I(Lsb3) I(Lsa4) I(Lsb4) V(sw) V(PH) V(PL)
.end
```