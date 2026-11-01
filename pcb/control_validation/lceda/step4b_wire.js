const out = [];
for (const [label, args] of [
    ['flat', [[100, 100, 120, 100]]],
    ['pairs', [[[100, 100], [120, 100]]]],
    ['flat_net', [[100, 100, 120, 100], 'TN_X']],
    ['pairs_net', [[[100, 100], [120, 100]], 'TN_Y']]
]) {
    try {
        const w = await eda.sch_PrimitiveWire.create(...args);
        out.push({ label, ok: true, id: w ? w.getState_PrimitiveId() : null });
    } catch (e) {
        out.push({ label, ok: false, err: String(e && e.message ? e.message : e) });
    }
}
return out;
