const queries = ['RC0603FR-0710RL', 'CL10B102KB8NNNC', 'CL10B682KB8NNNC'];
const out = {};
for (const q of queries) {
    try {
        const items = await eda.lib_Device.search(q);
        out[q] = items.slice(0, 3).map((d) => ({ name: d.name, uuid: d.uuid,
            lcsc: d.supplierId, footprint: d.footprintName || d.footprint || null }));
    } catch (e) { out[q] = String(e); }
}
return out;
