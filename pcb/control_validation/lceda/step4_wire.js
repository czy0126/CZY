const ids = (await eda.sch_PrimitiveComponent.getAll()).filter((c) => c.getState_Designator());
const wires = [];
for (const c of ids) {
    const ref = c.getState_Designator();
    const pins = await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(c.getState_PrimitiveId());
    for (const p of pins) {
        const net = ref === 'RT1' ? (p.pinNumber === '1' ? 'TN_A' : 'TN_COM')
                                  : (p.pinNumber === '1' ? 'TN_B' : 'TN_COM');
        wires.push([p.x, p.y, p.x + 20, p.y, net]);
    }
}
await Promise.all(wires.map((w) => eda.sch_PrimitiveWire.create([w[0], w[1], w[2], w[3]], w[4])));
return { made: wires.length, nets: wires.map((w) => w[4]) };
