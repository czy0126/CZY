const LIB = '0819f05c4eef4c71ace90d822a990e87';
const R1K = { libraryType: '3', libraryUuid: LIB, uuid: '18db11499a04403ba8c98e2f7a687fbc' };
const placed = [];
for (const [ref, x, y] of [['LT1', 200, 200], ['LT2', 200, 300]]) {
    const c = await eda.sch_PrimitiveComponent.create(R1K, x, y, undefined, 0, false, true, true);
    const id = c.getState_PrimitiveId();
    const cur = await eda.sch_PrimitiveComponent.get(id);
    const pre = cur.getState_OtherProperty();
    await eda.sch_PrimitiveComponent.modify(id, { designator: ref, otherProperty: pre });
    const pins = await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(id);
    placed.push({ ref, id, pins: pins.map((p) => ({ n: p.pinNumber, x: p.x, y: p.y })) });
}
const labels = [];
for (const p of placed) {
    for (const pin of p.pins) {
        const net = p.ref === 'LT1' ? (pin.n === '1' ? 'LA' : 'LCOM') : (pin.n === '1' ? 'LB' : 'LCOM');
        const lbl = await eda.sch_PrimitiveAttribute.createNetLabel(pin.x, pin.y, net);
        labels.push({ ref: p.ref, pin: pin.n, x: pin.x, y: pin.y, net, ok: !!lbl });
    }
}
return { placed, labels };
