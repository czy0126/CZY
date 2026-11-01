const comps = (await eda.sch_PrimitiveComponent.getAll()).filter((c) => c.getState_Designator());
const jobs = [];
for (const c of comps) {
    const ref = c.getState_Designator();
    const pins = await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(c.getState_PrimitiveId());
    for (const p of pins) {
        const net = ref === 'LT1' ? (p.pinNumber === '1' ? 'LA' : 'LCOM')
                                  : (p.pinNumber === '1' ? 'LB' : 'LCOM');
        const dx = p.x < 200 ? -20 : 20;
        jobs.push({ ref, pin: p.pinNumber, x: p.x, y: p.y, net, line: [p.x, p.y, p.x + dx, p.y] });
    }
}
const made = [];
for (const j of jobs) {
    const w = await eda.sch_PrimitiveWire.create(j.line, j.net);
    made.push({ ...j, id: w ? w.getState_PrimitiveId() : null });
}
return made;
