const NET = {
    U1: { VG1: 'VG1', PGND: 'PGND', REG: 'REG', VD1: 'VD1', VSS: 'VSS', VD2: 'VD2', VDD: 'VDD', VG2: 'VG2' },
    Q1: { S: 'SR_SRC', G: 'G1', D: 'SEC_A' }, Q2: { S: 'SR_SRC', G: 'G2', D: 'SEC_B' },
    Q4: { G: 'REG_HOLD', S: 'PGND', D: 'REG' },
    D1: { K: 'VIN_F', A: 'PGND' }, D2: { K: 'VDD', A: 'VIN_F' },
    J1: { '1': 'VBIAS', '2': 'PGND' }, J2: { '1': 'VOUT', '2': 'PGND' },
    J3: { '1': 'SEC_A', '2': 'VOUT', '3': 'SEC_B', '4': 'PGND' },
    JP1: { '1': 'FORCE1', '2': 'PGND' }, JP2: { '1': 'FORCE2', '2': 'PGND' },
    F1: { '1': 'VBIAS', '2': 'VIN_F' },
    C1: { '1': 'VDD', '2': 'PGND' }, C2: { '1': 'VDD', '2': 'PGND' }, C3: { '1': 'VDD', '2': 'PGND' },
    C4: { '1': 'REG', '2': 'PGND' }, C5: { '1': 'REG', '2': 'PGND' },
    C6: { '1': 'VOUT', '2': 'PGND' }, C7: { '1': 'VOUT', '2': 'PGND' },
    R1: { '1': 'VSS', '2': 'SR_SRC' }, R2: { '1': 'VD1', '2': 'SEC_A' }, R3: { '1': 'VD2', '2': 'SEC_B' },
    R4: { '1': 'REG_HOLD', '2': 'PGND' }, R5: { '1': 'FORCE1', '2': 'VD1' }, R6: { '1': 'FORCE2', '2': 'VD2' },
    Rg1: { '1': 'VG1', '2': 'G1' }, Rg2: { '1': 'VG2', '2': 'G2' },
    Rgs1: { '1': 'G1', '2': 'SR_SRC' }, Rgs2: { '1': 'G2', '2': 'SR_SRC' },
    Rsh1: { '1': 'SR_SRC', '2': 'PGND' }, Rsh2: { '1': 'SR_SRC', '2': 'PGND' },
    Rsn1: { '1': 'SEC_A', '2': 'SN1' }, Csn1: { '1': 'SN1', '2': 'SR_SRC' },
    Rsn2: { '1': 'SEC_B', '2': 'SN2' }, Csn2: { '1': 'SN2', '2': 'SR_SRC' },
    CGL1: { '1': 'G1', '2': 'SR_SRC' }, CGL2: { '1': 'G2', '2': 'SR_SRC' },
    TP1: { '1': 'VDD' }, TP2: { '1': 'REG' }, TP3: { '1': 'VSS' }, TP4: { '1': 'VD1' },
    TP5: { '1': 'VD2' }, TP6: { '1': 'VG1' }, TP7: { '1': 'VG2' }, TP8: { '1': 'PGND' },
    TP9: { '1': 'SR_SRC' }, TP10: { '1': 'PGND' }, TP11: { '1': 'VOUT' }, TP12: { '1': 'PGND' }
};
const out = [];
for (const c of await eda.sch_PrimitiveComponent.getAll()) {
    const ref = c.getState_Designator();
    if (!ref || !NET[ref]) continue;
    const x0 = c.getState_X ? c.getState_X() : null;
    const y0 = c.getState_Y ? c.getState_Y() : null;
    const pins = await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(c.getState_PrimitiveId());
    const seen = new Set();
    for (const p of pins) {
        const num = p.getState_PinNumber(), name = p.getState_PinName();
        let net = NET[ref][num] !== undefined ? NET[ref][num] : NET[ref][name];
        if (net === undefined) { out.push({ ref, err: 'no net', num, name }); continue; }
        const key = p.x + ',' + p.y;
        if (seen.has(key)) continue;
        seen.add(key);
        const dx = p.x - (x0 === null ? p.x : x0);
        const dy = p.y - (y0 === null ? p.y : y0);
        let ex = p.x, ey = p.y;
        if (Math.abs(dx) >= Math.abs(dy)) ex = p.x + (dx < 0 ? -20 : 20);
        else ey = p.y + (dy < 0 ? -20 : 20);
        const w = await eda.sch_PrimitiveWire.create([p.x, p.y, ex, ey], net);
        out.push({ ref, pin: num, name, net, ok: !!w });
    }
}
return out.filter((r) => r.err || !r.ok).length ? out.filter((r) => r.err || !r.ok) : { allOk: true, count: out.length };
