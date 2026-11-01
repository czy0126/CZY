const LIB = '0819f05c4eef4c71ace90d822a990e87';
const R1K = { libraryType: '3', libraryUuid: LIB, uuid: '18db11499a04403ba8c98e2f7a687fbc' };
await eda.dmt_EditorControl.openDocument('54b490e62c25b8cb');
await new Promise((r) => setTimeout(r, 2500));
const placed = [];
for (const [ref, x, y] of [['RT1', 100, 100], ['RT2', 100, 160]]) {
    const c = await eda.sch_PrimitiveComponent.create(R1K, x, y, undefined, 0, false, true, true);
    const id = c.getState_PrimitiveId();
    const pre = (await eda.sch_PrimitiveComponent.get(id)).getState_OtherProperty();
    await eda.sch_PrimitiveComponent.modify(id, { designator: ref, otherProperty: pre });
    const pins = await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(id);
    placed.push({ ref, id, pins: pins.map((p) => ({ n: p.pinNumber, x: p.x, y: p.y })) });
}
// stub each pin with a named net
for (const p of placed) {
    for (const pin of p.pins) {
        const net = p.ref === 'RT1' ? (pin.n === '1' ? 'TN_A' : 'TN_COM') : (pin.n === '1' ? 'TN_B' : 'TN_COM');
        await eda.sch_PrimitiveWire.create([pin.x, pin.y, pin.x + 20, pin.y], net);
    }
}
const nl = await eda.sch_Netlist.getNetlist();
return { placed, netlist: String(nl).slice(0, 1200) };
