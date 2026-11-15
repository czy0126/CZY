# G0 V7 48V NC EStop+manual re-arm — INCOMPLETE NATIVE KICAD

Open the same stem .kicad_pro in KiCad 10. The real 48V coil supply path uses VIN48_AUX → F_COIL → external NC EStop contact A (J_ESTOP_PWR) → external GX14FAC coil positive (J_GX14COIL.1); coil negative → Infineon IRL540N Drain; Source→PGND. The NC contact is OPEN until wired by qualified staff and cannot be bypassed by firmware. Sensata GX14 includes internal transorb: DO NOT add external flyback diode.

Independent source-authored SCH has CD4081 quad AND, CD4013 asynchronous reset latch, 2nd NC EStop contact B, UVLO_P_OK, UVLO_S_PRIMARY_OK, independent HS_OK, and a manual momentary NO ARM. Any fault resets the latch; on recovery another rising ARM pulse is needed. This is a CAD logic candidate, not a certified safety relay.

CRITICAL: THE PCB HAS SIGNAL NETS UNROUTED. Read V7_KICAD_INTERLOCK_INCOMPLETE_NOT_FOR_FAB_ACCEPTANCE.json for exact native KiCad unconnected count and ignored checks. NO GERBER, NO PRODUCTION, NO HARDWARE POWER! External contactor, physical two-channel NC EStop switch, actual HS monitor, fault injection and contact/welded-pole detection have NOT been built or tested. R8 on V5 power board remains DNP. All G0 nine physical witnesses pending.
